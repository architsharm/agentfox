"""Policy packs and business rules, for the dashboard's policy library.

Both were reachable only from the command line: `agentfox policy packs` to see what
ships, `agentfox policy rules compile` to turn a written policy into rules, and
`agentfox policy rules apply` to save one. These routes put the same operations
behind the screen a customer uses to add policies:

* ``GET  /api/library/packs``                — what ships, and whether it is installed
* ``POST /api/library/packs/{id}/install``   — install a pack, watching (observe)
* ``GET  /api/library/packs/{id}/contents``  — its rules, and its last simulation
* ``GET  /api/business/rules``               — the business rules in force
* ``POST /api/business/compile``             — compile written text; saves nothing
* ``POST /api/business/rules``               — save one compiled rule, watching
* ``POST /api/business/rules/{key}/mode``    — watch or enforce a business rule

Everything new starts in observe, exactly as the CLI does: nothing a customer adds
from the library blocks traffic until they promote it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.capabilities.business import Ladder
from agentfox.capabilities.business.compile import compile_document
from agentfox.capabilities.business.store import delete_ladder, save_ladder, set_mode
from agentfox.core.models import Agent, BusinessRule, Policy, User
from agentfox.platform.ledger import chain
from agentfox.platform.packs.loader import load_packs
from agentfox.platform.policy import PolicyDocument, current_binding, save_policy
from agentfox.platform.registry.service import known_arguments

router = APIRouter(tags=["library"])


def _pack_docs(pack: Any) -> list[PolicyDocument]:
    docs = []
    for path in pack.files("policies"):
        try:
            docs.append(PolicyDocument.from_yaml(path.read_text()))
        except Exception:
            continue
    return docs


def _pack_ladders(pack: Any) -> list[Ladder]:
    import yaml

    ladders = []
    for path in pack.files("ladders"):
        try:
            payload = yaml.safe_load(path.read_text()) or {}
            payload.pop("kind", None)
            ladders.append(Ladder.model_validate(payload))
        except Exception:
            continue
    return ladders


@router.get("/api/library/packs")
def list_packs(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    installed = {p.key: p for p in session.scalars(select(Policy))}
    rule_keys = set(session.scalars(select(BusinessRule.key)))
    out = []
    for pack in load_packs():
        docs = _pack_docs(pack)
        ladders = _pack_ladders(pack)
        if not docs and not ladders:
            continue
        policies = []
        for doc in docs:
            policy = installed.get(doc.key)
            binding = current_binding(session, policy.id)[0] if policy else None
            policies.append(
                {
                    "key": doc.key,
                    "name": doc.name,
                    "rules": len(doc.rules),
                    "installed": policy is not None,
                    "mode": binding.mode if binding else None,
                }
            )
        manifest = pack.manifest
        out.append(
            {
                "id": pack.id,
                "title": manifest.title,
                "description": (manifest.description or "").strip(),
                "tags": list(manifest.tags or []),
                "maturity": pack.maturity,
                "policies": policies,
                "ladders": [
                    {"key": lad.key, "name": lad.name, "installed": lad.key in rule_keys}
                    for lad in ladders
                ],
                "installed": all(p["installed"] for p in policies)
                and all(lad.key in rule_keys for lad in ladders),
            }
        )
    return {"packs": out}


def install(session: Session, pack_id: str, *, actor: str, reason: str = "") -> list[str] | None:
    """Install every policy and ladder a pack ships that is not installed yet, watching.

    Returns what was added, or None for an unknown pack. Shared by the library screen
    and the importers, so a pack reached either way lands the same.
    """
    pack = next((p for p in load_packs() if p.id == pack_id), None)
    if pack is None:
        return None
    existing = set(session.scalars(select(Policy.key)))
    rule_keys = set(session.scalars(select(BusinessRule.key)))
    why = reason or f"installed from pack {pack_id}"
    added: list[str] = []
    for doc in _pack_docs(pack):
        if doc.key in existing:
            continue
        save_policy(session, doc, author=actor, notes=why, bind_mode="observe")
        added.append(doc.key)
    for ladder in _pack_ladders(pack):
        if ladder.key in rule_keys:
            continue
        save_ladder(session, ladder, actor=actor, reason=why)
        added.append(ladder.key)
    chain.append(
        session,
        "library.pack_installed",
        actor_type="user",
        actor_id=actor,
        subject_type="pack",
        subject_id=pack_id,
        payload={"added": added},
    )
    return added


@router.post("/api/library/packs/{pack_id:path}/install")
def install_pack(
    pack_id: str, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    added = install(session, pack_id, actor=user.email or user.id)
    if added is None:
        raise HTTPException(404, f"unknown pack '{pack_id}'")
    return {"pack": pack_id, "added": added}


#: The order a ladder's outcomes are named by: its strongest band decides.
_STRONGEST = ("block", "escalate", "verify", "redact", "allow")

BASIC_DESCRIPTION = (
    "The default set: prompt attacks and jailbreaks in what users send, and personal data "
    "and secrets in replies. Nothing on tools. Watches first, then blocks the attacks and "
    "hides the data."
)


def _ladder_row(ladder: Ladder, business: dict[str, BusinessRule]) -> dict[str, Any]:
    outcomes = {b.outcome for b in ladder.bands}
    saved = business.get(ladder.key)
    bands = []
    for band in ladder.bands:
        edge = f"up to {band.upto:g} {ladder.unit}" if band.upto is not None else "above that"
        bands.append(f"{edge}: {band.outcome}")
    return {
        "id": ladder.key,
        "description": ladder.description or ladder.name,
        "surfaces": [ladder.surface],
        "effect": next((o for o in _STRONGEST if o in outcomes), "allow"),
        "severity": None,
        "tool": ladder.tool,
        "detail": " · ".join(bands),
        "installed": saved is not None,
        "mode": saved.mode if saved is not None else None,
    }


@router.get("/api/library/packs/{pack_id:path}/contents")
def pack_contents(
    pack_id: str,
    agents: str = "",
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """What a library holds, rule by rule, and what its last simulation on these agents
    (comma-separated) found: the library drawer and the library's own page.

    ``pack_id`` is a library (``basic`` is the basic guardrails) or the key of a policy
    one ships, so a link to a library's policy that was never applied lands on the
    library. ``scoped`` is false for a library of business rules only (ladders): those
    apply to every agent, not one project's."""
    from agentfox.capabilities.onboarding.service import basic_document
    from agentfox.capabilities.protection.libraries import BASIC, BASIC_ID, last_simulation

    slugs = [a for a in agents.split(",") if a]
    if pack_id == BASIC_ID:
        doc = basic_document("agent")
        return {
            "id": BASIC_ID,
            "title": BASIC,
            "description": BASIC_DESCRIPTION,
            "scoped": True,
            "rules": [_policy_rule(doc, r) for r in doc.rules],
            "simulation": last_simulation(session, BASIC_ID, slugs),
        }
    packs = load_packs()
    pack = next((p for p in packs if p.id == pack_id), None) or next(
        (p for p in packs if any(d.key == pack_id for d in _pack_docs(p))), None
    )
    if pack is None:
        raise HTTPException(404, f"no library '{pack_id}'")
    docs = _pack_docs(pack)
    ladders = _pack_ladders(pack)
    if not docs and not ladders:
        raise HTTPException(404, f"no library '{pack_id}'")
    business = {
        r.key: r
        for r in session.scalars(
            select(BusinessRule).where(BusinessRule.key.in_([lad.key for lad in ladders]))
        )
    }
    return {
        "id": pack.id,
        "title": pack.manifest.title,
        "description": (pack.manifest.description or "").strip(),
        "scoped": bool(docs),
        "rules": [_policy_rule(d, r) for d in docs for r in d.rules]
        + [_ladder_row(lad, business) for lad in ladders],
        "simulation": last_simulation(session, pack.id, slugs) if docs else None,
    }


