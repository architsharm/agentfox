"""Assemble the judges an operator enabled, and ask as few of them as possible.

Every surface previously reached for `JevClient` directly, which made
"enable the LLM tier" a setting with no effect. This resolves a decision kind
into the judges permitted to answer it — `CapabilityRouter` for policy, each
judge for availability — and combines their answers as the routing table says.

**Cascade, not union, wherever more than one tier can answer.** The first
version asked every enabled tier on every decision and kept the highest score.
That is simple and it is wasteful: on injection it bought +0.1 F1 for a hosted
LLM call on 100% of traffic. Under a cascade a tier's answer ends the matter
unless it lands in that kind's uncertain band, and only the still-unsettled
questions are carried onward — so the expensive tiers see a fraction of the
traffic instead of all of it, and a tier with nothing left to answer is never
called at all.

What a cascade cannot do is rescue a tier that is *confidently wrong*: a band
catches uncertainty, not error. That is why the ordering is per-kind and comes
from measurement rather than from price — on performative work Jev scores 0.07
on an answer that settles a hire, so asking it first would end the cascade on
a wrong answer and never reach the tier that can see it.

Nothing here decides *whether* a tier may answer. That is the router's job,
and asking twice would be two places to get it wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from agentfox.detection.judgment.capability import EGRESS_TIERS, ROUTING, CapabilityRouter, Combine, DecisionKind, Tier
from agentfox.detection.judgment.egress import JudgmentGateway
from agentfox.detection.judgment.jev import JevAnswer, JevClient, JevResult, JevUnavailable

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
    #: Tiers actually called. Under a cascade this is usually shorter than
    #: `tiers`, and the difference is the money not spent.
    consulted: tuple[Tier, ...] = ()

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
    from agentfox.detection.judgment.llm import LlmJudge

    judge = LlmJudge()
    if judge.tier() is not tier or not judge.available():
        return None
    if tier in EGRESS_TIERS:
        return JudgmentGateway(judge, backend="remote")  # type: ignore[arg-type]
    # A self-hosted endpoint is inside the boundary: no gate, no redaction,
    # nothing to withhold. Wrapping it would refuse payloads that never leave.
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
    """The judges permitted *and* able to answer this kind, in cascade order."""
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
    """Ask the enabled judges in order, stopping as soon as a question settles.

    Under `Combine.CASCADE` an answer outside the kind's band ends that
    question; the rest are carried to the next tier. Any other mode asks
    everyone and keeps the highest score, which is what union means.

    Raises `JevUnavailable` only when *no* judge could answer at all, so one
    tier being down degrades to the others rather than failing the decision.
    """
    members = panel if panel is not None else judges_for(kind)
    if not members:
        raise JevUnavailable(f"no judgment tier is enabled for {kind.value}")

    rule = ROUTING[kind]
    cascading = rule.combine is Combine.CASCADE
    lo, hi = rule.band

    result = PanelResult(tiers=tuple(t for t, _ in members))
    consulted: list[Tier] = []
    pending = dict(questions)

    for tier, judge in members:
        if not pending:
            break  # everything settled; this tier is never called
        consulted.append(tier)
        try:
            answers = judge.ask(state, pending).answers
        except JevUnavailable as exc:
            result.failures[tier] = str(exc)
            log.info("judgment panel: %s unavailable (%s)", tier.value, exc)
            continue

        settled: list[str] = []
        for qid, answer in answers.items():
            best = result.answers.get(qid)
            if best is None or answer.value > best.value:
                result.answers[qid] = answer
            result.answered_by.setdefault(qid, []).append(tier)
            if cascading and not (lo < answer.value < hi):
                settled.append(qid)
        if cascading:
            for qid in settled:
                pending.pop(qid, None)

    result.consulted = tuple(consulted)
    if result.empty and result.failures:
        joined = "; ".join(f"{t.value}: {why}" for t, why in result.failures.items())
        raise JevUnavailable(joined)
    return result
