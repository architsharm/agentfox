"""Turning NeMo Guardrails and Guardrails AI on, which was not possible.

Both adapters were registered with their configuration hard-coded empty —
`NemoRailsDetector()` with no config path, `GuardrailsAiDetector()` with no
validators — and `available()` returns False when those are empty. No setting
existed to fill either, so installing `agentfox[rails]` or `agentfox[validators]`
changed nothing: two detectors that could not be reached by any means.

Everything below was found by installing the real packages (nemoguardrails
0.24.1, guardrails-ai 0.11.0) into a scratch venv and running them. Neither
detect path had ever executed — both carry `# pragma: no cover - requires
optional dependency` — so what CI had checked was that they stayed off.

The packages themselves stay out of CI. These use stand-ins shaped like the real
APIs, each built to the behaviour actually observed.
"""

from __future__ import annotations

import sys
import types

import pytest

from agentfox.config import get_settings
from agentfox.guardrails.adapters.rails import GuardrailsAiDetector, NemoRailsDetector
from agentfox.guardrails.base import DetectionContext


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# NeMo Guardrails
# ---------------------------------------------------------------------------


@pytest.fixture
def nemo_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "nemoguardrails", types.ModuleType("nemoguardrails"))


def test_nemo_is_unreachable_with_nothing_configured(nemo_installed):
    """The state it shipped in: installed, and impossible to switch on."""
    d = NemoRailsDetector()
    assert d.config_path is None
    assert d.available() is False
    assert "no rails to run" in d.unavailable_reason


def test_a_config_directory_in_settings_turns_it_on(nemo_installed, monkeypatch, tmp_path):
    (tmp_path / "config.yml").write_text("models: []\n")
    monkeypatch.setenv("AGENTFOX_NEMO_RAILS_CONFIG_PATH", str(tmp_path))
    get_settings.cache_clear()

    d = NemoRailsDetector()
    assert d.config_path == str(tmp_path)
    assert d.available() is True


def test_the_path_is_read_per_call_not_frozen_at_registration(
    nemo_installed, monkeypatch, tmp_path
):
    """Registration happens at import time, before an operator's config exists.

    A value captured in `__init__` would ignore whatever they later configure.
    """
    d = NemoRailsDetector()
    assert d.available() is False
    monkeypatch.setenv("AGENTFOX_NEMO_RAILS_CONFIG_PATH", str(tmp_path))
    get_settings.cache_clear()
    assert d.available() is True


