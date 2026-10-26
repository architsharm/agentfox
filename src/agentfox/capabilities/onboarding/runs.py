"""Attack test runs as rows: one per run, keyed by tenant and project, each with the
map it runs on.

They used to be one JSON object on the user's onboarding row, rewritten whole by every
request, so two requests at once lost one's write; one map per user, so a second
`agentfox init` in another repository replaced the map a queued run would use; and a
runner that died left its run "running" for good, which refused every new test.

Now a runner claims a run with a lease it renews each time it reports. A run whose
lease lapses (or that no runner picked up in time) is failed with a sentence saying
so, which frees the project for a new test. Results only ever append, and a run that
has finished refuses more.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agentfox.capabilities.onboarding import service
from agentfox.core.models import OnboardingRun, as_aware

#: A claimed run whose runner has not reported for this long is treated as dead.
LEASE_SECONDS = 120
#: A queued run no runner has picked up in this long is given up on.
QUEUE_SECONDS = 15 * 60
ACTIVE = ("queued", "running")
TERMINAL = ("done", "failed")

DEAD_RUNNER = (
    "The test stopped: `agentfox init` stopped responding while it ran. "
    "Start it again in the project's repository, then run the test again."
)
NO_RUNNER = (
    "No `agentfox init` picked this test up. Run it in the project's repository "
    "(it must stay running), then start the test again."
)


class RunFinished(Exception):
    """Results for a run that has already finished."""


def _iso(value: dt.datetime | None) -> str | None:
    value = as_aware(value)
    return value.isoformat() if value else None


def as_dict(run: OnboardingRun) -> dict[str, Any]:
    """The run in the shape `service` builds and reads (and the dashboard's run JSON)."""
    return {
        "id": run.id,
        "project": run.project,
        "guards": run.guards,
        "sets": list(run.sets or []),
        "phase": run.phase,
        "status": run.status,
        "total": run.total,
        "totals": dict(run.totals or {}),
        "results": list(run.results or []),
        "error": run.error,
        "createdAt": _iso(run.created_at),
        "startedAt": _iso(run.started_at),
        "finishedAt": _iso(run.finished_at),
    }


def stale_reason(run: OnboardingRun, now: dt.datetime) -> str | None:
    """Why an unfinished run is over although nobody said so, or None."""
    if run.status == "running":
        lease = as_aware(run.lease_expires_at)
        if lease is not None and lease <= now:
            return DEAD_RUNNER
    if run.status == "queued":
        created = as_aware(run.created_at)
        if created is not None and (now - created).total_seconds() > QUEUE_SECONDS:
            return NO_RUNNER
    return None


def view(run: OnboardingRun, now: dt.datetime) -> dict[str, Any]:
    """The run as it stands, a lapsed one shown failed. Reading writes nothing."""
    out = as_dict(run)
    reason = stale_reason(run, now)
    if reason:
        out.update(status="failed", error=reason, finishedAt=out["finishedAt"] or now.isoformat())
    return out


def expire(session: Session, runs: list[OnboardingRun], now: dt.datetime) -> None:
    """Fail the runs whose runner is gone, so they stop holding their project."""
    for run in runs:
        reason = stale_reason(run, now)
        if reason:
            run.status, run.error, run.finished_at = "failed", reason, now
            run.lease_expires_at = None
    session.flush()


def create(
    session: Session,
    *,
    user_id: str,
    org_id: str,
    phase: str,
    structure: dict[str, Any],
    now: dt.datetime,
    project: str | None = None,
    guards: list[str] | None = None,
    sets: list[str] | None = None,
) -> OnboardingRun:
    built = service.new_run(phase, structure, now, project=project, guards=guards, sets=sets)
    run = OnboardingRun(
        id=built["id"],
        org_id=org_id,
        user_id=user_id,
        project=project,
        phase=phase,
        status="queued",
        guards=guards,
        sets=built["sets"],
        structure=structure,
        total=built["total"],
        totals=built["totals"],
        results=[],
        created_at=now,
    )
    session.add(run)
    session.flush()
    return run


def for_project(session: Session, project: str) -> list[OnboardingRun]:
    """The project's runs, oldest first."""
    return list(
        session.scalars(
            select(OnboardingRun)
            .where(OnboardingRun.project == project)
            .order_by(OnboardingRun.created_at, OnboardingRun.id)
        )
    )


def for_user(session: Session, user_id: str) -> list[OnboardingRun]:
    return list(
        session.scalars(
            select(OnboardingRun)
            .where(OnboardingRun.user_id == user_id)
            .order_by(OnboardingRun.created_at, OnboardingRun.id)
        )
    )


def claim_next(
    session: Session, *, user_id: str, project: str | None, now: dt.datetime
) -> OnboardingRun | None:
    """Hand the oldest waiting run this runner can run to it, under a lease.

    A runner runs its own project's tests, and its user's setup-wizard tests (which
    have no project). The row is locked while it is claimed, so two runners polling at
    once never both take it.
    """
    mine = OnboardingRun.project.is_(None) & (OnboardingRun.user_id == user_id)
    where = or_(OnboardingRun.project == project, mine) if project else mine
    waiting = list(
        session.scalars(
            select(OnboardingRun)
            .where(where, OnboardingRun.status.in_(ACTIVE))
            .order_by(OnboardingRun.created_at, OnboardingRun.id)
            .with_for_update(skip_locked=True)
        )
    )
    expire(session, waiting, now)
    run = next((r for r in waiting if r.status == "queued"), None)
    if run is None:
        return None
    run.status = "running"
    run.started_at = now
    run.lease_expires_at = now + dt.timedelta(seconds=LEASE_SECONDS)
    session.flush()
    return run


def locked(session: Session, run_id: str) -> OnboardingRun | None:
    return session.scalar(select(OnboardingRun).where(OnboardingRun.id == run_id).with_for_update())


def add_results(
    session: Session,
    run: OnboardingRun,
    results: list[dict[str, Any]],
    *,
    done: bool,
    error: str | None,
    now: dt.datetime,
) -> OnboardingRun:
    """Append a runner's report to a run it holds (locked by the caller), renewing
    its lease. A finished run refuses: a late error can't turn "done" into "failed"."""
    if run.status in TERMINAL:
        raise RunFinished(run.status)
    reason = stale_reason(run, now)
    if reason:
        expire(session, [run], now)
        raise RunFinished(run.status)
    if run.status == "queued":  # reported by a runner that never polled (an old client)
        run.status, run.started_at = "running", now
    updated = service.add_results(as_dict(run), results, done=done, error=error, now=now)
    run.results = updated["results"][: run.total or None]
    run.status = updated["status"]
    run.error = updated["error"]
    if updated["finishedAt"]:
        run.finished_at = now
        run.lease_expires_at = None
    else:
        run.lease_expires_at = now + dt.timedelta(seconds=LEASE_SECONDS)
    session.flush()
    return run


def remove_project(session: Session, project: str) -> None:
    for run in for_project(session, project):
        session.delete(run)
    session.flush()
