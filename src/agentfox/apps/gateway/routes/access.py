"""What an agent can do, for the dashboard: read it, grant it, change it, remove it.

Grants were reachable only from the command line (`agentfox permit`) and as a raw
per-identity list over HTTP, which meant the screen people open to answer "what can
this agent do" could not show it. These routes are keyed by agent slug, carry the
usage that makes a grant reviewable (how often each tool was called, blocked, last
used), and include the two lists that drive least privilege:

* ``tried`` — tools the agent called and was refused for having no grant
* ``unused`` — grants with no calls in the window
"""

from __future__ import annotations

import datetime as dt
import fnmatch
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.core.models import Capability, Decision, Identity, Tool, User
from agentfox.core.vocab import TAINT_ORDER
from agentfox.platform.identity import ensure_identity
from agentfox.platform.identity.service import grant_capability, revoke_capability
from agentfox.platform.ledger import chain
from agentfox.platform.registry.impact import infer_impact
from agentfox.platform.registry.service import impact_source_of, upsert_tool

router = APIRouter(prefix="/api/agents", tags=["access"])


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _capability_json(c: Capability, tools: dict[str, Tool]) -> dict[str, Any]:
    tool = tools.get(c.tool_key)
    return {
        "id": c.id,
        "tool_key": c.tool_key,
        "actions": c.actions,
        "constraints": c.constraints_json or {},
        "requires_approval": c.requires_approval,
        "max_taint": c.max_taint,
        "granted_by": c.granted_by,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "tool": {
            "name": tool.name,
            "impact": tool.impact,
            "impact_source": impact_source_of(tool),
            "description": tool.description,
        }
        if tool
        else None,
    }


@router.get("/{slug}/access")
def get_access(
    slug: str,
    days: int = Query(30, ge=1, le=90),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    identity = session.scalar(select(Identity).where(Identity.agent_id == agent.id))
    # A red-team run's simulated `redteam.*` grants are not the agent's access.
    caps = [
        c
        for c in (identity.capabilities if identity else [])
        if not c.tool_key.startswith("redteam.")
    ]
    tools = {t.key: t for t in session.scalars(select(Tool))}

    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    usage: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "blocked": 0, "held": 0, "last_used": None}
    )
    tried: dict[str, dict[str, Any]] = {}
    for d in session.scalars(
        select(Decision).where(
            Decision.agent_id == agent.id,
            Decision.created_at >= since,
            Decision.tool_key.is_not(None),
            Decision.tool_key.not_like("redteam.%"),
        )
    ):
        key = d.tool_key or ""
        at = _aware(d.created_at).isoformat()
        u = usage[key]
        u["calls"] += 1
        u["blocked"] += 1 if d.verdict == "block" else 0
        u["held"] += 1 if d.verdict == "escalate" else 0
        if not u["last_used"] or at > u["last_used"]:
            u["last_used"] = at
        if any(
            isinstance(r, dict) and r.get("rule_id") == "capability.denied"
            for r in d.rules_fired_json or []
        ):
            t = tried.setdefault(
                key, {"tool_key": key, "count": 0, "last": None, "sample_trace_id": d.trace_id}
            )
            t["count"] += 1
            if not t["last"] or at > t["last"]:
                t["last"], t["sample_trace_id"] = at, d.trace_id

    def calls_for(pattern: str) -> dict[str, Any]:
        rows = [v for k, v in usage.items() if fnmatch.fnmatch(k, pattern)]
        last = max((r["last_used"] for r in rows if r["last_used"]), default=None)
        return {
            "calls": sum(r["calls"] for r in rows),
            "blocked": sum(r["blocked"] for r in rows),
            "held": sum(r["held"] for r in rows),
            "last_used": last,
        }

    capabilities = [{**_capability_json(c, tools), "usage": calls_for(c.tool_key)} for c in caps]
    granted = [c.tool_key for c in caps]
    return {
        "agent": slug,
        "identity_id": identity.id if identity else None,
        "days": days,
        "capabilities": sorted(capabilities, key=lambda c: c["usage"]["calls"], reverse=True),
        "tried": sorted(
            (
                {**t, "tool": _capability_json(Capability(tool_key=t["tool_key"]), tools)["tool"]}
                for t in tried.values()
                if not any(fnmatch.fnmatch(t["tool_key"], g) for g in granted)
            ),
            key=lambda t: t["count"],
            reverse=True,
        ),
        "unused": [c["id"] for c in capabilities if c["usage"]["calls"] == 0],
        # Tools the agent's code defines that it has no grant for yet.
        "in_code": sorted(
            k for k in agent.declared_tools or [] if not any(fnmatch.fnmatch(k, g) for g in granted)
        ),
        "tools": [
            {"key": t.key, "name": t.name, "impact": t.impact, "description": t.description}
            for t in sorted(tools.values(), key=lambda t: t.key)
        ],
    }


