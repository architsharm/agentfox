"""A model still loading in the background never holds up a check or the exit.

With `pip install 'agentfox[classifiers]'` and the model pulled, a short script under
`agentfox.auto()` took 18-51 s and ended with a ~40-line "cannot schedule new futures
after interpreter shutdown" traceback: the first check queued behind the background
load, timed out (a `budget_breach`), and its pool thread, which the interpreter joins
at exit, stayed blocked until the load gave up. Fakes stand in for the model.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from agentfox.capabilities.detection import base as detection_base
from agentfox.capabilities.detection import warmup
from agentfox.capabilities.detection.base import Detection, DetectionContext
from agentfox.capabilities.detection.loading import load_once
from agentfox.capabilities.detection.pipeline import DetectorPipeline


class _Loading(detection_base.BaseDetector):
    key = "test.loading_model"
    surfaces = ("input",)
    timeout_ms = 250

    def __init__(self) -> None:
        self.release = threading.Event()

    def available(self) -> bool:
        return True

    @load_once
    def _model(self):
        self.release.wait(10)
        return object()

    def warm(self) -> None:
        self._model  # noqa: B018 - loading is the point

    def _detect(self, content, context):
        self._model  # noqa: B018
        return [Detection(entity_type="INJECTION.JAILBREAK", score=0.9, end=len(content))]


@pytest.fixture
def loading(monkeypatch):
    from agentfox.core.config import reset_settings_cache

    detector = _Loading()
    monkeypatch.setitem(detection_base._REGISTRY, detector.key, detector)
    monkeypatch.setenv("AGENTFOX_ENABLED_DETECTORS", f'["{detector.key}"]')
    reset_settings_cache()
    warmup._reset()
    yield detector
    detector.release.set()
    warmup._reset()
    reset_settings_cache()


def test_a_check_does_not_wait_for_a_model_still_loading(loading):
    thread = warmup.warm_in_background()
    assert thread is not None and warmup.warming(loading.key)

    started = time.perf_counter()
    result = DetectorPipeline(detectors=[loading]).run("hi", DetectionContext(surface="input"))
    elapsed = time.perf_counter() - started

    assert elapsed < 0.2, f"waited {elapsed:.2f}s for a model that was still loading"
    [run] = result.results
    assert (run.status, run.raw.get("cause")) == ("unavailable", warmup.WARMING)
    # Not slow or broken, only not loaded yet: no `budget_breach`, no fail_mode block.
    assert result.degraded == []


def test_once_loaded_the_check_uses_the_model(loading):
    thread = warmup.warm_in_background()
    loading.release.set()
    thread.join(5)
    assert not warmup.warming(loading.key)

    result = DetectorPipeline(detectors=[loading]).run("hi", DetectionContext(surface="input"))

    assert [d.entity_type for d in result.detections] == ["INJECTION.JAILBREAK"]


def test_warm_now_waits_for_the_background_load(loading):
    warmup.warm_in_background()
    threading.Timer(0.1, loading.release.set).start()

    warmup.warm_now()

    assert not warmup.warming(loading.key)


def test_a_failed_warm_up_says_one_line(monkeypatch, caplog):
    class Broken(_Loading):
        def warm(self) -> None:
            raise OSError("Could not load model x\n\nTraceback (most recent call last):\n  ...")

    warmup._reset()
    warmup._warm([Broken()])

    assert "could not warm detector test.loading_model: Could not load model x" in caplog.text
    assert "Traceback" not in caplog.text


_SCRIPT = textwrap.dedent(
    """
    import logging, sys, threading, time
    from concurrent.futures import ThreadPoolExecutor

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    from agentfox.capabilities.detection import base, warmup
    from agentfox.capabilities.detection.base import DetectionContext
    from agentfox.capabilities.detection.loading import load_once
    from agentfox.capabilities.detection.pipeline import DetectorPipeline

    class Model(base.BaseDetector):
        key = "test.slow_model"
        surfaces = ("input",)
        timeout_ms = 250

        def available(self):
            return True

        @load_once
        def _model(self):
            # Like transformers: the weights load through a thread pool, which stops
            # taking work once the interpreter begins to shut down.
            pool = ThreadPoolExecutor(1)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                pool.submit(time.sleep, 0.01).result()
            return object()

        def warm(self):
            self._model

        def _detect(self, content, context):
            self._model
            return []

    detector = Model()
    base._REGISTRY[detector.key] = detector
    warmup.warm_in_background()
    result = DetectorPipeline(detectors=[detector]).run("hi", DetectionContext(surface="input"))
    print("checked", result.results[0].status, result.degraded)
    """
)


def test_a_short_script_exits_at_once_and_quietly(tmp_path):
    env = {
        **os.environ,
        "AGENTFOX_STATE_DIR": str(tmp_path),
        "AGENTFOX_ENABLED_DETECTORS": '["test.slow_model"]',
        "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
    }
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=tmp_path,
    )
    elapsed = time.monotonic() - started

    assert done.returncode == 0, done.stderr
    assert "checked unavailable []" in done.stdout
    assert "cannot schedule new futures" not in done.stderr
    assert "Traceback" not in done.stderr
    assert elapsed < 20, f"exit waited {elapsed:.1f}s on the background load"


def test_an_attack_test_loads_the_model_before_its_first_probe(seeded, monkeypatch):
    """Checks no longer wait for a loading model, so a campaign (many checks in a row)
    loads it first; otherwise every probe would run without it."""
    from agentfox.capabilities.evaluation import run_campaign

    calls = []
    monkeypatch.setattr(warmup, "warm_now", lambda: calls.append(1))

    run_campaign(seeded, "support-triage", probes=[])

    assert calls == [1]


def test_a_model_warm_all_loaded_is_not_warmed_again_in_the_background(loading):
    """`warm_all()` then `AgentFox(...)`: the check must use the model it waited for."""
    loading.release.set()
    detection_base.warm_all()

    assert warmup.warm_in_background() is None
    assert not warmup.warming(loading.key)


def test_without_the_classifier_the_warning_says_blocking_is_pattern_only(caplog):
    """The default install blocks on the heuristic alone; it says so where it says the
    classifier is skipped, next to the install command."""
    from agentfox.capabilities.detection.base import warn_unrunnable

    with caplog.at_level("WARNING"):
        missing = warn_unrunnable()
    if "injection.classifier" not in missing:
        pytest.skip("the classifier can run here")
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "blocked, by the pattern heuristic alone" in said


def test_warm_all_then_an_in_process_warm_up_says_it_once(monkeypatch):
    from agentfox.capabilities.detection import base

    said = []
    monkeypatch.setattr(base, "warn_unrunnable", lambda **kw: said.append(kw) or [])
    warmup._reset()
    base.warm_all()
    warmup._warm([])

    assert len(said) == 1
