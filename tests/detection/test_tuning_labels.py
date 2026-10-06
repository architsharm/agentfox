"""Regressions for guardrail tuning text and labels (#36).

- a feedback label stored the detector run's max score, not the labelled entity's;
- the injection remedy said "untrusted content" for the user's own message.
"""

from __future__ import annotations

from agentfox.core.models import Decision, DetectionFinding, DetectorRun
from agentfox.detection.tuning import _remedy_for, explain_recorded, record_feedback


def test_a_label_on_one_entity_stores_that_entitys_score(seeded):
    run = DetectorRun(detector_key="presidio", surface="output", score=0.95)
    seeded.add(run)
    seeded.flush()
    seeded.add_all(
        [
            DetectionFinding(detector_run_id=run.id, entity_type="PII.SSN", score=0.95),
            DetectionFinding(detector_run_id=run.id, entity_type="PII.EMAIL", score=0.55),
        ]
    )
    decision = Decision(surface="output", verdict="block", detector_run_ids=[run.id])
    seeded.add(decision)
    seeded.flush()

    labelled = record_feedback(
        seeded,
        decision_id=decision.id,
        label="false_positive",
        entity_type="PII.EMAIL",
        actor="dev@example.com",
    )
    assert labelled.score == 0.55
    assert labelled.detector_key == "presidio"

    # With no entity named, the label is about the decisive (highest) match.
    unnamed = record_feedback(
        seeded, decision_id=decision.id, label="true_positive", actor="ops@example.com"
    )
    assert unnamed.entity_type == "PII.SSN"
    assert unnamed.score == 0.95


def test_injection_remedy_depends_on_where_the_instruction_came_from():
    on_input = _remedy_for(["INJECTION.DIRECT"], "input")
    in_document = _remedy_for(["INJECTION.INDIRECT"], "retrieval")
    assert "untrusted content" not in on_input
    assert "user's own message" in on_input
    assert "untrusted content" in in_document


def test_recorded_explanation_uses_the_input_remedy_for_user_input():
    explained = explain_recorded(
        {
            "surface": "input",
            "verdict": "block",
            "rules_fired": [
                {"rule_id": "injection.block", "verdict": "block", "entity_types": ["INJECTION"]}
            ],
        },
        [
            {
                "detector_key": "heuristic_injection",
                "findings": [{"entity_type": "INJECTION.DIRECT", "score": 0.9}],
            }
        ],
    )
    assert "untrusted content" not in explained["remedy"]
