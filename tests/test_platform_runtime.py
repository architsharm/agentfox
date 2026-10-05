"""The three platform rows the PRD listed as production blockers.

Loop governance, deferred work, and a persistence layer that refuses to be
misconfigured. Each one closes a Tier-0 gap in the PRD's own register, and each is a
control over the *shape* of a run or a deployment rather than over any single call.
"""

from __future__ import annotations

import pytest

from agentfox.jobs import store as jobs_db
from agentfox.runtime.agent_loop import CONTINUE, ESCALATE, STOP, LoopBudget, Step, govern_loop
from agentfox.core.db import configure_pool
from agentfox.jobs.queue import DEFERRABLE, JobQueue
from agentfox.core.models import Job


def run(tools_and_observations, budget=None):
    return govern_loop(
        [{"tool": t, "arguments": a, "observation": o} for t, a, o in tools_and_observations],
        budget=budget,
    )


# --- Loop governance (PL-4) ------------------------------------------------


def test_an_identical_call_repeated_is_the_agent_asking_again():
    """Whatever it returned the first time is still true. The second call is the agent
    not knowing what to do with the answer."""
    verdict = run([("crm.lookup", {"id": 1}, "x")] * 4)
    assert verdict.decision == STOP
    assert "identical arguments" in verdict.reason


def test_an_alternating_pair_is_caught_where_per_tool_counting_cannot_see_it():
    """A→B→A→B is a loop and neither tool repeats consecutively."""
    verdict = run([(t, {"n": i}, i) for i, t in enumerate(["a", "b", "a", "b", "a", "b"])])
    assert verdict.decision == STOP
    assert verdict.evidence["cycle"] == ["a", "b"]


def test_a_longer_cycle_is_caught_too():
    seq = ["a", "b", "c"] * 3
    verdict = run([(t, {"n": i}, i) for i, t in enumerate(seq)])
    assert verdict.decision == STOP
    assert verdict.evidence["cycle"] == ["a", "b", "c"]


def test_steps_that_produce_nothing_new_are_escalated_with_the_range():
    """ "Budget exhausted" tells an operator nothing. A step range tells them where to
    look."""
    verdict = run([(f"t{i}", {"i": i}, "unchanged") for i in range(7)])
    assert verdict.decision == ESCALATE
    assert verdict.evidence["from_step"] < verdict.evidence["to_step"]


def test_the_step_budget_still_applies():
    verdict = run([(f"t{i}", {"i": i}, i) for i in range(40)], budget=LoopBudget(max_steps=10))
    assert verdict.decision == STOP
    assert "step budget" in verdict.reason


def test_a_run_that_makes_progress_is_left_alone():
    """The false-positive floor. An agent doing eight different useful things is an
    agent working."""
    verdict = run([(f"t{i}", {"i": i}, i) for i in range(8)])
    assert verdict.decision == CONTINUE


def test_the_same_tool_with_different_arguments_is_progress():
    """Paging through results calls one tool repeatedly and is not a loop."""
    verdict = run([("search", {"page": i}, i) for i in range(5)])
    assert verdict.decision == CONTINUE


def test_a_legitimate_repeating_pipeline_is_not_flagged_as_a_cycle():
    """A single tool repeated is caught by the repeat rule; a cycle needs two distinct
    tools, or every batch pipeline would trip it."""
    verdict = run([("step", {"n": i}, i) for i in range(6)], budget=LoopBudget(max_repeats=99))
    assert verdict.decision == CONTINUE


def test_the_verdict_names_the_step_it_stopped_at():
    verdict = run([("crm.lookup", {"id": 1}, "x")] * 4)
    assert verdict.step == 3
    assert Step("crm.lookup", {"id": 1}).call_fingerprint


def test_a_cosmetically_different_observation_still_counts_as_no_progress():
    """Two observations that are the same result in every way that matters — key
    order, float formatting — must fingerprint identically, or a timestamp field
    alone defeats "no new observation" entirely."""
    obs_a = {"status": "pending", "amount": 10.0, "checked_at": "t1"}
    obs_b = {"amount": 10, "status": "pending", "checked_at": "t2"}
    # checked_at differs on purpose: canonicalization does not know it is
    # volatile the way effects.idempotency_key's VOLATILE_ARGS list does. This
    # test is about ordering/float-formatting, not about ignoring named fields.
    obs_a.pop("checked_at")
    obs_b.pop("checked_at")
    verdict = run([(f"t{i}", {"i": i}, obs_a if i % 2 == 0 else obs_b) for i in range(7)])
    assert verdict.decision == ESCALATE


def test_default_budget_has_no_decay():
    """`decay_from_depth=None` (the default) must reproduce the exact pre-decay
    behavior — the false-positive floor from `test_a_run_that_makes_progress_is_left_alone`
    must not start tripping just because this feature exists."""
    verdict = run([(f"t{i}", {"i": i}, i) for i in range(20)])
    assert verdict.decision == CONTINUE


