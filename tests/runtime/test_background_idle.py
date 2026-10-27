"""Background work (the classifier's advisory backstop) waits for an idle gateway,
so it never shares the CPU with a live check."""

from __future__ import annotations

import threading
import time

from agentfox.runtime.enforcement import background


def test_work_waits_while_a_check_is_in_flight(monkeypatch):
    monkeypatch.setattr(background, "QUIET_S", 0.05)
    ran = threading.Event()
    with background.foreground():
        background.submit(ran.set)
        time.sleep(0.2)
        assert not ran.is_set()  # a check is running: the job holds off
    assert ran.wait(2)  # it runs once the gateway is quiet


def test_work_runs_promptly_on_an_idle_gateway(monkeypatch):
    monkeypatch.setattr(background, "QUIET_S", 0.05)
    ran = threading.Event()
    background.submit(ran.set)
    assert ran.wait(2)


def test_a_failing_job_does_not_stop_the_worker(monkeypatch):
    monkeypatch.setattr(background, "QUIET_S", 0.01)
    ran = threading.Event()

    def boom():
        raise RuntimeError("nope")

    background.submit(boom)
    background.submit(ran.set)
    assert ran.wait(2)
