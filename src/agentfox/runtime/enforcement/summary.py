"""A short, masked preview of what the user asked, for the runs list.

Without one, a run read "User message · Agent reply" and nobody could find the run they
were looking for. A preview is still user content, so personal data and secrets are
masked by the same detectors that guard the traffic before anything is stored, and it
is cut to one line.
"""

from __future__ import annotations

from typing import Any

from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.detectors.pii import NativePiiDetector, redact_content
from agentfox.capabilities.detection.detectors.secrets import SecretsDetector

MAX_CHARS = 160
_DETECTORS = (NativePiiDetector(), SecretsDetector())


def mask(text: str) -> str:
    """``text`` with personal data and secrets masked, at full length: for content
    stored as a record, such as a call's transcript."""
    if not text:
        return ""
    context = DetectionContext(surface="input")
    found = [d for detector in _DETECTORS for d in detector.detect(text, context).detections]
    return redact_content(text, found)


#: The most of a user's message a run keeps (masked), for a test made from the run.
MAX_INPUT_CHARS = 8000


def record_input(session: Any, trace: Any, text: str) -> None:
    """Keep the user's message on the run (masked, as the preview is), as a ``input``
    span with ``agentfox.input``: what a regression test made from the run asks
    (`capabilities.evaluation.cases.promote_trace`). Without it a run reported to an
    account had nothing to test with, and its case passed at 100% on "No user input"."""
    from agentfox.platform.ledger.trace import add_span

    masked = mask(text or "")
    if not masked.strip():
        return
    add_span(
        session,
        trace,
        kind="input",
        name="user message",
        attributes={"agentfox.input": masked[:MAX_INPUT_CHARS]},
    )


def record_output(session: Any, trace: Any, text: str, *, agent: str | None = None) -> None:
    """Keep the reply the user got (masked), as an ``llm`` span with
    ``agentfox.output``: the shape online scoring, drift and promoted cases read. The
    guard-only path (`/v1/guard/output`, how ``auto()`` reports to an account) never
    saw the model call, so it recorded no output and those had nothing to score."""
    from agentfox.platform.ledger.trace import add_span

    masked = mask(text or "")
    if not masked.strip():
        return
    add_span(
        session,
        trace,
        kind="llm",
        name=f"{agent or 'agent'}.reply",
        attributes={"agentfox.output": masked[:MAX_INPUT_CHARS]},
    )


def summarize(text: str) -> str | None:
    text = " ".join((text or "").split())
    if not text:
        return None
    masked = mask(text)
    return masked if len(masked) <= MAX_CHARS else masked[: MAX_CHARS - 1] + "…"
