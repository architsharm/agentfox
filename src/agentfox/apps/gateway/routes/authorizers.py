"""The workspace's own access checks, asked before a tool call runs.

* ``GET /api/authorizers`` lists them (never a credential, only whether one is set).
* ``POST /api/authorizers`` registers or updates one by key.
* ``POST /api/authorizers/{key}/enabled`` switches one on or off.
* ``POST /api/authorizers/{key}/test`` asks it about one example call. Records nothing.
* ``DELETE /api/authorizers/{key}`` removes one.

Changing who may do what is the identity family's call, as granting tools is.
See `platform/identity/authorizer.py` for what is sent and what is accepted back.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.core.crypto import EncryptionNotConfigured
from agentfox.core.models import User
from agentfox.platform.identity import authorizer as authz
from agentfox.platform.ledger import chain

router = APIRouter(prefix="/api", tags=["authorizers"])


class AuthorizerIn(authz.AuthorizerSpec):
    #: Write-only. Omitted keeps the stored one; `clear_secret` removes it.
    auth_secret: str | None = None
    clear_secret: bool = False


@router.get("/authorizers")
def get_authorizers(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "authorizers": [authz.to_json(r) for r in authz.list_authorizers(session)],
        "timeout_ms": {"min": authz.MIN_TIMEOUT_MS, "max": authz.MAX_TIMEOUT_MS},
    }


@router.post("/authorizers", status_code=201)
def post_authorizer(
    payload: AuthorizerIn,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    """Register (or update) an access-check endpoint.

    409 when this deployment may not reach the address (egress off for a public
    one; a private one without `outbound_allow_private_hosts`; link-local never);
    503 when a credential is given but this deployment cannot encrypt it.
    """
    refused = authz.egress_refusal(payload.url)
    if refused:
        raise HTTPException(409, refused)
    if payload.auth_secret and not payload.auth_header:
        raise HTTPException(400, "a credential needs the header it is sent in")
    secret = "" if payload.clear_secret else payload.auth_secret
    spec = authz.AuthorizerSpec(**payload.model_dump(exclude={"auth_secret", "clear_secret"}))
    try:
        row, _ = authz.save_authorizer(session, spec, secret=secret, actor=user.email or user.id)
    except EncryptionNotConfigured as exc:
        raise HTTPException(
            503,
            "this deployment cannot store credentials (AGENTFOX_TOKEN_ENCRYPTION_KEY "
            "is unset); it fails closed rather than storing one unencrypted",
        ) from exc
    authz.clear_cache()
    return {"authorizer": authz.to_json(row)}


class ToggleIn(BaseModel):
    enabled: bool
    reason: str = ""


@router.post("/authorizers/{key}/enabled")
def toggle_authorizer(
    key: str,
    payload: ToggleIn,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    row = authz.get_authorizer(session, key)
    if row is None:
        raise HTTPException(404, f"no access check '{key}'")
    row.enabled = payload.enabled
    session.flush()
    chain.append(
        session,
        "authorizer.enabled" if payload.enabled else "authorizer.disabled",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="external_authorizer",
        subject_id=row.id,
        payload={"key": key, "reason": payload.reason},
    )
    authz.clear_cache()
    return {"authorizer": authz.to_json(row)}


@router.delete("/authorizers/{key}")
def remove_authorizer(
    key: str, session: Session = Depends(db), user: User = Depends(require("identity"))
) -> dict[str, Any]:
    row = authz.get_authorizer(session, key)
    if row is None:
        raise HTTPException(404, f"no access check '{key}'")
    authz.delete_authorizer(session, row, actor=user.email or user.id)
    authz.clear_cache()
    return {"deleted": key}


class TestIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    groups: list[str] = Field(default_factory=list)
    agent: str = "example-agent"
    tool: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/authorizers/{key}/test")
def test_authorizer(
    key: str,
    payload: TestIn,
    session: Session = Depends(db),
    _user: User = Depends(require("identity")),
) -> dict[str, Any]:
    """Ask the access check about one example call and show its answer."""
    row = authz.get_authorizer(session, key)
    if row is None:
        raise HTTPException(404, f"no access check '{key}'")
    body = {
        "subject": payload.subject,
        "groups": payload.groups,
        "attributes": {},
        "agent": payload.agent,
        "tool": payload.tool,
        "impact": "unknown",
        "arguments": payload.arguments,
        "environment": "test",
    }
    try:
        allowed, reason = authz.call(row, body)
    except authz.AuthorizerUnavailable as exc:
        return {"ok": False, "error": str(exc), "fail_mode": row.fail_mode}
    return {"ok": True, "allowed": allowed, "reason": reason}
