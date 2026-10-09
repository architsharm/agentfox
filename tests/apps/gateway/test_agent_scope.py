"""Changing one rule for some agents only: tighter always, looser only when allowed.

The change goes into each chosen agent's own layer (`agent.<slug>`), so it must
reach exactly those agents (and, when asked, the agents they hand work to) and
leave every other agent on the workspace rule.
"""

from __future__ import annotations

from agentfox.core.models import LineageEdge
from agentfox.platform.ledger.operator_log import operator_history
from agentfox.platform.policy import effective_for
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
DEV = as_user("priya@example.com")
ORCH, SUB, SUBSUB = "support-triage", "payments-ops", "hr-screening"


def _rule(session, slug: str, rule_id: str):
    """The winning copy of a rule for one agent, and every copy still in force."""
    effective = effective_for(session, slug)
    won = next(r for r in effective.rules if r.rule.id == rule_id)
    in_force = [
        (layer.level, rule)
        for layer in effective.applicable
        for rule in effective.rules_in_force(layer)
        if rule.id == rule_id
    ]
    return won, in_force


def _scope(client, rule_id: str, body: dict, key: str = "baseline", headers=ADMIN):
    return client.post(f"/api/policies/{key}/rules/{rule_id}/scope", json=body, headers=headers)


def test_tighten_for_one_agent_leaves_the_others_alone(client, session):
    r = _scope(client, "pii.outbound_redact", {"agents": [ORCH], "effect": "block"})
    assert r.status_code == 200, r.text
    assert [a["agent"] for a in r.json()["agents"]] == [ORCH]

    won, in_force = _rule(session, ORCH, "pii.outbound_redact")
    assert won.level == "agent" and won.rule.effect == "block"
    # The workspace copy stays in force beside the tighter one.
    assert ("org", "redact") in {(lvl, rule.effect) for lvl, rule in in_force}

    for other in (SUB, SUBSUB):
        won, _ = _rule(session, other, "pii.outbound_redact")
        assert won.level == "org" and won.rule.effect == "redact"


def test_preview_writes_nothing(client, session):
    r = _scope(
        client, "pii.outbound_redact", {"agents": [ORCH], "effect": "block", "preview": True}
    )
    assert r.status_code == 200, r.text
    assert "simulation" in r.json() and r.json()["agents"][0]["tighter"]
    won, _ = _rule(session, ORCH, "pii.outbound_redact")
    assert won.level == "org"


def test_loosening_is_refused_unless_the_rule_allows_it(client, session):
    off = {"agents": [ORCH], "enabled": False}
    r = _scope(client, "secrets.block", off)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["agent"] == ORCH and detail["policy"] == "baseline"
    assert detail["can_allow_loosening"] is True
    # A developer may change rules but may not grant agents the right to loosen.
    assert (
        _scope(client, "secrets.block", off, headers=DEV).json()["detail"]["can_allow_loosening"]
        is False
    )
    assert (
        client.post(
            "/api/policies/baseline/rules/secrets.block", json={"overridable": True}, headers=DEV
        ).status_code
        == 403
    )
    # A weaker action is a loosening too.
    assert (
        _scope(client, "secrets.block", {"agents": [ORCH], "effect": "redact"}).status_code == 409
    )
    # Less sensitive is a loosening too.
    assert _scope(client, "secrets.block", {"agents": [ORCH], "min_score": 0.99}).status_code == 409

    # The workspace rule grants it (saved, then made live like any rule change).
    saved = client.post(
        "/api/policies/baseline/rules/secrets.block", json={"overridable": True}, headers=ADMIN
    ).json()
    promoted = client.post(
        "/api/policies/baseline/mode",
        json={"mode": saved["mode"], "version": saved["version"]},
        headers=ADMIN,
    )
    assert promoted.status_code == 200, promoted.text

    r = _scope(client, "secrets.block", off)
    assert r.status_code == 200, r.text
    won, in_force = _rule(session, ORCH, "secrets.block")
    assert won.level == "agent" and won.loosened and not won.rule.enabled
    assert all(lvl == "agent" for lvl, _ in in_force)  # the workspace copy left force

    won, _ = _rule(session, SUB, "secrets.block")
    assert won.level == "org" and won.rule.enabled


def test_a_protected_rule_is_never_loosened_per_agent(client):
    r = _scope(
        client, "control_plane.tamper", {"agents": [ORCH], "enabled": False}, key="tool-containment"
    )
    assert r.status_code == 409
    assert r.json()["detail"]["can_allow_loosening"] is False


