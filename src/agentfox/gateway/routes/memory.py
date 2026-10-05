"""Read surface for memory write governance (P14, NOM-RTG-13, closes ASI06).

Writing goes through `POST /v1/guard/memory_write` (inline.py) — the same path
every other governed surface uses. This is the visibility half: what's actually
sitting in an agent's long-term memory, whether it's verified, and how long an
unverified entry has left before it decays.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Agent, MemoryEntry, User, utcnow
from ..deps import current_user, db, require

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _json(entry: MemoryEntry, agent_slug: str | None) -> dict[str, Any]:
    return {
        "id": entry.id,
        "agent": agent_slug,
        "subject": entry.subject,
        "content": entry.content,
        "taint_source": entry.taint_source,
        "provenance": entry.provenance,
        "decision_id": entry.decision_id,
        "verified_by": entry.verified_by,
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        "revoked_at": entry.revoked_at.isoformat() if entry.revoked_at else None,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
    }


@router.get("")
def list_entries(
    agent: str | None = Query(None),
    active_only: bool = Query(False),
    limit: int = Query(200, le=500),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    agent_id = None
    if agent:
        row = session.scalar(select(Agent).where(Agent.slug == agent))
        agent_id = row.id if row else "__none__"
    stmt = select(MemoryEntry).order_by(MemoryEntry.created_at.desc()).limit(limit)
    if agent_id:
        stmt = stmt.where(MemoryEntry.agent_id == agent_id)
    entries = list(session.scalars(stmt))
    agent_slugs = {
        a.id: a.slug
        for a in session.scalars(
            select(Agent).where(Agent.id.in_([e.agent_id for e in entries if e.agent_id]))
        )
    }
    return {
        "entries": [_json(e, agent_slugs.get(e.agent_id)) for e in entries],
        "total": len(entries),
        "unverified": sum(1 for e in entries if e.verified_by is None and e.active),
        "expired": sum(1 for e in entries if not e.active and e.revoked_at is None),
    }


@router.post("/{entry_id}/verify")
def verify_entry(
    entry_id: str,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """A human vouches for an entry — it stops decaying on the unverified TTL."""
    entry = session.get(MemoryEntry, entry_id)
    if entry is None:
        raise HTTPException(404, f"unknown memory entry '{entry_id}'")
    entry.verified_by = user.email
    entry.expires_at = None
    session.flush()
    agent = session.get(Agent, entry.agent_id) if entry.agent_id else None
    return _json(entry, agent.slug if agent else None)


@router.post("/{entry_id}/revoke")
def revoke_entry(
    entry_id: str,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Pull an entry immediately — the concrete fix for 'no way to find and
    remove a bad memory'."""
    entry = session.get(MemoryEntry, entry_id)
    if entry is None:
        raise HTTPException(404, f"unknown memory entry '{entry_id}'")
    entry.revoked_at = entry.revoked_at or utcnow()
    session.flush()
    agent = session.get(Agent, entry.agent_id) if entry.agent_id else None
    return _json(entry, agent.slug if agent else None)
