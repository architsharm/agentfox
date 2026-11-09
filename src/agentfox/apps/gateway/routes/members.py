"""Who is in this workspace, and adding a teammate (Settings → Members).

There is no email invite: sign-in providers key an account on the provider's own
subject, never on an email address (see ``integrations._provision_identity``), so a
teammate can't be matched to a GitHub or Google sign-in by their address. Adding one
makes the user, with a role, and a sign-in key shown once: the teammate pastes it on
the sign-in page, which is the same path as ``agentfox admin users create --token``.

Listing members is open to everyone in the workspace; changing them is the ``users``
route family (owner, admin).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.core.models import User
from agentfox.platform.identity.operators import (
    OPERATOR_ROLES,
    OperatorExists,
    create_operator,
    issue_token,
)
from agentfox.platform.ledger.operator_log import record

router = APIRouter(prefix="/api", tags=["platform"])

#: How long the sign-in key handed to a new teammate works. Signing in with it
#: exchanges it for a session of its own; it is a key like any other after that.
INVITE_KEY_DAYS = 7


def _json(u: User) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active}


@router.get("/members")
def list_members(
    session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """Everyone in this workspace, owners first."""
    rank = {r: i for i, r in enumerate(OPERATOR_ROLES)}
    members = sorted(
        session.scalars(select(User)), key=lambda u: (rank.get(u.role, 99), u.email or "")
    )
    return {"members": [_json(u) for u in members], "roles": list(OPERATOR_ROLES)}


class MemberIn(BaseModel):
    email: str
    role: str = "developer"


@router.post("/members", status_code=201)
def add_member(
    body: MemberIn, session: Session = Depends(db), user: User = Depends(require("users"))
) -> dict[str, Any]:
    """Add a teammate with a role. Returns a sign-in key for them, shown this once."""
    actor = user.email or user.id
    try:
        member = create_operator(
            session,
            body.email,
            role=body.role,
            org_id=user.org_id,
            actor=actor,
            reason=f"added from Settings → Members by {actor}",
        )
    except OperatorExists:
        raise HTTPException(409, f"{body.email.strip()} is already a member.") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    _token, raw = issue_token(
        session,
        member,
        name="sign-in key (added by a teammate)",
        ttl_days=INVITE_KEY_DAYS,
        actor=actor,
        reason=f"sign-in key for {member.email}",
    )
    session.commit()
    return {"member": _json(member), "signInKey": raw, "expiresInDays": INVITE_KEY_DAYS}


class MemberUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None


@router.patch("/members/{member_id}")
def update_member(
    member_id: str,
    body: MemberUpdate,
    session: Session = Depends(db),
    user: User = Depends(require("users")),
) -> dict[str, Any]:
    """Change a teammate's role, or deactivate them (their keys stop working with it)."""
    member = session.get(User, member_id)
    if member is None or member.org_id != user.org_id:
        raise HTTPException(404, "No such member.")
    if member.id == user.id:
        raise HTTPException(409, "You can't change your own role or remove yourself.")
    if body.role is not None and body.role not in OPERATOR_ROLES:
        raise HTTPException(422, f"Unknown role '{body.role}'.")
    before = _json(member)
    if body.role is not None:
        member.role = body.role
    if body.active is not None:
        member.active = body.active
    session.flush()
    record(
        session,
        "operator.user.updated",
        actor=user.email or user.id,
        reason="changed from Settings → Members",
        subject_type="user",
        subject_id=member.id,
        before=before,
        after=_json(member),
    )
    session.commit()
    return _json(member)
