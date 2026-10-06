"""Pillar 2 — identity, access and authorization: identities, credentials,
capabilities, scopes, delegation, approvals, users and repository scans.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin, as_aware, utcnow
from agentfox.core.models.registry import Agent


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
    #: Secret GitHub signs push deliveries with (`X-Hub-Signature-256`), encrypted.
    #: Null means this connection has no webhook secret of its own; the deployment-wide
    #: `github_webhook_secret` setting may still verify its deliveries.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text)


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
