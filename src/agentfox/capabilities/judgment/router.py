"""Route each predicate to whoever can actually evaluate it, then compose.

Code takes every comparison and every identity check. Jev takes the semantic
ones, all of them in a single request. Code composes the answers.

Three invariants, each one bought by a measured failure:

**Unevaluable is a verdict, not a fall-through.** 45 GBP against a 50 USD
limit has no answer without a rate. Jev scored it 0.58 "within"; every GBP
amount scored 0.58-0.64 regardless of size, so it was not converting at all.
Code returns UNKNOWN and the composer escalates.

**A judgment may raise severity and never clear it.** Every failure we
measured was an under-flag — the guardrail letting through what it should
have stopped. ``authorise`` therefore starts at "not authorised" and only a
code predicate can discharge it.

**Unknown beats satisfied.** A missing operand is not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agentfox.capabilities.judgment.jev import JevClient, JevResult, JevUnavailable
from agentfox.capabilities.judgment.predicate import (
    Comparison,
    Identity,
    Policy,
    PredicateKind,
    Semantic,
)


class Outcome(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"  # could not be evaluated — escalates


@dataclass(slots=True)
class PredicateResult:
    id: str
    kind: PredicateKind
    outcome: Outcome
    detail: str = ""
    probability: float | None = None
    evaluated_by: str = "code"


@dataclass(slots=True)
class Decision:
    authorised: bool
    escalate: bool
    results: dict[str, PredicateResult] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)
    jev_ms: float = 0.0
    jev_input_tokens: int = 0

    def reasons(self) -> list[str]:
        return [
            f"{r.id}: {r.detail}"
            for r in self.results.values()
            if r.outcome is not Outcome.SATISFIED
        ]


def resolve(state: Any, path: str) -> Any:
    """Read a dotted path. Missing is None, never an exception."""
    cur = state
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def _operand(state: Any, value: Any) -> Any:
    return resolve(state, value[1:]) if isinstance(value, str) and value.startswith("$") else value


_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
}


def eval_comparison(p: Comparison, state: Any) -> PredicateResult:
    left = resolve(state, p.left)
    right = _operand(state, p.right)
    if left is None or right is None:
        return PredicateResult(p.id, p.kind, Outcome.UNKNOWN, "operand missing")
    if p.unit:
        # A unit that does not match is not a comparison, it is a conversion,
        # and there is no rate in state. 45 GBP against a 50 USD limit.
        actual = resolve(state, p.left.rsplit(".", 1)[0] + ".currency") or p.unit
        if actual != p.unit:
            return PredicateResult(
                p.id,
                p.kind,
                Outcome.UNKNOWN,
                f"value is in {actual}, limit is {p.unit}, no rate in state",
            )
    try:
        ok = _OPS[p.op](float(left), float(right))
    except (TypeError, ValueError):
        return PredicateResult(
            p.id, p.kind, Outcome.UNKNOWN, f"not comparable: {left!r} {p.op} {right!r}"
        )
    return PredicateResult(
        p.id,
        p.kind,
        Outcome.SATISFIED if ok else Outcome.VIOLATED,
        f"{left} {p.op} {right}",
    )


def eval_identity(p: Identity, state: Any) -> PredicateResult:
    subject = resolve(state, p.subject)
    obj = _operand(state, p.object)
    if subject is None or obj is None:
        return PredicateResult(p.id, p.kind, Outcome.UNKNOWN, "operand missing")
    if p.relation == "equals":
        ok = subject == obj
    elif p.relation == "in":
        ok = isinstance(obj, (list, tuple, set)) and subject in obj
    else:  # same_tenant_as — never a judgment, see the module docstring
        ok = subject == obj
    return PredicateResult(
        p.id,
        p.kind,
        Outcome.SATISFIED if ok else Outcome.VIOLATED,
        f"{p.subject}={subject!r} {p.relation} {obj!r}",
    )


def project(state: Any, reads: tuple[str, ...]) -> Any:
    """The slice of state a question is shown. Empty `reads` means all of it."""
    if not reads:
        return state
    out: dict[str, Any] = {}
    for path in reads:
        value = resolve(state, path)
        if value is not None:
            out[path.replace(".", "_")] = value
    return out


class Router:
    def __init__(self, client: JevClient | None = None, *, threshold: float = 0.5) -> None:
        self._client = client or JevClient()
        self._threshold = threshold

    def evaluate(self, policy: Policy, state: Any) -> Decision:
        results: dict[str, PredicateResult] = {}
        degraded: list[str] = []

        for p in policy.by_kind(PredicateKind.COMPARISON, PredicateKind.IDENTITY):
            results[p.id] = (
                eval_comparison(p, state) if isinstance(p, Comparison) else eval_identity(p, state)
            )

        model_preds = policy.by_kind(PredicateKind.SEMANTIC, PredicateKind.SELECTION)
        jev = JevResult()
        if model_preds:
            # One request for every semantic question in the policy. Latency
            # is flat in question count, so splitting only adds round trips.
            questions: dict[str, dict[str, Any]] = {}
            shown: dict[str, Any] = {}
            for p in model_preds:
                if isinstance(p, Semantic):
                    questions[p.id] = {
                        "type": "noul",
                        "instructions": p.instructions,
                        "criteria": p.criteria,
                    }
                else:
                    questions[p.id] = {
                        "type": "choice",
                        "instructions": p.instructions,
                        "criteria": p.candidates,
                    }
                sub = project(state, p.reads)
                if isinstance(sub, dict):
                    shown.update(sub)
            try:
                jev = self._client.ask(shown or state, questions)
            except JevUnavailable as exc:
                # A judgment that could not run is a gap, not a pass.
                for p in model_preds:
                    results[p.id] = PredicateResult(
                        p.id,
                        p.kind,
                        Outcome.UNKNOWN,
                        f"judgment unavailable: {exc}",
                        evaluated_by="jev",
                    )
                degraded.append(f"jev: {exc}")
            else:
                for p in model_preds:
                    a = jev.answers.get(p.id)
                    if a is None:
                        results[p.id] = PredicateResult(
                            p.id, p.kind, Outcome.UNKNOWN, "no answer returned", evaluated_by="jev"
                        )
                        continue
                    if a.type == "noul":
                        results[p.id] = PredicateResult(
                            p.id,
                            p.kind,
                            Outcome.SATISFIED if a.value >= self._threshold else Outcome.VIOLATED,
                            f"p={a.value:.2f}",
                            probability=a.value,
                            evaluated_by="jev",
                        )
                    else:
                        results[p.id] = PredicateResult(
                            p.id,
                            p.kind,
                            Outcome.SATISFIED,
                            f"selected {a.value!r}",
                            probability=a.confidence,
                            evaluated_by="jev",
                        )

        required = policy.requires_all or tuple(results)
        outcomes = [results[k].outcome for k in required if k in results]
        authorised = bool(outcomes) and all(o is Outcome.SATISFIED for o in outcomes)
        escalate = any(o is Outcome.UNKNOWN for o in outcomes)
        return Decision(
            authorised=authorised and not escalate,
            escalate=escalate,
            results=results,
            degraded=degraded,
            jev_ms=jev.duration_ms,
            jev_input_tokens=jev.input_tokens,
        )
