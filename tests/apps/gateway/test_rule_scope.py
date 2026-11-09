"""A rule limited to one agent is listed, and enforced, on that agent only: whether
it was written in the app, or applied from a file that names the agent inside it."""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _applied_on(client, rule_id):
    rows = client.get("/api/policies/applied", headers=ADMIN).json()["rules"]
    row = next((r for r in rows if r["id"] == rule_id), None)
    return sorted(a["slug"] for a in row["agents"]) if row else []


def test_a_custom_rule_for_one_agent_is_not_applied_on_the_others(client):
    r = client.post(
        "/api/custom-rules",
        json={
            "key": "triage-words",
            "name": "Triage words",
            "kind": "terms",
            "entries": ["Globex"],
            "agents": ["support-triage"],
        },
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    assert _applied_on(client, "custom.triage-words") == ["support-triage"]


def test_a_limit_naming_its_agent_in_the_definition_is_scoped_to_it(client):
    # The shape `agentfox policy rules apply` sends: `agent:` inside the definition.
    definition = {
        "key": "pay-limit",
        "name": "Payment limit",
        "tool": "payments.transfer",
        "field": "arguments.amount",
        "unit": "USD",
        "agent": "payments-ops",
        "bands": [{"upto": 100, "outcome": "allow"}, {"upto": None, "outcome": "escalate"}],
    }
    r = client.post("/api/business/rules", json={"definition": definition}, headers=ADMIN)
    assert r.status_code == 201, r.text
    assert r.json()["agent"] == "payments-ops"
    assert r.json()["definition"]["agent"] == "payments-ops"
    assert _applied_on(client, "business.pay-limit") == ["payments-ops"]
