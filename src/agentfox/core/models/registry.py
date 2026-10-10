"""Pillar 1 — discovery and the agent registry: agents, their controls, tools, MCP
servers, lineage and discovery findings.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin, utcnow

if TYPE_CHECKING:
    # Resolved by name through the mapper registry: identity.py imports this module.
    from agentfox.core.models.identity import Identity


class Agent(Base, TimestampMixin):
    """Created by explicit registration or on first observation."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="ux_agents_org_slug"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.agent_id)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    owner_email: Mapped[str | None] = mapped_column(String(200))
    owner_team: Mapped[str | None] = mapped_column(String(120))
    environment: Mapped[str] = mapped_column(String(32), default="production")
    # EU AI Act aligned tiering.
    risk_tier: Mapped[str] = mapped_column(String(24), default="limited")
    framework: Mapped[str | None] = mapped_column(String(64))  # auto-detected
    status: Mapped[str] = mapped_column(String(24), default="active")
    registered: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when a repo scan proposed this agent (status="draft") rather than it being
    # registered directly — lets the review UI show why it showed up.
    source_scan_run_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("scan_runs.id"), index=True
    )
    # Set for agents onboarded via the hosted-API path rather than a repo scan —
    # a live endpoint we point at instead of source we're given.
    endpoint_url: Mapped[str | None] = mapped_column(String(500))
    docs_url: Mapped[str | None] = mapped_column(String(500))
    openapi_spec_url: Mapped[str | None] = mapped_column(String(500))
    declared_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    declared_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Set only by `agentfox admin seed` — a UX audit found seed/demo agents were
    # indistinguishable from a real customer's own registrations anywhere in the UI.
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)

    identities: Mapped[list[Identity]] = relationship(back_populates="agent")

    @property
    def is_owned(self) -> bool:
        """An unowned agent is a reportable compliance finding."""
        return bool(self.owner_email)


class AgentControl(Base, TimestampMixin):
    """Kill switch and quarantine.

    Checked before anything else in the request path. Two states beyond `active`:

    * ``quarantined`` — the agent may not act. Every request is blocked, but the
      record is kept and the agent can be resumed. This is the state you want during
      an investigation.
    * ``killed`` — the same block, with the stronger operational meaning. Kept
      separate because "we are looking into it" and "stop this now" are different
      conversations, and an auditor will ask which one was declared.

    Both are reversible and both are audited. An irreversible kill switch is one
    nobody dares use.
    """

    __tablename__ = "agent_controls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("ctr"))
    agent_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agents.id"), unique=True, index=True
    )
    state: Mapped[str] = mapped_column(String(24), default="active")
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(String(120))
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    previous_state: Mapped[str | None] = mapped_column(String(24))
    #: The agent's circuit breaker: its settings and its state (closed, open, probing).
    #: NULL means the defaults, never tripped. See `runtime.enforcement.breaker`.
    breaker_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    @property
    def blocking(self) -> bool:
        return self.state in ("quarantined", "killed")


class Tool(Base, TimestampMixin):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("org_id", "key", name="ux_tools_org_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.tool_id)
    key: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(32), default="function")
    # The axis policy reasons over. `irreversible` is the class that warrants HITL.
    impact: Mapped[str] = mapped_column(String(24), default="read")
    # The tool's input schema. May carry `x-agentfox-impact-source: inferred` (a JSON
    # Schema vendor keyword, ignored by validators) — see
    # `registry.service.impact_source_of`.
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mcp_server_id: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    # Cascade analysis (effects.cascade_risk): declared downstream effects this
    # tool's own call sets off (a DB trigger, a webhook, a fan-out) — the graph
    # cascade_risk() walks. Undeclared triggers stay invisible by design (see that
    # function's own docstring); this column is how an operator declares one.
    triggers_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Whether values copied out of this tool's output taint the arguments they
    #: land in. ``untrusted`` (the default) treats every tool result as content an
    #: attacker may have written.
    #: ``trusted`` is an operator's declaration that the output comes from a system
    #: of record they control — a CRM read — so a customer's email address copied
    #: from it into ``send_email`` is not untrusted input. See capabilities/detection/taint.py.
    output_trust: Mapped[str] = mapped_column(String(16), default="untrusted")
    #: The MCP impact annotations (`readOnlyHint`, `destructiveHint`, ...) as reviewed
    #: when the listing was registered or accepted; part of the pinned digest
    #: (`platform.registry.digest.tool_digest`). NULL: recorded before annotations were kept.
    annotations_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


#: Values of `Tool.output_trust`.
OUTPUT_TRUST_LEVELS = ("untrusted", "trusted")

#: Declared effect classes for a tool (`registry.service.EFFECT_CLASS_KEY`).
#: ``communication``: the tool's irreversible effect is a message leaving — an email,
#: a chat message, a notification — not data destroyed, money moved or state changed.
TOOL_EFFECT_CLASSES = ("communication",)


