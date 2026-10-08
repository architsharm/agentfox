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
