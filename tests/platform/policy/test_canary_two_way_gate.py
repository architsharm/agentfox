"""The canary gate looks both ways, and a canary cannot ramp faster than its dwell time.

Before: a candidate that blocked *less* than stable was read as healthy and advanced,
so a quietly loosened control shipped to 100%; and repeated calls ramped a canary to
100% as soon as both cohorts reached `min_sample`.
"""

from __future__ import annotations

import datetime as dt

from agentfox.core.config import get_settings
from agentfox.core.models import (
    AuditEntry,
    Decision,
    JobSchedule,
    Policy,
    PolicyBinding,
    PolicyVersion,
)
from agentfox.platform.jobs import scheduler
from agentfox.platform.jobs import store as jobs_db
from agentfox.platform.policy import PolicyDocument, save_policy
from agentfox.platform.policy.canary import canary_rollout, evaluate_gate, start_canary
from tests.conftest import as_user

BASE = """
key: gate-test
mode: enforce
default_effect: allow
rules:
  - id: injection.block
    when: {detection: {entity_prefix: INJECTION, min_score: 0.8}}
    effect: block
"""

LOOSER = """
key: gate-test
mode: enforce
default_effect: allow
rules: []
"""


def _versions(session):
    save_policy(session, PolicyDocument.from_yaml(BASE), bind_mode="enforce")
    save_policy(session, PolicyDocument.from_yaml(LOOSER), bind_mode="enforce")
    policy = session.query(Policy).filter_by(key="gate-test").one()
    versions = {v.version: v for v in session.query(PolicyVersion).filter_by(policy_id=policy.id)}
    return versions[1], versions[2]


def _decisions(session, version_id, *, total, blocked):
    for i in range(total):
        session.add(
            Decision(
                agent_id=None,
                verdict="block" if i < blocked else "allow",
                policy_version_id=version_id,
                policy_version_ids=[version_id],
                mode="enforce",
            )
        )
    session.flush()


def _aware(value):
    return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value


def test_a_candidate_that_blocks_less_is_rolled_back_as_a_loosening(session):
    v1, v2 = _versions(session)
    canary = start_canary(
        session, "gate-test", min_sample=10, max_block_rate_drop=0.15, min_dwell_seconds=0
    )
    _decisions(session, v1.id, total=100, blocked=40)  # stable blocks 40%
    _decisions(session, v2.id, total=50, blocked=5)  # candidate blocks 10%
    result = canary_rollout(session, canary.id)
    assert result.status == "rolled_back"
    assert result.percent == 0
    assert "LESS" in result.rollback_reason
    assert "loosen" in result.rollback_reason
    bound = (
        session.query(PolicyBinding)
        .filter_by(policy_version_id=v1.id, effective_to=None)
        .one_or_none()
    )
    assert bound is not None, "binding restored to stable"


def test_a_candidate_that_blocks_more_is_still_rolled_back(session):
    v1, v2 = _versions(session)
    canary = start_canary(
        session, "gate-test", min_sample=10, max_block_rate_delta=0.15, min_dwell_seconds=0
    )
    _decisions(session, v1.id, total=100, blocked=5)
    _decisions(session, v2.id, total=50, blocked=30)
    result = canary_rollout(session, canary.id)
    assert result.status == "rolled_back"
    assert "MORE" in result.rollback_reason


def test_a_small_drop_within_the_gate_is_not_a_rollback(session):
    v1, v2 = _versions(session)
    canary = start_canary(
        session,
        "gate-test",
        steps=[10, 100],
        min_sample=10,
        max_block_rate_drop=0.15,
        min_dwell_seconds=0,
    )
    _decisions(session, v1.id, total=100, blocked=20)
    _decisions(session, v2.id, total=50, blocked=6)  # 12% vs 20%: an 8-point drop
    result = canary_rollout(session, canary.id)
    assert result.status == "rolling"
    assert result.step_index == 1 and result.percent == 100


def test_holds_inside_dwell_time_and_advances_after_it(session):
    v1, v2 = _versions(session)
    canary = start_canary(
        session, "gate-test", steps=[10, 50, 100], min_sample=10, min_dwell_seconds=3600
    )
    started = _aware(canary.last_advanced_at)
    assert started is not None, "the first step's start is recorded"
    _decisions(session, v1.id, total=50, blocked=5)
    _decisions(session, v2.id, total=50, blocked=5)

    for minutes in (0, 10, 59):
        held = canary_rollout(session, canary.id, now=started + dt.timedelta(minutes=minutes))
        assert held.step_index == 0 and held.percent == 10
    gate = evaluate_gate(session, canary, now=started + dt.timedelta(minutes=30))
    assert gate.action == "hold" and "dwell" in gate.reason

    after = started + dt.timedelta(minutes=61)
    advanced = canary_rollout(session, canary.id, now=after)
    assert advanced.step_index == 1 and advanced.percent == 50
    assert _aware(advanced.last_advanced_at) == after

    # The dwell clock restarts at the new step: an immediate second call holds.
    again = canary_rollout(session, canary.id, now=after + dt.timedelta(seconds=5))
    assert again.percent == 50


