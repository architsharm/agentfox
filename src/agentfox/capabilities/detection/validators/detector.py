"""A validator as a detector, and a validator's findings as detections.

Only validators that run with no settings become stand-alone detectors
(``validator.<name>``); the rest run through custom rules, which supply settings.
Either way findings become :class:`Detection` objects here, in one place, so
redaction and span handling are the same for both.
"""

from __future__ import annotations

from typing import Any

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    DetectorResult,
    redact_sample,
)
from agentfox.capabilities.detection.validators import all_validators
from agentfox.capabilities.detection.validators.base import CheckContext, Validator
from agentfox.capabilities.judgment.jev import JevUnavailable

KEY_PREFIX = "validator."


def check_context(context: DetectionContext) -> CheckContext:
    return CheckContext(
        surface=context.surface,
        tool=context.tool_key or (context.extra or {}).get("tool"),
        agent_slug=context.agent_slug,
        extra=context.extra or {},
    )


def detections(
    validator: Validator,
    params: Any,
    content: str,
    context: DetectionContext,
    *,
    entity_type: str | None = None,
    detail: dict[str, Any] | None = None,
) -> list[Detection]:
    """Run a validator and report its findings as detections of `entity_type`."""
    if not content:
        return []
    out: list[Detection] = []
    for f in validator.check(content, params, check_context(context)):
        start, end = (f.start, f.end) if f.end > f.start else (0, len(content))
        out.append(
            Detection(
                entity_type=entity_type or validator.entity_type,
                score=max(0.0, min(1.0, f.score)),
                start=start,
                end=end,
                # Never the matched text itself: a reason can quote what it found.
                sample=redact_sample(content[start:end]),
                owasp_id=validator.owasp_id,
                atlas_id=validator.atlas_id,
                detail={
                    "validator": validator.name,
                    "reason": f.reason,
                    **(detail or {}),
                    **f.detail,
                },
            )
        )
    return out


class ValidatorDetector(BaseDetector):
    """``validator.<name>``: one settings-free validator in the detector pipeline."""

    def __init__(self, validator: Validator) -> None:
        self.validator = validator
        #: `catalog.group_of` reads `spec.entity_type`.
        self.spec = validator
        self.key = f"{KEY_PREFIX}{validator.name}"
        self.version = getattr(validator, "version", "1.0")
        self.surfaces = tuple(validator.surfaces)
        self.timeout_ms = validator.timeout_ms
        if validator.requires_budget_ms:
            self.requires_budget_ms = validator.requires_budget_ms
        self.label = validator.label or validator.name
        self.covers_threats = tuple(x for x in (validator.owasp_id, validator.atlas_id) if x)
        # `models.models_for` reads these.
        self.model_id = validator.models[0] if validator.models else None
        self.secondary_model_id = validator.models[1] if len(validator.models) > 1 else None
        # A check about shape (valid JSON, must end with …) is about the text as
        # written; decoding it first would judge a different text.
        self.handles_views = not getattr(validator, "scan_views", True)
        # None for a validator that needs settings: wrapped only to pull its weights
        # or describe it, never run on its own.
        self._params = validator.params() if validator.standalone() else None

    def available(self) -> bool:
        return self.validator.available()

    @property
    def unavailable_reason(self) -> str:
        return self.validator.unavailable_reason()

    def warm(self) -> None:
        if self.available():
            self.validator.warm()

    def judge_entities(self, context: DetectionContext | None = None) -> tuple[str, ...]:
        """What a judge validator produces; empty for one decided by code."""
        if getattr(self.validator, "kind", "") != "judge":
            return ()
        return (self.validator.entity_type,)

    def detect(self, content: str, context: DetectionContext) -> DetectorResult:
        try:
            return super().detect(content, context)
        except JevUnavailable as exc:
            # A judge that got no answer, or whose payload was not sent: the same
            # report the built-in judges make, so the pipeline tells them apart.
            from agentfox.capabilities.detection.detectors.judgment import (
                unavailable_result,
            )

            return unavailable_result(self, exc, self.judge_entities(context))

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if self._params is None:
            raise RuntimeError(f"{self.key} needs settings; run it through a rule")
        return detections(self.validator, self._params, content, context)


def validator_detectors() -> list[ValidatorDetector]:
    """Every registered validator offered as a detector and runnable with no settings."""
    return [
        ValidatorDetector(v) for v in all_validators().values() if v.detector and v.standalone()
    ]
