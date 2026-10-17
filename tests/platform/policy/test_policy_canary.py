"""P12-6 — agent canary rollout by version, with health gates and automated rollback."""

from __future__ import annotations

import pytest

from agentfox.core.models import Decision, Policy, PolicyBinding, PolicyVersion
from agentfox.platform.policy import (
    CanaryError,
    PolicyDocument,
    active_canary,
    active_policies,
    canary_health,
    canary_rollout,
    pick_version_id,
    rollback_canary,
    save_policy,
    start_canary,
)

BASE = """
key: canary-test
mode: enforce
default_effect: allow
rules:
  - id: injection.block
    when: {detection: {entity_prefix: INJECTION, min_score: 0.8}}
    effect: block
    controls: [NOM-RTG-01]
"""

TIGHTER = """
key: canary-test
mode: enforce
default_effect: allow
rules:
  - id: injection.block
    when: {detection: {entity_prefix: INJECTION, min_score: 0.8}}
    effect: block
    controls: [NOM-RTG-01]
  - id: pii.block
    when: {detection: {entity_prefix: PII, min_score: 0.5}}
    effect: block
    controls: [NOM-RTG-02]
"""


def _make_two_versions(session):
    """Stable v1 bound, candidate v2 saved but not yet promoted."""
    save_policy(session, PolicyDocument.from_yaml(BASE), bind_mode="enforce")
    save_policy(session, PolicyDocument.from_yaml(TIGHTER), bind_mode="enforce")
    policy = session.query(Policy).filter_by(key="canary-test").one()
    versions = {
        v.version: v for v in session.query(PolicyVersion).filter_by(policy_id=policy.id).all()
    }
    return policy, versions[1], versions[2]