def _policy_rule(doc: PolicyDocument, rule: Any) -> dict[str, Any]:
    return {
        "id": rule.id,
        "description": rule.description,
        "surfaces": list(rule.when.surface or []) if rule.when else [],
        "effect": rule.effect,
        "severity": rule.severity,
        "tool": getattr(rule.when, "tool", None) if rule.when else None,
        "policy": doc.key,
    }


def _rule_json(rule: BusinessRule) -> dict[str, Any]:
    definition = dict(rule.definition_json or {})
    return {
        "key": rule.key,
        "kind": rule.kind,
        "name": definition.get("name") or rule.key,
        "description": definition.get("description", ""),
        "tool": rule.tool,
        "mode": rule.mode,
        "enabled": rule.enabled,
        "definition": definition,
    }


@router.get("/api/business/rules")
def list_business_rules(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "rules": [
            _rule_json(r) for r in session.scalars(select(BusinessRule).order_by(BusinessRule.key))
        ]
    }


class CompileIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    #: The agent the rule is written for: its declared tools are what a rule's tool
    #: resolves to ("refund" -> its `issue_refund`).
    agent: str | None = None


def _field_warnings(session: Session, compiled: dict[str, Any]) -> dict[str, Any]:
    """A limit on an argument the tool does not take can never apply; say so before it
    is saved rather than letting it sit in force doing nothing."""
    for rule in compiled.get("rules", []):
        definition = rule.get("definition") or {}
        tool = definition.get("tool")
        path = str(definition.get("field") or definition.get("field_path") or "")
        field = path.removeprefix("arguments.").split(".")[0]
        if not tool or not field:
            continue
        known = known_arguments(session, tool)
        if known is None:
            rule.setdefault("warnings", []).append(
                f"No calls to {tool} have been seen yet, so `{field}` cannot be "
                "checked against its arguments."
            )
        elif field not in known:
            rule.setdefault("warnings", []).append(
                f"{tool} takes no `{field}` argument "
                f"({', '.join(sorted(known)) or 'none'}), so this limit would never apply."
            )
    return compiled


