"""Pillar 5 — audit, observability and traceability: traces, spans, the hash-chained
audit log, jobs, evidence packages and retention.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TenantScoped, TimestampMixin, utcnow


class Trace(Base, TimestampMixin):
    __tablename__ = "traces"
    __table_args__ = (Index("ix_traces_agent_time", "agent_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.trace_id)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    agent_slug: Mapped[str | None] = mapped_column(String(120), index=True)
    session_id: Mapped[str | None] = mapped_column(String(120), index=True)
    environment: Mapped[str] = mapped_column(String(32), default="production")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="ok")
    verdict: Mapped[str] = mapped_column(String(16), default="allow", index=True)
    intent: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120))
    provider: Mapped[str | None] = mapped_column(String(64))
    token_usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class TraceLink(Base, TimestampMixin):
    """The join key between our decision and an external observability run.

    Deliberately a link table and not a copy of their span data. Their trace store is
    better than ours; duplicating it would make us a worse LangSmith. What nobody has
    is the *join*, so that is the only thing we keep.
    """

    __tablename__ = "trace_links"
    __table_args__ = (
        Index("ix_trace_links_external", "system", "external_trace_id"),
        Index("ix_trace_links_run", "system", "external_run_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.trace_link_id)
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    system: Mapped[str] = mapped_column(String(32))  # langsmith | langfuse | otel
    external_trace_id: Mapped[str] = mapped_column(String(200))
    external_run_id: Mapped[str | None] = mapped_column(String(200))
    project: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    # inbound: they called us and carried the id. outbound: we created the id.
    direction: Mapped[str] = mapped_column(String(16), default="inbound")


class Span(Base, TimestampMixin):
    """OpenLLMetry semantic conventions live in `attributes_json`."""

    __tablename__ = "spans"
    __table_args__ = (Index("ix_spans_trace_time", "trace_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.span_id)
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(24), default="llm")
    name: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="ok")
    error: Mapped[str | None] = mapped_column(Text)


class AuditEntry(Base, TenantScoped):
    """Append-only, hash-chained.

    There is intentionally no ``updated_at``, no ORM update path, and no delete
    endpoint. The chain is verified by :mod:`agentfox.platform.ledger.chain`, which is a pure
    function over exported rows so a third party can run it without our systems.
    """

    __tablename__ = "audit_entries"
    # The chain is per tenant, so `seq` is unique within an org rather than globally.
    # A single global chain would make tenant A's verification depend on tenant B's
    # entries — you cannot check a hash chain you are only allowed to see half of —
    # and A's evidence package would carry B's digests. One chain per tenant keeps
    # independent verifiability, which is the whole point of the chain.
    __table_args__ = (UniqueConstraint("org_id", "seq", name="uq_audit_org_seq"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("aud"))
    # `org_id` comes from TenantScoped. It was declared inline here once, which quietly
    # excluded the audit log — the single most sensitive table — from tenant filtering.
    seq: Mapped[int] = mapped_column(Integer, index=True)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_type: Mapped[str] = mapped_column(String(24), default="system")
    actor_id: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64), index=True)
    subject_type: Mapped[str] = mapped_column(String(32), default="")
    subject_id: Mapped[str | None] = mapped_column(String(120), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_digest: Mapped[str] = mapped_column(String(64))
    prev_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))


class AuditCheckpoint(Base, TimestampMixin):
    """Signed anchor. The key lives outside the application database."""

    __tablename__ = "audit_checkpoints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("ckp"))
    seq: Mapped[int] = mapped_column(Integer, index=True)
    digest: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    signature: Mapped[str] = mapped_column(String(128))
    key_id: Mapped[str] = mapped_column(String(64), default="local")


class Job(Base, TimestampMixin):
    """Deferred work, persisted so the dead letter is real public state
    across requests rather than in-process memory a serverless invocation throws
    away the moment it returns. Mirrors jobs.py's in-process Job/JobQueue shape —
    that module stays the reference implementation for local/offline use (`agentfox
    demo`, tests); this is the swappable production backend behind the same
    enqueue/run/retry/dead-letter interface, the same seam pattern already used for
    the policy engine (native vs OPA) and entitlement (native vs OpenFGA).
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_enqueued", "status", "enqueued_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.job_id)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    enqueued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: Backoff: a retried job is not eligible again until this time.
    available_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the current attempt began, so a job stuck in `running` can be recovered.
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: The recurring schedule that enqueued this job, if any.
    schedule_id: Mapped[str | None] = mapped_column(String(40), index=True)


class EvidencePackage(Base, TimestampMixin):
    __tablename__ = "evidence_packages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.evidence_id)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    built_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    chain_verification_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    code_version: Mapped[str] = mapped_column(String(40), default="")
    catalog_version: Mapped[str] = mapped_column(String(40), default="")
    path: Mapped[str] = mapped_column(String(500), default="")


class RetentionPolicy(Base, TimestampMixin):
    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint("org_id", "data_class", name="ux_retention_policies_org_data_class"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("ret"))
    data_class: Mapped[str] = mapped_column(String(64))
    retain_days: Mapped[int] = mapped_column(Integer, default=365)
    redact_fields: Mapped[list[str]] = mapped_column(JSON, default=list)


class LegalHold(Base, TimestampMixin):
    __tablename__ = "legal_holds"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("hld"))
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    placed_by: Mapped[str] = mapped_column(String(120), default="")
    placed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
