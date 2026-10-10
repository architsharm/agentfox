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
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.apps.report import evidence
from agentfox.capabilities.compliance import (
    FRAMEWORK_TITLES,
    all_frameworks,
    board_view,
    classify,
    compute_all,
    controls_for_framework,
    framework_coverage,
    latest_statuses,
    obligation_calendar,
    posture,
    requirements_for_framework,
)
from agentfox.capabilities.compliance import (
    register as risk_register,
)
from agentfox.capabilities.compliance import retention as retention_svc
from agentfox.capabilities.compliance import reviews as reviews_svc
from agentfox.capabilities.compliance.risk import assess
from agentfox.capabilities.detection.tuning import explain_recorded
from agentfox.core.models import (
    AuditEntry,
    Control,
    EvidencePackage,
    FrameworkMapping,
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
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
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
# Evidence packages
# ---------------------------------------------------------------------------


class EvidenceIn(BaseModel):
    agents: list[str] = Field(default_factory=lambda: ["*"])
    controls: list[str] = Field(default_factory=lambda: ["*"])
    period_from: dt.datetime | None = None
    period_to: dt.datetime | None = None


def _run_evidence_package(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """The job's handler. Runs inside jobs_db.run_pending(), which has
    already tenant-bound the session to the job's own org_id, not whatever
    context happened to be ambient when this got registered at import time."""
    period_from = (
        dt.datetime.fromisoformat(payload["period_from"]) if payload.get("period_from") else None
    )
    period_to = (
        dt.datetime.fromisoformat(payload["period_to"]) if payload.get("period_to") else None
    )
    package = evidence.build(
        session,
        agents=payload.get("agents"),
        controls=payload.get("controls"),
        period_from=period_from,
        period_to=period_to,
        requested_by=payload.get("requested_by", "system"),
    )
    return {
        "evidence_package_id": package.id,
        "path": package.path,
        "scope": package.scope_json,
        "manifest": package.manifest_json,
        "chain_verification": package.chain_verification_json,
    }


jobs_db.register("evidence.package", _run_evidence_package)


@router.post("/evidence", status_code=201)
def build_evidence(
    payload: EvidenceIn, session: Session = Depends(db), user: User = Depends(require("evidence"))
) -> dict[str, Any]:
    """Enqueues through jobs_db rather than calling evidence.build()
    directly, and processes it within this same request — see jobs_db's own
    module docstring for why same-request processing, not a deferred worker,
    is the honest fit here. A transient failure gets one automatic retry
    later, with backoff, and this returns 202 queued_for_retry meanwhile; a
    permanent one is a real `Job` row with status="dead" a human can find via
    GET /jobs, not a bare 500."""
    job = jobs_db.enqueue(
        session,
        "evidence.package",
        payload={
            "agents": payload.agents,
            "controls": payload.controls,
            "period_from": payload.period_from.isoformat() if payload.period_from else None,
            "period_to": payload.period_to.isoformat() if payload.period_to else None,
            "requested_by": user.email,
        },
        org_id=session_org(session),
        requested_by=user.email,
    )
    # Run exactly this job: run_pending(limit=1) picks the tenant's oldest eligible job,
    # which need not be the one just queued.
    jobs_db.run_job(session, job)
    session.refresh(job)
    if job.status == "dead":
        raise HTTPException(502, f"evidence package build failed: {job.last_error}")
    if job.status != "done":
        # A failed first attempt is queued for retry with backoff. A 201 with an empty
        # package here would look like success, so report it as still pending.
        return JSONResponse(
            status_code=202,
            content={
                "id": None,
                "status": "queued_for_retry",
                "job_id": job.id,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "last_error": job.last_error,
                "retry_after": jobs_db.job_json(job)["available_at"],
            },
        )
    result = job.result_json
    return {
        "id": result.get("evidence_package_id"),
        "path": result.get("path"),
        "scope": result.get("scope"),
        "manifest": result.get("manifest"),
        "chain_verification": result.get("chain_verification"),
        "job_id": job.id,
    }


@router.get("/evidence")
def list_evidence(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "packages": [
            {
                "id": p.id,
                "scope": p.scope_json,
                "requested_by": p.requested_by,
                "built_at": _iso(p.built_at),
                "chain_valid": (p.chain_verification_json or {}).get("valid"),
                "counts": (p.manifest_json or {}).get("counts", {}),
            }
            for p in session.scalars(
                select(EvidencePackage).order_by(EvidencePackage.built_at.desc())
            )
        ]
    }


@router.get("/evidence/{package_id}/download")
def download_evidence(
    package_id: str, session: Session = Depends(db), user: User = Depends(require("evidence"))
):
    package = session.get(EvidencePackage, package_id)
    if package is None or not package.path or not Path(package.path).exists():
        raise HTTPException(404, "evidence package not found on disk")
    # Who read the evidence is itself audit-relevant.
    chain.append(
        session,
        "evidence.downloaded",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="evidence_package",
        subject_id=package.id,
        payload={"scope": package.scope_json},
    )
    return FileResponse(
        package.path, media_type="application/zip", filename=f"agentfox-evidence-{package.id}.zip"
    )


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


# ---------------------------------------------------------------------------
# Controls & frameworks
# ---------------------------------------------------------------------------


def _catalog_current(session: Session) -> None:
    """Bring this tenant's stored catalog up to the one this build ships. It was only
    loaded into an empty workspace, so an upgrade that added a control left it "No such
    control" everywhere until someone ran the manual sync."""
    from agentfox.capabilities.compliance.catalog import catalog_behind, sync_catalog

    if catalog_behind(session):
        sync_catalog(session)


@router.get("/controls")
def list_controls(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    _catalog_current(session)
    statuses = latest_statuses(session)
    reviews = reviews_svc.latest_reviews(session)
    out = []
    for control in session.scalars(select(Control).order_by(Control.key)):
        mappings = list(
            session.scalars(
                select(FrameworkMapping).where(FrameworkMapping.control_key == control.key)
            )
        )
        status = statuses.get(control.key)
        out.append(
            {
                "key": control.key,
                "title": control.title,
                "objective": control.objective,
                "family": control.family,
                "pillar": control.pillar,
                "implemented_by": control.implemented_by,
                "evidence_sources": control.evidence_sources,
                "status": status.status if status else "not_computed",
                "rationale": status.rationale if status else None,
                "computed_at": _iso(status.computed_at) if status else None,
                "mappings": [
                    {
                        "framework": m.framework,
                        "reference": m.reference,
                        "review_status": m.review_status,
                    }
                    for m in mappings
                ],
                "reviews": {
                    fw: reviews_svc.review_state(r)
                    for (key, fw), r in reviews.items()
                    if key == control.key
                },
            }
        )
    return {"controls": out, "posture": posture(session)}


@router.get("/controls/{key}")
def get_control(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """One control: what it checks, the evidence computed for it, where it is mapped,
    and every attestation made against it."""
    _catalog_current(session)
    control = session.scalar(select(Control).where(Control.key == key))
    if control is None:
        raise HTTPException(404, f"unknown control '{key}'")
    mappings = list(
        session.scalars(select(FrameworkMapping).where(FrameworkMapping.control_key == key))
    )
    latest = reviews_svc.latest_reviews(session)
    frameworks: dict[str, dict[str, Any]] = {}
    for m in mappings:
        entry = frameworks.setdefault(
            m.framework,
            {
                "framework": m.framework,
                "title": FRAMEWORK_TITLES.get(m.framework, m.framework),
                "references": [],
                "review": reviews_svc.review_json(latest.get((key, m.framework))),
            },
        )
        entry["references"].append(m.reference)
    return {
        "key": control.key,
        "title": control.title,
        "objective": control.objective,
        "family": control.family,
        "implemented_by": control.implemented_by,
        "evidence_sources": control.evidence_sources,
        "status_rule": control.status_rule_json,
        "evidence": reviews_svc.control_evidence(session, key),
        "frameworks": sorted(frameworks.values(), key=lambda f: f["title"]),
        "history": [reviews_svc.review_json(r) for r in reviews_svc.review_history(session, key)],
        "outcomes": list(reviews_svc.OUTCOMES),
        "valid_days": reviews_svc.REVIEW_VALID_DAYS,
    }


class ControlReviewIn(BaseModel):
    framework: str
    outcome: str
    note: str = ""


@router.post("/controls/{key}/reviews", status_code=201)
def review_control(
    key: str,
    payload: ControlReviewIn,
    session: Session = Depends(db),
    user: User = Depends(require("control_review")),
) -> dict[str, Any]:
    """Attest one control against one framework. The reviewer is always the caller."""
    try:
        review = reviews_svc.record_review(
            session,
            key,
            payload.framework,
            payload.outcome,
            reviewer=user.email or user.id,
            note=payload.note,
        )
    except reviews_svc.ReviewError as exc:
        raise HTTPException(400, str(exc)) from exc
    return reviews_svc.review_json(review) or {}


@router.post("/controls/sync")
def sync_controls(
    session: Session = Depends(db),
    user: User = Depends(require("compliance")),
) -> dict[str, Any]:
    """Load the static control catalog and obligation calendar from YAML into this
    tenant's control-plane DB. `agentfox admin catalog sync` does the same thing
    from the CLI against whatever DB it's pointed at — this is the same idempotent
    upsert, reachable without shell access to the deployment, so a freshly provisioned
    org isn't stuck at "0 controls, mapped to seven frameworks" with no way to fix it
    from the product itself."""
    from agentfox.capabilities.compliance.catalog import sync_catalog, sync_obligations

    catalog = sync_catalog(session)
    obligations = sync_obligations(session)
    chain.append(
        session,
        "compliance.catalog_synced",
        actor_type="user",
        actor_id=user.email or user.id,
        payload={**catalog, "obligations": obligations},
    )
    return {"catalog": catalog, "obligations": obligations, "posture": posture(session)}


@router.post("/controls/compute")
def compute_controls(
    window_days: int = 30,
    session: Session = Depends(db),
    user: User = Depends(require("compliance")),
) -> dict[str, Any]:
    statuses = compute_all(session, window_days)
    chain.append(
        session,
        "compliance.computed",
        actor_type="user",
        actor_id=user.email or user.id,
        payload={"controls": len(statuses), "window_days": window_days},
    )
    return {
        "computed": len(statuses),
        "posture": posture(session),
        "statuses": [
            {"control_key": s.control_key, "status": s.status, "rationale": s.rationale}
            for s in statuses
        ],
    }


@router.get("/frameworks")
def frameworks(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    _catalog_current(session)
    return {"frameworks": all_frameworks(session)}


@router.get("/frameworks/{key}")
def framework(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """One framework: its requirements, the controls mapped to each with live status
    and attestation, its dated obligations, and its declared gaps."""
    _catalog_current(session)
    if key not in FRAMEWORK_TITLES and not session.scalar(
        select(FrameworkMapping.id).where(FrameworkMapping.framework == key).limit(1)
    ):
        raise HTTPException(404, f"unknown framework '{key}'")
    coverage = framework_coverage(session, key)
    controls = controls_for_framework(session, key)
    coverage["controls"] = controls
    coverage["requirements_detail"] = requirements_for_framework(session, key, controls)
    coverage["posture"] = posture(session, key)
    coverage["obligations_detail"] = [
        o for o in obligation_calendar(session) if o["framework"] == key
    ]
    return coverage


@router.get("/compliance/status")
def compliance_status(
    framework: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    _catalog_current(session)
    return posture(session, framework)


# ---------------------------------------------------------------------------
# Risk & obligations
# ---------------------------------------------------------------------------


@router.get("/risk/register")
def get_register(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"register": risk_register(session)}


@router.get("/risk/classify/{slug}")
def classify_agent(
    slug: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    return classify(session, agent)


class AssessIn(BaseModel):
    eu_ai_act_class: str | None = None
    inherent_risk: str = "medium"
    residual_risk: str = "low"
    answers: dict[str, Any] = Field(default_factory=dict)
    review_months: int = 12
    #: Whether the caller signs the assessment off. The signer is always the
    #: authenticated caller: a sign-off naming someone else is a forged signature.
    sign_off: bool = False
    #: Deprecated and ignored beyond a consistency check — kept so an old client that
    #: sends its own address still works, and one naming someone else is refused.
    signed_off_by: str | None = None


@router.post("/risk/assessments/{slug}", status_code=201)
def create_assessment(
    slug: str,
    payload: AssessIn,
    session: Session = Depends(db),
    user: User = Depends(require("compliance")),
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    signer = user.email or user.id
    if payload.signed_off_by and payload.signed_off_by.strip().lower() != str(signer).lower():
        raise HTTPException(
            403,
            "an assessment can only be signed off by the authenticated caller; "
            f"'{payload.signed_off_by}' is not you",
        )
    assessment = assess(
        session,
        agent,
        assessor=user.email,
        eu_ai_act_class=payload.eu_ai_act_class,
        inherent_risk=payload.inherent_risk,
        residual_risk=payload.residual_risk,
        answers=payload.answers,
        review_months=payload.review_months,
        signed_off_by=signer if (payload.sign_off or payload.signed_off_by) else None,
    )
    chain.append(
        session,
        "risk.assessed",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
        payload={
            "class": assessment.eu_ai_act_class,
            "residual_risk": assessment.residual_risk,
            "signed_off_by": assessment.signed_off_by,
        },
    )
    return {
        "id": assessment.id,
        "agent": slug,
        "eu_ai_act_class": assessment.eu_ai_act_class,
        "assessor": assessment.assessor,
        "signed_off_by": assessment.signed_off_by,
        "mitigations": assessment.mitigations_json,
        "next_review_at": _iso(assessment.next_review_at),
    }


@router.get("/obligations")
def obligations(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"obligations": obligation_calendar(session)}


@router.get("/board")
def board(session: Session = Depends(db), _user: User = Depends(current_user)) -> dict[str, Any]:
    return board_view(session)


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).isoformat()
