"""Judgment: policy decomposed into predicates, each routed to whoever can
evaluate it. Code owns comparisons and identity; Jev owns meaning."""

from __future__ import annotations

from agentfox.capabilities.judgment.capability import (
    EVIDENCE,
    ROUTING,
    CapabilityRouter,
    Combine,
    DecisionKind,
    Evidence,
    Measurement,
    Plan,
    Tier,
)
from agentfox.capabilities.judgment.egress import (
    Backend,
    EgressRefused,
    EgressReport,
    JudgmentGateway,
    PiiEgress,
)
from agentfox.capabilities.judgment.jev import JevAnswer, JevClient, JevResult, JevUnavailable
from agentfox.capabilities.judgment.llm import LlmJudge
from agentfox.capabilities.judgment.panel import PanelResult, judges_for
from agentfox.capabilities.judgment.posture import Ceiling, Posture, PostureRefused
from agentfox.capabilities.judgment.predicate import (
    Comparison,
    Identity,
    Policy,
    Predicate,
    PredicateKind,
    PredicateMisrouted,
    Selection,
    Semantic,
    lint_semantic,
)
from agentfox.capabilities.judgment.router import (
    Decision,
    Outcome,
    PredicateResult,
    Router,
    resolve,
)

__all__ = [
    "Ceiling",
    "LlmJudge",
    "Posture",
    "PostureRefused",
    "PanelResult",
    "judges_for",
    "PiiEgress",
    "ROUTING",
    "EVIDENCE",
    "Tier",
    "Plan",
    "Measurement",
    "Evidence",
    "DecisionKind",
    "Combine",
    "CapabilityRouter",
    "Backend",
    "Comparison",
    "Decision",
    "EgressRefused",
    "EgressReport",
    "Identity",
    "JevAnswer",
    "JevClient",
    "JevResult",
    "JevUnavailable",
    "JudgmentGateway",
    "Outcome",
    "Policy",
    "Predicate",
    "PredicateKind",
    "PredicateMisrouted",
    "PredicateResult",
    "Router",
    "Selection",
    "Semantic",
    "lint_semantic",
    "resolve",
]