class AccessIn(BaseModel):
    tool_key: str
    requires_approval: bool = False
    max_taint: str = "user"
    constraints: dict[str, Any] = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=lambda: ["*"])
    #: The tool's risk, when the operator chose one: read, write, high_impact or
    #: irreversible. Absent, an undeclared tool is registered with a cautious guess.
    impact: str | None = None


IMPACTS = ("read", "write", "high_impact", "irreversible")


def _declare(session: Session, key: str, impact: str | None, actor: str) -> None:
    """Make sure the registry knows the tool being granted.

    A grant for a tool the registry has never seen used to leave every call held by
    `tool.not_declared` — the operator clicked Allow and nothing was allowed. So the
    tool is registered here: with the impact the operator chose, or a cautious guess
    from its name, marked as a guess for them to confirm.
    """
    if "*" in key:
        return
    known = session.scalar(select(Tool).where(Tool.key == key))
    if impact is not None:
        upsert_tool(session, key, impact=impact, actor=actor, name=known.name if known else key)
    elif known is None:
        upsert_tool(
            session,
            key,
            impact=infer_impact(key, cautious=True),
            impact_source="inferred",
            actor=actor,
        )


@router.post("/{slug}/access", status_code=201)
def set_access(
    slug: str,
    payload: AccessIn,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    """Grant a tool, or change the existing grant for it (one grant per tool key)."""
    if payload.max_taint not in TAINT_ORDER:
        raise HTTPException(400, f"max_taint must be one of {', '.join(TAINT_ORDER)}")
    if payload.impact is not None and payload.impact not in IMPACTS:
        raise HTTPException(400, f"impact must be one of {', '.join(IMPACTS)}")
    agent = get_agent_or_404(session, slug)
    _declare(session, payload.tool_key, payload.impact, user.email or user.id)
    identity = ensure_identity(session, agent)
    existing = next((c for c in identity.capabilities if c.tool_key == payload.tool_key), None)
    if existing:
        existing.requires_approval = payload.requires_approval
        existing.max_taint = payload.max_taint
        existing.constraints_json = payload.constraints
        existing.actions = payload.actions
        capability, event = existing, "capability.updated"
        session.flush()
    else:
        capability = grant_capability(
            session,
            identity,
            payload.tool_key,
            actions=payload.actions,
            constraints=payload.constraints,
            requires_approval=payload.requires_approval,
            max_taint=payload.max_taint,
            granted_by=user.email,
        )
        event = "capability.granted"
    chain.append(
        session,
        event,
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="capability",
        subject_id=capability.id,
        payload={"agent": slug, **payload.model_dump()},
    )
    return {"id": capability.id, "tool_key": capability.tool_key, "event": event}


@router.delete("/{slug}/access/{capability_id}")
def remove_access(
    slug: str,
    capability_id: str,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    capability = session.get(Capability, capability_id)
    identity = session.get(Identity, capability.identity_id) if capability else None
    if capability is None or identity is None or identity.agent_id != agent.id:
        raise HTTPException(404, "unknown grant for this agent")
    shape = _capability_json(capability, {})
    revoke_capability(session, capability_id)
    chain.append(
        session,
        "capability.revoked",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="capability",
        subject_id=capability_id,
        payload={
            "agent": slug,
            **{k: shape[k] for k in ("tool_key", "constraints", "requires_approval", "max_taint")},
        },
    )
    return {"revoked": capability_id}