def test_an_explicit_path_beats_settings(nemo_installed, monkeypatch, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("AGENTFOX_NEMO_RAILS_CONFIG_PATH", str(tmp_path))
    get_settings.cache_clear()
    assert NemoRailsDetector(config_path=str(other)).config_path == str(other)


def test_a_path_that_is_the_yaml_file_is_refused_with_the_reason(
    nemo_installed, monkeypatch, tmp_path
):
    """The obvious mistake, and NeMo's own exception for it is unhelpful."""
    config = tmp_path / "config.yml"
    config.write_text("models: []\n")
    monkeypatch.setenv("AGENTFOX_NEMO_RAILS_CONFIG_PATH", str(config))
    get_settings.cache_clear()

    d = NemoRailsDetector()
    assert d.available() is False
    assert "not a directory" in d.unavailable_reason


def test_the_reason_distinguishes_a_missing_package_from_a_missing_config(monkeypatch):
    monkeypatch.setitem(sys.modules, "nemoguardrails", None)
    assert "not installed" in NemoRailsDetector().unavailable_reason


def _nemo_detector(monkeypatch, tmp_path, response, rails=()):
    """A NemoRailsDetector whose `_rails.generate` returns what we say."""
    monkeypatch.setitem(sys.modules, "nemoguardrails", types.ModuleType("nemoguardrails"))
    monkeypatch.setenv("AGENTFOX_NEMO_RAILS_CONFIG_PATH", str(tmp_path))
    get_settings.cache_clear()

    class _Rail:
        def __init__(self, name):
            self.name = name
            self.stop = True

    class _Log:
        activated_rails = [_Rail(n) for n in rails]

    class _Response:
        def __init__(self):
            self.response = [{"role": "assistant", "content": response}]
            self.log = _Log()

    class _Rails:
        def generate(self, **_kwargs):
            return _Response()

    d = NemoRailsDetector()
    d.__dict__["_rails"] = _Rails()
    return d


def test_a_rails_config_that_cannot_run_is_not_reported_as_clean(monkeypatch, tmp_path):
    """The defect this test exists for.

    With no model configured, NeMo catches its own ValueError, answers "I'm
    sorry, an internal error has occurred." and marks the rail stopped. The old
    code read that prose for the phrases "i cannot" / "i'm not able to", found
    neither, and returned no detections — a completely non-functional rails
    config reporting a clean pass. `adapters/hub.py` already raises in exactly
    this situation, with a comment explaining why; this adapter did not.
    """
    d = _nemo_detector(
        monkeypatch, tmp_path, "I'm sorry, an internal error has occurred.", rails=["self check"]
    )
    with pytest.raises(RuntimeError) as excinfo:
        d.detect("wire funds", DetectionContext(surface="input"))
    assert "could not run" in str(excinfo.value)


def test_a_stopped_rail_is_a_detection_whatever_its_wording(monkeypatch, tmp_path):
    """The verdict comes from `activated_rails`, not from reading the reply.

    Matching prose meant a rail whose refusal is worded differently — most of
    them, since the wording is the operator's to write — registered as a pass.
    """
    d = _nemo_detector(
        monkeypatch, tmp_path, "Let's talk about something else.", rails=["refuse payments"]
    )
    detections = d.detect("wire funds", DetectionContext(surface="input")).detections
    assert [x.entity_type for x in detections] == ["RAILS.BLOCKED"]
    assert detections[0].detail["rails"] == ["refuse payments"]


def test_no_rail_firing_is_a_pass(monkeypatch, tmp_path):
    d = _nemo_detector(monkeypatch, tmp_path, "Your order ships tomorrow.")
    assert d.detect("where is my order", DetectionContext(surface="input")).detections == []


# ---------------------------------------------------------------------------
# Guardrails AI
# ---------------------------------------------------------------------------


class _Outcome:
    def __init__(self, passed):
        self.validation_passed = passed
        self.validation_summaries = []


class _TheirValidationError(Exception):
    pass


_TheirValidationError.__name__ = "ValidationError"


@pytest.fixture
def guardrails_ai(monkeypatch):
    """A `guardrails` package shaped like 0.11: `use`, and a raising `validate`."""
    calls: dict = {}

    class Guard:
        def use(self, *validators):
            calls["use"] = list(validators)
            return self

        def validate(self, content):
            if content == "bad":
                raise _TheirValidationError("Value is not parseable as valid JSON!")
            return _Outcome(True)

    root = types.ModuleType("guardrails")
    root.Guard = Guard
    base = types.ModuleType("guardrails.validator_base")

    class Validator:
        pass

    base.Validator = Validator
    root.validator_base = base
    monkeypatch.setitem(sys.modules, "guardrails", root)
    monkeypatch.setitem(sys.modules, "guardrails.validator_base", base)

    ns = types.ModuleType("guardrails_ai")
    monkeypatch.setitem(sys.modules, "guardrails_ai", ns)
    for slug, class_name in (("valid_json", "ValidJson"), ("detect_pii", "DetectPII")):
        mod = types.ModuleType(f"guardrails_ai.{slug}")
        made = type(class_name, (Validator,), {})
        setattr(mod, class_name, made)
        monkeypatch.setitem(sys.modules, f"guardrails_ai.{slug}", mod)
        setattr(ns, slug, mod)
    return calls


def test_guardrails_ai_is_unreachable_with_nothing_configured(guardrails_ai):
    d = GuardrailsAiDetector()
    assert d.available() is False
    assert "no validators to run" in d.unavailable_reason


def test_slugs_in_settings_turn_it_on(guardrails_ai, monkeypatch):
    monkeypatch.setenv("AGENTFOX_GUARDRAILS_AI_VALIDATORS", '["valid_json", "detect_pii"]')
    get_settings.cache_clear()

    d = GuardrailsAiDetector()
    assert d.validator_slugs == ["valid_json", "detect_pii"]
    assert [type(v).__name__ for v in d.validators] == ["ValidJson", "DetectPII"]
    assert d.available() is True


def test_a_named_validator_that_is_not_installed_says_so(guardrails_ai, monkeypatch):
    monkeypatch.setenv("AGENTFOX_GUARDRAILS_AI_VALIDATORS", '["not_a_real_validator"]')
    get_settings.cache_clear()

    d = GuardrailsAiDetector()
    assert d.available() is False
    assert "not_a_real_validator" in d.unavailable_reason


def test_the_guard_is_composed_with_use_when_use_many_is_gone(guardrails_ai, monkeypatch):
    """`use_many` was theirs through 0.5.x and is gone by 0.11.

    pyproject allows >=0.5, so both are real. Against 0.11 the old call raised
    `'Guard' object has no attribute 'use_many'` on the first request — the
    composite detector could never run at all.
    """
    monkeypatch.setenv("AGENTFOX_GUARDRAILS_AI_VALIDATORS", '["valid_json"]')
    get_settings.cache_clear()

    d = GuardrailsAiDetector()
    assert d.detect("ok", DetectionContext(surface="output")).detections == []
    assert [type(v).__name__ for v in guardrails_ai["use"]] == ["ValidJson"]


def test_a_failed_validation_is_a_detection_not_a_thrown_detector(guardrails_ai, monkeypatch):
    """Their default `on_fail` RAISES rather than returning an outcome.

    The old code only read `validation_passed`, so every genuine finding became
    a thrown detector; the pipeline then recorded `error` and degraded the
    check. A real violation reported as a broken control is the one direction a
    guardrail must never fail in.
    """
    monkeypatch.setenv("AGENTFOX_GUARDRAILS_AI_VALIDATORS", '["valid_json"]')
    get_settings.cache_clear()

    detections = GuardrailsAiDetector().detect("bad", DetectionContext(surface="output")).detections
    assert [x.entity_type for x in detections] == ["SCHEMA.VIOLATION"]
    assert "not parseable as valid JSON" in detections[0].detail["summaries"][0]
    assert detections[0].detail["validators"] == ["valid_json"]


def test_an_exception_that_is_not_theirs_still_propagates(guardrails_ai, monkeypatch):
    """Catching everything would hide a broken detector as a finding — the same
    mistake in the opposite direction."""
    monkeypatch.setenv("AGENTFOX_GUARDRAILS_AI_VALIDATORS", '["valid_json"]')
    get_settings.cache_clear()

    d = GuardrailsAiDetector()

    class _Boom:
        def validate(self, _content):
            raise MemoryError("out of memory")

    d.__dict__["_guard"] = _Boom()
    with pytest.raises(MemoryError):
        d.detect("anything", DetectionContext(surface="output"))


def test_explicit_validator_instances_still_work(guardrails_ai):
    """Constructing the detector in code must not need settings."""
    from guardrails_ai.valid_json import ValidJson

    d = GuardrailsAiDetector(validators=[ValidJson()])
    assert d.available() is True
    assert d.validator_slugs == []
