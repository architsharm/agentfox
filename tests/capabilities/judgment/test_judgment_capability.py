"""Enabling a capability must widen coverage and never degrade a control.

That is the whole contract of a tiered product. An operator who switches
everything on is making the most optimistic possible choice, and the system
has to be safe under it — which means the measured failures have to be
enforced by the router, not left to whoever writes the call site.
"""

from __future__ import annotations

import itertools

import pytest

from agentfox.capabilities.judgment import (
    EVIDENCE,
    ROUTING,
    CapabilityRouter,
    Combine,
    DecisionKind,
    Evidence,
    Tier,
)

ALL_TIERS = frozenset(Tier)
STRUCTURAL = (DecisionKind.STRUCTURAL_PARSED, DecisionKind.STRUCTURAL_GRANT)


def _every_subset():
    optional = [t for t in Tier if t is not Tier.DETERMINISTIC]
    for r in range(len(optional) + 1):
        for combo in itertools.combinations(optional, r):
            yield frozenset(combo)


@pytest.mark.parametrize("kind", STRUCTURAL)
def test_no_capability_can_take_a_structural_decision_from_code(kind) -> None:
    """Code measured 100% here. Nothing enabled may change that."""
    for subset in _every_subset():
        plan = CapabilityRouter(subset, allow_egress=True).plan(kind)
        assert plan.deciders == (Tier.DETERMINISTIC,), f"{kind} changed with {sorted(subset)}"
        assert plan.combine is Combine.CODE_WINS


def test_an_excluded_tier_is_refused_with_the_measurement_that_refused_it() -> None:
    plan = CapabilityRouter(ALL_TIERS, allow_egress=True).plan(DecisionKind.STRUCTURAL_PARSED)
    reason = plan.why(Tier.JEV)
    assert "98.3" in reason and "100.0" in reason


def test_entitlement_never_goes_to_a_model() -> None:
    plan = CapabilityRouter(ALL_TIERS, allow_egress=True).plan(DecisionKind.STRUCTURAL_GRANT)
    assert Tier.JEV not in plan.deciders
    assert "18.5" in plan.why(Tier.JEV)


def test_enabling_more_never_shrinks_the_decider_set() -> None:
    """Monotonicity: adding a capability only ever adds coverage."""
    for kind in DecisionKind:
        for subset in _every_subset():
            small = CapabilityRouter(subset, allow_egress=True).plan(kind)
            for extra in Tier:
                bigger = CapabilityRouter(subset | {extra}, allow_egress=True).plan(kind)
                if small.combine is Combine.BEST_AVAILABLE or bigger.combine is (
                    Combine.BEST_AVAILABLE
                ):
                    continue  # best-available deliberately keeps exactly one
                assert set(small.deciders) <= set(bigger.deciders), (
                    f"{kind}: adding {extra} removed a decider"
                )


def test_semantic_cascades_so_an_abstention_can_only_be_added() -> None:
    """Cheapest first, and an abstention can still only ever be added.

    The deterministic layer is low-recall on contested questions (8.4%) but
    high-precision (95.1%), so it leads and costs nothing. A cascade stops at
    the first decisive answer, so the hosted tiers see only what the cheap
    ones left unsettled — and no tier can drop a refusal another asked for.
    """
    code_only = CapabilityRouter(frozenset(), allow_egress=True).plan(DecisionKind.SEMANTIC)
    assert code_only.deciders == (Tier.DETERMINISTIC,)
    with_jev = CapabilityRouter({Tier.JEV}, allow_egress=True).plan(DecisionKind.SEMANTIC)
    assert with_jev.combine is Combine.CASCADE
    assert with_jev.deciders == (Tier.DETERMINISTIC, Tier.JEV)  # order is the cascade

    r = CapabilityRouter({Tier.JEV}, allow_egress=True)
    # either layer wanting an abstention is enough
    assert r.decide(DecisionKind.SEMANTIC, {Tier.DETERMINISTIC: True, Tier.JEV: False}) is True
    assert r.decide(DecisionKind.SEMANTIC, {Tier.DETERMINISTIC: False, Tier.JEV: True}) is True


def test_pattern_open_cascades_cheapest_first() -> None:
    """Union bought +0.1 F1 on injection for an LLM call on every request."""
    plan = CapabilityRouter({Tier.JEV, Tier.LLM}, allow_egress=True).plan(DecisionKind.PATTERN_OPEN)
    assert plan.combine is Combine.CASCADE
    # deterministic and Jev are asked before the hosted LLM, never after
    assert plan.deciders.index(Tier.JEV) < plan.deciders.index(Tier.LLM)


# --- the hard egress gates ------------------------------------------------
def test_hosted_tiers_are_dropped_when_egress_is_off() -> None:
    plan = CapabilityRouter(ALL_TIERS, allow_egress=False).plan(DecisionKind.PATTERN_OPEN)
    assert Tier.JEV not in plan.deciders
    assert Tier.LLM not in plan.deciders
    assert "allow_egress" in plan.why(Tier.JEV)
    # the local tiers still work, so the capability degrades rather than fails
    assert Tier.LOCAL_MODEL in plan.deciders


