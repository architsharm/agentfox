"""The rules that keep a self-improving governance product from rewriting its own guardrails."""

from __future__ import annotations

import itertools

import pytest

from agentfox.improvement import contract as c


def test_loosening_is_never_automatic_at_any_level():
    for level, kind in itertools.product(c.AUTONOMY_LEVELS, ["threshold", "grant", "suppression"]):
        assert not c.may_apply_automatically(direction=c.LOOSENS, kind=kind, autonomy_level=level)


@pytest.mark.parametrize("kind", sorted(c.NEVER_AUTOMATIC_KINDS))
def test_never_automatic_kinds_stay_manual_even_when_labelled_tightening(kind):
    for level in c.AUTONOMY_LEVELS:
        for direction in (c.TIGHTENS, c.NEUTRAL):
            assert not c.may_apply_automatically(
                direction=direction, kind=kind, autonomy_level=level
            )


def test_only_l3_and_l4_apply_without_a_person():
    allowed = {
        level
        for level in c.AUTONOMY_LEVELS
        if c.may_apply_automatically(
            direction=c.TIGHTENS, kind="grant.narrow", autonomy_level=level
        )
    }
    assert allowed == {"L3", "L4"}


def test_unknown_direction_or_level_fails_closed():
    assert not c.may_apply_automatically(direction="sideways", kind="x", autonomy_level="L4")
    assert not c.may_apply_automatically(direction=c.TIGHTENS, kind="x", autonomy_level="L9")


def test_org_level_loosening_needs_two_people_and_nothing_else_does():
    assert c.requires_second_approver(direction=c.LOOSENS, scope_level="org")
    assert not c.requires_second_approver(direction=c.LOOSENS, scope_level="team")
    assert not c.requires_second_approver(direction=c.TIGHTENS, scope_level="org")


def test_lifecycle_has_no_shortcuts():
    assert c.transition_allowed(c.PROPOSED, c.PROVEN)
    assert not c.transition_allowed(c.PROPOSED, c.APPLIED), "cannot apply unproven"
    assert not c.transition_allowed(c.PROVEN, c.APPLIED), "cannot apply unapproved"
    for terminal in c.TERMINAL:
        assert not c.TRANSITIONS[terminal], f"{terminal} must be terminal"
    assert set(c.TRANSITIONS) == set(c.STATUSES)


def test_demotion_never_drops_below_recommend():
    assert c.lower_autonomy("L4") == "L3"
    assert c.lower_autonomy("L2") == "L1"
    assert c.lower_autonomy("L1") == "L1"
    assert c.lower_autonomy("L0") == "L1"
    assert c.lower_autonomy("bogus") == "L1"
