"""Persistence of what the detectors saw: detector runs, degradation and findings."""

from __future__ import annotations

from typing import Any

from agentfox.core.models import Agent, DetectionFinding, DetectorRun
from agentfox.platform.ledger.findings import raise_finding, record_detector_health

#: Past tense, spelled out. `f"{verdict.capitalize()}ed"` produced "Escalateed"
#: and "Tokenizeed", and there is no rule that turns every one of these into a
#: past participle correctly.
_PAST_TENSE = {
    "block": "Blocked",
    "redact": "Redacted",
    "mask": "Masked",
    "tokenize": "Tokenised",
    "escalate": "Escalated",
    "abstain": "Abstained",
    "allow": "Allowed",
}


def _detection_title(effective: str, applied: str, surface: str, entity_types: list[str]) -> str:
    """What a detection finding is called, and it has to be what HAPPENED.

    This read `f"{effective.capitalize()}ed on {surface}"`, where `effective` is
    what the policy WOULD do rather than what was done. Under an observe-mode
    policy the finding was therefore titled "Blocked on input" for a request
    that was allowed through — a false statement, in the record the product
    exists to keep.

    It matters more now than it did: a deployment with nothing bound falls back
    to the shipped baseline in observe, so an observe-mode finding is the first
    one a new user sees rather than an edge case.

    Same distinction the trace verdict carries: `applied` is what happened,
    `effective` is what the policy asked for, and when they differ the title
    says so rather than picking the more dramatic of the two.
    """
    entities = ", ".join(entity_types)
    if applied == effective:
        return f"{_PAST_TENSE.get(effective, effective.capitalize())} on {surface}: {entities}"
    # Observe: recorded, not acted on. Naming both is what makes the row
    # actionable — it says what would change if this policy were promoted.
    return (
        f"Would have been {_PAST_TENSE.get(effective, effective).lower()} on {surface}: {entities}"
    )


class _FindingsMixin:
    """Enforcer's detector persistence. Mixed into :class:`Enforcer`, never used alone."""

    def _raise_detection_finding(
        self,
        *,
        agent: Agent | None,
        trace_id: str | None,
        decision_id: str,
        surface: str,
        effective: str,
        applied: str,
        reason: str,
        rules_fired: list[dict[str, Any]],
        detections: list,
    ) -> None:
        """The general-Findings counterpart to `_persist_detectors`.

        `DetectionFinding.sample` already carries a redacted excerpt — it just
        never left the trace it was captured on. This dedupes by entity type,
        keeping the highest-scoring sample for each, and reuses whichever
        controls the firing rules already declared rather than inventing a new
        control key for the same decision.
        """
        by_entity: dict[str, Any] = {}
        for detection in detections:
            current = by_entity.get(detection.entity_type)
            if current is None or detection.score > current.score:
                by_entity[detection.entity_type] = detection
        if not by_entity:
            return

        controls = sorted({c for r in rules_fired for c in (r.get("controls") or [])}) or [
            "NOM-RTG-06"
        ]
        entity_types = sorted(by_entity)
        severity = "high" if effective in ("block", "escalate") else "medium"

        # One finding per (agent, surface, verdict, entity set): the same detector firing
        # on the same kind of content is one pattern with a count, and the refreshed
        # evidence always points at the latest decision.
        raise_finding(
            self.session,
            type="guardrail_detection",
            severity=severity,
            title=_detection_title(effective, applied, surface, entity_types),
            subject_type="agent",
            subject_id=agent.id if agent else None,
            fingerprint_parts=(surface, effective, *entity_types),
            evidence={
                "trace_id": trace_id,
                "decision_id": decision_id,
                "surface": surface,
                "verdict": effective,
                "reason": reason,
                "detections": [
                    {
                        "entity_type": d.entity_type,
                        "score": d.score,
                        "sample": d.sample,
                        "owasp_id": d.owasp_id,
                        "atlas_id": d.atlas_id,
                    }
                    for d in by_entity.values()
                ],
            },
            control_keys=controls,
        )

    def _record_degradation(self, agent: Agent | None, surface: str, pipeline_result) -> None:
        """A degraded detector is a finding — one per detector, closed on recovery."""
        record_detector_health(
            self.session,
            subject_id=agent.id if agent else None,
            surface=surface,
            pipeline_result=pipeline_result,
        )

    def _persist_detectors(self, pipeline_result, trace_id: str | None, surface: str) -> list[str]:
        ids: list[str] = []
        for run in pipeline_result.results:
            row = DetectorRun(
                trace_id=trace_id,
                detector_key=run.detector_key,
                detector_version=run.version,
                surface=surface,
                duration_ms=run.duration_ms,
                status=run.status,
                score=run.score,
                raw_json=run.raw,
            )
            self.session.add(row)
            self.session.flush()
            ids.append(row.id)
            for detection in run.detections:
                self.session.add(
                    DetectionFinding(
                        detector_run_id=row.id,
                        trace_id=trace_id,
                        entity_type=detection.entity_type,
                        score=detection.score,
                        start=detection.start,
                        end=detection.end,
                        # Already redacted by the detector — see redact_sample().
                        sample=detection.sample[:200],
                        owasp_id=detection.owasp_id,
                        atlas_id=detection.atlas_id,
                    )
                )
        return ids
