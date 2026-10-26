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
    assert rule_about(_rule(capability="requires_approval")) == "tools that need approval"
    assert rule_about(_rule(action_risk="undeclared-table")) == "risky actions: undeclared table"
    assert (
        rule_about(_rule(completion_requires=["refund.issued"]))
        == "saying it's done without refund.issued"
    )
    # A content rule is described by what it finds, not here.
    pii = _rule(surface=["input"], detection=DetectionCondition(entity_prefix="PII"))
    assert rule_about(pii) == ""


# --- which checks can fire a rule: what they find, and where -------------------------

from agentfox.capabilities.detection.catalog import (  # noqa: E402
    ANY,
    Feed,
    can_fire,
    checks_for_rule,
    describe,
    feeds_for,
    rule_finds,
    rule_surfaces,
)


def _shipped(doc_key: str, rule_id: str) -> Rule:
    from agentfox.platform.policy.store import load_available

    doc = next(d for d in load_available() if d.key == doc_key)
    return next(r for r in doc.rules if r.id == rule_id)


def _checks(rule: Rule, session=None) -> list[str]:
    return checks_for_rule(rule, feeds_for(all_detectors(), session))


def test_a_rule_on_reasoning_lists_only_checks_that_run_on_reasoning():
    for doc, rule_id in (
        ("baseline", "injection.adopted_in_reasoning"),
        ("coding-agent", "code.injection_adopted"),
    ):
        checks = _checks(_shipped(doc, rule_id))
        assert checks, rule_id
        for key in checks:
            assert "reasoning" in all_detectors()[key].surfaces, (rule_id, key)
        # The ML classifier and the judge never see reasoning.
        assert "injection.classifier" not in checks
        assert "injection.judgment" not in checks
        assert "injection.heuristic" in checks


def test_a_rule_on_tool_arguments_lists_only_checks_that_run_there():
    checks = _checks(_shipped("tool-containment", "injection.in_tool_arguments"))
    assert "injection.heuristic" in checks
    assert "injection.classifier" not in checks and "injection.judgment" not in checks
    assert all("tool_args" in all_detectors()[k].surfaces for k in checks)
    # `validator.web_sanitization` reports CODE too, but never on tool arguments.
    assert _checks(_shipped("agent-integrity", "code.insecure")) == ["code.insecure"]


def test_a_detection_rule_naming_nothing_matches_any_finding():
    rule = _rule(detection=DetectionCondition())
    assert rule_finds(rule) == ANY
    assert can_fire(rule, Feed("x", "PII", ("input",)))
    assert len(_checks(rule)) > 10
    assert rule_finds(_rule(budget_exceeded=True)) == ""
    assert rule_surfaces(rule) is None
    assert rule_surfaces(_rule(surface=["output"], detection=DetectionCondition())) == ["output"]


def test_exact_entities_match_exactly_and_kinds_by_kind():
    jail = _rule(detection=DetectionCondition(entity="INJECTION.JAILBREAK"))
    assert can_fire(jail, Feed("injection.heuristic", "INJECTION", ("input",)))
    assert not can_fire(jail, Feed("pii.native", "PII", ("input",)))
    acme = _rule(detection=DetectionCondition(entity="CUSTOM.ACME"))
    assert can_fire(acme, Feed("custom.lists", "CUSTOM.ACME", ("input",), "rule:acme"))
    assert not can_fire(acme, Feed("custom.lists", "CUSTOM.OTHER", ("input",), "rule:other"))
    on_output = _rule(surface=["output"], detection=DetectionCondition(entity_prefix="PII"))
    assert not can_fire(on_output, Feed("x", "PII", ("input",)))


def _custom_model(session, key: str, prefix: str, surfaces=("input", "output")):
    from agentfox.core.models import CustomModel

    session.add(
        CustomModel(
            key=key,
            name=key,
            url="https://models.example.com/classify",
            surfaces_json=list(surfaces),
            entity_prefix=prefix,
        )
    )
    session.flush()


def test_custom_models_report_what_they_were_registered_as(session):
    detector = all_detectors()["custom.models"]
    # Nothing registered: its default kind, as before.
    assert describe(detector, feeds_for(all_detectors(), session))["finds_all"] == ["CUSTOM"]
    _custom_model(session, "acme-pii", "PII")
    _custom_model(session, "acme-guard", "CUSTOM")
    facts = describe(detector, feeds_for(all_detectors(), session))
    assert facts["finds"] == "CUSTOM"  # unchanged, for compatibility
    assert sorted(facts["finds_all"]) == ["CUSTOM", "PII"]
    # A PII rule is checked by the PII model, on the surfaces it runs on.
    pii_on_input = _rule(surface=["input"], detection=DetectionCondition(entity_prefix="PII"))
    assert "custom.models" in _checks(pii_on_input, session)
    pii_on_tools = _rule(surface=["tool_args"], detection=DetectionCondition(entity_prefix="PII"))
    assert "custom.models" not in _checks(pii_on_tools, session)
    # An injection rule is not.
    inj = _rule(detection=DetectionCondition(entity_prefix="INJECTION"))
    assert "custom.models" not in _checks(inj, session)


def test_a_custom_rule_is_checked_by_the_detector_that_matches_it(session):
    from agentfox.core.models import CustomRule

    session.add(CustomRule(key="acme", name="Acme", kind="terms", entries_json=["acme"]))
    session.add(CustomRule(key="travel", name="Travel", kind="topic", entries_json=["flights"]))
    session.flush()
    _custom_model(session, "acme-guard", "CUSTOM")

    def checks(entity: str) -> list[str]:
        return _checks(_rule(detection=DetectionCondition(entity=entity)), session)

    assert checks("CUSTOM.ACME") == ["custom.lists"]
    assert checks("CUSTOM.TRAVEL") == ["custom.lists", "custom.topics"]
    assert checks("CUSTOM.ACME_GUARD") == ["custom.models"]
    # A rule on every custom finding is fed by all of them.
    every = _checks(_rule(detection=DetectionCondition(entity_prefix="CUSTOM")), session)
    assert every == ["custom.lists", "custom.models", "custom.topics"]
