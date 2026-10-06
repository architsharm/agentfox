"""Policy persistence and binding resolution (P6-1).

Two invariants live here:

* **Versions are immutable.** Saving a changed body creates version *n+1*; it never
  rewrites *n*. Decisions reference the version id, so history stays truthful even
  after the policy is edited (Appendix E.1.5 — "that rule was always on").
* **Bindings carry the mode.** A policy version bound in ``observe`` records what it
  *would* have done; the same version bound in ``enforce`` blocks. Promotion between
  the two is an explicit, audited act (PRD R3).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import Agent, Policy, PolicyBinding, PolicyVersion, utcnow
from agentfox.policy.canary import active_canary, pick_version_id
from agentfox.policy.engine import NativePolicyEngine, PolicyEngine
from agentfox.policy.hierarchy import (
    EffectivePolicy,
    PolicyLayer,
    lint_policy,
    lint_summary,
    resolve_effective,
)
from agentfox.policy.model import PolicyDocument
from agentfox.policy.opa import OpaPolicyEngine


def get_engine(name: str | None = None) -> PolicyEngine:
    choice = name or get_settings().policy_engine
    if choice == "opa":
        engine = OpaPolicyEngine()
        if engine.available():
            return engine
        # Deliberate: an unreachable sidecar must not silently disable policy.
        return NativePolicyEngine()
    return NativePolicyEngine()


#: Where a project keeps policy packs of its own, relative to the working
#: directory — the same convention `agentfox.toml` already uses.
#:
#: This is the distribution mechanism, and it is deliberately git rather than a
#: hub. A competitor ships `policies add <owner>/<repo>`, which is a real
#: advantage over three files baked into a wheel; but it also means the
#: governance product reaches the network to fetch the rules it will enforce,
#: on a deployment whose whole argument is that it does not reach the network.
#: A directory in the repository gets the same result — a team's policies
#: travel with the code, arrive by `git pull`, and are reviewed in a pull
#: request like everything else — and the fetch stays where it belongs, with
#: the operator and their existing supply-chain controls.
PROJECT_POLICY_DIR = Path(".agentfox") / "policies"


class PolicyPackError(RuntimeError):
    """A pack on disk could not be read, named by file.

    Without this a typo in somebody's own pack surfaces as a pydantic
    `ValidationError` traceback with no filename in it, and the operator is
    left diffing three YAML files to find which one. The underlying message is
    kept — it is usually exact — and the path is put in front of it.
    """

    def __init__(self, path: Path, cause: Exception) -> None:
        detail = " ".join(str(cause).split())
        super().__init__(f"{path}: {detail}")
        self.path = path
        self.cause = cause


def _read_pack(path: Path) -> PolicyDocument:
    try:
        return PolicyDocument.from_yaml(path.read_text())
    except Exception as exc:
        raise PolicyPackError(path, exc) from exc


def project_policy_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / PROJECT_POLICY_DIR


def load_from_dir(directory: Path | None = None) -> list[PolicyDocument]:
    directory = directory or get_settings().policies_dir
    out: list[PolicyDocument] = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.y*ml")):
        out.append(_read_pack(path))
    return out


def load_available(root: Path | None = None) -> list[PolicyDocument]:
    """Every pack this deployment can bind: the shipped ones, then the project's.

    A project pack with the same key as a shipped one REPLACES it, and that is
    the point — overriding `baseline` for your own deployment is the ordinary
    reason to write one. Replacement rather than merge because a half-merged
    policy is a policy nobody can predict, and `PolicyDocument`'s own
    protected-rule check still applies to whatever replaces it, so a project
    cannot quietly drop `control_plane.tamper` by shipping a thinner
    `tool-containment`.
    """
    shipped = {doc.key: doc for doc in load_from_dir()}
    for doc in load_from_dir(project_policy_dir(root)):
        shipped[doc.key] = doc
    return list(shipped.values())


def pack_sources(root: Path | None = None) -> list[dict[str, str]]:
    """Where each loadable pack came from, for `agentfox policy packs`.

    Provenance is the question an operator actually has about a policy they did
    not write, and "which file is this rule in" is not answerable from
    `policy list`, which reads the database.
    """
    rows: list[dict[str, str]] = []
    seen: dict[str, int] = {}
    for origin, directory in (
        ("shipped", get_settings().policies_dir),
        ("project", project_policy_dir(root)),
    ):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.y*ml")):
            doc = _read_pack(path)
            row = {
                "key": doc.key,
                "origin": origin,
                "path": str(path),
                "mode": doc.mode,
                "rules": str(len(doc.rules)),
                "overrides": "",
            }
            if doc.key in seen:
                row["overrides"] = rows[seen[doc.key]]["path"]
            seen[doc.key] = len(rows)
            rows.append(row)
    return rows


def _currently_bound(session: Session) -> list[PolicyBinding]:
    """Every binding active right now — the same effective_from/effective_to window
    check `active_layers` and `active_policies` both need."""
    now = utcnow()
    return list(
        session.scalars(
            select(PolicyBinding).where(
                PolicyBinding.effective_from <= now,
                (PolicyBinding.effective_to.is_(None)) | (PolicyBinding.effective_to > now),
            )
        )
    )


def _open_binding_for_version(session: Session, version_id: str) -> PolicyBinding | None:
    """The still-open (not yet closed) binding for one policy version, if any —
    shared by `save_policy` and `set_mode`, both of which need to find or replace it."""
    return session.scalar(
        select(PolicyBinding).where(
            PolicyBinding.policy_version_id == version_id,
            PolicyBinding.effective_to.is_(None),
        )
    )


@dataclass
class BoundLayer:
    """One live binding, as a hierarchy layer, with the rows it came from."""

    layer: PolicyLayer
    version: PolicyVersion
    binding: PolicyBinding


def _bound_layers(
    session: Session,
    agent_slug: str | None = None,
    environment: str | None = None,
    *,
    scoped: bool = True,
    pick_canary: bool = False,
) -> list[BoundLayer]:
    """Every live binding as a layer: the one place bindings become documents.

    `active_layers` (for `policy effective` / `policy lint`), `active_policies` (the
    inventory) and `policies_in_force` (the runtime) all read through here, so the
    three can never disagree about which version a binding means or what mode it
    is in.

    ``pick_canary`` routes a request to the canary candidate when one is rolling
    (P12-6): a running canary splits live traffic between the bound (stable)
    version and a candidate by percentage, per request. `active_canary` only
    returns a hit when the binding still points at the canary's own recorded stable
    version, so a binding that moved out from under a stale canary (e.g. someone
    edited the policy directly) is never silently overridden.
    """
    out: list[BoundLayer] = []
    for binding in _currently_bound(session):
        version = session.get(PolicyVersion, binding.policy_version_id)
        if version is None:
            continue
        if pick_canary:
            canary = active_canary(session, version.policy_id)
            if canary is not None and canary.stable_version_id == version.id:
                picked_id = pick_version_id(canary)
                if picked_id != version.id:
                    candidate_version = session.get(PolicyVersion, picked_id)
                    if candidate_version is not None:
                        version = candidate_version
        doc = PolicyDocument.model_validate(version.compiled_json or yaml.safe_load(version.body))
        doc.scope = binding.scope_json or doc.scope
        if scoped and not doc.matches_scope(agent_slug, environment):
            continue
        doc.mode = binding.mode  # the binding, not the document, decides enforcement
        out.append(
            BoundLayer(
                layer=PolicyLayer(
                    document=doc,
                    level=binding.level or "org",
                    scope_id=binding.scope_id or "*",
                    mode=binding.compose or "extend",
                ),
                version=version,
                binding=binding,
            )
        )
    return out


def active_layers(session: Session, subject: dict[str, str] | None = None) -> list[PolicyLayer]:
    """Every bound policy version, as hierarchy layers (P12)."""
    if subject is None:
        return [b.layer for b in _bound_layers(session, scoped=False)]
    return [
        b.layer for b in _bound_layers(session, subject.get("agent"), subject.get("environment"))
    ]


def _subject(
    agent_slug: str | None,
    environment: str | None,
    team: str | None,
    user: str | None,
    org: str | None,
) -> dict[str, str]:
    return {
        "org": org or get_settings().org_id,
        "team": team or "*",
        "agent": agent_slug or "*",
        "user": user or "*",
        "environment": environment or "*",
    }


def effective_for(
    session: Session,
    agent_slug: str | None = None,
    environment: str | None = None,
    team: str | None = None,
    user: str | None = None,
    org: str | None = None,
) -> EffectivePolicy:
    """Resolve the policy actually in force for a subject, with provenance.

    ``team`` defaults to the agent's registered ``owner_team`` — the same team the
    runtime resolves for it — so `policy effective --agent X` shows what X gets.
    """
    if team is None and agent_slug:
        team = agent_team(session, agent_slug)
    subject = _subject(agent_slug, environment, team, user, org)
    return resolve_effective(active_layers(session, subject), subject)


def agent_team(session: Session, agent_slug: str | None) -> str | None:
    """The team an agent belongs to, for the `team` level of the hierarchy.

    Team membership is `Agent.owner_team` (set by `agents register --owner-team`,
    the registry API, or seed). An agent with no owner team belongs to no team, so
    only `team` layers scoped to `*` apply to it.
    """
    if not agent_slug:
        return None
    return session.scalar(
        select(Agent.owner_team).where(Agent.slug == agent_slug).order_by(Agent.created_at)
    )


def policies_in_force(
    session: Session,
    agent_slug: str | None = None,
    environment: str | None = None,
    team: str | None = None,
    user: str | None = None,
    org: str | None = None,
) -> list[tuple[PolicyDocument, PolicyVersion, PolicyBinding]]:
    """What the runtime evaluates for one subject: the hierarchy, resolved (P12).

    The same `resolve_effective` that `policy effective` prints decides this, so the
    command shows what the enforcer does. Per layer that means:

    * a layer whose level/scope does not cover the subject is skipped — a team's
      `restrict` applies to that team's agents only;
    * a rule rejected as an illegal loosening is dropped (the broader rule stands);
    * a rule replaced by a granted `override` is dropped, so the override loosens;
    * a rule a narrower layer tightened stays in force beside the tighter one.

    Each pack is returned with only its rules in force, still under its own binding
    mode, so observe packs keep recording and enforce packs keep blocking.

    ``team`` defaults to the agent's ``owner_team``. ``user`` is only known when the
    caller supplies it; without it, `user` layers scoped to a specific user do not
    apply (a `user` layer scoped to `*` does).
    """
    if team is None and agent_slug:
        team = agent_team(session, agent_slug)
    bound = _bound_layers(session, agent_slug, environment, pick_canary=True)
    subject = _subject(agent_slug, environment, team, user, org)
    effective = resolve_effective([b.layer for b in bound], subject)
    applicable = {id(layer) for layer in effective.applicable}
    out = []
    for b in bound:
        if id(b.layer) not in applicable:
            continue
        doc = b.layer.document.model_copy()
        doc.rules = effective.rules_in_force(b.layer)
        out.append((doc, b.version, b.binding))
    return out


def lint_all(session: Session) -> dict:
    """Lint every bound policy layer. Intended for CI (P12-4)."""
    return lint_summary(lint_policy(active_layers(session)))


def save_policy(
    session: Session,
    doc: PolicyDocument,
    author: str = "system",
    notes: str = "",
    bind_mode: str | None = None,
    level: str = "org",
    scope_id: str = "*",
    compose: str = "extend",
) -> tuple[Policy, PolicyVersion]:
    """Upsert a policy and append an immutable version."""
    policy = session.scalar(select(Policy).where(Policy.key == doc.key))
    if policy is None:
        policy = Policy(key=doc.key, name=doc.name or doc.key, description=doc.description)
        session.add(policy)
        session.flush()

    body = doc.to_yaml()
    latest = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version.desc())
    ).first()

    body_unchanged = latest is not None and latest.body == body
    if body_unchanged:
        version = latest  # no-op edit on the rules; do not manufacture a version
    else:
        version = PolicyVersion(
            policy_id=policy.id,
            version=(latest.version + 1) if latest else doc.version,
            body=body,
            compiled_json=doc.model_dump(),
            author=author,
            notes=notes,
        )
        session.add(version)
        session.flush()

    mode = bind_mode or doc.mode
    current_binding = _open_binding_for_version(session, version.id) if body_unchanged else None
    if (
        current_binding is not None
        and current_binding.mode == mode
        and current_binding.level == level
        and current_binding.scope_id == scope_id
        and current_binding.compose == compose
    ):
        return policy, version  # rules, mode, and hierarchy placement all unchanged

    _close_open_bindings(session, policy.id)
    session.add(
        PolicyBinding(
            policy_version_id=version.id,
            scope_json=doc.scope or {},
            mode=mode,
            level=level,
            scope_id=scope_id,
            compose=compose,
        )
    )
    session.flush()
    return policy, version


def _close_open_bindings(session: Session, policy_id: str) -> None:
    version_ids = [
        v.id
        for v in session.scalars(select(PolicyVersion).where(PolicyVersion.policy_id == policy_id))
    ]
    if not version_ids:
        return
    for binding in session.scalars(
        select(PolicyBinding).where(
            PolicyBinding.policy_version_id.in_(version_ids),
            PolicyBinding.effective_to.is_(None),
        )
    ):
        binding.effective_to = utcnow()


def active_policies(
    session: Session, agent_slug: str | None = None, environment: str | None = None
) -> list[tuple[PolicyDocument, PolicyVersion, PolicyBinding]]:
    """Every policy version currently bound and in (pack) scope, with its mode applied.

    The inventory: no hierarchy resolution, so a team-scoped layer is listed for
    everyone. What one request is actually evaluated against is
    :func:`policies_in_force`.
    """
    return [
        (b.layer.document, b.version, b.binding)
        for b in _bound_layers(session, agent_slug, environment, pick_canary=True)
    ]


def current_binding(
    session: Session, policy_id: str
) -> tuple[PolicyBinding, PolicyVersion] | tuple[None, None]:
    """The open binding for a policy, whichever version it points at.

    Not "the binding of the latest version": after a canary is started or rolled
    back, the live binding points at an *earlier* version than the newest one, and
    reading only the newest made the policy look unbound.
    """
    version_ids = {
        v.id: v
        for v in session.scalars(select(PolicyVersion).where(PolicyVersion.policy_id == policy_id))
    }
    if not version_ids:
        return None, None
    binding = session.scalars(
        select(PolicyBinding)
        .where(
            PolicyBinding.policy_version_id.in_(list(version_ids)),
            PolicyBinding.effective_to.is_(None),
        )
        .order_by(PolicyBinding.effective_from.desc())
    ).first()
    if binding is None:
        return None, None
    return binding, version_ids[binding.policy_version_id]


def set_mode(
    session: Session, policy_key: str, mode: str, version: int | None = None
) -> PolicyBinding | None:
    """Promote (or demote) a policy between observe and enforce.

    Changes the mode of the version that is *live* — the open binding — not of the
    newest version. After a canary rollback the newest version is the one that was
    rolled back; binding it here re-shipped exactly what the rollback removed and
    left the policy with two open bindings.

    ``version`` (a version number) makes that version the live one, in ``mode``,
    replacing the current binding but keeping its hierarchy placement. This is how
    a version saved from the editor goes live. With no binding at all, the newest
    version is bound.
    """
    policy = session.scalar(select(Policy).where(Policy.key == policy_key))
    if policy is None:
        return None
    binding, bound_version = current_binding(session, policy.id)

    target: PolicyVersion | None
    if version is not None:
        target = session.scalar(
            select(PolicyVersion).where(
                PolicyVersion.policy_id == policy.id, PolicyVersion.version == version
            )
        )
        if target is None:
            return None
    elif bound_version is not None:
        target = bound_version
    else:
        target = session.scalars(
            select(PolicyVersion)
            .where(PolicyVersion.policy_id == policy.id)
            .order_by(PolicyVersion.version.desc())
        ).first()
        if target is None:
            return None

    if binding is not None and binding.policy_version_id == target.id:
        binding.mode = mode
        session.flush()
        return binding

    placement = {
        "scope_json": binding.scope_json if binding is not None else {},
        "level": binding.level if binding is not None else "org",
        "scope_id": binding.scope_id if binding is not None else "*",
        "compose": binding.compose if binding is not None else "extend",
    }
    _close_open_bindings(session, policy.id)
    new_binding = PolicyBinding(policy_version_id=target.id, mode=mode, **placement)
    session.add(new_binding)
    session.flush()
    return new_binding


def history(session: Session, policy_key: str) -> list[dict]:
    policy = session.scalar(select(Policy).where(Policy.key == policy_key))
    if policy is None:
        return []
    versions = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version)
    ).all()
    return [
        {
            "id": v.id,
            "version": v.version,
            "author": v.author,
            "notes": v.notes,
            "created_at": v.created_at.isoformat()
            if isinstance(v.created_at, dt.datetime)
            else None,
            "rules": len((v.compiled_json or {}).get("rules", [])),
        }
        for v in versions
    ]
