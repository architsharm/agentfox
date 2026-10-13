"""Audit, evidence and compliance routes (Pillars 5 and 6).

Two things are deliberate here:

* There is **no** PUT, PATCH or DELETE on ``/api/audit/entries``. The absence is the
  control.
* Reading an evidence package writes its own audit entry. Who looked at the evidence
  is audit-relevant, and a governance product that exempts itself from its own
  controls is not credible.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.capabilities.compliance import retention as retention_svc
from agentfox.capabilities.detection.tuning import explain_recorded
from agentfox.core.models import (
    AuditEntry,
    LegalHold,
    RetentionPolicy,
    Trace,
    User,
)
from agentfox.core.tenancy import session_org
from agentfox.exporters import siem
from agentfox.exporters.correlation import links_for, resolve_external
from agentfox.platform.jobs import store as jobs_db
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.trace import full_trace, search_traces

router = APIRouter(prefix="/api", tags=["audit", "compliance"])


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------


@router.get("/traces")
def list_traces(
    agent: str | None = None,
    verdict: str | None = None,
    environment: str | None = None,
    entity_type: str | None = None,
    tool: str | None = None,
    rule: str | None = None,
    errors: bool = False,
    since_days: int | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    limit: int = 100,
    group: bool = False,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Runs, newest first. ``group=true`` gives one row per conversation."""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days) if since_days else None
    if start and (since is None or start > since):
        since = start
    return {
        "traces": search_traces(
            session,
            agent_slug=agent,
            verdict=verdict,
            environment=environment,
            entity_type=entity_type,
            tool_key=tool,
            rule_id=rule,
            errors_only=errors,
            since=since,
            until=end,
            limit=min(limit, 500),
            group=group,
        )
    }


# ---------------------------------------------------------------------------
# Observability correlation
# ---------------------------------------------------------------------------


