"""In-process entry points warm the opted-in model detectors (#48).

Only the gateway and the hooks daemon called `warm_all()`, so with `auto()` or the
SDK an enabled classifier loaded its weights inside the first real request and
timed out.
"""

from __future__ import annotations

import threading

import pytest

from agentfox.capabilities.detection import base as detection_base
from agentfox.capabilities.detection import warmup


class _Slow(detection_base.BaseDetector):
    key = "test.slow_model"

    def __init__(self) -> None:
        self.warmed = threading.Event()

    def warm(self) -> None:
        self.warmed.set()

    def _detect(self, content, context):
        return []


@pytest.fixture
def slow(monkeypatch):
    from agentfox.core.config import get_settings, reset_settings_cache

    detector = _Slow()
    monkeypatch.setitem(detection_base._REGISTRY, detector.key, detector)
    monkeypatch.setenv(
        "NOMETRIA_ENABLED_DETECTORS",
        '["injection.heuristic", "pii.native", "test.slow_model"]',
    )
    reset_settings_cache()
    assert "test.slow_model" in get_settings().enabled_detectors
    warmup._reset()
    yield detector
    warmup._reset()


@pytest.mark.parametrize("entry", ["auto", "sdk", "langgraph"])
def test_an_enabled_model_detector_is_warmed(slow, entry):
    if entry == "auto":
        from agentfox.frameworks.autoguard import auto, off

        auto(agent="warm-bot", quiet=True)
        off()
    elif entry == "sdk":
        from agentfox.frameworks.sdk import AgentFox

        AgentFox("warm-bot")
    else:
        from agentfox.frameworks.langgraph import AgentFoxGuard

        AgentFoxGuard(agent="warm-bot")
    assert slow.warmed.wait(5), f"{entry} did not warm the enabled detector"


def test_nothing_is_started_for_the_default_detectors():
    warmup._reset()
    assert warmup.warm_in_background() is None


def test_a_remote_client_does_not_warm(slow):
    from agentfox.frameworks.sdk import AgentFox

    AgentFox("warm-bot", base_url="http://gateway.invalid")
    assert not slow.warmed.wait(0.2)
