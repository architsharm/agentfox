"""One per-detector timeout, and a detector cannot quietly tighten it.

Scoring ~7,000 messages through `DetectorPipeline(detector_timeout_ms=30000,
budget_ms=120000)`, 981 checks still came back without the injection classifier's
verdict under load: the classifier's own `timeout_ms = 250` replaced the configured
30 s instead of adding to it, so a caller who raised the timeout got 250 ms anyway,
and under `fail_mode=open` those messages were allowed on the heuristic alone.

The precedence (`pipeline.detector_allowance_ms`): the configured timeout, raised by
a detector's own declared need, capped by the run's budget.
"""

from __future__ import annotations

import time

from agentfox.capabilities.detection import remote
from agentfox.capabilities.detection.adapters.classifiers import (
    PromptInjectionClassifierDetector,
)
from agentfox.capabilities.detection.base import BaseDetector, DetectionContext
from agentfox.capabilities.detection.loading import CallScope, enter_scope
from agentfox.capabilities.detection.pipeline import DetectorPipeline, detector_allowance_ms
from agentfox.core.config import get_settings


def _slow_classifier(seconds: float) -> PromptInjectionClassifierDetector:
    detector = PromptInjectionClassifierDetector(secondary_model_id=None)
    detector.available = lambda: True  # type: ignore[method-assign]

    def score(text):
        time.sleep(seconds)
        return [[{"label": "injection", "score": 0.99}, {"label": "safe", "score": 0.01}]]

    detector.__dict__["_pipeline"] = score
    return detector


class _Slow(BaseDetector):
    key = "test.slow"
    version = "1"
    surfaces = ("input",)

    def __init__(self, seconds: float, timeout_ms: int | None) -> None:
        self.seconds = seconds
        self.timeout_ms = timeout_ms

    def _detect(self, content, context):
        time.sleep(self.seconds)
        return []


def _run(detector, **pipeline_kw):
    result = DetectorPipeline([detector], **pipeline_kw).run(
        "hello there", DetectionContext(surface="input")
    )
    return result, next(r for r in result.results if r.detector_key == detector.key)


def test_a_configured_timeout_above_the_classifiers_own_is_honoured():
    """The research run's case: 30 s configured, the model takes longer than 250 ms."""
    detector = _slow_classifier(0.4)
    assert detector.timeout_ms == 250
    result, run = _run(detector, detector_timeout_ms=2000, budget_ms=5000)
    assert run.status == "ok" and run.detections
    assert result.degraded == []


def test_a_declared_timeout_still_raises_a_smaller_configured_one():
    """The default install: 40 ms configured, the classifier gets its 250 ms."""
    detector = _slow_classifier(0.1)
    result, run = _run(detector, detector_timeout_ms=40, budget_ms=300)
    assert run.status == "ok"
    assert result.degraded == []


def test_a_detector_with_no_declared_timeout_gets_the_configured_one():
    result, run = _run(_Slow(0.2, None), detector_timeout_ms=30, budget_ms=1000)
    assert run.status == "timeout" and run.duration_ms == 30
    assert result.degraded == ["test.slow"]


def test_the_budget_caps_every_allowance():
    result, run = _run(_Slow(0.5, 2000), detector_timeout_ms=5000, budget_ms=100)
    assert run.status == "timeout" and run.duration_ms <= 100
    assert result.degraded == ["test.slow"]


def test_the_allowance_is_the_larger_of_configured_and_declared(monkeypatch):
    monkeypatch.setattr(get_settings(), "long_text_budget_ms", 1000)
    detector = PromptInjectionClassifierDetector(secondary_model_id=None)
    short = DetectionContext(surface="input", extra={"content_chars": 10})
    long = DetectionContext(surface="input", extra={"content_chars": 900})
    assert detector_allowance_ms(detector, short, 40) == 250
    assert detector_allowance_ms(detector, short, 30000) == 30000
    assert detector_allowance_ms(detector, long, 40) == 1000
    assert detector_allowance_ms(detector, long, 30000) == 30000
    assert detector_allowance_ms(_Slow(0, None), short, 40) == 40


def test_the_model_server_stand_in_adds_the_round_trip_to_a_request_dependent_need(
    monkeypatch,
):
    """`RemoteDetector` forwarded `timeout_for` to the local detector, so the pipeline
    never added `NETWORK_ALLOWANCE_MS` for a remote classifier."""
    monkeypatch.setattr(get_settings(), "long_text_budget_ms", 1000)
    proxy = remote.RemoteDetector(PromptInjectionClassifierDetector(secondary_model_id=None))
    short = DetectionContext(surface="input", extra={"content_chars": 10})
    long = DetectionContext(surface="input", extra={"content_chars": 900})
    assert proxy.timeout_for(short) == 250 + remote.NETWORK_ALLOWANCE_MS
    assert proxy.timeout_for(long) == 1000 + remote.NETWORK_ALLOWANCE_MS
    assert detector_allowance_ms(proxy, short, 30000) == 30000


def test_the_model_server_request_lasts_as_long_as_the_pipeline_waits():
    """Its HTTP timeout was fixed at the model's own 250 ms + 50 ms whatever the
    pipeline was configured to wait; it now follows the call's deadline."""
    proxy = remote.RemoteDetector(PromptInjectionClassifierDetector(secondary_model_id=None))
    try:
        enter_scope(None)
        assert proxy._http_timeout_s() == (250 + remote.NETWORK_ALLOWANCE_MS) / 1000
        enter_scope(CallScope(time.perf_counter() + 30))
        assert 29 < proxy._http_timeout_s() <= 30
    finally:
        enter_scope(None)
