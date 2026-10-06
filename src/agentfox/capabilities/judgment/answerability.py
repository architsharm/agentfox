"""A judgment layer over the deterministic answerability check.

`answerability.py` says, deliberately: "All deterministic: an answerability
check that itself calls a model inherits the failure it is meant to prevent."
That is right about *self*-assessment — asking the answering model whether it
knows reproduces exactly the overconfidence being guarded against. It is not
an argument against a separate, non-generating judgment model, which has no
answer to defend.

So the deterministic core stays untouched and authoritative, and this composes
with it from outside. The measured reason:

    KUQ + CoCoNot, 5,161 questions
      deterministic alone   83.5%   recall 38.1%   precision 95.1%
      + judgment (union)    93.5%   recall 90.9%
      contested questions   8.4% -> 84.3% recall

**This can only add an abstention, never remove one.** The deterministic layer
is precise (95.1%) and the union keeps everything it asked for; a judgment
that says "answerable" is ignored. That is what makes the composition safe to
turn on: the worst case is over-refusal, which the product already treats as
the lesser harm, and the best case is the 676 contested questions the regex
layer was catching 57 of.

The cost, which belongs next to the gain: over-refusal on genuinely answerable
questions rises from 0.75% to 5.37% on KUQ, and 0% to 3.69% on the CoCoNot
control. An operator enabling this is buying recall with precision.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from agentfox.capabilities.judgment import panel
from agentfox.capabilities.judgment.capability import DecisionKind
from agentfox.capabilities.judgment.egress import JudgmentGateway
from agentfox.capabilities.judgment.jev import JevUnavailable

if TYPE_CHECKING:  # pragma: no cover
    from agentfox.grounding.answerability import AnswerabilityVerdict

log = logging.getLogger(__name__)

#: Chosen on a dev half of KUQ and confirmed once on the held half: F1 87.8
#: dev, 87.5 held. Below 0.7 the over-refusal rate climbs faster than recall.
THRESHOLD = 0.7

QUESTIONS: dict[str, dict[str, Any]] = {
    "contested": {
        "type": "noul",
        "instructions": (
            "Read `question`. Is this a matter on which informed, reasonable "
            "people genuinely disagree, rather than one with a settled answer?"
        ),
        "criteria": {
            "what": (
                "The answer turns on values, taste, or a live dispute — there is "
                "no fact that would settle it."
            ),
            "not_for": (
                "There is a correct answer, even if it is obscure, technical, or "
                "the reader does not happen to know it."
            ),
        },
    },
    "not_yet_determined": {
        "type": "noul",
        "instructions": (
            "Read `question`. Does answering it require knowing something that "
            "has not happened or has not been determined yet?"
        ),
        "criteria": {
            "what": (
                "It asks about a future event, an undecided outcome, or something "
                "nobody could know at the time of asking."
            ),
            "not_for": (
                "It asks about something already established, whether in the past or the present."
            ),
        },
    },
}

#: Reuse the kinds the deterministic layer already emits, so downstream policy,
#: the operator log and the abstention metrics see nothing new. A contested
#: question is an opinion question, which is what UNSUPPORTED_TYPE means here;
#: one that cannot be known yet is UNKNOWABLE.
KIND = {"contested": "unsupported_question_type", "not_yet_determined": "unknowable"}

#: `_TEMPLATES` in answerability.py needs formatting arguments this layer does
#: not have (the boundary's systems, coverage dates). These say the same kind
#: of thing in the same voice: name what is missing rather than just refusing.
RESPONSE = {
    "contested": (
        "That is a question informed people genuinely disagree on rather than one "
        "with a recorded answer. I can set out the positions, but I would be "
        "inventing authority if I picked one."
    ),
    "not_yet_determined": (
        "That asks for something that has not been determined yet. I can only "
        "report what is already recorded, so I do not have an answer for it."
    ),
}


def enabled(gateway: JudgmentGateway | None = None) -> bool:
    """True when some enabled tier can answer this kind — Jev, an LLM, or both.

    An injected `gateway` supplies the transport, never the permission: the
    routing table still has to allow a judgment tier for this kind.
    """
    if not panel.permitted_tiers(DecisionKind.SEMANTIC):
        return False
    return gateway is not None or bool(panel.judges_for(DecisionKind.SEMANTIC))


def _ask(state, questions, gateway: JudgmentGateway | None):
    """Every enabled tier, unioned by score. `gateway` is for tests."""
    if gateway is not None:
        return gateway.ask(state, questions).answers
    return panel.ask(DecisionKind.SEMANTIC, state, questions).answers


def augment(
    verdict: AnswerabilityVerdict,
    question: str,
    *,
    gateway: JudgmentGateway | None = None,
    threshold: float = THRESHOLD,
) -> AnswerabilityVerdict:
    """Add an abstention the deterministic layer missed. Never remove one.

    Returns `verdict` unchanged when the tier is off, the judgment cannot be
    made, or nothing fires — so a caller can apply this unconditionally.
    """
    if not verdict.answerable:
        return verdict  # already abstaining; nothing to add
    if not question.strip() or not enabled(gateway):
        return verdict
    try:
        answers = _ask({"question": question}, QUESTIONS, gateway)
    except JevUnavailable as exc:
        # Degrading to the deterministic verdict is the safe direction here:
        # it is the behaviour the product has today.
        log.info("answerability judgment unavailable: %s", exc)
        return verdict

    fired = [
        (qid, answers[qid].value)
        for qid in QUESTIONS
        if qid in answers and answers[qid].value >= threshold
    ]
    if not fired:
        return verdict
    qid, score = max(fired, key=lambda kv: kv[1])
    return replace(
        verdict,
        answerable=False,
        abstention_kind=KIND.get(qid, "unknowable"),
        response=verdict.response or RESPONSE.get(qid, ""),
        reasons=[
            *verdict.reasons,
            {
                "check": "judgment",
                "question": qid,
                "score": round(float(score), 3),
                "engine": "jev",
                "reason": (
                    "no settled answer: informed people disagree"
                    if qid == "contested"
                    else "cannot be known yet"
                ),
            },
        ],
    )
