"""Protect an agent: its own layer can only add caution, and the setup is re-runnable."""

from __future__ import annotations

from agentfox.capabilities import protection
from agentfox.core.models import CustomRule
from agentfox.platform.policy import effective_for
from tests.conftest import INDIRECT_INJECTION, as_user

ADMIN = as_user("admin@example.com")
AGENT = "support-triage"
URL = f"/api/agents/{AGENT}/protection"
SETUP = {
    "protections": {"attacks": "high", "secrets": "high", "off_task": "on"},
    "message": "Sorry, I can't help with that here.",
    "words": ["Globex"],
    "avoid": "legal advice, lawsuits",
    "allowed": "",
}


def test_the_catalogue_and_its_levels(client):
    body = client.get(URL, headers=ADMIN).json()
    assert body["levels"] == protection.LEVELS
    keys = {p["key"]: p for p in body["protections"]}
    assert keys["attacks"]["graded"] and not keys["off_task"]["graded"]
    assert all(p["level"] == "off" for p in body["protections"])


def test_save_writes_an_agent_layer_and_scoped_rules(client, session):
    r = client.post(URL, json=SETUP, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["policy"]["mode"] == "observe"

    body = client.get(URL, headers=ADMIN).json()
    levels = {p["key"]: p["level"] for p in body["protections"]}
    assert levels["attacks"] == "high" and levels["off_task"] == "on" and levels["harmful"] == "off"
    assert body["message"] == SETUP["message"]
    assert body["words"] == ["Globex"] and body["avoid"] == "legal advice, lawsuits"

    rules = {r.key: r for r in session.query(CustomRule)}
    assert rules[f"{AGENT}-words"].agents_json == [AGENT]


def test_the_layer_applies_to_that_agent_only(client, session):
    client.post(URL, json=SETUP, headers=ADMIN)
    mine = {r.rule.id for r in effective_for(session, AGENT).rules if r.level == "agent"}
    other = {r.rule.id for r in effective_for(session, "payments-ops").rules if r.level == "agent"}
    assert "injection.direct" in mine and not other


def test_an_agent_cannot_go_below_the_workspace(client, session):
    client.post(URL, json={"protections": {"attacks": "low"}}, headers=ADMIN)
    effective = effective_for(session, AGENT)
    org_rules = {
        r.id: r
        for layer in effective.applicable
        if layer.level == "org"
        for r in effective.rules_in_force(layer)
    }
    # The workspace's own copy stays in force beside the agent's less sensitive one.
    assert "injection.direct" in org_rules
    attacks = next(
        p for p in client.get(URL, headers=ADMIN).json()["protections"] if p["key"] == "attacks"
    )
    assert attacks["inherited"] is not None


def test_rerunning_edits_instead_of_piling_up(client, session):
    client.post(URL, json=SETUP, headers=ADMIN)
    client.post(URL, json={**SETUP, "words": [], "avoid": ""}, headers=ADMIN)
    keys = {r.key for r in session.query(CustomRule)}
    assert f"{AGENT}-words" not in keys and f"{AGENT}-avoid" not in keys


def test_preview_replays_this_agents_traffic(client):
    client.post("/v1/guard/input", json={"agent": AGENT, "content": INDIRECT_INJECTION})
    r = client.post(f"{URL}/preview", json=SETUP, headers=ADMIN)
    assert r.status_code == 200 and r.json()["replayed"] >= 1


def test_bad_choices_and_permissions(client):
    assert (
        client.post(URL, json={"protections": {"off_task": "high"}}, headers=ADMIN).status_code
        == 400
    )
    assert client.post(URL, json={"protections": {"nope": "on"}}, headers=ADMIN).status_code == 400
    assert (
        client.post("/api/agents/no-such/protection", json=SETUP, headers=ADMIN).status_code == 404
    )
    assert client.post(URL, json=SETUP, headers=as_user("viewer@example.com")).status_code in (
        401,
        403,
    )
