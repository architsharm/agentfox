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
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_started: threading.Thread | None = None


def _needs_warming() -> list:
    from agentfox.capabilities.detection.base import BaseDetector, all_detectors
    from agentfox.core.config import get_settings

    enabled = set(get_settings().enabled_detectors)
    return [
        detector
        for key, detector in all_detectors().items()
        if key in enabled and type(detector).warm is not BaseDetector.warm
    ]


def _warm(detectors: list) -> None:
    for detector in detectors:
        try:
            # `available()` can itself be slow (it imports the model library), so it
            # is asked here, on this thread, rather than by the caller.
            if detector.available():
                detector.warm()
        except Exception as exc:  # noqa: BLE001 - warming must never break the caller
            log.warning("agentfox: could not warm detector %s: %s", detector.key, exc)


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
        _started = threading.Thread(
            target=_warm, args=(detectors,), name="agentfox-detector-warmup", daemon=True
        )
        _started.start()
        return _started


def _reset() -> None:
    """For tests: allow a later `warm_in_background()` to start again."""
    global _started
    with _lock:
        _started = None
