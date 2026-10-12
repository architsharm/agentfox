"""Judge validators: ported Guardrails AI checks that ask the judgment tier.

No network here. The panel's judges are replaced with a fake, the way
`test_judgment_detector.py` replaces the gateway, so what is pinned is the
contract: off unless a tier is enabled and permitted, a finding only at or above
the bar, and an error, never a clean result, when no judge answers.
"""

from __future__ import annotations

import pytest

from agentfox.capabilities.detection.validators import CheckContext, get_validator
from agentfox.capabilities.detection.validators.builtin import judges
from agentfox.capabilities.judgment import JevAnswer, JevResult, panel
from agentfox.capabilities.judgment.capability import DecisionKind, Tier
from agentfox.capabilities.judgment.jev import JevUnavailable
from agentfox.core.config import get_settings

JUDGES = {
    "llm_critic": ("QUALITY.METRIC_FAILED", DecisionKind.SEMANTIC),
    "response_evaluator": ("QUALITY.EVALUATION_FAILED", DecisionKind.SEMANTIC),
    "qa_relevance_llm_eval": ("QUALITY.IRRELEVANT", DecisionKind.SEMANTIC),
    "responsiveness_check": ("QUALITY.UNRESPONSIVE", DecisionKind.SEMANTIC),
    "politeness_check": ("QUALITY.IMPOLITE", DecisionKind.SEMANTIC),
    "logic_check": ("QUALITY.LOGICAL_FALLACY", DecisionKind.SEMANTIC),
    "persona_consistency": ("QUALITY.PERSONA_DRIFT", DecisionKind.SEMANTIC),
    "saliency_check": ("QUALITY.MISSING_TOPICS", DecisionKind.SEMANTIC),
    "toxic_language_llm": ("SAFETY.TOXIC", DecisionKind.SEMANTIC),
    "unusual_prompt": ("INJECTION.UNUSUAL", DecisionKind.PATTERN_OPEN),
    "prompt_injection_llm": ("INJECTION.INSTRUCTION_OVERRIDE", DecisionKind.PATTERN_OPEN),
    "relevancy_evaluator": ("GROUNDING.IRRELEVANT_CONTEXT", DecisionKind.SEMANTIC),
    "rag_retrieval_rating": ("GROUNDING.POOR_RETRIEVAL", DecisionKind.SEMANTIC),
    "rag_hallucination": ("GROUNDING.HALLUCINATION", DecisionKind.SEMANTIC),
    "rag_qa_correctness": ("QUALITY.INCORRECT_ANSWER", DecisionKind.SEMANTIC),
    "provenance_llm": ("GROUNDING.UNSUPPORTED", DecisionKind.SEMANTIC),
    "wiki_provenance": ("GROUNDING.UNSUPPORTED", DecisionKind.SEMANTIC),
}

#: Settings that make each judge runnable, and a check context it can use.
SETTINGS: dict[str, dict] = {
    "llm_critic": {"metrics": {"clarity": {"description": "Is it clear?", "threshold": 3}}},
    "response_evaluator": {"validation_question": "Does it give a date?"},
    "persona_consistency": {"persona_description": "A cheerful pirate who sells boats."},
    "saliency_check": {"topics": ["pricing", "delivery"]},
    "wiki_provenance": {"topic_name": "Apollo 11"},
}
CTX = CheckContext(
    surface="output",
    extra={"prompt": "When did Apollo 11 land?", "sources": ["Apollo 11 landed in 1969."]},
)
TEXT = "Apollo 11 landed on the Moon in 1969. It was crewed by three astronauts."


class FakeJudge:
    """Scores every question it is asked; records what it was sent."""

    def __init__(self, score: float = 0.0, scores: dict[str, float] | None = None, drop=()):
        self.score = score
        self.scores = scores or {}
        self.drop = set(drop)
        self.calls: list[tuple[dict, dict]] = []

    def available(self) -> bool:
        return True

    def ask(self, state, questions):
        self.calls.append((state, questions))
        return JevResult(
            answers={
                q: JevAnswer(q, "noul", self.scores.get(q, self.score), 1.0)
                for q in questions
                if q not in self.drop
            }
        )


class DownJudge(FakeJudge):
    def ask(self, state, questions):
        raise JevUnavailable("service down")


@pytest.fixture
def tiers_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "judgment_tiers", ["deterministic", "jev"])
    monkeypatch.setattr(s, "allow_egress", True)


@pytest.fixture
def seat(monkeypatch, tiers_on):
    """Put a judge on the panel for every decision kind."""

    def _seat(judge):
        monkeypatch.setattr(panel, "judges_for", lambda kind: [(Tier.JEV, judge)])
        return judge

    return _seat


