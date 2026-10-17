"""The validator framework: registry, plug-ins, detectors and custom rules."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.custom import (
    CustomListDetector,
    CustomRuleSpec,
    CustomValidatorDetector,
    compile_rule,
)
from agentfox.capabilities.detection.validators import (
    _REGISTRY,
    CheckContext,
    Finding,
    Validator,
    all_validators,
    check,
    get_validator,
    register_validator,
)
from agentfox.capabilities.detection.validators.detector import ValidatorDetector


class _NeedsWord(BaseModel):
    word: str


class _MustSayPlease(Validator):
    name = "test_must_say_please"
    label = "Must say please"
    entity_type = "FORMAT.TEST"
    surfaces = ("output",)
    Params = _NeedsWord

    def check(self, text, params, ctx):
        return [] if params.word in text else [Finding(f"missing '{params.word}'")]


@pytest.fixture
def plugin():
    register_validator(_MustSayPlease)
    yield get_validator("test_must_say_please")
    _REGISTRY.pop("test_must_say_please", None)


def test_builtins_register_and_describe_themselves():
    validators = all_validators()
    assert "ban_list" in validators
    for v in validators.values():
        d = v.describe()
        assert d["name"] and d["entity_type"], v
        assert d["kind"] in ("rule", "model", "judge")
        assert d["params_schema"]["type"] == "object"
        # Every port names where it came from.
        if v.upstream:
            assert v.upstream.startswith("guardrails-ai/")


def test_settings_are_checked_before_anything_runs():
    with pytest.raises(ValueError, match="banned_words"):
        get_validator("ban_list").params({})
    with pytest.raises(ValueError, match="max_l_dist"):
        get_validator("ban_list").params({"banned_words": ["x"], "max_l_dist": 9})


def test_fuzzy_ban_list_catches_spacing_and_typos_but_not_substrings():
    words = {"banned_words": ["globex"]}
    assert check("ban_list", "try G l o b e x today", words)
    assert check("ban_list", "is globbex cheaper?", words)
    hit = check("ban_list", "ask globex.", words)[0]
    assert (hit.start, hit.end) == (4, 10)
    assert not check("ban_list", "the globexcorporation tower", words)
    assert not check("ban_list", "a class act", {"banned_words": ["ass"]})


def test_an_entry_point_validator_is_a_peer(plugin):
    assert plugin.standalone() is False
    assert check("test_must_say_please", "please do", {"word": "please"}) == []
    assert check("test_must_say_please", "do it", {"word": "please"})


def test_only_settings_free_opted_in_validators_become_detectors():
    keys = {k for k in all_detectors() if k.startswith("validator.")}
    for name, v in all_validators().items():
        assert (f"validator.{name}" in keys) == (v.detector and v.standalone()), name


def test_a_validator_detector_reports_spans_redacted():
    class _Flag(Validator):
        name = "test_flag_secretword"
        entity_type = "SECRET.TEST"
        surfaces = ("output",)

        def check(self, text, params, ctx: CheckContext):
            i = text.find("hunter2")
            return [Finding("found it", i, i + 7)] if i >= 0 else []

    result = ValidatorDetector(_Flag()).detect(
        "pw is hunter2 ok", DetectionContext(surface="output")
    )
    d = result.detections[0]
    assert (d.entity_type, d.start, d.end) == ("SECRET.TEST", 6, 13)
    assert "hunter2" not in d.sample
    assert d.detail["validator"] == "test_flag_secretword"


def test_a_validator_rule_reports_under_its_own_entity(plugin):
    spec = CustomRuleSpec(
        key="say-please",
        name="Say please",
        kind="validator",
        validator={"name": "test_must_say_please", "params": {"word": "please"}},
    )
    # Where it checks defaults to where the validator can check.
    assert spec.surfaces == ["output"]
    rule = compile_rule(spec)
    ctx = DetectionContext(surface="output", extra={"custom_rules": [rule]})
    found = CustomValidatorDetector().detect("do it now", ctx).detections
    assert [d.entity_type for d in found] == ["CUSTOM.SAY_PLEASE"]
    assert found[0].detail["custom_rule"] == "say-please"
    assert CustomValidatorDetector().detect("please do it", ctx).detections == []
    # The word-list detector leaves validator rules alone.
    assert CustomListDetector().detect("do it now", ctx).detections == []
    # And it does not run where it was not asked to.
    ctx_in = DetectionContext(surface="input", extra={"custom_rules": [rule]})
    assert CustomValidatorDetector().detect("do it now", ctx_in).detections == []


def test_a_validator_rule_refuses_unknown_names_and_bad_settings(plugin):
    with pytest.raises(ValueError, match="no validator named"):
        CustomRuleSpec(key="x1", name="x", kind="validator", validator={"name": "nope"})
    with pytest.raises(ValueError, match="word"):
        CustomRuleSpec(
            key="x2", name="x", kind="validator", validator={"name": "test_must_say_please"}
        )
    with pytest.raises(ValueError, match="no allowed form"):
        CustomRuleSpec(
            key="x3",
            name="x",
            kind="validator",
            polarity="allow",
            validator={"name": "test_must_say_please", "params": {"word": "p"}},
        )


def test_a_rule_asks_for_more_budget_only_when_its_validator_needs_it(plugin):
    class _Slow(_MustSayPlease):
        name = "test_slow_judge"
        requires_budget_ms = 2500

    register_validator(_Slow)
    try:
        slow = compile_rule(
            CustomRuleSpec(
                key="slow",
                name="slow",
                kind="validator",
                validator={"name": "test_slow_judge", "params": {"word": "p"}},
            )
        )
        fast = compile_rule(
            CustomRuleSpec(
                key="fast",
                name="fast",
                kind="validator",
                validator={"name": "test_must_say_please", "params": {"word": "p"}},
            )
        )
        d = CustomValidatorDetector()
        assert d.budget_for(DetectionContext(surface="output", extra={"custom_rules": [fast]})) == 0
        both = DetectionContext(surface="output", extra={"custom_rules": [fast, slow]})
        assert d.budget_for(both) == 2500
    finally:
        _REGISTRY.pop("test_slow_judge", None)


def test_a_validator_needing_settings_can_still_be_wrapped_to_pull_its_weights():
    detector = ValidatorDetector(get_validator("ban_list"))
    assert detector.key == "validator.ban_list"
    with pytest.raises(RuntimeError, match="needs settings"):
        detector.detect("text", DetectionContext(surface="output"))


def test_the_validator_rules_detector_is_not_even_submitted_without_a_rule(plugin):
    """It declares a timeout, so it runs in the heavy pool. Submitted on every request
    with nothing to do, it queued behind slow models' stragglers and waited out the
    request's budget; CI's latency test caught it at 100–101 ms."""
    from agentfox.capabilities.detection.pipeline import DetectorPipeline

    pipeline = DetectorPipeline(detectors=[CustomValidatorDetector()])
    empty = pipeline.run("do it", DetectionContext(surface="output"))
    assert [r.detector_key for r in empty.results] == []

    rule = compile_rule(
        CustomRuleSpec(
            key="say-please",
            name="Say please",
            kind="validator",
            validator={"name": "test_must_say_please", "params": {"word": "please"}},
        )
    )
    ruled = pipeline.run(
        "do it", DetectionContext(surface="output", extra={"custom_rules": [rule]})
    )
    assert [r.detector_key for r in ruled.results] == ["custom.validators"]
    assert ruled.results[0].detections


def test_a_missing_library_is_looked_for_once_not_on_every_request(monkeypatch):
    """`available()` runs on every request; looking for an absent module walks the
    whole import path, which cost CI about 250 ms per request across the validators."""
    import importlib.util

    from agentfox.capabilities.detection.validators.base import module_present

    class _NeedsAbsentLib(Validator):
        name = "test_needs_absent_lib"
        entity_type = "FORMAT.TEST"
        requires = ("agentfox_test_no_such_module",)

    looked = []
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: looked.append(name) or real(name, *a)
    )
    module_present.cache_clear()
    v = _NeedsAbsentLib()
    assert [v.available() for _ in range(5)] == [False] * 5
    assert looked.count("agentfox_test_no_such_module") == 1
    module_present.cache_clear()
