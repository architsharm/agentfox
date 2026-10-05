"""Persistence model for all six pillars.

Implements Appendix D. Three invariants are enforced here in code rather than by
convention, because they are the ones an auditor tests:

  * ``AuditEntry`` is append-only and hash-chained (P5-2). There is no update or
    delete path anywhere in the codebase.
  * ``PolicyVersion`` is immutable; every ``Decision`` binds the exact version in
    force at decision time (X-4).
  * ``Capability`` narrowing on delegation is validated at write time, not audited
    after the fact (P2-5).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from agentfox.core import ids


def as_aware(value: dt.datetime | None) -> dt.datetime | None:
    """Attach UTC to a datetime that lost its timezone in storage.

    SQLite has no timezone type, so a value written as aware comes back naive and
    comparing it to :func:`utcnow` raises. That turned every credential *with an
    expiry* into a 500 on the inline path — invisible until agent credentials were
    actually resolved there, because nothing else read the field.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[Any]: JSON}


class TenantScoped:
    """Carries the tenant key, and is the hook every isolation filter targets.

    Isolation is applied against *this class*, so inheriting it is what makes a model
    tenant-safe — and :func:`agentfox.core.tenancy.assert_tenant_safe` fails at import if
    any mapped class does not. That inverts the usual arrangement: instead of
    remembering to filter each new query, you cannot define a model that escapes the
    filter in the first place.
    """

    org_id: Mapped[str] = mapped_column(String(64), default="org_default", index=True)


class TenantExempt:
    """Marks the rare table that exists *before* there is a tenant to scope it to.

    The rule in :class:`TenantScoped` is the important one and this does not soften
    it: a model that simply forgets tenancy still fails at import. What this adds is
    a way to say "outside the tenant model, on purpose" that is impossible to do by
    accident — inheriting this mixin is not enough on its own, the table must also be
    named in :data:`TENANT_EXEMPT_TABLES` below, so the exemption cannot be granted
    without editing the one place that states the bar for granting it.

    The bar: a row here is readable by every tenant and by none, because no tenant
    filter applies to it. So the only rows that may live in such a table are rows that
    belong to *nobody* — never a customer's data under a different name.
    """


#: Tables allowed to sit outside tenant isolation, and why each one is allowed.
#:
#: Read this list as a security review: every entry is a table the filter in
#: ``tenancy.py`` does not touch. It is deliberately a hard-coded roster rather than
#: "whatever inherits the mixin", so adding a table to it is a diff a reviewer sees.
TENANT_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        # A waitlist signup is a stranger asking to be told when the hosted service
        # exists. There is no org to scope it to yet — creating one would be inventing
        # a tenant for someone who has not signed up for anything.
        "waitlist_signups",
    }
)


class TimestampMixin(TenantScoped):
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------------------------------------------------------------------------
# Pillar 1 — Discovery & Agent Registry
# ---------------------------------------------------------------------------


class Agent(Base, TimestampMixin):
    """P1-1, P1-4. Created by explicit registration or on first observation."""

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
    # EU AI Act aligned tiering (P6-3).
    risk_tier: Mapped[str] = mapped_column(String(24), default="limited")
    framework: Mapped[str | None] = mapped_column(String(64))  # P1-6, auto-detected
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
    # Set only by `agentfox seed` — a UX audit found seed/demo agents were
    # indistinguishable from a real customer's own registrations anywhere in the UI.
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)

    identities: Mapped[list[Identity]] = relationship(back_populates="agent")

    @property
    def is_owned(self) -> bool:
        """An unowned agent is a reportable compliance finding (P1-4)."""
        return bool(self.owner_email)


