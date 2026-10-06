"""#41 — the policy hierarchy is what the runtime enforces, not only what it prints.

`policy effective` and `policy lint` resolved org -> team -> agent -> user with
extend/restrict/override, while the enforcer evaluated every bound pack flatly: a
team-scoped `restrict` fired for every agent, and a granted `override` could not
loosen anything. These tests drive the real `Enforcer.evaluate` so the two cannot
drift apart again.
"""

from __future__ import annotations

from agentfox.policy import PolicyDocument, effective_for, policies_in_force, save_policy
from agentfox.registry.service import register_agent
from agentfox.runtime.enforcement import Enforcer

ORG_OBSERVE = """
key: org-pack
mode: observe
rules:
  - id: input.note
    when: {surface: [input]}
    effect: allow
"""

TEAM_RESTRICT = """
key: finance-restrict
mode: enforce
rules:
  - id: finance.input.block
    when: {surface: [input]}
    effect: block
    reason: finance agents may not take free-text input
"""

ORG_OVERRIDABLE = """
key: org-overridable
mode: enforce
rules:
  - id: input.hold
    when: {surface: [input]}
    effect: block
    overridable: {overridable}
"""

AGENT_OVERRIDE = """
key: agent-override
mode: enforce
rules:
  - id: input.hold
    when: {surface: [input]}
    effect: allow
"""


def _agents(session):
    finance = register_agent(session, "ledger-bot", owner_team="finance")
    support = register_agent(session, "help-bot", owner_team="support")
    return finance, support


def _decide(session, agent):
    return Enforcer(session).evaluate(
        agent=agent, identity=None, content="hello", surface="input", persist=False
    )


def test_a_team_restrict_applies_only_to_that_teams_agents(session):
    finance, support = _agents(session)
    save_policy(session, PolicyDocument.from_yaml(ORG_OBSERVE), bind_mode="observe")
    save_policy(
        session,
        PolicyDocument.from_yaml(TEAM_RESTRICT),
        bind_mode="enforce",
        level="team",
        scope_id="finance",
        compose="restrict",
    )

    assert _decide(session, finance).verdict == "block"
    outside = _decide(session, support)
    assert outside.verdict == "allow"
    assert "finance.input.block" not in {r["rule_id"] for r in outside.rules_fired}


def test_a_granted_override_loosens_at_runtime(session):
    finance, support = _agents(session)
    save_policy(
        session,
        PolicyDocument.from_yaml(ORG_OVERRIDABLE.replace("{overridable}", "true")),
        bind_mode="enforce",
    )
    save_policy(
        session,
        PolicyDocument.from_yaml(AGENT_OVERRIDE),
        bind_mode="enforce",
        level="agent",
        scope_id="ledger-bot",
        compose="override",
    )

    assert _decide(session, finance).verdict == "allow"
    assert _decide(session, support).verdict == "block"


def test_an_ungranted_loosening_is_rejected_at_runtime(session):
    finance, _support = _agents(session)
    save_policy(
        session,
        PolicyDocument.from_yaml(ORG_OVERRIDABLE.replace("{overridable}", "false")),
        bind_mode="enforce",
    )
    save_policy(
        session,
        PolicyDocument.from_yaml(AGENT_OVERRIDE),
        bind_mode="enforce",
        level="agent",
        scope_id="ledger-bot",
        compose="override",
    )

    result = _decide(session, finance)
    assert result.verdict == "block"
    # And `policy effective` says the same thing the enforcer did.
    effective = effective_for(session, agent_slug="ledger-bot")
    assert [r["rule_id"] for r in effective.rejected] == ["input.hold"]


def test_tightening_in_an_observe_layer_does_not_demote_the_enforced_org_rule(session):
    """A team trialling a stricter rule in observe must not switch the org's off."""
    finance, _support = _agents(session)
    org = ORG_OVERRIDABLE.replace("{overridable}", "false").replace(
        "effect: block", "effect: escalate"
    )
    save_policy(session, PolicyDocument.from_yaml(org), bind_mode="enforce")
    team = AGENT_OVERRIDE.replace("effect: allow", "effect: block").replace("enforce", "observe")
    save_policy(
        session,
        PolicyDocument.from_yaml(team),
        bind_mode="observe",
        level="team",
        scope_id="finance",
        compose="restrict",
    )

    result = _decide(session, finance)
    assert result.verdict == "escalate"  # the org's enforced rule still applies
    assert result.effective_verdict == "block"  # the team's stricter rule is recorded


def test_effective_and_runtime_resolve_the_agents_team_the_same_way(session):
    _agents(session)
    save_policy(
        session,
        PolicyDocument.from_yaml(TEAM_RESTRICT),
        bind_mode="enforce",
        level="team",
        scope_id="finance",
        compose="restrict",
    )
    effective = effective_for(session, agent_slug="ledger-bot")
    assert [r.rule.id for r in effective.rules] == ["finance.input.block"]
    in_force = policies_in_force(session, "ledger-bot")
    assert [d.key for d, _v, _b in in_force] == ["finance-restrict"]
    assert policies_in_force(session, "help-bot") == []
