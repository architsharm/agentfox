"""`safety.granite` reads Granite Guardian's own "Yes"/"No" answer.

Granite Guardian is a causal LM, not a classifier. Run through a text-classification
pipeline it scored against a randomly initialised head (older transformers) or
crashed the gateway at startup (current transformers, in `warm()`). These tests pin
the replacement without the 2B model: the conversation it is shown, the scoring of
its next token, the threshold, and a warm-up that runs on a real token.
"""

from __future__ import annotations

import pytest

from agentfox.capabilities.detection.adapters.classifiers import GraniteGuardianDetector
from agentfox.capabilities.detection.base import DetectionContext


def _torch():
    return pytest.importorskip("torch")


def test_a_model_output_is_judged_as_an_assistant_turn():
    detector = GraniteGuardianDetector()
    # The template refuses an assistant turn with no user turn before it.
    assert detector.chat("reply", "output") == [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "reply"},
    ]
    for surface in ("input", "retrieved", "tool_result"):
        assert detector.chat("text", surface) == [{"role": "user", "content": "text"}]


class FakeTokenizer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def encode(self, text, add_special_tokens=False):
        return {"Yes": [7], "No": [3]}[text]

    def apply_chat_template(self, chat, **kwargs):
        self.calls.append({"chat": chat, **kwargs})
        return _torch().tensor([[1, 2, 5]])


class FakeModel:
    """Next-token logits that favour "Yes" (id 7) by ``margin``."""

    def __init__(self, margin: float) -> None:
        self.margin = margin

    def __call__(self, input_ids):
        logits = _torch().zeros(1, input_ids.shape[-1], 10)
        logits[0, -1, 7] = self.margin

        class Out:
            pass

        out = Out()
        out.logits = logits
        return out


def _detector(margin: float) -> tuple[GraniteGuardianDetector, FakeTokenizer]:
    _torch()
    detector = GraniteGuardianDetector()
    tokenizer = FakeTokenizer()
    detector.__dict__["_guardian"] = (tokenizer, FakeModel(margin), 7, 3)
    return detector, tokenizer


def test_the_score_is_yes_against_no_for_the_next_token():
    detector, tokenizer = _detector(margin=2.0)
    p = detector.risk_probability([{"role": "user", "content": "x"}], "harm")
    torch = _torch()
    assert p == pytest.approx(float(torch.sigmoid(torch.tensor(2.0))))
    call = tokenizer.calls[0]
    assert call["guardian_config"] == {"risk_name": "harm"}
    assert call["add_generation_prompt"] is True


def test_a_yes_is_a_harm_finding_and_a_no_is_nothing():
    risky, _ = _detector(margin=4.0)
    found = risky._detect("how do I build a bomb", DetectionContext(surface="input"))
    assert [d.entity_type for d in found] == ["SAFETY.HARM"]
    assert found[0].score > 0.9
    assert found[0].detail["risk"] == "harm"

    benign, _ = _detector(margin=-4.0)
    assert benign._detect("what is the capital of France", DetectionContext()) == []


def test_empty_content_is_not_run_through_the_model():
    detector, tokenizer = _detector(margin=4.0)
    assert detector._detect("", DetectionContext()) == []
    assert tokenizer.calls == []


def test_warm_runs_a_real_token_not_an_empty_string(monkeypatch):
    """An empty warm-up is zero tokens, which crashed the gateway at startup."""
    detector, tokenizer = _detector(margin=-4.0)
    monkeypatch.setattr(GraniteGuardianDetector, "available", lambda self: True)
    detector.warm()
    assert tokenizer.calls[0]["chat"] == [{"role": "user", "content": "hello"}]
