"""Control-plane routes for Pillars 1 and 2 — registry, identity, approvals."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...audit import chain
from ...findings import STATUSES as FINDING_STATUSES
from ...identity import (
    assess_posture,
    check_capability,
    expire_stale_approvals,
    grant_capability,
    issue_credential,
    resolve_approval,
    revoke_credential,
    rotate_credential,
)
from ...models import (
    Agent,
    ApiToken,
    ApprovalRequest,
    Capability,
    Credential,
    Finding,
    Handoff,
    Identity,
    McpServer,
    Tool,
    User,
    utcnow,
)
from ...registry.control import UnknownAgent, all_controls, set_state
from ...registry.service import (
    assess_delegation,
    attest_registry,
    derive_lineage,
    detect_shadow_agents,
    impact_source_of,
    inventory,
    lineage,
    register_agent,
    scan_mcp_server,
    unowned_agents,
    upsert_mcp_server,
    upsert_tool,
)
from ..auth import issue_token
from ..deps import current_user, db, get_agent_or_404, require

router = APIRouter(prefix="/api", tags=["registry", "identity"])


# ---------------------------------------------------------------------------
# Self-service API tokens — the CLI/SDK path had no way for an already-signed-in
# dashboard user to get a token for their own scripts short of the GitHub-login
# provisioning flow, which only ever mints one server-to-server at sign-in.
# ---------------------------------------------------------------------------


class TokenIn(BaseModel):
    name: str = ""
    ttl_days: int | None = 365


@router.post("/tokens", status_code=201)
def create_token(
    payload: TokenIn, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """Mint a token for the caller's own use. The raw value is returned once —
    same guarantee as every other credential this platform issues."""
    token, raw = issue_token(
        session,
        user,
        name=payload.name or "self-service",
        ttl_days=payload.ttl_days,
        actor=user.email or user.id,
        reason="self-service token generation",
    )
    chain.append(
        session,
        "token.self_issued",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="api_token",
        subject_id=token.id,
        payload={"name": token.name},
    )
    session.commit()
    return {"id": token.id, "name": token.name, "token": raw, "expires_at": _iso(token.expires_at)}


@router.get("/tokens")
def list_tokens(
    session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    tokens = session.scalars(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
    )
    return {
        "tokens": [
            {
                "id": t.id,
                "name": t.name,
                "key_prefix": t.key_prefix,
                "created_at": _iso(t.created_at),
                "expires_at": _iso(t.expires_at),
                "revoked_at": _iso(t.revoked_at),
            }
            for t in tokens
        ]
    }


@router.post("/tokens/{token_id}/revoke")
def revoke_token(
    token_id: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    token = session.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        raise HTTPException(404, "no token with that id")
    token.revoked_at = utcnow()
    session.flush()
    chain.append(
        session,
        "token.revoked",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="api_token",
        subject_id=token.id,
    )
    session.commit()
    return {"id": token.id, "revoked": True}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentIn(BaseModel):
    slug: str
    name: str = ""
    purpose: str = ""
    owner_email: str | None = None
    owner_team: str | None = None
    environment: str = "production"
    risk_tier: str = "limited"
    declared_models: list[str] = Field(default_factory=list)
    declared_tools: list[str] = Field(default_factory=list)
    data_classes: list[str] = Field(default_factory=list)
    framework: str | None = None


def _agent_json(agent: Agent, session: Session | None = None) -> dict[str, Any]:
    control = "active"
    if session is not None:
        from ...models import AgentControl

        row = session.scalar(select(AgentControl).where(AgentControl.agent_id == agent.id))
        control = row.state if row else "active"
    return {
        "control_state": control,
        "id": agent.id,
        "slug": agent.slug,
        "name": agent.name,
        "purpose": agent.purpose,
        "owner_email": agent.owner_email,
        "owner_team": agent.owner_team,
        "environment": agent.environment,
        "risk_tier": agent.risk_tier,
        "framework": agent.framework,
        "status": agent.status,
        "registered": agent.registered,
        "owned": agent.is_owned,
        "is_seed": agent.is_seed,
        "declared_models": agent.declared_models,
        "declared_tools": agent.declared_tools,
        "data_classes": agent.data_classes,
        "first_seen_at": _iso(agent.first_seen_at),
        "last_seen_at": _iso(agent.last_seen_at),
    }


@router.get("/agents")
def list_agents(
    session: Session = Depends(db),
    registered: bool | None = None,
    environment: str | None = None,
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    query = select(Agent).order_by(Agent.slug)
    if registered is not None:
        query = query.where(Agent.registered.is_(registered))
    if environment:
        query = query.where(Agent.environment == environment)
    return {
        "agents": [_agent_json(a, session) for a in session.scalars(query)],
        "inventory": inventory(session),
    }


@router.post("/agents", status_code=201)
def create_agent(
    payload: AgentIn,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    agent = register_agent(session, **payload.model_dump())
    chain.append(
        session,
        "agent.registered",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
        payload=payload.model_dump(),
    )
    return _agent_json(agent)


@router.get("/agents/{slug}")
def get_agent(
    slug: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    return _agent_json(agent, session)


class AgentUpdate(BaseModel):
    owner_email: str | None = None
    owner_team: str | None = None
    risk_tier: str | None = None
    purpose: str | None = None


@router.patch("/agents/{slug}")
def update_agent(
    slug: str,
    payload: AgentUpdate,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(agent, field, value)
    session.flush()
    chain.append(
        session,
        "agent.updated",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
        payload=changes,
    )
    return _agent_json(agent, session)


@router.get("/agents/{slug}/lineage")
def agent_lineage(
    slug: str, depth: int = 2, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    derive_lineage(session, slug)
    return lineage(session, slug, depth)


@router.get("/agents/{slug}/posture")
def agent_posture(
    slug: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    from ...evaluation.drift import evaluate_slos
    from ...models import Decision, Trace

    agent = get_agent_or_404(session, slug)

    traces = list(session.scalars(select(Trace).where(Trace.agent_slug == slug)))
    decisions = list(session.scalars(select(Decision).where(Decision.agent_id == agent.id)))
    findings = list(
        session.scalars(
            select(Finding).where(
                Finding.subject_id.in_([agent.id, slug]), Finding.status == "open"
            )
        )
    )
    # Hand-offs are recorded independently of Trace/Decision — a conversation can
    # escalate without ever producing a traced execution path (e.g. this agent's
    # SDK only calls record_turn/raise_handoff directly). Counting only Trace and
    # Decision rows here made a real, escalated conversation report as "no traffic
    # recorded" on the one page most likely to be checked first during an incident.
    handoffs = list(session.scalars(select(Handoff).where(Handoff.agent_id == agent.id)))
    by_verdict: dict[str, int] = {}
    for decision in decisions:
        by_verdict[decision.verdict] = by_verdict.get(decision.verdict, 0) + 1

    return {
        "agent": _agent_json(agent, session),
        "traces": len(traces),
        "decisions": len(decisions),
        "decisions_by_verdict": by_verdict,
        "blocked": by_verdict.get("block", 0),
        "escalated": by_verdict.get("escalate", 0),
        "handoffs": len(handoffs),
        "open_findings": [
            {"id": f.id, "type": f.type, "severity": f.severity, "title": f.title} for f in findings
        ],
        "slos": evaluate_slos(session, slug),
    }


@router.get("/discovery/shadow")
def shadow_agents(
    window_days: int = 30, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"shadow_agents": detect_shadow_agents(session, window_days)}


@router.post("/discovery/scan")
def run_discovery(
    session: Session = Depends(db), user: User = Depends(require("registry"))
) -> dict[str, Any]:
    """Sweep: lineage, unowned agents, registry drift, identity posture, delegation shape."""
    edges = derive_lineage(session)
    unowned = unowned_agents(session)
    drift = attest_registry(session)
    posture = assess_posture(session)
    delegation = assess_delegation(session)
    chain.append(
        session,
        "discovery.scan",
        actor_type="user",
        actor_id=user.email or user.id,
        payload={
            "edges": edges,
            "unowned": len(unowned),
            "drift": len(drift),
            "posture": len(posture),
            "delegation": len(delegation),
        },
    )
    return {
        "lineage_edges": edges,
        "unowned_agents": len(unowned),
        "registry_drift": len(drift),
        "identity_posture_findings": len(posture),
        "delegation_findings": len(delegation),
        "shadow_agents": detect_shadow_agents(session),
    }


# ---------------------------------------------------------------------------
# Tools & MCP
# ---------------------------------------------------------------------------


class ToolIn(BaseModel):
    key: str
    name: str = ""
    kind: str = "function"
    impact: str = "read"
    description: str = ""
    json_schema: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools")
def list_tools(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "tools": [
            {
                "key": t.key,
                "name": t.name,
                "kind": t.kind,
                "impact": t.impact,
                "impact_source": impact_source_of(t),
                "description": t.description,
                "mcp_server_id": t.mcp_server_id,
            }
            for t in session.scalars(select(Tool).order_by(Tool.key))
        ]
    }


@router.post("/tools", status_code=201)
def create_tool(
    payload: ToolIn, session: Session = Depends(db), _user: User = Depends(require("registry"))
) -> dict[str, Any]:
    tool = upsert_tool(
        session,
        payload.key,
        name=payload.name,
        kind=payload.kind,
        impact=payload.impact,
        schema=payload.json_schema,
        description=payload.description,
    )
    return {"key": tool.key, "impact": tool.impact}


class McpIn(BaseModel):
    name: str
    url: str = ""
    transport: str = "stdio"
    trust_level: str = "untrusted"
    pinned_version: str | None = None


@router.get("/mcp-servers")
def list_mcp(session: Session = Depends(db), _user: User = Depends(current_user)) -> dict[str, Any]:
    return {
        "servers": [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "transport": s.transport,
                "trust_level": s.trust_level,
                "pinned_version": s.pinned_version,
                "last_scanned_at": _iso(s.last_scanned_at),
            }
            for s in session.scalars(select(McpServer))
        ]
    }


@router.post("/mcp-servers", status_code=201)
def create_mcp(
    payload: McpIn, session: Session = Depends(db), _user: User = Depends(require("registry"))
) -> dict[str, Any]:
    server = upsert_mcp_server(session, **payload.model_dump())
    return {"id": server.id, "name": server.name}


class McpScanIn(BaseModel):
    tools: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/mcp-servers/{name}/scan")
def scan_mcp(
    name: str,
    payload: McpScanIn,
    session: Session = Depends(db),
    _user: User = Depends(require("registry")),
) -> dict[str, Any]:
    server = session.scalar(select(McpServer).where(McpServer.name == name))
    if server is None:
        raise HTTPException(404, f"unknown MCP server '{name}'")
    return scan_mcp_server(session, server, payload.tools)


@router.post("/mcp-servers/{name}/tools")
def register_mcp_tools(
    name: str,
    payload: McpScanIn,
    session: Session = Depends(db),
    _user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """I-2 — snapshot a listing *and* register each tool in the registry.

    Distinct from ``/scan``, which only reports hygiene. Registration is what gives
    the tool a policy identity and a digest to compare against at call time; without
    it the rug-pull check has no baseline.
    """
    from ...integrations.mcp import McpGovernor

    governor = McpGovernor(session=session, agent_slug="", server_name=name)
    report = governor.register_tools(payload.tools)
    return {**report, "registered": [t.get("name") for t in payload.tools if t.get("name")]}


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _agent_slug_for_subject(
    session: Session, subject_type: str, subject_id: str | None
) -> str | None:
    """A finding's `subject_id` is an agent identifier — but call sites across the
    codebase have raised findings with both the agent's DB id and its slug in that
    field over time. Resolving both here, once, means the dashboard can always link
    to `/agents/{slug}` without guessing which form a given finding used.
    """
    if subject_type != "agent" or not subject_id:
        return None
    agent = session.get(Agent, subject_id)
    if agent is None:
        agent = session.scalar(select(Agent).where(Agent.slug == subject_id))
    return agent.slug if agent else None


@router.get("/findings")
def list_findings(
    status: str | None = "open",
    severity: str | None = None,
    type: str | None = None,
    agent: str | None = None,
    limit: int = 200,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    query = select(Finding).order_by(Finding.created_at.desc()).limit(limit)
    if status:
        query = query.where(Finding.status == status)
    if severity:
        query = query.where(Finding.severity == severity)
    if type:
        query = query.where(Finding.type == type)
    if agent:
        # `subject_id` has been raised with both the agent's DB id and its slug
        # across call sites over time (see `_agent_slug_for_subject`) — matching
        # against both is what makes this filter reliable regardless of which
        # form a given finding used.
        record = session.scalar(select(Agent).where(Agent.slug == agent))
        subject_ids = {agent, record.id} if record else {agent}
        query = query.where(Finding.subject_type == "agent", Finding.subject_id.in_(subject_ids))
    return {
        "findings": [
            {
                "id": f.id,
                "type": f.type,
                "severity": f.severity,
                "status": f.status,
                "title": f.title,
                "subject_type": f.subject_type,
                "subject_id": f.subject_id,
                "agent_slug": _agent_slug_for_subject(session, f.subject_type, f.subject_id),
                "controls": f.control_keys,
                "evidence": f.evidence_json,
                "occurrences": f.occurrences,
                "last_seen_at": _iso(f.last_seen_at),
                "created_at": _iso(f.created_at),
            }
            for f in session.scalars(query)
        ]
    }


@router.get("/findings/{finding_id}")
def get_finding(
    finding_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(404, "unknown finding")
    return {
        "id": finding.id,
        "type": finding.type,
        "severity": finding.severity,
        "status": finding.status,
        "title": finding.title,
        "subject_type": finding.subject_type,
        "subject_id": finding.subject_id,
        "agent_slug": _agent_slug_for_subject(session, finding.subject_type, finding.subject_id),
        "controls": finding.control_keys,
        "evidence": finding.evidence_json,
        "occurrences": finding.occurrences,
        "last_seen_at": _iso(finding.last_seen_at),
        "suppression_reason": finding.suppression_reason,
        "suppressed_by": finding.suppressed_by,
        "resolution_note": finding.resolution_note,
        "resolved_by": finding.resolved_by,
        "created_at": _iso(finding.created_at),
        "resolved_at": _iso(finding.resolved_at),
    }


class FindingPatch(BaseModel):
    status: str
    suppression_reason: str | None = None
    # What was actually done to fix it — required for "resolved", same discipline
    # "suppressed" already has via suppression_reason. See migration a3f7c9e1b204.
    note: str | None = None


@router.patch("/findings/{finding_id}")
def patch_finding(
    finding_id: str,
    payload: FindingPatch,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(404, "unknown finding")
    if payload.status not in FINDING_STATUSES:
        # The status is the queue. A free-text status is a finding that silently
        # leaves every view filtering on open/suppressed/resolved — and it used to be
        # written into the audit chain as an action name, too.
        raise HTTPException(
            400, f"status must be one of {', '.join(FINDING_STATUSES)}, got {payload.status!r}"
        )
    if payload.status == "suppressed" and not payload.suppression_reason:
        # Suppression without a recorded justification is how a finding queue becomes
        # meaningless; the reason is the control, not the button.
        raise HTTPException(400, "suppression requires a justification")
    if payload.status == "resolved" and not payload.note:
        # Same reasoning as suppression: a one-click "resolved" with nothing recorded
        # is how a still-broken critical finding vanishes from the executive view
        # without anyone having actually fixed it.
        raise HTTPException(400, "resolving requires a note describing what was fixed")
    finding.status = payload.status
    finding.suppression_reason = payload.suppression_reason
    finding.suppressed_by = user.email if payload.status == "suppressed" else None
    if payload.status == "resolved":
        finding.resolved_at = utcnow()
        finding.resolution_note = payload.note
        finding.resolved_by = user.email
    elif payload.status == "open":
        # A reopened finding is not still resolved: leaving the old resolution on it
        # would make the next reader believe the fix was recorded and still holds.
        finding.resolved_at = None
        finding.resolution_note = None
        finding.resolved_by = None
    chain.append(
        session,
        f"finding.{payload.status}",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="finding",
        subject_id=finding.id,
        payload={"type": finding.type, "reason": payload.suppression_reason or payload.note},
    )
    return {"id": finding.id, "status": finding.status}


# ---------------------------------------------------------------------------
# Identities, credentials, capabilities
# ---------------------------------------------------------------------------


@router.get("/identities")
def list_identities(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    out = []
    for identity in session.scalars(select(Identity)):
        credentials = list(
            session.scalars(select(Credential).where(Credential.identity_id == identity.id))
        )
        capabilities = list(
            session.scalars(select(Capability).where(Capability.identity_id == identity.id))
        )
        out.append(
            {
                "id": identity.id,
                "principal": identity.principal,
                "agent_id": identity.agent_id,
                "kind": identity.kind,
                "status": identity.status,
                "posture": identity.posture,
                "last_used_at": _iso(identity.last_used_at),
                "credentials": [
                    {
                        "id": c.id,
                        "prefix": c.key_prefix,
                        "active": c.active,
                        "expires_at": _iso(c.expires_at),
                        "revoked_at": _iso(c.revoked_at),
                    }
                    for c in credentials
                ],
                "capabilities": [
                    {
                        "id": c.id,
                        "tool_key": c.tool_key,
                        "actions": c.actions,
                        "constraints": c.constraints_json,
                        "max_taint": c.max_taint,
                        "requires_approval": c.requires_approval,
                    }
                    for c in capabilities
                ],
            }
        )
    return {"identities": out}


@router.post("/identities/{identity_id}/credentials", status_code=201)
def issue(
    identity_id: str,
    ttl_days: int = 90,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise HTTPException(404, "unknown identity")
    credential, raw = issue_credential(session, identity, ttl_days=ttl_days)
    chain.append(
        session,
        "credential.issued",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="credential",
        subject_id=credential.id,
        payload={"identity": identity.principal, "ttl_days": ttl_days},
    )
    # Shown once, never stored in plaintext.
    return {
        "credential_id": credential.id,
        "key": raw,
        "expires_at": _iso(credential.expires_at),
        "note": "This key is shown once and cannot be retrieved again.",
    }


@router.post("/identities/{identity_id}/rotate")
def rotate(
    identity_id: str,
    overlap_hours: int = 24,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise HTTPException(404, "unknown identity")
    credential, raw = rotate_credential(session, identity, overlap_hours)
    chain.append(
        session,
        "credential.rotated",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="credential",
        subject_id=credential.id,
        payload={"identity": identity.principal, "overlap_hours": overlap_hours},
    )
    return {"credential_id": credential.id, "key": raw, "overlap_hours": overlap_hours}


@router.post("/credentials/{credential_id}/revoke")
def revoke(
    credential_id: str, session: Session = Depends(db), user: User = Depends(require("identity"))
) -> dict[str, Any]:
    if not revoke_credential(session, credential_id):
        raise HTTPException(404, "unknown credential")
    chain.append(
        session,
        "credential.revoked",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="credential",
        subject_id=credential_id,
        payload={},
    )
    return {"revoked": credential_id}


class CapabilityIn(BaseModel):
    tool_key: str
    actions: list[str] = Field(default_factory=lambda: ["*"])
    constraints: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    max_taint: str = "user"


@router.post("/identities/{identity_id}/capabilities", status_code=201)
def add_capability(
    identity_id: str,
    payload: CapabilityIn,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise HTTPException(404, "unknown identity")
    capability = grant_capability(
        session,
        identity,
        payload.tool_key,
        actions=payload.actions,
        constraints=payload.constraints,
        requires_approval=payload.requires_approval,
        max_taint=payload.max_taint,
        granted_by=user.email,
    )
    chain.append(
        session,
        "capability.granted",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="capability",
        subject_id=capability.id,
        payload=payload.model_dump(),
    )
    return {"id": capability.id, "tool_key": capability.tool_key}


class CapabilityCheckIn(BaseModel):
    tool_key: str
    action: str = "*"
    arguments: dict[str, Any] = Field(default_factory=dict)
    argument_taint: dict[str, str] = Field(default_factory=dict)


@router.post("/identities/{identity_id}/check")
def check(
    identity_id: str,
    payload: CapabilityCheckIn,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    identity = session.get(Identity, identity_id)
    return check_capability(
        session,
        identity,
        payload.tool_key,
        payload.action,
        payload.arguments,
        payload.argument_taint,
    ).to_json()


# ---------------------------------------------------------------------------
# Approvals (P2-3)
# ---------------------------------------------------------------------------


@router.get("/approvals")
def list_approvals(
    status: str = "pending", session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    expire_stale_approvals(session)
    query = select(ApprovalRequest).order_by(ApprovalRequest.requested_at.desc())
    if status:
        query = query.where(ApprovalRequest.status == status)
    return {
        "approvals": [
            {
                "id": a.id,
                "agent_id": a.agent_id,
                "tool": a.tool_key,
                "arguments": a.arguments_json,
                "reason": a.reason,
                "status": a.status,
                "requested_at": _iso(a.requested_at),
                "expires_at": _iso(a.expires_at),
                "trace_id": a.trace_id,
                "decision_id": a.decision_id,
                "timeout_action": a.timeout_action,
            }
            for a in session.scalars(query)
        ]
    }


@router.get("/approvals/{approval_id}")
def get_approval(
    approval_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    # The SDK polls this single-approval route, not the bulk list below — without
    # expiring here too, a stale approval reads "pending" forever unless something
    # else happens to hit /approvals first (NOM-IAM-03: unanswered must fail closed).
    expire_stale_approvals(session)
    approval = session.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(404, "unknown approval")
    return {
        "id": approval.id,
        "status": approval.status,
        "reason": approval.reason,
        "tool": approval.tool_key,
        "arguments": approval.arguments_json,
        "rationale": approval.resolution_rationale,
    }


class ApprovalDecision(BaseModel):
    rationale: str = ""


@router.post("/approvals/{approval_id}/approve")
def approve(
    approval_id: str,
    payload: ApprovalDecision,
    session: Session = Depends(db),
    user: User = Depends(require("approvals")),
) -> dict[str, Any]:
    return _resolve(session, approval_id, True, user, payload.rationale)


@router.post("/approvals/{approval_id}/deny")
def deny(
    approval_id: str,
    payload: ApprovalDecision,
    session: Session = Depends(db),
    user: User = Depends(require("approvals")),
) -> dict[str, Any]:
    return _resolve(session, approval_id, False, user, payload.rationale)


def _resolve(
    session: Session, approval_id: str, approved: bool, user: User, rationale: str
) -> dict[str, Any]:
    approval = resolve_approval(session, approval_id, approved, user.id, rationale)
    if approval is None:
        raise HTTPException(404, "unknown approval")
    chain.append(
        session,
        f"approval.{approval.status}",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="approval",
        subject_id=approval.id,
        payload={"tool": approval.tool_key, "rationale": rationale, "reason": approval.reason},
    )
    return {"id": approval.id, "status": approval.status, "resolver": user.email}


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).isoformat()


# ---------------------------------------------------------------------------
# Kill switch & quarantine (PL-3)
# ---------------------------------------------------------------------------


class ControlIn(BaseModel):
    reason: str = ""


@router.get("/agent-controls")
def list_agent_controls(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Kill-switch/quarantine state per agent (PL-3).

    Deliberately not `/api/controls` — that path collided with governance.py's
    compliance-control listing (NIST/EU-AI-Act style controls), and since both
    routers registered a handler on the identical path, whichever was included
    first in app.py silently ate every request to the other. This one was
    winning, which meant the compliance page's `posture` field was never in the
    response it actually got back — the crash that surfaced it.
    """
    return {"controls": all_controls(session)}