class McpServer(Base, TimestampMixin):
    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("org_id", "name", name="ux_mcp_servers_org_name"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.mcp_id)
    name: Mapped[str] = mapped_column(String(160))
    url: Mapped[str] = mapped_column(String(500), default="")
    transport: Mapped[str] = mapped_column(String(32), default="stdio")
    pinned_version: Mapped[str | None] = mapped_column(String(64))
    trust_level: Mapped[str] = mapped_column(String(24), default="untrusted")
    last_scanned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class McpToolSnapshot(Base, TimestampMixin):
    """Consecutive digests differing => schema drift finding."""

    __tablename__ = "mcp_tool_snapshots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("mts"))
    mcp_server_id: Mapped[str] = mapped_column(String(40), ForeignKey("mcp_servers.id"), index=True)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tools_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    digest: Mapped[str] = mapped_column(String(64))


class LineageEdge(Base, TimestampMixin):
    """Derived from observed spans, not declared config."""

    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint("org_id", "src_id", "dst_id", "relation", name="uq_lineage_edge"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("lin"))
    src_type: Mapped[str] = mapped_column(String(32))
    src_id: Mapped[str] = mapped_column(String(120), index=True)
    dst_type: Mapped[str] = mapped_column(String(32))
    dst_id: Mapped[str] = mapped_column(String(120), index=True)
    relation: Mapped[str] = mapped_column(String(32))
    observed_count: Mapped[int] = mapped_column(Integer, default=0)
    declared: Mapped[bool] = mapped_column(Boolean, default=False)
    first_observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Finding(Base, TimestampMixin):
    """The cross-pillar queue. Everything that needs a human eventually lands here."""

    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_triage", "status", "severity", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.finding_id)
    type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="open")
    title: Mapped[str] = mapped_column(String(300), default="")
    subject_type: Mapped[str] = mapped_column(String(32), default="agent")
    subject_id: Mapped[str | None] = mapped_column(String(120), index=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    control_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    suppressed_by: Mapped[str | None] = mapped_column(String(120))
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # A one-click, no-justification "resolved" is how a still-open critical finding
    # disappears from the executive view without anyone actually fixing it — this
    # pair makes resolving carry the same accountability suppressing already does.
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(120))
    #: Identity of the underlying problem, stable across occurrences, so a recurring
    #: condition is one finding with a count rather than a new row on every request.
    #: Nullable: findings raised before fingerprints existed simply have none.
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


#: Values of `Monitor.kind` the platform knows how to run. Other kinds can be
#: registered at import time (`agentfox.capabilities.monitoring.register_kind`).
MONITOR_KINDS = ("github_repo", "hosted_api", "mcp_server", "deployed_agent")


class Monitor(Base, TimestampMixin):
    """Something connected that AgentFox re-checks on its own, on a schedule.

    Created when a GitHub repository is connected and scanned, a hosted API's spec is
    scanned, or an MCP server is registered — or by hand. The `monitors.run` job runs
    every enabled monitor whose `next_run_at` has passed, diffs the result against
    `baseline_json` (the previous run's snapshot), raises findings for what appeared
    and closes the ones whose condition cleared. See `agentfox.capabilities.monitoring`.
    """

    __tablename__ = "monitors"
    __table_args__ = (
        UniqueConstraint("org_id", "kind", "target", name="ux_monitors_org_kind_target"),
        Index("ix_monitors_due", "enabled", "next_run_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("mon"))
    #: github_repo | hosted_api | mcp_server | deployed_agent (see MONITOR_KINDS).
    kind: Mapped[str] = mapped_column(String(32), index=True)
    #: What is watched: `owner/repo`, a spec URL, an MCP server name, a probe target id.
    target: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(200), default="")
    #: Kind-specific settings: a branch or ref, the endpoint a spec describes, ids.
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=6 * 3600)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: pending | baseline | ok | changed | failed — the outcome of the last run.
    status: Mapped[str] = mapped_column(String(16), default="pending")
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: What the last run found: counts, what changed, findings opened and closed.
    last_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The snapshot the next run is compared with. Empty until the first run.
    baseline_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(120), default="")


class AlertChannel(Base, TimestampMixin):
    """Where a tenant wants monitor alerts sent, beyond the deployment-wide webhook.

    One row per tenant per kind. Only `slack` today: an incoming-webhook URL, stored
    encrypted (it is a bearer credential for the channel).
    """

    __tablename__ = "alert_channels"
    __table_args__ = (UniqueConstraint("org_id", "kind", name="ux_alert_channels_org_kind"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("alc"))
    kind: Mapped[str] = mapped_column(String(16), default="slack")
    url_encrypted: Mapped[str] = mapped_column(Text, default="")
    min_severity: Mapped[str] = mapped_column(String(16), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(120), default="")
