"""Pillar 4 — evaluation and reliability: suites, runs, baselines, drift, SLOs and
red-team campaigns.
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
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin


class EvalSuite(Base, TimestampMixin):
    __tablename__ = "eval_suites"
    __table_args__ = (UniqueConstraint("org_id", "key", name="ux_eval_suites_org_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.eval_id)
    key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class EvalCase(Base, TimestampMixin):
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("cse"))
    suite_id: Mapped[str] = mapped_column(String(40), ForeignKey("eval_suites.id"), index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    split: Mapped[str] = mapped_column(String(24), default="test")
    # "promote this production failure to a test case".
    source_trace_id: Mapped[str | None] = mapped_column(String(40))
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class EvalRun(Base, TimestampMixin):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.run_id)
    suite_id: Mapped[str] = mapped_column(String(40), index=True)
    target_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scorer_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    baseline_run_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    runner: Mapped[str] = mapped_column(String(24), default="native")
    mode: Mapped[str] = mapped_column(String(16), default="offline")  # offline | online
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    code_version: Mapped[str] = mapped_column(String(40), default="")


class EvalResult(Base, TimestampMixin):
    __tablename__ = "eval_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id", "scorer_key", name="uq_eval_result"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("res"))
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    scorer_key: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)


class EvalAnnotation(Base, TimestampMixin):
    """Human review of a borderline eval result (score near the scorer's own
    threshold, or scorers disagreeing on the same case). A pass/fail scorer
    verdict close to its own cutoff, or two scorers splitting on the same case, is
    exactly the shape a human should look at rather than trust blindly — this is
    the queue for that, mirroring Finding's own "the cross-pillar queue" pattern
    (a status/note/actor triple) rather than inventing a new shape.
    """

    __tablename__ = "eval_annotations"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "eval_result_id", "annotator", name="ux_eval_annotations_org_result_annotator"
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("ann"))
    eval_result_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("eval_results.id"), index=True
    )
    verdict: Mapped[str] = mapped_column(String(16), default="agree")  # agree | disagree
    note: Mapped[str] = mapped_column(Text, default="")
    annotator: Mapped[str] = mapped_column(String(120), default="")


class Baseline(Base, TimestampMixin):
    """Regression gate semantics live here."""

    __tablename__ = "baselines"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("bsl"))
    suite_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120), default="main")
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DriftWindow(Base, TimestampMixin):
    __tablename__ = "drift_windows"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("drf"))
    agent_id: Mapped[str] = mapped_column(String(40), index=True)
    scorer_key: Mapped[str] = mapped_column(String(64))
    window_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    n: Mapped[int] = mapped_column(Integer, default=0)
    mean: Mapped[float] = mapped_column(Float, default=0.0)
    p50: Mapped[float] = mapped_column(Float, default=0.0)
    p95: Mapped[float] = mapped_column(Float, default=0.0)
    psi: Mapped[float | None] = mapped_column(Float)
    ks: Mapped[float | None] = mapped_column(Float)
    baseline_window_id: Mapped[str | None] = mapped_column(String(40))
    drifted: Mapped[bool] = mapped_column(Boolean, default=False)


class SLO(Base, TimestampMixin):
    __tablename__ = "slos"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("slo"))
    agent_id: Mapped[str] = mapped_column(String(40), index=True)
    scorer_key: Mapped[str] = mapped_column(String(64))
    objective: Mapped[str] = mapped_column(String(300), default="")
    window: Mapped[str] = mapped_column(String(24), default="7d")
    target: Mapped[float] = mapped_column(Float, default=0.9)
    current: Mapped[float | None] = mapped_column(Float)
    error_budget_remaining: Mapped[float | None] = mapped_column(Float)


class RedTeamCampaign(Base, TimestampMixin):
    __tablename__ = "redteam_campaigns"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("rtc"))
    name: Mapped[str] = mapped_column(String(200), default="")
    runner: Mapped[str] = mapped_column(String(24), default="native")
    probes: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class RedTeamFinding(Base, TimestampMixin):
    __tablename__ = "redteam_findings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("rtf"))
    campaign_id: Mapped[str] = mapped_column(String(40), index=True)
    probe: Mapped[str] = mapped_column(String(120))
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)
    owasp_id: Mapped[str | None] = mapped_column(String(24))
    atlas_id: Mapped[str | None] = mapped_column(String(32))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProbeTarget(Base, TimestampMixin):
    """A deployed agent's live endpoint that scheduled red-team probes may be sent to.

    Probing sends adversarial input to something that is running, so nothing here
    happens by default: a target is created **disabled**, and only an explicit opt-in
    (``enabled=True``) recorded with who gave it, when, and the warning they
    acknowledged lets `evaluation.live_probes` send anything. Changing the URL clears
    the opt-in, because the consent was for that host.

    Volume is bounded per target (``max_probes_per_run``, ``rate_limit_per_minute``,
    ``interval_seconds``) and again by hard caps in `evaluation.live_probes` that a
    row cannot exceed. Campaigns are written to ``redteam_campaigns`` with
    ``runner="live"`` and ``target_json.source="live_probe"``.
    """

    __tablename__ = "probe_targets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("prb"))
    agent_slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    #: "http" (POST {message} -> {reply, tool_calls, blocked}) or "in_process" (an
    #: agent governed by this gateway, run through the enforcement path).
    adapter: Mapped[str] = mapped_column(String(24), default="http")
    url: Mapped[str | None] = mapped_column(String(500))
    #: The one host the opt-in covers. A request to any other host is refused.
    registered_host: Mapped[str | None] = mapped_column(String(255))
    #: Model for the in-process adapter.
    model: Mapped[str | None] = mapped_column(String(64))
    #: Encrypted ``Authorization`` header value for the http adapter (core.crypto).
    auth_header_ciphertext: Mapped[str | None] = mapped_column(Text)
    #: ``forbidden_tools`` / ``leak_markers`` / ``probes``: what an escape looks like
    #: for this agent, and which probes to send.
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_in_by: Mapped[str | None] = mapped_column(String(200))
    opted_in_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    opt_in_acknowledgement: Mapped[str | None] = mapped_column(Text)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    max_probes_per_run: Mapped[int] = mapped_column(Integer, default=12)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=20.0)
    next_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_campaign_id: Mapped[str | None] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(200), default="")
