"""A rule that can never fire still reports itself as enforced.

A competitor throws at load when a policy names an implementation that does not
exist, and the reasoning in their source is the one this whole project rests
on: the guard then allows, exits zero, and still lists itself among the
policies that ran — a machine reporting that a check happened when it never
did.

`lint_policy` caught duplicate ids, shadowing and illegal loosening. Nothing
asked the simpler question: can this rule's own conditions ever be true?

Writing the check found two answers of "no" in our own shipped code, which is
the argument for having it. One was a typo-class drift in `_FALLBACK_FOR_TIER`
— see `test_the_prohibited_tier_reaches_the_eu_pack` below.
"""

from __future__ import annotations

from agentfox.core.config import get_settings
from agentfox.core.vocab import SURFACES
from agentfox.platform.policy.hierarchy import PolicyLayer, lint_policy
from agentfox.platform.policy.model import Condition, PolicyDocument, Rule
from agentfox.platform.policy.store import load_from_dir
from agentfox.prove.compliance.risk import EU_CLASSES
from agentfox.runtime.enforcement import _fallback_policies


def unreachable(*rules: Rule) -> list[str]:
    doc = PolicyDocument(key="lint-fixture", rules=list(rules))
    layer = PolicyLayer(level="org", scope_id="org", document=doc)
    return [f.rule_id for f in lint_policy([layer]) if f.code == "unreachable"]


# ---------------------------------------------------------------------------
# What it catches
# ---------------------------------------------------------------------------


def test_a_surface_that_does_not_exist():
    """The typo case, and the most likely one: surfaces are free text in YAML."""
    assert unreachable(Rule(id="typo", when=Condition(surface=["compleiton"]))) == ["typo"]


def test_a_value_outside_a_known_enum():
    assert unreachable(Rule(id="op", when=Condition(action_operation=["delete"]))) == ["op"]
    assert unreachable(Rule(id="tier", when=Condition(risk_tier=["critical"]))) == ["tier"]
    assert unreachable(Rule(id="impact", when=Condition(tool_impact=["dangerous"]))) == ["impact"]


def test_completion_conditions_without_the_completion_surface():
    """The mistake the new surface invites: naming the conditions and forgetting
    to scope the rule to the only surface that supplies them."""
    rule = Rule(id="gate", when=Condition(completion_requires=["work_verified"]))
    assert unreachable(rule) == ["gate"]


def test_the_message_says_what_is_legal():
    doc = PolicyDocument(key="k", rules=[Rule(id="r", when=Condition(surface=["nope"]))])
    finding = next(
        f
        for f in lint_policy([PolicyLayer(level="org", scope_id="o", document=doc)])
        if f.code == "unreachable"
    )
    assert "can never fire" in finding.message
    assert "input" in finding.message, "the message has to name the values that work"
    assert finding.severity == "high"


# ---------------------------------------------------------------------------
# What it must not catch
# ---------------------------------------------------------------------------


def test_a_rule_with_one_good_value_among_bad_ones_is_not_dead():
    """It can still fire. Flagging it would be a false positive, and a linter
    that cries wolf on working rules gets switched off."""
    assert unreachable(Rule(id="mixed", when=Condition(surface=["input", "nonsense"]))) == []


def test_action_risk_is_deliberately_not_checked():
    """Risk codes come from several modules and rules may glob over them, so a
    whitelist here would be a second place to keep in step — the exact problem
    the check exists to solve."""
    assert unreachable(Rule(id="risk", when=Condition(action_risk="totally-made-up"))) == []
    assert unreachable(Rule(id="glob", when=Condition(action_risk="sql.*"))) == []


def test_an_empty_condition_is_not_dead():
    """It matches everything. `lint_policy` already flags that as
    `unconditional`, which is a different complaint."""
    assert unreachable(Rule(id="all", when=Condition())) == []


def test_every_shipped_pack_is_clean():
    """The regression this file is really for."""
    for pack in load_from_dir(get_settings().policies_dir):
        layer = PolicyLayer(level="org", scope_id="org", document=pack)
        dead = [f.rule_id for f in lint_policy([layer]) if f.code == "unreachable"]
        assert dead == [], f"{pack.key} ships rules that can never fire: {dead}"


# ---------------------------------------------------------------------------
# The bug it found
# ---------------------------------------------------------------------------


def test_the_prohibited_tier_reaches_the_eu_pack():
    """`_FALLBACK_FOR_TIER` was keyed on "unacceptable", which nothing emits.

    The classifier's vocabulary is `EU_CLASSES` — prohibited, high, limited,
    minimal — so the branch meant to cover the most serious tier was dead, and
    an agent classified as a *prohibited practice* fell through to
    `_FALLBACK_DEFAULT`: the weakest of the three packs, on the deployment that
    most needed the strongest.
    """
    assert "prohibited" in EU_CLASSES and "unacceptable" not in EU_CLASSES
    assert [d.key for d in _fallback_policies("prohibited")] == [
        "baseline",
        "eu-ai-act-high-risk",
    ]


def test_the_lint_enums_come_from_the_source_of_truth():
    """If either list were retyped here it would drift, which is the failure
    this module is about."""
    from agentfox.platform.policy.hierarchy import _ENUMERABLE_CONDITIONS

    assert _ENUMERABLE_CONDITIONS["risk_tier"] is EU_CLASSES
    assert _ENUMERABLE_CONDITIONS["surface"] is SURFACES