@router.post("/api/business/compile")
def compile_text(
    payload: CompileIn, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Compile written policy into rules and questions. Nothing is saved."""
    agent = (
        session.scalar(select(Agent).where(Agent.slug == payload.agent)) if payload.agent else None
    )
    tools = list(agent.declared_tools or []) if agent else None
    return _field_warnings(
        session, compile_document(payload.text, key_prefix="custom", tools=tools).to_json()
    )


class BusinessRuleIn(BaseModel):
    definition: dict[str, Any]
    agent: str | None = None


@router.post("/api/business/rules", status_code=201)
def save_business_rule(
    payload: BusinessRuleIn, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    definition = {k: v for k, v in payload.definition.items() if k != "kind"}
    definition["mode"] = "observe"
    try:
        ladder = Ladder.model_validate(definition)
    except Exception as exc:
        raise HTTPException(400, f"not a valid rule: {exc}") from exc
    try:
        rule = save_ladder(
            session,
            ladder,
            agent_slug=payload.agent,
            actor=user.email or "",
            reason="added in the dashboard",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _rule_json(rule)


@router.get("/api/business/rules/{key}")
def get_business_rule(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    if rule is None:
        raise HTTPException(404, f"unknown business rule '{key}'")
    return _rule_json(rule)


class BusinessRuleEdit(BaseModel):
    definition: dict[str, Any]


@router.put("/api/business/rules/{key}")
def edit_business_rule(
    key: str,
    payload: BusinessRuleEdit,
    session: Session = Depends(db),
    user: User = Depends(require("policy")),
) -> dict[str, Any]:
    """Change a rule's thresholds in place. It keeps its mode; changing an enforcing
    rule changes what is approved right now, so it needs the production role."""
    from agentfox.apps.gateway.deps import WRITE_ROLES

    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    if rule is None:
        raise HTTPException(404, f"unknown business rule '{key}'")
    if rule.mode == "enforce" and user.role not in WRITE_ROLES["policy_production"]:
        raise HTTPException(
            403, "this rule is enforcing; changing it needs a production policy role"
        )
    definition = {k: v for k, v in payload.definition.items() if k != "kind"}
    definition.update({"key": key, "mode": rule.mode})
    try:
        ladder = Ladder.model_validate(definition)
    except Exception as exc:
        raise HTTPException(400, f"not a valid rule: {exc}") from exc
    agent = session.get(Agent, rule.agent_id) if rule.agent_id else None
    saved = save_ladder(
        session,
        ladder,
        agent_slug=agent.slug if agent else None,
        enabled=rule.enabled,
        actor=user.email or "",
        reason="edited in the dashboard",
    )
    return _rule_json(saved)


@router.delete("/api/business/rules/{key}")
def remove_business_rule(
    key: str, session: Session = Depends(db), user: User = Depends(require("policy_production"))
) -> dict[str, Any]:
    if not delete_ladder(session, key, actor=user.email or "", reason="deleted in the dashboard"):
        raise HTTPException(404, f"unknown business rule '{key}'")
    return {"deleted": key}


class ModeIn(BaseModel):
    mode: str


@router.get("/api/business/rules/{key}/history")
def business_rule_history(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Every saved version of the rule, newest first, with its bands."""
    from agentfox.capabilities.business.store import history

    if session.scalar(select(BusinessRule).where(BusinessRule.key == key)) is None:
        raise HTTPException(404, f"unknown business rule '{key}'")
    return {"key": key, "versions": history(session, key)}


@router.post("/api/business/rules/{key}/versions/{version}/restore", status_code=201)
def restore_business_rule(
    key: str,
    version: int,
    session: Session = Depends(db),
    user: User = Depends(require("policy")),
) -> dict[str, Any]:
    """Put an earlier version's bands back, as a new version in the rule's current mode.

    Restoring an enforcing rule changes what is held right now, so like an edit it
    needs the production role, and the restored bands are simulated on the way in."""
    from agentfox.apps.gateway.deps import may_enforce
    from agentfox.capabilities.business.simulate import simulate_rule
    from agentfox.capabilities.business.store import restore_version

    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    if rule is None:
        raise HTTPException(404, f"unknown business rule '{key}'")
    if rule.mode == "enforce" and not may_enforce(user):
        raise HTTPException(
            403, "this rule is enforcing; restoring a version needs a production policy role"
        )
    try:
        restored = restore_version(session, key, version, actor=user.email or user.id)
    except ValueError as exc:
        raise HTTPException(409 if "already live" in str(exc) else 404, str(exc)) from exc
    out = _rule_json(restored)
    out["restored"] = version
    out["version"] = restored.version
    if restored.mode == "enforce":
        out["simulation"] = simulate_rule(session, restored, run_by=user.email or user.id)
    return out


@router.post("/api/business/rules/{key}/simulate")
def simulate_business_rule(
    key: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """Replay the last 7 days of calls through the rule as if it enforced, and record
    it: what Start blocking needs first, as for any library."""
    from agentfox.capabilities.business.simulate import simulate_rule

    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    if rule is None:
        raise HTTPException(404, f"unknown business rule '{key}'")
    try:
        return simulate_rule(session, rule, run_by=user.email or user.id)
    except ValueError as exc:
        raise HTTPException(422, f"the rule no longer validates: {exc}") from exc


@router.post("/api/business/rules/{key}/mode")
def business_rule_mode(
    key: str,
    payload: ModeIn,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
    """Watch or enforce a business rule. Enforcing needs a recorded simulation of the
    rule as it stands (``POST …/simulate``), the same gate as a policy pack's; going
    back to watching never does."""
    from agentfox.capabilities.business.simulate import simulation_for_rule

    if payload.mode == "enforce":
        rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
        if rule is None:
            raise HTTPException(404, f"unknown business rule '{key}'")
        if rule.mode != "enforce" and simulation_for_rule(session, rule) is None:
            raise HTTPException(
                409,
                f"'{key}' has not been simulated as it stands: replay recent traffic "
                f"through it first (Simulate, or POST /api/business/rules/{key}/simulate), "
                "then start blocking",
            )
    try:
        rule = set_mode(
            session,
            key,
            payload.mode,
            actor=user.email or "",
            reason=f"set to {payload.mode} in the dashboard",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _rule_json(rule)
