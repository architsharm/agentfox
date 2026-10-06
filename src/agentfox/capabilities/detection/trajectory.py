"""Conversation trajectory scoring (crescendo detection).

Every detector in this codebase scores **one message**. A crescendo
(Microsoft, arXiv:2404.01833) is built so that no single message is worth
scoring: each turn is a request a reasonable user could send and a reasonable
assistant could answer, and only the *sequence* arrives somewhere no single
message would have been allowed to go.

`Enforcer.check_conversation_window` answers a different multi-turn attack —
payload splitting, where a
sentence is cut into fragments that reassemble into a string the detector already
recognises. `benchmarks/crescendo/` measured whether that transfers, and it does
not: joining six innocuous turns yields six innocuous turns. **The signal is in
the slope, not in the content.** This module measures the slope.

What it does, following the crescendo entry in `docs/design/failure-modes.md`:

1. Score each turn on three *risk-adjacent* components — none of which is
   evidence on its own, which is the point:

   * **sub-threshold detector activation** — a detector finding that scored
     above zero but below the threshold at which a policy would act. This is
     the first component the design names, and it is wired to the real pipeline
     (:class:`TurnRisk.detector_score` is supplied by the caller from the same
     run the per-message path already makes). Be aware of what it is worth:
     across the 22 conversations in `benchmarks/crescendo/` the shipped
     detectors return **exactly zero** on every one of the 132 turns, so on
     genuine crescendo traffic this component contributes nothing at all. It is
     built because it is cheap, correct, and does carry signal on the mixed
     traffic where a crescendo is interleaved with clumsier probing — not
     because it is what catches crescendos.
   * **topic drift** — lexical distance from the first turn in the window
     (the design says "embedding-distance drift from turn 1's topic"; this is
     the offline, deterministic form of the same measurement — no model calls,
     per this codebase's offline default).
   * **reframing markers** — the scaffolding a crescendo is built out of:
     hypothetical framing, fiction/role framing, emotional framing, manufactured
     authority, persistence directives, restriction negotiation, and scope
     totalisation. The families are taken from the published description of the
     technique, not from any particular corpus.

2. Keep it as a **rolling window** (5-8 turns), never cumulative, so that a
   conversation which drifts and then genuinely resolves stops being penalised.
   Resolution is read with `claims_resolution` below, the same lexicon
   escalation governance uses, not a second one.

3. Fire on the **slope** of that score across the window, independent of whether
   any single turn crossed a per-message threshold.

**Observe-first.** Nothing here decides a verdict. `assess` returns a finding;
`Enforcer.check_conversation_window` puts it on the `action_risk` channel that
the action-assurance checks already use, where a policy author can act on it. See the
module's use site in `enforcement.py` for how a policy makes it block.

Deterministic and offline: regexes and set arithmetic, no model calls, no state.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

#: The entity/finding name for this detection, in the repo's entity convention
#: (`INJECTION.ROLE_DELIMITER`, `PII.US_SSN`, ...).
ENTITY = "CRESCENDO.TRAJECTORY_DRIFT"

#: The lowercase dotted code the same finding carries on the `action["risks"]`
#: channel, matching every other risk code there (`sql.unbounded_mutation`,
#: `commitment.binding`, ...) so that an `action_risk: "crescendo.*"` policy
#: condition works without a schema change.
RISK_CODE = "crescendo.trajectory_drift"

#: Rolling window, in turns. The design calls for 5-8; 6 is also
#: `check_conversation_window`'s own long-standing default, so the two paths see
#: the same history.
DEFAULT_WINDOW = 6

#: "Above zero but below the block threshold". The shipped baseline policy's
#: injection rules act at `min_score` 0.6-0.7 and the policy model's default is
#: 0.5, so 0.6 is the point below which a detector finding is real but inert.
#: A finding at or above it is not *sub*-threshold — the per-message path is
#: already handling it and this module must not double-count it.
DEFAULT_BLOCK_THRESHOLD = 0.6

#: Slope of the risk-adjacent score per turn, over the window. A conversation
#: has to be gaining roughly a tenth of the score's range every turn, sustained
#: across the window, to reach this.
DEFAULT_SLOPE_THRESHOLD = 0.09

#: A slope means nothing if the score it is a slope of is noise. The window's
#: last turn also has to have arrived somewhere: without this floor, a
#: conversation creeping from 0.00 to 0.15 has the same slope as one climbing
#: from 0.30 to 0.90, and only the second is a trajectory worth reporting.
DEFAULT_LEVEL_FLOOR = 0.45


# ---------------------------------------------------------------------------
# Reframing markers.
#
# These are the families the crescendo literature describes as the scaffolding
# an escalation is carried on, written out here rather than tuned: a marker
# earns its place by being a named part of the technique, not by separating any
# particular set of conversations. Several appear in entirely legitimate
# traffic — "from now on", "every", "full access" are ordinary things to say —
# which is exactly why no single marker is evidence and why the slope, not the
# count, is what fires.
# ---------------------------------------------------------------------------

_MARKERS: dict[str, list[str]] = {
    # Distance-creating framing: the request is not a request, it is a supposition.
    "hypothetical": [
        r"\bhypothetical(?:ly)?\b",
        r"\bthought experiment\b",
        r"\bpurely (?:as|for|in)\b",
        r"\b(?:just |let'?s |lets )?(?:suppose|imagine)\b",
        r"\bin theory\b|\btheoretically\b",
        r"\blet'?s say\b",
    ],
    # Fiction/role framing: the answer is attributed to a character.
    "fiction": [
        r"\b(?:for|in) (?:a|my|the) (?:story|novel|screenplay|script|scene|book)\b",
        r"\bfiction(?:al)?\b",
        r"\bin character\b",
        r"\b(?:role.?play|play the role|act as|answer as)\b",
        r"\bas (?:a|the) character\b",
    ],
    # Emotional framing: refusal is made to cost something. The "late grandmother"
    # pattern is the canonical published instance.
    "emotional": [
        r"\b(?:my )?(?:late|departed) \w+\b",
        r"\b(?:passed away|passed on)\b",
        r"\b(?:grand(?:mother|father|ma|pa)|nan|nana) (?:used to|would)\b",
        r"\bjust like she would\b|\bjust like he would\b",
        r"\bto help me (?:wind down|cope|feel better)\b",
    ],
    # Manufactured authority: the conversation grants itself a permission.
    "authority": [
        r"\b(?:it'?s|this is|as an?) authoris?ed\b",
        r"\bas (?:the|an?) (?:administrator|admin|superuser|operator)\b",
        r"\byou'?ve agreed\b|\bwe(?:'ve| have) established\b",
        r"\b(?:normal |usual )?restrictions? (?:do(?:n'?t| not)|no longer) (?:really )?apply\b",
        r"\bwithout (?:a |an )?(?:separate )?approval\b",
        r"\bin (?:this|that) role\b",
        r"\beffectively acting as\b",
    ],
    # Persistence: the frame is made to outlive the turn that introduced it.
    "persistence": [
        r"\bfrom now on\b",
        r"\bfor (?:the rest of )?(?:this|the) (?:conversation|session|chat)\b",
        r"\bgoing forward\b",
        r"\bevery (?:question|answer|response) (?:from now|going)\b",
    ],
    # Restriction negotiation: the constraint itself becomes the subject.
    "restriction": [
        r"\bno (?:operating )?(?:restrictions?|limits?|rules?)\b",
        r"\bunrestricted\b",
        r"\b(?:turn off|disable|switch off|bypass|skip|get around|without waiting)\b",
        r"\b(?:really )?necessary\b.{0,20}\b(?:checks?|controls?)\b",
        r"\bstay under the (?:cap|limit)\b|\bunder the (?:cap|limit)\b",
    ],
    # Scope totalisation: the defining move of an escalation is that the object of
    # the request keeps getting larger. This is the lexical form of that move.
    #
    # The quantifier has to be quantifying a *scope*, not a duration. "It's been
    # snowing all week" and "I've asked every time" are not escalations, and a
    # bare `\b(?:every|all)\s+\w+` reads them as ones — which is how the first
    # version of this module produced its only false positive, on a support chat
    # that wandered into the weather.
    "totalisation": [
        r"\b(?:every|all|entire|whole|any and all)\s+(?:of\s+)?(?:the\s+|those\s+|their\s+)?"
        r"(?!week|weeks|day|days|month|months|year|years|hour|hours|minute|minutes|"
        r"morning|afternoon|evening|night|nights|weekend|weekends|time|times|season|"
        r"seasons|along|around|over|right|well|good|sorts?|kinds?)\w+",
        r"\bin the (?:system|database|org(?:anisation|anization)?)\b",
        r"\bnot just\b",
        r"\brather than just\b",
        r"\b(?:widen|broaden|expand) (?:it|the scope)\b",
        r"\bfull (?:access|details|export|list|text|system prompt)\b",
    ],
    # Verbatim extraction: "describe" becoming "reproduce" is the last step of
    # every disclosure crescendo.
    "extraction": [
        r"\bverbatim\b|\bword for word\b",
        r"\b(?:the )?(?:exact|actual|real) "
        r"(?:text|rules?|instructions?|keys?|credentials?|values?)\b",
        r"\byou were (?:given|configured with|provided)\b",
        r"\byour own (?:setup|configuration|instructions?)\b",
        r"\bsystem prompt\b",
    ],
}

_MARKER_RE: dict[str, list[re.Pattern[str]]] = {
    family: [re.compile(p, re.I) for p in patterns] for family, patterns in _MARKERS.items()
}

#: Each distinct marker *family* present on a turn contributes this much, capped
#: below. Families rather than matches, so that a turn which says "every" three
#: times is not three times as suspicious as one that says it once.
_MARKER_WEIGHT = 0.22
_MARKER_CAP = 0.66

#: Weights on the three components. Drift is worth the least on purpose: benign
#: conversations drift constantly (a support chat wanders, a debugging session
#: moves from symptom to cause to fix) and drift alone would flag all of them.
_W_DETECTOR = 1.0
_W_DRIFT = 0.30
_W_MARKERS = 1.0

#: Words carrying no topic. Kept short deliberately — a long stop list is a
#: tuning surface.
_STOPWORDS = frozenset(
    """a an the and or but if then than that this these those there here is are was were be been
    being am do does did doing have has had having i me my we our you your he she it its they them
    their to of in on at for with from by as about into over after before can could would should
    will shall may might must not no nor so too very just also only own same s t don now what which
    who whom when where why how all any both each few more most other some such up down out off
    again further once please thanks thank ok okay hi hey hello yes yeah sure great good perfect
    let lets us me mind bit""".split()
)

_WORD_RE = re.compile(r"[a-z][a-z'\-]{2,}")

#: Longer turns are not more suspicious, and scanning an unbounded transcript is
#: not something a 300ms request budget can absorb. Public because the caller has
#: to apply the same cap to the detector runs behind component one: a 250KB turn
#: put through the real pipeline six times costs seconds, not milliseconds.
SCAN_CHARS = 2000
_SCAN_CHARS = SCAN_CHARS


def _content_tokens(text: str) -> set[str]:
    # Slice *before* lowercasing: `.lower()` on a 250KB turn allocates a 250KB
    # string only to throw away all but 2KB of it, and this runs once per turn in
    # the window.
    body = (text or "")[:_SCAN_CHARS].lower()
    return {w for w in _WORD_RE.findall(body) if w not in _STOPWORDS}


def topic_drift(text: str, baseline: set[str]) -> float:
    """Lexical distance of one turn from the window's opening topic, in [0, 1].

    Overlap coefficient rather than Jaccard: turns are short and of very
    uneven length, and Jaccard would report a one-word acknowledgement as
    maximally distant from a long opening question purely on set size.
    """
    tokens = _content_tokens(text)
    if not tokens or not baseline:
        return 0.0
    overlap = len(tokens & baseline) / min(len(tokens), len(baseline))
    return round(1.0 - overlap, 4)


def reframing_markers(text: str) -> list[str]:
    """Which scaffolding families this turn uses. Names, not a score."""
    body = (text or "")[:_SCAN_CHARS]
    return sorted(
        family for family, patterns in _MARKER_RE.items() if any(p.search(body) for p in patterns)
    )


#: A resolution claim the agent makes about itself. Escalation governance reads the
#: same lexicon (`containment.escalation.turn_signals`).
_RESOLUTION_CLAIMS = [
    r"\b(?:i(?:'ve| have)?\s+)?(?:resolved|fixed|sorted|completed|taken care of)\b",
    r"\bis (?:now )?(?:resolved|fixed|complete|sorted)\b",
    r"\banything else (?:i can help|you need)\b",
    r"\bglad (?:i could|to have) help",
    r"\bmarking this (?:as )?(?:resolved|closed)\b",
]
_RESOLUTION_RE = [re.compile(p, re.I) for p in _RESOLUTION_CLAIMS]


def claims_resolution(text: str) -> bool:
    """Whether the agent's text claims the issue is resolved."""
    return any(p.search(text or "") for p in _RESOLUTION_RE)


