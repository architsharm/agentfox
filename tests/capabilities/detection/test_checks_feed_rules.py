"""How a check feeds a rule: a rule matches the kind of finding a check reports.

The map's panel shows, under each rule, the checks that can fire it. That join is
only right if every check says what it finds, and every rule says what it looks for.
"""

from __future__ import annotations

from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection.catalog import finds_of
from agentfox.capabilities.protection.map import rule_about, rule_kind
from agentfox.platform.policy.model import Condition, DetectionCondition, Rule


def test_every_check_says_what_it_finds():
    unknown = [key for key, d in all_detectors().items() if not finds_of(d)]
    assert unknown == []


def test_checks_report_the_kind_rules_match_on():
    finds = {key: finds_of(d) for key, d in all_detectors().items()}
    # Regex, ML and LLM checks for the same risk report the same kind.
    assert finds["injection.heuristic"] == "INJECTION"
    assert finds["injection.judgment"] == "INJECTION"
    assert finds["unicode.tags"] == "INJECTION"
    assert finds["pii.native"] == finds["pii.judgment"] == "PII"
    assert finds["secrets.native"] == "SECRET"
    assert finds["safety.lexicon"] == "SAFETY"
    # A ported validator says it itself.
    assert finds["validator.web_sanitization"] == "CODE"


def _rule(**when) -> Rule:
    return Rule(id="r", when=Condition(**when))


def test_rules_are_content_action_or_run():
    content = _rule(surface=["input"], detection=DetectionCondition(entity_prefix="PII"))
    assert rule_kind(content) == "content"
    assert rule_kind(_rule(action_risk="sql.*")) == "action"
    assert rule_kind(_rule(taint_exceeds="user", tool_impact=["irreversible"])) == "action"
    assert rule_kind(_rule(budget_exceeded=True)) == "run"
    assert rule_kind(_rule(loop_detected=True)) == "run"


def test_rules_that_are_not_about_content_say_what_they_look_at():
    assert (
        rule_about(_rule(taint_exceeds="tool_result", tool_impact=["irreversible"]))
        == "irreversible tools · arguments that came from tool result or worse"
    )
    assert rule_about(_rule(tool_known=False)) == "tools the code never declared"
    assert rule_about(_rule(budget_exceeded=True)) == "budget used up"
