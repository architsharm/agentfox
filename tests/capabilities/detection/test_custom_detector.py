"""The custom-rule detector, with the offline scorer CI has."""

from __future__ import annotations

import pytest

from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.custom import (
    CustomListDetector,
    CustomRuleSpec,
    LexicalTopicScorer,
    compile_rule,
    validate_pattern,
)


def _match(spec: dict, text: str, surface: str = "input", agent: str | None = None):
    rule = compile_rule(CustomRuleSpec(**{"key": "test", "name": "t", **spec}))
    detector = CustomListDetector(scorer=LexicalTopicScorer())
    return detector.detect(
        text, DetectionContext(surface=surface, agent_slug=agent, extra={"custom_rules": [rule]})
    ).detections


def test_terms_respect_word_boundaries():
    spec = {"kind": "terms", "entries": ["Acme", "C++"]}
    assert _match(spec, "Acme's pricing") and _match(spec, "we use C++ here")
    assert not _match(spec, "Acmeville is lovely")


def test_terms_are_case_insensitive_unless_asked():
    assert _match({"kind": "terms", "entries": ["globex"]}, "GLOBEX")
    assert not _match({"kind": "terms", "entries": ["globex"], "case_sensitive": True}, "GLOBEX")


def test_patterns_locate_each_match():
    [d] = _match({"kind": "patterns", "entries": [r"ACC-\d{4}"]}, "account ACC-1234 is open")
    assert (d.start, d.end) == (8, 16)


def test_scope_by_agent_and_surface():
    spec = {
        "kind": "terms",
        "entries": ["secret"],
        "agents": ["billing-bot"],
        "surfaces": ["output"],
    }
    assert _match(spec, "secret", surface="output", agent="billing-bot")
    assert not _match(spec, "secret", surface="input", agent="billing-bot")
    assert not _match(spec, "secret", surface="output", agent="other-bot")


def test_a_denied_topic_by_its_own_words():
    spec = {
        "kind": "topic",
        "description": "medical diagnosis symptoms treatment",
        "examples": ["what medicine should I take"],
    }
    assert _match(spec, "Which medicine treats these symptoms?")
    assert not _match(spec, "Where is my parcel?")


def test_off_topic_is_judged_only_on_real_questions():
    spec = {
        "kind": "topic",
        "polarity": "allow",
        "description": "orders shipping delivery parcel tracking",
    }
    assert not _match(spec, "Where is my parcel and when is delivery?")
    assert _match(spec, "Tell me a joke about elephants and giraffes please")
    assert not _match(spec, "hi there")


def test_no_rules_is_free():
    assert CustomListDetector().detect("anything", DetectionContext()).detections == []


@pytest.mark.parametrize("bad", ["(a+)+", r"(\w*)*x", "[unclosed", "x" * 400])
def test_patterns_that_could_hang_or_break_are_refused(bad):
    with pytest.raises(ValueError):
        validate_pattern(bad)


def test_a_weak_topic_match_still_reaches_the_rules_default_threshold():
    """Lexical matches start at 0.34; the rule fires at 0.5. Scores are calibrated so a
    match is never detected-and-ignored."""
    from agentfox.capabilities.detection.custom import _calibrated

    assert _calibrated(0.34, 0.34) == 0.5
    assert 0.5 < _calibrated(0.43, 0.34) < 0.7
    assert _calibrated(1.0, 0.34) == 1.0
    [d] = _match(
        {"kind": "topic", "description": "medical diagnosis symptoms treatment"},
        "Which medicine treats these symptoms?",
    )
    assert d.score >= 0.5 and "similarity" in d.detail
