"""P7 — answerability and abstention. Genuinely unclaimed across OSS and commercial.

*"If someone asks for future sales, the answer should be 'data not available', not a
generated one."*

Everything in the competitive set scores an answer **after** it exists: Cleanlab TLM,
Vectara HHEM, RAGAS, Galileo, Patronus all take a generated response and judge it.
That is a fundamentally different control from refusing to generate one, and it cannot
address F1 — by the time you are scoring, the number has been invented, and a
confident wrong number scored at 0.4 is still a confident wrong number in front of a
user.

**Nobody refuses to generate based on a declared coverage boundary.** That is the
claim, and it turns on the one thing a model cannot know about itself: what the index
behind it actually contains. AbstentionBench (20 datasets, 35k+ unanswerable queries)
found that reasoning fine-tuning frequently *degrades* abstention — the more capable
model is worse at saying "I don't know" — which is exactly what you would expect if
abstention is a property of the *system's* knowledge boundary rather than of the
model's reasoning.

So the boundary is declared, not inferred: which systems of record the agent can
reach, what time range they cover, which entity scopes exist, and which question
*types* are answerable at all. Four deterministic classifiers run pre-flight, and an
unanswerable question is answered from a template without a model call.

**The counter-metric is the point of the design.** Over-refusal (F1.5) kills adoption
faster than hallucination does, and the AAAI 2026 work on retrieval-augmented refusal
shows retrieval noise pushing models to refuse questions they could answer. So: every
abstention is recorded, over-refusal is detected and raises a finding, and the whole
pillar ships observe-first. Refusing to answer is a product decision with a cost, and
pretending otherwise produces an agent nobody uses.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .findings import raise_finding as _raise_finding
from .models import Agent, Finding, KnowledgeBoundary, utcnow

log = logging.getLogger(__name__)

# Question types an agent may be declared able to answer.
FACT = "fact"
AGGREGATE = "aggregate"
PREDICTION = "prediction"
OPINION = "opinion"
PROCEDURE = "procedure"
QUESTION_TYPES = (FACT, AGGREGATE, PREDICTION, OPINION, PROCEDURE)

# Why an answer was refused. Each maps to a distinct template — "I don't know" is a
# worse answer than "I hold 24 months and you asked about 2019".
OUT_OF_COVERAGE = "out_of_coverage"
OUT_OF_SCOPE_ENTITY = "out_of_scope_entity"
UNSUPPORTED_TYPE = "unsupported_question_type"
OUT_OF_DOMAIN = "out_of_domain"
UNKNOWABLE = "unknowable"

# --- Question-type markers -------------------------------------------------

#: F1.1/F1.4 — the future tense is the single highest-signal marker there is. A
#: question about what *will* happen cannot be answered from a system of record,
#: whatever the model's confidence.
PREDICTION_MARKERS = [
    r"\bwill\s+(?:\w+\s+){0,3}(?:be|become|reach|grow|fall|rise|drop|increase|decrease)\b",
    r"\b(?:forecast|predict|projection|projected|expected to|anticipate)\w*\b",
    r"\bhow much .{0,30}(?:next|coming|future|upcoming)\b",
    r"\b(?:next|coming|following|upcoming)\s+(?:year|quarter|month|week)\b",
    r"\b(?:q[1-4]\s*)?20[3-9]\d\b",  # a year far enough out to be a forecast
    r"\bgoing to\s+(?:be|reach|hit|grow)\b",
    # Structural future-question shapes that don't depend on a fixed verb list —
    # benchmarked on KUQ (benchmarks/answerability/README.md): these four raise
    # future-tense recall 39.0% -> 69.0% for 2 new false positives out of 3,826
    # benign rows tested, both defensible edge cases. Deliberately structural
    # (question-initial "will", explicit relative-future phrasing) rather than a
    # wider verb whitelist, which benchmarked far noisier for the same recall.
    r"^\s*will\s+\w",  # inverted yes/no future question: "Will X ever Y?"
    r"\bwhen\s+will\b",
    r"\b\d+\s+years?\s+from\s+now\b",
    r"\bin\s+(?:the\s+next\s+)?\d+\s+years?\b",
    r"\b(?:fifty|forty|thirty|twenty|ten|hundred)\s+years?\s+from\s+now\b",
    # Hypothetical/conditional forecast shapes — the same structural-not-vocabulary
    # discipline as the four above. Candidates tested against `known` + CoCoNot
    # before shipping; see benchmarks/answerability/README.md.
    r"\bwhat if\b.{0,80}\b(?:would|might|could)\b",
    r"\bhow might\b.{0,40}\b(?:impact|shape|change|affect|influence)\b",
]

_OPINION_MARKERS = [
    r"\b(?:should i|do you (?:think|believe)|what do you (?:think|reckon)|in your opinion)\b",
    r"\b(?:is it (?:a good|worth)|would you recommend)\b",
    r"\bbest\s+(?:choice|option|approach)\s+for me\b",
    # Third-person subjective/debatable framing — benchmarked on KUQ's
    # "controversial" category (benchmarks/answerability/README.md): raises
    # recall 0.74% -> 5.62% for 1 new false positive out of 3,447 benign rows.
    # A real, disclosed ceiling remains: most debatable questions ("does
    # pineapple belong on pizza") carry no syntactic marker at all — that gap
    # needs semantic understanding, not more patterns, and is left open.
    r"\b(?:is|are|was|were)\s+(?:\w+\s+){0,4}(?:better|worse|superior|inferior)\s+than\b",
    r"\bdeserves?\s+(?:to|the)\b",
    r"\bbelongs?\s+on\b",
    r"\bis\s+it\s+(?:ok(?:ay)?|right|wrong|fair|moral|ethical|acceptable)\s+(?:to|for|that)\b",
    r"\bshould\s+(?:\w+\s+){0,3}(?:be allowed|have|get|receive|deserve|be able)\b",
]

_AGGREGATE_MARKERS = [
    r"\b(?:total|sum|average|mean|median|count|how many|how much)\b",
    r"\b(?:across all|in aggregate|overall)\b",
]

_PROCEDURE_MARKERS = [
    r"\bhow (?:do|can) i\b",
    r"\bwhat (?:are the )?steps\b",
    r"\bhow to\b",
]

#: F1.6 — the agent narrating that it has part of the picture.
_COMPLETENESS_MARKERS = [
    r"\b(?:based on|from) the (?:\d+|few|some) (?:documents|records|results)\b",
    r"\bi found (\d+)\b",
]

#: F1.5 — refusal language, used to detect refusals we did *not* ask for.
_REFUSAL_MARKERS = [
    r"\bi (?:can'?t|cannot|am unable to|won'?t) (?:help|assist|answer|provide|share)\b",
    r"\bi (?:don'?t|do not) have (?:access|that|the) \w*",
    r"\b(?:that|this) (?:is |falls )?(?:outside|beyond) (?:my|the) (?:scope|remit|knowledge)\b",
    r"\bdata not available\b",
    r"\bi'?m (?:not able|unable) to\b",
]

_PREDICTION_RE = [re.compile(p, re.I) for p in PREDICTION_MARKERS]
_OPINION_RE = [re.compile(p, re.I) for p in _OPINION_MARKERS]
_AGGREGATE_RE = [re.compile(p, re.I) for p in _AGGREGATE_MARKERS]
_PROCEDURE_RE = [re.compile(p, re.I) for p in _PROCEDURE_MARKERS]
_COMPLETENESS_RE = [re.compile(p, re.I) for p in _COMPLETENESS_MARKERS]
_REFUSAL_RE = [re.compile(p, re.I) for p in _REFUSAL_MARKERS]

#: Years and explicit dates, for the coverage-window check.
_YEAR_RE = re.compile(r"\b(19\d\d|20\d\d)\b")
_RELATIVE_PAST = re.compile(
    r"\b(?:(\d+)|a|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(year|month|week|day)s?\s+ago\b",
    re.I,
)
_WORD_NUMBERS = {
    "a": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_UNIT_DAYS = {"year": 365, "month": 30, "week": 7, "day": 1}


# ---------------------------------------------------------------------------
# The declared boundary
# ---------------------------------------------------------------------------


def declare_boundary(
    session: Session,
    *,
    agent_id: str | None,
    systems_of_record: list[str] | None = None,
    coverage_months: int | None = None,
    coverage_start: dt.date | None = None,
    entity_types: list[str] | None = None,
    answerable_types: list[str] | None = None,
    out_of_scope_topics: list[str] | None = None,
    freshness_hours: int | None = None,
    mode: str = "observe",
) -> KnowledgeBoundary:
    """P7-1 — declare what this agent can actually answer from.

    Declared rather than inferred, because the fact that decides the question — what
    the index behind the agent contains — is not visible to the model and is not
    derivable from the corpus without the operator saying so.
    """
    boundary = session.scalar(
        select(KnowledgeBoundary).where(KnowledgeBoundary.agent_id == agent_id)
    )
    if boundary is None:
        boundary = KnowledgeBoundary(agent_id=agent_id)
        session.add(boundary)
    boundary.systems_of_record = systems_of_record or []
    boundary.coverage_months = coverage_months
    boundary.coverage_start = coverage_start
    boundary.entity_types = entity_types or []
    boundary.answerable_types = answerable_types or [FACT, AGGREGATE, PROCEDURE]
    boundary.out_of_scope_topics = out_of_scope_topics or []
    boundary.freshness_hours = freshness_hours
    boundary.mode = mode
    session.flush()
    return boundary


def get_boundary(session: Session, agent_id: str | None) -> KnowledgeBoundary | None:
    if not agent_id:
        return None
    return session.scalar(select(KnowledgeBoundary).where(KnowledgeBoundary.agent_id == agent_id))


# ---------------------------------------------------------------------------
# Classification (P7-2)
# ---------------------------------------------------------------------------


def _asks_about_a_resolved_prediction(text: str, now: dt.date) -> bool:
    """A forecast-shaped question that names only years already past isn't soliciting
    a new prediction — it's asking to recall a documented one ("what disease was
    projected to be eradicated by 2018" — 2018 has happened; there's a factual answer
    on record). No mentioned year at all leaves the question genuinely open-ended, so
    this only fires when every year named is already behind `now`. A mix that includes
    any future year (e.g. "in 2020, experts predicted X by 2050") stays a real,
    unresolved prediction — deliberately, since one still-open year is enough to make
    the question a forecast again.
    """
    years = [int(y) for y in _YEAR_RE.findall(text)]
    return bool(years) and all(y <= now.year for y in years)


def question_type(text: str, now: dt.date | None = None) -> str:
    """Classify the question. Deterministic and ordered by consequence.

    Prediction is checked first: a question that is *both* an aggregate and a forecast
    ("what will total revenue be next year") is a forecast, and treating it as an
    aggregate is precisely the F1.4 failure — a projection returned in the same
    register as a record.
    """
    if any(p.search(text) for p in _PREDICTION_RE):
        if _asks_about_a_resolved_prediction(text, now or dt.date.today()):
            return FACT
        return PREDICTION
    if any(p.search(text) for p in _OPINION_RE):
        return OPINION
    if any(p.search(text) for p in _AGGREGATE_RE):
        return AGGREGATE
    if any(p.search(text) for p in _PROCEDURE_RE):
        return PROCEDURE
    return FACT


def _temporal_scope(
    text: str, boundary: KnowledgeBoundary | None, now: dt.date | None = None
) -> dict[str, Any]:
    """F1.2 — does the question reach past what the index holds?

    Returns `in_scope: True` when no date is mentioned at all. Refusing every undated
    question would be the over-refusal failure in its purest form.
    """
    now = now or dt.date.today()
    if boundary is None:
        return {"in_scope": True, "reason": "no boundary declared"}

    earliest = None
    if boundary.coverage_start:
        earliest = boundary.coverage_start
    elif boundary.coverage_months:
        earliest = now - dt.timedelta(days=30 * boundary.coverage_months)
    if earliest is None:
        return {"in_scope": True, "reason": "no coverage window declared"}

    for match in _YEAR_RE.finditer(text):
        year = int(match.group(1))
        if year < earliest.year:
            return {
                "in_scope": False,
                "asked_about": str(year),
                "earliest": earliest.isoformat(),
                "reason": f"asked about {year}; coverage starts {earliest.isoformat()}",
            }

    match = _RELATIVE_PAST.search(text)
    if match:
        raw = match.group(1)
        count = int(raw) if raw else _WORD_NUMBERS.get(match.group(0).split()[0].lower(), 1)
        days = count * _UNIT_DAYS[match.group(2).lower()]
        asked = now - dt.timedelta(days=days)
        if asked < earliest:
            return {
                "in_scope": False,
                "asked_about": asked.isoformat(),
                "earliest": earliest.isoformat(),
                "reason": (
                    f"asked about {asked.isoformat()}; coverage starts {earliest.isoformat()}"
                ),
            }
    return {"in_scope": True, "earliest": earliest.isoformat()}


def _entity_scope(
    text: str, boundary: KnowledgeBoundary | None, known_entities: list[str] | None = None
) -> dict[str, Any]:
    """F1.3 — the customer who is not in the CRM.

    Only decides when the caller supplies the entities that *are* in scope. Guessing
    at entity membership from the prompt would produce refusals on typos and nicknames,
    which is the adoption-killing failure again.
    """
    if boundary is None or known_entities is None:
        return {"in_scope": True, "reason": "no entity scope supplied"}
    lowered = text.lower()
    referenced = [e for e in known_entities if e and e.lower() in lowered]
    # An identifier-shaped token that matches nothing we hold is the signal.
    candidates = re.findall(r"\b(?:[A-Z]{2,}-?\d{2,}|\d{5,})\b", text)
    unknown = [c for c in candidates if not any(c.lower() == e.lower() for e in known_entities)]
    if unknown and not referenced:
        return {
            "in_scope": False,
            "unknown": unknown,
            "reason": (
                f"identifier(s) {', '.join(unknown)} are not in any declared system of record"
            ),
        }
    return {"in_scope": True, "referenced": referenced}


def _topic_scope(text: str, boundary: KnowledgeBoundary | None) -> dict[str, Any]:
    if boundary is None or not boundary.out_of_scope_topics:
        return {"in_scope": True}
    lowered = text.lower()
    hit = [t for t in boundary.out_of_scope_topics if t.lower() in lowered]
    if hit:
        return {
            "in_scope": False,
            "topics": hit,
            "reason": f"declared out of scope: {', '.join(hit)}",
        }
    return {"in_scope": True}


@dataclass
class AnswerabilityVerdict:
    """Whether to answer, and if not, what to say instead."""

    answerable: bool
    question_type: str = FACT
    reasons: list[dict[str, Any]] = field(default_factory=list)
    abstention_kind: str | None = None
    response: str = ""
    mode: str = "observe"

    @property
    def should_abstain(self) -> bool:
        """Enforced only in enforce mode. Observe-first is not a nicety here — an
        over-refusing agent is uninstalled faster than a hallucinating one."""
        return not self.answerable and self.mode == "enforce"

    def to_json(self) -> dict[str, Any]:
        return {
            "answerable": self.answerable,
            "question_type": self.question_type,
            "abstention_kind": self.abstention_kind,
            "reasons": self.reasons,
            "response": self.response,
            "mode": self.mode,
            "should_abstain": self.should_abstain,
        }


def _article(word: str) -> str:
    """"a opinion question" is the kind of slip that makes a refusal look automated.

    Every value that reaches this is one of QUESTION_TYPES — plain ASCII words — so
    the vowel test is exact here and does not need a general a/an library.
    """
    return "an" if word[:1].lower() in "aeiou" else "a"


def _or_list(items: list[str]) -> str:
    """"fact or aggregate or procedure" reads as a machine listing enum members."""
    items = list(items)
    if len(items) <= 2:
        return " or ".join(items)
    return f"{', '.join(items[:-1])} or {items[-1]}"


#: P7-3 — templated abstentions. Each says *what* is missing, because "I don't know"
#: sends the user away while "I hold 24 months and you asked about 2019" sends them to
#: the right system.
_TEMPLATES = {
    UNKNOWABLE: (
        "That asks for a projection rather than a recorded fact. I can only report what "
        "is in {systems}, so I don't have an answer for it."
    ),
    OUT_OF_COVERAGE: (
        "I hold data from {earliest} onwards, and that question is about {asked_about}. "
        "Data not available for that period."
    ),
    OUT_OF_SCOPE_ENTITY: (
        "I can't find {unknown} in {systems}. Rather than guess, I'd rather tell you it "
        "isn't there."
    ),
    UNSUPPORTED_TYPE: (
        "That's {article} {question_type} question, and this agent is set up to answer "
        "{answerable} questions from {systems}."
    ),
    OUT_OF_DOMAIN: "That topic is outside what this agent is set up to cover ({topics}).",
}


def classify_answerability(
    text: str,
    boundary: KnowledgeBoundary | None,
    *,
    known_entities: list[str] | None = None,
    now: dt.date | None = None,
) -> AnswerabilityVerdict:
    """P7-2/P7-3 — decide before generation whether the question can be answered.

    Four checks, cheapest and most decisive first. All deterministic: an answerability
    check that itself calls a model inherits the failure it is meant to prevent.
    """
    qtype = question_type(text, now)
    systems = ", ".join((boundary.systems_of_record if boundary else []) or ["its sources"])
    mode = boundary.mode if boundary else "observe"
    reasons: list[dict[str, Any]] = []

    answerable_types = (boundary.answerable_types if boundary else None) or list(QUESTION_TYPES)
    if qtype not in answerable_types:
        kind = UNKNOWABLE if qtype == PREDICTION else UNSUPPORTED_TYPE
        reasons.append({"check": "question_type", "type": qtype, "allowed": answerable_types})
        return AnswerabilityVerdict(
            answerable=False,
            question_type=qtype,
            reasons=reasons,
            abstention_kind=kind,
            mode=mode,
            response=_TEMPLATES[kind].format(
                systems=systems,
                question_type=qtype,
                article=_article(qtype),
                answerable=_or_list(answerable_types),
            ),
        )

    temporal = _temporal_scope(text, boundary, now)
    if not temporal["in_scope"]:
        reasons.append({"check": "temporal", **temporal})
        return AnswerabilityVerdict(
            answerable=False,
            question_type=qtype,
            reasons=reasons,
            abstention_kind=OUT_OF_COVERAGE,
            mode=mode,
            response=_TEMPLATES[OUT_OF_COVERAGE].format(**temporal),
        )

    topic = _topic_scope(text, boundary)
    if not topic["in_scope"]:
        reasons.append({"check": "topic", **topic})
        return AnswerabilityVerdict(
            answerable=False,
            question_type=qtype,
            reasons=reasons,
            abstention_kind=OUT_OF_DOMAIN,
            mode=mode,
            response=_TEMPLATES[OUT_OF_DOMAIN].format(topics=", ".join(topic["topics"])),
        )

    entity = _entity_scope(text, boundary, known_entities)
    if not entity["in_scope"]:
        reasons.append({"check": "entity", **entity})
        return AnswerabilityVerdict(
            answerable=False,
            question_type=qtype,
            reasons=reasons,
            abstention_kind=OUT_OF_SCOPE_ENTITY,
            mode=mode,
            response=_TEMPLATES[OUT_OF_SCOPE_ENTITY].format(
                unknown=", ".join(entity["unknown"]), systems=systems
            ),
        )

    return AnswerabilityVerdict(answerable=True, question_type=qtype, mode=mode)


# ---------------------------------------------------------------------------
# Post-flight (P7-4, P7-5, P7-7)
# ---------------------------------------------------------------------------


def verify_boundary(
    answer: str, verdict: AnswerabilityVerdict, boundary: KnowledgeBoundary | None
) -> list[dict[str, Any]]:
    """P7-4 — did the answer exceed the boundary the question passed?

    A question can be in scope and the answer still stray, most commonly by drifting
    from record into projection halfway through.
    """
    breaches: list[dict[str, Any]] = []
    allowed = (boundary.answerable_types if boundary else None) or list(QUESTION_TYPES)
    if PREDICTION not in allowed:
        hits = [p.pattern for p in _PREDICTION_RE if p.search(answer)]
        if hits:
            breaches.append(
                {
                    "breach": "prediction_in_answer",
                    "detail": "the answer contains forecast language for an agent declared "
                    "record-only",
                    "patterns": hits[:3],
                }
            )
    if boundary and boundary.coverage_start:
        for match in _YEAR_RE.finditer(answer):
            if int(match.group(1)) < boundary.coverage_start.year:
                breaches.append(
                    {
                        "breach": "out_of_coverage_in_answer",
                        "detail": f"the answer cites {match.group(1)}, before coverage starts "
                        f"{boundary.coverage_start.isoformat()}",
                    }
                )
                break
    return breaches


def completeness_signal(
    answer: str, *, retrieved: int | None = None, available: int | None = None
) -> dict[str, Any]:
    """F1.6 — retrieved 3 of 50 and answered as though exhaustive.

    The signal is the *absence* of a caveat when the counts say one is warranted, not
    the presence of hedging.
    """
    declares = bool(any(p.search(answer) for p in _COMPLETENESS_RE))
    if retrieved is None or available is None or available <= 0:
        return {"declared": declares, "known": False}
    ratio = retrieved / available
    partial = ratio < 0.8
    return {
        "declared": declares,
        "known": True,
        "retrieved": retrieved,
        "available": available,
        "ratio": round(ratio, 3),
        "partial": partial,
        # The failure is answering as if exhaustive, so it fires only when the answer
        # is partial *and* silent about it.
        "misleading": partial and not declares,
        "suggested_caveat": (
            f"Based on {retrieved} of {available} matching records." if partial else ""
        ),
    }


def is_refusal(answer: str) -> bool:
    return any(p.search(answer or "") for p in _REFUSAL_RE)


def detect_over_refusal(
    session: Session,
    *,
    answer: str,
    verdict: AnswerabilityVerdict,
    agent_id: str | None = None,
    trace_id: str | None = None,
    raise_finding: bool = True,
) -> dict[str, Any] | None:
    """**P7-6 — the counter-metric, and the reason this pillar is safe to ship.**

    An agent that refuses what it could have answered is uninstalled faster than one
    that occasionally invents. So a refusal on a question our own boundary says was
    answerable is a *finding against us*, never a block.
    """
    if not verdict.answerable or not is_refusal(answer):
        return None
    record = {
        "reason": "the agent refused a question its declared boundary says is answerable",
        "question_type": verdict.question_type,
        "trace_id": trace_id,
        "excerpt": answer[:200],
    }
    if raise_finding:
        # One finding per (agent, question type): refusing answerable questions of a
        # kind is one behaviour with a count, and the evidence keeps the latest case.
        _raise_finding(
            session,
            type="over_refusal",
            severity="medium",
            title="Agent refused an answerable question",
            subject_type="agent",
            subject_id=agent_id,
            evidence=record,
            control_keys=["NOM-RTG-11"],
            fingerprint_parts=(verdict.question_type,),
        )
    return record


def abstention_report(session: Session, *, days: int = 7) -> dict[str, Any]:
    """Both rates side by side. Reporting abstention without over-refusal would let a
    team optimise one into the other and call it progress."""
    since = utcnow() - dt.timedelta(days=days)
    over = list(
        session.scalars(
            select(Finding).where(Finding.type == "over_refusal", Finding.created_at >= since)
        )
    )
    boundaries = list(session.scalars(select(KnowledgeBoundary)))
    return {
        "window_days": days,
        "boundaries_declared": len(boundaries),
        "enforcing": sum(1 for b in boundaries if b.mode == "enforce"),
        "over_refusals": len(over),
        "agents_without_boundary": [
            a.slug
            for a in session.scalars(select(Agent))
            if not any(b.agent_id == a.id for b in boundaries)
        ],
    }
