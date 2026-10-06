"""P11 — escalation governance over HTTP.

The route that matters is `GET /api/escalation/missed`. Everything else here is
plumbing that any HITL product has; that one answers the question nobody else asks —
which conversations qualified for a human and never got one.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.containment.escalation import (
    DEFAULT_CONDITIONS,
    assess,
    detect_missed_escalation,
    escalation_report,
    get_policy,
    handoff_completeness,
    record_turn,
    run_scan,
    set_policy,
    turn_depth_risk,
)
from agentfox.core.models import Agent, ConversationTurn, Handoff, User, utcnow
from agentfox.gateway.deps import current_user, db, get_agent_or_404, require

router = APIRouter(prefix="/api/escalation", tags=["escalation"])


def _agent_id(session: Session, slug: str | None) -> str | None:
    return get_agent_or_404(session, slug).id if slug else None


# ---------------------------------------------------------------------------
# Policy (P11-1)
# ---------------------------------------------------------------------------


class PolicyIn(BaseModel):
    agent: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    owner_role: str = "support"
    sla_minutes: int = Field(60, ge=1, le=10080)
    mode: str = "observe"


@router.get("/policy")
def read_policy(
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    policy = get_policy(session, _agent_id(session, agent))
    return {
        "agent": agent,
        "conditions": policy.conditions_json or DEFAULT_CONDITIONS,
        "owner_role": policy.owner_role,
        "sla_minutes": policy.sla_minutes,
        "mode": policy.mode,
        "defaults": DEFAULT_CONDITIONS,
    }


@router.put("/policy", status_code=201)
def write_policy(
    payload: PolicyIn,
    session: Session = Depends(db),
    _user: User = Depends(require("policy")),
) -> dict[str, Any]:
    policy = set_policy(
        session,
        agent_id=_agent_id(session, payload.agent),
        conditions=payload.conditions,
        owner_role=payload.owner_role,
        sla_minutes=payload.sla_minutes,
        mode=payload.mode,
    )
    return {"id": policy.id, "conditions": policy.conditions_json, "mode": policy.mode}


# ---------------------------------------------------------------------------
# Turn capture
# ---------------------------------------------------------------------------


class TurnIn(BaseModel):
    session_id: str
    agent: str | None = None
    trace_id: str | None = None
    user_text: str = ""
    agent_text: str = ""
    escalated: bool = False
    failed: bool = False
    confidence: float | None = None


@router.post("/turns", status_code=201)
def capture_turn(
    payload: TurnIn,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Record one turn with its signals.

    Signals are extracted here rather than at detection time, so a later change to the
    lexicon cannot make yesterday's conversations answer differently.
    """
    turn = record_turn(
        session,
        session_id=payload.session_id,
        agent_id=_agent_id(session, payload.agent),
        trace_id=payload.trace_id,
        user_text=payload.user_text,
        agent_text=payload.agent_text,
        escalated=payload.escalated,
        failed=payload.failed,
        confidence=payload.confidence,
    )
    # Set when an enforcing escalation policy handed the conversation off on this turn
    # (or an earlier one): the caller should stop answering and tell the user.
    handoff_id = session.scalar(
        select(Handoff.id).where(Handoff.session_id == payload.session_id).limit(1)
    )
    return {
        "id": turn.id,
        "turn_index": turn.turn_index,
        "signals": turn.signals_json,
        "handoff_id": handoff_id,
    }


