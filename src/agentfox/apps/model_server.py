"""The model server: model-backed detectors, on the machine that should run them.

A gateway that cannot hold weights (serverless, read-only, cold instances) or has no
GPU sends each model-backed detection here instead of loading the model itself
(`model_server_url`; the client is `detection.remote`). This process runs the very
same detector classes, from the same release, on whatever device it has
(`model_device`), so the two sides cannot disagree about what a detector does.

No database, no policies, no tenants: it answers "what does detector X find in this
text", and nothing else. Decisions stay with the gateway.

    agentfox serve-models --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

import hmac
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agentfox import __version__

log = logging.getLogger(__name__)

#: The longest text accepted, in characters. Every detector here truncates well below
#: this; the bound only stops one request from holding a worker on a huge body.
MAX_CONTENT = 200_000


class DetectRequest(BaseModel):
    detector: str
    content: str = Field(max_length=MAX_CONTENT)
    surface: str = "input"
    agent_slug: str | None = None


def served_detectors() -> dict[str, Any]:
    """The model-backed detectors this process can run, keyed by name.

    Read from the registry directly, never through the remote proxies: this process
    *is* the model server, and asking itself over HTTP would loop.
    """
    from agentfox.capabilities.detection.base import _REGISTRY
    from agentfox.capabilities.detection.models import models_for

    return {key: d for key, d in _REGISTRY.items() if models_for(d)}


def _require_token(authorization: str | None = Header(default=None)) -> None:
    from agentfox.core.config import get_settings

    expected = get_settings().model_server_token
    if not expected:
        return  # loopback only; `serve-models` refuses anything else without a token
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="model server token required")


def _warm() -> None:
    for key, detector in served_detectors().items():
        try:
            if not detector.available():
                reason = getattr(detector, "unavailable_reason", "") or "not available"
                log.warning("model server: %s cannot run here (%s)", key, reason)
                continue
            started = time.perf_counter()
            detector.warm()
            log.info("model server: %s warm in %.1fs", key, time.perf_counter() - started)
        except Exception:
            log.exception("model server: %s failed to warm; it stays cold", key)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load every model before taking traffic, so no request pays for a load.
    _warm()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AgentFox model server", version=__version__, lifespan=lifespan)

    @app.get("/health")
    def health(_: None = Depends(_require_token)) -> dict[str, Any]:
        from agentfox.capabilities.detection.loading import model_device

        detectors = {}
        for key, detector in served_detectors().items():
            available = bool(detector.available())
            reason = "" if available else str(getattr(detector, "unavailable_reason", "") or "")
            detectors[key] = {"available": available, "reason": reason}
        return {"version": __version__, "device": model_device(), "detectors": detectors}

    @app.post("/v1/detect")
    def detect(req: DetectRequest, _: None = Depends(_require_token)) -> dict[str, Any]:
        from agentfox.capabilities.detection.base import DetectionContext

        detector = served_detectors().get(req.detector)
        if detector is None:
            raise HTTPException(404, f"{req.detector} is not a model-backed detector")
        if not detector.available():
            reason = getattr(detector, "unavailable_reason", "") or "not available"
            raise HTTPException(503, f"{req.detector} cannot run here: {reason}")
        started = time.perf_counter()
        result = detector.detect(
            req.content, DetectionContext(surface=req.surface, agent_slug=req.agent_slug)
        )
        return {
            "detector": req.detector,
            "version": result.version,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detections": [
                {
                    "entity_type": d.entity_type,
                    "score": d.score,
                    "start": d.start,
                    "end": d.end,
                    "sample": d.sample,
                    "owasp_id": d.owasp_id,
                    "atlas_id": d.atlas_id,
                    "detail": d.detail,
                }
                for d in result.detections
            ],
        }

    return app


app = create_app()
