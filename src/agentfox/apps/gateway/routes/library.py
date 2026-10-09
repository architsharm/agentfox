"""Policy packs and business rules, for the dashboard's policy library.

Both were reachable only from the command line: `agentfox policy packs` to see what
ships, `agentfox policy rules compile` to turn a written policy into rules, and
`agentfox policy rules apply` to save one. These routes put the same operations
behind the screen a customer uses to add policies:

* ``GET  /api/library/packs``                — what ships, and whether it is installed
* ``POST /api/library/packs/{id}/install``   — install a pack, watching (observe)
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


def known_arguments(session: Session, tool_key: str) -> set[str] | None:
    """The arguments a tool takes: from its declared input schema, else from the calls
    seen. None when neither says anything."""
    from agentfox.core.models import Decision, Tool
    from agentfox.platform.registry.service import tool_input_schema

    tool = session.scalar(select(Tool).where(Tool.key == tool_key))
    declared = set((tool_input_schema(tool).get("properties") or {}).keys()) if tool else set()
    if declared:
        return declared
    seen: set[str] = set()
    recent = session.scalars(
        select(Decision)
        .where(Decision.tool_key == tool_key)
        .order_by(Decision.created_at.desc())
        .limit(50)
    )
    for decision in recent:
        seen |= set(((decision.taint_summary_json or {}).get("arguments_snapshot") or {}).keys())
    return seen or None


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
    return _field_warnings(session, compile_document(payload.text, key_prefix="custom").to_json())


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


@router.post("/api/business/rules/{key}/mode")
def business_rule_mode(
    key: str,
    payload: ModeIn,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
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