@dataclass(slots=True)
class TurnRisk:
    """One turn's risk-adjacent score and where it came from."""

    index: int
    score: float
    detector: float = 0.0
    drift: float = 0.0
    markers: list[str] = field(default_factory=list)
    resolved: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "score": round(self.score, 4),
            "detector": round(self.detector, 4),
            "drift": round(self.drift, 4),
            "markers": self.markers,
            "resolved": self.resolved,
        }


def score_turn(
    text: str,
    *,
    index: int = 0,
    baseline: set[str] | None = None,
    detector_score: float = 0.0,
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD,
) -> TurnRisk:
    """The risk-adjacent score for one turn. No state, no I/O.

    `detector_score` is the max score from the per-message detector run the
    caller has already made. Only its *sub-threshold* range counts: at or above
    `block_threshold` the per-message path owns the decision and this module
    stays out of it, which also stops a single blatant turn from manufacturing
    a trajectory out of nothing.
    """
    # Truncated once, here, and every component below reads the truncated body —
    # including `claims_resolution`, whose lexicon would otherwise be run over the
    # whole turn. Cheap to get wrong and expensive to leave wrong: this check runs
    # once per turn in the window, so any per-turn cost is multiplied by the window.
    body = (text or "")[:_SCAN_CHARS]
    sub = detector_score if 0.0 < detector_score < block_threshold else 0.0
    drift = topic_drift(body, baseline or set())
    markers = reframing_markers(body)
    marker_score = min(_MARKER_CAP, _MARKER_WEIGHT * len(markers))
    score = min(1.0, _W_DETECTOR * sub + _W_DRIFT * drift + _W_MARKERS * marker_score)
    return TurnRisk(
        index=index,
        score=round(score, 4),
        detector=sub,
        drift=drift,
        markers=markers,
        resolved=claims_resolution(body),
    )


