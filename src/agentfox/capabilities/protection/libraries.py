"""Libraries: sets of rules applied together, and which one a rule belongs to.

A library is applied to chosen agents, the agents of one project: each gets its own
copy (`agent.<slug>.<library policy>`), bound to that agent alone, so a library on one
project never reaches another. Libraries applied before this, workspace-wide, still
count where they apply. The basic guardrails (one click after the first attack test)
are a library too, kept the same way (`agent.<slug>.basic`, built by
``onboarding.service.basic_document``), and the starter rules earlier versions of
`agentfox init` set up are one as well. A rule set for one agent by hand belongs to no
library.

A copy goes live like any policy: watching first, and blocking only through the gate
``POST /api/policies/{key}/mode`` keeps (a caller who may change production policy,
and a recorded simulation of exactly the rules being enforced, ``simulation_for``).
:func:`library_mode` keeps that gate for a library's copies and
:func:`simulate_library` records the simulations it asks for, with main's simulator.

Each version a library writes into a copy says where it came from in its notes
(``[from <library> <policy key> <hash of the shipped rules>]``), so a fix to a shipped
library shows as ``outdated`` on the copies made before it (:func:`library_status`),
and applying the library again brings them up to date in the mode they are in
(:func:`apply_library`, through ``publish_in_current_mode``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

BASIC = "Basic guardrails"
STARTER = "Starter rules (watch only)"
OWN = "Set for this agent"

#: The id the basic guardrails go by in the library routes.
BASIC_ID = "basic"

#: How far back a library's copies are replayed by :func:`simulate_library`; the
#: same default as ``POST /api/policies/simulate``.
SIMULATE_DAYS = 30

_FROM = re.compile(r"\[from (?P<library>[^\s\]]+) (?P<policy>[^\s\]]+) (?P<hash>[0-9a-f]{12})\]")


@lru_cache(maxsize=1)
def library_titles() -> dict[str, str]:
    """Policy key -> the title of the library that ships it."""
    from agentfox.platform.packs.loader import load_packs
    from agentfox.platform.policy import PolicyDocument

    titles: dict[str, str] = {}
    for pack in load_packs():
        for path in pack.files("policies"):
            try:
                key = PolicyDocument.from_yaml(path.read_text()).key
            except Exception:
                continue
            titles[key] = pack.manifest.title
    return titles


def agent_copy_key(slug: str, policy_key: str) -> str:
    """The key of one agent's copy of a library policy."""
    return f"agent.{slug}.{policy_key}"


def library_of(rule_id: str, policy_key: str, level: str, name: str = "") -> str:
    """The library a rule in force comes from, by the policy it lives in."""
    if rule_id.startswith("basic.") or policy_key.endswith(".basic"):
        return BASIC
    # An agent's copy of a library: agent.<slug>.<library policy key>.
    parts = policy_key.split(".", 2)
    if len(parts) == 3 and parts[0] == "agent" and parts[2] in library_titles():
        return library_titles()[parts[2]]
    if rule_id.startswith("watch."):
        return STARTER
    if level != "agent" and not policy_key.startswith("agent."):
        return library_titles().get(policy_key) or name or policy_key
    return OWN


def remove_starter(session: Any, *, actor: str, slugs: list[str] | None = None) -> list[str]:
    """Take the starter rules (``watch.*``) out of every agent's own layer, keeping
    anything else that layer holds. A new, audited version each; returns the agents."""
    from sqlalchemy import select

    from agentfox.capabilities.protection import own_layer
    from agentfox.core.models import Policy
    from agentfox.platform.policy.publish import publish_in_current_mode

    changed = []
    for key in session.scalars(select(Policy.key).where(Policy.key.like("agent.%"))):
        slug = key.removeprefix("agent.")
        if "." in slug or (slugs is not None and slug not in slugs):
            continue
        doc = own_layer(session, slug)
        keep = [r for r in doc.rules if not r.id.startswith("watch.")]
        if len(keep) == len(doc.rules):
            continue
        publish_in_current_mode(
            session,
            doc.model_copy(update={"rules": keep}),
            actor=actor,
            notes="starter rules removed",
            level="agent",
            scope_id=slug,
            agent_slug=slug,
        )
        changed.append(slug)
    return changed