def test_decay_makes_the_same_stall_trip_earlier_late_in_a_long_run():
    """A stall that would be tolerated early in a run (well under the flat
    threshold) is judged more strictly once the run is deep into its budget —
    "a step deep into a long loop is scored more strictly than an early one"."""
    budget = LoopBudget(max_steps=20, max_steps_without_progress=5, decay_from_depth=15)
    # 15 steps of real progress (past the decay point), then a 3-step stall.
    # At step 18: progressed=3 of a 5-step span, decayed threshold = 5*(1-3/5) = 2,
    # so 3 stalled steps trips it. The flat (undecayed) threshold stays 5, so the
    # identical stall alone would not.
    steps = [(f"t{i}", {"i": i}, i) for i in range(15)] + [
        (f"stalled{i}", {"i": i}, "same") for i in range(3)
    ]
    verdict = run(steps, budget=budget)
    assert verdict.decision == ESCALATE
    without_decay = run(steps, budget=LoopBudget(max_steps=20, max_steps_without_progress=5))
    assert without_decay.decision == CONTINUE


# --- Deferred work (PL-5) --------------------------------------------------


def test_work_with_no_handler_is_refused_at_enqueue_not_at_run():
    """Discovering that nothing knows how to package evidence, an hour after the
    request that needed it, is the failure this module exists to avoid."""
    queue = JobQueue()
    with pytest.raises(KeyError, match="no handler"):
        queue.enqueue("evidence.package")


def test_a_job_runs_off_the_request_path():
    queue = JobQueue()
    seen = []
    queue.register("evidence.package", seen.append)
    queue.enqueue("evidence.package", {"trace": "t1"})
    assert seen == [], "nothing runs until a worker asks it to"
    assert queue.run_pending() == 1
    assert seen == [{"trace": "t1"}]


def test_a_failing_job_is_retried_then_dead_lettered_never_discarded():
    """Evidence missing without a record is worse than evidence never collected — the
    gap looks identical to "nothing happened"."""
    queue = JobQueue()
    attempts = []

    def explode(payload):
        attempts.append(payload)
        raise RuntimeError("upstream down")

    queue.register("evidence.package", explode)
    queue.enqueue("evidence.package", {"trace": "t1"}, max_attempts=3)
    queue.run_pending(limit=10)

    assert len(attempts) == 3
    assert queue.stats()["dead"] == 1
    assert queue.dead_letter[0].last_error.startswith("RuntimeError")


def test_dead_lettered_work_can_be_replayed_once_the_cause_is_fixed():
    queue = JobQueue()
    state = {"broken": True}

    def handler(payload):
        if state["broken"]:
            raise RuntimeError("upstream down")

    queue.register("evidence.package", handler)
    queue.enqueue("evidence.package", {}, max_attempts=1)
    queue.run_pending(limit=5)
    assert queue.stats()["dead"] == 1

    state["broken"] = False
    assert queue.retry_dead() == 1
    queue.run_pending(limit=5)
    assert queue.stats() == {**queue.stats(), "dead": 0, "done": 1}


def test_the_deferrable_list_makes_adding_inline_work_a_visible_decision():
    assert "evidence.package" in DEFERRABLE
    assert "compliance.recompute" in DEFERRABLE


def test_a_job_carries_the_tenant_that_created_it():
    queue = JobQueue()
    queue.register("evidence.package", lambda p: None)
    job = queue.enqueue("evidence.package", org_id="org-1")
    assert job.to_json()["org_id"] == "org-1"


# --- Persisted queue (PL-5, jobs_db) ----------------------------------------
#
# jobs.py's JobQueue above is the in-process reference implementation — right
# for `agentfox demo`, the CLI, and the tests above. The two real production
# callers (POST /api/evidence, POST /api/redteam/campaigns) go through
# jobs_db instead, because a Vercel invocation's memory doesn't survive past
# the response — a dead-lettered job living only in a `deque` that's about to
# be garbage-collected isn't "public state", it's a value nobody ever saw.
# These tests exercise the same enqueue/run/retry/dead-letter contract
# against the DB-backed version.


def test_db_queue_refuses_a_kind_with_no_handler(session):
    jobs_db._HANDLERS.pop("test.no_handler", None)
    with pytest.raises(KeyError, match="no handler"):
        jobs_db.enqueue(session, "test.no_handler", org_id="org-1")


def test_db_queue_runs_a_job_and_records_its_result(session):
    jobs_db.register("test.echo", lambda s, p: {"got": p})
    job = jobs_db.enqueue(session, "test.echo", {"trace": "t1"}, org_id="org-1")
    assert job.status == "pending", "nothing runs until a worker asks it to"

    finished = jobs_db.run_pending(session, org_id="org-1")

    assert finished == 1
    session.refresh(job)
    assert job.status == "done"
    assert job.result_json == {"got": {"trace": "t1"}}
    assert job.finished_at is not None


