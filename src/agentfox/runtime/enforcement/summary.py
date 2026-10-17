"""A short, masked preview of what the user asked, for the runs list.

Without one, a run read "User message · Agent reply" and nobody could find the run they
were looking for. A preview is still user content, so personal data and secrets are
masked by the same detectors that guard the traffic before anything is stored, and it
is cut to one line.
"""

from __future__ import annotations

from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.detectors.pii import NativePiiDetector, redact_content
from agentfox.capabilities.detection.detectors.secrets import SecretsDetector

MAX_CHARS = 160
_DETECTORS = (NativePiiDetector(), SecretsDetector())


def summarize(text: str) -> str | None:
    text = " ".join((text or "").split())
    if not text:
        return None
    context = DetectionContext(surface="input")
    found = [d for detector in _DETECTORS for d in detector.detect(text, context).detections]
    masked = redact_content(text, found)
    return masked if len(masked) <= MAX_CHARS else masked[: MAX_CHARS - 1] + "…"
