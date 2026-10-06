"""What the enforcer returns: the verdict for one call, a preflight outcome and a
streamed event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentfox.core.models import Agent, Identity, Trace
from agentfox.detection import TaintTracker


#: Verdicts whose outcome is a rewritten copy of the content rather than a yes or no.
REWRITE_VERDICTS = frozenset({"redact", "mask", "tokenize"})


class ProviderUnavailable(RuntimeError):
    """Every provider on the fallback ladder failed or is circuit-open."""


@dataclass
class EnforcementResult:
    verdict: str = "allow"
    effective_verdict: str = "allow"
    mode: str = "observe"
    decision_id: str | None = None
    trace_id: str | None = None
    approval_id: str | None = None
    policy_version_id: str | None = None
    rules_fired: list[dict[str, Any]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    taint: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    degraded: list[str] = field(default_factory=list)
    content: str | None = None  # redacted content, when the verdict is a redaction
    reason: str = ""
    # P3-12/13/14. `explanation` is what an engineer reads instead of "blocked by
    # policy"; `suppressed` records exceptions that fired, because an exception that
    # leaves no trace is a hole rather than a control.
    explanation: dict[str, Any] = field(default_factory=dict)
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    latency_budget: dict[str, Any] = field(default_factory=dict)

    @property
    def detections_found(self) -> bool:
        return bool(self.entities) or bool(self.rules_fired)

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def escalated(self) -> bool:
        return self.verdict == "escalate"

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            # The rewritten text when the applied verdict rewrites it (redact, mask,
            # tokenize); null otherwise. Without it a guard endpoint could say
            # "redact" and leave every caller to mask the content themselves.
            "content": self.content if self.verdict in REWRITE_VERDICTS else None,
            "effective_verdict": self.effective_verdict,
            "mode": self.mode,
            "decision_id": self.decision_id,
            "trace_id": self.trace_id,
            "approval_id": self.approval_id,
            "policy_version": self.policy_version_id,
            "rules_fired": self.rules_fired,
            "entities": self.entities,
            "findings": self.findings,
            "taint": self.taint,
            "latency_ms": round(self.latency_ms, 2),
            "degraded": self.degraded,
            "reason": self.reason,
            "explanation": self.explanation,
            "suppressed": self.suppressed,
            "latency_budget": self.latency_budget,
        }


@dataclass
class PreflightOutcome:
    """Everything the pre-flight established, shared by the buffered and streaming paths."""

    agent: Agent | None = None
    identity: Identity | None = None
    trace: Trace | None = None
    tracker: TaintTracker | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    result: EnforcementResult = field(default_factory=EnforcementResult)
    stopped: bool = False


@dataclass
class StreamEvent:
    """One event on the enforced stream.

    ``kind`` is one of:
      ``delta``   — content to forward to the caller
      ``blocked`` — enforcement stopped the stream; ``result`` explains why
      ``done``    — the stream completed; ``result`` carries the final verdict
    """

    kind: str = "delta"
    delta: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    result: EnforcementResult | None = None
