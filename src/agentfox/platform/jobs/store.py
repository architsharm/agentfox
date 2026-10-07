"""Persisted backend for jobs.py's enqueue/run/retry/dead-letter interface.

`jobs.py`'s `JobQueue` is deliberately in-process (see its own docstring) — the
right choice for `agentfox demo`, the CLI, and tests, where one process's memory
is all there is. It is the wrong choice for the two operations docs/design/gap-analysis.md
named as the actual candidates for this (evidence-package export, red-team-
campaign runs): those run behind a serverless HTTP handler, where a `deque` in
one invocation's memory is gone the instant that invocation returns, and the
next request — even a retry of the exact same job — gets a fresh, empty queue.
A dead-lettered job in that world isn't "public state", it's a value that
existed for a few hundred milliseconds and was never seen by anyone.

So this module keeps the interface, swaps the backend to Postgres/SQLite (the
same "native default, swappable seam" pattern already used for the policy
engine and entitlement), and makes one deliberate simplification for this
deployment target: rather than a separate always-on worker polling a queue
(the classic shape, and the one Redis/SQS would give for free), a job is
enqueued and run in the same request that created it. That still buys the two
things jobs.py's docstring says actually matter — a transient failure gets
retried instead of just failing the request, and a permanent failure is a
`Job` row with `status="dead"` a human can find later, not a bare 500 nobody
recorded — without inventing an async polling UI Vercel's own cron-frequency
limits (once/day on the Hobby tier this ships on) would make painfully slow
for something a person is sitting in a browser waiting on. `run_pending()` is
still exposed and wired to a cron-triggered endpoint (`GET|POST
/api/internal/jobs/run`) as a backstop, and that backstop does three things:

* **Recovery.** A job left in `running` for longer than
  `settings.job_stuck_after_seconds` — the request that started it crashed or hit
  a platform timeout mid-attempt — is counted as a failed attempt and either
  requeued with backoff or dead-lettered, so a crashed job does not sit in
  `running` forever.
* **Backoff.** A failed attempt sets `available_at = now + base * 2**(attempts-1)`
  and `run_pending` skips a job until then, so a retry is not burned against an
  upstream that failed a millisecond ago.
* **Honesty on the request path.** A request that enqueues-and-runs must not read
  an empty `result_json` off a job that failed its first attempt and was put back
  for retry as if it had succeeded; `run_job` runs exactly the job the request
  created, and the caller checks `status` for all three outcomes.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import Job, utcnow
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.platform.jobs.queue import DEAD, DONE, PENDING, RUNNING

log = logging.getLogger(__name__)

#: kind -> handler. A handler takes the session (already tenant-bound to the
#: job's org) and the job's payload, and returns a JSON-serialisable result
#: dict stashed on the job as `result_json` — the shape a caller polls for.
_HANDLERS: dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {}


def register(kind: str, handler: Callable[[Session, dict[str, Any]], dict[str, Any]]) -> None:
    _HANDLERS[kind] = handler


def is_registered(kind: str) -> bool:
    return kind in _HANDLERS


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    org_id: str,
    requested_by: str = "",
    max_attempts: int = 3,
    schedule_id: str | None = None,
) -> Job:
    """Accept work for later. Refuses a kind with no registered handler for the
    same reason jobs.py's in-process queue does: discovering nothing knows how
    to do this an hour (or a cron cycle) later, as missing evidence instead of
    a request-time error, is the exact failure this module exists to avoid."""
    if kind not in _HANDLERS:
        raise KeyError(
            f"no handler registered for '{kind}'. Refusing to accept work that "
            "nothing knows how to do — the failure would surface later as "
            "missing evidence, not now as a clear error"
        )
    job = Job(
        kind=kind,
        payload_json=payload or {},
        max_attempts=max_attempts,
        org_id=org_id,
        requested_by=requested_by,
        enqueued_at=utcnow(),
        schedule_id=schedule_id,
    )
    session.add(job)
    session.flush()
    return job


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes for timezone-aware columns; everything we
    store is UTC, so a naive value read back is UTC too."""
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    """A handler's result lands in a JSON column; datetimes and the like become ISO
    strings here rather than failing the flush after the work already succeeded."""
    return json.loads(
        json.dumps(value, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
    )


def backoff_delay(attempts: int) -> dt.timedelta:
    """Exponential backoff after the `attempts`-th failed attempt: base, 2*base, 4*base…"""
    base = max(0, int(get_settings().job_backoff_base_seconds))
    return dt.timedelta(seconds=base * (2 ** max(0, attempts - 1)))


def _fail_attempt(session: Session, job: Job, error: str, *, now: dt.datetime) -> None:
    """Record a failed attempt: dead-letter at max attempts, else requeue with backoff."""
    job.last_error = error
    job.started_at = None
    if job.attempts >= job.max_attempts:
        job.status = DEAD
        job.finished_at = now
        job.available_at = None
    else:
        job.status = PENDING
        job.available_at = now + backoff_delay(job.attempts)
    session.flush()


def _run_one(session: Session, job: Job, *, now: dt.datetime) -> None:
    # Caller has already bound the session to job.org_id.
    job.status = RUNNING
    job.attempts += 1
    job.started_at = now
    job.available_at = None
    session.flush()
    try:
        result = _HANDLERS[job.kind](session, job.payload_json or {})
    except Exception as exc:  # noqa: BLE001 - a job's own failure must not propagate raw
        error = f"{type(exc).__name__}: {exc}"
        log.warning("job '%s' (%s) attempt %d failed: %s", job.kind, job.id, job.attempts, error)
        log.debug("%s", traceback.format_exc())
        _fail_attempt(session, job, error, now=now)
        return
    job.status = DONE
    job.result_json = _json_safe(result or {})
    job.finished_at = now
    job.started_at = None
    session.flush()


def run_job(session: Session, job: Job, *, now: dt.datetime | None = None) -> Job:
    """Run exactly this job, now, if it is pending — the request path's primitive.

    `run_pending(limit=1)` runs the *oldest* eligible job for the tenant, which is not
    necessarily the one the request just enqueued (a scheduled job may be ahead of it),
    and the request would then read an empty result off its own untouched job. This
    runs the one the caller means. The caller must then look at `job.status`: `done`,
    `dead`, or `pending` (failed, queued for retry at `available_at`).
    """
    if job.status != PENDING:
        return job
    bind_session(session, job.org_id)
    _run_one(session, job, now=now or utcnow())
    return job


def recover_stuck(
    session: Session, *, org_id: str | None = None, now: dt.datetime | None = None
) -> int:
    """Treat a job `running` for longer than `settings.job_stuck_after_seconds` as a
    crashed attempt. The attempt already counted when it started, so recovery only
    decides requeue-with-backoff or dead-letter. Returns how many were recovered."""
    now = now or utcnow()
    cutoff = now - dt.timedelta(seconds=max(0, int(get_settings().job_stuck_after_seconds)))
    query = select(Job).where(
        Job.status == RUNNING,
        or_(
            Job.started_at < cutoff,
            # Rows from before `started_at` existed: fall back to when they were queued.
            (Job.started_at.is_(None)) & (Job.enqueued_at < cutoff),
        ),
    )
    if org_id is not None:
        bind_session(session, org_id)
        stuck = list(session.scalars(query))
    else:
        with system_scope("cron backstop: recovering jobs stuck in running across every tenant"):
            stuck = list(session.scalars(query))
    for job in stuck:
        bind_session(session, job.org_id)
        started = _aware(job.started_at) or _aware(job.enqueued_at)
        log.warning(
            "job '%s' (%s) stuck in running since %s; recovering", job.kind, job.id, started
        )
        if job.attempts <= 0:
            job.attempts = 1
        _fail_attempt(
            session,
            job,
            f"stuck in running since {started.isoformat() if started else '?'} (longer than "
            f"{get_settings().job_stuck_after_seconds}s) — presumed crashed mid-attempt",
            now=now,
        )
    return len(stuck)


def run_pending(
    session: Session,
    *,
    org_id: str | None = None,
    limit: int = 50,
    now: dt.datetime | None = None,
) -> int:
    """Run queued work. `org_id=None` (the cron path) processes across every
    tenant present in the table — the request path always passes its own
    org_id, since a caller's request should never trigger another tenant's
    queued work. Returns how many jobs reached a terminal state (done or
    dead — a job put back to pending for another attempt doesn't count).

    Jobs stuck in `running` are recovered first, and a job still inside its
    backoff window (`available_at` in the future) is skipped.

    Every query in this codebase against a `TenantScoped` model (`Job`
    included) is automatically restricted to the session's *bound* tenant —
    an `execute_state`-level filter (tenancy.py's `_tenant_criteria`), not
    something an explicit `.where(Job.org_id == ...)` clause here could
    override or duplicate. So finding this org's pending jobs means actually
    binding the session to it first, and finding every org's pending jobs
    (the cron path) means the one sanctioned way to see across tenants —
    `system_scope()` — not an unfiltered query the isolation layer would
    silently filter anyway.
    """
    now = now or utcnow()
    recover_stuck(session, org_id=org_id, now=now)
    query = (
        select(Job)
        .where(
            Job.status == PENDING,
            or_(Job.available_at.is_(None), Job.available_at <= now),
        )
        .order_by(Job.enqueued_at)
        .limit(limit)
    )
    if org_id is not None:
        bind_session(session, org_id)
        jobs = list(session.scalars(query))
    else:
        with system_scope("cron backstop: running pending jobs across every tenant"):
            jobs = list(session.scalars(query))
    finished = 0
    for job in jobs:
        # Re-bind per job: the cron sweep's jobs list can span several
        # tenants, and the handler's own writes (an EvidencePackage, a
        # RedTeamCampaign) must land in the job's tenant, not whichever one
        # ran immediately before it.
        bind_session(session, job.org_id)
        _run_one(session, job, now=now)
        if job.status in (DONE, DEAD):
            finished += 1
    if org_id is not None:
        bind_session(session, org_id)
    return finished


def retry_dead(session: Session, job_id: str) -> Job | None:
    """Put one dead-lettered job back to pending, once whatever broke it has
    been fixed. Mirrors jobs.py's JobQueue.retry_dead, scoped to one job by id
    rather than by kind since a caller here is reviving a specific row they can
    see, not blind-retrying a whole category."""
    job = session.get(Job, job_id)
    if job is None or job.status != DEAD:
        return None
    job.status = PENDING
    job.attempts = 0
    job.last_error = ""
    job.finished_at = None
    job.available_at = None
    job.started_at = None
    session.flush()
    return job


def job_json(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "result": job.result_json,
        "requested_by": job.requested_by,
        "enqueued_at": _iso(job.enqueued_at),
        "finished_at": _iso(job.finished_at),
        "started_at": _iso(job.started_at),
        "available_at": _iso(job.available_at),
        "schedule_id": job.schedule_id,
    }


def _iso(value: dt.datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None