def test_sub_agents_follow_their_orchestrator(client, session):
    session.add_all(
        [
            LineageEdge(
                src_type="agent", src_id=ORCH, dst_type="agent", dst_id=SUB, relation="delegates_to"
            ),
            LineageEdge(
                src_type="agent",
                src_id=SUB,
                dst_type="agent",
                dst_id=SUBSUB,
                relation="delegates_to",
            ),
        ]
    )
    session.commit()

    tree = client.get("/api/policies/baseline/rules/safety.harm/agents", headers=ADMIN).json()
    depth = {a["slug"]: a["depth"] for a in tree["agents"]}
    assert depth[ORCH] == 0 and depth[SUB] == 1 and depth[SUBSUB] == 2

    r = _scope(
        client, "safety.harm", {"agents": [SUB], "min_score": 0.5, "include_delegates": True}
    )
    assert r.status_code == 200, r.text
    assert {a["agent"] for a in r.json()["agents"]} == {SUB, SUBSUB}
    for slug in (SUB, SUBSUB):
        won, _ = _rule(session, slug, "safety.harm")
        assert won.level == "agent" and won.rule.when.detection.min_score == 0.5
    won, _ = _rule(session, ORCH, "safety.harm")
    assert won.level == "org"


def test_effective_says_what_changed_and_reset_undoes_it(client, session):
    _scope(client, "pii.outbound_redact", {"agents": [ORCH], "effect": "block"})

    body = client.get(f"/api/policies/effective?agent={ORCH}", headers=ADMIN).json()
    rule = next(r for r in body["rules"] if r["rule_id"] == "pii.outbound_redact")
    assert rule["changed_for_agent"] and rule["level"] == "agent"
    change = next(c for c in body["agent_changes"] if c["rule_id"] == "pii.outbound_redact")
    assert change["kind"] == "changed" and change["has_effect"]
    assert change["default"]["effect"] == "redact" and change["agent"]["effect"] == "block"

    other = client.get(f"/api/policies/effective?agent={SUB}", headers=ADMIN).json()
    assert not any(r["changed_for_agent"] for r in other["rules"])

    r = client.delete(f"/api/policies/agents/{ORCH}/rules/pii.outbound_redact", headers=ADMIN)
    assert r.status_code == 200, r.text
    won, _ = _rule(session, ORCH, "pii.outbound_redact")
    assert won.level == "org" and won.rule.effect == "redact"
    assert (
        client.delete(
            f"/api/policies/agents/{ORCH}/rules/pii.outbound_redact", headers=ADMIN
        ).status_code
        == 404
    )

    actions = [h["action"] for h in operator_history(session)]
    assert "operator.agent_rule.changed" in actions and "operator.agent_rule.reset" in actions


def test_setting_back_to_the_default_drops_the_copy(client, session):
    _scope(client, "pii.outbound_redact", {"agents": [ORCH], "effect": "block"})
    r = _scope(client, "pii.outbound_redact", {"agents": [ORCH], "effect": "redact"})
    assert r.status_code == 200 and r.json()["agents"][0]["after"] is None
    won, _ = _rule(session, ORCH, "pii.outbound_redact")
    assert won.level == "org"


def test_rerunning_protection_setup_keeps_agent_rule_changes(client, session):
    # A rule outside the protection catalogue, and one inside it (personal data).
    _scope(client, "injection.system_prompt_leak", {"agents": [ORCH], "min_score": 0.5})
    _scope(client, "pii.outbound_redact", {"agents": [ORCH], "effect": "block"})
    r = client.post(
        f"/api/agents/{ORCH}/protection",
        json={"protections": {"attacks": "high", "personal_data": "high"}},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    won, _ = _rule(session, ORCH, "injection.system_prompt_leak")
    assert won.level == "agent" and won.rule.when.detection.min_score == 0.5
    won, _ = _rule(session, ORCH, "pii.outbound_redact")
    assert won.level == "agent" and won.rule.effect == "block"
    assert won.rule.when.detection.min_score == 0.5  # the setup's "high"


def test_every_agent_edits_the_rule_where_it_lives(client):
    r = _scope(client, "pii.outbound_redact", {"effect": "block"})
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "every" and r.json()["key"] == "baseline"


def test_unknown_agent_and_permissions(client):
    assert (
        _scope(client, "safety.harm", {"agents": ["nobody"], "min_score": 0.5}).status_code == 404
    )
    assert _scope(
        client,
        "safety.harm",
        {"agents": [ORCH], "min_score": 0.5},
        headers=as_user("aisha@example.com"),
    ).status_code in (401, 403)
