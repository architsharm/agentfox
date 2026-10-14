"""Model-backed detectors answered by a model server instead of this process.

When `model_server_url` is set, each detector in `model_server_detectors` (every
model-backed one, by default) is replaced, wherever the registry hands detectors out,
by a `RemoteDetector`. It has the same key, surfaces and version, and its `detect`
is one HTTP call to `agentfox serve-models` (`apps/model_server.py`), which runs the
real detector on its own hardware.

Nothing about a decision changes. The detections come back with their detail intact
(an advisory backstop hit stays advisory). The pipeline still bounds the call by the
detector's own timeout, and a server that is slow, down or refusing is reported as
degraded or unavailable, never as a clean pass.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from agentfox.capabilities.detection.base import Detection, DetectionContext, DetectorResult

log = logging.getLogger(__name__)

#: Added to the wrapped detector's own timeout for the round trip. Same-region HTTPS
#: on a kept-alive connection measures in single-digit milliseconds; this leaves room
#: for a slow hop without hiding a slow model.
NETWORK_ALLOWANCE_MS = 50

#: How long a health answer is trusted. Short enough that a restarted server or a
#: newly pulled model is picked up within a minute.
HEALTH_TTL_S = 30.0

_client_lock = threading.Lock()
_client: Any = None
_health: dict[str, Any] = {"at": 0.0, "url": None, "detectors": {}, "error": None}
_proxies: dict[tuple[str, str], RemoteDetector] = {}


def _http():
    """One kept-alive client for the process: a new TLS handshake per detection would
    cost more than the model."""
    global _client
    with _client_lock:
        if _client is None:
            import httpx

            _client = httpx.Client(timeout=5.0, limits=httpx.Limits(max_keepalive_connections=32))
        return _client


def _headers() -> dict[str, str]:
    from agentfox.core.config import get_settings

    token = get_settings().model_server_token
    return {"Authorization": f"Bearer {token}"} if token else {}


def server_health(*, refresh: bool = False) -> dict[str, Any]:
    """What the model server says it can run, cached for `HEALTH_TTL_S`."""
    from agentfox.core.config import get_settings

    url = (get_settings().model_server_url or "").rstrip("/")
    now = time.monotonic()
    if not refresh and _health["url"] == url and now - _health["at"] < HEALTH_TTL_S:
        return _health
    try:
        r = _http().get(f"{url}/health", headers=_headers(), timeout=3.0)
        r.raise_for_status()
        body = r.json()
        _health.update(at=now, url=url, detectors=body.get("detectors", {}), error=None)
    except Exception as exc:  # noqa: BLE001 - any failure means "cannot run there now"
        _health.update(at=now, url=url, detectors={}, error=f"{type(exc).__name__}: {exc}")
    return _health


def is_remote(detector: Any) -> bool:
    """Whether this detector should be answered by the model server."""
    from agentfox.capabilities.detection.models import models_for
    from agentfox.core.config import get_settings

    settings = get_settings()
    if not settings.model_server_url or isinstance(detector, RemoteDetector):
        return False
    chosen = settings.model_server_detectors
    if chosen:
        return detector.key in chosen
    return bool(models_for(detector))


def resolve(detector: Any) -> Any:
    """The detector itself, or its remote stand-in when the model server answers it."""
    if detector is None or not is_remote(detector):
        return detector
    from agentfox.core.config import get_settings

    url = get_settings().model_server_url or ""
    key = (detector.key, url)
    proxy = _proxies.get(key)
    if proxy is None or proxy.local is not detector:
        proxy = _proxies[key] = RemoteDetector(detector)
    return proxy


class RemoteDetector:
    """Stands in for a model-backed detector, answering through the model server.

    Everything not overridden here (`key`, `surfaces`, `version`, `model_id`, a
    detector's own `applies`) is the wrapped detector's, so catalogues, `doctor` and
    the pipeline see the same detector they always did.
    """

    handles_views = True  # the server runs the full detector, de-obfuscation included

    def __init__(self, local: Any) -> None:
        self.local = local

    def __getattr__(self, name: str) -> Any:
        return getattr(self.local, name)

    @property
    def timeout_ms(self) -> int:
        from agentfox.core.config import get_settings

        own = getattr(self.local, "timeout_ms", None) or get_settings().detector_timeout_ms
        return int(own) + NETWORK_ALLOWANCE_MS

    def available(self) -> bool:
        entry = server_health()["detectors"].get(self.key) or {}
        return bool(entry.get("available"))

    @property
    def unavailable_reason(self) -> str:
        health = server_health()
        if health["error"]:
            return f"model server unreachable at {health['url']} ({health['error']})"
        entry = health["detectors"].get(self.key)
        if entry is None:
            return f"the model server at {health['url']} does not serve {self.key}"
        return f"on the model server: {entry.get('reason') or 'not available'}"

    def warm(self) -> None:
        # The server loads its models before taking traffic; here only the
        # connection and the health answer are worth having before the first request.
        server_health(refresh=True)

    def detect(self, content: str, context: DetectionContext) -> DetectorResult:
        from agentfox.core.config import get_settings

        url = (get_settings().model_server_url or "").rstrip("/")
        r = _http().post(
            f"{url}/v1/detect",
            json={
                "detector": self.key,
                "content": content or "",
                "surface": context.surface,
                "agent_slug": context.agent_slug,
            },
            headers=_headers(),
            timeout=self.timeout_ms / 1000,
        )
        r.raise_for_status()
        body = r.json()
        detections = [
            Detection(
                entity_type=d["entity_type"],
                score=float(d["score"]),
                start=int(d.get("start", 0)),
                end=int(d.get("end", 0)),
                sample=d.get("sample", ""),
                owasp_id=d.get("owasp_id"),
                atlas_id=d.get("atlas_id"),
                detail={**(d.get("detail") or {}), "served_by": "model_server"},
            )
            for d in body.get("detections", [])
        ]
        return DetectorResult(
            detector_key=self.key,
            version=body.get("version", self.version),
            score=max((d.score for d in detections), default=0.0),
            detections=detections,
            raw={"model_server_latency_ms": body.get("latency_ms")},
        )


def _reset() -> None:
    """For tests: forget the cached client, health and proxies."""
    global _client
    with _client_lock:
        _client = None
    _health.update(at=0.0, url=None, detectors={}, error=None)
    _proxies.clear()