@router.get("/conversations/{session_id}")
def conversation(
    session_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """The transcript plus why the policy did or didn't fire on it.

    Includes the actual turn text — a missed-escalation row that says only
    "3 triggers on turn 2" gives an operator nothing to act on; they need to see
    what the user actually said.
    """
    turns = list(
        session.scalars(select(ConversationTurn).where(ConversationTurn.session_id == session_id))
    )
    if not turns:
        raise HTTPException(404, "no turns recorded for that session")
    agent_id = next((t.agent_id for t in turns if t.agent_id), None)
    agent = session.get(Agent, agent_id) if agent_id else None
    assessment = assess(turns, get_policy(session, agent_id))
    handoff = session.scalar(
        select(Handoff).where(Handoff.session_id == session_id).order_by(Handoff.created_at.desc())
    )
    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_slug": agent.slug if agent else None,
        "agent_name": agent.name if agent else None,
        "assessment": assessment.to_json(),
        "turn_depth": turn_depth_risk(turns, get_policy(session, agent_id)),
        "handoff": _handoff_json(handoff, session) if handoff else None,
        "turns": [
            {
                "index": t.turn_index,
                "user_text": t.user_text,
                "agent_text": t.agent_text,
                "trace_id": t.trace_id,
                "signals": t.signals_json,
                "escalated": t.escalated,
                "claims_resolution": t.resolved_claimed,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in sorted(turns, key=lambda t: t.turn_index)
        ],
    }


# ---------------------------------------------------------------------------
# The control (P11-2)
# ---------------------------------------------------------------------------


@router.get("/missed")
def missed(
    since_hours: int = Query(24, ge=1, le=8760),
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """**The 31% control.** Conversations that qualified for a hand-off and got none.

    Read-only: this endpoint does not raise findings or retroactive hand-offs, so it
    is safe to poll from a dashboard. `POST /scan` is the one that acts.
    """
    result = detect_missed_escalation(
        session, since_hours=since_hours, agent_slug=agent, raise_findings=False
    )
    agent_ids = {m["agent_id"] for m in result["missed"] if m.get("agent_id")}
    slugs = (
        {a.id: a.slug for a in session.scalars(select(Agent).where(Agent.id.in_(agent_ids)))}
        if agent_ids
        else {}
    )
    for m in result["missed"]:
        m["agent_slug"] = slugs.get(m.get("agent_id"))
    return result


@router.post("/scan")
def scan(
    since_hours: int = Query(24, ge=1, le=8760),
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(require("approvals")),
) -> dict[str, Any]:
    """Run detection and act on it: findings, retroactive hand-offs, SLA breaches.

    Retroactive hand-offs are the point. Recording that a person was left waiting and
    then leaving them waiting produces an audit artefact, not a control.
    """
    return run_scan(session, since_hours=since_hours, agent_slug=agent)


@router.get("/report")
def report(
    since_hours: int = Query(24, ge=1, le=8760),
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    return escalation_report(session, since_hours=since_hours, agent_slug=agent)


# ---------------------------------------------------------------------------
# Hand-offs (P11-6/7)
# ---------------------------------------------------------------------------


@router.get("/handoffs")
def list_handoffs(
    status: str | None = None,
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    stmt = select(Handoff).order_by(Handoff.created_at.desc())
    if status:
        stmt = stmt.where(Handoff.status == status)
    if agent:
        stmt = stmt.where(Handoff.agent_id == _agent_id(session, agent))
    return {"handoffs": [_handoff_json(h, session) for h in session.scalars(stmt)]}


@router.post("/handoffs/{handoff_id}/acknowledge")
def acknowledge(
    handoff_id: str,
    session: Session = Depends(db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    handoff = session.get(Handoff, handoff_id)
    if handoff is None:
        raise HTTPException(404, "unknown hand-off")
    handoff.acknowledged_at = utcnow()
    handoff.owner_user_id = user.id
    handoff.status = "acknowledged"
    session.flush()
    return _handoff_json(handoff, session)


def _handoff_json(handoff: Handoff, session: Session) -> dict[str, Any]:
    completeness = handoff_completeness(handoff.context_json)
    agent = session.get(Agent, handoff.agent_id) if handoff.agent_id else None
    return {
        "id": handoff.id,
        "session_id": handoff.session_id,
        "agent_id": handoff.agent_id,
        "agent_slug": agent.slug if agent else None,
        "agent_name": agent.name if agent else None,
        "trace_id": handoff.trace_id,
        "status": handoff.status,
        "reason": handoff.reason,
        "summary": (handoff.context_json or {}).get("conversation_summary"),
        "triggers": handoff.triggers_json,
        "owner_role": handoff.owner_role,
        "due_at": handoff.due_at.isoformat() if handoff.due_at else None,
        "completeness": completeness,
        "detected_retroactively": handoff.detected_retroactively,
    }
