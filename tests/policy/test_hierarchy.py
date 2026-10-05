"""P12 — hierarchical policy composition and lint.

The evidence for this pillar is a number: a practitioner who built it by hand
reported **87% fewer policy misconfigurations**. These tests exist to protect the
property that produces that number — a narrower level may always tighten, and may
only loosen where explicitly granted.
"""

from __future__ import annotations

from agentfox.policy import PolicyDocument, save_policy
from agentfox.policy.hierarchy import (
    PolicyLayer,
    lint_policy,
    lint_summary,
    resolve_effective,
)
from agentfox.policy.store import effective_for, lint_all
from tests.conftest import as_user

ORG = """
key: org
mode: enforce
rules:
  - id: secrets.block
    when: {detection: {entity_prefix: SECRET, min_score: 0.9}}
    effect: block
  - id: pii.redact
    when: {surface: [output], detection: {entity_prefix: PII, min_score: 0.7}}
    effect: redact
  - id: kb.allow
    when: {tool: kb.search}
    effect: allow
    overridable: true
"""


def layer(body: str, level: str, scope: str = "*", mode: str = "extend") -> PolicyLayer:
    return PolicyLayer(PolicyDocument.from_yaml(body), level=level, scope_id=scope, mode=mode)


def rules_by_id(effective) -> dict[str, object]:
    return {r.rule.id: r for r in effective.rules}


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_org_rules_apply_when_no_narrower_layer_exists():
    effective = resolve_effective([layer(ORG, "org")], {"org": "acme"})
    assert rules_by_id(effective)["secrets.block"].rule.effect == "block"


def test_a_narrower_level_may_always_tighten():
    """Nobody needs authorisation to be more careful."""
    team = """
key: t
rules:
  - id: pii.redact
    when: {surface: [output], detection: {entity_prefix: PII, min_score: 0.7}}
    effect: block
"""
    effective = resolve_effective(
        [layer(ORG, "org"), layer(team, "team", "finance")],
        {"org": "acme", "team": "finance"},
    )
    resolved = rules_by_id(effective)["pii.redact"]
    assert resolved.rule.effect == "block"
    assert resolved.level == "team"
    assert resolved.overrides == ["org:*"]
    assert not resolved.loosened


def test_loosening_is_rejected_without_an_upstream_grant():
    """The safety property. A team cannot quietly disable an org control."""
    team = """
key: t
rules:
  - id: secrets.block
    when: {detection: {entity_prefix: SECRET, min_score: 0.9}}
    effect: allow
"""
    effective = resolve_effective(
        [layer(ORG, "org"), layer(team, "team", "finance")],
        {"org": "acme", "team": "finance"},
    )
    assert rules_by_id(effective)["secrets.block"].rule.effect == "block"
    assert effective.rejected
    assert "not marked overridable" in effective.rejected[0]["reason"]


def test_loosening_is_permitted_where_granted():
    """`overridable: true` is a deliberate grant, and it works."""
    team = """
key: t
rules:
  - id: kb.allow
    when: {tool: kb.search}
    effect: allow
"""
    strict = ORG.replace(
        "    effect: allow\n    overridable: true", "    effect: block\n    overridable: true"
    )
    effective = resolve_effective(
        [layer(strict, "org"), layer(team, "team", "finance")],
        {"org": "acme", "team": "finance"},
    )
    resolved = rules_by_id(effective)["kb.allow"]
    assert resolved.rule.effect == "allow"
    assert resolved.loosened
    assert not effective.rejected


def test_restrict_mode_cannot_weaken_even_with_a_grant():
    """A layer that declares restraint and then loosens is a misconfiguration."""
    team = """
key: t
rules:
  - id: kb.allow
    when: {tool: kb.search}
    effect: allow
"""
    strict = ORG.replace(
        "    effect: allow\n    overridable: true", "    effect: block\n    overridable: true"
    )
    effective = resolve_effective(
        [layer(strict, "org"), layer(team, "team", "finance", mode="restrict")],
        {"org": "acme", "team": "finance"},
    )
    assert rules_by_id(effective)["kb.allow"].rule.effect == "block"
    assert "restrict" in effective.rejected[0]["reason"]


def test_narrowest_level_wins_across_four_levels():
    def one(effect: str) -> str:
        return f"""
key: k
rules:
  - id: pii.redact
    when: {{surface: [output], detection: {{entity_prefix: PII, min_score: 0.7}}}}
    effect: {effect}
"""

    effective = resolve_effective(
        [
            layer(ORG, "org"),
            layer(one("mask"), "team", "finance"),
            layer(one("escalate"), "agent", "payments-ops"),
            layer(one("block"), "user", "priya@acme.com"),
        ],
        {"org": "acme", "team": "finance", "agent": "payments-ops", "user": "priya@acme.com"},
    )
    resolved = rules_by_id(effective)["pii.redact"]
    assert resolved.rule.effect == "block"
    assert resolved.level == "user"


def test_context_isolation_between_teams():
    """P12-5: a team never sees another team's rules, because they are never in scope."""
    other = """
key: other
rules:
  - id: other.secret
    when: {tool: internal.thing}
    effect: block
"""
    effective = resolve_effective(
        [layer(ORG, "org"), layer(other, "team", "legal")],
        {"org": "acme", "team": "finance"},
    )
    assert "other.secret" not in rules_by_id(effective)
    assert "team:legal" not in " ".join(effective.layers)


