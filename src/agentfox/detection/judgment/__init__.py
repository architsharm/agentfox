"""Judgment: policy decomposed into predicates, each routed to whoever can
evaluate it. Code owns comparisons and identity; Jev owns meaning."""

from __future__ import annotations

from agentfox.detection.judgment.capability import (
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
from agentfox.detection.judgment.egress import Backend, EgressRefused, EgressReport, JudgmentGateway, PiiEgress
from agentfox.detection.judgment.jev import JevAnswer, JevClient, JevResult, JevUnavailable
from agentfox.detection.judgment.llm import LlmJudge
from agentfox.detection.judgment.panel import PanelResult, judges_for
from agentfox.detection.judgment.posture import Ceiling, Posture, PostureRefused
from agentfox.detection.judgment.predicate import (
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
from agentfox.detection.judgment.router import Decision, Outcome, PredicateResult, Router, resolve

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
