"""Detector interface — the build-vs-reuse seam for Pillar 3.

Every runtime primitive, ours or wrapped OSS, implements :class:`Detector`. That is
what makes "wrap the primitive, own the interface" a tested
property rather than an aspiration: swapping Presidio for something else, or
dropping a project that gets archived, touches one adapter file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agentfox.core.vocab import SURFACES


@dataclass(slots=True)
class Detection:
    """One located finding inside a piece of content.

    ``sample`` is redacted at construction: we store enough to explain
    the decision to a human and never enough to re-leak the value.
    """

    entity_type: str
    score: float
    start: int = 0
    end: int = 0
    sample: str = ""
    owasp_id: str | None = None
    atlas_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DetectionContext:
    """Everything a detector may need beyond the raw string."""

    surface: str = "input"
    agent_slug: str | None = None
    trace_id: str | None = None
    tool_key: str | None = None
    tool_impact: str = "read"
    intent: str | None = None
    taint_source: str = "user"
    schema: dict[str, Any] | None = None
    prior_tools: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DetectorResult:
    detector_key: str
    version: str
    score: float = 0.0
    detections: list[Detection] = field(default_factory=list)
    status: str = "ok"  # ok | timeout | error | skipped_budget | unavailable
    duration_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def triggered(self) -> bool:
        return bool(self.detections)


@runtime_checkable
class Detector(Protocol):
    key: str
    version: str
    surfaces: tuple[str, ...]
    timeout_ms: int | None

    def available(self) -> bool:
        """False when an optional dependency or model weight is absent.

        Unavailable detectors degrade the pipeline rather than failing it — that is
        what makes the offline default work without pretending coverage exists.
        """
        ...

    def warm(self) -> None:
        """Pay any first-call cost now, off the request path. No-op for most
        detectors; see :meth:`BaseDetector.warm`."""
        ...

    def detect(self, content: str, context: DetectionContext) -> DetectorResult: ...


class BaseDetector:
    """Convenience base: subclasses implement :meth:`_detect`."""

    key: str = "base"
    version: str = "1"
    surfaces: tuple[str, ...] = SURFACES

    #: Set by detectors that normalise internally, so this class does not do it twice.
    handles_views: bool = False

    #: Published threat identifiers this detector looks for — OWASP LLM / Agentic
    #: and MITRE ATLAS. Declared rather than inferred from the `owasp_id` it happens
    #: to stamp on a detection, because the coverage question is "is anything
    #: watching for this", and a detector that has never fired still is.
    #:
    #: Empty is a real answer: several adapters wrap a third-party check whose threat
    #: mapping is somebody else's to assert. An undeclared detector is reported as
    #: contributing no coverage rather than being quietly credited with some.
    covers_threats: tuple[str, ...] = ()

    #: None means "use the pipeline's default (`detector_timeout_ms`)". A detector
    #: that genuinely needs longer — a real model forward pass, not a regex scan —
    #: declares that here rather than the pipeline granting everyone more rope,
    #: which would blunt the whole point of a per-detector budget.
    timeout_ms: int | None = None

    def available(self) -> bool:  # pragma: no cover - overridden by adapters
        return True

    def warm(self) -> None:
        """Pay any first-call cost (loading a model into memory, say) now, off the
        request path. No-op by default; a detector backed by something with real
        startup cost overrides this. `detector_timeout_ms` is short enough
        that a detector which only gets slow once, on its very first call, would
        otherwise silently degrade the first real request after every process
        start — see :meth:`warm_all`."""

    def detect(self, content: str, context: DetectionContext) -> DetectorResult:
        detections = self._detect(content or "", context)
        if not self.handles_views:
            detections.extend(self._detect_obfuscated(content or "", context, detections))
        score = max((d.score for d in detections), default=0.0)
        return DetectorResult(
            detector_key=self.key,
            version=self.version,
            score=score,
            detections=detections,
        )

    def _detect_obfuscated(
        self, content: str, context: DetectionContext, already: list[Detection]
    ) -> list[Detection]:
        """Re-run this detector over de-obfuscated readings of the same content.

        Every detector inherits evasion resistance here rather than implementing it,
        which matters because the blindness was not confined to injection: a
        base64-encoded API key or a zero-width-salted SSN passed the DLP detectors
        untouched, which is an exfiltration path with a governance layer watching.

        Ordinary content normalises to a single view, so this costs nothing on the
        common path. Spans are mapped back to the original text, because a detection
        reported at coordinates in a decoded string would point at characters the user
        never sent — and redaction would then corrupt the payload.
        """
        from agentfox.capabilities.detection.normalize import normalize

        normalised = normalize(content)
        if len(normalised.views) <= 1:
            return []

        seen = {(d.entity_type, d.start, d.end) for d in already}
        extra: list[Detection] = []
        # Every view whose text differs from what `_detect` already saw. Skipping the
        # primary view was wrong: it is the *cleaned* one, so zero-width-salted content
        # was normalised and then never re-scanned.
        for view in normalised.views:
            if view.text == content:
                continue
            for found in self._detect(view.text, context):
                start, end = view.origin(found.start, found.end)
                key = (found.entity_type, start, end)
                if key in seen:
                    continue
                seen.add(key)
                found.start, found.end = start, end
                found.sample = redact_sample(content[start:end])
                found.detail = {**found.detail, "view": view.kind, "obfuscated": True}
                # Content that had to be decoded before it matched is worse than
                # content that matched as written: nobody base64-encodes a credential
                # they intend to handle correctly.
                found.score = min(1.0, found.score + 0.1)
                extra.append(found)
        return extra

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Redaction — applied at capture, never after the fact
# --------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def redact_sample(value: str, keep: int = 4, max_len: int = 80) -> str:
    """Return a sample safe to persist.

    Keeps a short prefix so a human can recognise *what kind* of thing matched,
    masks the rest. An audit log that stores the SSN it detected is a new
    liability, not a control.
    """
    value = _WS.sub(" ", (value or "").strip())
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    visible = value[:keep]
    masked = "*" * min(len(value) - keep, max_len - keep)
    return f"{visible}{masked}"


def snippet(value: str, start: int, end: int, window: int = 40) -> str:
    """A redacted window around a match, for explaining a block to a developer."""
    lo = max(0, start - window)
    hi = min(len(value), end + window)
    before = _WS.sub(" ", value[lo:start])
    after = _WS.sub(" ", value[end:hi])
    return f"…{before}[{redact_sample(value[start:end])}]{after}…"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

_REGISTRY: dict[str, Detector] = {}


def register_detector(detector: Detector) -> Detector:
    _REGISTRY[detector.key] = detector
    return detector


def get_detector(key: str) -> Detector | None:
    return _REGISTRY.get(key)


def all_detectors() -> dict[str, Detector]:
    return dict(_REGISTRY)


def available_detectors() -> dict[str, Detector]:
    return {k: d for k, d in _REGISTRY.items() if d.available()}


def warm_all() -> None:
    """Call once at process startup (see `gateway.app.lifespan`). Only detectors
    with real first-call cost do anything here; everything else is a no-op."""
    for detector in available_detectors().values():
        detector.warm()