# --- What a library is, and what an agent's copy of it should hold ------------------


def _library_docs(pack_id: str) -> tuple[str, list[Any]] | None:
    """A shipped library's title and policies; None when no loaded pack has this id
    (so ``pack_id`` can only ever name a shipped library, never any policy key)."""
    from agentfox.platform.packs.loader import load_packs
    from agentfox.platform.policy import PolicyDocument

    for pack in load_packs():
        if pack.id != pack_id:
            continue
        docs = []
        for path in pack.files("policies"):
            try:
                docs.append(PolicyDocument.from_yaml(path.read_text()))
            except Exception:
                continue
        return pack.manifest.title, docs
    return None


@dataclass
class Copy:
    """One agent's copy of one of a library's policies."""

    slug: str
    key: str
    #: The shipped policy it copies (for the basic guardrails, ``basic``).
    source: str
    #: What the copy should hold now: the shipped rules, under the copy's key.
    doc: Any


def is_library(pack_id: str) -> bool:
    return pack_id == BASIC_ID or _library_docs(pack_id) is not None


def library_title(pack_id: str) -> str | None:
    if pack_id == BASIC_ID:
        return BASIC
    found = _library_docs(pack_id)
    return found[0] if found else None


def copies(pack_id: str, slugs: list[str]) -> list[Copy] | None:
    """Each agent's copies of a library, as the library ships them now. None when
    there is no such library."""
    if pack_id == BASIC_ID:
        from agentfox.capabilities.onboarding.service import basic_document, basic_key

        return [Copy(s, basic_key(s), BASIC_ID, basic_document(s)) for s in slugs]
    found = _library_docs(pack_id)
    if found is None:
        return None
    title, docs = found
    out = []
    for slug in slugs:
        for doc in docs:
            key = agent_copy_key(slug, doc.key)
            shipped = doc.model_copy(update={"key": key, "name": title, "mode": "observe"})
            out.append(Copy(slug, key, doc.key, shipped))
    return out


def rules_hash(doc: Any) -> str:
    """A short hash of what a policy's rules do (``simulate.rules_fingerprint``: rules,
    default effect, scope; not its key, name or mode)."""
    from agentfox.platform.policy.simulate import rules_fingerprint

    return hashlib.sha256(rules_fingerprint(doc).encode()).hexdigest()[:12]


def provenance(pack_id: str, copy: Copy) -> str:
    """The note a library's version of a copy carries: where its rules came from."""
    return f"[from {pack_id} {copy.source} {rules_hash(copy.doc)}]"


def _live(session: Any, key: str) -> tuple[Any, Any, Any] | None:
    """(policy, binding, live version) of a copy that applies something; None when it
    does not exist or was emptied (its project was disconnected)."""
    from sqlalchemy import select

    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import current_binding, load_version_document

    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        return None
    binding, live = current_binding(session, policy.id)
    if binding is None or live is None or not load_version_document(live).rules:
        return None
    return policy, binding, live


def copied_from(session: Any, policy: Any, live: Any) -> str:
    """The hash of the shipped rules the live copy was made from: the newest version up
    to the live one that records it, else (a copy made before copies said where they
    came from) the live rules themselves."""
    from sqlalchemy import select

    from agentfox.core.models import PolicyVersion
    from agentfox.platform.policy.store import load_version_document

    versions = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id, PolicyVersion.version <= live.version)
        .order_by(PolicyVersion.version.desc())
    )
    for version in versions:
        found = _FROM.search(version.notes or "")
        if found:
            return found["hash"]
    return rules_hash(load_version_document(live))


# --- Applying, updating, simulating, switching ---------------------------------------


