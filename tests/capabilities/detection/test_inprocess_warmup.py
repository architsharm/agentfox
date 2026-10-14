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
        "AGENTFOX_ENABLED_DETECTORS",
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


# ---------------------------------------------------------------------------
# `warm_all()`, the gateway's and the hooks daemon's startup warm-up.
# ---------------------------------------------------------------------------


class _Present(detection_base.BaseDetector):
    """A detector whose weights are on disk, as every model's are in the gateway
    image, whether or not anything has enabled it."""

    def __init__(self, key: str, fails: bool = False) -> None:
        self.key = key
        self.fails = fails
        self.warmed = False

    def available(self) -> bool:
        return True

    def warm(self) -> None:
        if self.fails:
            raise RuntimeError("cannot reshape tensor of 0 elements")
        self.warmed = True

    def _detect(self, content, context):
        return []


@pytest.fixture
def present(monkeypatch):
    from agentfox.core.config import reset_settings_cache

    detectors = {key: _Present(key) for key in ("test.enabled", "test.idle", "test.opted_in")}
    for key, detector in detectors.items():
        monkeypatch.setitem(detection_base._REGISTRY, key, detector)
    monkeypatch.setenv("AGENTFOX_ENABLED_DETECTORS", '["injection.heuristic", "test.enabled"]')
    reset_settings_cache()
    yield detectors
    reset_settings_cache()


def test_startup_warms_what_can_be_called_not_whatever_has_weights(present):
    """The gateway image carries Granite Guardian's weights with the detector off.
    Warming every detector with weights loaded about 10GB at each boot for nothing."""
    detection_base.warm_all()

    assert present["test.enabled"].warmed
    assert not present["test.idle"].warmed


def test_startup_warms_a_detector_a_workspace_switched_on(present, session):
    from agentfox.capabilities.detection.detector_settings import set_enabled

    set_enabled(session, "test.opted_in", True, actor="admin@example.com", reason="test")
    session.commit()

    detection_base.warm_all()

    assert present["test.opted_in"].warmed
    assert not present["test.idle"].warmed


def test_without_the_database_startup_warms_the_deployments_list(present, monkeypatch):
    from agentfox.capabilities.detection import detector_settings

    def unreadable(session):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(detector_settings, "enabled_anywhere", unreadable)

    detection_base.warm_all()

    assert present["test.enabled"].warmed
    assert not present["test.idle"].warmed


def test_one_detector_failing_to_warm_does_not_stop_the_others(present, monkeypatch, caplog):
    """`warm_all()` runs in the gateway's startup, where Granite Guardian's warm-up
    crash took the whole gateway down. A broken detector should stay cold instead."""
    from agentfox.core.config import reset_settings_cache

    present["test.idle"].fails = True
    monkeypatch.setenv("AGENTFOX_ENABLED_DETECTORS", '["test.enabled", "test.idle"]')
    reset_settings_cache()

    detection_base.warm_all()

    assert present["test.enabled"].warmed
    assert "test.idle failed to warm" in caplog.text
