"""Judgment: policy decomposed into predicates, each routed to whoever can
evaluate it. Code owns comparisons and identity; Jev owns meaning."""

from __future__ import annotations

from .capability import (
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
from .egress import Backend, EgressRefused, EgressReport, JudgmentGateway, PiiEgress
from .jev import JevAnswer, JevClient, JevResult, JevUnavailable
from .predicate import (
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
from .router import Decision, Outcome, PredicateResult, Router, resolve

__all__ = [
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
