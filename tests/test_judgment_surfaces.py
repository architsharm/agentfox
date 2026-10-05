"""The second and third judgment surfaces: answerability and PII presence.

Both are riskier than injection. Answerability sits in a file that says, on
purpose, that it is all deterministic. PII judgment asks a third party about
the customer's own data. The tests here are mostly about the limits, not the
gains.
"""

from __future__ import annotations

import pytest

from agentfox.grounding.answerability import UNKNOWABLE, UNSUPPORTED_TYPE, AnswerabilityVerdict
from agentfox.core.config import get_settings
from agentfox.detection.base import DetectionContext
from agentfox.detection.detectors.judgment import PiiJudgmentDetector
from agentfox.detection.judgment import JevAnswer, JevClient, JevResult, JudgmentGateway
from agentfox.detection.judgment.answerability import augment
from agentfox.detection.judgment.egress import EgressRefused


class FakeGateway(JudgmentGateway):
    def __init__(self, scores: dict[str, float] | None = None, refuse: str = "") -> None:
        super().__init__(JevClient(api_key="test"), backend="remote")
        self._scores = scores or {}
        self._refuse = refuse

    def ask(self, state, questions):  # type: ignore[override]
        if self._refuse:
            raise EgressRefused(self._refuse)
        return JevResult(
            answers={
                qid: JevAnswer(qid, "noul", self._scores.get(qid, 0.0), 1.0) for qid in questions
            }
        )


@pytest.fixture
def judgment_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "judgment_tiers", ["deterministic", "jev"])
    monkeypatch.setattr(s, "allow_egress", True)


ANSWERABLE = AnswerabilityVerdict(answerable=True, mode="enforce")


# --- answerability: may only ever ADD an abstention ----------------------
def test_it_adds_an_abstention_the_regexes_missed(judgment_on) -> None:
    out = augment(ANSWERABLE, "Are Moms better than Dads?", gateway=FakeGateway({"contested": 0.9}))
    assert out.answerable is False
    assert out.abstention_kind == UNSUPPORTED_TYPE
    assert out.response  # says what is missing, not just "no"


def test_a_not_yet_determined_question_uses_the_existing_kind(judgment_on) -> None:
    out = augment(
        ANSWERABLE, "Who wins in 2032?", gateway=FakeGateway({"not_yet_determined": 0.95})
    )
    assert out.abstention_kind == UNKNOWABLE


def test_it_can_never_turn_an_abstention_back_into_an_answer(judgment_on) -> None:
    """The deterministic layer is precise; a confident model must not overrule it."""
    refused = AnswerabilityVerdict(answerable=False, abstention_kind=UNKNOWABLE, mode="enforce")
    out = augment(refused, "anything", gateway=FakeGateway({"contested": 0.0}))
    assert out.answerable is False
    assert out is refused  # untouched, and no call made


def test_a_confident_answerable_judgment_changes_nothing(judgment_on) -> None:
    out = augment(
        ANSWERABLE, "What is our refund window?", gateway=FakeGateway({"contested": 0.01})
    )
    assert out.answerable is True


def test_it_no_ops_when_no_judgment_tier_is_enabled() -> None:
    out = augment(ANSWERABLE, "Are Moms better than Dads?", gateway=FakeGateway({"contested": 1.0}))
    assert out.answerable is True


def test_an_outage_degrades_to_todays_behaviour(judgment_on) -> None:
    out = augment(ANSWERABLE, "Are Moms better?", gateway=FakeGateway(refuse="service down"))
    assert out.answerable is True


def test_the_reason_records_the_engine_and_score(judgment_on) -> None:
    out = augment(ANSWERABLE, "Are Moms better?", gateway=FakeGateway({"contested": 0.88}))
    added = out.reasons[-1]
    assert added["engine"] == "jev" and added["score"] == pytest.approx(0.88)