class AgentControl(Base, TimestampMixin):
    """PL-3 — kill switch and quarantine.

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
    # P9 cascade analysis (effects.cascade_risk): declared downstream effects this
    # tool's own call sets off (a DB trigger, a webhook, a fan-out) — the graph
    # cascade_risk() walks. Undeclared triggers stay invisible by design (see that
    # function's own docstring); this column is how an operator declares one.
    triggers_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: P3-4: whether values copied out of this tool's output taint the arguments they
    #: land in. ``untrusted`` (the default, and the behaviour before this column
    #: existed) treats every tool result as content an attacker may have written.
    #: ``trusted`` is an operator's declaration that the output comes from a system
    #: of record they control — a CRM read — so a customer's email address copied
    #: from it into ``send_email`` is not untrusted input. See guardrails/taint.py.
    output_trust: Mapped[str] = mapped_column(String(16), default="untrusted")


#: Values of `Tool.output_trust`.
OUTPUT_TRUST_LEVELS = ("untrusted", "trusted")


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
    """P1-5. Consecutive digests differing => schema drift finding."""

    __tablename__ = "mcp_tool_snapshots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("mts"))
    mcp_server_id: Mapped[str] = mapped_column(String(40), ForeignKey("mcp_servers.id"), index=True)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tools_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    digest: Mapped[str] = mapped_column(String(64))


class LineageEdge(Base, TimestampMixin):
    """P1-3. Derived from observed spans, not declared config."""

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


# ---------------------------------------------------------------------------
# Pillar 2 — Identity, Access & Authorization
# ---------------------------------------------------------------------------


class Identity(Base, TimestampMixin):
    """P2-1. The governed non-human identity."""

    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("org_id", "principal", name="ux_identities_org_principal"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.identity_id)
    agent_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("agents.id"), index=True)
    principal: Mapped[str] = mapped_column(String(160), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="agent")
    status: Mapped[str] = mapped_column(String(24), default="active")
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    posture: Mapped[str] = mapped_column(String(24), default="healthy")

    agent: Mapped[Agent | None] = relationship(back_populates="identities")
    capabilities: Mapped[list[Capability]] = relationship(back_populates="identity")
    credentials: Mapped[list[Credential]] = relationship(back_populates="identity")


class Credential(Base, TimestampMixin):
    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.credential_id)
    identity_id: Mapped[str] = mapped_column(String(40), ForeignKey("identities.id"), index=True)
    key_prefix: Mapped[str] = mapped_column(String(32), index=True)
    key_hash: Mapped[str] = mapped_column(String(256))
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[str | None] = mapped_column(String(40))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    identity: Mapped[Identity] = relationship(back_populates="credentials")

    @property
    def active(self) -> bool:
        if self.revoked_at:
            return False
        expires = as_aware(self.expires_at)
        if expires and expires < utcnow():
            return False
        return True


class Capability(Base, TimestampMixin):
    """P2-2. Tool-scoped least privilege with argument-level constraints."""

    __tablename__ = "capabilities"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.capability_id)
    identity_id: Mapped[str] = mapped_column(String(40), ForeignKey("identities.id"), index=True)
    tool_key: Mapped[str] = mapped_column(String(160))  # glob allowed
    actions: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["*"])
    constraints_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    # P3-4: the highest taint level permitted to reach this tool's arguments.
    max_taint: Mapped[str] = mapped_column(String(24), default="user")
    granted_by: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    identity: Mapped[Identity] = relationship(back_populates="capabilities")


class AccessScopeRule(Base, TimestampMixin):
    """P18 data-access scoping (data_access.analyse_access): declares what a table
    means to the SQL-scoping analysis — a scoped table (rows must be filtered to the
    caller's own principal) or a reference table (lookup data, no principal filter
    required). Undeclared tables are reported by analyse_access but never assumed
    safe (see that module's own docstring); this is how an operator declares one.
    """

    __tablename__ = "access_scope_rules"
    __table_args__ = (
        UniqueConstraint("org_id", "table_name", name="ux_access_scope_rules_org_table"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("asr"))
    table_name: Mapped[str] = mapped_column(String(160), index=True)
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    column: Mapped[str | None] = mapped_column(String(120))
    principal_key: Mapped[str] = mapped_column(String(120), default="id")
    restricted_columns: Mapped[list[str]] = mapped_column(JSON, default=list)


class DelegationEdge(Base, TimestampMixin):
    """P2-5. Write-time invariant: child capabilities are a subset of the parent's."""

    __tablename__ = "delegation_edges"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("dlg"))
    parent_identity_id: Mapped[str] = mapped_column(String(40), index=True)
    child_identity_id: Mapped[str] = mapped_column(String(40), index=True)
    capability_diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)


class ApprovalRequest(Base, TimestampMixin):
    """P2-3. Deny-on-timeout by default."""

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.approval_id)
    decision_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    tool_key: Mapped[str | None] = mapped_column(String(160))
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    approver_role: Mapped[str] = mapped_column(String(32), default="security")
    resolver_user_id: Mapped[str | None] = mapped_column(String(40))
    resolution_rationale: Mapped[str | None] = mapped_column(Text)
    timeout_action: Mapped[str] = mapped_column(String(16), default="deny")