def test_start_canary_defaults_to_latest_as_candidate(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", started_by="alice@example.com")
    assert canary.stable_version_id == v1.id
    assert canary.candidate_version_id == v2.id
    assert canary.percent == 10  # first step of the default ladder
    assert canary.status == "rolling"
    assert canary.steps[-1] == 100


def test_cannot_start_a_second_canary_while_one_is_rolling(session):
    _make_two_versions(session)
    start_canary(session, "canary-test")
    with pytest.raises(CanaryError, match="already has a canary rolling"):
        start_canary(session, "canary-test")


def test_can_canary_an_older_version_as_a_gradual_rollback(session):
    """Candidate need not be newer than stable — canarying v1 against a live v2
    is exactly "roll back gradually instead of all at once," and the health gate
    protects it the same way a forward rollout is protected."""
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", candidate_version=1)
    assert canary.stable_version_id == v2.id
    assert canary.candidate_version_id == v1.id


def test_unknown_policy_raises(session):
    with pytest.raises(CanaryError, match="unknown policy"):
        start_canary(session, "does-not-exist")


def test_pick_version_id_respects_percent_at_the_extremes(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", steps=[0, 100])
    canary.percent = 0
    assert pick_version_id(canary) == canary.stable_version_id
    canary.percent = 100
    assert pick_version_id(canary) == canary.candidate_version_id


def test_pick_version_id_is_roughly_proportional(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", steps=[30, 100])
    picks = [pick_version_id(canary) for _ in range(2000)]
    candidate_share = sum(1 for p in picks if p == canary.candidate_version_id) / len(picks)
    assert 0.22 < candidate_share < 0.38  # ~30% with sampling slack


def test_active_policies_splits_traffic_between_stable_and_candidate(session):
    policy, v1, v2 = _make_two_versions(session)
    start_canary(session, "canary-test", steps=[50, 100])
    seen_versions = set()
    for _ in range(200):
        bound = active_policies(session, agent_slug="any-agent")
        seen_versions.update(version.id for _doc, version, _b in bound)
    assert seen_versions == {v1.id, v2.id}


def test_active_policies_ignores_a_canary_once_the_binding_moved_on(session):
    """If someone hand-edits the policy while a canary is running, the canary must
    not silently keep splitting traffic against a binding it no longer owns."""
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", steps=[100])
    # A third version, bound directly — bypasses the canary machinery entirely.
    doc3 = PolicyDocument.from_yaml(BASE)
    doc3.name = "manually rebound"
    save_policy(session, doc3, bind_mode="enforce")
    bound = active_policies(session, agent_slug="any-agent")
    version_ids = {version.id for _doc, version, _b in bound}
    assert canary.candidate_version_id not in version_ids


def _record_decisions(session, version_id: str, *, total: int, blocked: int):
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


def test_canary_rollout_holds_when_sample_too_small(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", min_sample=20)
    _record_decisions(session, v1.id, total=5, blocked=0)
    _record_decisions(session, v2.id, total=5, blocked=0)
    result = canary_rollout(session, canary.id)
    assert result.status == "rolling"
    assert result.step_index == 0  # unchanged — not enough traffic yet


def test_canary_rollout_advances_when_healthy(session):
    policy, v1, v2 = _make_two_versions(session)
    # No dwell: this test is about the health decision, not the rate limit on advancing
    # (settings default a dwell time; see tests/platform/policy/test_canary_two_way_gate.py).
    canary = start_canary(
        session, "canary-test", steps=[10, 50, 100], min_sample=20, min_dwell_seconds=0
    )
    _record_decisions(session, v1.id, total=100, blocked=5)  # 5% stable
    _record_decisions(session, v2.id, total=25, blocked=1)  # 4% candidate — healthy
    result = canary_rollout(session, canary.id)
    assert result.status == "rolling"
    assert result.step_index == 1
    assert result.percent == 50


def test_canary_rollout_completes_and_promotes_candidate_on_last_step(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", steps=[100], min_sample=5, min_dwell_seconds=0)
    _record_decisions(session, v1.id, total=10, blocked=1)
    _record_decisions(session, v2.id, total=10, blocked=1)
    result = canary_rollout(session, canary.id)
    assert result.status == "completed"
    assert result.percent == 100
    # The binding now points at the candidate — it has become the new stable version.
    binding = (
        session.query(PolicyBinding)
        .filter_by(policy_version_id=v2.id, effective_to=None)
        .one_or_none()
    )
    assert binding is not None


def test_canary_rollout_auto_rolls_back_an_unhealthy_candidate(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(
        session, "canary-test", steps=[10, 100], min_sample=10, max_block_rate_delta=0.15
    )
    _record_decisions(session, v1.id, total=100, blocked=5)  # 5% stable
    _record_decisions(session, v2.id, total=25, blocked=15)  # 60% candidate — very unhealthy
    result = canary_rollout(session, canary.id)
    assert result.status == "rolled_back"
    assert result.percent == 0
    assert "block rate" in result.rollback_reason
    # The binding is restored to the stable version.
    binding = (
        session.query(PolicyBinding)
        .filter_by(policy_version_id=v1.id, effective_to=None)
        .one_or_none()
    )
    assert binding is not None
    assert active_canary(session, policy.id) is None


def test_manual_rollback_stops_traffic_split_immediately(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", steps=[100])
    result = rollback_canary(session, canary.id, reason="manual rollback by bob@example.com")
    assert result.status == "rolled_back"
    assert result.rollback_reason == "manual rollback by bob@example.com"
    bound = active_policies(session, agent_slug="any-agent")
    version_ids = {version.id for _doc, version, _b in bound}
    assert version_ids == {v1.id}


def test_rollback_is_idempotent_once_already_settled(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test", steps=[100])
    rollback_canary(session, canary.id)
    again = rollback_canary(session, canary.id)  # already rolled back — no-op, not an error
    assert again.status == "rolled_back"


def test_canary_health_reports_none_rate_with_no_decisions(session):
    policy, v1, v2 = _make_two_versions(session)
    canary = start_canary(session, "canary-test")
    health = canary_health(session, canary)
    assert health["stable"]["block_rate"] is None
    assert health["candidate"]["block_rate"] is None
    assert health["ready"] is False
