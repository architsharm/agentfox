"""Which evaluator is allowed to decide what, and why — from measurement.

The product should get better as an operator turns capabilities on, and must
not get worse. Those are different requirements and the second one is the hard
one: a hosted judgment model is a large gain on some decisions and a
*regression* on others, and "enable everything" is the configuration most
people will pick.

So the routing table below is not advice. Every entry carries the measurement
it came from (`EVIDENCE`), and a tier that measured worse than code on a kind
of decision is **excluded from deciding it**, however many capabilities are
enabled. Turning Jev on cannot make SQL blast-radius analysis worse, because
Jev is not permitted to answer that question.

The five kinds, and what the benchmarks say (full tables in
`docs/jev-final-numbers.md`):

    STRUCTURAL_PARSED   a property of a parse tree — does this DELETE have a
                        bounding WHERE. code 100.0%, Jev 98.3%. Code decides,
                        alone.
    STRUCTURAL_GRANT    a lookup against what was granted — may this caller
                        see this resource. code exact, Jev 18.5%. Code
                        decides, alone.
    PATTERN_OPEN        pattern-shaped but the surface forms are not
                        enumerable — PII presence, an injection payload.
                        Neither alone is best: SQLi 91.7% code / 84.6% Jev /
                        94.9% unioned. Union.
    SEMANTIC            what the text means — is this question contested.
                        code 8.4%, Jev 81.7%. Judgment decides; code cannot.
    PERFORMATIVE        what an utterance *does* rather than says — "shall I
                        send the rejection" settles a decision. Every
                        evaluator is weak; the honest outcome is escalation,
                        not a verdict.

Two rules make "enable more, get better" true rather than hoped-for:

1. **A tier never decides a kind it measured worse on.** Enabling it adds
   coverage elsewhere and changes nothing here.
2. **Union only where union measured better.** Adding an opinion to a
   decision that is already right is how a 100% control becomes a 98% one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "Combine",
    "DecisionKind",
    "Evidence",
    "Measurement",
    "Plan",
    "Tier",
    "CapabilityRouter",
    "EVIDENCE",
    "ROUTING",
]


class Tier(StrEnum):
    """An evaluator an operator can switch on. Ordered cheapest-first."""

    DETERMINISTIC = "deterministic"  # regex, parsers, grant lookups. Always on.
    LOCAL_MODEL = "local_model"  # PIGuard, Granite Guardian, embeddings. Local.
    JEV = "jev"  # hosted judgment model. Egress.
    LLM = "llm"  # hosted general model as judge. Egress, slowest.
    LOCAL_LLM = "local_llm"  # a self-hosted general model. No egress.


#: Tiers whose use sends the payload off the customer's boundary.
EGRESS_TIERS = frozenset({Tier.JEV, Tier.LLM})


class DecisionKind(StrEnum):
    STRUCTURAL_PARSED = "structural_parsed"
    STRUCTURAL_GRANT = "structural_grant"
    PATTERN_OPEN = "pattern_open"
    SEMANTIC = "semantic"
    PERFORMATIVE = "performative"


class Combine(StrEnum):
    CODE_WINS = "code_wins"  # deterministic answer is final; others advisory
    UNION = "union"  # any decider flagging is a flag
    VOTE = "vote"  # at least `quorum` deciders must agree
    BEST_AVAILABLE = "best_available"  # the highest-ranked enabled decider
    ESCALATE = "escalate"  # no evaluator is trusted; hand to a person


@dataclass(frozen=True, slots=True)
class Measurement:
    """One benchmarked number, kept so an exclusion can be justified."""

    accuracy: float
    corpus: str
    n: int
    note: str = ""


#: What each tier measured on each kind. Absent means unmeasured, which is
#: treated as "may not decide" rather than "probably fine".
EVIDENCE: dict[tuple[DecisionKind, Tier], Measurement] = {
    (DecisionKind.STRUCTURAL_PARSED, Tier.DETERMINISTIC): Measurement(
        100.0, "gretelai/synthetic_text_to_sql", 5528, "analyse_sql(), 1 false block"
    ),
    (DecisionKind.STRUCTURAL_PARSED, Tier.JEV): Measurement(
        98.3, "gretelai/synthetic_text_to_sql", 5528, "819 false blocks at 0.5"
    ),
    (DecisionKind.STRUCTURAL_GRANT, Tier.DETERMINISTIC): Measurement(
        100.0, "PrivacyLens (mechanical)", 493, "exact by construction"
    ),
    (DecisionKind.STRUCTURAL_GRANT, Tier.JEV): Measurement(
        18.5, "PrivacyLens", 493, "recall-only; no negatives in the corpus"
    ),
    (DecisionKind.PATTERN_OPEN, Tier.DETERMINISTIC): Measurement(
        91.7, "payload-box SQLi", 156, "100% precision, 89.3% recall"
    ),
    (DecisionKind.PATTERN_OPEN, Tier.JEV): Measurement(
        84.6, "payload-box SQLi", 156, "union with code reaches 94.9%"
    ),
    (DecisionKind.SEMANTIC, Tier.DETERMINISTIC): Measurement(
        83.5, "KUQ + CoCoNot", 5161, "8.4% recall on contested questions"
    ),
    (DecisionKind.SEMANTIC, Tier.JEV): Measurement(
        93.3, "KUQ + CoCoNot", 5161, "81.7% recall on contested questions"
    ),
    (DecisionKind.SEMANTIC, Tier.LLM): Measurement(
        75.4, "KUQ + CoCoNot", 5161, "worse than Jev and 200x the cost"
    ),
    (DecisionKind.PERFORMATIVE, Tier.DETERMINISTIC): Measurement(
        0.0, "refund corpus", 96, "presupposition missed 96/96"
    ),
    (DecisionKind.PERFORMATIVE, Tier.JEV): Measurement(
        7.0, "HR screening", 180, "scores 0.07 on an answer that settles a hire"
    ),
    (DecisionKind.PERFORMATIVE, Tier.LLM): Measurement(
        85.0, "HR screening", 180, "the only tier with usable signal here"
    ),
}


@dataclass(frozen=True, slots=True)
class Rule:
    combine: Combine
    #: Ranked. Only tiers an operator enabled are used, in this order.
    prefer: tuple[Tier, ...]
    #: Never permitted to decide this kind, with the reason, whatever is on.
    forbid: tuple[tuple[Tier, str], ...] = ()
    quorum: int = 2
    #: True when no enabled tier can answer well enough to be trusted alone.
    escalate_if_unresolved: bool = False


ROUTING: dict[DecisionKind, Rule] = {
    # Code is exact. A model opinion here can only subtract.
    DecisionKind.STRUCTURAL_PARSED: Rule(
        combine=Combine.CODE_WINS,
        prefer=(Tier.DETERMINISTIC,),
        forbid=(
            (Tier.JEV, "98.3% vs code's 100.0% on 5,528 SQL statements; 819 false blocks at 0.5"),
            (Tier.LLM, "no measurement; a parse tree is not a judgment"),
            (Tier.LOCAL_LLM, "no measurement; a parse tree is not a judgment"),
        ),
    ),
    DecisionKind.STRUCTURAL_GRANT: Rule(
        combine=Combine.CODE_WINS,
        prefer=(Tier.DETERMINISTIC,),
        forbid=(
            (Tier.JEV, "18.5% recall on 493 PrivacyLens vignettes; entitlement is a lookup"),
            (Tier.LLM, "unmeasured; the grant is in the session, not the text"),
            (Tier.LOCAL_LLM, "unmeasured; the grant is in the session, not the text"),
        ),
    ),
    # Measured: neither alone beats the pair.
    DecisionKind.PATTERN_OPEN: Rule(
        combine=Combine.UNION,
        prefer=(Tier.DETERMINISTIC, Tier.LOCAL_MODEL, Tier.JEV, Tier.LOCAL_LLM, Tier.LLM),
    ),
    # Union, not best-available. On KUQ + CoCoNot the union measured 93.5%
    # against 93.3% for Jev alone, with recall 90.9% against 88.8% — and it is
    # strictly safer for an abstention boundary, because a union can only *add*
    # an abstention and never remove one the deterministic layer wanted. The
    # deterministic layer is low-recall here (8.4% on contested questions) but
    # high-precision (95.1%), so its verdicts are worth keeping.
    DecisionKind.SEMANTIC: Rule(
        combine=Combine.UNION,
        prefer=(Tier.DETERMINISTIC, Tier.JEV, Tier.LOCAL_LLM, Tier.LLM, Tier.LOCAL_MODEL),
    ),
    # Everything is weak. Two must agree, or a person looks.
    DecisionKind.PERFORMATIVE: Rule(
        combine=Combine.VOTE,
        prefer=(Tier.LLM, Tier.LOCAL_LLM, Tier.JEV),
        forbid=(
            (
                Tier.DETERMINISTIC,
                "0/96 on presupposition in the refund corpus; the breach is in what "
                "the utterance does, not what it says",
            ),
        ),
        quorum=1,
        escalate_if_unresolved=True,
    ),
}


@dataclass(frozen=True, slots=True)
class Plan:
    """Who decides, who was excluded and why, and what may leave the box."""

    kind: DecisionKind
    combine: Combine
    deciders: tuple[Tier, ...] = ()
    excluded: tuple[tuple[Tier, str], ...] = ()
    quorum: int = 1
    escalate: bool = False
    egress_tiers: tuple[Tier, ...] = ()

    @property
    def decidable(self) -> bool:
        return bool(self.deciders) or self.escalate

    def why(self, tier: Tier) -> str:
        for t, reason in self.excluded:
            if t == tier:
                return reason
        return "enabled and permitted" if tier in self.deciders else "not enabled"


@dataclass
class CapabilityRouter:
    """Turns "what the operator enabled" into "who may answer this question".

    `enabled` is the operator's choice. DETERMINISTIC is always present: it
    needs no key, no weights and no network, and removing it would leave some
    kinds with no permitted decider at all.
    """

    enabled: frozenset[Tier] = field(default_factory=frozenset)
    allow_egress: bool = False

    def __post_init__(self) -> None:
        self.enabled = frozenset(self.enabled) | {Tier.DETERMINISTIC}

    @classmethod
    def from_settings(cls, settings: object | None = None) -> CapabilityRouter:
        if settings is None:
            from ..config import get_settings

            settings = get_settings()
        names = getattr(settings, "judgment_tiers", None) or []
        tiers = set()
        for n in names:
            try:
                tiers.add(Tier(str(n).strip().lower()))
            except ValueError:
                continue
        return cls(frozenset(tiers), bool(getattr(settings, "allow_egress", False)))

    def plan(self, kind: DecisionKind, *, payload_may_leave: bool = True) -> Plan:
        rule = ROUTING[kind]
        forbidden = dict(rule.forbid)
        excluded: list[tuple[Tier, str]] = []
        deciders: list[Tier] = []

        for tier in rule.prefer:
            if tier in forbidden:
                excluded.append((tier, forbidden[tier]))
                continue
            if tier not in self.enabled:
                excluded.append((tier, "not enabled by the operator"))
                continue
            if tier in EGRESS_TIERS:
                if not self.allow_egress:
                    excluded.append((tier, "allow_egress is off"))
                    continue
                if not payload_may_leave:
                    excluded.append((tier, "payload is classified as must-not-leave"))
                    continue
            deciders.append(tier)

        # a forbidden tier is excluded even if the operator never enabled it,
        # so the reason recorded is the measured one rather than "not enabled"
        for tier, reason in rule.forbid:
            if tier not in rule.prefer and all(t != tier for t, _ in excluded):
                excluded.append((tier, reason))

        combine = rule.combine
        escalate = False
        if not deciders:
            combine, escalate = Combine.ESCALATE, True
        elif rule.combine is Combine.VOTE and len(deciders) < rule.quorum:
            if rule.escalate_if_unresolved:
                combine, escalate = Combine.ESCALATE, True
        elif rule.combine is Combine.BEST_AVAILABLE:
            deciders = deciders[:1]

        return Plan(
            kind=kind,
            combine=combine,
            deciders=tuple(deciders),
            excluded=tuple(excluded),
            quorum=rule.quorum,
            escalate=escalate,
            egress_tiers=tuple(t for t in deciders if t in EGRESS_TIERS),
        )

    def decide(
        self, kind: DecisionKind, votes: dict[Tier, bool], plan: Plan | None = None
    ) -> bool | None:
        """Combine the votes a plan's deciders produced. None means escalate.

        Votes from tiers the plan excluded are discarded rather than trusted,
        so a caller that over-collects cannot reintroduce an excluded opinion.
        """
        plan = plan or self.plan(kind)
        if plan.combine is Combine.ESCALATE:
            return None
        usable = {t: v for t, v in votes.items() if t in plan.deciders}
        if not usable:
            return None
        if plan.combine is Combine.CODE_WINS:
            return usable.get(Tier.DETERMINISTIC, next(iter(usable.values())))
        if plan.combine is Combine.UNION:
            return any(usable.values())
        if plan.combine is Combine.VOTE:
            return sum(1 for v in usable.values() if v) >= plan.quorum
        return next(iter(usable.values()))


@dataclass(frozen=True, slots=True)
class Evidence:
    """A read-only view for operators: what a tier is worth, per kind."""

    @staticmethod
    def for_kind(kind: DecisionKind) -> dict[Tier, Measurement]:
        return {t: m for (k, t), m in EVIDENCE.items() if k == kind}

    @staticmethod
    def best(kind: DecisionKind) -> tuple[Tier, Measurement] | None:
        found = Evidence.for_kind(kind)
        if not found:
            return None
        return max(found.items(), key=lambda kv: kv[1].accuracy)
