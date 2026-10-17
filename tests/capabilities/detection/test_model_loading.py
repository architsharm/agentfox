"""A model detector loads once and runs one forward pass at a time, under any burst.

Regression for two crashes found when `injection.classifier` became a default: the
first concurrent requests to a cold detector raced `transformers`' lazy import
(``ImportError: cannot import name 'pipeline'``) and built the model in several
threads at once, and concurrent forward passes on one model segfaulted the process.
Fakes stand in for the model so this runs without weights.
"""

from __future__ import annotations

import threading
import time

from agentfox.capabilities.detection.loading import inference_lock, load_once

THREADS = 16


def _burst(target) -> None:
    barrier = threading.Barrier(THREADS)

    def run() -> None:
        barrier.wait()
        target()

    threads = [threading.Thread(target=run) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_a_burst_of_first_requests_loads_the_model_once():
    loads = []

    class Detector:
        @load_once
        def model(self):
            loads.append(1)
            time.sleep(0.05)  # long enough for every thread to arrive mid-load
            return object()

    detector = Detector()
    seen = []
    _burst(lambda: seen.append(detector.model))

    assert len(loads) == 1
    assert len({id(m) for m in seen}) == 1


def test_forward_passes_on_one_model_never_overlap():
    model = object.__new__(type("Model", (), {}))
    running = 0
    peak = 0
    guard = threading.Lock()

    def forward() -> None:
        nonlocal running, peak
        with inference_lock(model):
            with guard:
                running += 1
                peak = max(peak, running)
            time.sleep(0.005)
            with guard:
                running -= 1

    _burst(forward)
    assert peak == 1


def test_a_value_set_directly_wins_over_the_loader():
    """Tests (and callers) fake a model by writing the instance dict, as they did
    with `cached_property`; that must keep working."""

    class Detector:
        @load_once
        def model(self):
            raise AssertionError("should not load")

    detector = Detector()
    detector.__dict__["model"] = "fake"
    assert detector.model == "fake"
