"""Reading a Guardrails AI guard, in each form it is written, without running it."""

from __future__ import annotations

import json

from agentfox.capabilities.detection.importers import planner
from agentfox.capabilities.detection.importers.guardrails_ai import parse, plan, slug_of

PYTHON = """
from guardrails import Guard, OnFailAction
from guardrails.hub import CompetitorCheck, ToxicLanguage, DetectPII, RestrictToTopic, ValidLength
guard = Guard().use_many(
    CompetitorCheck(["Globex", "Initech"], on_fail=OnFailAction.REASK),
    ToxicLanguage(threshold=0.5, on_fail="exception"),
    DetectPII(["EMAIL_ADDRESS"], "fix"),
)
guard.use(
    RestrictToTopic, valid_topics=["shipping", "orders"], invalid_topics=["politics"], on="messages"
)
guard.use(ValidLength(1, 100))
guard.use(SomethingInHouse())
"""


def _kinds(p):
    return [(i.kind, i.target) for i in p.items]


def test_slugs_from_every_spelling():
    assert {
        slug_of(n)
        for n in ("CompetitorCheck", "competitor-check", "hub://guardrails/competitor_check")
    } == {"competitor_check"}


def test_python_guard_maps_each_validator():
    p = plan(PYTHON)
    competitors = next(i for i in p.items if i.target == "gr-competitor-check")
    # Its own port, with its own settings, rather than an approximation.
    assert competitors.rule.kind == "validator"
    assert competitors.rule.validator.name == "competitor_check"
    assert competitors.rule.validator.params["competitors"] == ["Globex", "Initech"]
    assert competitors.on_block == "reask"
    allowed = next(i for i in p.items if i.target == "gr-allowed-topics")
    assert allowed.rule.polarity == "allow" and allowed.rule.surfaces == ["input"]
    assert ("detector", "safety.lexicon") in _kinds(p) and ("detector", "custom.topics") in _kinds(
        p
    )
    [baseline] = [i for i in p.items if i.target == "baseline"]
    assert "ToxicLanguage" in baseline.source and "DetectPII" in baseline.source
    length = next(i for i in p.items if i.target == "gr-valid-length")
    assert length.rule.validator.params == {"min": 1, "max": 100, "unit": "chars"} or (
        length.rule.validator.params["min"] == 1 and length.rule.validator.params["max"] == 100
    )
    skipped = {i.source: i.note for i in p.of("skipped")}
    assert set(skipped) == {"SomethingInHouse"}


def test_on_fail_carries_over():
    p = plan(
        'Guard().use(BanList(banned_words=["x1"], on_fail="noop"))'
        '.use(BanList(banned_words=["x2"], on_fail="fix"))'
    )
    assert [i.effect for i in p.of("custom_rule")] == ["allow", "redact"]


def test_rail_is_read_without_an_xml_parser():
    rail = """<rail version="0.1"><output>
      <string name="a" on-fail-competitor-check="refrain"
        validators="competitor-check: ['Apple', 'Samsung']; valid-length: 1 10"/>
    </output></rail>"""
    rule, length = plan(rail).of("custom_rule")
    assert rule.rule.validator.params["competitors"] == ["Apple", "Samsung"]
    assert rule.effect == "block" and rule.line == 3
    assert length.rule.validator.name == "valid_length"


def test_to_dict_json():
    data = {
        "validators": [
            {
                "id": "guardrails/ban_list",
                "on": "messages",
                "onFail": "exception",
                "kwargs": {"banned_words": ["foo"]},
            }
        ]
    }
    [rule] = plan(json.dumps(data)).of("custom_rule")
    assert rule.rule.surfaces == ["input"]


def test_existing_keys_are_not_overwritten():
    p = plan('Guard().use(BanList(banned_words=["a"]))', existing_keys={"gr-ban-list"})
    assert p.of("custom_rule")[0].target == "gr-ban-list-2"


def test_nothing_is_executed_and_bad_input_says_so():
    validators, _ = parse('Guard().use(BanList(banned_words=__import__("os").listdir("/")))')
    assert validators[0].kwargs["banned_words"] is None
    assert plan("x = (").errors and plan("print(1)").errors


def test_registry_resolves_the_importer():
    assert planner("guardrails-ai") is plan and planner("nope") is None


def test_a_validator_needing_settings_it_was_not_given_is_skipped_with_why():
    [item] = plan("Guard().use(RegexMatch())").items
    assert item.kind == "skipped" and "regex" in item.note


def test_a_settings_free_port_offered_as_a_detector_is_switched_on():
    p = plan("Guard().use(WebSanitization())")
    assert ("detector", "validator.web_sanitization") in _kinds(p)
