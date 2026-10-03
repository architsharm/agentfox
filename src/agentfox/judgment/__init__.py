"""Judgment: policy decomposed into predicates, each routed to whoever can
evaluate it. Code owns comparisons and identity; Jev owns meaning."""

from __future__ import annotations

from .egress import Backend, EgressRefused, EgressReport, JudgmentGateway
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
