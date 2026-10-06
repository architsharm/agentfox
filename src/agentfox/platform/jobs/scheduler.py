"""Recurring work: the part that fills the job queue.

The cron endpoint (`/api/internal/jobs/run`) drains the job queue, but draining alone
runs only what someone has already enqueued. A `JobSchedule` row per tenant per kind is
what puts periodic work — control recomputation, drift checks, canary advancement,
posture campaigns — on the queue, so it runs unattended; the same cron call then drains it.

Two functions:

* :func:`ensure_default_schedules` creates the default rows for the session's tenant,
  once. It never touches a row that already exists, so an operator who disabled or
  retuned a schedule keeps that choice.
* :func:`enqueue_due` enqueues one job for every enabled schedule whose `next_due_at`
  has passed, then moves `next_due_at` a full interval past *now*. A cron that fires
  late by several intervals enqueues once, not once per missed interval, and a schedule
  whose previous job is still `pending` or `running` enqueues nothing — a slow or
  failing job cannot pile copies of itself onto the queue.

Everything is gated by `settings.scheduler_enabled`.

Default schedules (per tenant)
------------------------------

======================  =========  ========  ===================================================
kind                    interval   enabled   why
======================  =========  ========  ===================================================
``canary.advance``      1 hour     yes       Drives every rolling policy canary through the
                                             two-way gate. Rollback is immediate; advancing
                                             still needs `min_dwell_seconds` at each step.
``compliance.recompute``  1 day    yes       Keeps control status current (30-day window)
                                             without someone pressing "compute".
``drift.check``         1 day      yes       Persists drift windows and drift findings
                                             (groundedness), so `GET /api/eval/drift` stays
                                             read-only.
``grants.propose``      1 day      yes       Learned permissions: files ``tool.declare`` and
                                             ``capability.grant`` proposals from observed
                                             tool calls. Files only; a person approves.
``escalation.scan``     1 hour     yes       Missed-escalation pass over the last 24 hours:
                                             findings for every agent, retroactive hand-offs
                                             where the escalation policy enforces, overdue
                                             hand-offs marked breached.
``redteam.posture``     7 days     no        Adaptive red-team campaign per active agent. Off
                                             by default: it is the most expensive job and
                                             files findings, so a tenant opts in.
``monitors.run``        10 min     yes       Runs the tenant's due monitors. Each monitor keeps
                                             its own interval (`Monitor.next_run_at`), so this
                                             only decides how often "due" is checked; with no
                                             monitor due the job does nothing.
======================  =========  ========  ===================================================

How often anything runs is bounded by how often the runner is triggered. The Vercel
cron fires once a day (Hobby tier); `.github/workflows/monitors.yml` calls the same
endpoint every 30 minutes, and self-hosted deployments run `agentfox admin jobs
run-due` from their own scheduler. Calling it more often than an interval is always
safe: schedules and monitors both refuse to run before they are due.

`eval.run` has a handler but no default schedule: it needs a suite and a target that
only the tenant can name. Add a `JobSchedule` row with that payload to run one on a
cadence.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import Agent, Job, JobSchedule, Monitor, Policy, User, utcnow
from agentfox.core.tenancy import bind_session, session_org, system_scope
from agentfox.core.vocab import AUTOMATION_ACTOR_TYPE
from agentfox.platform.jobs import store as jobs_db
from agentfox.platform.jobs.queue import PENDING, RUNNING

HOUR = 3600
DAY = 24 * HOUR


@dataclass(frozen=True)
class DefaultSchedule:
    kind: str
    interval_seconds: int
    enabled: bool
    payload: dict[str, Any] = field(default_factory=dict)
    why: str = ""


DEFAULT_SCHEDULES: tuple[DefaultSchedule, ...] = (
    DefaultSchedule(
        "canary.advance",
        HOUR,
        True,
        {},
        "advance, hold or roll back every rolling canary through the two-way gate",
    ),
    DefaultSchedule(
        "compliance.recompute",
        DAY,
        True,
        {"window_days": 30},
        "keep control status current",
    ),
    DefaultSchedule(
        "drift.check",
        DAY,
        True,
        {"scorer": "groundedness"},
        "persist drift windows and findings",
    ),
    DefaultSchedule(
        "tuning.propose",
        DAY,
        True,
        {"days": 30},
        "file rule cut-off proposals from labelled false positives; a person decides each",
    ),
    DefaultSchedule(
        "grants.propose",
        DAY,
        True,
        {"days": 30},
        "file tool declarations and grants learned from observed tool calls; a person decides each",
    ),
    DefaultSchedule(
        "escalation.scan",
        HOUR,
        True,
        {"since_hours": 24},
        "missed escalations and SLA breaches; hand-offs only where the policy enforces",
    ),
    DefaultSchedule(
        "monitors.run",
        10 * 60,
        True,
        {},
        "re-check connected sources whose own interval has passed",
    ),
    DefaultSchedule(
        "redteam.posture",
        7 * DAY,
        False,
        {"budget": 3, "seed": 1337},
        "adaptive red-team posture per agent; expensive, opt-in",
    ),
    DefaultSchedule(
        "probes.run",
        HOUR,
        True,
        {},
        "probe opted-in deployed agents that are due; sends nothing without an opt-in",
    ),
)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def ensure_default_schedules(session: Session, *, created_by: str = "") -> list[JobSchedule]:
    """Create any default schedule the session's tenant does not have yet.

    Returns the rows created (empty when every default already exists). A new row is
    due immediately (`next_due_at=None`), so the first cron run after a tenant appears
    does the work rather than waiting a full interval.
    """
    existing = set(session.scalars(select(JobSchedule.kind)))
    created: list[JobSchedule] = []
    for default in DEFAULT_SCHEDULES:
        if default.kind in existing:
            continue
        row = JobSchedule(
            kind=default.kind,
            payload_json=dict(default.payload),
            interval_seconds=default.interval_seconds,
            enabled=default.enabled,
            next_due_at=None,
            created_by=created_by or get_settings().improvement_actor_id,
        )
        session.add(row)
        created.append(row)
    if created:
        session.flush()
    return created


def _has_open_job(session: Session, schedule: JobSchedule) -> bool:
    return (
        session.scalar(
            select(Job.id)
            .where(Job.schedule_id == schedule.id, Job.status.in_((PENDING, RUNNING)))
            .limit(1)
        )
        is not None
    )


def enqueue_due(session: Session, now: dt.datetime | None = None) -> list[Job]:
    """Enqueue one job per enabled, due schedule in the session's bound tenant.

    Returns the jobs enqueued. No-op when `settings.scheduler_enabled` is false.
    """
    settings = get_settings()
    if not settings.scheduler_enabled:
        return []
    now = now or utcnow()
    org_id = session_org(session)
    enqueued: list[Job] = []
    schedules = session.scalars(
        select(JobSchedule).where(JobSchedule.enabled.is_(True)).order_by(JobSchedule.kind)
    )
    for schedule in list(schedules):
        due_at = _aware(schedule.next_due_at)
        if due_at is not None and due_at > now:
            continue
        if _has_open_job(session, schedule):
            # The previous run has not finished (or is waiting out its backoff). Leave
            # next_due_at alone so the schedule is picked up once that job settles.
            continue
        payload = dict(schedule.payload_json or {})
        payload.setdefault("actor_type", AUTOMATION_ACTOR_TYPE)
        payload.setdefault("requested_by", settings.improvement_actor_id)
        job = jobs_db.enqueue(
            session,
            schedule.kind,
            payload,
            org_id=org_id,
            requested_by=f"schedule:{schedule.id}",
            schedule_id=schedule.id,
        )
        schedule.last_enqueued_at = now
        schedule.next_due_at = now + dt.timedelta(seconds=max(1, int(schedule.interval_seconds)))
        enqueued.append(job)
    if enqueued:
        session.flush()
    return enqueued


def known_tenants(session: Session) -> list[str]:
    """Every tenant with users, agents, policies, schedules or monitors — the ones a cron
    run should create default schedules for and enqueue due work in."""
    orgs: set[str] = set()
    with system_scope("scheduler: enumerating tenants to enqueue recurring work"):
        for model in (User, Agent, Policy, JobSchedule, Monitor):
            orgs.update(o for o in session.scalars(select(model.org_id).distinct()) if o)
    return sorted(orgs)


def schedule_all_tenants(session: Session, now: dt.datetime | None = None) -> dict[str, int]:
    """The cron's scheduling pass: per tenant, ensure defaults then enqueue due work.

    Follows `jobs_db.run_pending`'s pattern — enumerate across tenants inside
    `system_scope`, then bind the session to each tenant before touching its rows, so
    every schedule and job lands in the tenant it belongs to. Returns {org_id: jobs
    enqueued}.
    """
    if not get_settings().scheduler_enabled:
        return {}
    now = now or utcnow()
    out: dict[str, int] = {}
    for org_id in known_tenants(session):
        bind_session(session, org_id)
        ensure_default_schedules(session)
        out[org_id] = len(enqueue_due(session, now))
    return out


def run_due(session: Session, *, limit: int = 50, now: dt.datetime | None = None) -> dict[str, Any]:
    """One pass of the job runner — what the cron route and `agentfox admin jobs run-due`
    both do: fill the queue from schedules, recover stuck jobs, run everything due."""
    scheduled = schedule_all_tenants(session, now)
    recovered = jobs_db.recover_stuck(session, org_id=None, now=now)
    finished = jobs_db.run_pending(session, org_id=None, limit=limit, now=now)
    return {
        "processed": finished,
        "recovered": recovered,
        "scheduled": sum(scheduled.values()),
        "scheduled_by_tenant": scheduled,
        "scheduler_enabled": get_settings().scheduler_enabled,
    }
