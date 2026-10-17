"""Pillar 6 — policy and compliance: policies and their immutable versions, bindings,
canaries, decisions, simulations, controls and framework status.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin, utcnow


class Policy(Base, TimestampMixin):
    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("org_id", "key", name="ux_policies_org_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.policy_id)
    key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(24), default="declarative")  # declarative | rego
    owner: Mapped[str | None] = mapped_column(String(120))
    # A scan-proposed policy: exists with a version but deliberately unbound (inert)
    # until a human approves it (see routes/integrations.py). Cleared on approval.
    proposed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_scan_run_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("scan_runs.id"), index=True
    )


class PolicyVersion(Base, TimestampMixin):
    """Immutable. Never mutated in place."""

    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version", name="uq_policy_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.policy_version_id)
    policy_id: Mapped[str] = mapped_column(String(40), ForeignKey("policies.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[str] = mapped_column(Text, default="")
    compiled_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    author: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str] = mapped_column(Text, default="")


class PolicyBinding(Base, TimestampMixin):
    """Observe-by-default is the mitigation for false blocks."""

    __tablename__ = "policy_bindings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("bnd"))
    policy_version_id: Mapped[str] = mapped_column(String(40), index=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(16), default="observe")
    # Where this binding sits in the hierarchy. Defaults keep pre-hierarchy
    # bindings behaving exactly as before: one org-wide layer that extends nothing.
    level: Mapped[str] = mapped_column(String(16), default="org")
    scope_id: Mapped[str] = mapped_column(String(160), default="*")
    compose: Mapped[str] = mapped_column(String(16), default="extend")
    effective_from: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    effective_to: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PolicyCanary(Base, TimestampMixin):
    """Agent canary rollout by version, with health gates and automated rollback.

    A running canary sits *on top of* the current binding rather than replacing it:
    ``stable_version_id`` is what the binding already points to, ``candidate_version_id``
    is the version being tried. Traffic is split per request by ``percent`` (see
    :func:`policy.canary.pick_version_id`); which cohort a given ``Decision`` landed in
    is never stored redundantly — it is recovered after the fact by checking whether its
    ``policy_version_id`` equals the stable or the candidate id, which stays true for the
    whole lifetime of a completed or rolled-back canary because versions are immutable.
    """

    __tablename__ = "policy_canaries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.policy_canary_id)
    policy_id: Mapped[str] = mapped_column(String(40), ForeignKey("policies.id"), index=True)
    stable_version_id: Mapped[str] = mapped_column(String(40))
    candidate_version_id: Mapped[str] = mapped_column(String(40))
    #: The rollout ladder, e.g. [10, 25, 50, 100]. `percent` is always steps[step_index].
    steps: Mapped[list[int]] = mapped_column(JSON, default=list)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    percent: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(16), default="rolling", index=True)
    #: Health gate: automatic rollback fires when the candidate cohort's block rate
    #: exceeds the stable cohort's by more than this, once both have `min_sample`.
    max_block_rate_delta: Mapped[float] = mapped_column(Float, default=0.15)
    min_sample: Mapped[int] = mapped_column(Integer, default=20)
    started_by: Mapped[str | None] = mapped_column(String(120))
    rollback_reason: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: The other half of the gate. A candidate that blocks *less* than stable by more
    #: than this is rolled back too: a quietly loosened control is the failure an
    #: automated change must never be able to ship.
    max_block_rate_drop: Mapped[float] = mapped_column(Float, default=0.15)
    #: Minimum time at each step before advancing, so a burst of calls cannot ramp a
    #: canary to 100% before real traffic has had a chance to disagree with it.
    min_dwell_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_advanced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_agent_verdict", "agent_id", "verdict", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.decision_id)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    span_id: Mapped[str | None] = mapped_column(String(40))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    identity_id: Mapped[str | None] = mapped_column(String(40))
    surface: Mapped[str] = mapped_column(String(24), default="input")
    tool_key: Mapped[str | None] = mapped_column(String(160))
    verdict: Mapped[str] = mapped_column(String(16), default="allow", index=True)
    rules_fired_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # Always the exact version(s) in force at decision time — NOM-AUD-02.
    # `policy_version_id` is the version that produced the winning verdict;
    # `policy_version_ids` is every version evaluated, because a decision is only
    # reproducible if you know the whole set that was in force, not just the winner.
    policy_version_id: Mapped[str | None] = mapped_column(String(40))
    policy_version_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    detector_run_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    taint_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str] = mapped_column(String(16), default="observe")
    approval_id: Mapped[str | None] = mapped_column(String(40))


class SimulationRun(Base, TimestampMixin):
    """Replay recorded traffic against a candidate policy."""

    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("sim"))
    policy_id: Mapped[str | None] = mapped_column(String(40))
    candidate_body: Mapped[str] = mapped_column(Text, default="")
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    replayed_count: Mapped[int] = mapped_column(Integer, default=0)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_by: Mapped[str] = mapped_column(String(120), default="")


class Control(Base, TimestampMixin):
    """The reference control catalog. Conceptually one shared, versioned set (the
    "one control set mapped to seven frameworks" claim on the Compliance page) — but
    every mapped class must be tenant-scoped (`assert_tenant_safe`), so each org gets
    its own copy, synced from the same YAML. That's why `key` alone can't be globally
    unique: two orgs syncing the same catalog would collide on each other's rows. The
    real uniqueness is (org_id, key)."""

    __tablename__ = "controls"
    __table_args__ = (UniqueConstraint("org_id", "key", name="ux_controls_org_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("ctl"))
    key: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(300))
    objective: Mapped[str] = mapped_column(Text, default="")
    family: Mapped[str] = mapped_column(String(16))
    pillar: Mapped[int] = mapped_column(Integer)
    implemented_by: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    status_rule_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    catalog_version: Mapped[str] = mapped_column(String(32), default="0.1.0-draft")


class FrameworkMapping(Base, TimestampMixin):
    """`draft` mappings ship in evidence packages chip-labeled `DRAFT — UNVERIFIED /
    NOT LEGAL ADVICE` rather than excluded."""

    __tablename__ = "framework_mappings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("fmp"))
    control_key: Mapped[str] = mapped_column(String(32), index=True)
    framework: Mapped[str] = mapped_column(String(32), index=True)
    reference: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(16), default="draft")
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ControlReview(Base, TimestampMixin):
    """A person's attestation of one control against one framework, at a point in time.

    Computed status (`ControlStatus`) says what the telemetry found; this says what a
    named reviewer concluded after looking at that evidence. The evidence they looked
    at is frozen in `evidence_json`, so the attestation can be argued with later, and
    it lapses at `expires_at`: an attestation nobody has renewed is not a current one.
    Rows are never updated. A new review supersedes the previous one.
    """

    __tablename__ = "control_reviews"
    __table_args__ = (Index("ix_ctlreview_key_fw_time", "control_key", "framework", "reviewed_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("crv"))
    control_key: Mapped[str] = mapped_column(String(32), index=True)
    framework: Mapped[str] = mapped_column(String(32), index=True)
    #: meets | partially_meets | does_not_meet | not_applicable
    outcome: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(120))
    reviewed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    #: The computed evidence the reviewer saw: status, rationale, rules, last fired.
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The audit-chain entry recording this review.
    audit_seq: Mapped[int | None] = mapped_column(Integer)


class ControlStatus(Base, TimestampMixin):
    """Computed from telemetry, never attested."""

    __tablename__ = "control_statuses"
    __table_args__ = (Index("ix_ctlstatus_key_time", "control_key", "computed_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("cst"))
    control_key: Mapped[str] = mapped_column(String(32), index=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="not_implemented")
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text, default="")


class RiskAssessment(Base, TimestampMixin):
    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("rsk"))
    agent_id: Mapped[str] = mapped_column(String(40), index=True)
    eu_ai_act_class: Mapped[str] = mapped_column(String(24), default="limited")
    inherent_risk: Mapped[str] = mapped_column(String(16), default="medium")
    residual_risk: Mapped[str] = mapped_column(String(16), default="medium")
    mitigations_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    answers_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assessor: Mapped[str] = mapped_column(String(120), default="")
    assessed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_review_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    signed_off_by: Mapped[str | None] = mapped_column(String(120))


class Obligation(Base, TimestampMixin):
    """The regulatory clock, as data rather than code."""

    __tablename__ = "obligations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("obl"))
    framework: Mapped[str] = mapped_column(String(32), index=True)
    reference: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    effective_date: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    applies_when_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="upcoming")
