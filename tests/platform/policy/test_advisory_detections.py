"""Advisory detections are recorded by observing policies and ignored by enforcing ones.

`injection.classifier`'s ensemble backstop marks its hits advisory: it lifts recall on
SPML and yanismiraoui by 50+ points, and lifts NotInject false positives from 11.5% to
41%. Observing, that trade is worth it; blocking, it is not.
"""

from __future__ import annotations

from agentfox.platform.policy.engine import NativePolicyEngine
from agentfox.platform.policy.model import (
    Condition,
    DetectionCondition,
    PolicyDocument,
    PolicyInput,
    Rule,
)


def _doc(mode: str) -> PolicyDocument:
    rule = Rule(
        id="block-injection",
        when=Condition(detection=DetectionCondition(entity_prefix="INJECTION", min_score=0.6)),
        effect="block",
    )
    return PolicyDocument(key="advisory-fixture", mode=mode, rules=[rule])


def _input(*, advisory: bool) -> PolicyInput:
    return PolicyInput(
        detections=[{"entity_type": "INJECTION.JAILBREAK", "score": 0.97, "advisory": advisory}]
    )


def test_an_enforcing_policy_does_not_block_on_an_advisory_detection_alone():
    decision = NativePolicyEngine().evaluate(_doc("enforce"), _input(advisory=True))
    assert decision.verdict == "allow"
    assert decision.rules_fired == []


def test_an_enforcing_policy_still_blocks_on_a_primary_detection():
    decision = NativePolicyEngine().evaluate(_doc("enforce"), _input(advisory=False))
    assert decision.verdict == "block"


def test_an_observing_policy_records_the_advisory_detection():
    decision = NativePolicyEngine().evaluate(_doc("observe"), _input(advisory=True))
    assert decision.verdict == "allow"
    assert decision.effective_verdict == "block"
    assert [r.rule_id for r in decision.rules_fired] == ["block-injection"]


def test_for_mode_leaves_the_input_untouched_when_nothing_is_advisory():
    pinput = _input(advisory=False)
    assert pinput.for_mode("enforce") is pinput
