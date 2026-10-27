"""Persistence of what the detectors saw: detector runs, degradation and findings."""

from __future__ import annotations

from typing import Any

from agentfox.core.ids import detector_run_id
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


#: Where the content was, as a reader says it.
_SURFACE_WORDS = {
    "input": "a user message",
    "output": "a reply",
    "tool_args": "a tool call",
    "tool_result": "a tool result",
    "retrieved": "retrieved content",
    "memory_write": "a memory write",
    "agent_message": "a message between agents",
    "reasoning": "the agent's reasoning",
}

#: What was found, by entity prefix, most specific first. A reader should never meet
#: `INJECTION.SYSTEM_PROMPT_LEAK` in a title; the evidence keeps the exact type.
_ENTITY_WORDS: tuple[tuple[str, str], ...] = (
    ("INJECTION.SYSTEM_PROMPT", "system prompt extraction"),
    ("INJECTION.", "a prompt attack"),
    ("JAILBREAK", "a jailbreak"),
    ("PII.", "personal data"),
    ("SECRET.", "a secret or API key"),
    ("CREDENTIAL", "credentials"),
    ("SAFETY.", "harmful content"),
    ("TOXIC", "harmful content"),
    ("CODE.", "insecure code"),
    ("GROUNDING.", "an unsupported claim"),
    ("TOPIC.", "an off-limits topic"),
    ("BRAND.", "a brand rule"),
)

_PRESENT = {"block": "Would block", "escalate": "Would hold", "redact": "Would redact"}


def _entity_words(entity: str, rules_fired: list[dict[str, Any]]) -> str:
    upper = entity.upper()
    if upper.startswith("CUSTOM."):
        # A rule the workspace wrote names itself: "support-bot: blocked words".
        for rule in rules_fired:
            if entity in (rule.get("entities") or []) or any(
                upper.startswith(str(p).upper()) for p in rule.get("entity_prefixes") or []
            ):
                reason = str(rule.get("reason") or "").replace(": your rule", "")
                name = reason.split(": ", 1)[-1].strip()
                if name:
                    return name
        return "one of your rules"
    for prefix, words in _ENTITY_WORDS:
        if upper.startswith(prefix):
            return words
    return entity.lower().replace("_", " ").replace(".", ": ")


def _detection_title(
    effective: str,
    applied: str,
    surface: str,
    entity_types: list[str],
    rules_fired: list[dict[str, Any]] | None = None,
) -> str:
    """What a detection finding is called, and it has to be what HAPPENED.

    `effective` is what the policy asked for and `applied` what was done; under a
    watching policy they differ, and the title says "would", never "blocked", for a
    request that went through. Plain words for what and where: the exact entity
    types stay in the evidence.
    """
    where = _SURFACE_WORDS.get(surface, surface.replace("_", " "))
    found = list(dict.fromkeys(_entity_words(e, rules_fired or []) for e in entity_types))
    what = ", ".join(found[:3]) + (f" and {len(found) - 3} more" if len(found) > 3 else "")
    if applied == effective:
        verb = _PAST_TENSE.get(effective, effective.capitalize())
        return f"{verb} {where}: {what}"
    verb = _PRESENT.get(effective, f"Would {effective}")
    return f"{verb} {where}: {what} (watching)"


def persist_detector_runs(
    session, pipeline_result, trace_id: str | None, surface: str
) -> list[str]:
    """One row per detector run and one per detection. Ids are assigned here, so the
    rows go to the database with the rest of the request's writes in one flush
    instead of a round trip each (a check runs about ten detectors)."""
    ids: list[str] = []
    for run in pipeline_result.results:
        run_id = detector_run_id()
        session.add(
            DetectorRun(
                id=run_id,
                trace_id=trace_id,
                detector_key=run.detector_key,
                detector_version=run.version,
                surface=surface,
                duration_ms=run.duration_ms,
                status=run.status,
                score=run.score,
                raw_json=run.raw,
            )
        )
        ids.append(run_id)
        for detection in run.detections:
            session.add(
                DetectionFinding(
                    detector_run_id=run_id,
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
        # A rule the workspace wrote itself (blocked words, topics) doing what it was
        # set up to do is a record, not an incident; watching, it is worth a look.
        if entity_types and all(e.upper().startswith("CUSTOM.") for e in entity_types):
            severity = "low" if applied == effective else "medium"

        # One finding per (agent, surface, verdict, entity set): the same detector firing
        # on the same kind of content is one pattern with a count, and the refreshed
        # evidence always points at the latest decision.
        raise_finding(
            self.session,
            type="guardrail_detection",
            severity=severity,
            title=_detection_title(effective, applied, surface, entity_types, rules_fired),
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
        return persist_detector_runs(self.session, pipeline_result, trace_id, surface)
