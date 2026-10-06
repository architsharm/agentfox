"""Which source is the answer allowed to come from, and when to stop and ask.

Provenance already ranks *retrieved documents* by tier, and conflict detection already
notices when two chunks disagree about a number. Both operate after the fact, on text
that has already been fetched. Neither governs the decision that determines everything
downstream: **which system the agent went to in the first place**.

In any real estate there are several. Balance is in the ledger, in the CRM, in last
night's warehouse extract, and in a cached summary. Three of those will answer, quickly
and confidently, and one of them is the system of record. Nothing in a trace
distinguishes "the agent consulted the ledger" from "the agent consulted whichever tool
came first in the list" — both look like a successful tool call returning a number.

Two failures follow, and the second is the interesting one.

**Using an available lesser source.** The warehouse extract answers, so the agent never
calls the ledger. The number is twelve hours old, the answer is grounded, cited and
wrong. This is checkable: if an authoritative source for the topic was reachable and a
lesser one was used, say so.

**Silently resolving a disagreement.** Two sources answer and the values differ. Every
system in this space picks one — highest tier, first result, most recent — and picking
is the mistake. A material disagreement between two systems of record is not a ranking
problem, it is *information*: something is out of sync, and the person asking is
usually the one who can say which reading is right. So the outcome here is neither
"answer from the best source" nor "block", but **confirm**: stop, state the
disagreement, name the alternatives, and let a human settle it.

That step is cheap and it is the one thing that converts a silent wrong answer into an
obviously-answerable question. It is modelled as a first-class result rather than a
policy someone can configure away, because a system that resolves conflicts quietly
will always look better in a demo and worse in production.

A note on where ``confirm`` sits, because it is not another rung on the enforcement
lattice. That lattice — allow, tokenize, mask, redact, abstain, escalate, block — is
ordered by how much of the answer survives, and every rung is terminal: the turn ends
with whatever the verdict allowed. ``confirm`` is not terminal. It is a precondition
that suspends the turn and resumes it with an answer that did not exist before, which
is why it cannot be expressed as "escalate, but softer". Escalate hands the work to
someone else; confirm hands back a fact and takes the work again. Composing the two is
therefore not a maximum: a request that must confirm *and* would be blocked is blocked,
because there is no point asking a question whose answer changes nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentfox.capabilities.grounding.provenance import TIER_RANK, UNVERIFIED

# --- Declaration -----------------------------------------------------------


@dataclass(frozen=True)
class SourceAuthority:
    """One place an answer can come from, and how much standing it has."""

    key: str
    #: system_of_record | approved | unverified | external
    tier: str = UNVERIFIED
    #: Topics this source is authoritative for. Empty means general purpose.
    topics: tuple[str, ...] = ()
    #: How stale its answer can be before its standing is reduced.
    max_age_seconds: int | None = None

    def covers(self, topic: str) -> bool:
        return not self.topics or topic.lower() in {t.lower() for t in self.topics}


@dataclass
class Reading:
    """What one source actually said."""

    source: str
    value: Any
    age_seconds: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {"source": self.source, "value": self.value, "age_seconds": self.age_seconds}


# --- The confirmation step -------------------------------------------------


@dataclass
class ConfirmationStep:
    """A question to put to a person before the answer is allowed to proceed.

    Structured rather than a free-text prompt so the runtime can render it, record the
    response against the decision, and replay it in evidence. A confirmation nobody can
    reconstruct afterwards is a pause, not a control.
    """

    question: str
    options: list[str] = field(default_factory=list)
    because: str = ""
    topic: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "options": self.options,
            "because": self.because,
            "topic": self.topic,
        }


@dataclass
class ArbitrationFinding:
    code: str
    detail: str
    severity: str = "high"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "severity": self.severity,
            "evidence": self.evidence,
        }


@dataclass
class Arbitration:
    """Which source should answer, and whether a person has to be asked first."""

    topic: str = ""
    chosen: str | None = None
    authoritative: list[str] = field(default_factory=list)
    findings: list[ArbitrationFinding] = field(default_factory=list)
    confirmation: ConfirmationStep | None = None

    @property
    def verdict(self) -> str:
        if self.confirmation is not None:
            return "confirm"
        severities = {f.severity for f in self.findings}
        if "critical" in severities:
            return "block"
        return "escalate" if severities else "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "chosen": self.chosen,
            "authoritative": self.authoritative,
            "verdict": self.verdict,
            "confirmation": self.confirmation.to_json() if self.confirmation else None,
            "findings": [f.to_json() for f in self.findings],
        }


# --- Comparison ------------------------------------------------------------

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and (match := _NUMBER.search(value)):
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:
            return None
    return None


def materially_differ(a: Any, b: Any, *, tolerance: float = 0.01) -> bool:
    """Whether two readings disagree in a way anyone would act on.

    Numbers are compared relatively, because £0.01 on a £4,000 balance is a rounding
    difference and reporting it would train people to dismiss the pair that matters.
    Anything non-numeric is compared after normalising whitespace and case — a
    paraphrase is a genuine disagreement between two systems of record about what the
    record says, and this deliberately does not try to decide otherwise.
    """
    left, right = _as_number(a), _as_number(b)
    if left is not None and right is not None:
        scale = max(abs(left), abs(right), 1.0)
        return abs(left - right) / scale > tolerance
    return " ".join(str(a).lower().split()) != " ".join(str(b).lower().split())


# --- Arbitration -----------------------------------------------------------


def arbitrate(
    topic: str,
    readings: list[Reading],
    *,
    sources: list[SourceAuthority],
    tolerance: float = 0.01,
    require_confirmation: bool = True,
) -> Arbitration:
    """Decide which reading may be used, or stop and ask.

    ``require_confirmation`` exists so an operator can turn a confirm into an escalate
    for a low-stakes topic. It cannot turn it into an allow: the disagreement is a fact
    about the estate, and a setting that made it disappear would be a setting for
    producing confident wrong answers.
    """
    by_key = {s.key: s for s in sources}
    result = Arbitration(topic=topic)

    covering = [s for s in sources if s.covers(topic)]
    best_rank = min((TIER_RANK.get(s.tier, 9) for s in covering), default=9)
    result.authoritative = sorted(s.key for s in covering if TIER_RANK.get(s.tier, 9) == best_rank)

    if not readings:
        return result

    ranked = sorted(
        readings,
        key=lambda r: (
            TIER_RANK.get(by_key[r.source].tier, 9) if r.source in by_key else 9,
            r.age_seconds if r.age_seconds is not None else 0,
        ),
    )
    result.chosen = ranked[0].source

    for reading in readings:
        source = by_key.get(reading.source)
        if source is None:
            result.findings.append(
                ArbitrationFinding(
                    "undeclared-source",
                    f"'{reading.source}' answered and has no declared standing, so there is "
                    "nothing to weigh it against",
                    "high",
                    {"source": reading.source},
                )
            )
            continue
        if (
            source.max_age_seconds is not None
            and reading.age_seconds is not None
            and reading.age_seconds > source.max_age_seconds
        ):
            result.findings.append(
                ArbitrationFinding(
                    "stale-reading",
                    f"'{reading.source}' answered from data {reading.age_seconds}s old, "
                    f"past its {source.max_age_seconds}s limit",
                    "high",
                    {"source": reading.source, "age_seconds": reading.age_seconds},
                )
            )

    # --- a lesser source was used while an authoritative one was reachable
    used = {r.source for r in readings}
    if result.authoritative and not (used & set(result.authoritative)):
        result.findings.append(
            ArbitrationFinding(
                "authoritative-source-bypassed",
                f"{sorted(used)} answered for '{topic}' while {result.authoritative} is the "
                "system of record and was not consulted. The answer will be grounded, cited "
                "and out of date",
                "critical",
                {"used": sorted(used), "authoritative": result.authoritative},
            )
        )

    # --- disagreement
    disagreeing = _disagreements(readings, tolerance)
    if disagreeing:
        pair = disagreeing[0]
        result.findings.append(
            ArbitrationFinding(
                "sources-disagree",
                f"'{pair[0].source}' says {pair[0].value!r} and '{pair[1].source}' says "
                f"{pair[1].value!r}. Picking one is the mistake — the disagreement means "
                "something is out of sync, and that is the finding",
                "critical",
                {"readings": [r.to_json() for r in readings]},
            )
        )
        if require_confirmation:
            result.confirmation = ConfirmationStep(
                question=f"Two systems disagree about {topic}. Which should be used?",
                options=[f"{r.source}: {r.value}" for r in readings],
                because=(
                    "a material disagreement between systems is information, not a "
                    "ranking problem, and the person asking is usually the one who can "
                    "say which reading is right"
                ),
                topic=topic,
            )

    return result


def _disagreements(readings: list[Reading], tolerance: float) -> list[tuple[Reading, Reading]]:
    out: list[tuple[Reading, Reading]] = []
    for i, left in enumerate(readings):
        for right in readings[i + 1 :]:
            if materially_differ(left.value, right.value, tolerance=tolerance):
                out.append((left, right))
    return out


def confirmation_for_ambiguous_source(
    topic: str, candidates: list[SourceAuthority]
) -> ConfirmationStep | None:
    """Ask which system to use *before* querying, when the choice is not determined.

    The cheapest place to resolve this is in front of the tool call, not after two of
    them have returned different numbers. Only raised when several sources share the
    top tier for the topic — one clear winner needs no question, and asking anyway is
    how a confirmation step becomes a dialog people click through.
    """
    covering = [s for s in candidates if s.covers(topic)]
    if len(covering) < 2:
        return None
    best = min(TIER_RANK.get(s.tier, 9) for s in covering)
    tied = [s.key for s in covering if TIER_RANK.get(s.tier, 9) == best]
    if len(tied) < 2:
        return None
    return ConfirmationStep(
        question=f"Several systems are equally authoritative for {topic}. Which should answer?",
        options=sorted(tied),
        because="the answer depends on which system is consulted, and nothing in the "
        "declaration decides between them",
        topic=topic,
    )