# Declared before /traces/{trace_id} deliberately: FastAPI matches in declaration
# order, so the parameterised route would otherwise swallow this one.
@router.get("/traces/resolve")
def resolve_trace(
    system: str = Query(..., description="langsmith | langfuse | otel"),
    external_id: str = Query(..., description="their trace id or run/observation id"),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Their run id → our governance decision.

    This is the direction that matters during an incident: an engineer is already
    looking at a Langfuse trace and wants to know which policy shaped it. Nobody
    ships this, because it requires the governance system to have stored the join
    key at decision time rather than reconstructing it from timestamps afterwards.
    """
    links = resolve_external(session, system, external_id)
    if not links:
        raise HTTPException(404, "no governed trace correlates with that id")
    out = []
    for link in links:
        trace = session.get(Trace, link.trace_id)
        out.append(
            {
                "trace_id": link.trace_id,
                "agent": trace.agent_slug if trace else None,
                "verdict": trace.verdict if trace else None,
                "started_at": trace.started_at.isoformat() if trace else None,
                "system": link.system,
                "external_trace_id": link.external_trace_id,
                "external_run_id": link.external_run_id,
                "url": link.url,
                "detail": f"/api/traces/{link.trace_id}",
            }
        )
    return {"matches": out}


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    detail = full_trace(session, trace_id, explain=explain_recorded)
    if detail is None:
        raise HTTPException(404, "unknown trace")
    detail["links"] = [
        {
            "system": link.system,
            "external_trace_id": link.external_trace_id,
            "external_run_id": link.external_run_id,
            "project": link.project,
            "url": link.url,
            "direction": link.direction,
        }
        for link in links_for(session, trace_id)
    ]
    return detail


# ---------------------------------------------------------------------------
# Audit chain — append-only, no mutation routes exist
# ---------------------------------------------------------------------------


@router.get("/audit/entries")
def audit_entries(
    limit: int = 200,
    action: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    query = select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(limit)
    if action:
        query = query.where(AuditEntry.action == action)
    return {
        "stats": chain.chain_stats(session),
        "entries": [chain.entry_to_row(e) for e in session.scalars(query)],
    }


@router.post("/audit/verify")
def verify_chain(
    start_seq: int | None = None,
    end_seq: int | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    result = chain.verify_range(session, start_seq, end_seq)
    return {**result.to_json(), "stats": chain.chain_stats(session)}


@router.post("/audit/checkpoint", status_code=201)
def checkpoint(
    session: Session = Depends(db), user: User = Depends(require("evidence"))
) -> dict[str, Any]:
    record = chain.checkpoint_now(session)
    if record is None:
        raise HTTPException(400, "audit chain is empty")
    return {
        "seq": record.seq,
        "digest": record.digest,
        "signed_at": _iso(record.signed_at),
        "by": user.email,
    }


# ---------------------------------------------------------------------------
# SIEM export
# ---------------------------------------------------------------------------


@router.get("/export/siem", response_class=PlainTextResponse)
def export_siem(
    format: str = Query("jsonl", pattern="^(jsonl|cef|leef|otlp)$"),
    since_days: int = 7,
    limit: int = 1000,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> str:
    return siem.export(
        session,
        format,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days),
        limit=limit,
    )


# ---------------------------------------------------------------------------
# The control catalog, as names
# ---------------------------------------------------------------------------


@router.get("/overview")
def workspace_overview(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Agents, their risk tiers and open issues: the Reports summary."""
    from agentfox.platform.registry.service import overview

    return overview(session)


@router.get("/catalog/controls")
def catalog_controls(_user: User = Depends(current_user)) -> dict[str, Any]:
    """Every control's id and title, from the catalog this build ships.

    Rules, findings and traces cite control ids everywhere; this is how a reader gets
    the name beside the code. Their status against a framework is AgentFox Enterprise
    (`/api/controls`).
    """
    from agentfox.capabilities.compliance.catalog import load_catalog

    catalog = load_catalog()
    return {
        "version": catalog.get("version"),
        "controls": [
            {"key": c["key"], "title": c.get("title", c["key"])}
            for c in catalog.get("controls") or []
            if c.get("key")
        ],
    }


# ---------------------------------------------------------------------------
# Retention & legal hold
# ---------------------------------------------------------------------------


@router.get("/retention")
def retention(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Every data class with its period, the last purge, the next one, and legal holds."""
    return {
        **retention_svc.overview(session),
        "policies": [
            {
                "data_class": p.data_class,
                "retain_days": p.retain_days,
                "redact_fields": p.redact_fields,
            }
            for p in session.scalars(select(RetentionPolicy))
        ],
        "legal_holds": [
            {
                "id": h.id,
                "scope": h.scope_json,
                "reason": h.reason,
                "placed_by": h.placed_by,
                "placed_at": _iso(h.placed_at),
                "released_at": _iso(h.released_at),
            }
            for h in session.scalars(select(LegalHold))
        ],
    }


class RetentionIn(BaseModel):
    retain_days: int
    #: Required: shortening retention destroys records, and the audit entry says why.
    reason: str
    redact_fields: list[str] | None = None


@router.put("/retention/{data_class}")
def set_retention(
    data_class: str,
    payload: RetentionIn,
    session: Session = Depends(db),
    user: User = Depends(require("retention")),
) -> dict[str, Any]:
    """Change how long one data class is kept. Audited as `operator.retention.changed`."""
    from agentfox.platform.ledger.operator_log import ReasonRequired

    try:
        policy = retention_svc.set_policy(
            session,
            data_class,
            payload.retain_days,
            actor=user.email or user.id,
            reason=payload.reason,
            redact_fields=payload.redact_fields,
        )
    except (retention_svc.RetentionError, ReasonRequired) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "data_class": policy.data_class,
        "retain_days": policy.retain_days,
        "redact_fields": policy.redact_fields,
    }


@router.post("/retention/purge")
def purge_now(
    session: Session = Depends(db), user: User = Depends(require("retention"))
) -> dict[str, Any]:
    """Run the retention purge now, through the same job the daily schedule runs."""
    from agentfox.apps import jobs as _jobs  # noqa: F401 - registers retention.purge

    job = jobs_db.enqueue(
        session,
        "retention.purge",
        payload={"trigger": "manual", "requested_by": user.email or user.id},
        org_id=session_org(session),
        requested_by=user.email or user.id,
    )
    jobs_db.run_job(session, job)
    session.refresh(job)
    if job.status != "done":
        raise HTTPException(502, f"retention purge failed: {job.last_error}")
    return {"job_id": job.id, **(job.result_json or {})}


@router.get("/retention/runs")
def retention_runs(
    limit: int = 20, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    from agentfox.core.models import RetentionRun

    rows = session.scalars(
        select(RetentionRun).order_by(RetentionRun.started_at.desc()).limit(min(limit, 100))
    )
    return {"runs": [retention_svc.run_json(r) for r in rows]}


class LegalHoldIn(BaseModel):
    scope: dict[str, Any] = Field(default_factory=dict)
    reason: str


@router.post("/legal-holds", status_code=201)
def place_hold(
    payload: LegalHoldIn,
    session: Session = Depends(db),
    user: User = Depends(require("compliance")),
) -> dict[str, Any]:
    hold = LegalHold(scope_json=payload.scope, reason=payload.reason, placed_by=user.email)
    session.add(hold)
    session.flush()
    chain.append(
        session,
        "legal_hold.placed",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="legal_hold",
        subject_id=hold.id,
        payload={"scope": payload.scope, "reason": payload.reason},
    )
    return {"id": hold.id, "placed_at": _iso(hold.placed_at)}


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).isoformat()
