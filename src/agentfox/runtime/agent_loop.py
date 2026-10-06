"""Governing the loop, not just the step.

Every control in this system is invoked per call: is this tool permitted, is this
argument tainted, is this statement destructive. The enforcer already counts how often
one tool has been called and how deep the path has gone, which catches the simplest
runaway — the same tool, over and over.

It does not catch the shapes that actually occur. An agent alternating between two
tools never repeats either one three times in a row. An agent re-issuing a query it
already answered makes progress by every counter that exists and none at all in fact.
An agent that keeps calling *different* tools while the world does not change looks,
step by step, exactly like an agent working.

What is missing is a view of the run rather than the step. That view is cheap to
maintain and answers a different question: not "is this call allowed" but "is this run
getting anywhere". The three signals below are the ones visible without understanding
the task, which is the constraint that makes this deterministic:

* **Repetition of a call.** The same tool with the same arguments, twice. Whatever the
  first one returned is still true; the second is the agent asking again because it did
  not know what to do with the answer.
* **Cycles in the sequence.** A→B→A→B is a loop that per-tool counting cannot see,
  because neither tool has repeated consecutively.
* **Absence of new state.** Steps continuing while every observation matches one
  already seen. This is the general case of the other two and the one that catches
  shapes nobody enumerated.

Stopping is a verdict with a reason attached, not a silent cap. An agent halted at step
40 with "budget exhausted" tells an operator nothing; halted with "steps 12-40 produced
no observation that had not already been seen" tells them where to look.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from agentfox.capabilities.containment.effects import _canonical

CONTINUE = "continue"
STOP = "stop"
ESCALATE = "escalate"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()[:16]


@dataclass
class Step:
    """One tool call and what came back."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    observation: Any = None

    @property
    def call_fingerprint(self) -> str:
        return _fingerprint({"tool": self.tool, "arguments": self.arguments})

    @property
    def observation_fingerprint(self) -> str:
        # Canonicalized first (effects._canonical: stable dict ordering, float
        # formatting, whitespace) so two observations that are the same result in
        # every way that matters — a timestamp or request id aside — fingerprint
        # identically. Without this, "no new observation" only ever caught a
        # byte-for-byte repeat, which a cosmetic diff defeats trivially.
        return _fingerprint(_canonical(self.observation))


@dataclass
class LoopBudget:
    """The declared shape of a legitimate run."""

    max_steps: int = 25
    max_repeats: int = 2
    #: Length of the repeating sequence to look for. 2 catches A-B-A-B, 3 catches
    #: A-B-C-A-B-C. Above 4 the pattern is usually a legitimate pipeline.
    max_cycle_length: int = 4
    #: Consecutive steps producing nothing new before the run is considered stuck.
    max_steps_without_progress: int = 5
    #: When set, the effective `max_steps_without_progress` threshold decays
    #: linearly from its full value at this step index down to 1 at `max_steps` —
    #: a step deep into a long run is judged more strictly than an early one,
    #: using only the step index already tracked, no new state. `None` (the
    #: default) keeps the threshold flat.
    decay_from_depth: int | None = None

    def effective_max_steps_without_progress(self, index: int) -> int:
        if self.decay_from_depth is None or index <= self.decay_from_depth:
            return self.max_steps_without_progress
        span = max(1, self.max_steps - self.decay_from_depth)
        progressed = min(index - self.decay_from_depth, span)
        decayed = self.max_steps_without_progress * (1 - progressed / span)
        return max(1, round(decayed))


@dataclass
class LoopVerdict:
    decision: str
    reason: str = ""
    step: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def stopped(self) -> bool:
        return self.decision != CONTINUE

    def to_json(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "step": self.step,
            "evidence": self.evidence,
        }


class LoopGovernor:
    """Watches a run and says when it has stopped getting anywhere.

    Stateful by necessity — every signal here is about the relationship between steps,
    which is exactly what a per-call control cannot see.
    """

    def __init__(self, budget: LoopBudget | None = None) -> None:
        self.budget = budget or LoopBudget()
        self.steps: list[Step] = []
        self._seen_observations: set[str] = set()
        self._steps_without_progress = 0

    def observe(self, step: Step) -> LoopVerdict:
        """Record a step and decide whether the run may continue."""
        self.steps.append(step)
        index = len(self.steps)

        if step.observation_fingerprint in self._seen_observations:
            self._steps_without_progress += 1
        else:
            self._seen_observations.add(step.observation_fingerprint)
            self._steps_without_progress = 0

        if index > self.budget.max_steps:
            return LoopVerdict(
                STOP,
                f"the run passed its {self.budget.max_steps}-step budget",
                index,
                {"steps": index},
            )

        repeats = sum(1 for s in self.steps if s.call_fingerprint == step.call_fingerprint)
        if repeats > self.budget.max_repeats:
            return LoopVerdict(
                STOP,
                f"'{step.tool}' has been called {repeats} times with identical "
                "arguments. Whatever it returned the first time is still true; the "
                "agent is asking again because it did not know what to do with the "
                "answer",
                index,
                {"tool": step.tool, "repeats": repeats},
            )

        if cycle := self._cycle():
            return LoopVerdict(
                STOP,
                f"the sequence {' → '.join(cycle)} is repeating. Per-tool counting "
                "cannot see this: neither tool repeats consecutively",
                index,
                {"cycle": cycle},
            )

        threshold = self.budget.effective_max_steps_without_progress(index)
        if self._steps_without_progress >= threshold:
            first = index - self._steps_without_progress
            return LoopVerdict(
                ESCALATE,
                f"steps {first}-{index} produced no observation that had not already "
                "been seen. The run is active and not advancing",
                index,
                {
                    "steps_without_progress": self._steps_without_progress,
                    "from_step": first,
                    "to_step": index,
                },
            )

        return LoopVerdict(CONTINUE, step=index)

    def _cycle(self) -> list[str] | None:
        """The shortest repeating tail, if the sequence has one."""
        tools = [s.tool for s in self.steps]
        for length in range(2, self.budget.max_cycle_length + 1):
            if len(tools) < length * 2:
                continue
            tail, before = tools[-length:], tools[-length * 2 : -length]
            if tail == before and len(set(tail)) > 1:
                return tail
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "steps": len(self.steps),
            "distinct_observations": len(self._seen_observations),
            "steps_without_progress": self._steps_without_progress,
            "tools": [s.tool for s in self.steps],
        }


def govern_loop(
    steps: list[Step] | list[dict[str, Any]], *, budget: LoopBudget | None = None
) -> LoopVerdict:
    """Replay a completed or in-flight run and return the first verdict that stopped it.

    Convenience over :class:`LoopGovernor` for callers holding a trace rather than
    driving the loop — the offline path used by attribution and evaluation.
    """
    governor = LoopGovernor(budget)
    last = LoopVerdict(CONTINUE)
    for raw in steps:
        step = (
            raw
            if isinstance(raw, Step)
            else Step(
                tool=str(raw.get("tool", "")),
                arguments=raw.get("arguments") or {},
                observation=raw.get("observation"),
            )
        )
        last = governor.observe(step)
        if last.stopped:
            return last
    return last