def test_a_must_not_leave_payload_keeps_hosted_tiers_out_even_with_egress_on() -> None:
    """The per-payload gate. Global egress on does not mean this text may go."""
    plan = CapabilityRouter(ALL_TIERS, allow_egress=True).plan(
        DecisionKind.PATTERN_OPEN, payload_may_leave=False
    )
    assert Tier.JEV not in plan.deciders
    assert "must-not-leave" in plan.why(Tier.JEV)
    assert Tier.LOCAL_LLM in plan.deciders  # self-hosted is still fine


def test_local_llm_is_not_treated_as_egress() -> None:
    plan = CapabilityRouter({Tier.LOCAL_LLM}, allow_egress=False).plan(DecisionKind.SEMANTIC)
    assert Tier.LOCAL_LLM in plan.deciders


# --- combination ----------------------------------------------------------
def test_votes_from_excluded_tiers_are_discarded() -> None:
    """A caller that over-collects must not reintroduce a forbidden opinion."""
    r = CapabilityRouter(ALL_TIERS, allow_egress=True)
    kind = DecisionKind.STRUCTURAL_PARSED
    assert r.decide(kind, {Tier.DETERMINISTIC: False, Tier.JEV: True}) is False


def test_any_consulted_decider_flagging_is_a_flag() -> None:
    r = CapabilityRouter({Tier.JEV}, allow_egress=True)
    kind = DecisionKind.PATTERN_OPEN
    assert r.decide(kind, {Tier.DETERMINISTIC: False, Tier.JEV: True}) is True
    assert r.decide(kind, {Tier.DETERMINISTIC: False, Tier.JEV: False}) is False


def test_performative_keeps_the_narrow_but_perfect_deterministic_signal() -> None:
    """Code-only still answers here, at 26.7% recall and 100% precision.

    An earlier table forbade the deterministic tier on the strength of one
    template. Widening commitments.py showed that was over-reach: narrow and
    perfectly precise is worth keeping, and the judgment tiers union on top.
    """
    plan = CapabilityRouter(frozenset()).plan(DecisionKind.PERFORMATIVE)
    assert plan.deciders == (Tier.DETERMINISTIC,)
    assert plan.combine is Combine.CASCADE

    both = CapabilityRouter({Tier.LLM}, allow_egress=True).plan(DecisionKind.PERFORMATIVE)
    assert set(both.deciders) == {Tier.DETERMINISTIC, Tier.LLM}


def test_performative_is_answerable_once_a_capable_tier_is_on() -> None:
    plan = CapabilityRouter({Tier.LLM}, allow_egress=True).plan(DecisionKind.PERFORMATIVE)
    assert not plan.escalate
    assert Tier.LLM in plan.deciders


# --- the table itself -----------------------------------------------------
def test_every_routed_kind_has_a_rule() -> None:
    assert set(ROUTING) == set(DecisionKind)


def test_every_forbidden_tier_cites_a_measurement_or_a_reason() -> None:
    for kind, rule in ROUTING.items():
        for tier, reason in rule.forbid:
            assert len(reason) > 20, f"{kind}/{tier} forbidden without a stated reason"


def test_forbidden_tiers_measured_worse_than_a_permitted_one() -> None:
    """The table must not forbid a tier that actually measured better."""
    for kind, rule in ROUTING.items():
        for tier, _ in rule.forbid:
            theirs = EVIDENCE.get((kind, tier))
            best = Evidence.best(kind)
            if theirs is None or best is None:
                continue
            assert theirs.accuracy <= best[1].accuracy, (
                f"{kind}: {tier} is forbidden but measured best"
            )


def test_deterministic_is_always_available() -> None:
    assert Tier.DETERMINISTIC in CapabilityRouter(frozenset()).enabled


def test_from_settings_reads_the_opt_in_list(monkeypatch) -> None:
    from agentfox.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "judgment_tiers", ["jev", "local_model", "nonsense"])
    monkeypatch.setattr(settings, "allow_egress", True)
    r = CapabilityRouter.from_settings()
    assert Tier.JEV in r.enabled and Tier.LOCAL_MODEL in r.enabled
    assert Tier.LLM not in r.enabled  # unlisted stays off; junk is ignored


def test_a_cheap_negative_cannot_end_the_performative_cascade() -> None:
    """A band catches uncertainty, not error — so make it asymmetric.

    Jev leads here because it is cheap, and asking the LLM first measured 80
    calls per 100 for no gain at all. But Jev's dangerous errors on this kind
    are confident *denials* — 0.07 on an answer that settles a hire — and a
    symmetric band would let one of those stop the cascade before the tier
    that can see it is ever asked. `lo` therefore sits below every possible
    score: only a confident yes is decisive.
    """
    from agentfox.capabilities.judgment.capability import ROUTING

    plan = CapabilityRouter({Tier.JEV, Tier.LLM}, allow_egress=True).plan(DecisionKind.PERFORMATIVE)
    assert plan.deciders.index(Tier.JEV) < plan.deciders.index(Tier.LLM)

    lo, hi = ROUTING[DecisionKind.PERFORMATIVE].band
    assert lo < 0.0, "a negative from the cheap tier must never be decisive"
    assert 0.0 < hi < 1.0
