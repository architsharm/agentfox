"""Inter-agent message security over HTTP (NOM-IAM-08, closes ASI07).

Message evaluation itself is `POST /v1/guard/agent_message` (inline.py), same
pattern as every other governed surface. This is the key-management and
visibility half: minting a signing key an agent holds onto, and the log of
what actually got evaluated on the ``agent_message`` surface.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.capabilities.containment.agent_messaging import mint_signing_key
from agentfox.core.models import AgentMessageLog, AgentSigningKey, User

router = APIRouter(prefix="/api", tags=["agent-messaging"])


@router.post("/agents/{slug}/signing-key")
def mint_key(
    slug: str,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Mint (or rotate) an agent's HMAC signing key. Shown once — like an API
    token, nothing after this call can retrieve the raw value again."""
    agent = get_agent_or_404(session, slug)
    key, raw = mint_signing_key(session, agent.id, created_by=user.email)
    return {"agent": slug, "key": raw, "created_at": key.created_at.isoformat()}


@router.get("/agents/{slug}/signing-key")
def key_status(
    slug: str,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    key = session.scalar(select(AgentSigningKey).where(AgentSigningKey.agent_id == agent.id))
    return {
        "agent": slug,
        "has_key": key is not None and key.revoked_at is None,
        "created_at": key.created_at.isoformat() if key else None,
    }


@router.get("/agent-messages")
def list_messages(
    sender: str | None = None,
    limit: int = 200,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    stmt = (
        select(AgentMessageLog).order_by(AgentMessageLog.created_at.desc()).limit(min(limit, 500))
    )
    if sender:
        stmt = stmt.where(AgentMessageLog.sender_slug == sender)
    rows = list(session.scalars(stmt))
    return {
        "messages": [
            {
                "id": m.id,
                "sender": m.sender_slug,
                "recipient": m.recipient_slug,
                "signed": m.signed,
                "signature_valid": m.signature_valid,
                "agent_card_match": m.agent_card_match,
                "decision_id": m.decision_id,
                "trace_id": m.trace_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
        "total": len(rows),
        "unsigned": sum(1 for m in rows if not m.signed),
        "invalid_signature": sum(1 for m in rows if m.signature_valid is False),
        "agent_card_mismatch": sum(1 for m in rows if not m.agent_card_match),
    }
