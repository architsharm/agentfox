"""The LLM tier: a general model as a judge, and the panel that assembles tiers.

Two things need pinning. A general model returns prose unless held to a shape,
so the parser has to survive what models actually send. And `local_llm` must
be distinguishable from `llm` by something real — an endpoint on loopback —
rather than by a vendor's name, or the egress gate means nothing.
"""

from __future__ import annotations

import pytest

from agentfox.config import get_settings
from agentfox.judgment import JevUnavailable, LlmJudge, judges_for
from agentfox.judgment.capability import DecisionKind, Tier
from agentfox.judgment.llm import _parse
from agentfox.providers.base import CompletionRequest, CompletionResponse, register_provider

QUESTIONS = {
    "settles": {"type": "noul", "instructions": "settled?", "criteria": {"what": "x"}},
    "undertakes": {"type": "noul", "instructions": "undertaken?", "criteria": {"what": "y"}},
}


class FakeProvider:
    key = "fake-judge"
    version = "1"

    def __init__(self, text: str = "settles: 90\nundertakes: 10", fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.seen: list[CompletionRequest] = []

    def available(self) -> bool:
        return True

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if self.fail:
            raise RuntimeError("provider exploded")
        self.seen.append(request)
        return CompletionResponse(text=self.text, model="fake-1", provider=self.key)

    def stream(self, request):  # pragma: no cover - not used by the judge
        raise NotImplementedError

    def supports_native_streaming(self) -> bool:  # pragma: no cover
        return False


@pytest.fixture
def fake_provider(monkeypatch):
    provider = FakeProvider()
    register_provider(provider)
    s = get_settings()
    monkeypatch.setattr(s, "judgment_llm_provider", provider.key)
    monkeypatch.setattr(s, "allow_egress", True)
    return provider


# --- parsing what models actually send -----------------------------------
def test_it_parses_the_plain_shape() -> None:
    out = _parse("settles: 90\nundertakes: 10", QUESTIONS)
    assert out["settles"].value == pytest.approx(0.9)
    assert out["undertakes"].value == pytest.approx(0.1)


def test_it_survives_a_preamble_and_bullets() -> None:
    """Models add scaffolding no matter how the prompt is worded."""
    text = "Sure! Here are the scores:\n\n- settles: 85\n- undertakes = 5\n\nHope that helps."
    out = _parse(text, QUESTIONS)
    assert out["settles"].value == pytest.approx(0.85)
    assert out["undertakes"].value == pytest.approx(0.05)


def test_a_skipped_question_is_absent_not_zero() -> None:
    """Absent means 'no answer'; zero would mean 'confidently no'."""
    out = _parse("settles: 70", QUESTIONS)
    assert "settles" in out and "undertakes" not in out


def test_out_of_range_scores_are_clamped() -> None:
    out = _parse("settles: 150\nundertakes: 0", QUESTIONS)
    assert out["settles"].value == 1.0


def test_prose_with_no_scores_yields_nothing() -> None:
    assert _parse("I cannot answer that.", QUESTIONS) == {}


# --- the judge -----------------------------------------------------------
def test_it_asks_through_the_provider_interface(fake_provider) -> None:
    result = LlmJudge().ask({"reply": "that's sorted"}, QUESTIONS)
    assert result.answers["settles"].value == pytest.approx(0.9)
    assert len(fake_provider.seen) == 1  # one completion for every question


def test_it_does_not_send_the_literal_model_name_default(fake_provider) -> None:
    """`CompletionRequest.model` defaults to "default", which 404s upstream."""
    LlmJudge().ask({"reply": "x"}, QUESTIONS)
    assert fake_provider.seen[0].model != "default"


def test_a_provider_failure_is_unavailable_not_a_verdict(fake_provider, monkeypatch) -> None:
    fake_provider.fail = True
    with pytest.raises(JevUnavailable):
        LlmJudge().ask({"reply": "x"}, QUESTIONS)


def test_unparseable_output_is_unavailable_not_a_verdict(fake_provider) -> None:
    fake_provider.text = "I'd rather not score this."
    with pytest.raises(JevUnavailable):
        LlmJudge().ask({"reply": "x"}, QUESTIONS)


def test_echo_cannot_judge(monkeypatch) -> None:
    """The keyless offline default exists to run the stack, not to judge."""
    s = get_settings()
    monkeypatch.setattr(s, "judgment_llm_provider", "echo")
    assert LlmJudge().available() is False


# --- local versus hosted, which is what the egress gate turns on ---------
@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:11434", Tier.LOCAL_LLM),
        ("http://127.0.0.1:8000/v1", Tier.LOCAL_LLM),
        ("http://vllm.localhost:8000", Tier.LOCAL_LLM),
        ("https://api.some-vendor.com/v1", Tier.LLM),
        (None, Tier.LLM),
    ],
)
def test_locality_comes_from_the_endpoint_not_the_vendor(monkeypatch, url, expected) -> None:
    monkeypatch.setattr(get_settings(), "litellm_base_url", url)
    assert LlmJudge().tier() is expected


