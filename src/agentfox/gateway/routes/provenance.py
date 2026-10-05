"""P8 — source authority over HTTP.

This pillar shipped with a working engine and **no interface at all**: registering a
source was a Python call, so the only people who could use it were people willing to
import our package and write code against it. A control nobody can reach is not a
control, and it is the reason the audit's usability table concluded that the things
which are trivial are the things that observe while the things that protect are
expert-only.

The tiering decision is the part a business actually has to make — *which of our
sources are systems of record, and which is someone's personal notebook* — so it needs
to be answerable by an operator with a terminal, not only by whoever owns the codebase.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...context_integrity import chunk_quality, document_quality
from ...crypto import DecryptionFailed, EncryptionNotConfigured
from ...models import SourceConnection, SourceRecord, User
from ...provenance import (
    CONNECTION_KINDS,
    TIERS,
    assess_provenance,
    freshness_breach,
    register_connection,
    register_source,
    validate_source,
)
from ..deps import current_user, db, require

router = APIRouter(prefix="/api/sources", tags=["provenance"])


class SourceIn(BaseModel):
    key: str = Field(description="The identifier the retriever emits — URI, doc id, table.")
    title: str = ""
    tier: str = Field("unverified", description=" | ".join(TIERS))
    owner: str | None = None
    domain: str | None = Field(None, description="Corpus this belongs to, e.g. 'finance'.")
    updated_at_source: dt.datetime | None = None
    freshness_sla_hours: int | None = None
    deprecated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.put("", status_code=201)
def upsert(
    payload: SourceIn,
    session: Session = Depends(db),
    _user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Register or re-tier a source."""
    try:
        record = register_source(
            session,
            payload.key,
            title=payload.title,
            tier=payload.tier,
            owner=payload.owner,
            domain=payload.domain,
            updated_at_source=payload.updated_at_source,
            freshness_sla_hours=payload.freshness_sla_hours,
            deprecated=payload.deprecated,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _json(record)


@router.get("")
def list_sources(
    tier: str | None = None,
    domain: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    stmt = select(SourceRecord).order_by(SourceRecord.tier, SourceRecord.key)
    if tier:
        stmt = stmt.where(SourceRecord.tier == tier)
    if domain:
        stmt = stmt.where(SourceRecord.domain == domain)
    records = list(session.scalars(stmt))
    connection_kinds = {
        c.source_key: c.kind
        for c in session.scalars(
            select(SourceConnection).where(
                SourceConnection.source_key.in_([r.key for r in records])
            )
        )
    }
    return {
        "sources": [_json(r, connection_kind=connection_kinds.get(r.key)) for r in records],
        "tiers": list(TIERS),
        "counts": {t: sum(1 for r in records if r.tier == t) for t in TIERS},
    }


@router.get("/health")
def health(session: Session = Depends(db), _user: User = Depends(current_user)) -> dict[str, Any]:
    """Which registered sources are stale, deprecated, or unowned.

    The question an operator actually has is not "what is registered" but "what is
    rotting" — a tiering exercise done once and never revisited is worse than none,
    because the tier says authoritative long after the content stopped being so.
    """
    records = list(session.scalars(select(SourceRecord)))
    stale, deprecated, unowned = [], [], []
    for record in records:
        breach = freshness_breach(record)
        if breach:
            stale.append(breach)
        if record.deprecated:
            deprecated.append(record.key)
        if not record.owner:
            unowned.append(record.key)
    return {
        "registered": len(records),
        "stale": stale,
        "deprecated": deprecated,
        "unowned": unowned,
        "healthy": len(records) - len({*(b["source"] for b in stale), *deprecated}),
    }


class AssessIn(BaseModel):
    answer: str
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    agent_domain: str | None = None


@router.post("/assess")
def assess(
    payload: AssessIn,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Would this answer, from these sources, pass?

    A dry run against real retrieval output, so a team can see what the control would
    say before wiring it into their request path.
    """
    return assess_provenance(
        session, payload.answer, payload.chunks, agent_domain=payload.agent_domain
    ).to_json()


class ContextCheckIn(BaseModel):
    #: A single document's extracted text, e.g. what a loader just pulled from a PDF.
    text: str = ""
    #: Or a list of chunks as they would reach the retriever — checked for the
    #: assembly-level defects `document_quality` can't see (duplicates, near-empty
    #: chunks, a boundary cut mid-sentence).
    chunks: list[str] = Field(default_factory=list)
    source_key: str = ""


@router.post("/context-check")
def context_check(payload: ContextCheckIn, _user: User = Depends(current_user)) -> dict[str, Any]:
    """P14 — would this document or chunk set be fit to enter the corpus?

    A dry run against pasted or re-fetched text, in the same spirit as `/assess`:
    the ingestion/chunk quality gate (`context_integrity.py`) existed with no route
    at all — this is deliberately the lightweight wiring rather than an inline
    retrieval-path gate, so a team can check a document before deciding whether to
    build that gate at all.
    """
    if not payload.text and not payload.chunks:
        raise HTTPException(400, "provide 'text' or 'chunks' to check")
    result: dict[str, Any] = {}
    if payload.text:
        result["document"] = document_quality(payload.text, source_key=payload.source_key).to_json()
    if payload.chunks:
        findings = chunk_quality(payload.chunks)
        result["chunks"] = {
            "count": len(payload.chunks),
            "findings": [f.to_json() for f in findings],
        }
    return result


@router.delete("/{key:path}")
def deprecate(
    key: str,
    hard: bool = Query(False, description="Delete rather than mark deprecated."),
    session: Session = Depends(db),
    _user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Retire a source. Deprecates by default rather than deleting.

    A deleted source silently becomes *unverified* again — the default for anything
    unregistered — where a deprecated one keeps raising a finding every time an answer
    is grounded in it. Losing that signal is exactly the wrong outcome for a source you
    retired because it was wrong.
    """
    record = session.scalar(select(SourceRecord).where(SourceRecord.key == key))
    if record is None:
        raise HTTPException(404, f"unknown source '{key}'")
    if hard:
        session.delete(record)
        return {"deleted": key}
    record.deprecated = True
    session.flush()
    return _json(record)


@router.post("/{key:path}/validate")
def validate(
    key: str,
    session: Session = Depends(db),
    _user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Actually fetch the source and check its content, rather than trust the tier.

    A tier is a claim a human made once. This is us going and looking: fetching the
    URL, hashing what came back, and flagging when it's changed since the last check
    — or reporting honestly that the key isn't a URL at all and can't be checked this
    way.
    """
    try:
        return validate_source(session, key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


class ConnectionIn(BaseModel):
    key: str = Field(description="Must match an already-registered source's key.")
    kind: str = Field(description=" | ".join(CONNECTION_KINDS))
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "database: dialect, host, port, database, username, check_table (optional). "
            "api: base_url, auth_header (default 'Authorization'), auth_prefix (default 'Bearer ')."
        ),
    )
    credential: str | None = Field(
        None,
        description="The raw password or token — encrypted immediately, never stored in the clear.",
    )


@router.post("/connections", status_code=201)
def connect(
    payload: ConnectionIn,
    session: Session = Depends(db),
    _user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Attach a real connector to a registered source — a database or an
    authenticated enterprise API — so `validate` can check it for real instead
    of assuming every source is a plain fetchable URL.
    """
    try:
        connection = register_connection(
            session,
            payload.key,
            kind=payload.kind,
            config=payload.config,
            credential=payload.credential,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except EncryptionNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except DecryptionFailed as exc:
        raise HTTPException(500, str(exc)) from exc
    return _connection_json(connection)


def _connection_json(connection: SourceConnection) -> dict[str, Any]:
    return {
        "source_key": connection.source_key,
        "kind": connection.kind,
        "config": connection.config_json,
        "has_credential": bool(connection.credential_encrypted),
    }


def _kwargs(item: SourceIn) -> dict[str, Any]:
    return {
        "title": item.title,
        "tier": item.tier,
        "owner": item.owner,
        "domain": item.domain,
        "updated_at_source": item.updated_at_source,
        "freshness_sla_hours": item.freshness_sla_hours,
        "deprecated": item.deprecated,
        "metadata": item.metadata,
    }


def _json(record: SourceRecord, *, connection_kind: str | None = None) -> dict[str, Any]:
    return {
        "key": record.key,
        "title": record.title,
        "tier": record.tier,
        "owner": record.owner,
        "domain": record.domain,
        "updated_at_source": (
            record.updated_at_source.isoformat() if record.updated_at_source else None
        ),
        "freshness_sla_hours": record.freshness_sla_hours,
        "deprecated": record.deprecated,
        "is_seed": record.is_seed,
        "stale": bool(freshness_breach(record)),
        "content_hash": record.content_hash,
        "last_validated_at": (
            record.last_validated_at.isoformat() if record.last_validated_at else None
        ),
        "last_validation_status": record.last_validation_status,
        #: None means "plain URL or unfetchable key" — no connection registered.
        "connection_kind": connection_kind,
    }