def update_outdated(session: Any, pack_id: str, slugs: list[str], *, actor: str) -> list[str]:
    """Bring these agents' copies of a library up to date with what it ships now, each
    in the mode it is in (``publish_in_current_mode``: a blocking copy's new version is
    simulated and recorded before it goes live). Returns the agents updated."""
    from agentfox.platform.policy.publish import publish_in_current_mode

    title = library_title(pack_id)
    updated: list[str] = []
    for copy in copies(pack_id, slugs) or []:
        live = _live(session, copy.key)
        if live is None or copied_from(session, live[0], live[2]) == rules_hash(copy.doc):
            continue
        publish_in_current_mode(
            session,
            copy.doc,
            actor=actor,
            notes=f"library '{title}' updated {provenance(pack_id, copy)}",
            level="agent",
            scope_id=copy.slug,
            compose="extend",
            agent_slug=copy.slug,
        )
        if copy.slug not in updated:
            updated.append(copy.slug)
    return updated


def apply_library(
    session: Any, pack_id: str, slugs: list[str], *, actor: str
) -> dict[str, list[str]] | None:
    """Apply a library to these agents only, watching first: each agent gets its own
    copy of the library's policies (a copy emptied when its project was disconnected
    is filled again, in the mode it was left in: watching). Agents that already have
    it are brought up to date when the library has changed since
    (:func:`update_outdated`). None when there is no such library."""
    from agentfox.platform.policy.publish import publish_in_current_mode

    found = copies(pack_id, slugs)
    if found is None:
        return None
    title = library_title(pack_id)
    added: list[str] = []
    for copy in found:
        if _live(session, copy.key) is not None:
            continue
        publish_in_current_mode(
            session,
            copy.doc,
            actor=actor,
            notes=f"library '{title}' applied {provenance(pack_id, copy)}",
            level="agent",
            scope_id=copy.slug,
            compose="extend",
            agent_slug=copy.slug,
        )
        if copy.slug not in added:
            added.append(copy.slug)
    updated = [s for s in update_outdated(session, pack_id, slugs, actor=actor) if s not in added]
    return {"added": added, "updated": updated}


class NotSimulated(Exception):
    """Enforcing was asked for copies whose live rules have no recorded simulation."""

    def __init__(self, pack_id: str, pending: list[dict[str, Any]]) -> None:
        self.pending = pending
        agents = sorted({p["agent"] for p in pending})
        super().__init__(
            f"simulate first: {library_title(pack_id)} has not been simulated on "
            f"{', '.join(agents)} with the rules it has now. Click Simulate to see what "
            "it would have stopped in recent traffic, then start blocking."
        )


def library_mode(
    session: Any, pack_id: str, slugs: list[str], mode: str, *, actor: str
) -> list[str] | None:
    """Watch or block with a library on these agents. Returns the agents changed; None
    when there is no such library.

    The gate of ``POST /api/policies/{key}/mode``, for each copy: blocking needs a
    recorded simulation of exactly the copy's live rules (``simulation_for``), checked
    for every copy before any is switched (:class:`NotSimulated`). Watching never needs
    one. Who may do either is the route's to check, as it is for ``/mode``. Each switch
    is audited like that route's.
    """
    from agentfox.platform.ledger import chain
    from agentfox.platform.policy.simulate import simulation_for
    from agentfox.platform.policy.store import set_mode

    found = copies(pack_id, slugs)
    if found is None:
        return None
    targets = [(c, live) for c in found if (live := _live(session, c.key)) is not None]
    if mode == "enforce":
        pending = [
            {"agent": c.slug, "key": c.key, "version": live[2].version}
            for c, live in targets
            if simulation_for(session, live[2]) is None
        ]
        if pending:
            raise NotSimulated(pack_id, pending)
    changed: list[str] = []
    for copy, (_policy, binding, version) in targets:
        if binding.mode != mode:
            set_mode(session, copy.key, mode, version=version.version)
            chain.append(
                session,
                f"policy.mode_{mode}",
                actor_type="user",
                actor_id=actor,
                subject_type="policy",
                subject_id=copy.key,
                payload={"mode": mode, "version": version.version, "library": pack_id},
            )
        if copy.slug not in changed:
            changed.append(copy.slug)
    return changed


