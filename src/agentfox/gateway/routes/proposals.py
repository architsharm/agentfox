"""Change proposals over HTTP — the inbox for the governed improvement loop.

Anyone who can read the control plane can read proposals: seeing what the system wants
to change about itself is not privileged. Deciding, applying, rolling back and
verifying are production policy changes, so they need ``policy_production``. Nothing
here can apply a change as automation — a request always has a person behind it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agentfox.capabilities.improvement import contract
from agentfox.capabilities.improvement.proposals import (
    IllegalTransition,
    apply_proposal,
    decide,
    get_proposal,
    list_proposals,
    proposal_json,
    rollback_proposal,
    verify_proposal,
)
from agentfox.core.models import ChangeProposal, User
from agentfox.gateway.deps import current_user, db, require

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


def _load(session: Session, proposal_id: str) -> ChangeProposal:
    proposal = get_proposal(session, proposal_id)
    if proposal is None:
        raise HTTPException(404, f"unknown proposal '{proposal_id}'")
    return proposal


def _raise(exc: ValueError) -> None:
    status = 409 if isinstance(exc, IllegalTransition) else 400
    raise HTTPException(status, str(exc)) from exc


@router.get("")
def list_all(
    status: str | None = None,
    kind: str | None = None,
    scope_level: str | None = None,
    scope_id: str | None = None,
    limit: int = 200,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """List change proposals, filtered by status, kind and scope."""
    if status and status not in contract.STATUSES:
        raise HTTPException(400, f"status must be one of {contract.STATUSES}")
    rows = list_proposals(
        session,
        status=status,
        kind=kind,
        scope_level=scope_level,
        scope_id=scope_id,
        limit=max(1, min(limit, 500)),
    )
    return {"proposals": [proposal_json(p) for p in rows]}


@router.get("/{proposal_id}")
def show(
    proposal_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """One proposal with its diff, evidence, proof and decisions."""
    return proposal_json(_load(session, proposal_id))


class DecideRequest(BaseModel):
    approve: bool
    note: str


@router.post("/{proposal_id}/decide")
def decide_route(
    proposal_id: str,
    payload: DecideRequest,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
    """Approve or reject; an org-level loosening needs two different approvers."""
    proposal = _load(session, proposal_id)
    try:
        decide(
            session,
            proposal,
            approve=payload.approve,
            actor=user.email or user.id,
            note=payload.note,
        )
    except ValueError as exc:
        _raise(exc)
    return proposal_json(proposal)


@router.post("/{proposal_id}/apply")
def apply_route(
    proposal_id: str,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
    """Apply an approved proposal, or settle one whose canary has finished."""
    proposal = _load(session, proposal_id)
    try:
        apply_proposal(session, proposal, actor=user.email or user.id, automated=False)
    except ValueError as exc:
        _raise(exc)
    return proposal_json(proposal)


class RollbackRequest(BaseModel):
    reason: str


@router.post("/{proposal_id}/rollback")
def rollback_route(
    proposal_id: str,
    payload: RollbackRequest,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
    """Undo an applied or canaried proposal through its applier."""
    proposal = _load(session, proposal_id)
    try:
        rollback_proposal(session, proposal, reason=payload.reason, actor=user.email or user.id)
    except ValueError as exc:
        _raise(exc)
    return proposal_json(proposal)


class VerifyRequest(BaseModel):
    verified: bool
    note: str


@router.post("/{proposal_id}/verify")
def verify_route(
    proposal_id: str,
    payload: VerifyRequest,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
    """Record whether an applied change worked; ``verified: false`` rolls it back."""
    proposal = _load(session, proposal_id)
    try:
        verify_proposal(
            session,
            proposal,
            verified=payload.verified,
            note=payload.note,
            actor=user.email or user.id,
        )
    except ValueError as exc:
        _raise(exc)
    return proposal_json(proposal)
