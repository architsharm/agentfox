"""Work that runs after the response, when the gateway is not checking anything.

The classifier's advisory backstop is a second model pass. Started on its own thread
after each response, it ran at the same moment as the next request's own model pass
and the two shared the CPU: under back-to-back traffic the default layer's median
went from 80 ms to 116 ms on CPU (measured 2026-10-28), for a result no verdict
waits for. Here it waits until no check is in flight and none has finished for
:data:`QUIET_S`, so live checks never compete with it. Under constant load it waits;
the queue keeps the newest :data:`MAX_PENDING` jobs and drops the oldest.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

log = logging.getLogger(__name__)

#: How long the gateway must have been idle before background work starts.
QUIET_S = 0.25
MAX_PENDING = 1024

_lock = threading.Lock()
_wake = threading.Condition(_lock)
_jobs: deque[Callable[[], None]] = deque(maxlen=MAX_PENDING)
_in_flight = 0
_last_done = 0.0
_worker: threading.Thread | None = None


@contextmanager
def foreground() -> Iterator[None]:
    """Mark a check in progress; background work holds off until it ends."""
    global _in_flight, _last_done
    with _lock:
        _in_flight += 1
    try:
        yield
    finally:
        with _lock:
            _in_flight -= 1
            _last_done = time.monotonic()
            _wake.notify_all()


def submit(job: Callable[[], None]) -> None:
    """Run ``job`` when the gateway is idle. Never raises into the caller."""
    global _worker
    with _lock:
        if len(_jobs) == _jobs.maxlen:
            log.debug("background queue full; dropping the oldest job")
        _jobs.append(job)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="agentfox-background", daemon=True)
            _worker.start()
        _wake.notify_all()


def _idle_for() -> float:
    """Seconds left before the gateway counts as idle (0 when it is)."""
    if _in_flight:
        return QUIET_S
    return max(0.0, QUIET_S - (time.monotonic() - _last_done))


def _run() -> None:
    while True:
        with _lock:
            while not _jobs or _idle_for() > 0:
                _wake.wait(timeout=_idle_for() if _jobs else None)
            job = _jobs.popleft()
        try:
            job()
        except Exception:  # pragma: no cover - background work never raises
            log.warning("background job failed", exc_info=True)
