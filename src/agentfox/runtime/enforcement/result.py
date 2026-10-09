"""What the enforcer returns: the verdict for one call, a preflight outcome and a
streamed event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentfox.capabilities.detection import TaintTracker
from agentfox.core.models import Agent, Identity, Trace

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
    # `explanation` is what an engineer reads instead of "blocked by
    # policy"; `suppressed` records exceptions that fired, because an exception that
    # leaves no trace is a hole rather than a control.
    explanation: dict[str, Any] = field(default_factory=dict)
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    latency_budget: dict[str, Any] = field(default_factory=dict)
    #: What to show the end user when the request was stopped or held, from the
    #: deciding rule's `message`. Empty when no deciding rule set one.
    user_message: str = ""
    #: When the deciding rules ask to re-ask rather than refuse an output: the
    #: correction to send the model. The gateway's proxy uses it itself; a guard
    #: endpoint returns it for the caller to use.
    reask_instruction: str = ""

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
            "user_message": self.user_message or None,
            "fix": {"instruction": self.reask_instruction} if self.reask_instruction else None,
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
    #: Tool-call fragments the model streamed (OpenAI ``delta.tool_calls`` shape).
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    result: EnforcementResult | None = None


#: Applied verdicts after which the end user is not getting what they asked for.
STOPPING_VERDICTS = frozenset({"block", "escalate", "abstain"})


def user_message_for(verdict: str, rules_fired: list[dict[str, Any]]) -> str:
    """The deciding rule's end-user message, if it set one.

    "Deciding" is a rule whose effect is the applied verdict; when several decide,
    the first one with a message wins, in the order the policies fired them.
    """
    if verdict not in STOPPING_VERDICTS:
        return ""
    return next(
        (r["message"] for r in rules_fired if r.get("effect") == verdict and r.get("message")),
        "",
    )


def reask_instruction_for(effective: str, surface: str, rules_fired: list[dict[str, Any]]) -> str:
    """The correction to re-ask with, or "" when this block is not fixable.

    Only a blocked model *output* qualifies, and only when every rule that blocked it
    asked for a re-ask: one rule that wants a refusal keeps the refusal. The
    instruction is built from the rules' reasons, the operator-facing text, because
    it goes to the model and never to the end user.
    """
    if effective != "block" or surface not in ("output", "completion"):
        return ""
    blocking = [r for r in rules_fired if r.get("effect") == "block"]
    if not blocking or any(r.get("on_block", "refuse") != "reask" for r in blocking):
        return ""
    reasons = "; ".join(dict.fromkeys(r.get("reason") or r.get("rule_id", "") for r in blocking))
    return (
        "Your previous answer was not allowed: "
        f"{reasons}. Answer the same request again without that problem."
    )


def masking_entities(rules_fired: list[dict[str, Any]]) -> tuple[set[str], tuple[str, ...]]:
    """Exact entity types and prefixes the firing mask/redact rules name.

    Personal data and secrets are always masked under a masking verdict, as before.
    Beyond those, only what a masking rule actually named — so a custom word list
    set to Mask masks its words, and a block rule's entities are never rewritten.
    """
    exact: set[str] = set()
    prefixes: list[str] = ["PII", "SECRET"]
    for r in rules_fired:
        if r.get("effect") not in ("redact", "mask", "tokenize"):
            continue
        exact.update(str(e).upper() for e in r.get("entities") or [])
        prefixes.extend(str(p).upper() for p in r.get("entity_prefixes") or [])
    return exact, tuple(dict.fromkeys(prefixes))