@router.post("/agents/{slug}/quarantine")
def quarantine_agent(
    slug: str,
    payload: ControlIn,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Stop an agent while you investigate. Reversible and audited."""
    return _set_agent_state(session, slug, "quarantined", payload.reason, user)


@router.post("/agents/{slug}/kill")
def kill_agent(
    slug: str,
    payload: ControlIn,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    """Stop an agent now. Requires the stronger role — this is an incident action."""
    return _set_agent_state(session, slug, "killed", payload.reason, user)


@router.post("/agents/{slug}/resume")
def resume_agent(
    slug: str,
    payload: ControlIn,
    session: Session = Depends(db),
    user: User = Depends(require("identity")),
) -> dict[str, Any]:
    """Restart a stopped agent. Deliberately the same role as `kill` — restarting
    something that was stopped for cause is not a lesser decision than stopping it."""
    return _set_agent_state(session, slug, "active", payload.reason, user)


def _set_agent_state(
    session: Session, slug: str, state: str, reason: str, user: User
) -> dict[str, Any]:
    try:
        control = set_state(session, slug, state, reason=reason, actor=user.email)
    except UnknownAgent as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "agent": slug,
        "state": control.state,
        "previous_state": control.previous_state,
        "reason": control.reason,
        "actor": control.actor,
        "changed_at": _iso(control.changed_at),
    }
