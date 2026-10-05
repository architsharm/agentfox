"""The cron actually fires, stuck and failing jobs recover, and schedules fill the queue.

Covers the Phase 0 scheduler gaps: a GET-only Vercel cron against a POST-only route and
the wrong secret name, `running` jobs nobody recovered, retries with no backoff,
deferrable kinds with no handler, nothing enqueueing recurring work, request routes
reporting success on a failed first attempt, adaptive red team unreachable over HTTP,
and a drift GET that wrote rows.
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentfox.jobs import handlers as job_handlers

from agentfox.jobs import store as jobs_db

from agentfox.jobs import scheduler
from agentfox.core.config import get_settings
from agentfox.core.models import (
    DriftWindow,
    EvalCase,
    EvalResult,
    EvalRun,
    EvalSuite,
    Finding,
    Job,
    JobSchedule,
)
from tests.conftest import as_user

NOW = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.UTC)
CRON = "/api/internal/jobs/run"


def _aware(value):
    return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value


# ---------------------------------------------------------------------------
# Cron route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["get", "post"])
def test_cron_accepts_get_and_post_with_the_nometria_secret(client, monkeypatch, method):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setattr(get_settings(), "cron_secret", "ours")
    response = getattr(client, method)(CRON, headers={"Authorization": "Bearer ours"})
    assert response.status_code == 200, response.text
    assert "processed" in response.json()


@pytest.mark.parametrize("method", ["get", "post"])
def test_cron_accepts_vercels_cron_secret_name(client, monkeypatch, method):
    monkeypatch.setattr(get_settings(), "cron_secret", None)
    monkeypatch.setenv("CRON_SECRET", "vercels")
    response = getattr(client, method)(CRON, headers={"Authorization": "Bearer vercels"})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("method", ["get", "post"])
def test_cron_refuses_without_any_secret_configured(client, monkeypatch, method):
    monkeypatch.setattr(get_settings(), "cron_secret", None)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    response = getattr(client, method)(CRON, headers={"Authorization": "Bearer anything"})
    assert response.status_code == 503


def test_cron_rejects_a_wrong_or_missing_secret_when_both_names_are_set(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", "ours")
    monkeypatch.setenv("CRON_SECRET", "vercels")
    assert client.get(CRON, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get(CRON).status_code == 401
    assert client.get(CRON, headers={"Authorization": "Bearer ours"}).status_code == 200
    assert client.get(CRON, headers={"Authorization": "Bearer vercels"}).status_code == 200


def test_cron_schedules_recurring_work_and_is_idempotent(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", "ours")
    headers = {"Authorization": "Bearer ours"}

    first = client.get(CRON, headers=headers).json()
    enabled_defaults = sum(1 for d in scheduler.DEFAULT_SCHEDULES if d.enabled)
    assert first["scheduled"] >= enabled_defaults
    assert first["processed"] >= enabled_defaults

    second = client.get(CRON, headers=headers).json()
    assert second["scheduled"] == 0, "a second call inside the interval must not re-enqueue"

    listing = client.get("/api/jobs", headers=as_user("aisha@example.com")).json()["jobs"]
    kinds = {j["kind"] for j in listing if j["schedule_id"]}
    assert {"canary.advance", "compliance.recompute", "drift.check"} <= kinds
    assert "redteam.posture" not in kinds, "disabled by default"
    assert all(j["status"] == "done" for j in listing if j["schedule_id"]), listing


def test_cron_honours_scheduler_enabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", "ours")
    monkeypatch.setattr(get_settings(), "scheduler_enabled", False)
    body = client.get(CRON, headers={"Authorization": "Bearer ours"}).json()
    assert body["scheduled"] == 0
    assert body["scheduler_enabled"] is False


# ---------------------------------------------------------------------------
# Recovery and backoff
# ---------------------------------------------------------------------------


def test_a_job_stuck_in_running_is_recovered_with_backoff(session):
    ran = []
    jobs_db.register("test.stuck", lambda s, p: ran.append(1) or {"ok": True})
    job = jobs_db.enqueue(session, "test.stuck", org_id="org-1", max_attempts=3)
    job.status = "running"
    job.attempts = 1
    job.started_at = NOW - dt.timedelta(seconds=get_settings().job_stuck_after_seconds + 60)
    session.flush()

    jobs_db.run_pending(session, org_id="org-1", now=NOW)
    session.refresh(job)
    assert job.status == "pending"
    assert "stuck in running" in job.last_error
    assert _aware(job.available_at) > NOW, "recovered as a failed attempt, so it backs off"
    assert ran == []

    jobs_db.run_pending(session, org_id="org-1", now=NOW + dt.timedelta(hours=1))
    session.refresh(job)
    assert job.status == "done"
    assert job.attempts == 2
    assert ran == [1]


def test_a_recently_started_running_job_is_left_alone(session):
    jobs_db.register("test.busy", lambda s, p: {})
    job = jobs_db.enqueue(session, "test.busy", org_id="org-1")
    job.status = "running"
    job.attempts = 1
    job.started_at = NOW - dt.timedelta(seconds=30)
    session.flush()
    assert jobs_db.recover_stuck(session, org_id="org-1", now=NOW) == 0
    session.refresh(job)
    assert job.status == "running"


def test_a_stuck_job_at_max_attempts_is_dead_lettered(session):
    jobs_db.register("test.stuck_dead", lambda s, p: {})
    job = jobs_db.enqueue(session, "test.stuck_dead", org_id="org-1", max_attempts=1)
    job.status = "running"
    job.attempts = 1
    job.started_at = NOW - dt.timedelta(days=1)
    session.flush()
    with_scope = jobs_db.recover_stuck(session, org_id=None, now=NOW)
    assert with_scope == 1
    session.refresh(job)
    assert job.status == "dead"


def test_backoff_delays_retries_exponentially(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "job_backoff_base_seconds", 60)
    attempts = []

    def explode(s, p):
        attempts.append(1)
        raise RuntimeError("upstream down")

    jobs_db.register("test.backoff", explode)
    job = jobs_db.enqueue(session, "test.backoff", org_id="org-1", max_attempts=3)

    jobs_db.run_pending(session, org_id="org-1", now=NOW)
    session.refresh(job)
    assert len(attempts) == 1 and job.status == "pending"
    assert _aware(job.available_at) == NOW + dt.timedelta(seconds=60)

    jobs_db.run_pending(session, org_id="org-1", now=NOW + dt.timedelta(seconds=30))
    assert len(attempts) == 1, "still inside the backoff window"

    second = NOW + dt.timedelta(seconds=61)
    jobs_db.run_pending(session, org_id="org-1", now=second)
    session.refresh(job)
    assert len(attempts) == 2
    assert _aware(job.available_at) == second + dt.timedelta(seconds=120)

    jobs_db.run_pending(session, org_id="org-1", now=second + dt.timedelta(seconds=121))
    session.refresh(job)
    assert len(attempts) == 3
    assert job.status == "dead"
    assert job.available_at is None


def test_a_failed_evidence_build_is_queued_for_retry_not_an_empty_success(client, monkeypatch):
    def explode(s, p):
        raise RuntimeError("storage unavailable")

    monkeypatch.setitem(jobs_db._HANDLERS, "evidence.package", explode)
    response = client.post(
        "/api/evidence", json={"agents": ["*"]}, headers=as_user("aisha@example.com")
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued_for_retry"
    assert body["id"] is None
    assert body["attempts"] == 1
    assert "storage unavailable" in body["last_error"]


def test_a_failed_first_attempt_is_reported_as_queued_for_retry_not_success(client, monkeypatch):
    def explode(s, p):
        raise RuntimeError("model endpoint timed out")

    monkeypatch.setitem(jobs_db._HANDLERS, "redteam.sweep", explode)
    response = client.post(
        "/api/redteam/campaigns",
        json={"agent": "support-triage"},
        headers=as_user("priya@example.com"),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued_for_retry"
    assert body["id"] is None
    assert body["attempts"] == 1
    assert "timed out" in body["last_error"]
    assert body["retry_after"]


# ---------------------------------------------------------------------------
# Handlers for the previously-unregistered deferrable kinds
# ---------------------------------------------------------------------------


def test_every_deferrable_kind_but_retrieval_has_a_handler():
    from agentfox.jobs.queue import DEFERRABLE

    for kind in ("eval.run", "compliance.recompute", "evidence.package", "redteam.sweep"):
        assert kind in DEFERRABLE
    for kind in (
        "eval.run",
        "compliance.recompute",
        "canary.advance",
        "drift.check",
        "redteam.posture",
    ):
        assert kind in jobs_db._HANDLERS
        assert job_handlers.HANDLERS[kind] is jobs_db._HANDLERS[kind]


def test_eval_run_enqueues_and_runs(seeded):
    suite = EvalSuite(key="sched-suite", name="scheduled")
    seeded.add(suite)
    seeded.flush()
    seeded.add(
        EvalCase(
            suite_id=suite.id,
            input_json={"prompt": "What is the refund policy?"},
            expected_json={"goal": "refund policy"},
            context_json={"retrieved": ["Refunds within 30 days."]},
        )
    )
    seeded.flush()
    job = jobs_db.enqueue(
        seeded,
        "eval.run",
        {"suite": "sched-suite", "target": {"agent": "support-triage"}},
        org_id="org_default",
    )
    jobs_db.run_pending(seeded, org_id=job.org_id)
    seeded.refresh(job)
    assert job.status == "done", job.last_error
    run = seeded.get(EvalRun, job.result_json["eval_run_id"])
    assert run is not None


def test_eval_run_with_an_unknown_suite_fails_the_job_not_the_process(session):
    job = jobs_db.enqueue(session, "eval.run", {"suite": "nope"}, org_id="org-1", max_attempts=1)
    jobs_db.run_pending(session, org_id="org-1")
    session.refresh(job)
    assert job.status == "dead"
    assert "unknown eval suite" in job.last_error


def test_compliance_recompute_enqueues_and_runs(seeded):
    from agentfox.prove.compliance.catalog import sync_catalog

    sync_catalog(seeded)
    job = jobs_db.enqueue(seeded, "compliance.recompute", {"window_days": 7}, org_id="org_default")
    jobs_db.run_pending(seeded, org_id=job.org_id)
    seeded.refresh(job)
    assert job.status == "done", job.last_error
    assert job.result_json["computed"] > 0
    assert job.result_json["window_days"] == 7


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def test_default_schedules_are_created_once_and_respect_operator_changes(session):
    created = scheduler.ensure_default_schedules(session)
    assert {s.kind for s in created} == {d.kind for d in scheduler.DEFAULT_SCHEDULES}
    by_kind = {s.kind: s for s in created}
    assert by_kind["redteam.posture"].enabled is False
    assert by_kind["canary.advance"].enabled is True

    by_kind["canary.advance"].enabled = False
    session.flush()
    assert scheduler.ensure_default_schedules(session) == []
    assert session.get(JobSchedule, by_kind["canary.advance"].id).enabled is False


def _test_schedule(session, kind="test.sched", interval=3600):
    jobs_db.register(kind, lambda s, p: {"ran": True})
    row = JobSchedule(kind=kind, interval_seconds=interval, enabled=True, payload_json={"x": 1})
    session.add(row)
    session.flush()
    return row


def test_a_schedule_enqueues_exactly_once_per_due_period(session):
    schedule = _test_schedule(session)

    first = scheduler.enqueue_due(session, NOW)
    assert [j.kind for j in first] == ["test.sched"]
    assert first[0].schedule_id == schedule.id
    assert first[0].payload_json["actor_type"] == "automation"
    assert _aware(schedule.last_enqueued_at) == NOW
    assert _aware(schedule.next_due_at) == NOW + dt.timedelta(hours=1)
    jobs_db.run_pending(session, org_id=first[0].org_id, now=NOW)

    assert scheduler.enqueue_due(session, NOW + dt.timedelta(minutes=30)) == []

    # A cron that is five intervals late still enqueues once, not five times.
    late = NOW + dt.timedelta(hours=5)
    assert len(scheduler.enqueue_due(session, late)) == 1
    assert scheduler.enqueue_due(session, late) == []


def test_a_schedule_does_not_enqueue_while_its_previous_job_is_open(session):
    _test_schedule(session)
    (job,) = scheduler.enqueue_due(session, NOW)
    later = NOW + dt.timedelta(hours=3)
    assert scheduler.enqueue_due(session, later) == [], "previous job still pending"

    job.status = "running"
    job.started_at = later
    session.flush()
    assert scheduler.enqueue_due(session, later) == [], "previous job still running"

    job.status = "done"
    session.flush()
    assert len(scheduler.enqueue_due(session, later)) == 1


def test_disabled_schedules_and_a_disabled_scheduler_enqueue_nothing(session, monkeypatch):
    schedule = _test_schedule(session)
    schedule.enabled = False
    session.flush()
    assert scheduler.enqueue_due(session, NOW) == []

    schedule.enabled = True
    session.flush()
    monkeypatch.setattr(get_settings(), "scheduler_enabled", False)
    assert scheduler.enqueue_due(session, NOW) == []
    assert session.query(Job).count() == 0


def test_schedules_are_per_tenant(session):
    from agentfox.core.tenancy import bind_session

    bind_session(session, "org-a")
    scheduler.ensure_default_schedules(session)
    bind_session(session, "org-b")
    scheduler.ensure_default_schedules(session)
    enqueued = scheduler.enqueue_due(session, NOW)
    assert {j.org_id for j in enqueued} == {"org-b"}
    bind_session(session, "org-a")
    assert {j.org_id for j in scheduler.enqueue_due(session, NOW)} == {"org-a"}


# ---------------------------------------------------------------------------
# Evaluation routes
# ---------------------------------------------------------------------------


def test_adaptive_campaign_over_http_returns_a_posture_headline(client):
    response = client.post(
        "/api/redteam/campaigns",
        json={"agent": "support-triage", "adaptive": True, "budget": 1, "seed": 7},
        headers=as_user("priya@example.com"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["headline"]
    assert body["summary"]["adaptive"]["budget"] == 1
    assert body["summary"]["headline"] == body["headline"]


def test_static_campaign_over_http_is_unchanged(client):
    body = client.post(
        "/api/redteam/campaigns",
        json={"agent": "support-triage"},
        headers=as_user("priya@example.com"),
    ).json()
    assert "adaptive" not in body["summary"]
    assert body["headline"] is None


def _seed_online_scores(agent: str):
    """Online eval scores in the baseline window and a clearly shifted current window."""
    from agentfox.core.db import session_scope

    now = dt.datetime.now(dt.UTC)
    with session_scope() as s:
        for when, scores in (
            (now - dt.timedelta(days=3), [0.9, 0.92, 0.95, 0.91, 0.93, 0.94]),
            (now - dt.timedelta(hours=2), [0.1, 0.15, 0.2, 0.12, 0.11, 0.18]),
        ):
            run = EvalRun(
                suite_id="online", mode="online", target_json={"agent": agent}, created_at=when
            )
            s.add(run)
            s.flush()
            for i, score in enumerate(scores):
                s.add(
                    EvalResult(
                        run_id=run.id, case_id=f"c{i}", scorer_key="groundedness", score=score
                    )
                )


def test_get_drift_writes_nothing(client):
    """Recording is the scheduled drift.check job (test below), not a page view."""
    _seed_online_scores("support-triage")
    from agentfox.core.db import session_scope

    def counts():
        with session_scope() as s:
            return s.query(DriftWindow).count(), s.query(Finding).filter_by(type="drift").count()

    before = counts()
    headers = as_user("priya@example.com")
    for _ in range(3):
        got = client.get("/api/eval/drift?agent=support-triage", headers=headers)
        assert got.status_code == 200
        assert got.json()["drifted"] is True
    assert counts() == before, "viewing drift must not write a window or a finding"


def test_drift_check_job_persists_drift(session):
    _seed_online_scores("support-triage")
    job = jobs_db.enqueue(
        session, "drift.check", {"agents": ["support-triage"]}, org_id="org_default"
    )
    jobs_db.run_pending(session, org_id=job.org_id)
    session.refresh(job)
    assert job.status == "done", job.last_error
    assert job.result_json["windows_recorded"] == 1
    assert job.result_json["drifted"] == ["support-triage"]
    assert session.query(DriftWindow).count() == 1
