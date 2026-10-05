"""What the answer is entitled to sound like.

Answerability decides whether a question can be answered at all. It classifies "what
will sales be next quarter" as a prediction, checks it against the declared answerable
types, and abstains. That is the right control and it stops at the door.

It says nothing about the far more common case: the question *is* answerable, the agent
*does* answer, and the answer claims more precision or more authority than anything
behind it supports. Nothing here is ungrounded, nothing is a policy breach, and the
failure is entirely in the register::

    Q: What dose of ibuprofen should I take for this?
    A: Take 400mg every six hours with food.

    Q: Where will interest rates be in 2027?
    A: Around 3.25%, falling through the second half.

Both are fluent, both are plausible, both are the kind of thing a model produces
readily. The first is a medical instruction from something that is not a clinician. The
second is a point estimate about a future that has no system of record — and the
specificity is what does the damage, because "rates will probably ease" is a defensible
sentence and "3.25%" is a number someone will plan around.

So the unit of control here is **specificity licensed by epistemic standing**. Three
things decide it:

* **The question's type.** A prediction cannot license a point estimate, whatever the
  retrieved context says, because the context is about the past.
* **The domain.** In medicine, law and finance the line is not accuracy but *instruction*
  — telling someone what to take, what to sign, or what to buy is regulated activity
  regardless of whether the answer is correct.
* **What the answer actually did.** Hedged generality and a bare number are different
  acts, and the difference is visible in the text.

Deliberately not a toxicity classifier or a safety model. Those ask whether content is
harmful in general; this asks whether *this* system was entitled to say *this*, which is
a question about standing rather than content, and standing is declared rather than
inferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentfox.grounding.answerability import OPINION, PREDICTION, question_type
from agentfox.core.finding import RiskFinding

# --- Domains ---------------------------------------------------------------

MEDICAL = "medical"
LEGAL = "legal"
FINANCIAL = "financial"
SCIENTIFIC = "scientific"
GENERAL = "general"

_DOMAIN_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    (
        MEDICAL,
        (
            "dose",
            "dosage",
            "mg",
            "symptom",
            "diagnos",
            "treatment",
            "prescri",
            "medication",
            "drug",
            "therapy",
            "pain",
            "infection",
            "blood pressure",
            "side effect",
            "contraindicat",
        ),
    ),
    (
        LEGAL,
        (
            "contract",
            "liable",
            "liability",
            "sue",
            "lawsuit",
            "statute",
            "clause",
            "terminate the agreement",
            "legally",
            "court",
            "damages",
            "breach of",
        ),
    ),
    (
        FINANCIAL,
        (
            "invest",
            "portfolio",
            "stock",
            "shares",
            "allocation",
            "returns",
            "interest rate",
            "yield",
            "tax",
            "pension",
            "mortgage rate",
        ),
    ),
    (
        SCIENTIFIC,
        (
            "causes",
            "mechanism",
            "efficacy",
            "statistically significant",
            "clinical trial",
            "p-value",
            "correlation",
            "study shows",
        ),
    ),
]


def domain_of(text: str) -> str:
    lowered = " ".join((text or "").lower().split())
    for domain, markers in _DOMAIN_MARKERS:
        if any(marker in lowered for marker in markers):
            return domain
    return GENERAL


# --- What the answer did ---------------------------------------------------

#: A dose is the clearest case of an instruction wearing a number. Abbreviated and
#: spelled-out units both count — "500 milligrams" carries the same instruction as
#: "500mg", and only checking the abbreviation is a vocabulary gap, not a different
#: risk (P18 register broadening).
_DOSAGE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|ml|g|iu|units?|"
    r"milligrams?|micrograms?|millilit(?:er|re)s?|grams?|international\s+units?)\b"
    r"|\b(?:take|use|apply|inject|administer)\s+\d",
    re.I,
)

#: A point estimate: a number with no interval and no hedge around it.
_POINT_ESTIMATE = re.compile(
    r"\b\d+(?:\.\d+)?\s?%|\b[£$€¥]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\b"
)

#: Second-person instruction. "You should" is the grammatical form of advice.
_INSTRUCTION = re.compile(
    r"\b(?:you should|you need to|you must|i recommend|i'd recommend|i suggest|"
    r"my advice|the best option (?:is|for you)|go with|put \d+%|"
    r"take|stop taking|switch to|sign|sue|file a claim)\b",
    re.I,
)

#: A diagnosis or legal conclusion stated about the person.
_CONCLUSION = re.compile(
    r"\b(?:you (?:have|are suffering from|are experiencing)|this is (?:a|an)\s+\w+"
    r"(?: infection| fracture| breach| violation)|you are (?:liable|entitled|in breach))\b",
    re.I,
)

#: Uncertainty actually expressed. Not a hedge word count — these are the forms that
#: change what the sentence claims.
_UNCERTAINTY = re.compile(
    r"\b(?:might|may|could|possibly|likely|unlikely|roughly|approximately|around|"
    r"about|typically|generally|usually|tends to|estimate|projected|forecast|"
    r"uncertain|cannot predict|can't predict|no way to know|depends on|"
    r"speak to|consult|see a|talk to your|professional advice|not a substitute)\b",
    re.I,
)

#: Causal language stated as settled.
_CAUSAL_CLAIM = re.compile(
    r"\b(?:causes|is caused by|leads to|results in|proves|demonstrates that|"
    r"is responsible for)\b",
    re.I,
)

#: Deferral to a qualified human — the register a regulated answer is entitled to.
_REFERRAL = re.compile(
    r"\b(?:speak to|consult|see) (?:a|your|an) (?:doctor|gp|clinician|pharmacist|"
    r"physician|lawyer|solicitor|attorney|adviser|advisor|accountant|professional)\b"
    r"|\bprofessional (?:medical|legal|financial) advice\b"
    r"|\bnot (?:medical|legal|financial) advice\b",
    re.I,
)


RegisterFinding = RiskFinding


@dataclass
class RegisterCheck:
    """Whether the answer claimed more standing than it had."""

    domain: str = GENERAL
    question: str = ""
    hedged: bool = False
    referred: bool = False
    findings: list[RegisterFinding] = field(default_factory=list)

    @property
    def permitted(self) -> bool:
        return not self.findings

    @property
    def verdict(self) -> str:
        severities = {f.severity for f in self.findings}
        if "critical" in severities:
            return "block"
        return "abstain" if severities else "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "question_type": self.question,
            "hedged": self.hedged,
            "referred": self.referred,
            "permitted": self.permitted,
            "verdict": self.verdict,
            "findings": [f.to_json() for f in self.findings],
        }


#: Domains where instruction is regulated activity regardless of correctness.
REGULATED = (MEDICAL, LEGAL, FINANCIAL)


def check_register(
    answer: str,
    *,
    request: str = "",
    licensed_domains: tuple[str, ...] = (),
    domain: str | None = None,
) -> RegisterCheck:
    """Compare what the answer did against what this system is entitled to do.

    ``licensed_domains`` is the declaration that makes this workable: an operator that
    genuinely employs clinicians can license `medical` and the instruction findings stop
    firing. Standing is declared, never inferred — a system cannot work out from its own
    output whether it is allowed to give medical advice.

    The domain is taken from the question and the answer together, because the risk
    lives in either: someone can ask a vague question and get a dose back.
    """
    text = " ".join((answer or "").split())
    qtype = question_type(request) if request else ""
    resolved = domain or domain_of(f"{request} {text}")
    check = RegisterCheck(domain=resolved, question=qtype)
    check.hedged = bool(_UNCERTAINTY.search(text))
    check.referred = bool(_REFERRAL.search(text))

    regulated = resolved in REGULATED and resolved not in licensed_domains

    # --- an instruction in a regulated domain
    if regulated:
        if _DOSAGE.search(text):
            check.findings.append(
                RegisterFinding(
                    "dosage-instruction",
                    f"the answer states a dose. In {resolved} the line is not accuracy but "
                    "instruction — telling someone what to take is regulated activity "
                    "whether or not the figure is right",
                    "critical",
                    {"domain": resolved},
                )
            )
        elif _CONCLUSION.search(text):
            check.findings.append(
                RegisterFinding(
                    "conclusion-about-the-person",
                    f"the answer reaches a {resolved} conclusion about the person rather "
                    "than describing what is generally true",
                    "critical",
                    {"domain": resolved},
                )
            )
        elif _INSTRUCTION.search(text):
            check.findings.append(
                RegisterFinding(
                    "regulated-instruction",
                    f"the answer tells the person what to do in a {resolved} matter. "
                    "General information is not the same act as advice, and the difference "
                    "is the second person",
                    "high",
                    {"domain": resolved},
                )
            )
        if check.findings and not check.referred:
            check.findings.append(
                RegisterFinding(
                    "no-referral",
                    "a regulated answer with no route to someone qualified leaves the "
                    "person with this as their only source",
                    "high",
                    {"domain": resolved},
                )
            )

    # --- false precision about the future
    if qtype == PREDICTION:
        numbers = _POINT_ESTIMATE.findall(text)
        if numbers and not check.hedged:
            check.findings.append(
                RegisterFinding(
                    "false-precision-about-the-future",
                    "the question is about the future, which has no system of record, and "
                    f"the answer gives a point estimate ({numbers[0]}) with no uncertainty. "
                    "'Rates will probably ease' is defensible; a number is something "
                    "somebody plans around",
                    "high",
                    {"values": numbers[:3]},
                )
            )
        elif not check.hedged and text:
            check.findings.append(
                RegisterFinding(
                    "unhedged-prediction",
                    "a claim about the future stated in the same register as a fact",
                    "medium",
                    {},
                )
            )

    # "What dose should I take?" classifies as an opinion question because of the
    # "should I", so this would report a second time on the same sentence. In a
    # regulated domain the regulated path owns that judgement — including when the
    # domain is licensed, where the considered answer is that the instruction is fine.
    if (
        qtype == OPINION
        and resolved not in REGULATED
        and not check.hedged
        and _INSTRUCTION.search(text)
    ):
        check.findings.append(
            RegisterFinding(
                "preference-stated-as-fact",
                "the question asked what the system thinks and the answer instructs "
                "without marking it as a judgement",
                "medium",
                {},
            )
        )

    # --- settled causation
    # Medicine as well as science: "the drug causes the improvement" is the same
    # over-claim whichever bucket the wording lands in, and the domain classifier will
    # usually call that one medical.
    if resolved in (SCIENTIFIC, MEDICAL) and _CAUSAL_CLAIM.search(text) and not check.hedged:
        check.findings.append(
            RegisterFinding(
                "causal-claim-stated-as-settled",
                "a causal mechanism is asserted without the qualification the evidence "
                "carries. Correlation surviving into an answer as cause is the most common "
                "way a correct citation produces a wrong claim",
                "high",
                {},
            )
        )

    return check
