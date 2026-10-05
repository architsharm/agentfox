"""One shared shape for a module-level, non-persisted finding.

Five independent modules (``effects``, ``data_access``, ``guardrails.actions``,
``register``, ``context_integrity``) each hand-rolled the same
``{code, detail, severity, evidence}`` dataclass with an identical ``to_json``.
This is the one copy.

Deliberately distinct from ``models.Finding``, the persisted cross-pillar queue —
these are transient, in-request analysis results (a statement's risk findings, a
context-quality defect) that a caller may or may not choose to raise into that
queue, never a database row on their own. And deliberately *not* a shared
severity vocabulary: ``context_integrity.Finding`` keeps its own three-value
warn/degraded/reject scale, mapped 1:1 onto an enforcement verdict, because that
mapping is the whole point of that module — forcing it onto the four-value
critical/high/medium/low scale used elsewhere would break it for no benefit,
since nothing merges these values across modules today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskFinding:
    """One measurable defect, with the evidence for it."""

    code: str
    detail: str
    severity: str = "high"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "severity": self.severity,
            "evidence": self.evidence,
        }
