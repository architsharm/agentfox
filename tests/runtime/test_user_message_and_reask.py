"""A rule can tell the end user what happened, and can ask for a re-ask instead of a refusal."""

from __future__ import annotations

from agentfox.platform.policy.engine import NativePolicyEngine
from agentfox.platform.policy.model import PolicyDocument, PolicyInput
from agentfox.runtime.enforcement.result import (
    masking_entities,
    reask_instruction_for,
    user_message_for,
)

POLICY = """
key: msg-test
name: Message test
mode: enforce
rules:
  - id: words.block
    when: {detection: {entity_prefix: CUSTOM.BANNED}}
    effect: block
    reason: banned phrase in the reply
    message: "Sorry, I can't talk about that."
    on_block: reask
"""


def _fired():
    doc = PolicyDocument.from_yaml(POLICY)
    decision = NativePolicyEngine().evaluate(
        doc,
        PolicyInput(surface="output", detections=[{"entity_type": "CUSTOM.BANNED", "score": 1.0}]),
    )
    return [f.to_json() for f in decision.rules_fired]


def test_the_engine_carries_message_and_on_block():
    [rule] = _fired()
    assert rule["message"] == "Sorry, I can't talk about that."
    assert rule["on_block"] == "reask"


def test_unset_fields_keep_the_old_record_shape():
    doc = PolicyDocument.from_yaml(
        POLICY.replace('    message: "Sorry, I can\'t talk about that."\n', "").replace(
            "    on_block: reask\n", ""
        )
    )
    decision = NativePolicyEngine().evaluate(
        doc,
        PolicyInput(surface="output", detections=[{"entity_type": "CUSTOM.BANNED", "score": 1.0}]),
    )
    record = decision.rules_fired[0].to_json()
    assert "message" not in record and "on_block" not in record


def test_user_message_comes_from_the_deciding_rule_only():
    rules = [
        {"rule_id": "a", "effect": "redact", "message": "masked"},
        {"rule_id": "b", "effect": "block", "message": "stopped"},
    ]
    assert user_message_for("block", rules) == "stopped"
    assert user_message_for("allow", rules) == ""


def test_reask_needs_every_blocking_rule_to_ask_for_it():
    reask = {"rule_id": "a", "effect": "block", "reason": "too long", "on_block": "reask"}
    refuse = {"rule_id": "b", "effect": "block", "reason": "unsafe"}
    assert "too long" in reask_instruction_for("block", "output", [reask])
    assert reask_instruction_for("block", "output", [reask, refuse]) == ""
    # Never on a tool call, and never when nothing blocked.
    assert reask_instruction_for("block", "tool_args", [reask]) == ""
    assert reask_instruction_for("escalate", "output", [reask]) == ""


def test_masking_covers_what_the_masking_rule_named():
    exact, prefixes = masking_entities(
        [
            {"effect": "redact", "entity_prefixes": ["CUSTOM.COMPETITORS"]},
            {"effect": "block", "entity_prefixes": ["CUSTOM.SECRETPROJECT"]},
        ]
    )
    assert "CUSTOM.COMPETITORS" in prefixes and "PII" in prefixes
    assert "CUSTOM.SECRETPROJECT" not in prefixes
    assert exact == set()