class User(Base, TimestampMixin):
    """An operator of the control plane.

    Email is unique **per tenant**, not globally — the same correction migration
    ``217f32001df6`` made to several other tables. A global unique meant two tenants
    could not both have a user at the same address, which is wrong on its face for a
    multi-tenant system (two companies, one shared contractor) and which made it
    impossible to seed a second fixture world at all: `seed.seed` already tests for an
    existing user with a tenant-filtered query, so it inserted and the global index
    rejected the insert.

    The lookup this affects is the development identity header, which resolves a user
    by email before any tenant is known. `gateway/auth.py` resolves that ambiguity
    explicitly rather than relying on the index to make it impossible.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="ux_users_org_email"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.user_id)
    email: Mapped[str] = mapped_column(String(200), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(32), default="developer")
    # OIDC/SAML seam (P2-4). Populated by an IdP when one is wired.
    external_id: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ApiToken(Base, TimestampMixin):
    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("tok"))
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    key_prefix: Mapped[str] = mapped_column(String(32), index=True)
    key_hash: Mapped[str] = mapped_column(String(256))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class GithubConnection(Base, TimestampMixin):
    """A stored, encrypted GitHub OAuth grant.

    The gateway is what lists and fetches an org's repos — the raw GitHub access
    token never reaches the browser, only this record's org-scoped id does.
    """

    __tablename__ = "github_connections"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("ghc"))
    github_user_id: Mapped[str] = mapped_column(String(64), index=True)
    github_login: Mapped[str] = mapped_column(String(200), default="")
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    connected_by_user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"))


class ScanRun(Base, TimestampMixin):
    """One repo scan. Links `discovery.py`'s static findings to the draft agents and
    policies it proposed, so a reviewer can see why something showed up."""

    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("scn"))
    # Null for a hosted-API or CLI scan — there's no stored connection to point at:
    # unlike GitHub we hold no credential to fetch the spec (hosted-API) or ever touch
    # the target machine at all (CLI submit — the scan already ran locally).
    connection_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("github_connections.id"), index=True
    )
    # "github" (default, repo scan), "hosted_api" (OpenAPI spec scan), or "cli"
    # (`agentfox scan --submit` / `agentfox scan --sessions --submit` — a locally-run scan
    # whose redacted summary, never its file contents, was submitted for review).
    source_kind: Mapped[str] = mapped_column(String(16), default="github")
    repo_full_name: Mapped[str] = mapped_column(String(300), default="")
    # The endpoint or spec URL, for a hosted-API scan. Unused for a github scan.
    target_url: Mapped[str | None] = mapped_column(String(500))
    ref: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|completed|failed
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Pillar 3 — Runtime Guardrails
# ---------------------------------------------------------------------------


class DetectorRun(Base, TimestampMixin):
    """status=timeout|skipped_budget is the P3-6 degradation signal (NOM-RTG-06)."""

    __tablename__ = "detector_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.detector_run_id)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    span_id: Mapped[str | None] = mapped_column(String(40))
    detector_key: Mapped[str] = mapped_column(String(64), index=True)
    detector_version: Mapped[str] = mapped_column(String(32), default="0")
    surface: Mapped[str] = mapped_column(String(24), default="input")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="ok")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DetectionFinding(Base, TimestampMixin):
    """`sample` is redacted at capture (P5-5) — we never store the raw secret."""

    __tablename__ = "detection_findings"
    __table_args__ = (Index("ix_detfind_entity", "entity_type", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("dfn"))
    detector_run_id: Mapped[str] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    start: Mapped[int] = mapped_column(Integer, default=0)
    end: Mapped[int] = mapped_column(Integer, default=0)
    sample: Mapped[str] = mapped_column(String(200), default="")
    action_taken: Mapped[str] = mapped_column(String(24), default="none")
    owasp_id: Mapped[str | None] = mapped_column(String(24))
    atlas_id: Mapped[str | None] = mapped_column(String(32))


class BusinessRule(Base, TimestampMixin):
    """A stored business guardrail — today a threshold ladder, by kind for what comes next.

    Kept beside policy documents rather than inside them because the two compose by
    different algebras: security rules take the lattice maximum, ladders select exactly
    one band. Flattening them into one list is what makes a refund threshold able to
    silently weaken an injection control.
    """

    __tablename__ = "business_rules"
    __table_args__ = (Index("ix_business_scope", "kind", "tool", "field_path"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("biz"))
    key: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="threshold_ladder")
    #: Who agreed it, so a disagreement has someone to resolve it.
    owner: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    tool: Mapped[str | None] = mapped_column(String(160), index=True)
    field_path: Mapped[str | None] = mapped_column(String(200))
    #: The full authored definition, validated against the kind's schema on write.
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(16), default="observe")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EndUserPrincipal(Base, TimestampMixin):
    """P10-1 — the human the agent is acting for.

    Everything else in this pillar depends on this record existing. The Copilot-class
    failure is precisely its absence: the agent runs under its own service identity
    and inherits the union of everything that identity can reach, so every permission
    check passes and the answer still contains what the *requester* was never entitled
    to see.
    """

    __tablename__ = "end_user_principals"
    __table_args__ = (Index("ix_principal_subject", "subject", "agent_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("prn"))
    #: Stable identifier from the caller's IdP — an OIDC `sub`, an employee id.
    subject: Mapped[str] = mapped_column(String(200), index=True)
    display: Mapped[str] = mapped_column(String(200), default="")
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    #: Group and role memberships the entitlement engine resolves against.
    groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Clearance labels: which restricted classes this person may see at all.
    clearances: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: GDPR Art. 5(1)(b): what this data may be used for.
    purposes: Mapped[list[str]] = mapped_column(JSON, default=list)
    residency: Mapped[str | None] = mapped_column(String(16))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ResourceGrant(Base, TimestampMixin):
    """P10-2 — who may see which resource, for the native entitlement engine.

    Deliberately a thin ACL rather than a relationship model. Customers who already
    run OpenFGA or Cedar should keep it; this exists so the control is usable by the
    much larger group who have permissions expressed as "this group can read this
    folder" and nothing more formal.
    """

    __tablename__ = "resource_grants"
    __table_args__ = (Index("ix_grant_resource", "resource", "principal_kind", "principal"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("grt"))
    #: Matches the `source` a retriever puts on a chunk, glob allowed.
    resource: Mapped[str] = mapped_column(String(500), index=True)
    principal_kind: Mapped[str] = mapped_column(String(16), default="group")  # group | subject
    principal: Mapped[str] = mapped_column(String(200), index=True)
    #: Restricted classes this resource carries: mnpi, legal_hold, blackout, pii.
    classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    purposes: Mapped[list[str]] = mapped_column(JSON, default=list)
    residency: Mapped[str | None] = mapped_column(String(16))


class DisclosureEvent(Base, TimestampMixin):
    """P10-3 — what was withheld, and why.

    The drop count *is* the oversharing metric. A pre-filter that silently returns
    fewer chunks tells nobody anything; the same filter recording what it removed turns
    "our agent might be oversharing" into a number with examples attached.
    """

    __tablename__ = "disclosure_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("dsc"))
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    principal_subject: Mapped[str | None] = mapped_column(String(200), index=True)
    stage: Mapped[str] = mapped_column(String(16), default="pre")  # pre | post
    candidates: Mapped[int] = mapped_column(Integer, default=0)
    withheld: Mapped[int] = mapped_column(Integer, default=0)
    reasons_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: P10-4: the agent could reach more than the principal. The diagnostic that
    #: motivates the whole exercise, and valuable before any model exists.
    over_permission: Mapped[float] = mapped_column(Float, default=0.0)


class SourceRecord(Base, TimestampMixin):
    """P8-1 — what a retrieved chunk came from, and whether that source may be trusted.

    Our groundedness scorer checks the answer against the retrieved context and never
    asks whether that context was authoritative. An agent that faithfully grounds an
    answer in a deprecated 2019 wiki page scores 1.0, which is the whole of F2.
    """

    __tablename__ = "source_records"
    __table_args__ = (
        Index("ix_sources_tier", "tier", "domain"),
        UniqueConstraint("org_id", "key", name="ux_source_records_org_key"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("src"))
    #: Stable identifier the retriever emits — URI, doc id, table name.
    key: Mapped[str] = mapped_column(String(500), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    # system_of_record | approved | unverified | external
    tier: Mapped[str] = mapped_column(String(24), default="unverified")
    owner: Mapped[str | None] = mapped_column(String(200))
    #: The corpus this belongs to, so a support agent answering from the finance
    #: corpus (F2.6) is detectable rather than merely unlikely.
    domain: Mapped[str | None] = mapped_column(String(120), index=True)
    updated_at_source: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    freshness_sla_hours: Mapped[int | None] = mapped_column(Integer)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Tiering a source is a claim that it's authoritative — these two fields are the
    #: difference between that claim and a checked fact. A tier says a human decided
    #: this source should be trusted; these say we actually went and looked at what's
    #: there. Only ever set for a `key` that resolves to a fetchable URL — a doc id or
    #: table name has nothing to fetch, and last_validated_at stays null for those,
    #: honestly, rather than faking a check that never happened.
    content_hash: Mapped[str | None] = mapped_column(String(64))
    last_validated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_validation_status: Mapped[str | None] = mapped_column(String(24))
    #: Set only by `agentfox seed` — see Agent.is_seed for why this exists.
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)


class SourceConnection(Base, TimestampMixin):
    """P8 — how to actually reach a source, for sources that are more than a
    fetchable URL: an enterprise knowledge base or a customer's own database.

    A registry key alone is a claim; this is what turns "validate" from a plain
    HTTP GET into a real connector. `kind` picks which one:

    * ``database`` — dialect/host/port/database/username in `config_json`, the
      password held only as `credential_encrypted`. Validated by connecting and
      introspecting schema, not by fetching arbitrary bytes.
    * ``api`` — `base_url` and an `auth_header` name in `config_json`, the
      bearer token or key held only as `credential_encrypted`. This is the one
      connector that covers Confluence, SharePoint, Notion, Jira and similar —
      they are all an authenticated REST endpoint under the hood, and that is
      the primitive this wraps rather than a vendor-specific SDK per source.
    """

    __tablename__ = "source_connections"
    __table_args__ = (
        UniqueConstraint("org_id", "source_key", name="ux_source_connections_org_key"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("con"))
    #: Matches SourceRecord.key — one connection per registered source.
    source_key: Mapped[str] = mapped_column(String(500), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # database | api
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Never the raw password/token — see crypto.py. Nullable only because a
    #: connection can in principle be unauthenticated (an internal API with no
    #: auth), not because we ever store a secret in the clear.
    credential_encrypted: Mapped[str | None] = mapped_column(Text)


class KnowledgeBoundary(Base, TimestampMixin):
    """P7-1 — what this agent can actually answer from.

    Declared, not inferred. The fact that decides answerability — what the index behind
    the agent contains — is invisible to the model and cannot be derived from the corpus
    without the operator saying so.
    """

    __tablename__ = "knowledge_boundaries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("kbd"))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True, unique=True)
    systems_of_record: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Rolling window in months, or an absolute start date. Absolute wins.
    coverage_months: Mapped[int | None] = mapped_column(Integer)
    coverage_start: Mapped[dt.date | None] = mapped_column(Date)
    entity_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: fact | aggregate | prediction | opinion | procedure
    answerable_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    out_of_scope_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    freshness_hours: Mapped[int | None] = mapped_column(Integer)
    #: observe-first, deliberately: an over-refusing agent is uninstalled faster than a
    #: hallucinating one, so enforcement is something an operator turns on knowingly.
    mode: Mapped[str] = mapped_column(String(16), default="observe")


class EscalationPolicy(Base, TimestampMixin):
    """P11-1 — the conditions under which this agent *must* hand off to a human.

    Declared per agent, and deliberately separate from the guardrail policy: a
    guardrail decides whether an action may proceed, an escalation policy decides
    whether a human must be involved. Conflating them means an agent that is behaving
    within policy and still failing the user has nothing that notices.
    """

    __tablename__ = "escalation_policies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("esc"))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)  # None = default
    #: Condition thresholds. Absent keys are not evaluated.
    conditions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    owner_role: Mapped[str] = mapped_column(String(64), default="support")
    #: F5.6 — an escalation nobody owns within an SLA is a dropped escalation.
    sla_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(16), default="observe")  # observe | enforce


class Handoff(Base, TimestampMixin):
    """P11-6/7 — one hand-off to a human, with its context package and its clock.

    Distinct from `ApprovalRequest`, which asks a human to authorise an *action*. A
    hand-off transfers the *conversation*, and the failure modes are different: an
    approval that expires denies safely, whereas a hand-off that expires leaves a real
    person waiting.
    """

    __tablename__ = "handoffs"
    __table_args__ = (Index("ix_handoffs_status_due", "status", "due_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("hnd"))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    session_id: Mapped[str | None] = mapped_column(String(120), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    #: Which declared conditions triggered it — the audit answer to "why a human?".
    triggers_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: F5.2 — the context the human receives. A hand-off without it is a failure even
    #: though the hand-off itself happened.
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completeness: Mapped[float] = mapped_column(Float, default=0.0)
    owner_role: Mapped[str] = mapped_column(String(64), default="support")
    owner_user_id: Mapped[str | None] = mapped_column(String(40))
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # pending | acknowledged | resolved | breached
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    #: Set when the hand-off was created retroactively by missed-escalation detection
    #: rather than at the time it should have happened.
    detected_retroactively: Mapped[bool] = mapped_column(Boolean, default=False)


class ConversationTurn(Base, TimestampMixin):
    """P11-3/5 — the per-turn record missed-escalation detection reads back.

    Traces record what the *agent* did. This records what the *conversation* looked
    like, which is what the escalation conditions are written against.
    """

    __tablename__ = "conversation_turns"
    __table_args__ = (Index("ix_turns_session_index", "session_id", "turn_index"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("trn"))
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    user_text: Mapped[str] = mapped_column(Text, default="")
    agent_text: Mapped[str] = mapped_column(Text, default="")
    #: Signals extracted at capture time — sentiment, abstention, repetition, topic.
    signals_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)


class GuardrailFeedback(Base, TimestampMixin):
    """P3-14 — a human's verdict on our verdict.

    The measured complaint is that guardrails cannot be tuned: a team gets false
    positives, has nowhere to put that fact, and turns the detector off. This row is
    the place to put it, and the input to both precision reporting and threshold
    recommendation.
    """

    __tablename__ = "guardrail_feedback"
    # One label per decision per person is enforced in application code rather than as
    # a unique constraint, because a deployed table may already hold duplicates and a
    # constraint would make the migration fail on exactly the data it exists to clean.
    __table_args__ = (
        Index("ix_feedback_detector", "detector_key", "label"),
        Index("ix_feedback_decision_actor", "decision_id", "actor"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("gfb"))
    decision_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    detector_key: Mapped[str | None] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    # false_positive | true_positive | false_negative
    label: Mapped[str] = mapped_column(String(24), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), default="open")  # open | applied | rejected


class Suppression(Base, TimestampMixin):
    """P3-14 — a scoped, expiring exception to a detector.

    Expiry is not a nicety. A permanent silent exception is indistinguishable from a
    detector that stopped working, and that is exactly how guardrail programmes decay.
    Every suppression carries an owner, a reason and an end date, and every hit is
    counted so an unused one is visible.
    """

    __tablename__ = "suppressions"
    __table_args__ = (Index("ix_suppressions_scope", "agent_id", "detector_key", "entity_type"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("sup"))
    feedback_id: Mapped[str | None] = mapped_column(String(40))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)  # None = all agents
    detector_key: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    # When set, only this exact matched text is suppressed rather than the whole class.
    sample_hash: Mapped[str | None] = mapped_column(String(64))
    surface: Mapped[str | None] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        return expires > dt.datetime.now(dt.UTC)


class TaintTag(Base, TimestampMixin):
    """P3-4. The substrate for intent-based containment."""

    __tablename__ = "taint_tags"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("tnt"))
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    path: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(32))
    trust: Mapped[str] = mapped_column(String(16), default="untrusted")
    propagated_from: Mapped[str | None] = mapped_column(String(300))


class Budget(Base, TimestampMixin):
    """P3-10. Consumption bounds and loop containment."""

    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("bdg"))
    scope_type: Mapped[str] = mapped_column(String(24), default="agent")
    scope_id: Mapped[str] = mapped_column(String(120), index=True)
    window: Mapped[str] = mapped_column(String(24), default="hour")
    window_started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    max_calls: Mapped[int | None] = mapped_column(Integer)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    max_cost_usd: Mapped[float | None] = mapped_column(Float)
    max_depth: Mapped[int | None] = mapped_column(Integer)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class MemoryEntry(Base, TimestampMixin):
    """NOM-RTG-13 — P14 extension, closes OWASP ASI06 (Memory & Context Poisoning).

    A write into whatever an agent uses as long-term memory (vector store, `mem0`
    -style store, a LangGraph checkpointer) governed the same way a tool call is:
    the detector pipeline runs on the way *in*, not only on the way back out at
    retrieval time, and the entry carries the taint of whatever produced it so a
    later retrieval can weight or refuse it the way P8 already weights a source
    tier. ``verified_by`` is None until a human or a trusted process confirms the
    entry — until then :attr:`active` defaults closed rather than open, unlike
    :class:`Suppression`: an unconfirmed memory is not entitled to persist
    indefinitely just because nobody has gotten around to revoking it.
    """

    __tablename__ = "memory_entries"
    __table_args__ = (Index("ix_memory_entries_scope", "agent_id", "subject"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.memory_entry_id)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    subject: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    taint_source: Mapped[str] = mapped_column(String(32), default="user")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decision_id: Mapped[str | None] = mapped_column(String(40))
    verified_by: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.verified_by is not None:
            return True
        if self.expires_at is None:
            return False
        expires = as_aware(self.expires_at)
        return expires > dt.datetime.now(dt.UTC)


class AgentSigningKey(Base, TimestampMixin):
    """NOM-IAM-08 — P17, closes OWASP ASI07 (agent-to-agent message integrity).

    One HMAC secret per agent, encrypted at rest with the same primitive
    :mod:`crypto` already uses for a connected GitHub token or a source
    connection's credential. Signs and verifies A2A traffic where AgentFox is
    the transport (``agentfox.auto()``-wrapped multi-agent calls); traffic on an
    external A2A/MCP bus is reported ``unsigned`` rather than silently trusted.
    """

    __tablename__ = "agent_signing_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.agent_signing_key_id)
    agent_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    key_encrypted: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(200))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AgentMessageLog(Base, TimestampMixin):
    """NOM-IAM-08 — one row per inter-agent message evaluated on the
    ``agent_message`` surface. The ``(org_id, sender_slug, nonce)`` uniqueness is
    the anti-replay mechanism itself, not just an audit convenience: a repeated
    ``(sender, nonce)`` pair fails to insert, and the caller maps that straight
    to a ``replay`` verdict rather than re-deriving replay detection elsewhere.
    """

    __tablename__ = "agent_message_log"
    __table_args__ = (
        UniqueConstraint("org_id", "sender_slug", "nonce", name="ux_agent_message_sender_nonce"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.agent_message_id)
    sender_slug: Mapped[str] = mapped_column(String(120), index=True)
    recipient_slug: Mapped[str | None] = mapped_column(String(120))
    nonce: Mapped[str] = mapped_column(String(64))
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    signature_valid: Mapped[bool | None] = mapped_column(Boolean)
    agent_card_match: Mapped[bool] = mapped_column(Boolean, default=True)
    decision_id: Mapped[str | None] = mapped_column(String(40))
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)


# ---------------------------------------------------------------------------
# Pillar 4 — Evaluation & Reliability
# ---------------------------------------------------------------------------


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
    # P4-6: "promote this production failure to a test case".
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
    """P4 — human review of a borderline eval result (score near the scorer's own
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
    """Regression gate semantics for P4-1 live here."""

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


# ---------------------------------------------------------------------------
# Pillar 5 — Audit, Observability & Traceability
# ---------------------------------------------------------------------------


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
    """I-4 / I-6 — the join key between our decision and an external observability run.

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
    """OpenLLMetry semantic conventions live in `attributes_json` (P5-1)."""

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
    """P5-2. Append-only, hash-chained.

    There is intentionally no ``updated_at``, no ORM update path, and no delete
    endpoint. The chain is verified by :mod:`agentfox.prove.audit.chain`, which is a pure
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
    """Signed anchor. The key lives outside the application database (NFR-7)."""

    __tablename__ = "audit_checkpoints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("ckp"))
    seq: Mapped[int] = mapped_column(Integer, index=True)
    digest: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    signature: Mapped[str] = mapped_column(String(128))
    key_id: Mapped[str] = mapped_column(String(64), default="local")


class Job(Base, TimestampMixin):
    """Deferred work (P4/PL-5), persisted so the dead letter is real public state
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


# ---------------------------------------------------------------------------
# Pillar 6 — Policy & Compliance
# ---------------------------------------------------------------------------


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
    """Immutable. Never mutated in place — X-4."""

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
    """Observe-by-default is the R3 (false-block) mitigation."""

    __tablename__ = "policy_bindings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("bnd"))
    policy_version_id: Mapped[str] = mapped_column(String(40), index=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(16), default="observe")
    # P12 — where this binding sits in the hierarchy. Defaults keep pre-hierarchy
    # bindings behaving exactly as before: one org-wide layer that extends nothing.
    level: Mapped[str] = mapped_column(String(16), default="org")
    scope_id: Mapped[str] = mapped_column(String(160), default="*")
    compose: Mapped[str] = mapped_column(String(16), default="extend")
    effective_from: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    effective_to: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PolicyCanary(Base, TimestampMixin):
    """Agent canary rollout by version, with health gates and automated rollback (P12-6).

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
    # Always the exact version(s) in force at decision time — X-4, NOM-AUD-02.
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
    """P2-7. Replay recorded traffic against a candidate policy."""

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
    NOT LEGAL ADVICE` rather than excluded (Appendix B §B.6)."""

    __tablename__ = "framework_mappings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("fmp"))
    control_key: Mapped[str] = mapped_column(String(32), index=True)
    framework: Mapped[str] = mapped_column(String(32), index=True)
    reference: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(16), default="draft")
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ControlStatus(Base, TimestampMixin):
    """P6-4. Computed from telemetry, never attested."""

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
    """P6-5. The regulatory clock, as data rather than code (R6)."""

    __tablename__ = "obligations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("obl"))
    framework: Mapped[str] = mapped_column(String(32), index=True)
    reference: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    effective_date: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    applies_when_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="upcoming")


# ---------------------------------------------------------------------------
# Improvement loop (governed self-improvement, Phase 0)
# ---------------------------------------------------------------------------
#: Rows the one-open-proposal-per-problem index covers. Must list exactly
#: ``improvement.contract.OPEN``; tests/test_proposals_integrity.py holds the two together.
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

    Before this table the platform had a daily cron that only ever drained jobs someone
    had already enqueued, so nothing periodic — posture campaigns, drift checks, canary
    advancement, suppression hygiene — could run unattended at all.
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


# ---------------------------------------------------------------------------
# Public playground
# ---------------------------------------------------------------------------


class PlaygroundSandbox(Base, TimestampMixin):
    """The registry row for one public-playground sandbox.

    A sandbox is a tenant. Its ``org_id`` is its own id, and every row the visitor's
    activity produces (traces, decisions, findings, audit entries, the seeded demo
    fixtures) is written under that org, so the ordinary session-level tenant filter in
    ``tenancy.py`` is what keeps one sandbox out of another. No sandbox-specific filter
    exists, because a filter somebody has to remember is not a control.

    This row is what makes a sandbox outlive the process that created it: before it
    existed, sandboxes lived in a module-level dict with a per-sandbox in-memory SQLite
    engine, which works on one long-lived container and does not work at all on the
    serverless deployment in ``api/vercel.json``, where the next request is a different
    instance and finds nothing.

    What the id proves and does not prove: the id is a 128-bit random value and it is
    the only credential the playground has, so holding it is what grants access. It
    does not identify a person and it is not revocable. Anyone the visitor sends the
    link to can read the sandbox.
    """

    __tablename__ = "playground_sandboxes"

    #: Also this sandbox's ``org_id``. Format is checked before it is ever bound to a
    #: session, so a caller cannot name a real tenant in the path and be bound to it.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: Idle expiry. Extended on each use, so the TTL the page shows is time since the
    #: visitor's last action, not time since creation.
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    #: Trace ids this sandbox produced, oldest first, capped. Stored rather than
    #: recomputed so the live sidebar shows the visitor's own actions in the order they
    #: happened and not the seeded fixtures' traces.
    trace_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


# ---------------------------------------------------------------------------
# Hosted-cloud waitlist — the one table that is not a tenant's
# ---------------------------------------------------------------------------


class WaitlistSignup(Base, TenantExempt):
    """A stranger asking to be told when the hosted service exists.

    Why this sits outside the tenant pattern that governs every other table: a
    waitlist signup happens *before* the person has an org. Scoping it would mean
    inventing a tenant for somebody who has not signed up for anything, and then
    either hiding the list from the operator who needs to read it or filing every
    signup under the deployment's own org — a tenant boundary that means nothing,
    which is worse than admitting there isn't one. So the row belongs to nobody, and
    :class:`TenantExempt` plus :data:`TENANT_EXEMPT_TABLES` say so out loud.

    The consequence to hold in mind: ``tenancy.py``'s session filter does not touch
    this table, so a query here returns every signup whatever tenant the session is
    bound to. That is correct for a list of people who have no tenant, and it is the
    reason nothing tenant-facing may ever be added to this table.

    The email is unique, stored lowercased and stripped, so somebody double-clicking
    the submit button joins the list once rather than twice. ``source`` is what keeps
    this table usable for the *next* list — it names which form the person came
    through, so "hosted cloud" and whatever is asked in a year are one table and one
    endpoint rather than two of each.

    What is deliberately absent: nothing here sends mail, and no third party is told.
    A signup is a row. Someone reads the table when there is something to announce.
    """

    __tablename__ = "waitlist_signups"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.waitlist_signup_id)
    #: Unique across the whole table, not per anything — see the class docstring. 320
    #: is the longest address SMTP will carry (64 local + @ + 255 domain).
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    #: Which list this is. Indexed because reading "everyone waiting for hosted cloud"
    #: is the only query this table has.
    source: Mapped[str] = mapped_column(String(64), default="hosted-cloud", index=True)
    #: Both optional, both free text the visitor typed. Kept because "who is asking"
    #: is the only thing that makes a waitlist worth more than a count.
    company: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    #: Declared here rather than inherited: ``TimestampMixin`` carries ``TenantScoped``
    #: with it, which is exactly what this table must not have.
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JudgmentPosture(Base, TimestampMixin):
    """Which judgment tiers this tenant has turned on, and what may leave the process.

    Separate from :class:`~agentfox.core.config.Settings` on purpose, and the separation is
    the point rather than an accident of storage. Settings are what the *operator of
    the process* chose: environment variables and a config file, read once, unreachable
    from any HTTP request. This row is what an *admin inside the product* chose. The
    two are not interchangeable, because the question "may this deployment talk to a
    third party at all" and the question "do we want it to today" have different
    people answering them and different blast radii when answered wrong.

    So the relationship is one-directional and enforced in
    :mod:`agentfox.detection.judgment.posture`: a row here may only ever *narrow* what the
    deployment permits. Enabling a remote tier on a deployment whose ``allow_egress``
    is off is refused rather than stored-and-ignored, because a posture page that
    shows JEV as on while nothing is being sent to JEV is worse than one that will not
    let you turn it on — it answers the compliance question wrongly in writing.

    One row per tenant. ``version`` is bumped on every write for the same reason the
    policy and business-rule tables carry one: an auditor asking what left the building
    in March needs the posture that was in force in March, and the audit chain's
    before/after pair is what reconstructs it.
    """

    __tablename__ = "judgment_posture"
    __table_args__ = (UniqueConstraint("org_id", name="uq_judgment_posture_org"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("jpo"))
    #: Tier names from :class:`agentfox.detection.judgment.Tier`. ``deterministic`` is implicit
    #: and always on — it needs no key, no weights and no network, and a kind with no
    #: permitted decider at all is not a posture anyone meant to choose.
    tiers: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: ``block`` | ``redact`` | ``allow`` — see :class:`agentfox.detection.judgment.PiiEgress`.
    pii_egress: Mapped[str] = mapped_column(String(16), default="redact")
    #: Whether a remote tier's outage denies the request or is treated as no-signal.
    fail_closed: Mapped[bool] = mapped_column(Boolean, default=True)
    #: ``local`` | ``remote`` | ``auto``.
    backend: Mapped[str] = mapped_column(String(16), default="local")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(200))


def _is_exempt(cls: type) -> bool:
    """True for a mapped class deliberately placed outside tenant isolation.

    Both halves have to hold — the mixin *and* the roster entry — so neither a stray
    inheritance nor a stray list entry is enough on its own.
    """
    return (
        issubclass(cls, TenantExempt)
        and getattr(cls, "__tablename__", None) in TENANT_EXEMPT_TABLES
    )


__all__ = [n for n in dir() if n[0].isupper()]


def _assert_every_model_is_tenant_scoped() -> None:
    """Fail loudly at import if a model escapes tenant isolation.

    Tenant filtering targets :class:`TenantScoped`, so a model that does not inherit it
    is invisible to the filter and its rows are readable by every tenant. That is a
    data breach, and it is the kind introduced by someone adding a table months from
    now who has never read the tenancy module. Making it an import error means the
    mistake cannot reach a running system.
    """
    escaped = sorted(
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if not issubclass(mapper.class_, TenantScoped)
        and not issubclass(mapper.class_, TenantExempt)
    )
    if escaped:
        raise RuntimeError(
            "these models are not tenant-scoped and would leak across tenants: "
            f"{escaped}. Inherit TenantScoped (usually via TimestampMixin)."
        )

    # The other direction, and the reason the roster is a roster: a model that wears
    # the exemption mixin but is not on the list is somebody opting a table out of
    # tenancy without going near the list that explains what that costs. Checked
    # separately from the sweep above so this case gets its own message — told to
    # "inherit TenantScoped", the author of such a model would go looking for a bug
    # that isn't there.
    unlisted = sorted(
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantExempt)
        and mapper.class_.__tablename__ not in TENANT_EXEMPT_TABLES
    )
    if unlisted:
        raise RuntimeError(
            f"these models claim TenantExempt but are not listed in "
            f"TENANT_EXEMPT_TABLES: {unlisted}. Add the table name there, in the same "
            "diff, with the reason it holds no tenant's data."
        )


_assert_every_model_is_tenant_scoped()