def simulate_library(
    session: Any,
    pack_id: str,
    slugs: list[str],
    *,
    run_by: str,
    since_days: int = SIMULATE_DAYS,
    limit: int = 1000,
) -> dict[str, Any] | None:
    """Replay each agent's recent traffic against its copies of a library, as if they
    were blocking, and record each simulation (``record_simulation``) so blocking them
    afterwards passes the gate. The same simulator and record as
    ``POST /api/policies/simulate``, run per copy and narrowed to the copy's agent.

    Per agent: the checks it would have blocked, held for a person, and hidden data
    in, counted once each whichever copy acted. None when there is no such library.
    """
    from agentfox.platform.policy.simulate import record_simulation, simulate
    from agentfox.platform.policy.store import load_version_document

    found = copies(pack_id, slugs)
    if found is None:
        return None
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days)
    agents: dict[str, dict[str, Any]] = {}
    acted: dict[str, dict[str, set[str]]] = {}
    for copy in found:
        live = _live(session, copy.key)
        if live is None:
            continue
        doc = load_version_document(live[2])
        diff = simulate(session, doc, agent_slug=copy.slug, since=since, limit=limit)
        run = record_simulation(
            session,
            doc,
            diff,
            run_by=run_by,
            scope={"agent": copy.slug, "since_days": since_days, "library": pack_id},
        )
        row = agents.setdefault(
            copy.slug, {"agent": copy.slug, "replayed": 0, "examples": [], "policies": []}
        )
        row["replayed"] = max(row["replayed"], diff.replayed)
        seen = acted.setdefault(copy.slug, {"block": set(), "escalate": set(), "hide": set()})
        for record in diff.would_stop:
            if record.get("own") in ("block", "escalate"):
                seen[record["own"]].add(record["decision_id"])
                if len(row["examples"]) < 5:
                    row["examples"].append(record)
        seen["hide"].update(r["decision_id"] for r in diff.would_hide)
        row["policies"].append(
            {
                "key": copy.key,
                "version": live[2].version,
                "simulation_id": run.id,
                "counts": diff.to_json()["counts"],
            }
        )
    out = []
    for slug, row in agents.items():
        seen = acted[slug]
        held = seen["escalate"] - seen["block"]
        hidden = seen["hide"] - seen["block"] - held
        out.append({**row, "blocked": len(seen["block"]), "held": len(held), "hidden": len(hidden)})
    return {
        "library": pack_id,
        "since_days": since_days,
        "agents": out,
        "replayed": sum(r["replayed"] for r in out),
        "blocked": sum(r["blocked"] for r in out),
        "held": sum(r["held"] for r in out),
        "hidden": sum(r["hidden"] for r in out),
    }


def library_status(session: Any, pack_id: str, slugs: list[str]) -> dict[str, Any]:
    """On which of these agents a library is applied, whether it blocks there, whether
    it is also applied workspace-wide, and on which agents the copy is older than what
    the library ships now (``outdated``; apply it again to update them)."""
    from sqlalchemy import select

    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import current_binding

    found = copies(pack_id, slugs)
    if found is None:
        return {
            "agents": [],
            "blocking": False,
            "workspace": False,
            "outdated": False,
            "outdatedAgents": [],
        }
    on: list[str] = []
    outdated: list[str] = []
    modes: list[str] = []
    workspace: list[str] = []
    if pack_id != BASIC_ID:
        for doc in (_library_docs(pack_id) or ("", []))[1]:
            whole = session.scalar(select(Policy).where(Policy.key == doc.key))
            binding = current_binding(session, whole.id)[0] if whole is not None else None
            if binding is not None:
                workspace.append(binding.mode)
    for copy in found:
        live = _live(session, copy.key)
        if live is None:
            continue
        policy, binding, version = live
        if copy.slug not in on:
            on.append(copy.slug)
        modes.append(binding.mode)
        if copied_from(session, policy, version) != rules_hash(copy.doc):
            if copy.slug not in outdated:
                outdated.append(copy.slug)
    # Whether it blocks on these agents: their copies when they have them (what
    # "Start blocking" switches), else the workspace-wide policy that reaches them.
    modes = modes or workspace
    return {
        "agents": on,
        "workspace": bool(workspace),
        "blocking": bool(modes) and all(m == "enforce" for m in modes),
        "outdated": bool(outdated),
        "outdatedAgents": outdated,
    }
