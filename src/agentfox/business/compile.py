"""Turn a written policy into executable guardrails, and ask only what it must.

The previous step suggested *which kind* of guardrail a sentence needed, which left
every parameter — the thresholds, the units, the roles, the band structure — for a
human to transcribe. That is most of the work, so the tool was doing the easy part.

This compiles. Given a policy document it produces complete, executable definitions and
a review queue, and the number that matters is how much lands in the first pile.

Three principles decide what gets escalated:

**State assumptions, do not hide them.** Where a reading is uncertain but one choice is
clearly right, the compiler makes it and *says so* on the rule. An assumption written
down is reviewable in seconds; a question in a queue costs a round-trip.

**Most apparent ambiguity has exactly one sensible answer.** "Under $10 auto-approve,
between $10 and $100 verify" is ambiguous about which band owns exactly 10 — and only
one reading leaves no gap. Flagging that would make the tool tiresome without making it
safer. Genuine ambiguity is where two readings are both viable *and lead to different
enforcement*.

**Every flag is a specific answerable question.** "Please review this rule" is not a
question. "Is 'management' the `finance` or `support` approver role?" is, and it can be
answered in one word by someone who never reads the rest.

Deterministic throughout. A model that silently mis-extracts a threshold is worse than
one that asks, and this is a domain where the structure — numbers, comparators, roles —
is genuinely parseable. A model-assisted path belongs on the sentences this cannot
handle, and its output should land in the same review queue rather than in enforcement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentfox.business.ladder import KNOWN_UNITS, Ladder

# --- Lexicon ---------------------------------------------------------------

_CURRENCY_WORD = {
    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",
    "$": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "eur": "EUR",
    "€": "EUR",
    "pound": "GBP",
    "pounds": "GBP",
    "gbp": "GBP",
    "£": "GBP",
    "yen": "JPY",
    "jpy": "JPY",
    "¥": "JPY",
}

#: Words that place a threshold. The direction matters more than the word.
_UPPER = (
    "under",
    "below",
    "less than",
    "up to",
    "at most",
    "no more than",
    "fewer than",
    "not exceeding",
    "beneath",
    "within",
)
_LOWER = (
    "over",
    "above",
    "more than",
    "greater than",
    "exceeding",
    "exceeds",
    "at least",
    "in excess of",
    "beyond",
    "from",
)

#: How an outcome is written in prose, mapped to what the ladder does.
_OUTCOME_WORDS: list[tuple[tuple[str, ...], str]] = [
    (
        (
            "auto-approve",
            "auto approve",
            "automatically approve",
            "automatically approved",
            "no approval",
            "without approval",
            "auto-approved",
            "approve automatically",
            "may proceed",
            "allowed",
            "no approval required",
            "no approval needed",
            "does not require approval",
            "not require approval",
        ),
        "allow",
    ),
    (
        (
            "human review",
            "manual review",
            "human approval",
            "manager approval",
            "sign-off",
            "sign off",
            "approval from",
            "approved by",
            "escalate",
            "escalated",
            "reviewed by",
            "requires approval",
            "require approval",
            "second pair of eyes",
            "four eyes",
        ),
        "escalate",
    ),
    (
        (
            "validate",
            "validation",
            "verify",
            "verification",
            "check with",
            "cross-reference",
            "confirm with",
            "run a check",
            "fraud check",
            "risk check",
        ),
        "verify",
    ),
    (
        (
            "must not",
            "never",
            "prohibited",
            "forbidden",
            "block",
            "blocked",
            "deny",
            "denied",
            "not permitted",
            "refuse",
        ),
        "block",
    ),
    (("redact", "mask", "remove", "strip"), "redact"),
]

#: Role words to an approver role. Deliberately small — a wrong guess here is a rule
#: that routes an approval to the wrong queue, so anything unrecognised is a question.
_ROLES = {
    "finance": "finance",
    "financial": "finance",
    "accounting": "finance",
    "manager": "manager",
    "management": None,
    "supervisor": "manager",
    "legal": "legal",
    "compliance": "compliance",
    "security": "security",
    "support": "support",
    "customer support": "support",
    "hr": "hr",
    "human resources": "hr",
}

#: Domain words to the tool a rule most likely governs. Used only as a suggestion —
#: an unresolved tool is a question, never a guess that silently governs nothing.
_TOOL_HINTS = {
    "refund": "payments.refund",
    "transfer": "payments.transfer",
    "payment": "payments.transfer",
    "discount": "billing.discount",
    "credit": "billing.credit",
    "delete": "db.query",
    "email": "email.send",
}

#: The scale suffix must be a whole word. Without the boundary, "$100 must run" read
#: the `m` of "must" as "million" and turned a hundred-dollar threshold into a
#: hundred-million-dollar one — silently, and in the direction that approves more.
_AMOUNT = re.compile(
    r"([£$€¥])?\s*(\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(k|m|thousand|million)\b)?"
    r"(?:\s*(dollars?|euros?|pounds?|yen|usd|eur|gbp|jpy)\b)?",
    re.I,
)
_SCALE = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000}
#: Same whole-word rule as `_AMOUNT`: an unbounded `(?:k|m)?` here swallowed the `m`
#: of the following word and inflated the upper bound by a million.
_BETWEEN = re.compile(
    r"\bbetween\s+([£$€¥]?\s?[\d,.]+(?:\s*[km]\b)?)"
    r"\s*(?:and|-|–|to)\s*"
    r"([£$€¥]?\s?[\d,.]+(?:\s*[km]\b)?)",
    re.I,
)
#: Blank lines separate paragraphs; a single newline is just a wrapped line and must
#: not end a sentence. Real policy documents are wrapped, and treating a wrap as a
#: boundary silently split "fraud check" across two fragments so neither matched.
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.;!?])\s+")


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for paragraph in _PARAGRAPH.split(text or ""):
        # Collapse the wrapping before any phrase matching happens.
        flat = " ".join(paragraph.split())
        out.extend(s.strip() for s in _SENTENCE.split(flat) if s.strip())
    return out


@dataclass
class Assumption:
    """Something the compiler decided so a human did not have to."""

    what: str
    why: str

    def to_json(self) -> dict[str, str]:
        return {"what": self.what, "why": self.why}


@dataclass
class ReviewItem:
    """A specific answerable question. Never "please review"."""

    question: str
    source: str
    why: str
    options: list[str] = field(default_factory=list)
    #: True when nothing can be compiled until this is answered.
    blocking: bool = True
    rule_key: str = ""
    #: Every sentence this question stands in for. One question can block a ladder
    #: assembled from four sentences, and all four have to stay accounted for.
    covers: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "options": self.options,
            "why": self.why,
            "source": self.source,
            "blocking": self.blocking,
            "rule_key": self.rule_key,
        }


@dataclass
class CompiledRule:
    """A complete, executable definition, with what was assumed to reach it."""

    key: str
    kind: str
    definition: dict[str, Any]
    sources: list[str] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    confidence: float = 1.0

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "definition": self.definition,
            "sources": self.sources,
            "assumptions": [a.to_json() for a in self.assumptions],
            "confidence": round(self.confidence, 3),
        }


@dataclass
class Compilation:
    rules: list[CompiledRule] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    #: Sentences that are governance but express something we cannot enforce. Worth
    #: knowing early — a policy the product cannot represent is a procurement finding,
    #: not a bug to discover in month three.
    unmappable: list[str] = field(default_factory=list)
    #: Sentences that are not governance at all: headings, preamble, definitions.
    ignored: list[str] = field(default_factory=list)
    #: Every sentence judged to be governance, recorded as it is read.
    #:
    #: Derived from the output buckets, this number was wrong in the direction that
    #: flatters: when several sentences fed one ladder and the ladder was blocked on a
    #: question, only the first was attached to that question and the rest were counted
    #: nowhere at all. Sentences that govern real money left no trace in any bucket.
    governance: list[str] = field(default_factory=list)

    @property
    def governance_sentences(self) -> int:
        return len(self.governance)

    def unaccounted(self) -> list[str]:
        """Governance sentences that reached no bucket. Must always be empty."""
        placed = {s for rule in self.rules for s in rule.sources}
        placed |= {s for item in self.review for s in item.covers or [item.source]}
        placed |= set(self.unmappable)
        return [s for s in self.governance if s not in placed]

    @property
    def auto_rate(self) -> float:
        """Share of governance that compiled with no blocking question.

        The number this module exists to move. Assumptions do not count against it —
        an assumption stated on the rule is reviewed in seconds, and treating it as a
        failure would push the compiler towards asking about everything.
        """
        total = self.governance_sentences
        if not total:
            return 1.0
        blocked = len(
            {
                sentence
                for item in self.review
                if item.blocking
                for sentence in (item.covers or [item.source])
            }
        )
        return (total - blocked - len(self.unmappable)) / total

    def to_json(self) -> dict[str, Any]:
        return {
            "rules": [rule.to_json() for rule in self.rules],
            "review": [item.to_json() for item in self.review],
            "unmappable": self.unmappable,
            "ignored": self.ignored,
            "auto_rate": round(self.auto_rate, 3),
            "governance_sentences": self.governance_sentences,
        }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _amount(text: str) -> tuple[float | None, str | None]:
    match = _AMOUNT.search(text)
    if not match:
        return None, None
    symbol, digits, scale, word = match.groups()
    try:
        value = float(digits.replace(",", ""))
    except ValueError:
        return None, None
    if scale:
        value *= _SCALE[scale.lower()]
    unit = None
    if symbol:
        unit = _CURRENCY_WORD.get(symbol)
    elif word:
        unit = _CURRENCY_WORD.get(word.lower())
    return value, unit


#: "need finance approval", "requires legal sign-off". Naming the approving team
#: between the verb and the noun is the most common way a policy writes escalation,
#: and matching only fixed phrases missed every variant that named a team we had not
#: listed — the sentence was then dropped as non-governance, not flagged.
_NEEDS_APPROVAL = re.compile(
    r"\b(?:require|requires|required|need|needs|must (?:get|obtain|have|seek)|subject to)\b"
    r"(?:\s+\w+){0,3}?\s+"
    r"(?:approval|approvals|authorisation|authorization|sign-?off|sign\s?off)\b"
)


def _outcome(text: str) -> str | None:
    lowered = " ".join(text.lower().split())
    # Ordered by specificity: "requires approval" must beat a bare "approve".
    for words, outcome in _OUTCOME_WORDS:
        for word in sorted(words, key=len, reverse=True):
            if word in lowered:
                return outcome
    if _NEEDS_APPROVAL.search(lowered):
        return "escalate"
    return None


def _role(text: str) -> tuple[str | None, str | None]:
    """Return (role, ambiguous_word). A recognised-but-unmapped word is a question."""
    lowered = text.lower()
    for word in sorted(_ROLES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            mapped = _ROLES[word]
            return (mapped, None) if mapped else (None, word)
    return None, None


#: The thing a threshold is about — "purchase orders", "refunds", "wire transfers".
#: A question that quotes the subject can be answered in a word by someone who has not
#: read the document; "which tool does this govern?" cannot.
_SUBJECT = re.compile(
    r"^\s*(?:all\s+|any\s+|every\s+)?([a-z][a-z ]{2,28}?)\s+"
    r"(?:under|over|above|below|between|from|in excess of|of more than|greater than|"
    r"less than|up to|that|which|must|may|require|requires|need|needs|are|is)\b",
    re.I,
)


def _subject(sentence: str) -> str | None:
    match = _SUBJECT.search(sentence.strip())
    if not match:
        return None
    subject = match.group(1).strip().lower()
    return subject if len(subject.split()) <= 3 else None


def _tool(text: str) -> str | None:
    lowered = text.lower()
    explicit = re.search(r"\b([a-z_]+\.[a-z_]+)\b", lowered)
    if explicit:
        return explicit.group(1)
    for word, tool in _TOOL_HINTS.items():
        if word in lowered:
            return tool
    return None


@dataclass
class _Clause:
    """One threshold statement pulled out of a sentence."""

    lower: float | None
    upper: float | None
    outcome: str
    unit: str | None
    role: str | None
    #: The clause fragment, which is what a question should quote.
    source: str
    #: The whole sentence the fragment came from. A sentence usually carries several
    #: clauses, and accounting for which sentences were handled has to happen at
    #: sentence granularity or it silently loses the ones that were split.
    sentence: str = ""
    ambiguous_role: str | None = None


def _clauses(sentence: str) -> list[_Clause]:
    """Split a sentence into the threshold statements it contains.

    Policy sentences routinely carry the whole ladder — "under $10 auto-approve, $10 to
    $100 verify, above $100 needs review" — so splitting on commas and conjunctions
    recovers the bands that a per-sentence parser would collapse into one.
    """
    parts = re.split(
        r",|;| and (?=[^,]*\b(?:under|over|above|below|between|more|less)\b)", sentence
    )
    out: list[_Clause] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        outcome = _outcome(text)
        if outcome is None:
            continue
        role, ambiguous = _role(text)
        unit = None

        between = _BETWEEN.search(text)
        if between:
            low, low_unit = _amount(between.group(1))
            high, high_unit = _amount(between.group(2))
            out.append(
                _Clause(low, high, outcome, low_unit or high_unit, role, text, sentence, ambiguous)
            )
            continue

        value, unit = _amount(text)
        if value is None:
            continue
        lowered = text.lower()
        if any(word in lowered for word in _UPPER):
            out.append(_Clause(None, value, outcome, unit, role, text, sentence, ambiguous))
        elif any(word in lowered for word in _LOWER):
            out.append(_Clause(value, None, outcome, unit, role, text, sentence, ambiguous))
        else:
            out.append(_Clause(None, value, outcome, unit, role, text, sentence, ambiguous))
    return out


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

#: Prohibition without a modal verb. "No destructive queries may be run against
#: production" contains no must/should/never, and was silently ignored — the single
#: strongest sentence in a document is often written this way.
_PROHIBITION = re.compile(
    r"^\s*(?:no|never|under no circumstances)\b"
    r"|\b(?:may not|must not|cannot|shall not|is not permitted|are not permitted"
    r"|is prohibited|are prohibited|is forbidden|are forbidden|do not|don't)\b"
)

_NOT_GOVERNANCE = (
    "this document",
    "purpose",
    "scope",
    "definitions",
    "revision",
    "version",
    "approved by",
    "effective date",
    "contact",
    "see also",
    "appendix",
    "table of",
)


def _is_governance(sentence: str) -> bool:
    lowered = sentence.lower().strip()
    if len(lowered) < 12:
        return False
    if lowered.endswith(":") and len(lowered) < 60:
        return False  # a heading
    if any(marker in lowered for marker in _NOT_GOVERNANCE):
        return False
    if _PROHIBITION.search(lowered):
        return True
    return _outcome(sentence) is not None or any(
        word in lowered
        for word in ("must", "should", "may only", "never", "always", "require", "need")
    )


def compile_document(text: str, *, key_prefix: str = "policy") -> Compilation:
    """Compile a written policy into executable rules and a short review queue."""
    result = Compilation()
    sentences = _sentences(text)

    ladder_clauses: list[_Clause] = []
    for sentence in sentences:
        if not _is_governance(sentence):
            result.ignored.append(sentence)
            continue
        result.governance.append(sentence)
        found = _clauses(sentence)
        if found and any(c.unit for c in found):
            ladder_clauses.extend(found)
        elif found:
            # A number with no currency. "escalate after 3 failed attempts" and
            # "fewer than 5 contributors" both parse as thresholds, and both were being
            # merged into whatever money ladder the document happened to contain — then
            # lost outright when that ladder stopped to ask which tool it governed. Try
            # the typed extractors first; a count-based guardrail knows its own shape.
            if not _handle_non_threshold(sentence, result, key_prefix, quiet=True):
                ladder_clauses.extend(found)
        else:
            _handle_non_threshold(sentence, result, key_prefix)

    if ladder_clauses:
        _build_ladders(ladder_clauses, result, key_prefix)
    return result


def _handle_non_threshold(
    sentence: str, result: Compilation, key_prefix: str, *, quiet: bool = False
) -> bool:
    """Sentences that govern but carry no threshold.

    The point of this path is to produce *parameters*, not a label. Naming the right
    guardrail and leaving every field blank looks like progress on a coverage report
    and enforces nothing at runtime, so a rule is only emitted here when its
    definition is complete enough to run. Anything short of that becomes a question.
    """
    from agentfox.business.catalogue import CATALOGUE, suggest

    lowered = " ".join(sentence.lower().split())
    matches = suggest(sentence, limit=3)

    # The best-scoring kind is not always the one whose parameters are present. "PII in
    # any reply must be masked" scores highest as an output contract, which has nothing
    # to extract, while the PII detector two places down reads it exactly. Prefer the
    # highest-ranked kind that yields a *complete* definition over the highest-ranked
    # kind outright.
    for kind, _score in matches:
        extractor = _EXTRACTORS.get(kind.id)
        if extractor and (extraction := extractor(sentence, lowered)):
            _emit(result, kind, extraction, sentence, key_prefix)
            return True

    if not matches:
        # Nothing in the catalogue recognised the wording. The extractors are narrow
        # enough to be their own detectors, so let them try: each returns None unless
        # its own parameters are actually present.
        for kind_id, extractor in _EXTRACTORS.items():
            if extraction := extractor(sentence, lowered):
                kind = next(k for k in CATALOGUE if k.id == kind_id)
                extraction.confidence = min(extraction.confidence, 0.65)
                extraction.assumptions.append(
                    Assumption(
                        what=f"read as {kind.name.lower()} from the settings it names",
                        why="the wording matched no guardrail in the catalogue, but the "
                        "values this kind needs are all present in the sentence",
                    )
                )
                _emit(result, kind, extraction, sentence, key_prefix)
                return True
        if not quiet:
            result.unmappable.append(sentence)
        return False

    kind, _score = matches[0]
    if kind.id in ("threshold_ladder", "approval_requirement"):
        if quiet:
            return False
        # Approval language with no threshold: an unconditional rule, which is
        # expressible but almost never what the author meant.
        result.review.append(
            ReviewItem(
                question="Does this apply to every call, or only above some amount?",
                source=sentence,
                why="approval language with no threshold compiles to an unconditional "
                "rule, which fires on every request",
                options=["unconditional", "add a threshold"],
                blocking=True,
            )
        )
        return False

    # No extractor produced a definition. A guardrail that takes no parameters is
    # complete the moment it is named; anything else becomes a question.
    if not kind.params:
        _emit(result, kind, _Extraction({}, [], [], 0.9), sentence, key_prefix)
        return True

    if quiet:
        return False
    needed = ", ".join(kind.params)
    result.review.append(
        ReviewItem(
            question=f"This reads like {kind.name.lower()}. What should {needed} be?",
            source=sentence,
            why="the guardrail is clear from the wording but its settings are not "
            "stated, and a rule with empty settings enforces nothing",
            blocking=True,
            rule_key=f"{key_prefix}-{kind.id.replace('_', '-')}",
        )
    )
    return False


def _emit(
    result: Compilation, kind: Any, extraction: _Extraction, sentence: str, key_prefix: str
) -> None:
    key = f"{key_prefix}-{kind.id.replace('_', '-')}"
    for item in extraction.review:
        item.source = item.source or sentence
        item.rule_key = item.rule_key or key
        result.review.append(item)
    result.rules.append(
        CompiledRule(
            key=key,
            kind=kind.id,
            definition={"kind": kind.id, **extraction.definition},
            sources=[sentence],
            assumptions=extraction.assumptions,
            confidence=extraction.confidence,
        )
    )


# --- Parameter extraction --------------------------------------------------
#
# One function per guardrail kind. Each returns a complete definition or None, and
# None routes the sentence to review rather than emitting a hollow rule.


@dataclass
class _Extraction:
    definition: dict[str, Any]
    assumptions: list[Assumption] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    confidence: float = 0.85


_PII_ENTITIES = {
    "email": "EMAIL_ADDRESS",
    "email address": "EMAIL_ADDRESS",
    "phone": "PHONE_NUMBER",
    "phone number": "PHONE_NUMBER",
    "ssn": "US_SSN",
    "social security": "US_SSN",
    "credit card": "CREDIT_CARD",
    "card number": "CREDIT_CARD",
    "home address": "LOCATION",
    "date of birth": "DATE_TIME",
    "passport": "US_PASSPORT",
    "bank account": "US_BANK_NUMBER",
    "ip address": "IP_ADDRESS",
    "medical": "MEDICAL_LICENSE",
}

#: Words that name a protected subject when a sentence forbids disclosing it.
_SENSITIVE = (
    "salary",
    "compensation",
    "payroll",
    "pay data",
    "headcount",
    "pricing",
    "margin",
    "cost basis",
    "roadmap",
    "legal",
    "litigation",
    "personnel",
    "performance review",
    "termination",
    "acquisition",
    "merger",
)

_REGULATED = (
    "legal advice",
    "medical",
    "health",
    "tax advice",
    "immigration",
    "investment advice",
    "financial advice",
    "diagnosis",
    "prescription",
)

_DESTRUCTIVE_VERBS = (
    "delete",
    "drop",
    "truncate",
    "destructive",
    "wipe",
    "purge",
    "mass update",
    "bulk update",
    "alter",
)


def _audience(text: str) -> tuple[list[str], str | None]:
    """Who a disclosure is permitted to. Returns (roles, unmapped_word)."""
    scope = re.search(
        r"\b(?:outside(?: of)?|other than|except(?: for)?|besides|beyond)\s+"
        r"(?:the\s+)?([A-Za-z][\w \-]{1,40})",
        text,
    )
    if not scope:
        return [], None
    role, ambiguous = _role(scope.group(1))
    return ([role] if role else []), ambiguous


def _extract_entitlement(sentence: str, lowered: str) -> _Extraction | None:
    subjects = [w for w in _SENSITIVE if w in lowered]
    if not subjects:
        # Fall back to the object of the disclosure verb.
        obj = re.search(
            r"\b(?:disclose|share|reveal|expose|send|provide|show|give)\s+"
            r"(?:any\s+|all\s+|the\s+)?([\w \-]{3,40}?)\s+"
            r"(?:to|with|outside|for)\b",
            lowered,
        )
        if not obj:
            return None
        subjects = [obj.group(1).strip()]

    roles, ambiguous = _audience(lowered)
    review: list[ReviewItem] = []
    if ambiguous:
        review.append(
            ReviewItem(
                question=f"Which role is '{ambiguous}'?",
                source="",
                why="the audience decides who this rule lets through, and "
                "guessing it wrong either leaks or blocks everyone",
                options=sorted({r for r in _ROLES.values() if r}),
            )
        )
    definition: dict[str, Any] = {
        "engine": "native",
        "default": "deny",
        "protected_subjects": sorted(set(subjects)),
    }
    assumptions = [
        Assumption(
            what="default deny — anyone not named is refused",
            why="a disclosure rule written as a prohibition is a deny-list by intent",
        )
    ]
    if roles:
        definition["permitted_roles"] = roles
    return _Extraction(definition, assumptions, review, 0.85 if roles else 0.75)


def _extract_escalation(sentence: str, lowered: str) -> _Extraction | None:
    definition: dict[str, Any] = {}
    assumptions: list[Assumption] = []

    if re.search(r"\b(frustrat|angry|upset|abusive|irate|distress|dissatisf|complain)", lowered):
        definition["sentiment_below"] = 0.3
        assumptions.append(
            Assumption(
                what="'frustrated' read as sentiment below 0.3",
                why="the policy names a feeling, not a number; 0.3 is the tuned default and "
                "is the one setting here worth revisiting after a week of traffic",
            )
        )
    if m := re.search(r"after\s+(\d+)\s+(?:failed|unsuccessful|repeated)", lowered):
        definition["repeated_failure"] = int(m.group(1))
    if m := re.search(r"after\s+(\d+)\s+(?:turns?|messages?|exchanges?|replies)", lowered):
        definition["turn_depth"] = int(m.group(1))
    if m := re.search(r"within\s+(\d+)\s+(minutes?|hours?)", lowered):
        minutes = int(m.group(1)) * (60 if m.group(2).startswith("hour") else 1)
        definition["sla_minutes"] = minutes
    topics = [t for t in _REGULATED if t in lowered]
    if topics:
        definition["regulated_topics"] = topics

    if not definition:
        return None
    role, ambiguous = _role(lowered)
    review: list[ReviewItem] = []
    if role:
        definition["to_role"] = role
    elif ambiguous:
        review.append(
            ReviewItem(
                question=f"Which approver role is '{ambiguous}'?",
                source="",
                why="escalation has to name a queue that exists, or it lands nowhere",
                options=sorted({r for r in _ROLES.values() if r}),
            )
        )
    return _Extraction(definition, assumptions, review, 0.85)


def _extract_source_authority(sentence: str, lowered: str) -> _Extraction | None:
    if "source of truth" in lowered or "system of record" in lowered:
        tier = "system_of_record"
    elif re.search(r"\b(approved|authorised|authorized|official|sanctioned)\b", lowered):
        tier = "approved"
    elif re.search(r"\b(verified|trusted)\b", lowered):
        tier = "approved"
    else:
        return None

    definition: dict[str, Any] = {"required_tier": tier}
    assumptions: list[Assumption] = []
    if m := re.search(r"no older than\s+(\d+)\s+(hours?|days?)", lowered):
        hours = int(m.group(1)) * (24 if m.group(2).startswith("day") else 1)
        definition["max_age_hours"] = hours
    else:
        assumptions.append(
            Assumption(
                what="no freshness limit — any age of source satisfies this",
                why="the policy sets an authority bar but no staleness bar, and inventing "
                "one would reject sources the author meant to allow",
            )
        )
    if m := re.search(r"\bfor\s+([\w \-]{3,30}?)\s+(?:questions|queries|topics|matters)", lowered):
        definition["topic"] = m.group(1).strip()
    return _Extraction(definition, assumptions, [], 0.85)


def _extract_action_analysis(sentence: str, lowered: str) -> _Extraction | None:
    verbs = [v for v in _DESTRUCTIVE_VERBS if v in lowered]
    if not verbs:
        return None
    definition: dict[str, Any] = {
        "deny_verbs": ["DELETE", "DROP", "TRUNCATE", "ALTER", "UPDATE_WITHOUT_WHERE"],
    }
    environments = [e for e in ("production", "prod", "live") if e in lowered]
    if environments:
        definition["environments"] = ["production"]
    assumptions = [
        Assumption(
            what="'destructive' read as DELETE, DROP, TRUNCATE, ALTER, and UPDATE "
            "with no WHERE clause",
            why="the policy names the category, not the statements; this is the set the "
            "SQL analyser already recognises as irreversible",
        ),
        Assumption(
            what="parsed with the generic SQL dialect",
            why="no dialect is named, and the generic parser reads all five verbs "
            "correctly — only dialect-specific syntax would need this changed",
        ),
    ]
    return _Extraction(definition, assumptions, [], 0.85)


def _extract_pii(sentence: str, lowered: str) -> _Extraction | None:
    entities = sorted({v for k, v in _PII_ENTITIES.items() if k in lowered})
    if not entities:
        if not re.search(
            r"\b(pii|personal (?:data|information)|personally identifiable)\b", lowered
        ):
            return None
        entities = ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD", "PERSON"]
        assumptions = [
            Assumption(
                what="'personal data' read as the standard entity set",
                why="the policy names the category rather than the fields, and this is the "
                "set the detector treats as personal data by default",
            )
        ]
    else:
        assumptions = []
    redaction = "tokenize" if "tokenis" in lowered or "tokeniz" in lowered else "mask"
    return _Extraction({"entities": entities, "redaction": redaction}, assumptions, [], 0.85)


def _extract_aggregation_floor(sentence: str, lowered: str) -> _Extraction | None:
    if m := re.search(
        r"(?:fewer than|less than|at least|minimum of)\s+(\d+)\s+"
        r"(?:people|employees|individuals|contributors|records|respondents)",
        lowered,
    ):
        return _Extraction({"k": int(m.group(1))}, [], [], 0.9)
    return None


def _extract_spend_budget(sentence: str, lowered: str) -> _Extraction | None:
    definition: dict[str, Any] = {}
    if m := re.search(
        r"(?:no more than|at most|up to|maximum of)\s+(\d[\d,]*)\s+"
        r"(?:calls?|requests?|invocations?)",
        lowered,
    ):
        definition["max_calls"] = int(m.group(1).replace(",", ""))
    if m := re.search(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(?:per|a|each)\b", lowered):
        definition["max_cost_usd"] = float(m.group(1).replace(",", ""))
    if not definition:
        return None
    window = re.search(r"\bper\s+(hour|day|week|month|minute)\b", lowered)
    definition["window"] = f"1{window.group(1)[0]}" if window else "1d"
    assumptions = (
        []
        if window
        else [
            Assumption(
                what="budget window read as one day",
                why="no window is stated, and a budget with no window is either unlimited or "
                "instantly exhausted depending on how it is read",
            )
        ]
    )
    return _Extraction(definition, assumptions, [], 0.8)


def _extract_knowledge_boundary(sentence: str, lowered: str) -> _Extraction | None:
    definition: dict[str, Any] = {}
    if m := re.search(r"(?:last|past|previous|only)\s+(\d+)\s+months?", lowered):
        definition["coverage_months"] = int(m.group(1))
    if m := re.search(r"(?:last|past|previous|only)\s+(\d+)\s+years?", lowered):
        definition["coverage_months"] = int(m.group(1)) * 12
    if re.search(r"\b(?:predict|forecast|speculat|guess|opinion)", lowered):
        definition["answerable_types"] = ["fact", "aggregate", "procedure"]
    if not definition:
        return None
    return _Extraction(definition, [], [], 0.85)


def _extract_taint_ceiling(sentence: str, lowered: str) -> _Extraction | None:
    for word, level in (
        ("web", "retrieved"),
        ("retrieved", "retrieved"),
        ("search result", "retrieved"),
        ("user", "user"),
        ("tool", "tool_result"),
        ("memory", "memory"),
    ):
        if word in lowered:
            return _Extraction({"max_taint": level}, [], [], 0.75)
    return None


def _extract_rate_of_change(sentence: str, lowered: str) -> _Extraction | None:
    if m := re.search(
        r"(?:no more than|at most|maximum of)\s+(\d+)\s+"
        r"(?:times?|repeats?|attempts?|retries)",
        lowered,
    ):
        return _Extraction({"max_repeats": int(m.group(1))}, [], [], 0.9)
    return None


def _extract_verified_state(sentence: str, lowered: str) -> _Extraction | None:
    if m := re.search(r"within\s+(?:the last\s+)?(\d+)\s+(seconds?|minutes?|hours?)", lowered):
        n = int(m.group(1))
        unit = m.group(2)
        per = 1 if unit.startswith("second") else 60 if unit.startswith("minute") else 3600
        seconds = n * per
        return _Extraction({"max_age_seconds": seconds}, [], [], 0.9)
    if re.search(r"\b(?:re-?read|re-?check|confirm|verify)\b.*\bbefore\b", lowered):
        return _Extraction(
            {"max_age_seconds": 60},
            [
                Assumption(
                    what="the read must be under 60 seconds old",
                    why="the policy requires a fresh read but does not say how fresh; 60s is "
                    "the default and the one number here worth confirming",
                )
            ],
            [],
            0.7,
        )
    return None


_EXTRACTORS: dict[str, Any] = {
    "entitlement_filter": _extract_entitlement,
    "escalation_policy": _extract_escalation,
    "source_authority": _extract_source_authority,
    "action_analysis": _extract_action_analysis,
    "pii_detection": _extract_pii,
    "aggregation_floor": _extract_aggregation_floor,
    "spend_budget": _extract_spend_budget,
    "knowledge_boundary": _extract_knowledge_boundary,
    "taint_ceiling": _extract_taint_ceiling,
    "rate_of_change": _extract_rate_of_change,
    "verified_state_precondition": _extract_verified_state,
}


def _build_ladders(clauses: list[_Clause], result: Compilation, key_prefix: str) -> None:
    """Assemble threshold clauses into one total ladder per (tool, unit)."""
    units = {c.unit for c in clauses if c.unit}
    tool = _tool(" ".join(c.source for c in clauses))
    #: Fragments for quoting back in a question; whole sentences for accounting.
    source_fragments = [c.source for c in clauses]
    source_sentences = list(dict.fromkeys(c.sentence or c.source for c in clauses))

    if len(units) > 1:
        result.review.append(
            ReviewItem(
                question=f"These thresholds mix {sorted(units)}. Which currency governs?",
                source=" / ".join(source_fragments[:2]),
                why="a threshold agreed in one currency must not silently apply in "
                "another, and converting is not ours to decide",
                options=sorted(units),
                covers=source_sentences,
            )
        )
        return

    assumptions: list[Assumption] = []
    unit = next(iter(units), None)
    if unit is None:
        # A bare number with no currency anywhere. This is genuinely ambiguous only if
        # the field could be money; if the wording is about counts, "count" is right.
        result.review.append(
            ReviewItem(
                question="What unit are these numbers in?",
                source=source_fragments[0],
                why="a bare threshold is the bug that approves a hundred-fold larger "
                "refund when one team means cents and another means dollars",
                options=[u for u in KNOWN_UNITS if not u.endswith("_CENTS")],
                covers=source_sentences,
            )
        )
        return

    if tool is None:
        result.review.append(
            ReviewItem(
                question=(
                    f"Which tool handles {subject}?"
                    if (subject := _subject(source_sentences[0]))
                    else "Which tool does this govern?"
                ),
                source=source_fragments[0],
                why="a ladder with no tool would band every call that happens to carry "
                "a matching field",
                options=sorted(set(_TOOL_HINTS.values())),
                covers=source_sentences,
            )
        )
        return
    if not any(re.search(r"\b[a-z_]+\.[a-z_]+\b", c.source.lower()) for c in clauses):
        assumptions.append(
            Assumption(
                what=f"governs the tool '{tool}'",
                why="inferred from the wording; no tool was named explicitly",
            )
        )

    # Order by upper bound; the open-ended clause goes last.
    bounded = sorted([c for c in clauses if c.upper is not None], key=lambda c: c.upper or 0)
    open_ended = [c for c in clauses if c.upper is None]

    bands: list[dict[str, Any]] = []
    for clause in bounded:
        band: dict[str, Any] = {
            "upto": clause.upper,
            "outcome": clause.outcome,
            "reason": clause.source[:120],
        }
        if clause.outcome == "verify":
            band["verify"] = {"check": "risk.check", "on_fail": "escalate"}
            assumptions.append(
                Assumption(
                    what="verification calls 'risk.check'",
                    why="the policy says to validate but does not name the check",
                )
            )
        if clause.outcome == "escalate" and clause.role:
            band["approver_role"] = clause.role
        bands.append(band)

    if open_ended:
        top = open_ended[-1]
        band = {"outcome": top.outcome, "reason": top.source[:120]}
        if top.role:
            band["approver_role"] = top.role
        bands.append(band)
    else:
        # No sentence covered the top of the range. Rather than leave a hole — the exact
        # defect this construct removes — close it at the strictest outcome present and
        # say so.
        strictest = max(
            (c.outcome for c in clauses),
            key=lambda o: ["allow", "verify", "redact", "escalate", "block"].index(o),
        )
        bands.append(
            {
                "outcome": strictest,
                "reason": "closes the ladder; no sentence covered the top of the range",
            }
        )
        assumptions.append(
            Assumption(
                what=f"values above the highest threshold are '{strictest}'",
                why="no sentence covered them, and a ladder with an open top has the "
                "silent gap this construct exists to remove",
            )
        )

    # Overlapping upper bounds mean two sentences disagree about the same range.
    uppers = [b["upto"] for b in bands if "upto" in b]
    if len(uppers) != len(set(uppers)):
        result.review.append(
            ReviewItem(
                question=f"Two rules both stop at {uppers[0]}. Which applies?",
                source=" / ".join(source_fragments[:2]),
                why="overlapping bands mean two sentences claim the same range",
                covers=source_sentences,
            )
        )
        return

    ambiguous_roles = [c.ambiguous_role for c in clauses if c.ambiguous_role]
    if ambiguous_roles:
        result.review.append(
            ReviewItem(
                question=f"Which approver role is '{ambiguous_roles[0]}'?",
                source=next(c.source for c in clauses if c.ambiguous_role),
                why="routing an approval to the wrong queue is worse than not routing it",
                options=sorted({v for v in _ROLES.values() if v}),
                covers=source_sentences,
                blocking=False,
            )
        )

    # Boundaries: prose leaves the endpoint ambiguous, and exactly one reading is
    # total. Take it, and say which.
    assumptions.append(
        Assumption(
            what="each threshold is inclusive — 'under $10' and 'from $10' both put 10 "
            "in the lower band",
            why="the wording leaves the endpoint open and only one reading leaves no gap",
        )
    )

    definition = {
        "key": f"{key_prefix}-{tool.replace('.', '-')}",
        "tool": tool,
        "field": "arguments.amount",
        "unit": unit,
        "mode": "observe",
        "bands": bands,
    }
    try:
        Ladder.model_validate(definition)
    except Exception as exc:
        result.review.append(
            ReviewItem(
                question=f"These thresholds do not form a valid ladder: {exc}",
                source=" / ".join(source_fragments[:2]),
                why="the compiler could not assemble them into non-overlapping bands",
                covers=source_sentences,
            )
        )
        return

    result.rules.append(
        CompiledRule(
            key=definition["key"],
            kind="threshold_ladder",
            definition=definition,
            sources=source_sentences,
            assumptions=assumptions,
            confidence=round(max(0.5, 1.0 - 0.1 * len(assumptions)), 3),
        )
    )