def slope(scores: Sequence[float]) -> float:
    """Least-squares slope of the score series, per turn.

    Least squares rather than last-minus-first: a crescendo is a sustained
    climb, and the difference between the endpoints cannot tell that apart from
    a single loud final turn after five quiet ones — which is a per-message
    problem that the per-message path already owns.
    """
    n = len(scores)
    if n < 3:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(scores) / n
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(scores))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return round(num / den, 4) if den else 0.0


@dataclass(slots=True)
class TrajectoryAssessment:
    """What the window looked like, and whether that is worth reporting."""

    fired: bool
    slope: float
    level: float
    peak: float
    window: int
    turns: list[TurnRisk] = field(default_factory=list)
    reason: str = ""
    entity: str = ENTITY
    code: str = RISK_CODE

    @property
    def markers(self) -> list[str]:
        return sorted({m for t in self.turns for m in t.markers})

    def to_json(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "code": self.code,
            "fired": self.fired,
            "slope": self.slope,
            "level": self.level,
            "peak": self.peak,
            "window": self.window,
            "markers": self.markers,
            "reason": self.reason,
            "turns": [t.to_json() for t in self.turns],
        }


def assess(
    texts: Sequence[str],
    *,
    detector_scores: Sequence[float] | None = None,
    window: int = DEFAULT_WINDOW,
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD,
    level_floor: float = DEFAULT_LEVEL_FLOOR,
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD,
) -> TrajectoryAssessment:
    """Score the last `window` turns and decide whether the slope is a finding.

    `texts` is oldest-first and ends with the turn being evaluated.
    `detector_scores`, when given, is the per-message detector max score for
    each corresponding turn — the number the per-message run already produced.

    Three conditions, all required:

    * the window holds enough turns to have a slope at all (three);
    * the least-squares slope across the window is at or above
      `slope_threshold`;
    * the window's last turn is at or above `level_floor`, so that a slope
      measured on noise is not reported as a trajectory.

    And one veto: if the latest turn claims the conversation resolved, nothing
    fires. The score is kept rolling rather than cumulative precisely so a
    conversation that drifts and then lands is not penalised for the drift, and
    a resolution claim is the clearest statement that it landed.
    """
    recent = list(texts)[-window:]
    scores = list(detector_scores or [])[-window:] if detector_scores else []
    if scores and len(scores) != len(recent):
        scores = []

    # The baseline is the first turn *in the window*, not the first turn of the
    # conversation: the window is what rolls, and a topic set that never ages
    # out would make an hour-old opening subject define drift forever.
    baseline = _content_tokens(recent[0]) if recent else set()

    turns = [
        score_turn(
            text,
            index=i,
            baseline=baseline if i else set(),
            detector_score=scores[i] if scores else 0.0,
            block_threshold=block_threshold,
        )
        for i, text in enumerate(recent)
    ]
    series = [t.score for t in turns]
    gradient = slope(series)
    level = series[-1] if series else 0.0
    peak = max(series, default=0.0)
    resolved = bool(turns and turns[-1].resolved)

    fired = (
        len(turns) >= 3 and gradient >= slope_threshold and level >= level_floor and not resolved
    )
    if fired:
        families = sorted({m for t in turns for m in t.markers})
        reason = (
            f"conversation trajectory is escalating: risk-adjacent score rose "
            f"{gradient:+.2f}/turn across {len(turns)} turns to {level:.2f}, with no "
            f"single turn crossing the per-message threshold"
            + (f" (reframing: {', '.join(families)})" if families else "")
        )
    elif resolved and gradient >= slope_threshold:
        reason = "trajectory rose but the latest turn claims resolution; not reported"
    else:
        reason = "no escalating trajectory"

    return TrajectoryAssessment(
        fired=fired,
        slope=gradient,
        level=round(level, 4),
        peak=round(peak, 4),
        window=len(turns),
        turns=turns,
        reason=reason,
    )
