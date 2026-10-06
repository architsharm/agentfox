"""Whether the agent is allowed to stop.

Every other guard on the Enforcer asks whether an action is safe. This one asks
a question nothing in the product asked before: the agent says it is finished —
is it?

The market survey calls this `c4`, "did the agent finish the task it was
given", and marks it unsolved-but-buildable with only evaluation vendors in it,
all of whom score it after the fact on sampled runs. We were in exactly that
position: `silent_failure` is an offline scorer, so an agent reporting "your
refund is processed" after the payment API returned an error was caught in next
week's report rather than stopped at the time.

The division of labour is the part worth pinning. The CALLER reports what it
can observe at the moment of the claim, because only the caller can see it.
POLICY decides which of those facts must hold, because that is a governance
decision that differs per agent and per environment.
"""

from __future__ import annotations

from agentfox.core.vocab import SURFACES
from agentfox.platform.policy.engine import NativePolicyEngine
from agentfox.platform.policy.model import Condition, PolicyDocument, PolicyInput, Rule
from agentfox.runtime.enforcement import Enforcer


def _engine_verdict(requires: list[str], reported: dict[str, object], surface: str = "completion"):
    """One rule, one input, straight through the matcher."""
    doc = PolicyDocument(
        key="test-completion",
        mode="enforce",
        rules=[
            Rule(
                id="completion.gate",
                when=Condition(surface=["completion"], completion_requires=requires),
                effect="block",
            )
        ],
    )
    return NativePolicyEngine().evaluate(
        doc, PolicyInput(agent_slug="a", surface=surface, completion=reported)
    )


def test_the_surface_exists():
    assert "completion" in SURFACES


# ---------------------------------------------------------------------------
# The matcher
# ---------------------------------------------------------------------------


def test_an_unmet_condition_fires_the_rule():
    assert _engine_verdict(["work_verified"], {"work_verified": False}).verdict == "block"


def test_a_condition_nobody_reported_counts_as_unmet():
    """The default that makes this a gate rather than a formality.

    If an unreported condition were assumed satisfied, a caller who forgot to
    pass it would sail through — and forgetting to check is precisely the
    failure being guarded against.
    """
    assert _engine_verdict(["ci_green"], {}).verdict == "block"
    assert _engine_verdict(["ci_green"], {"committed": True}).verdict == "block"


def test_a_met_condition_does_not_fire():
    assert _engine_verdict(["work_verified"], {"work_verified": True}).verdict != "block"


def test_every_named_condition_has_to_hold():
    assert _engine_verdict(["a", "b"], {"a": True, "b": False}).verdict == "block"
    assert _engine_verdict(["a", "b"], {"a": True, "b": True}).verdict != "block"


def test_the_rule_does_not_reach_other_surfaces():
    """A completion rule must not start firing on ordinary traffic."""
    assert _engine_verdict(["work_verified"], {}, surface="input").verdict != "block"


# ---------------------------------------------------------------------------
# Through the Enforcer, against the shipped pack
# ---------------------------------------------------------------------------


def test_an_unverified_completion_claim_is_escalated(seeded):
    """The shipped rule, end to end — not the matcher in isolation."""
    result = Enforcer(seeded).guard_completion(
        agent_slug="support-triage",
        claim="Your refund has been processed.",
    )
    assert "completion.unverified_claim" in {r["rule_id"] for r in result.rules_fired}
    assert result.verdict == "escalate"


def test_a_verified_completion_claim_passes(seeded):
    result = Enforcer(seeded).guard_completion(
        agent_slug="support-triage",
        claim="Your refund has been processed.",
        completion={"work_verified": True},
    )
    assert "completion.unverified_claim" not in {r["rule_id"] for r in result.rules_fired}
    assert result.verdict not in ("block", "escalate")


def test_the_claim_still_goes_through_the_detector_pipeline(seeded):
    """The gate is additive. A completion claim is also output content, and the
    rules that already apply to output content still apply to it."""
    result = Enforcer(seeded).guard_completion(
        agent_slug="support-triage",
        claim="Done. The customer SSN is 123-45-6789.",
        completion={"work_verified": True},
    )
    assert any(e.startswith("PII") for e in result.entities), result.entities


def test_the_shipped_pack_carries_both_completion_rules():
    from agentfox.core.config import get_settings
    from agentfox.platform.policy.store import load_from_dir

    packs = load_from_dir(get_settings().policies_dir)
    pack = next(p for p in packs if p.key == "tool-containment")
    by_id = {r.id: r for r in pack.rules}

    assert by_id["completion.unverified_claim"].effect == "escalate"
    # Escalate rather than block on purpose: a false completion claim needs a
    # human to look, and blocking the agent's final message strands the run
    # without telling anyone.
    assert by_id["completion.irreversible_unconfirmed"].effect == "block"
    assert by_id["completion.irreversible_unconfirmed"].severity == "critical"
    for name in ("completion.unverified_claim", "completion.irreversible_unconfirmed"):
        rule = by_id[name]
        assert rule.when.surface == ["completion"], "must not fire on ordinary traffic"
