"""The governed improvement loop: change proposals and job schedules."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin

#: Rows the one-open-proposal-per-problem index covers. Must list exactly
#: ``improvement.contract.OPEN``; tests/improvement/test_proposals_integrity.py holds the
#: two together.
PROPOSAL_OPEN_FINGERPRINT = (
    "fingerprint IS NOT NULL AND status IN ('proposed', 'proven', 'approved', 'canary', 'applied')"
)


class ChangeProposal(Base, TimestampMixin):
    """A proposed change to any piece of configuration, and everything that happened to it.

    The improvement loop never edits configuration directly. It files one of these,
    attaches the evidence that motivated it and the proof that it is safe, and the
    change then moves through a lifecycle a person can read: proposed, proven,
    approved, canary, applied, verified — or rejected, rolled back, superseded.

    ``direction`` is load-bearing. A change that loosens a control can never be applied
    by automation, whatever autonomy its class has earned; that rule lives in
    ``improvement.contract`` and is enforced where proposals are applied.
    """

    __tablename__ = "change_proposals"
    __table_args__ = (
        Index("ix_proposals_status_created", "status", "created_at"),
        # One open proposal per problem per tenant, enforced by the database so two
        # concurrent filings cannot both win. Closed proposals keep their fingerprint.
        Index(
            "ux_proposals_open_fingerprint",
            "org_id",
            "fingerprint",
            unique=True,
            sqlite_where=text(PROPOSAL_OPEN_FINGERPRINT),
            postgresql_where=text(PROPOSAL_OPEN_FINGERPRINT),
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("chp"))
    kind: Mapped[str] = mapped_column(String(48), index=True)
    #: Which loop produced it, e.g. "tuning.threshold", "grants.unused".
    source: Mapped[str] = mapped_column(String(64), default="")
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_ref: Mapped[str] = mapped_column(String(200), default="")
    scope_level: Mapped[str] = mapped_column(String(16), default="org")
    scope_id: Mapped[str] = mapped_column(String(200), default="*")
    title: Mapped[str] = mapped_column(String(300), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[str] = mapped_column(String(16), default="neutral")
    autonomy_level: Mapped[str] = mapped_column(String(4), default="L1")
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    #: Identity of the problem being fixed, so the same issue is one open proposal.
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    proof_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_effect_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    related_finding_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    proposed_by: Mapped[str] = mapped_column(String(120), default="")
    decided_by: Mapped[str | None] = mapped_column(String(120))
    #: The second person on a two-person decision (any loosening at org level).
    second_approver: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str] = mapped_column(Text, default="")
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_note: Mapped[str] = mapped_column(Text, default="")


class JobSchedule(Base, TimestampMixin):
    """Recurring work, per tenant. The cron drains queues; this is what fills them.

    A cron that only drains jobs someone already enqueued cannot run anything periodic;
    schedules are what let posture campaigns, drift checks, canary advancement and
    suppression hygiene run unattended.
    """

    __tablename__ = "job_schedules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("jsc"))
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_enqueued_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(120), default="")
