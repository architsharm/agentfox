"""Evidence package routes. Part of AgentFox Enterprise (BSL 1.1, see ee/LICENSE).

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

from agentfox_ee.evidence import package as evidence
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.core.models import (
    EvidencePackage,
    User,
)
from agentfox.core.tenancy import session_org
from agentfox.platform.jobs import store as jobs_db
from agentfox.platform.ledger import chain

router = APIRouter(prefix="/api", tags=["evidence"])


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


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).isoformat()