def test_db_queue_retries_then_dead_letters_never_discarding_the_record(session):
    attempts = []

    def explode(s, payload):
        attempts.append(payload)
        raise RuntimeError("upstream down")

    jobs_db.register("test.explode", explode)
    job = jobs_db.enqueue(session, "test.explode", {"trace": "t1"}, org_id="org-1", max_attempts=3)

    # Retries back off (jobs_db.backoff_delay), so each later pass runs an hour on.
    import datetime as dt

    start = dt.datetime.now(dt.UTC)
    for hour in range(3):
        jobs_db.run_pending(session, org_id="org-1", now=start + dt.timedelta(hours=hour))

    assert len(attempts) == 3
    session.refresh(job)
    assert job.status == "dead"
    assert job.last_error.startswith("RuntimeError")
    # Still queryable — the point of persisting it at all.
    assert session.get(Job, job.id) is not None


def test_db_queue_dead_lettered_work_can_be_replayed_once_the_cause_is_fixed(session):
    state = {"broken": True}

    def handler(s, payload):
        if state["broken"]:
            raise RuntimeError("upstream down")
        return {"ok": True}

    jobs_db.register("test.flaky", handler)
    job = jobs_db.enqueue(session, "test.flaky", {}, org_id="org-1", max_attempts=1)
    jobs_db.run_pending(session, org_id="org-1")
    session.refresh(job)
    assert job.status == "dead"

    state["broken"] = False
    revived = jobs_db.retry_dead(session, job.id)
    assert revived is not None
    assert revived.status == "pending"
    assert revived.attempts == 0

    jobs_db.run_pending(session, org_id="org-1")
    session.refresh(job)
    assert job.status == "done"
    assert job.result_json == {"ok": True}


def test_db_queue_retry_dead_is_a_noop_on_a_job_that_is_not_dead(session):
    jobs_db.register("test.noop", lambda s, p: {})
    job = jobs_db.enqueue(session, "test.noop", org_id="org-1")
    assert jobs_db.retry_dead(session, job.id) is None, (
        "job is pending, not dead — nothing to revive"
    )


def test_db_queue_run_pending_with_an_org_id_never_touches_another_tenants_jobs(session):
    jobs_db.register("test.tenant_scoped", lambda s, p: {"ran": True})
    other_org_job = jobs_db.enqueue(session, "test.tenant_scoped", org_id="org-other")

    finished = jobs_db.run_pending(session, org_id="org-mine")

    assert finished == 0
    session.refresh(other_org_job)
    assert other_org_job.status == "pending", (
        "a request in one tenant must never run another tenant's queued work"
    )


def test_db_queue_run_pending_with_no_org_id_is_the_cron_backstop_across_every_tenant(session):
    jobs_db.register("test.cron_scoped", lambda s, p: {"ran": True})
    job_a = jobs_db.enqueue(session, "test.cron_scoped", org_id="org-a")
    job_b = jobs_db.enqueue(session, "test.cron_scoped", org_id="org-b")

    finished = jobs_db.run_pending(session, org_id=None)

    assert finished == 2
    session.refresh(job_a)
    session.refresh(job_b)
    assert job_a.status == "done"
    assert job_b.status == "done"


def test_db_queue_binds_the_jobs_own_tenant_before_running_the_handler(session):
    """A worker processing a job later has no ambient request context — the
    job's own org_id, not whatever was bound (or unbound) when it happened to
    run, has to be what a row the handler creates gets stamped with."""
    seen_org = {}

    def handler(s, payload):
        from agentfox.core.tenancy import session_org

        seen_org["value"] = session_org(s)
        return {}

    jobs_db.register("test.tenant_binding", handler)
    jobs_db.enqueue(session, "test.tenant_binding", org_id="org-specific")
    jobs_db.run_pending(session, org_id="org-specific")

    assert seen_org["value"] == "org-specific"


# --- Persistence (PL-6) ----------------------------------------------------


def test_sqlite_is_refused_for_a_multi_worker_deployment():
    """The second worker does not fail loudly. It takes a write lock and the first one
    waits, which surfaces as the governance layer being intermittently slow — and a
    layer that is intermittently slow gets its timeout raised until it fails open.
    """
    with pytest.raises(RuntimeError, match="single-writer"):
        configure_pool("sqlite:///x.db", workers=4)


def test_sqlite_remains_the_single_process_default():
    assert configure_pool("sqlite:///x.db")["connect_args"]["check_same_thread"] is False


def test_postgres_is_pooled_and_pre_pings():
    """The connection this layer needs is the one it needs during an incident, and a
    stale handle then costs a request that mattered."""
    pool = configure_pool("postgresql://localhost/agentfox", workers=4)
    assert pool["pool_pre_ping"] is True
    assert pool["pool_size"] >= 5
