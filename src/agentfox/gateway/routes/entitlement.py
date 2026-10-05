"""P10 — entitlement over HTTP.

`POST /filter` is the one that does the work: a retriever hands it candidate chunks
and the calling human, and gets back what that human may see plus a record of
everything withheld. It is deliberately callable *before* the model, because filtering
after generation means the answer already contains what it should not.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, EndUserPrincipal, ResourceGrant, User
from agentfox.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.grounding.entitlement import (
    RESTRICTED_CLASSES,
    filter_retrieval,
    get_engine,
    grant,
    over_permission_report,
    record_disclosure,
    upsert_principal,
)

router = APIRouter(prefix="/api/entitlement", tags=["entitlement"])


class PrincipalIn(BaseModel):
    subject: str = Field(description="Stable IdP identifier — an OIDC `sub`, employee id.")
    agent: str | None = None
    display: str = ""
    groups: list[str] = Field(default_factory=list)
    clearances: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    residency: str | None = None


@router.put("/principals", status_code=201)
def put_principal(
    payload: PrincipalIn,
    session: Session = Depends(db),
    _user: User = Depends(require("identity")),
) -> dict[str, Any]:
    agent_id = get_agent_or_404(session, payload.agent).id if payload.agent else None
    record = upsert_principal(
        session,
        payload.subject,
        agent_id=agent_id,
        display=payload.display,
        groups=payload.groups,
        clearances=payload.clearances,
        purposes=payload.purposes,
        residency=payload.residency,
    )
    return _principal_json(record)


@router.get("/principals")
def list_principals(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "principals": [_principal_json(p) for p in session.scalars(select(EndUserPrincipal))],
        "restricted_classes": list(RESTRICTED_CLASSES),
    }


class GrantIn(BaseModel):
    resource: str = Field(description="Matches a chunk's source; globs allowed.")
    principal: str
    principal_kind: str = "group"
    classes: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    residency: str | None = None


@router.post("/grants", status_code=201)
def add_grant(
    payload: GrantIn,
    session: Session = Depends(db),
    _user: User = Depends(require("identity")),
) -> dict[str, Any]:
    record = grant(
        session,
        payload.resource,
        principal=payload.principal,
        principal_kind=payload.principal_kind,
        classes=payload.classes,
        purposes=payload.purposes,
        residency=payload.residency,
    )
    return {"id": record.id, "resource": record.resource, "principal": record.principal}


@router.get("/grants")
def list_grants(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "grants": [
            {
                "id": g.id,
                "resource": g.resource,
                "principal": g.principal,
                "principal_kind": g.principal_kind,
                "classes": g.classes,
                "purposes": g.purposes,
                "residency": g.residency,
            }
            for g in session.scalars(select(ResourceGrant))
        ],
        "engine": get_engine().key,
    }


class FilterIn(BaseModel):
    subject: str
    agent: str | None = None
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    purpose: str | None = None
    trace_id: str | None = None
    record: bool = Field(True, description="Persist what was withheld.")


@router.post("/filter")
def filter_chunks(
    payload: FilterIn,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Return only what this human may see, and record what was withheld.

    Call it before generation. Filtering afterwards means the answer already contains
    what it should not — at which point the only remaining option is to refuse to send
    it, and the user learns that something exists.
    """
    principal = session.scalar(
        select(EndUserPrincipal).where(EndUserPrincipal.subject == payload.subject)
    )
    if principal is None:
        raise HTTPException(
            404,
            f"unknown principal '{payload.subject}'. Register it first — an agent "
            "answering with no idea who is asking is the failure this prevents.",
        )
    agent_id = None
    if payload.agent:
        agent = session.scalar(select(Agent).where(Agent.slug == payload.agent))
        agent_id = agent.id if agent else None

    decision = filter_retrieval(session, principal, payload.chunks, purpose=payload.purpose)
    if payload.record:
        record_disclosure(
            session, decision, trace_id=payload.trace_id, agent_id=agent_id, stage="pre"
        )
    return {"chunks": decision.visible, **decision.to_json()}


@router.get("/over-permission")
def over_permission(
    days: int = Query(7, ge=1, le=365),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """How much more the agent can reach than its callers are entitled to.

    Works before any entitlement model exists, which is the argument for looking at it
    first: a customer with no grants sees 1.0 and understands the exercise immediately.
    """
    return over_permission_report(session, days=days)


def _principal_json(record: EndUserPrincipal) -> dict[str, Any]:
    return {
        "subject": record.subject,
        "display": record.display,
        "groups": record.groups,
        "clearances": record.clearances,
        "purposes": record.purposes,
        "residency": record.residency,
    }
