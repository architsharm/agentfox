"""P7 — knowledge boundary and abstention over HTTP.

`POST /check` is the interesting one: it answers "would this question be refused, and
what would we say instead?" without running anything. That is how a team tunes the
boundary against real traffic before enforcing it — and given the counter-metric here
is refusals, tuning first is not optional.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...answerability import (
    QUESTION_TYPES,
    abstention_report,
    classify_answerability,
    declare_boundary,
    get_boundary,
    question_type,
)
from ...models import Agent, KnowledgeBoundary, User
from ..deps import current_user, db, get_agent_or_404, require

router = APIRouter(prefix="/api/answerability", tags=["answerability"])


class BoundaryIn(BaseModel):
    agent: str
    systems_of_record: list[str] = Field(default_factory=list)
    coverage_months: int | None = None
    coverage_start: dt.date | None = None
    entity_types: list[str] = Field(default_factory=list)
    answerable_types: list[str] = Field(default_factory=list)
    out_of_scope_topics: list[str] = Field(default_factory=list)
    freshness_hours: int | None = None
    mode: str = "observe"


@router.put("/boundary", status_code=201)
def write_boundary(
    payload: BoundaryIn,
    session: Session = Depends(db),
    _user: User = Depends(require("policy")),
) -> dict[str, Any]:
    unknown = set(payload.answerable_types) - set(QUESTION_TYPES)
    if unknown:
        raise HTTPException(400, f"unknown question type(s): {sorted(unknown)}")
    boundary = declare_boundary(
        session,
        agent_id=get_agent_or_404(session, payload.agent).id,
        systems_of_record=payload.systems_of_record,
        coverage_months=payload.coverage_months,
        coverage_start=payload.coverage_start,
        entity_types=payload.entity_types,
        answerable_types=payload.answerable_types or None,
        out_of_scope_topics=payload.out_of_scope_topics,
        freshness_hours=payload.freshness_hours,
        mode=payload.mode,
    )
    return _boundary_json(boundary, payload.agent)


@router.get("/boundaries")
def list_boundaries(
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Every declared knowledge boundary, or one agent's with `?agent=<slug>`.

    A filtered read 404s on an unknown agent; a known agent with no declaration
    returns an empty list rather than an error.
    """
    stmt = select(KnowledgeBoundary)
    if agent is not None:
        stmt = stmt.where(KnowledgeBoundary.agent_id == get_agent_or_404(session, agent).id)
    agents = {a.id: a.slug for a in session.scalars(select(Agent))}
    return {
        "boundaries": [
            _boundary_json(b, agents.get(b.agent_id, "?")) for b in session.scalars(stmt)
        ],
        "question_types": list(QUESTION_TYPES),
    }


class CheckIn(BaseModel):
    agent: str
    question: str
    known_entities: list[str] = Field(default_factory=list)


@router.post("/check")
def check(
    payload: CheckIn,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Would this question be refused, and what would we say instead?

    Runs nothing and changes nothing, so a team can replay real traffic against a
    candidate boundary before enforcing it. Shipping a refusal control without this
    step means discovering the false-positive rate from users.
    """
    boundary = get_boundary(session, get_agent_or_404(session, payload.agent).id)
    verdict = classify_answerability(
        payload.question, boundary, known_entities=payload.known_entities or None
    )
    return {
        "agent": payload.agent,
        "question_type": question_type(payload.question),
        "boundary_declared": boundary is not None,
        **verdict.to_json(),
    }


@router.get("/report")
def report(
    days: int = Query(7, ge=1, le=365),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Abstention and over-refusal side by side.

    Reporting one without the other would let a team optimise abstention up, push
    refusals onto answerable questions, and call it progress.
    """
    return abstention_report(session, days=days)


def _boundary_json(boundary: KnowledgeBoundary, slug: str) -> dict[str, Any]:
    return {
        "agent": slug,
        "systems_of_record": boundary.systems_of_record,
        "coverage_months": boundary.coverage_months,
        "coverage_start": (
            boundary.coverage_start.isoformat() if boundary.coverage_start else None
        ),
        "entity_types": boundary.entity_types,
        "answerable_types": boundary.answerable_types,
        "out_of_scope_topics": boundary.out_of_scope_topics,
        "freshness_hours": boundary.freshness_hours,
        "mode": boundary.mode,
    }
