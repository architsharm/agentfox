"""Policy, decomposed into predicates that know who should evaluate them.

Measured against Jev 1.13 over ~150 calls, one mechanism explains every
failure we found: **Jev weights the salient, typical signal and
under-weights a qualifying field that contradicts it.**

    amount within limit      matched, elapsed days       ignored
    user_id                  matched, account_id         ignored
    role = support agent     matched, acting_for_user_id ignored
    merchant and amount      matched, descriptor         ignored

The same question split so it weighs one thing recovers: 0.64 -> 0.96 on a
subscription, 0.77 -> 0.97 on instalments. And the predicates Jev got wrong
were wrong *confidently and reproducibly* — 0.98 on eight consecutive runs —
so no confidence threshold catches them. TypeSafe documents the same ground
as "jaggedness": not a calculator, dates read as text, accuracy falls as
unrelated state grows, answers the question you wrote.

So the split is not a style preference, it is the correctness boundary:

    COMPARISON / IDENTITY -> code.  Exact, free, reproducible.
    SEMANTIC              -> Jev.   One signal per question.
    SELECTION             -> Jev picks from candidates code enumerated.

The type definitions below make the mistake unwritable rather than
documented. A ``Comparison`` has operands and an operator; a ``Semantic`` has
none and cannot express one. The remaining hole is a comparison smuggled into
a semantic question *in prose* — which is exactly the bug that started this
investigation — so :func:`lint_semantic` refuses those too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class PredicateKind(StrEnum):
    COMPARISON = "comparison"
    IDENTITY = "identity"
    SEMANTIC = "semantic"
    SELECTION = "selection"


#: Kinds code owns. Nothing here ever reaches a model.
CODE_KINDS = (PredicateKind.COMPARISON, PredicateKind.IDENTITY)
MODEL_KINDS = (PredicateKind.SEMANTIC, PredicateKind.SELECTION)


class PredicateMisrouted(ValueError):
    """A judgment question is carrying work that belongs in code."""


#: Phrasings that mean a comparison is happening inside a semantic question.
#: Every one of these appeared in a question that then failed. "within the
#: last" is the literal wording of the 90-day condition that returned 0.98
#: wrong on eight consecutive runs.
_COMPARISON_IN_PROSE = [
    (r"\bat least\b", "at least"),
    (r"\bat most\b", "at most"),
    (r"\bno more than\b", "no more than"),
    (r"\bno fewer than\b", "no fewer than"),
    (r"\bwithin the (?:last|past|previous)\b", "within the last"),
    (r"\bolder than\b", "older than"),
    (r"\bnewer than\b", "newer than"),
    (r"\bgreater than\b", "greater than"),
    (r"\bless than\b", "less than"),
    (r"\bexceeds?\b", "exceeds"),
    (r"\bunder the\b.{0,20}\blimit\b", "under the limit"),
    (r"\bwithin\b.{0,20}\blimit\b", "within the limit"),
    (r"\bhow many\b", "how many"),
    (r"\bcount\b", "count"),
    (r"[<>]=?|≤|≥", "a comparison operator"),
]


def lint_semantic(instructions: str, criteria: Any) -> None:
    """Refuse a semantic question that is really asking for a comparison.

    This is the check that would have caught the original mistake. The
    question "does `days_since_last_refund` satisfy the policy's requirement
    about recent refunds" reads as a judgment and is a subtraction.
    """
    blob = f"{instructions} {criteria!r}".lower()
    for pattern, name in _COMPARISON_IN_PROSE:
        if re.search(pattern, blob):
            raise PredicateMisrouted(
                f"semantic question contains {name!r}, which is a comparison. "
                "Jev is not a calculator and this is the shape that fails "
                "confidently rather than uncertainly. Express it as "
                "Comparison(left=..., op=..., right=...) so code evaluates it."
            )


@dataclass(frozen=True, slots=True)
class Comparison:
    """A numeric, date or duration comparison. Always evaluated in code."""

    id: str
    left: str  # state path, e.g. "request.days_since_last_refund"
    op: Literal["<", "<=", "==", ">=", ">", "!="]
    right: Any  # a literal, or a state path when prefixed with "$"
    unit: str | None = None  # e.g. "USD", "days" — a mismatch is unevaluable
    kind: PredicateKind = field(default=PredicateKind.COMPARISON, init=False)


@dataclass(frozen=True, slots=True)
class Identity:
    """Equality, membership or tenancy. Always evaluated in code.

    Never Jev: asked to judge entitlement directly it returned 0.78 "entitled"
    for a requester whose `user_id` matched and whose `account_id` did not.
    Cross-tenant isolation is one of the four controls that may not fail open.
    """

    id: str
    subject: str  # state path
    relation: Literal["equals", "in", "same_tenant_as"]
    object: Any  # literal, list, or "$path"
    kind: PredicateKind = field(default=PredicateKind.IDENTITY, init=False)


@dataclass(frozen=True, slots=True)
class Semantic:
    """A judgment with exactly one thing to weigh. Evaluated by Jev."""

    id: str
    instructions: str
    criteria: dict[str, Any]
    #: Names the single signal this question turns on. Required, because
    #: writing it down is what stops a second signal creeping in — the
    #: bundled duplicate question weighed merchant, amount, timing and
    #: descriptor at once and got 0.64 where the descriptor alone got 0.96.
    weighs: str
    #: State paths this question is shown. Context helps meaning questions:
    #: stripping it dropped a presupposed-approval case from 0.92 to 0.38.
    reads: tuple[str, ...] = ()
    kind: PredicateKind = field(default=PredicateKind.SEMANTIC, init=False)

    def __post_init__(self) -> None:
        lint_semantic(self.instructions, self.criteria)
        if not self.weighs.strip():
            raise PredicateMisrouted(
                f"semantic predicate {self.id!r} must name the one signal it weighs"
            )


@dataclass(frozen=True, slots=True)
class Selection:
    """Read a value out of prose. Code enumerates candidates, Jev picks.

    Selection is the one numeric-adjacent thing Jev does reliably: asked
    which number in a policy was the approval limit it answered at confidence
    1.00, in the same run where it got the comparison wrong.
    """

    id: str
    instructions: str
    candidates: dict[str, str]
    reads: tuple[str, ...] = ()
    kind: PredicateKind = field(default=PredicateKind.SELECTION, init=False)


Predicate = Comparison | Identity | Semantic | Selection


@dataclass(frozen=True, slots=True)
class Policy:
    """One policy, decomposed. `requires_all` is the conjunction to authorise."""

    key: str
    version: str
    predicates: tuple[Predicate, ...]
    requires_all: tuple[str, ...] = ()

    def by_kind(self, *kinds: PredicateKind) -> tuple[Predicate, ...]:
        return tuple(p for p in self.predicates if p.kind in kinds)
