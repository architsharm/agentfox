"""Deferred job queue observability + cron backstop.

Evidence-package export and red-team-campaign runs enqueue and process within
the same request that creates them (see `platform/jobs/store.py`'s own module docstring
for why, not a design accident). What these routes add is the part that
same-request processing can't give a caller on its own: a durable, queryable
record of every attempt — including one that's dead-lettered, or one stuck in
`running` because the request that started it never got to finish.

The cron endpoint accepts GET (what Vercel Cron sends) and POST, and authenticates
with either `AGENTFOX_CRON_SECRET` or Vercel's own `CRON_SECRET`. Each call first
fills the queue from per-tenant `JobSchedule` rows (`agentfox.platform.jobs.scheduler`), then
recovers stuck jobs and drains everything due. Calling it twice in a row is safe:
a schedule enqueues at most once per interval and never while its previous job
is still pending or running.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps import jobs as job_handlers
from agentfox.apps import showcase
from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.core.config import get_settings
from agentfox.core.models import Job, User
from agentfox.core.tenancy import session_org
from agentfox.platform.jobs import scheduler
from agentfox.platform.jobs import store as jobs_db

# Imported for its side effect: registers the eval.run, compliance.recompute,
# canary.advance, drift.check, redteam.posture, monitors.run and probes.run handlers
# wherever this router loads.
_REGISTERED_KINDS = tuple(job_handlers.HANDLERS)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
def list_jobs(
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Includes dead-lettered jobs by default — that's the point (jobs.py's
    own docstring: the dead letter is public state, not a log line an
    operator has to know to go look for)."""
    query = (
        select(Job)
        .where(Job.org_id == session_org(session))
        .order_by(Job.enqueued_at.desc())
        .limit(limit)
    )
    if kind:
        query = query.where(Job.kind == kind)
    if status:
        query = query.where(Job.status == status)
    return {"jobs": [jobs_db.job_json(j) for j in session.scalars(query)]}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    job = session.get(Job, job_id)
    if job is None or job.org_id != session_org(session):
        raise HTTPException(404, "unknown job")
    return jobs_db.job_json(job)


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: str, session: Session = Depends(db), _user: User = Depends(require("jobs"))
) -> dict[str, Any]:
    job = session.get(Job, job_id)
    if job is None or job.org_id != session_org(session):
        raise HTTPException(404, "unknown job")
    revived = jobs_db.retry_dead(session, job_id)
    if revived is None:
        raise HTTPException(409, f"job is '{job.status}', not 'dead' — nothing to retry")
    jobs_db.run_job(session, revived)
    session.refresh(revived)
    return jobs_db.job_json(revived)


def _cron_secrets() -> list[str]:
    """Every configured cron secret. `AGENTFOX_CRON_SECRET` is ours; `CRON_SECRET` is
    the name Vercel sets and sends as `Authorization: Bearer <value>` on cron calls —
    accepting only the former meant the deployed cron was always refused."""
    candidates = [get_settings().cron_secret, os.environ.get("CRON_SECRET")]
    return [c for c in candidates if c]


def _require_cron_secret(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = _cron_secrets()
    if not expected:
        raise HTTPException(
            503,
            (
                "no cron secret is configured (AGENTFOX_CRON_SECRET or CRON_SECRET) — this "
                "endpoint is disabled"
            ),
        )
    given = (authorization or "").removeprefix("Bearer ").strip()
    # Compare against every candidate without short-circuiting, so timing does not
    # reveal which (if either) secret a guess was close to.
    matched = False
    for candidate in expected:
        matched |= secrets.compare_digest(given.encode(), candidate.encode())
    if not given or not matched:
        raise HTTPException(401, "invalid or missing cron secret")


@router.get(
    "/internal/jobs/run",
    dependencies=[Depends(_require_cron_secret)],
    operation_id="run_pending_jobs_cron_get",
)
@router.post(
    "/internal/jobs/run",
    dependencies=[Depends(_require_cron_secret)],
    operation_id="run_pending_jobs_cron_post",
)
def run_pending_jobs(limit: int = 50, session: Session = Depends(db)) -> dict[str, Any]:
    """The cron entry point. GET because that is what Vercel Cron sends; POST for
    anything else that drives it.

    0. With `settings.showcase_enabled`, make sure the public showcase tenant and its
       opted-in probe target exist (`evaluation.showcase`), so it is one of the tenants
       the scheduling pass below finds.
    1. Scheduling pass (if `settings.scheduler_enabled`): per tenant, create default
       schedules and enqueue whatever is due.
    2. Recover jobs stuck in `running`, then run every pending job whose backoff has
       elapsed, across every tenant — the one place that's correct, since nothing
       about a cron trigger belongs to a single tenant's request.
    """
    try:
        with session.begin_nested():
            showcase_state = showcase.ensure_showcase(session)
    except Exception as exc:  # noqa: BLE001 - the showcase must never stop the cron
        log.warning("showcase setup failed: %s", exc, exc_info=True)
        showcase_state = {"error": f"{type(exc).__name__}: {exc}"}
    return {**scheduler.run_due(session, limit=limit), "showcase": showcase_state}
