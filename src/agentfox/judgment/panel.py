"""Assemble the judges an operator has actually enabled, for one decision.

Every surface previously reached for `JevClient` directly, which made "enable
the LLM tier" a setting with no effect. This resolves a decision kind into the
set of judges permitted to answer it — consulting `CapabilityRouter` for
policy and each judge for availability — and combines their answers the way
the routing table says to.

Combination is union by score: a question's result is the highest probability
any permitted judge gave it. That matches what the benchmarks found wherever
more than one tier is allowed to answer, and it means adding a tier can raise
a score but never lower one, which is the monotonicity promise made in
`capability.py` carried through to the runtime.

Nothing here decides *whether* a tier may answer. That is the router's job,
and asking twice would be two places to get it wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from .capability import EGRESS_TIERS, CapabilityRouter, DecisionKind, Tier
from .egress import JudgmentGateway
from .jev import JevAnswer, JevClient, JevResult, JevUnavailable

log = logging.getLogger(__name__)


class Judge(Protocol):
    def available(self) -> bool: ...
    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> JevResult: ...


@dataclass(slots=True)
class PanelResult:
    answers: dict[str, JevAnswer] = field(default_factory=dict)
    answered_by: dict[str, list[Tier]] = field(default_factory=dict)
    tiers: tuple[Tier, ...] = ()
    failures: dict[Tier, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.answers


def _jev_judge() -> Judge | None:
    client = JevClient()
    if not client.available():
        return None
    # Everything hosted goes out through the gateway, which holds the egress
    # gate and the redaction. Judges never reach the network themselves.
    return JudgmentGateway(client, backend="remote")


def _llm_judge(tier: Tier) -> Judge | None:
    from .llm import LlmJudge

    judge = LlmJudge()
    if judge.tier() is not tier or not judge.available():
        return None
    if tier in EGRESS_TIERS:
        return JudgmentGateway(judge, backend="remote")  # type: ignore[arg-type]
    return judge


def permitted_tiers(kind: DecisionKind) -> tuple[Tier, ...]:
    """Tiers the router allows to *judge* this kind — policy only.

    Deliberately separate from `judges_for`, which also asks whether each one
    is reachable. A caller that injects its own transport (a test, or an
    operator wiring a bespoke judge) still has to pass this: supplying a
    client must never be a way around the routing table.
    """
    plan = CapabilityRouter.from_settings().plan(kind)
    return tuple(t for t in plan.deciders if t not in (Tier.DETERMINISTIC, Tier.LOCAL_MODEL))


def judges_for(kind: DecisionKind) -> list[tuple[Tier, Judge]]:
    """The judges permitted *and* able to answer this kind, in preference order."""
    plan = CapabilityRouter.from_settings().plan(kind)
    out: list[tuple[Tier, Judge]] = []
    for tier in plan.deciders:
        judge: Judge | None = None
        if tier is Tier.JEV:
            judge = _jev_judge()
        elif tier in (Tier.LLM, Tier.LOCAL_LLM):
            judge = _llm_judge(tier)
        # DETERMINISTIC and LOCAL_MODEL are answered by the detectors
        # themselves, not by a judge, so they are not assembled here.
        if judge is not None:
            out.append((tier, judge))
    return out


def ask(
    kind: DecisionKind,
    state: Any,
    questions: dict[str, dict[str, Any]],
    *,
    panel: list[tuple[Tier, Judge]] | None = None,
) -> PanelResult:
    """Ask every enabled judge, and keep the highest score per question.

    Raises `JevUnavailable` only when *no* judge could answer at all, so one
    tier being down degrades to the others rather than failing the decision.
    """
    members = panel if panel is not None else judges_for(kind)
    if not members:
        raise JevUnavailable(f"no judgment tier is enabled for {kind.value}")

    result = PanelResult(tiers=tuple(t for t, _ in members))
    for tier, judge in members:
        try:
            answers = judge.ask(state, questions).answers
        except JevUnavailable as exc:
            result.failures[tier] = str(exc)
            log.info("judgment panel: %s unavailable (%s)", tier.value, exc)
            continue
        for qid, answer in answers.items():
            best = result.answers.get(qid)
            if best is None or answer.value > best.value:
                result.answers[qid] = answer
            result.answered_by.setdefault(qid, []).append(tier)

    if result.empty and result.failures:
        joined = "; ".join(f"{t.value}: {why}" for t, why in result.failures.items())
        raise JevUnavailable(joined)
    return result
