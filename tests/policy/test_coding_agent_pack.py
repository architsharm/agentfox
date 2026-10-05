"""The pack named after a job rather than a standard.

Every other pack here is named after what it implements — a detector floor, a
capability model, a regulation. The person installing our hooks is not looking
for any of those; they run a coding agent on a laptop that can reach
production, and until now the answer to "which pack do I turn on" was three
packs and a reading list.

What the tests hold onto is the thing that makes a profile worth shipping
rather than documenting: it must be a *composition*, tuned, and it must not
quietly restate rules that already fire. A profile that re-declared
`capability.denied` would double every decision record and teach the reader
that packs are alternatives when they are layers.
"""

from __future__ import annotations

import pytest

from agentfox.policy.store import load_available

PACK = "coding-agent"


@pytest.fixture(scope="module")
def packs():
    return {doc.key: doc for doc in load_available()}


@pytest.fixture(scope="module")
def pack(packs):
    assert PACK in packs, "the coding-agent profile is not being discovered"
    return packs[PACK]


def test_it_ships_in_observe_like_everything_else(pack):
    """A guardrail that starts blocking the moment it is installed produces a
    false block, gets switched off, and never gets switched back on."""
    assert pack.mode == "observe"


def test_it_does_not_restate_a_rule_another_pack_already_ships(packs, pack):
    """Layers, not alternatives. A duplicated id would fire twice and write
    two decision records for one event."""
    others = {r.id for key, doc in packs.items() if key != PACK for r in doc.rules}
    assert not ({r.id for r in pack.rules} & others)


def test_every_rule_is_namespaced_to_the_profile(pack):
    """`code.` rather than `injection.` — so a reader looking at a decision
    record can tell which pack decided it without opening any of them."""
    assert all(rule.id.startswith("code.") for rule in pack.rules)


def test_it_is_tuned_rather_than_merely_added(packs, pack):
    """The claim this pack makes is not 'more rules', it is 'the same
    detectors, at the thresholds this job needs'. If any threshold here were
    the same as baseline's for the same surface, that rule would be dead
    weight — baseline already fires first.
    """
    baseline = {r.id: r for r in packs["baseline"].rules}
    fetched = next(r for r in pack.rules if r.id == "code.injection_in_fetched_content")
    adopted = next(r for r in pack.rules if r.id == "code.injection_adopted")

    assert (
        fetched.when.detection.min_score < baseline["injection.indirect"].when.detection.min_score
    )
    assert (
        adopted.when.detection.min_score
        < baseline["injection.adopted_in_reasoning"].when.detection.min_score
    )


def test_the_surface_a_pretooluse_hook_cannot_see_is_the_one_it_covers(pack):
    """The reason this pack and the PostToolUse binding landed together: a
    coding agent's injection arrives in what a tool returned, and the call
    that fetched it looked entirely ordinary."""
    fetched = next(r for r in pack.rules if r.id == "code.injection_in_fetched_content")
    assert "tool_result" in fetched.when.surface


def test_a_credential_arriving_is_treated_as_worse_than_the_generic_case(packs, pack):
    """Baseline catches a secret anywhere at 0.9. The failure here is not the
    agent leaking a key, it is the key entering the context window at all —
    after which no downstream control can unsee it."""
    baseline = {r.id: r for r in packs["baseline"].rules}
    incoming = next(r for r in pack.rules if r.id == "code.secret_in_fetched_content")
    assert incoming.when.detection.min_score < baseline["secrets.block"].when.detection.min_score
    assert incoming.effect == "block"


def test_the_operator_s_own_turn_escalates_rather_than_blocks(pack):
    """The one surface where a false positive costs the person their own
    sentence. A pasted stack trace is the common case, not an attack."""
    turn = next(r for r in pack.rules if r.id == "code.injection_in_operator_turn")
    assert turn.when.surface == ["input"]
    assert turn.effect == "escalate"


def test_the_whole_shipped_set_still_lints_clean():
    """Including the unreachable check — a rule whose conditions can never all
    hold is a rule somebody believes is protecting them."""
    from agentfox.policy.hierarchy import PolicyLayer, lint_policy

    layers = [PolicyLayer(document=doc) for doc in load_available()]
    ours = {rule.id for doc in load_available() if doc.key == PACK for rule in doc.rules}
    findings = [f for f in lint_policy(layers) if f.rule_id in ours]
    assert not findings, [f.to_json() for f in findings]