def test_an_unknown_endpoint_is_treated_as_egress(monkeypatch) -> None:
    """Fails safe: not provably local means gated."""
    monkeypatch.setattr(get_settings(), "litellm_base_url", "garbage-not-a-url")
    assert LlmJudge().tier() is Tier.LLM


# --- the panel -----------------------------------------------------------
def test_the_panel_is_empty_with_no_tiers_enabled(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "judgment_tiers", ["deterministic"])
    assert judges_for(DecisionKind.SEMANTIC) == []


def test_the_panel_picks_up_the_llm_tier(fake_provider, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "judgment_tiers", ["deterministic", "llm"])
    monkeypatch.setattr(get_settings(), "litellm_base_url", None)
    tiers = [t for t, _ in judges_for(DecisionKind.SEMANTIC)]
    assert Tier.LLM in tiers


def test_the_panel_never_assembles_a_tier_for_a_forbidden_kind(fake_provider, monkeypatch) -> None:
    """Structural work stays with code however many tiers are configured."""
    monkeypatch.setattr(get_settings(), "judgment_tiers", ["deterministic", "jev", "llm"])
    assert judges_for(DecisionKind.STRUCTURAL_PARSED) == []
    assert judges_for(DecisionKind.STRUCTURAL_GRANT) == []


# --- the cascade: the expensive tier should mostly not be called ---------
class CountingJudge:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls: list[dict] = []

    def available(self) -> bool:
        return True

    def ask(self, state, questions):
        from agentfox.judgment.jev import JevAnswer, JevResult

        self.calls.append(dict(questions))
        return JevResult(
            answers={
                q: JevAnswer(q, "noul", self.scores.get(q, 0.5), 1.0)
                for q in questions
                if q in self.scores
            }
        )


def test_a_decisive_cheap_answer_never_reaches_the_expensive_tier() -> None:
    """The whole point: stop paying once the question is settled."""
    from agentfox.judgment import panel
    from agentfox.judgment.capability import DecisionKind

    cheap = CountingJudge({"settles": 0.97})  # outside the band -> decisive
    dear = CountingJudge({"settles": 0.5})
    out = panel.ask(
        DecisionKind.PATTERN_OPEN,
        {"content": "x"},
        {"settles": QUESTIONS["settles"]},
        panel=[(Tier.JEV, cheap), (Tier.LLM, dear)],
    )
    assert out.answers["settles"].value == pytest.approx(0.97)
    assert dear.calls == []  # never called
    assert out.consulted == (Tier.JEV,)


def test_an_uncertain_answer_is_carried_to_the_next_tier() -> None:
    from agentfox.judgment import panel
    from agentfox.judgment.capability import DecisionKind

    cheap = CountingJudge({"settles": 0.5})  # inside the band -> unsettled
    dear = CountingJudge({"settles": 0.95})
    out = panel.ask(
        DecisionKind.PATTERN_OPEN,
        {"content": "x"},
        {"settles": QUESTIONS["settles"]},
        panel=[(Tier.JEV, cheap), (Tier.LLM, dear)],
    )
    assert out.answers["settles"].value == pytest.approx(0.95)
    assert out.consulted == (Tier.JEV, Tier.LLM)


def test_only_the_unsettled_questions_are_carried() -> None:
    """A mixed batch sends the expensive tier the remainder, not the lot."""
    from agentfox.judgment import panel
    from agentfox.judgment.capability import DecisionKind

    cheap = CountingJudge({"settles": 0.98, "undertakes": 0.5})
    dear = CountingJudge({"undertakes": 0.9})
    out = panel.ask(
        DecisionKind.PATTERN_OPEN,
        {"content": "x"},
        QUESTIONS,
        panel=[(Tier.JEV, cheap), (Tier.LLM, dear)],
    )
    assert list(dear.calls[0]) == ["undertakes"]  # the settled one is not re-asked
    assert out.answers["settles"].value == pytest.approx(0.98)
    assert out.answers["undertakes"].value == pytest.approx(0.9)


def test_one_tier_failing_degrades_to_the_next() -> None:
    from agentfox.judgment import panel
    from agentfox.judgment.capability import DecisionKind

    class Broken:
        def available(self):
            return True

        def ask(self, state, questions):
            raise JevUnavailable("down")

    dear = CountingJudge({"settles": 0.9})
    out = panel.ask(
        DecisionKind.PATTERN_OPEN,
        {"content": "x"},
        {"settles": QUESTIONS["settles"]},
        panel=[(Tier.JEV, Broken()), (Tier.LLM, dear)],
    )
    assert out.answers["settles"].value == pytest.approx(0.9)
    assert Tier.JEV in out.failures
