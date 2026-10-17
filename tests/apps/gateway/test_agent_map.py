"""The guardrail map: one entry per rule as this agent gets it, ready to change in place.

Each rule carries the pack a per-agent change is made against, whether the agent has
its own copy, and the grant behind each tool's permission, so the map can switch a
rule or a permission for this agent without leaving the page.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
ORCH, OTHER = "support-triage", "payments-ops"


def _map(client, slug: str = ORCH) -> dict:
    r = client.get(f"/api/agents/{slug}/map", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def _entries(m: dict, rule_id: str) -> list[dict]:
    rules = [r for s in m["stages"] for r in s["rules"]] + m["everywhere"]
    rules += [r for t in m["tools"] for r in t["rules"]]
    return [r for r in rules if r["id"] == rule_id]


def _scope(client, rule_id: str, body: dict, key: str = "baseline"):
    return client.post(f"/api/policies/{key}/rules/{rule_id}/scope", json=body, headers=ADMIN)


def test_each_rule_says_where_to_change_it(client):
    entries = _entries(_map(client), "pii.outbound_redact")
    assert entries, "the rule is on the map"
    for e in entries:
        assert e["policy"] == "baseline" and e["own"] is False and e["enabled"] is True


def test_an_agent_change_shows_as_its_own_copy(client):
    assert _scope(client, "pii.outbound_redact", {"agents": [ORCH], "effect": "block"}).is_success
    entries = _entries(_map(client), "pii.outbound_redact")
    # One entry per step, not one per copy: the agent's own wins.
    assert {e["effect"] for e in entries} == {"block"}
    e = entries[0]
    assert e["own"] and e["level"] == "agent" and e["policy"] == "baseline"
    assert e["workspace"]["effect"] == "redact"
    assert any(a["effect"] == "redact" for a in e["also"])
    # Other agents keep the workspace rule.
    assert {x["effect"] for x in _entries(_map(client, OTHER), "pii.outbound_redact")} == {"redact"}


def test_a_rule_switched_off_for_the_agent_stays_on_the_map(client):
    saved = client.post(
        "/api/policies/baseline/rules/secrets.block", json={"overridable": True}, headers=ADMIN
    ).json()
    client.post(
        "/api/policies/baseline/mode",
        json={"mode": saved["mode"], "version": saved["version"]},
        headers=ADMIN,
    )
    assert _entries(_map(client), "secrets.block")[0]["overridable"] is True
    assert _scope(client, "secrets.block", {"agents": [ORCH], "enabled": False}).is_success
    entries = _entries(_map(client), "secrets.block")
    assert entries and all(e["own"] and e["enabled"] is False for e in entries)


def test_tools_carry_their_grant(client):
    r = client.post(
        f"/api/agents/{ORCH}/access",
        json={"tool_key": "crm.*", "requires_approval": True},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/agents/{ORCH}/access",
        json={"tool_key": "crm.lookup", "constraints": {}},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    tools = {t["key"]: t for t in _map(client)["tools"]}
    # The tool's own grant wins over a pattern that also covers it.
    lookup = tools["crm.lookup"]
    assert lookup["permission"] == "allowed" and lookup["grant"]["key"] == "crm.lookup"
    assert lookup["grant"]["id"] and lookup["grant"]["max_taint"] == "user"


def test_a_custom_rule_for_another_agent_is_not_on_this_agents_map(client):
    client.post(
        "/api/custom-rules",
        json={
            "key": "only-triage",
            "name": "Only triage",
            "kind": "terms",
            "entries": ["zebra"],
            "agents": ["support-triage"],
        },
    ).raise_for_status()

    def rule_ids(slug):
        body = client.get(f"/api/agents/{slug}/map").json()
        ids = {r["id"] for st in body["stages"] for r in st["rules"]}
        ids |= {r["id"] for r in body["everywhere"]}
        ids |= {r["id"] for t in body["tools"] for r in t["rules"]}
        return ids

    assert "custom.only-triage" in rule_ids("support-triage")
    assert "custom.only-triage" not in rule_ids("payments-ops")
