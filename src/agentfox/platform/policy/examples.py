"""Saved examples for a rule, re-checked against every proposed change to it.

The week-of-traffic replay answers "how much would this change move?". It cannot
answer "does the rule still catch *the* case it was written for?", because that case
may not have happened this week. An operator who saves the message that motivated a
rule — and one that must never trip it — gets that answer on every change.

An example is a recorded decision plus an expectation (the rule fires, or it does
not). Re-checking re-evaluates the decision's stored detections and context against
the candidate policy, the same deterministic replay `simulate` uses, so the policy
change is the only variable. Examples are kept as eval cases in one suite per rule
(``rule:<rule_id>``), so they also show up wherever eval suites do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Decision, EvalCase, EvalSuite
from agentfox.platform.policy.engine import NativePolicyEngine
from agentfox.platform.policy.model import PolicyDocument
from agentfox.platform.policy.simulate import policy_input_from_decision

TAG = "rule-examples"
MAX_PER_RULE = 50


def suite_key(rule_id: str) -> str:
    return f"rule:{rule_id}"


def _suite(session: Session, rule_id: str, *, create: bool = False) -> EvalSuite | None:
    suite = session.scalar(select(EvalSuite).where(EvalSuite.key == suite_key(rule_id)))
    if suite is None and create:
        suite = EvalSuite(
            key=suite_key(rule_id),
            name=f"Examples for {rule_id}",
            description="Saved on the rule's page; re-checked before every change to it.",
            tags=[TAG],
        )
        session.add(suite)
        session.flush()
    return suite


@dataclass
class Example:
    id: str
    decision_id: str
    fires: bool
    surface: str
    sample: str
    trace_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "decision_id": self.decision_id,
            "fires": self.fires,
            "surface": self.surface,
            "sample": self.sample,
            "trace_id": self.trace_id,
        }


def _example(case: EvalCase) -> Example:
    data = case.input_json or {}
    return Example(
        id=case.id,
        decision_id=str(data.get("decision_id", "")),
        fires=bool((case.expected_json or {}).get("fires")),
        surface=str(data.get("surface", "")),
        sample=str(data.get("sample", "")),
        trace_id=case.source_trace_id,
    )


def list_examples(session: Session, rule_id: str) -> list[Example]:
    suite = _suite(session, rule_id)
    if suite is None:
        return []
    cases = session.scalars(
        select(EvalCase).where(EvalCase.suite_id == suite.id).order_by(EvalCase.created_at)
    )
    return [_example(c) for c in cases]


def add_example(
    session: Session, rule_id: str, decision_id: str, *, fires: bool, sample: str = ""
) -> Example:
    decision = session.get(Decision, decision_id)
    if decision is None:
        raise LookupError(f"no decision '{decision_id}'")
    suite = _suite(session, rule_id, create=True)
    existing = list_examples(session, rule_id)
    if len(existing) >= MAX_PER_RULE:
        raise ValueError(f"a rule keeps at most {MAX_PER_RULE} examples")
    if any(e.decision_id == decision_id for e in existing):
        raise ValueError("that example is already saved")
    case = EvalCase(
        suite_id=suite.id,
        input_json={
            "decision_id": decision_id,
            "surface": decision.surface,
            "sample": sample[:200],
        },
        expected_json={"fires": fires},
        labels=[rule_id],
        source_trace_id=decision.trace_id,
    )
    session.add(case)
    session.flush()
    return _example(case)


def delete_example(session: Session, rule_id: str, example_id: str) -> bool:
    suite = _suite(session, rule_id)
    case = session.get(EvalCase, example_id)
    if suite is None or case is None or case.suite_id != suite.id:
        return False
    session.delete(case)
    session.flush()
    return True


@dataclass
class Check:
    example: Example
    fired: bool | None  # None: the recorded decision is gone

    @property
    def passed(self) -> bool:
        return self.fired is not None and self.fired == self.example.fires

    def to_json(self) -> dict[str, Any]:
        return {**self.example.to_json(), "fired": self.fired, "passed": self.passed}


def check(session: Session, rule_id: str, candidate: PolicyDocument) -> list[Check]:
    """Does ``rule_id`` in ``candidate`` still do what each saved example expects?"""
    engine = NativePolicyEngine()
    doc = candidate.model_copy(update={"mode": "enforce"}, deep=True)
    out: list[Check] = []
    for example in list_examples(session, rule_id):
        decision = session.get(Decision, example.decision_id)
        if decision is None:
            out.append(Check(example, None))
            continue
        pinput = policy_input_from_decision(session, decision)
        fired = any(r.rule_id == rule_id for r in engine.evaluate(doc, pinput).rules_fired)
        out.append(Check(example, fired))
    return out
