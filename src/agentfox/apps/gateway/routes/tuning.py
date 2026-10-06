"""The guardrail tuning surface over HTTP.

Detection is commoditised; tuning is not. These routes exist because the practitioner
complaint is rarely "the detector missed it" — it is "it fired, I could not tell
whether it was right, and I had nowhere to put the fact that it was wrong". The
answer to a false positive has to be cheaper than turning the detector off, or the
detector gets turned off.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.capabilities.detection.tuning import (
    LABEL_REFUSED_ROLES,
    LABELS,
    SUPPRESSION_SCOPES,
    active_suppressions,
    apply_suppression,
    latency_report,
    precision_report,
    record_feedback,
    revoke_suppression,
    suppression_health,
    threshold_recommendations,
)
from agentfox.core.models import Agent, GuardrailFeedback, Suppression, User

router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


@router.get("/latency")
def latency(
    agent: str | None = None,
    days: int = Query(7, ge=1, le=90),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Per-detector and per-agent p50/p95/max, plus how often the budget degraded.

    Percentiles rather than means on purpose: a mean hides the tail, and the tail is
    what gets a governance product removed for being slow.
    """
    return latency_report(session, agent_slug=agent, days=days)


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    decision_id: str
    label: str = Field(description=" | ".join(LABELS))
    detector_key: str | None = None
    entity_type: str | None = None
    note: str = ""


@router.post("/feedback", status_code=201)
def submit_feedback(
    payload: FeedbackRequest,
    session: Session = Depends(db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """ "This was wrong", attached to the decision it is about.

    The label's author is the signed-in caller and nobody else — the request body has
    no actor field to spoof. Filing it again for the same decision changes the caller's
    label rather than adding a vote. Auditors are refused: they observe the controls,
    and a control its auditor can tune is not independently audited.
    """
    if user.role in LABEL_REFUSED_ROLES:
        raise HTTPException(
            403,
            f"role '{user.role}' observes guardrails and may not label their decisions",
        )
    try:
        feedback = record_feedback(
            session,
            decision_id=payload.decision_id,
            label=payload.label,
            detector_key=payload.detector_key,
            entity_type=payload.entity_type,
            note=payload.note,
            actor=user.email or user.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "id": feedback.id,
        "decision_id": feedback.decision_id,
        "actor": feedback.actor,
        "label": feedback.label,
        "detector_key": feedback.detector_key,
        "entity_type": feedback.entity_type,
        "score": feedback.score,
        "status": feedback.status,
    }


@router.get("/feedback")
def list_feedback(
    label: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    stmt = select(GuardrailFeedback).order_by(GuardrailFeedback.created_at.desc()).limit(limit)
    if label:
        stmt = stmt.where(GuardrailFeedback.label == label)
    if status:
        stmt = stmt.where(GuardrailFeedback.status == status)
    return {
        "feedback": [
            {
                "id": row.id,
                "decision_id": row.decision_id,
                "trace_id": row.trace_id,
                "detector_key": row.detector_key,
                "entity_type": row.entity_type,
                "label": row.label,
                "score": row.score,
                "verdict": row.verdict,
                "note": row.note,
                "actor": row.actor,
                "status": row.status,
                "at": row.created_at.isoformat(),
            }
            for row in session.scalars(stmt)
        ]
    }


@router.get("/precision")
def precision(
    agent: str | None = None,
    days: int = Query(30, ge=1, le=365),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Per-detector precision with the label count beside it.

    The denominator is not decoration — precision over four labels is noise, and
    reporting it without the sample size is how a tuning surface starts lying.
    """
    agent_id = None
    if agent:
        record = session.scalar(select(Agent).where(Agent.slug == agent))
        agent_id = record.id if record else agent
    return precision_report(session, days=days, agent_id=agent_id)


@router.get("/recommendations")
def recommendations(
    days: int = Query(30, ge=1, le=365),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Threshold suggestions, including the honest refusal to make one.

    A detector whose false and true positives occupy the same score range cannot be
    fixed with a dial, and saying so is more useful than a confident number.
    """
    return {"recommendations": [r.to_json() for r in threshold_recommendations(session, days=days)]}


# ---------------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------------


class SuppressionRequest(BaseModel):
    feedback_id: str
    scope: str = Field("agent", description=" | ".join(SUPPRESSION_SCOPES))
    ttl_days: int = Field(30, ge=1, le=365)
    exact: bool = Field(False, description="suppress only this exact matched text")
    reason: str = ""


@router.post("/suppressions", status_code=201)
def create_suppression(
    payload: SuppressionRequest,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    """Accept a false positive as a scoped, expiring exception.

    Expiry is mandatory by construction: a permanent silent exception is
    indistinguishable from a detector that stopped working.
    """
    try:
        suppression = apply_suppression(
            session,
            feedback_id=payload.feedback_id,
            scope=payload.scope,
            ttl_days=payload.ttl_days,
            actor=user.email,
            exact=payload.exact,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _suppression_json(session, suppression)


@router.get("/suppressions")
def list_suppressions(
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    agent_id = get_agent_or_404(session, agent).id if agent else None
    rows = (
        active_suppressions(session, agent_id)
        if agent
        else list(session.scalars(select(Suppression)))
    )
    return {
        "suppressions": [_suppression_json(session, row) for row in rows],
        "health": suppression_health(session),
    }


@router.delete("/suppressions/{suppression_id}")
def delete_suppression(
    suppression_id: str,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    try:
        revoke_suppression(session, suppression_id, actor=user.email)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"revoked": suppression_id}


def _suppression_json(session: Session, row: Suppression) -> dict[str, Any]:
    agent = session.get(Agent, row.agent_id) if row.agent_id else None
    return {
        "id": row.id,
        "agent": agent.slug if agent else "*",
        "detector_key": row.detector_key,
        "entity_type": row.entity_type,
        "exact_match_only": bool(row.sample_hash),
        "reason": row.reason,
        "created_by": row.created_by,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "hits": row.hits,
        "active": row.active,
    }
