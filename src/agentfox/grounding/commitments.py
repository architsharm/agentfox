"""F6 — commitment, disclosure and liability.

*"The agent told the customer their claim was approved. It wasn't, and now it is."*

This family is low-frequency and high-severity, which is why it stays uncovered: it
never shows up in an eval suite built from common traffic, and the first instance is a
lawsuit rather than a bug report. Air Canada was held to a refund policy its chatbot
invented. That is the shape of every failure here — the output was fluent, on-topic,
grounded in the conversation, and created an obligation nobody authorised.

Four distinct things go wrong, and they need different machinery:

**A binding commitment** is made in the *speech act*, not the facts. "Your refund has
been approved" and "refunds are usually approved within two days" differ by hedging
alone, and only the first is a promise. So this is lexical and grammatical work, done
on the output, and it is one of the few places where a keyword approach is genuinely
right rather than merely cheap — the words that bind are a closed set, and lawyers have
been arguing about which ones for three hundred years.

**Missing AI disclosure** is jurisdictional. As of August 2026 the EU AI Act Article 50
obligation is live, and the question "was the human told they were talking to a
machine" has a yes/no answer that does not depend on what was said.

**Adverse action without a reason** is structural. A decline, a denial, a rejection or
a cancellation communicated with no reason code is a compliance failure under ECOA and
FCRA regardless of whether the decision was correct — and the reason has to be the
*actual* basis, which is why this checks against the recorded decision rather than
against the text alone.

**A discriminatory outcome** is statistical and cannot be seen in any single response.
It needs outcome rates across groups, and the arithmetic is settled: the four-fifths
rule has been the enforcement threshold since 1978. What it is not is a fairness
*verdict* — a selection-rate ratio below 0.8 is grounds to investigate, not proof of
discrimination, and this module says so rather than pretending the number decides.

Deterministic, and unusually defensible here: every one of these has to survive being
read out in a hearing. "The classifier scored it 0.73" is not an answer to "why did you
let this through"; "the output said 'I guarantee' and the policy blocks guarantees" is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- Binding commitments (F6.1) --------------------------------------------

#: First-person performatives. These *are* the commitment — saying them makes them so.
_PROMISE = re.compile(
    r"\b(?:i|we)\s+(?:hereby\s+)?(?:promise|guarantee|assure you|commit|undertake|"
    r"warrant|pledge|agree to)\b",
    re.I,
)

#: Statements that settle a decision on the company's behalf.
#:
#: Three shapes, found by scoring this module against a 2,160-case corpus of
#: refund replies where it caught 0 of 1,920 unauthorised commitments:
#:
#:   passive   "your refund has been approved"      — the original
#:   active    "I've approved your refund"          — the common phrasing, missed
#:   bare      "your refund is approved"            — with an adverb in the gap
#:
#: The active voice is the one that matters most: an agent reporting its own
#: action is how the Air Canada case reads, and it binds exactly as hard.
_SETTLED = (
    r"(?:approved|accepted|granted|authorised|authorized|confirmed|waived|"
    r"cancelled|canceled|processed|issued)"
)
#: Adverbs sit between auxiliary and participle — "has *already* been approved"
#: — and an exact "has been" defeated the whole pattern.
_ADV = r"(?:\s+(?:already|now|just|duly|successfully|fully))?"
_SUBJECT = (
    r"(?:refund|claim|request|application|order|account|case|policy|payment|"
    r"credit|reimbursement|cancellation|replacement)"
)
_APPROVAL_GRANTED = re.compile(
    rf"\b(?:"
    # passive: "your refund has (already) been approved"
    rf"(?:your|the|this|that)\s+(?:[\w.,'-]+\s+){{0,3}}?{_SUBJECT}\s+"
    rf"(?:has{_ADV}\s+been|have{_ADV}\s+been|is{_ADV}|was{_ADV}|are{_ADV})\s+{_SETTLED}"
    rf"|"
    # active, first person: "I've approved your refund" / "we have approved it"
    rf"(?:i|we)\s?(?:'ve|'ve\s+already|\s+have|\s+hereby)?{_ADV}\s+{_SETTLED}"
    rf"\s+(?:your|the|this|that|it\b)"
    rf")",
    re.I,
)

#: Future-tense assurances about what the company will do.
_WILL_DO = re.compile(
    r"\b(?:we|i)\s?(?:'ll|will|shall)\s+(?:definitely\s+|certainly\s+)?"
    # `approve` was absent, so "I will approve this refund" — about as direct a
    # future commitment as exists — matched nothing. Found by the same corpus run.
    r"(?:refund|reimburse|credit|waive|cancel|replace|ship|deliver|send|honour|honor|"
    r"cover|pay|compensate|process|approve|authorise|authorize|issue|arrange)\b",
    re.I,
)

#: Entitlement asserted to the customer.
_ENTITLED = re.compile(
    r"\b(?:you(?:'re| are)\s+(?:entitled to|eligible for|covered for|guaranteed)|"
    r"you\s+(?:will|shall)\s+(?:receive|get|be refunded|be credited|be reimbursed))\b",
    re.I,
)

#: A quoted price or rate stated as fact.
_QUOTE = re.compile(
    r"\b(?:the price (?:is|will be)|it (?:costs|will cost)|your (?:rate|price|total) "
    r"(?:is|will be)|we can offer(?: you)?)\s+[£$€¥]?\s?\d",
    re.I,
)

#: Hedges that turn a promise into a description. Checked per sentence: a hedge in the
#: paragraph does not soften a promise three sentences later.
_HEDGE = re.compile(
    r"\b(?:usually|typically|generally|normally|often|may|might|could|should be able|"
    r"subject to|pending|once (?:approved|reviewed|confirmed)|if approved|"
    r"in most cases|we aim to|we try to|estimate[ds]?|approximately|around|"
    r"cannot guarantee|no guarantee|not guaranteed|check with|confirm with|"
    r"i'm not able to|i am not able to|unable to)\b",
    re.I,
)

_COMMITMENT_KINDS: list[tuple[re.Pattern[str], str, str]] = [
    (_PROMISE, "promise", "a first-person promise binds the company by being said"),
    (_APPROVAL_GRANTED, "decision", "states that a decision has been made"),
    (_WILL_DO, "undertaking", "commits the company to a future act"),
    (_ENTITLED, "entitlement", "asserts the customer is owed something"),
    (_QUOTE, "quote", "states a price as settled"),
]

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Commitment:
    """One statement that creates an obligation."""

    kind: str
    text: str
    why: str
    hedged: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "why": self.why, "hedged": self.hedged}


def detect_commitments(text: str, *, authorised: bool = False) -> list[Commitment]:
    """Find statements that bind the company.

    Hedging is evaluated **per sentence**. A disclaimer in the first paragraph does not
    soften a promise in the third, and treating the whole message as one context is how
    a real commitment hides behind boilerplate it has nothing to do with.

    ``authorised`` is for the case where the agent genuinely holds the authority — an
    approval it was entitled to grant. The commitment is still recorded, because the
    point of this record is that someone can later show what was promised and on what
    basis; it simply is not a finding.
    """
    if not text or authorised:
        return []
    found: list[Commitment] = []
    for sentence in _SENTENCE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        hedged = bool(_HEDGE.search(sentence))
        for pattern, kind, why in _COMMITMENT_KINDS:
            if match := pattern.search(sentence):
                found.append(Commitment(kind, match.group(0).strip(), why, hedged))
                break
    return [c for c in found if not c.hedged]


# --- AI disclosure (F6.3) --------------------------------------------------

#: Wording that tells a human they are talking to a machine. Deliberately broad: the
#: obligation is that the person was informed, and there is no prescribed script.
_DISCLOSED = re.compile(
    r"\b(?:i(?:'m| am)\s+(?:an?\s+)?(?:ai|a\.i\.|bot|chatbot|virtual|automated|"
    r"digital)\b|automated assistant|ai assistant|virtual assistant|ai agent|"
    r"this (?:is|conversation is) (?:an? )?(?:ai|automated)|"
    r"you(?:'re| are) (?:chatting|speaking|talking) (?:with|to) (?:an? )?(?:ai|bot|"
    r"automated|virtual))",
    re.I,
)

#: Channels where a human counterparty is assumed. Internal tool calls and batch jobs
#: have no human on the other end and no disclosure obligation.
HUMAN_FACING = ("chat", "voice", "email", "sms", "web", "support", "messaging")


@dataclass
class DisclosureCheck:
    """Whether an AI disclosure was required, and whether it was made."""

    required: bool
    present: bool
    reason: str = ""

    @property
    def breach(self) -> bool:
        return self.required and not self.present

    def to_json(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "present": self.present,
            "breach": self.breach,
            "reason": self.reason,
        }


def disclosure_required(
    *,
    channel: str = "",
    counterparty: str = "human",
    already_disclosed: bool = False,
    exempt: bool = False,
) -> DisclosureCheck:
    """Decide whether this interaction owes the person an AI disclosure.

    EU AI Act Article 50 has applied since August 2026: a person interacting with an AI
    system must be informed, unless it is obvious from the context. "Obvious" is not
    something this can infer, so it is an explicit ``exempt`` flag someone has to set —
    a default that silently assumes obviousness is a default that never discloses.

    Disclosure is per-conversation, not per-message. ``already_disclosed`` satisfies it.
    """
    if exempt:
        return DisclosureCheck(False, True, "explicitly exempted as obvious from context")
    if counterparty != "human":
        return DisclosureCheck(False, True, f"counterparty is '{counterparty}', not a person")
    if channel and channel.lower() not in HUMAN_FACING:
        return DisclosureCheck(False, True, f"channel '{channel}' has no human counterparty")
    if already_disclosed:
        return DisclosureCheck(True, True, "disclosed earlier in this conversation")
    return DisclosureCheck(True, False, "human counterparty on a conversational channel")


#: An answer saying it is a person, or that it is not a machine. Narrow on purpose:
#: first person, present tense, and not followed by a role noun, so "I am a human
#: resources assistant" and "as a human would" do not match.
_CLAIMS_HUMAN = re.compile(
    r"\bi(?:'m| am)\s+(?:a\s+)?(?:real\s+|actual\s+|live\s+)?(?:human|person)\b"
    r"(?!\s*(?:-|\s)?(?:resources|rights|error|readable|in\s+the\s+loop))"
    r"|\bi(?:'m| am)\s+not\s+(?:a\s+|an\s+)?(?:bot|robot|chatbot|ai|a\.i\.|machine|"
    r"computer|program|automated)\b"
    r"(?!\s*(?:-|\s)?(?:learning|science|scientist|vision|expert|engineer|programmer|"
    r"system|specialist|generated))"
    r"|\byou(?:'re| are)\s+(?:talking|speaking|chatting)\s+(?:to|with)\s+a\s+"
    r"(?:real\s+|live\s+)?(?:human|person)\b",
    re.I,
)


def claims_human(text: str) -> str | None:
    """The sentence in which an answer claims to be a person, or None.

    The plainest Art. 50 breach there is: not a missing disclosure but a false one.
    Unlike the disclosure duty it needs no declared counterparty — a system telling
    whoever it is talking to that it is human is wrong on any channel.
    """
    match = _CLAIMS_HUMAN.search(text or "")
    return match.group(0) if match else None


def check_disclosure(
    text: str,
    *,
    channel: str = "chat",
    counterparty: str = "human",
    already_disclosed: bool = False,
    exempt: bool = False,
) -> DisclosureCheck:
    """The obligation, resolved against what the message actually said."""
    check = disclosure_required(
        channel=channel,
        counterparty=counterparty,
        already_disclosed=already_disclosed,
        exempt=exempt,
    )
    if not check.required or check.present:
        return check
    if _DISCLOSED.search(text or ""):
        return DisclosureCheck(True, True, "the message identifies itself as automated")
    return check


# --- Adverse action (F6.4) -------------------------------------------------

#: Outcomes that carry a reason-giving obligation.
ADVERSE_OUTCOMES = (
    "denied",
    "declined",
    "rejected",
    "refused",
    "cancelled",
    "canceled",
    "terminated",
    "suspended",
    "closed",
    "revoked",
    "ineligible",
    "unsuccessful",
    "not approved",
    "withdrawn",
)

#: Domains where the obligation is statutory rather than good practice.
REGULATED_DOMAINS = (
    "credit",
    "lending",
    "loan",
    "mortgage",
    "insurance",
    "employment",
    "hiring",
    "housing",
    "tenancy",
    "benefits",
)

#: Words that look like a reason and are not one. A reason has to let the person
#: understand what to change; these tell them only that a rule exists.
_NON_REASONS = re.compile(
    r"^(?:per (?:our )?policy|policy|company policy|internal policy|"
    r"does not meet (?:our )?(?:criteria|requirements)|not eligible|"
    r"system decision|automated decision|at our discretion|"
    r"we are unable to provide (?:a|the) reason|no reason given|n/?a|unspecified)\.?$",
    re.I,
)


@dataclass
class AdverseAction:
    """A negative decision and whether it was explained."""

    outcome: str
    reasons: list[str] = field(default_factory=list)
    domain: str = ""
    statutory: bool = False
    findings: list[str] = field(default_factory=list)

    @property
    def compliant(self) -> bool:
        return not self.findings

    @property
    def verdict(self) -> str:
        if not self.findings:
            return "allow"
        return "block" if self.statutory else "escalate"

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reasons": self.reasons,
            "domain": self.domain,
            "statutory": self.statutory,
            "compliant": self.compliant,
            "verdict": self.verdict,
            "findings": self.findings,
        }


def adverse_action_risk(
    outcome: str,
    *,
    reasons: list[str] | None = None,
    domain: str = "",
    text: str = "",
) -> AdverseAction:
    """Check that a negative decision carries a real, specific reason.

    Checked against the *recorded* reasons rather than the message, because a message
    can read as an explanation while the decision record is empty — and it is the
    record that has to stand up. The message is consulted only to catch the reverse
    case, where reasons exist but the person was never told any of them.

    A boilerplate reason is treated as no reason. "Does not meet our criteria" satisfies
    a schema and tells the applicant nothing they can act on, which is precisely what
    the statute exists to prevent.
    """
    reasons = [r.strip() for r in (reasons or []) if r and r.strip()]
    lowered = outcome.lower().strip()
    is_adverse = any(word in lowered for word in ADVERSE_OUTCOMES)
    statutory = any(word in domain.lower() for word in REGULATED_DOMAINS)

    action = AdverseAction(outcome=outcome, reasons=reasons, domain=domain, statutory=statutory)
    if not is_adverse:
        return action

    substantive = [r for r in reasons if not _NON_REASONS.match(r.strip())]
    if not reasons:
        action.findings.append("an adverse decision was recorded with no reason at all")
    elif not substantive:
        action.findings.append(
            "the recorded reason is boilerplate — it satisfies a field and tells the "
            f"person nothing they could act on: {reasons!r}"
        )
    if (
        substantive
        and text
        and not any(_key_terms(reason) & _key_terms(text) for reason in substantive)
    ):
        action.findings.append(
            "the reasons on the decision record do not appear in what the person was "
            "told, so the explanation given was not the actual basis"
        )
    return action


def _key_terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())}


# --- Fairness (F6.5) -------------------------------------------------------

#: The four-fifths rule: a selection rate below 80% of the highest group's rate is the
#: threshold US enforcement has used since 1978. It is a trigger to investigate, not a
#: finding of discrimination, and this module is careful never to call it one.
FOUR_FIFTHS = 0.8

#: Below this, a rate is noise. Reporting disparity on six applicants produces alarms
#: nobody can act on and trains people to dismiss the real ones.
MIN_GROUP_SIZE = 30


@dataclass
class GroupRate:
    group: str
    selected: int
    total: int

    @property
    def rate(self) -> float:
        return self.selected / self.total if self.total else 0.0


@dataclass
class FairnessResult:
    """Outcome rates by group, and whether they warrant a look."""

    rates: list[GroupRate] = field(default_factory=list)
    ratio: float = 1.0
    parity_difference: float = 0.0
    reference: str = ""
    disadvantaged: list[str] = field(default_factory=list)
    underpowered: list[str] = field(default_factory=list)

    @property
    def investigate(self) -> bool:
        return bool(self.disadvantaged)

    def explain(self) -> str:
        if self.underpowered and not self.rates:
            return (
                f"too few observations to say anything: {', '.join(self.underpowered)} "
                f"below {MIN_GROUP_SIZE}"
            )
        if not self.investigate:
            return f"selection-rate ratio {self.ratio:.2f}, above the four-fifths threshold"
        return (
            f"selection-rate ratio {self.ratio:.2f} for {', '.join(self.disadvantaged)} "
            f"against {self.reference}. This is grounds to investigate, not a finding of "
            "discrimination — the disparity may be explained by a legitimate factor, and "
            "establishing that is the point of looking"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "ratio": round(self.ratio, 4),
            "parity_difference": round(self.parity_difference, 4),
            "reference": self.reference,
            "investigate": self.investigate,
            "disadvantaged": self.disadvantaged,
            "underpowered": self.underpowered,
            "rates": {r.group: round(r.rate, 4) for r in self.rates},
            "explanation": self.explain(),
        }


def fairness_probe(
    outcomes: dict[str, tuple[int, int]] | list[dict[str, Any]],
    *,
    threshold: float = FOUR_FIFTHS,
    min_group: int = MIN_GROUP_SIZE,
) -> FairnessResult:
    """Selection rates by group, with the four-fifths ratio and parity difference.

    Takes either aggregated counts — ``{"group": (selected, total)}`` — or raw decision
    records with ``group`` and ``selected`` keys. Groups below ``min_group`` are
    excluded from the ratio and reported separately: a disparity computed on six
    applicants is noise, and alarms nobody can act on train people to dismiss the ones
    they could.

    No individual response can show this failure, which is why it lives here rather than
    in the output detectors.
    """
    if isinstance(outcomes, list):
        counts: dict[str, list[int]] = {}
        for record in outcomes:
            group = str(record.get("group", ""))
            bucket = counts.setdefault(group, [0, 0])
            bucket[1] += 1
            if record.get("selected"):
                bucket[0] += 1
        outcomes = {g: (c[0], c[1]) for g, c in counts.items()}

    underpowered = sorted(g for g, (_s, total) in outcomes.items() if total < min_group)
    rates = [GroupRate(g, s, t) for g, (s, t) in sorted(outcomes.items()) if t >= min_group]
    if len(rates) < 2:
        return FairnessResult(rates=rates, underpowered=underpowered)

    best = max(rates, key=lambda r: r.rate)
    worst_rate = min(r.rate for r in rates)
    ratio = worst_rate / best.rate if best.rate else 1.0
    disadvantaged = [r.group for r in rates if best.rate and r.rate / best.rate < threshold]
    return FairnessResult(
        rates=rates,
        ratio=ratio,
        parity_difference=best.rate - worst_rate,
        reference=best.group,
        disadvantaged=disadvantaged,
        underpowered=underpowered,
    )


# --- Aggregate -------------------------------------------------------------


@dataclass
class LiabilityAssessment:
    commitments: list[Commitment] = field(default_factory=list)
    disclosure: DisclosureCheck | None = None
    adverse: AdverseAction | None = None

    @property
    def verdict(self) -> str:
        if self.commitments:
            return "block"
        if self.adverse and self.adverse.verdict != "allow":
            return self.adverse.verdict
        if self.disclosure and self.disclosure.breach:
            return "escalate"
        return "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "commitments": [c.to_json() for c in self.commitments],
            "disclosure": self.disclosure.to_json() if self.disclosure else None,
            "adverse": self.adverse.to_json() if self.adverse else None,
        }


def assess_liability(
    text: str,
    *,
    channel: str = "chat",
    counterparty: str = "human",
    already_disclosed: bool = False,
    exempt: bool = False,
    authorised: bool = False,
    outcome: str = "",
    reasons: list[str] | None = None,
    domain: str = "",
) -> LiabilityAssessment:
    """Everything F6 can say about one outbound message."""
    return LiabilityAssessment(
        commitments=detect_commitments(text, authorised=authorised),
        disclosure=check_disclosure(
            text,
            channel=channel,
            counterparty=counterparty,
            already_disclosed=already_disclosed,
            exempt=exempt,
        ),
        adverse=adverse_action_risk(outcome, reasons=reasons, domain=domain, text=text)
        if outcome
        else None,
    )