def test_enforcement_escalates_and_never_relaxes_down_the_hierarchy():
    """A team cannot put itself back into observe once the org is enforcing."""
    team = "key: t\nmode: observe\nrules: []\n"
    effective = resolve_effective(
        [layer(ORG, "org"), layer(team, "team", "finance")],
        {"org": "acme", "team": "finance"},
    )
    assert effective.mode == "enforce"


def test_effective_policy_collapses_to_an_evaluable_document():
    """The composed result must run on the existing engine unchanged."""
    from agentfox.policy import NativePolicyEngine, PolicyInput

    effective = resolve_effective([layer(ORG, "org")], {"org": "acme"})
    decision = NativePolicyEngine().evaluate(
        effective.document(),
        PolicyInput(detections=[{"entity_type": "SECRET.OPENAI_KEY", "score": 0.97}]),
    )
    assert decision.verdict == "block"


def test_every_rule_reports_where_it_came_from():
    """Opacity is what makes layered policy dangerous."""
    effective = resolve_effective([layer(ORG, "org")], {"org": "acme"})
    for resolved in effective.rules:
        payload = resolved.to_json()
        assert payload["source"] and payload["level"] in ("org", "team", "agent", "user")


# ---------------------------------------------------------------------------
# Lint (P12-4)
# ---------------------------------------------------------------------------


def test_lint_flags_illegal_loosening_as_critical():
    team = """
key: t
rules:
  - id: secrets.block
    when: {detection: {entity_prefix: SECRET, min_score: 0.9}}
    effect: allow
"""
    findings = lint_policy([layer(ORG, "org"), layer(team, "team", "finance")])
    illegal = [f for f in findings if f.code == "illegal-loosening"]
    assert illegal and illegal[0].severity == "critical"


def test_lint_flags_an_unconditional_block():
    body = "key: k\nrules:\n  - id: everything\n    when: {}\n    effect: block\n"
    findings = lint_policy([layer(body, "org")])
    assert any(f.code == "unconditional" for f in findings)


def test_lint_flags_an_over_broad_tool_glob():
    body = 'key: k\nrules:\n  - id: wide\n    when: {tool: "*"}\n    effect: block\n'
    findings = lint_policy([layer(body, "org")])
    assert any(f.code == "over-broad-glob" for f in findings)


def test_lint_flags_a_shadowed_duplicate():
    findings = lint_policy([layer(ORG, "org"), layer(ORG, "team", "finance")])
    assert any(f.code == "shadowed" for f in findings)


def test_lint_gate_fails_on_critical_but_passes_on_advice():
    body = 'key: k\nrules:\n  - id: wide\n    when: {tool: "*"}\n    effect: block\n'
    advisory = lint_summary(lint_policy([layer(body, "org")]))
    assert advisory["passed"], "medium findings are advice, not a gate"

    team = """
key: t
rules:
  - id: secrets.block
    when: {detection: {entity_prefix: SECRET, min_score: 0.9}}
    effect: allow
"""
    blocking = lint_summary(lint_policy([layer(ORG, "org"), layer(team, "team", "finance")]))
    assert not blocking["passed"]
    assert blocking["blocking"]


def test_clean_policy_lints_clean():
    assert lint_summary(lint_policy([layer(ORG, "org")]))["passed"]


# ---------------------------------------------------------------------------
# Store + API integration
# ---------------------------------------------------------------------------


def test_shipped_packs_resolve_and_lint_clean(seeded):
    """The policies we ship must survive our own linter."""
    effective = effective_for(seeded, agent_slug="payments-ops")
    assert effective.rules
    assert effective.mode == "enforce"
    assert lint_all(seeded)["passed"], "shipped policy packs must lint clean"


def test_team_layer_composes_over_shipped_packs(seeded):
    team = PolicyDocument.from_yaml(
        """
key: finance-team
rules:
  - id: pii.outbound_redact
    when: {surface: [output], detection: {entity_prefix: PII, min_score: 0.7}}
    effect: block
"""
    )
    save_policy(seeded, team, author="lead", level="team", scope_id="finance")
    explained = effective_for(seeded, agent_slug="payments-ops", team="finance").explain()
    rule = next(r for r in explained["rules"] if r["rule_id"] == "pii.outbound_redact")
    assert rule["effect"] == "block"
    assert rule["source"] == "team:finance"


def test_effective_and_lint_endpoints(client):
    effective = client.get(
        "/api/policies/effective?agent=payments-ops", headers=as_user("marcus@example.com")
    )
    assert effective.status_code == 200
    body = effective.json()
    assert body["rules"] and body["layers"]
    assert all("source" in r for r in body["rules"])

    lint = client.get("/api/policies/lint", headers=as_user("marcus@example.com"))
    assert lint.status_code == 200
    assert lint.json()["passed"] is True


def test_pre_hierarchy_bindings_default_to_org_wide(seeded):
    """Backwards compatibility: existing bindings behave exactly as before."""
    from agentfox.policy.store import active_layers

    for policy_layer in active_layers(seeded):
        assert policy_layer.level == "org"
        assert policy_layer.scope_id == "*"
        assert policy_layer.mode == "extend"
