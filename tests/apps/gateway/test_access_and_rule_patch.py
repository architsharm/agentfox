"""Agent access over HTTP, and changing one rule as a new policy version."""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _agent(slug: str = "access-bot") -> str:
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        session.add(Agent(slug=slug, registered=True, status="active"))
    return slug


def test_grant_update_and_revoke_a_tool(client):
    slug = _agent()
    r = client.post(f"/api/agents/{slug}/access", json={"tool_key": "crm.lookup"}, headers=ADMIN)
    assert r.status_code == 201 and r.json()["event"] == "capability.granted"

    r = client.post(
        f"/api/agents/{slug}/access",
        json={
            "tool_key": "crm.lookup",
            "requires_approval": True,
            "constraints": {"amount": {"lte": 500}},
        },
        headers=ADMIN,
    )
    assert r.json()["event"] == "capability.updated"

    body = client.get(f"/api/agents/{slug}/access", headers=ADMIN).json()
    [cap] = body["capabilities"]
    assert cap["requires_approval"] is True
    assert cap["constraints"] == {"amount": {"lte": 500}}
    assert cap["id"] in body["unused"]

    assert client.delete(f"/api/agents/{slug}/access/{cap['id']}", headers=ADMIN).status_code == 200
    assert client.get(f"/api/agents/{slug}/access", headers=ADMIN).json()["capabilities"] == []


def test_refused_tools_are_listed_as_tried(client):
    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Decision

    slug = _agent("tried-bot")
    with session_scope() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == slug))
        session.add(
            Decision(
                agent_id=agent.id,
                surface="tool_call",
                tool_key="crm.delete_contact",
                verdict="block",
                rules_fired_json=[{"rule_id": "capability.denied"}],
            )
        )
    tried = client.get(f"/api/agents/{slug}/access", headers=ADMIN).json()["tried"]
    assert tried[0]["tool_key"] == "crm.delete_contact" and tried[0]["count"] == 1


def test_bad_trust_level_is_rejected(client):
    slug = _agent("taint-bot")
    r = client.post(
        f"/api/agents/{slug}/access", json={"tool_key": "x", "max_taint": "anything"}, headers=ADMIN
    )
    assert r.status_code == 400


def test_patching_a_rule_saves_a_version_without_changing_what_is_live(client):
    before = client.get("/api/policies/baseline", headers=ADMIN).json()
    r = client.post(
        "/api/policies/baseline/rules/safety.harm", json={"effect": "escalate"}, headers=ADMIN
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["version"] == before["latest_version"] + 1
    assert "escalate" in out["body"]
    after = client.get("/api/policies/baseline", headers=ADMIN).json()
    assert after["bound_version"] == before["bound_version"]


def test_patching_an_unknown_rule_is_404(client):
    r = client.post(
        "/api/policies/baseline/rules/nope.nope", json={"enabled": False}, headers=ADMIN
    )
    assert r.status_code == 404


def test_patching_message_reask_and_sensitivity(client):
    r = client.post(
        "/api/policies/baseline/rules/safety.harm",
        json={"message": "I can't help with that.", "on_block": "reask", "min_score": 0.3},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    body = r.json()["body"]
    assert "I can't help with that." in body and "reask" in body and "0.3" in body


def test_sensitivity_on_a_rule_without_detection_is_refused(client):
    r = client.post(
        "/api/policies/tool-containment/rules/capability.denied",
        json={"min_score": 0.3},
        headers=ADMIN,
    )
    assert r.status_code == 400


def test_granting_an_unknown_tool_registers_it_so_allow_means_allow(client):
    """Allow used to leave every call held by `tool.not_declared`."""
    r = client.post(
        "/api/agents/support-triage/access",
        json={"tool_key": "airline.cancel_flight"},
        headers=as_user("admin@example.com"),
    )
    assert r.status_code == 201, r.text
    caps = client.get(
        "/api/agents/support-triage/access", headers=as_user("admin@example.com")
    ).json()["capabilities"]
    tool = next(c for c in caps if c["tool_key"] == "airline.cancel_flight")["tool"]
    assert tool["impact"] == "irreversible" and tool["impact_source"] == "inferred"

    client.post(
        "/api/agents/support-triage/access",
        json={"tool_key": "airline.cancel_flight", "impact": "high_impact"},
        headers=as_user("admin@example.com"),
    )
    caps = client.get(
        "/api/agents/support-triage/access", headers=as_user("admin@example.com")
    ).json()["capabilities"]
    tool = next(c for c in caps if c["tool_key"] == "airline.cancel_flight")["tool"]
    assert tool["impact"] == "high_impact" and tool["impact_source"] == "declared"

    out = client.post(
        "/v1/guard/tool_call",
        json={
            "agent": "support-triage",
            "tool": "airline.cancel_flight",
            "arguments": {},
            "provenance": {},
        },
    ).json()
    assert "tool.not_declared" not in {f["rule_id"] for f in out["rules_fired"]}


def test_a_bad_impact_is_refused(client):
    r = client.post(
        "/api/agents/support-triage/access",
        json={"tool_key": "airline.x", "impact": "catastrophic"},
        headers=as_user("admin@example.com"),
    )
    assert r.status_code == 400


def test_a_retried_held_call_reuses_its_approval(client):
    client.post(
        "/api/agents/support-triage/access",
        json={
            "tool_key": "airline.cancel_flight",
            "requires_approval": True,
            "impact": "irreversible",
        },
        headers=ADMIN,
    )

    def call(args):
        return client.post(
            "/v1/guard/tool_call",
            json={
                "agent": "support-triage",
                "tool": "airline.cancel_flight",
                "arguments": args,
                "provenance": {},
            },
        ).json()

    first, again = call({"booking": "IR-D204"}), call({"booking": "IR-D204"})
    assert first["approval_id"] and again["approval_id"] == first["approval_id"]
    assert call({"booking": "ZZ-0001"})["approval_id"] != first["approval_id"]

    client.post(
        f"/api/approvals/{first['approval_id']}/approve", json={"rationale": "ok"}, headers=ADMIN
    )
    out = client.post(
        "/v1/guard/tool_call",
        json={
            "agent": "support-triage",
            "tool": "airline.cancel_flight",
            "arguments": {"booking": "IR-D204"},
            "provenance": {},
            "approval_id": first["approval_id"],
        },
    ).json()
    assert out["verdict"] == "allow"