# --- PII presence: a gate, not a redaction input -------------------------
def test_it_reports_presence_without_claiming_a_location(judgment_on) -> None:
    det = PiiJudgmentDetector(FakeGateway({"personal_data": 0.95}))
    result = det.detect("reach me on the usual number", DetectionContext(surface="output"))
    (found,) = result.detections
    assert found.entity_type == "PII.PRESENT_UNLOCATED"
    assert found.start == found.end == 0  # no span is claimed
    assert found.sample == ""  # nothing honest to show


def test_its_threshold_is_higher_than_injections(judgment_on) -> None:
    """0.8, because this fires on ordinary customer content, not on attacks."""
    det = PiiJudgmentDetector(FakeGateway({"personal_data": 0.7}))
    assert det.detect("some text", DetectionContext(surface="output")).detections == []


def test_it_is_absent_unless_a_tier_and_egress_are_both_on() -> None:
    assert PiiJudgmentDetector(FakeGateway()).available() is False


def test_the_pii_block_gate_refuses_rather_than_returning_clean(judgment_on, monkeypatch) -> None:
    """Refusal must be visible, or the pipeline reads it as 'no PII here'."""
    det = PiiJudgmentDetector(FakeGateway(refuse="judgment_pii_egress is 'block'"))
    result = det.detect("ssn 123-45-6789", DetectionContext(surface="output"))
    assert result.status == "unavailable"
    assert result.detections == []


def test_it_covers_output_where_injection_does_not() -> None:
    """A model leaking a customer's address in its own reply is the main case."""
    assert "output" in PiiJudgmentDetector.surfaces


# --- commitments: the fourth surface -------------------------------------
def _commit_gateway(**scores):
    return FakeGateway(scores)


def test_the_widened_regexes_catch_active_voice() -> None:
    """Found by benchmarking: the closed set only matched the passive form."""
    from agentfox.grounding.commitments import detect_commitments

    assert detect_commitments("I've approved your refund of 50 USD.")
    assert detect_commitments("Your refund has already been approved.")
    assert detect_commitments("I will approve this refund today.")


def test_the_widened_regexes_still_leave_the_hedges_alone() -> None:
    from agentfox.grounding.commitments import detect_commitments

    assert not detect_commitments("Refunds are usually approved within two days.")
    assert not detect_commitments("Your refund may be approved once a reviewer checks it.")


def test_judgment_adds_a_commitment_with_no_binding_word(judgment_on) -> None:
    from agentfox.detection.judgment.commitments import augment

    text = "That's sorted — the 50 USD is on its way back to you."
    from agentfox.grounding.commitments import detect_commitments

    assert detect_commitments(text) == []  # no binding word; the regexes cannot see it
    out = augment([], text, gateway=_commit_gateway(settles_outcome=0.9))
    assert len(out) == 1
    assert out[0].kind == "implied"
    assert "judgment" in out[0].why


def test_judgment_never_drops_a_deterministic_finding(judgment_on) -> None:
    """Those are the findings that survive a hearing."""
    from agentfox.grounding.commitments import Commitment
    from agentfox.detection.judgment.commitments import augment

    existing = [Commitment("promise", "I guarantee", "binds the company")]
    out = augment(existing, "I guarantee a refund.", gateway=_commit_gateway(settles_outcome=0.0))
    assert out == existing


def test_an_authorised_agent_is_not_second_guessed(judgment_on) -> None:
    from agentfox.detection.judgment.commitments import augment

    out = augment(
        [], "I've approved it.", authorised=True, gateway=_commit_gateway(settles_outcome=1.0)
    )
    assert out == []


def test_it_no_ops_with_no_tier_enabled() -> None:
    from agentfox.detection.judgment.commitments import augment

    assert augment([], "That's sorted, money's on its way.") == []


def test_an_outage_leaves_the_deterministic_answer(judgment_on) -> None:
    from agentfox.detection.judgment.commitments import augment

    assert augment([], "That's sorted.", gateway=FakeGateway(refuse="down")) == []