@pytest.fixture(autouse=True)
def no_wikipedia(monkeypatch):
    judges.wikipedia_page.cache_clear()

    def fake(params):
        if params.get("list") == "search":
            return {"query": {"search": [{"title": "Apollo 11"}]}}
        return {"query": {"pages": {"1": {"extract": "Apollo 11 landed on the Moon in 1969."}}}}

    monkeypatch.setattr(judges, "_wiki_get", fake)


# --- registration -----------------------------------------------------------
@pytest.mark.parametrize("name", sorted(JUDGES))
def test_registered_as_a_judge(name) -> None:
    v = get_validator(name)
    assert v is not None
    entity, decision = JUDGES[name]
    assert v.kind == "judge"
    assert v.entity_type == entity
    assert v.decision_kind is decision
    assert v.upstream and v.upstream.startswith("guardrails-ai/")
    assert v.requires_budget_ms and v.timeout_ms
    for q in v.questions(TEXT, v.params(SETTINGS.get(name)), CTX).values():
        assert q["type"] == "noul"
        assert q["criteria"]["what"] and q["criteria"]["not_for"]


def test_the_summary_match_is_a_rule() -> None:
    v = get_validator("extracted_summary_sentences_match")
    assert v is not None and v.kind == "rule"
    assert v.available()


# --- settings ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("llm_critic", {}),
        ("llm_critic", {"metrics": {"x": {"description": "d", "threshold": 9}}}),
        ("response_evaluator", {}),
        ("persona_consistency", {}),
        ("saliency_check", {}),
        ("wiki_provenance", {}),
        ("toxic_language_llm", {"validation_method": "paragraph"}),
        ("politeness_check", {"threshold": 1.5}),
        ("politeness_check", {"llm_callable": "gpt-3.5-turbo"}),
        ("rag_retrieval_rating", {"min_range_value": 5, "max_range_value": 1}),
    ],
)
def test_bad_settings_are_refused(name, raw) -> None:
    with pytest.raises(ValueError, match=name):
        get_validator(name).params(raw)


def test_good_settings_are_accepted() -> None:
    for name, raw in SETTINGS.items():
        get_validator(name).params(raw)
    assert get_validator("prompt_injection_llm").params().threshold == 0.8


# --- availability ------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(JUDGES))
def test_off_with_a_reason_when_no_tier_is_enabled(name) -> None:
    v = get_validator(name)
    assert v.available() is False
    assert v.unavailable_reason()
    assert v.describe()["unavailable_reason"]


def test_the_reason_names_the_setting() -> None:
    assert "judgment_tiers" in get_validator("politeness_check").unavailable_reason()


def test_on_once_a_tier_is_enabled_and_reachable(seat) -> None:
    seat(FakeJudge())
    assert get_validator("politeness_check").available() is True
    assert get_validator("unusual_prompt").available() is True


def test_a_supplied_judge_cannot_get_round_the_routing_table(monkeypatch) -> None:
    monkeypatch.setattr(panel, "judges_for", lambda kind: [(Tier.JEV, FakeJudge())])
    assert get_validator("politeness_check").available() is False


def test_wikipedia_needs_egress_as_well(monkeypatch, seat) -> None:
    seat(FakeJudge())
    v = get_validator("wiki_provenance")
    assert v.available() is True
    monkeypatch.setattr(get_settings(), "allow_egress", False)
    assert v.available() is False
    assert "allow_egress" in v.unavailable_reason()


# --- findings ----------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(JUDGES))
def test_high_score_finds_low_score_does_not(name, seat) -> None:
    v = get_validator(name)
    params = v.params(SETTINGS.get(name))
    high = 0.0 if name == "saliency_check" else 0.95  # saliency asks "is it covered"
    low = 1.0 - high
    seat(FakeJudge(score=high))
    found = v.check(TEXT, params, CTX)
    assert found and all(0.0 <= f.score <= 1.0 for f in found)
    seat(FakeJudge(score=low))
    assert v.check(TEXT, params, CTX) == []


def test_the_threshold_is_the_bar(seat) -> None:
    v = get_validator("politeness_check")
    seat(FakeJudge(score=0.6))
    assert v.check("Whatever.", v.params({"threshold": 0.6}), CTX)[0].score == 0.6
    assert v.check("Whatever.", v.params({"threshold": 0.61}), CTX) == []


def test_sentence_mode_reports_the_sentence(seat) -> None:
    v = get_validator("toxic_language_llm")
    text = "Thanks for asking. You are an idiot. Have a nice day."
    judge = seat(FakeJudge(scores={"s1": 0.9}))
    [finding] = v.check(text, v.params(), CTX)
    assert text[finding.start : finding.end] == "You are an idiot."
    assert judge.calls[0][0]["sentences"]["s1"] == "You are an idiot."


