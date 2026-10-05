"""Label integrity — the human verdicts the improvement loop tunes detectors from.

Precision reports, threshold recommendations and every loop proposal built on them
trust these rows. So a label must have a real, authenticated author; one person gets
one vote per decision; every label is on the audit chain; and the people whose job is
to observe the controls cannot shape them. Also pins three tuning bugs that corrupted
the labels or the suppressions built from them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.core.models import (
    Agent,
    AuditEntry,
    Decision,
    DetectionFinding,
    DetectorRun,
    GuardrailFeedback,
    RiskAssessment,
)
from agentfox.detection.base import Detection, DetectorResult
from agentfox.detection.pipeline import PipelineResult
from agentfox.detection.tuning import (
    apply_suppression,
    explain,
    record_feedback,
    sample_hash,
)

from .conftest import INDIRECT_INJECTION, PII_TEXT, as_user


@pytest.fixture
def decision_id(client) -> str:
    client.post(
        "/api/policies/baseline/mode",
        json={"mode": "enforce"},
        headers=as_user("admin@example.com"),
    )
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": [
                {"role": "user", "content": "Summarise."},
                {"role": "tool", "content": INDIRECT_INJECTION},
            ],
        },
        headers={"X-Nometria-Agent": "support-triage"},
    )
    assert response.status_code == 403, response.text
    return response.json()["error"]["decision_id"]


def _file(client, decision_id, user, **body):
    return client.post(
        "/api/guardrails/feedback",
        json={"decision_id": decision_id, "label": "false_positive", **body},
        headers=as_user(user),
    )


def _audit(action: str) -> list[AuditEntry]:
    from agentfox.core.db import session_scope

    with session_scope() as s:
        rows = list(s.scalars(select(AuditEntry).where(AuditEntry.action == action)))
        s.expunge_all()
        return rows


def _feedback_rows() -> list[GuardrailFeedback]:
    from agentfox.core.db import session_scope

    with session_scope() as s:
        rows = list(s.scalars(select(GuardrailFeedback)))
        s.expunge_all()
        return rows


# ---------------------------------------------------------------------------
# Feedback over the API
# ---------------------------------------------------------------------------


def test_every_label_is_on_the_audit_chain_under_its_author(client, decision_id):
    filed = _file(client, decision_id, "priya@example.com", note="benign quote")
    assert filed.status_code == 201, filed.text
    entries = _audit("guardrail.feedback.recorded")
    assert len(entries) == 1
    assert entries[0].actor_type == "user"
    assert entries[0].actor_id == "priya@example.com"
    assert entries[0].subject_id == decision_id
    assert entries[0].payload_json["after"]["label"] == "false_positive"


def test_the_actor_is_the_authenticated_user_never_the_body(client, decision_id):
    filed = _file(client, decision_id, "priya@example.com", actor="marcus@example.com")
    assert filed.status_code == 201, filed.text
    assert filed.json()["actor"] == "priya@example.com"
    assert [row.actor for row in _feedback_rows()] == ["priya@example.com"]


def test_one_label_per_decision_per_person_and_a_change_is_audited(client, decision_id):
    first = _file(client, decision_id, "priya@example.com")
    second = client.post(
        "/api/guardrails/feedback",
        json={"decision_id": decision_id, "label": "true_positive", "note": "on reflection"},
        headers=as_user("priya@example.com"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"], "a second label updates, not adds"
    rows = _feedback_rows()
    assert len(rows) == 1 and rows[0].label == "true_positive"

    changes = _audit("guardrail.feedback.changed")
    assert len(changes) == 1
    assert changes[0].actor_id == "priya@example.com"
    assert changes[0].payload_json["before"]["label"] == "false_positive"
    assert changes[0].payload_json["after"]["label"] == "true_positive"

    # Filing the identical label again changes nothing and records nothing new.
    client.post(
        "/api/guardrails/feedback",
        json={"decision_id": decision_id, "label": "true_positive", "note": "on reflection"},
        headers=as_user("priya@example.com"),
    )
    assert len(_audit("guardrail.feedback.changed")) == 1

    # A different person is a different vote.
    _file(client, decision_id, "marcus@example.com")
    assert len(_feedback_rows()) == 2


def test_an_auditor_cannot_label(client, decision_id):
    refused = _file(client, decision_id, "aisha@example.com")
    assert refused.status_code == 403
    assert _feedback_rows() == []
    assert _audit("guardrail.feedback.recorded") == []


def test_a_label_backing_a_suppression_cannot_be_flipped_under_it(client, decision_id):
    filed = _file(client, decision_id, "marcus@example.com")
    created = client.post(
        "/api/guardrails/suppressions",
        json={"feedback_id": filed.json()["id"], "ttl_days": 7},
        headers=as_user("marcus@example.com"),
    )
    assert created.status_code == 201, created.text
    flipped = client.post(
        "/api/guardrails/feedback",
        json={"decision_id": decision_id, "label": "true_positive"},
        headers=as_user("marcus@example.com"),
    )
    assert flipped.status_code == 400
    assert "suppression" in flipped.json()["detail"]


def test_record_feedback_requires_an_actor(seeded, enforcer):
    agent = seeded.scalar(select(Agent).where(Agent.slug == "support-triage"))
    result = enforcer.evaluate(agent=agent, identity=None, content=PII_TEXT, surface="output")
    with pytest.raises(ValueError, match="identity"):
        record_feedback(seeded, decision_id=result.decision_id, label="false_positive")


# ---------------------------------------------------------------------------
# Tuning bugs
# ---------------------------------------------------------------------------


def test_the_dispute_payload_names_the_decisive_detector_not_the_first():
    """Bug: the dispute named ``matches[0].detector`` — whichever detector ran first —
    so a one-click false-positive report was filed against a detector that had no
    bearing on the verdict."""

    class FakeResult:
        verdict = "block"
        effective_verdict = "block"
        mode = "enforce"
        trace_id = "trc_1"
        decision_id = "dec_1"
        rules_fired = [
            {"rule_id": "pii.block", "effect": "block", "entities": ["PII_SSN"], "reason": "pii"}
        ]

    pipeline = PipelineResult(
        results=[
            DetectorResult(
                "safety.lexicon",
                "1",
                score=0.99,
                detections=[Detection("SAFETY_TOXIC", 0.99, 0, 4)],
            ),
            DetectorResult(
                "pii.native", "1", score=0.6, detections=[Detection("PII_SSN", 0.6, 10, 21)]
            ),
        ]
    )
    explanation = explain(FakeResult(), pipeline, content="x" * 40, surface="output")
    payload = explanation.dispute["payload"]
    assert payload["detector_key"] == "pii.native"
    assert payload["entity_type"] == "PII_SSN"


def test_a_dispute_with_no_decisive_match_names_no_detector():
    class FakeResult:
        verdict = "escalate"
        effective_verdict = "escalate"
        mode = "enforce"
        trace_id = None
        decision_id = None
        rules_fired = [{"rule_id": "tool.approval", "effect": "escalate", "reason": "x"}]

    explanation = explain(FakeResult(), PipelineResult(), surface="tool_args")
    assert explanation.dispute["payload"]["detector_key"] is None


def _two_detector_decision(seeded) -> tuple[Decision, str]:
    agent = seeded.scalar(select(Agent).where(Agent.slug == "support-triage"))
    trace_id = "trc_exact_bug"
    other_run = DetectorRun(trace_id=trace_id, detector_key="secrets.native", score=0.99)
    pii_run = DetectorRun(trace_id=trace_id, detector_key="pii.native", score=0.8)
    # A different decision on the same trace, whose detection lands first.
    unrelated_run = DetectorRun(trace_id=trace_id, detector_key="pii.native", score=0.95)
    seeded.add_all([other_run, pii_run, unrelated_run])
    seeded.flush()
    seeded.add_all(
        [
            DetectionFinding(
                detector_run_id=other_run.id,
                trace_id=trace_id,
                entity_type="SECRET_KEY",
                score=0.99,
                sample="sk-live-something",
            ),
            DetectionFinding(
                detector_run_id=unrelated_run.id,
                trace_id=trace_id,
                entity_type="PII_EMAIL",
                score=0.95,
                sample="someone.else@example.com",
            ),
            DetectionFinding(
                detector_run_id=pii_run.id,
                trace_id=trace_id,
                entity_type="PII_EMAIL",
                score=0.8,
                sample="jane.doe@example.com",
            ),
        ]
    )
    decision = Decision(
        trace_id=trace_id,
        agent_id=agent.id,
        verdict="block",
        detector_run_ids=[other_run.id, pii_run.id],
    )
    seeded.add(decision)
    seeded.flush()
    return decision, "jane.doe@example.com"


def test_an_exact_suppression_hashes_the_labelled_detection(seeded):
    """Bug: the sample was looked up by trace alone, unordered, so the "exact"
    suppression could hash another detector's match or another decision's."""
    decision, labelled_sample = _two_detector_decision(seeded)
    feedback = record_feedback(
        seeded,
        decision_id=decision.id,
        label="false_positive",
        detector_key="pii.native",
        entity_type="PII_EMAIL",
        actor="priya@example.com",
    )
    suppression = apply_suppression(
        seeded, feedback_id=feedback.id, exact=True, actor="marcus@example.com", reason="fixture"
    )
    assert suppression.sample_hash == sample_hash(labelled_sample)


def test_an_exact_suppression_without_a_sample_is_refused_not_widened(seeded):
    agent = seeded.scalar(select(Agent).where(Agent.slug == "support-triage"))
    decision = Decision(trace_id="trc_empty", agent_id=agent.id, verdict="block")
    seeded.add(decision)
    seeded.flush()
    feedback = record_feedback(
        seeded,
        decision_id=decision.id,
        label="false_positive",
        detector_key="pii.native",
        actor="priya@example.com",
    )
    with pytest.raises(ValueError, match="exact"):
        apply_suppression(seeded, feedback_id=feedback.id, exact=True, actor="marcus@example.com")


@pytest.mark.parametrize("scope", ["Agent", "globl", "", "team"])
def test_an_unknown_scope_is_refused_rather_than_going_global(seeded, scope):
    """Bug: any scope other than exactly "agent" silently created a global
    suppression — a typo silenced a detector for every agent."""
    decision, _ = _two_detector_decision(seeded)
    feedback = record_feedback(
        seeded,
        decision_id=decision.id,
        label="false_positive",
        detector_key="pii.native",
        actor="priya@example.com",
    )
    with pytest.raises(ValueError, match="scope"):
        apply_suppression(seeded, feedback_id=feedback.id, scope=scope, actor="marcus@example.com")


def test_global_scope_must_be_asked_for_by_name(seeded):
    decision, _ = _two_detector_decision(seeded)
    feedback = record_feedback(
        seeded,
        decision_id=decision.id,
        label="false_positive",
        detector_key="pii.native",
        actor="priya@example.com",
    )
    suppression = apply_suppression(
        seeded, feedback_id=feedback.id, scope="global", actor="marcus@example.com"
    )
    assert suppression.agent_id is None


def test_an_unknown_scope_is_a_400_over_the_api(client, decision_id):
    filed = _file(client, decision_id, "marcus@example.com")
    response = client.post(
        "/api/guardrails/suppressions",
        json={"feedback_id": filed.json()["id"], "scope": "everyone"},
        headers=as_user("marcus@example.com"),
    )
    assert response.status_code == 400
    assert "scope" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Risk assessment sign-off
# ---------------------------------------------------------------------------


def _assess(client, user, **body):
    return client.post("/api/risk/assessments/support-triage", json=body, headers=as_user(user))


def test_sign_off_is_the_authenticated_caller(client):
    response = _assess(client, "dana@example.com", sign_off=True)
    assert response.status_code == 201, response.text
    assert response.json()["signed_off_by"] == "dana@example.com"
    entry = _audit("risk.assessed")[-1]
    assert entry.actor_id == "dana@example.com"
    assert entry.payload_json["signed_off_by"] == "dana@example.com"


def test_signing_off_in_someone_elses_name_is_refused(client):
    from agentfox.core.db import session_scope

    def count() -> int:
        with session_scope() as s:
            return len(list(s.scalars(select(RiskAssessment))))

    before = count()
    response = _assess(client, "dana@example.com", signed_off_by="marcus@example.com")
    assert response.status_code == 403
    assert count() == before, "a refused sign-off must not leave an assessment behind"


def test_an_assessment_without_sign_off_is_unsigned(client):
    response = _assess(client, "dana@example.com")
    assert response.status_code == 201, response.text
    assert response.json()["signed_off_by"] is None
    # An old client naming itself still works.
    legacy = _assess(client, "dana@example.com", signed_off_by="dana@example.com")
    assert legacy.json()["signed_off_by"] == "dana@example.com"
