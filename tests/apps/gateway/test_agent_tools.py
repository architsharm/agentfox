"""The tools one agent can be tested with: its own, never every tool in the workspace."""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _setup(slug: str = "tools-bot") -> str:
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Decision
    from agentfox.platform.registry.service import upsert_tool

    with session_scope() as session:
        session.add(
            Agent(slug=slug, registered=True, status="active", declared_tools=["crm.lookup"])
        )
        session.add(Agent(slug="other-bot", registered=True, status="active"))
        session.flush()
        agent = session.scalar(select(Agent).where(Agent.slug == slug))
        other = session.scalar(select(Agent).where(Agent.slug == "other-bot"))
        upsert_tool(
            session,
            "crm.lookup",
            impact="read",
            schema={
                "type": "object",
                "properties": {"customer_id": {"type": "string"}, "limit": {"type": "integer"}},
            },
        )
        session.add(
            Decision(
                agent_id=agent.id,
                surface="tool_args",
                tool_key="mail.send",
                taint_summary_json={"arguments_snapshot": {"to": "x", "body": "y"}},
            )
        )
        session.add(Decision(agent_id=agent.id, surface="tool_args", tool_key="redteam.exfil"))
        session.add(Decision(agent_id=other.id, surface="tool_args", tool_key="billing.refund"))
    return slug


def test_tools_are_the_agents_own_with_where_each_is_known_from(client):
    slug = _setup()
    r = client.post(f"/api/agents/{slug}/access", json={"tool_key": "kb.search"}, headers=ADMIN)
    assert r.status_code == 201, r.text

    body = client.get(f"/api/agents/{slug}/tools", headers=ADMIN).json()
    tools = {t["key"]: t for t in body["tools"]}
    # Another agent's tool and simulated red-team tools are not this agent's.
    assert set(tools) == {"crm.lookup", "kb.search", "mail.send"}
    assert tools["crm.lookup"]["sources"] == ["code"]
    assert tools["kb.search"]["sources"] == ["granted"]
    assert tools["kb.search"]["permission"] == "allowed"
    assert tools["mail.send"]["sources"] == ["seen"]

    # Arguments: typed blanks from the declared schema, else names from calls seen,
    # never the values a real call carried.
    assert tools["crm.lookup"]["arguments"] == {"customer_id": "", "limit": 0}
    assert tools["mail.send"]["arguments"] == {"body": "", "to": ""}
    assert tools["kb.search"]["arguments"] == {}


def test_it_is_the_same_set_the_map_shows(client):
    slug = _setup("map-bot")
    tools = {
        t["key"] for t in client.get(f"/api/agents/{slug}/tools", headers=ADMIN).json()["tools"]
    }
    mapped = {
        t["key"] for t in client.get(f"/api/agents/{slug}/map", headers=ADMIN).json()["tools"]
    }
    assert tools == mapped


def test_unknown_agent_is_404(client):
    assert client.get("/api/agents/nobody/tools", headers=ADMIN).status_code == 404