def test_dwell_time_never_delays_a_rollback(session):
    v1, v2 = _versions(session)
    canary = start_canary(session, "gate-test", min_sample=10, min_dwell_seconds=86400)
    _decisions(session, v1.id, total=50, blocked=25)
    _decisions(session, v2.id, total=50, blocked=0)
    result = canary_rollout(session, canary.id)
    assert result.status == "rolled_back"
    assert "LESS" in result.rollback_reason


def test_gate_thresholds_default_from_settings(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "canary_max_block_rate_drop", 0.05)
    monkeypatch.setattr(get_settings(), "canary_min_dwell_seconds", 1234)
    _versions(session)
    canary = start_canary(session, "gate-test")
    assert canary.max_block_rate_drop == 0.05
    assert canary.min_dwell_seconds == 1234


def test_start_route_accepts_and_defaults_the_new_gate_fields(client):
    headers = as_user("marcus@example.com")
    body = "key: gate-api\nmode: enforce\ndefault_effect: allow\nrules: []\n"
    client.post("/api/policies", json={"body": body}, headers=headers)
    client.post(
        "/api/policies",
        json={"body": "key: gate-api\nmode: enforce\ndefault_effect: allow\nname: v2\nrules: []\n"},
        headers=headers,
    )
    started = client.post(
        "/api/policies/gate-api/canary/start",
        json={"max_block_rate_drop": 0.07, "min_dwell_seconds": 600},
        headers=headers,
    )
    assert started.status_code == 201, started.text
    data = started.json()
    assert data["max_block_rate_drop"] == 0.07
    assert data["min_dwell_seconds"] == 600
    assert data["last_advanced_at"]
    assert data["gate"]["action"] == "hold"

    client.post("/api/policies/gate-api/canary/rollback", headers=headers)
    defaulted = client.post("/api/policies/gate-api/canary/start", json={}, headers=headers).json()
    assert defaulted["max_block_rate_drop"] == get_settings().canary_max_block_rate_drop
    assert defaulted["min_dwell_seconds"] == get_settings().canary_min_dwell_seconds

    bad = client.post(
        "/api/policies/gate-api/canary/start", json={"min_dwell_seconds": -1}, headers=headers
    )
    assert bad.status_code == 422


def test_scheduled_canary_advance_moves_rolling_canaries_through_the_gate(session):
    v1, v2 = _versions(session)
    canary = start_canary(
        session, "gate-test", steps=[10, 50, 100], min_sample=10, min_dwell_seconds=3600
    )
    canary.last_advanced_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    session.flush()
    _decisions(session, v1.id, total=50, blocked=5)
    _decisions(session, v2.id, total=50, blocked=5)

    scheduler.ensure_default_schedules(session)
    enqueued = [j for j in scheduler.enqueue_due(session) if j.kind == "canary.advance"]
    assert len(enqueued) == 1
    schedule = session.get(JobSchedule, enqueued[0].schedule_id)
    assert schedule.kind == "canary.advance"

    jobs_db.run_pending(session, org_id=enqueued[0].org_id)
    job = enqueued[0]
    session.refresh(job)
    assert job.status == "done", job.last_error
    (outcome,) = job.result_json["canaries"]
    assert outcome["action"] == "advance"
    session.refresh(canary)
    assert canary.percent == 50

    entry = session.query(AuditEntry).filter_by(action="policy.canary_advanced").one()
    assert entry.actor_type == "automation", "an automated advance is never recorded as a person"
    assert entry.actor_id == get_settings().improvement_actor_id

    # Next scheduled run inside the dwell window holds.
    job2 = jobs_db.enqueue(session, "canary.advance", {}, org_id=job.org_id)
    jobs_db.run_pending(session, org_id=job.org_id)
    session.refresh(job2)
    assert job2.result_json["canaries"][0]["action"] == "hold"
    session.refresh(canary)
    assert canary.percent == 50


def test_scheduled_canary_advance_rolls_back_a_loosening(session):
    v1, v2 = _versions(session)
    canary = start_canary(session, "gate-test", min_sample=10, min_dwell_seconds=3600)
    _decisions(session, v1.id, total=50, blocked=25)
    _decisions(session, v2.id, total=50, blocked=2)
    job = jobs_db.enqueue(session, "canary.advance", {}, org_id="org_default")
    jobs_db.run_pending(session, org_id=job.org_id)
    session.refresh(job)
    (outcome,) = job.result_json["canaries"]
    assert outcome["action"] == "rollback"
    assert outcome["status"] == "rolled_back"
    assert "LESS" in outcome["reason"]
    session.refresh(canary)
    assert canary.status == "rolled_back"
