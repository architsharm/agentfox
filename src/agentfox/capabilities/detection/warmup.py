"""Warm the enabled detectors that need it, once per process, off the caller's thread.

The gateway and the hooks daemon call `warm_all()` at startup. An application
governed in-process — `agentfox.auto()`, the SDK's `AgentFox`, a LangGraph
`AgentFoxGuard` — never did, so an opted-in model detector (``injection.classifier``,
say) loaded its weights inside the first real request, blew the per-detector budget
and degraded the first calls.

Background, not inline: loading a model takes seconds, and ``auto()`` is one line
at the top of somebody's program that must not stall it. Only detectors that are
enabled and override ``warm()`` count; with the default detector set nothing needs
warming and no thread is started.

A short script ends long before a model loads (torch alone takes seconds to import).
So, while the background warm-up has a detector, the pipeline does not wait for it:
the check runs without that detector and says so (`warming`), instead of queueing
behind the load until its allowance runs out. Nothing on the request path then
holds a lock the loader holds, the process exits when the script does, and a load
cut short by the exit is not reported as a failure.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_started: threading.Thread | None = None
#: The `cause` on a detector result skipped because its model is still loading.
WARMING = "warming"
#: Detectors the background warm-up has not finished with yet.
_pending: set[str] = set()
#: Set when the interpreter starts shutting down: a load interrupted by it is not an error.
_exiting = threading.Event()
#: Detectors already warmed in this process, by any path (`warm_all()` included).
_warmed: set[str] = set()
#: Whether `warm_now()` already ran in this process.
_done_now = False


def warming(key: str) -> bool:
    """Whether the background warm-up is still loading ``key``. The pipeline skips such
    a detector for the check at hand rather than wait for the load."""
    return key in _pending


def mark_warmed(key: str) -> None:
    """Record that ``key`` is loaded, so a later background warm-up skips it (a script
    that called `warm_all()` and then `AgentFox(...)` had its first check run without
    the model it had just waited for)."""
    _warmed.add(key)


def _mark_exiting() -> None:
    _exiting.set()


def _watch_for_exit() -> None:
    """Note the start of interpreter shutdown, before the thread pools refuse new work.

    `concurrent.futures` stops accepting work from `threading`'s own exit hook, which
    runs before `atexit`'s; transformers loads weights through such a pool, so a load
    still running then fails with "cannot schedule new futures after interpreter
    shutdown". Registered the same way, after it, so it runs first."""
    register = getattr(threading, "_register_atexit", None)
    try:
        if register is not None:
            register(_mark_exiting)
            return
    except RuntimeError:  # already shutting down
        _exiting.set()
        return
    import atexit

    atexit.register(_mark_exiting)


def _first_line(exc: BaseException) -> str:
    """transformers puts whole tracebacks in its exception messages; one line is enough."""
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _needs_warming() -> list:
    from agentfox.capabilities.detection.base import BaseDetector, all_detectors
    from agentfox.core.config import get_settings

    enabled = set(get_settings().enabled_detectors)
    return [
        detector
        for key, detector in all_detectors().items()
        if key in enabled and key not in _warmed and type(detector).warm is not BaseDetector.warm
    ]


def _warm(detectors: list) -> None:
    from agentfox.capabilities.detection.base import warn_unrunnable

    try:
        warn_unrunnable(once=True)
    except Exception as exc:  # noqa: BLE001 - warming must never break the caller
        log.debug("agentfox: detector availability report skipped: %s", exc)
    for detector in detectors:
        try:
            # `available()` can itself be slow (it imports the model library), so it
            # is asked here, on this thread, rather than by the caller.
            if detector.available():
                detector.warm()
                _warmed.add(detector.key)
        except Exception as exc:  # noqa: BLE001 - warming must never break the caller
            if _exiting.is_set():
                log.debug("agentfox: warm-up of %s stopped by exit: %s", detector.key, exc)
            else:
                log.warning(
                    "agentfox: could not warm detector %s: %s", detector.key, _first_line(exc)
                )
        finally:
            _pending.discard(detector.key)


def warm_now() -> None:
    """Warm the enabled detectors that need it on this thread, and wait for it.

    For a command that is about to run many checks in a row (an attack test): there
    the load is worth waiting for once, or every check would run without the model.
    Waits for a background warm-up already under way instead of loading twice."""
    global _done_now
    with _lock:
        running = _started
    if running is not None:
        running.join()
        return
    if _done_now:
        return
    try:
        detectors = _needs_warming()
    except Exception as exc:  # noqa: BLE001
        log.debug("agentfox: detector warm-up skipped: %s", exc)
        return
    _warm(detectors)
    _done_now = True


def warm_in_background() -> threading.Thread | None:
    """Start warming the enabled detectors that need it. Idempotent per process.

    Returns the thread (a daemon, so it never holds the process open), or None when
    nothing needs warming or a warm-up already started.
    """
    global _started
    with _lock:
        if _started is not None:
            return None
        try:
            detectors = _needs_warming()
        except Exception as exc:  # noqa: BLE001
            log.debug("agentfox: detector warm-up skipped: %s", exc)
            return None
        if not detectors:
            return None
        _watch_for_exit()
        _pending.update(d.key for d in detectors)
        _started = threading.Thread(
            target=_warm, args=(detectors,), name="agentfox-detector-warmup", daemon=True
        )
        _started.start()
        return _started


def _reset() -> None:
    """For tests: allow a later `warm_in_background()` to start again."""
    global _started, _done_now
    with _lock:
        _started = None
        _done_now = False
        _pending.clear()
        _warmed.clear()
        _exiting.clear()
