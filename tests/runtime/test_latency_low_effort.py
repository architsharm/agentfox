"""The low-effort latency fixes from the 2026-10-27 guard latency study.

Each test pins one behaviour the study found missing: a judge reply wrapped in
markdown is read, and a reply that cannot be read is not an outage; the request path
answers from the probe cache instead of probing inline; the classifier scores long
text in windows over all of it (an injection in the middle is still read).
"""

from __future__ import annotations

import datetime as dt
import threading

import pytest

from agentfox.capabilities.detection.adapters import classifiers
from agentfox.capabilities.judgment import llm
from agentfox.capabilities.judgment.jev import MALFORMED, OUTAGE, JevUnavailable, cause_of
from agentfox.runtime import availability

QUESTIONS = {"personal_data": {}, "injection": {}}


@pytest.mark.parametrize(
    "reply",
    [
        "personal_data: 12\ninjection: 90",
        "**personal_data**: 12\n**injection**: 90",
        "`personal_data`: 12\n`injection`: 90",
        '```json\n{"personal_data": 12, "injection": 90}\n```',
        "- personal_data = 12%\n- injection = 90%",
    ],
)
def test_the_judge_reads_the_wrappers_models_put_around_scores(reply):
    answers = llm._parse(reply, QUESTIONS)
    assert {k: v.value for k, v in answers.items()} == {"personal_data": 0.12, "injection": 0.9}


def test_an_unreadable_judge_reply_is_malformed_not_an_outage():
    exc = JevUnavailable("judge returned no parseable scores", cause=MALFORMED)
    assert cause_of(exc) == MALFORMED != OUTAGE


def test_the_request_path_answers_from_the_probe_cache(monkeypatch):
    calls = threading.Event()

    def probe():
        calls.set()
        return "down"

    monkeypatch.setattr(availability, "_PROBES", {"database": probe})
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
    monkeypatch.setattr(availability, "_PROBE_CACHE", {"database": (stale, "")})
    # Stale: the last known answer stands, and one refresh starts in the background.
    assert availability.probe_services(block=False) == {}
    assert calls.wait(5)
    # The first time ever there is nothing cached, so it probes inline.
    monkeypatch.setattr(availability, "_PROBE_CACHE", {})
    assert availability.probe_services(block=False) == {"database": "down"}


class _Tokenizer:
    """One token per word."""

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": text.split()}

    def decode(self, ids):
        return " ".join(ids)


class _Pipe:
    tokenizer = _Tokenizer()

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, texts):
        batch = texts if isinstance(texts, list) else [texts]
        self.seen.extend(batch)
        rows = [[{"label": "INJECTION", "score": 0.99 if "IGNORE" in t else 0.01}] for t in batch]
        return rows if isinstance(texts, list) else rows


def test_long_text_is_scored_in_windows_over_all_of_it(monkeypatch):
    monkeypatch.setattr(classifiers, "WINDOW_TOKENS", 10)
    monkeypatch.setattr(classifiers, "WINDOW_OVERLAP", 2)
    pipe = _Pipe()
    text = " ".join(["word"] * 20 + ["IGNORE"] + ["word"] * 20)  # in the middle
    rows = classifiers._scored(pipe, text)
    assert max(r["score"] for r in rows) == 0.99
    assert len(pipe.seen) > 2  # more than a head and a tail
    assert all(len(w.split()) <= 10 for w in pipe.seen)


def test_short_text_is_scored_whole(monkeypatch):
    pipe = _Pipe()
    classifiers._scored(pipe, "what is the refund window")
    assert pipe.seen == ["what is the refund window"]


class _Judge:
    """A judge that answered, but off-format (or, with OUTAGE, did not answer)."""

    key = "injection.judgment"
    version = "1"
    surfaces = ("input",)
    timeout_ms = 1000

    def __init__(self, cause):
        self.cause = cause

    def available(self):
        return True

    def detect(self, content, context):
        from agentfox.capabilities.detection.base import DetectorResult

        return DetectorResult(
            self.key, self.version, status="unavailable", raw={"cause": self.cause}
        )


def test_an_off_format_judge_reply_degrades_but_is_not_an_outage():
    """An input crafted to make the judge answer unparseably must not switch the judge
    off unseen: it is degraded (fail_mode sees it), but not a judge outage (no
    fail_closed block on a healthy judge). A real outage stays both."""
    from agentfox.capabilities.detection.base import DetectionContext
    from agentfox.capabilities.detection.pipeline import DetectorPipeline

    malformed = DetectorPipeline([_Judge(MALFORMED)]).run("x", DetectionContext(surface="input"))
    assert malformed.degraded == ["injection.judgment"]
    assert malformed.judge_outage == {}
    outage = DetectorPipeline([_Judge(OUTAGE)]).run("x", DetectionContext(surface="input"))
    assert outage.degraded == ["injection.judgment"]
    assert "injection.judgment" in outage.judge_outage


def test_the_commitment_judge_asked_early_is_not_asked_again(monkeypatch):
    """An output check starts the commitment judge in parallel with its detectors;
    the content check then uses that answer instead of asking a second time."""
    from agentfox.capabilities.judgment import commitments
    from agentfox.capabilities.judgment.jev import JevAnswer

    asked: list[str] = []

    def fake_ask(state, questions, gateway):
        asked.append(state["reply"])
        return {q: JevAnswer(q, "noul", 0.9, 0.8) for q in questions}

    monkeypatch.setattr(commitments, "_ask", fake_ask)
    monkeypatch.setattr(commitments, "enabled", lambda gateway=None: True)
    reply = "That has been taken care of for you, nothing more to do on your side."
    commitments.prefetch(reply)
    found = commitments.augment([], reply)
    assert asked == [reply]  # once, and early
    assert found and all(c.kind == "implied" for c in found)