def test_full_mode_names_the_categories(seat) -> None:
    v = get_validator("toxic_language_llm")
    seat(FakeJudge(scores={"threat": 0.8, "insult": 0.7}))
    [finding] = v.check("x y z", v.params({"validation_method": "full"}), CTX)
    assert finding.detail["categories"] == ["insult", "threat"]


def test_the_prompt_reaches_the_judge(seat) -> None:
    judge = seat(FakeJudge())
    v = get_validator("responsiveness_check")
    v.check(TEXT, v.params(), CTX)
    assert judge.calls[0][0]["prompt"] == "When did Apollo 11 land?"
    v.check(TEXT, v.params({"prompt": "From settings"}), CheckContext())
    assert judge.calls[1][0]["prompt"] == "From settings"


def test_a_missing_prompt_is_an_error_not_a_pass(seat) -> None:
    seat(FakeJudge())
    v = get_validator("qa_relevance_llm_eval")
    with pytest.raises(ValueError, match="prompt"):
        v.check(TEXT, v.params(), CheckContext())


def test_provenance_sends_the_sources(seat) -> None:
    judge = seat(FakeJudge(scores={"s1": 0.9}))
    v = get_validator("provenance_llm")
    [finding] = v.check(TEXT, v.params(), CTX)
    assert "1969" in judge.calls[0][0]["sources"]
    assert TEXT[finding.start : finding.end].startswith("It was crewed")


def test_llm_critic_scales_to_max_score(seat) -> None:
    v = get_validator("llm_critic")
    params = v.params(SETTINGS["llm_critic"])
    seat(FakeJudge(score=0.5))  # rating 2.5 of 5, bar 3
    [finding] = v.check(TEXT, params, CTX)
    assert finding.detail["metric"] == "clarity"
    assert finding.detail["rating"] == 2.5
    seat(FakeJudge(score=0.2))  # rating 4.0
    assert v.check(TEXT, params, CTX) == []


def test_wiki_provenance_judges_against_the_article(seat) -> None:
    judge = seat(FakeJudge(score=0.9))
    v = get_validator("wiki_provenance")
    found = v.check(TEXT, v.params(SETTINGS["wiki_provenance"]), CTX)
    assert found and found[0].detail["topic"] == "Apollo 11"
    assert "landed on the Moon" in judge.calls[0][0]["sources"]


def test_empty_text_is_not_a_call(seat) -> None:
    judge = seat(FakeJudge(score=1.0))
    v = get_validator("politeness_check")
    assert v.check("   ", v.params(), CTX) == []
    assert judge.calls == []


# --- failing visibly ------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(JUDGES))
def test_no_judge_is_an_error_not_clean(name, tiers_on, monkeypatch) -> None:
    monkeypatch.setattr(panel, "judges_for", lambda kind: [])
    v = get_validator(name)
    with pytest.raises(JevUnavailable):
        v.check(TEXT, v.params(SETTINGS.get(name)), CTX)


def test_an_outage_is_an_error_not_clean(seat) -> None:
    seat(DownJudge())
    v = get_validator("unusual_prompt")
    with pytest.raises(JevUnavailable, match="service down"):
        v.check("hello", v.params(), CTX)


def test_an_unanswered_question_is_an_error(seat) -> None:
    seat(FakeJudge(score=0.0, drop={"impolite"}))
    v = get_validator("politeness_check")
    with pytest.raises(JevUnavailable, match="impolite"):
        v.check("hello", v.params(), CTX)


def test_pass_on_invalid_covers_a_missing_answer_only(seat) -> None:
    v = get_validator("response_evaluator")
    params = v.params({**SETTINGS["response_evaluator"], "pass_on_invalid": True})
    seat(FakeJudge(drop={"answer_is_no"}))
    assert v.check(TEXT, params, CTX) == []
    seat(DownJudge())
    with pytest.raises(JevUnavailable):
        v.check(TEXT, params, CTX)


# --- the rule ------------------------------------------------------------------------
def test_summary_sentences_match_the_sources() -> None:
    v = get_validator("extracted_summary_sentences_match")
    source = (
        "The council approved the budget on Monday. Spending on parks rises by ten "
        "percent. The vote was seven to two."
    )
    summary = "The council approved the budget on Monday. The mayor resigned in protest."
    [finding] = v.check(summary, v.params(), CheckContext(extra={"sources": [source]}))
    assert summary[finding.start : finding.end] == "The mayor resigned in protest."
    assert v.check(summary[:42], v.params({"sources": [source]}), CheckContext()) == []


def test_summary_match_needs_sources() -> None:
    v = get_validator("extracted_summary_sentences_match")
    with pytest.raises(ValueError, match="sources"):
        v.check("Some summary.", v.params(), CheckContext())
