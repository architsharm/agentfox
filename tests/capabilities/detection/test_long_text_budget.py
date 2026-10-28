"""Long text gets a longer check budget, so the classifier finishes reading it.

On a CPU the injection classifier reads 200 to 600 characters in about 166 ms at the
median, and 22% of such checks ran out of the 300 ms budget and returned without its
verdict. Past `long_text_chars` its check may take up to `long_text_budget_ms`.
"""

from __future__ import annotations

import time

from agentfox.capabilities.detection.adapters.classifiers import (
    PromptInjectionClassifierDetector,
)
from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.pipeline import DetectorPipeline
from agentfox.core.config import get_settings


def _slow_classifier(seconds: float) -> PromptInjectionClassifierDetector:
    detector = PromptInjectionClassifierDetector(secondary_model_id=None)
    detector.available = lambda: True  # type: ignore[method-assign]

    def score(text):
        time.sleep(seconds)
        return [[{"label": "injection", "score": 0.99}, {"label": "safe", "score": 0.01}]]

    detector.__dict__["_pipeline"] = score
    return detector


def test_long_text_is_read_past_the_default_budget(monkeypatch):
    monkeypatch.setattr(get_settings(), "long_text_budget_ms", 1000)
    detector = _slow_classifier(0.4)  # longer than both the 250 ms timeout and 300 ms budget
    pipeline = DetectorPipeline([detector], budget_ms=300)
    result = pipeline.run("x" * 900, DetectionContext(surface="input"))
    run = next(r for r in result.results if r.detector_key == "injection.classifier")
    assert run.status == "ok" and run.detections
    assert result.budget_ms == 1000


def test_short_text_keeps_the_default_budget():
    detector = _slow_classifier(0.4)
    pipeline = DetectorPipeline([detector], budget_ms=300)
    result = pipeline.run("hello there", DetectionContext(surface="input"))
    run = next(r for r in result.results if r.detector_key == "injection.classifier")
    assert run.status == "timeout"
    assert result.budget_ms == 300


def test_the_threshold_is_a_setting(monkeypatch):
    monkeypatch.setattr(get_settings(), "long_text_chars", 2000)
    detector = PromptInjectionClassifierDetector(secondary_model_id=None)
    context = DetectionContext(surface="input", extra={"content_chars": 900})
    assert detector.budget_for(context) == 0
    assert detector.timeout_for(context) == detector.timeout_ms
