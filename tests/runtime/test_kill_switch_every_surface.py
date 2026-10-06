"""#11 + #13: the kill switch covers every guard surface, and blocks approvals.

Before: after `agents quarantine`, /v1/guard/input, /output, /memory_write and
/agent_message still answered `allow` (only completions and tool calls checked the
control state), and a pending approval for the stopped agent could still be approved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agentfox.apps.gateway.app import create_app
from agentfox.core.db import session_scope
from agentfox.core.models import Agent, MemoryEntry
from agentfox.platform.identity import AgentStopped, request_approval, resolve_approval
from agentfox.platform.registry.control import set_state

AGENT = "support-triage"


@pytest.fixture
def client():
    from agentfox.fixtures.seed import seed

    with session_scope() as s:
        seed(s)
    return TestClient(create_app())


def _stop(state: str = "quarantined") -> None:
    with session_scope() as s:
        set_state(s, AGENT, state, reason="incident 42", actor="test")


SURFACES = [
    ("/v1/guard/input", {"agent": AGENT, "content": "what is my order status?"}),
    ("/v1/guard/output", {"agent": AGENT, "content": "your order shipped"}),
    ("/v1/guard/memory_write", {"agent": AGENT, "content": "prefers email"}),
    ("/v1/guard/agent_message", {"sender": AGENT, "content": "hand-off", "nonce": "k1"}),
    ("/v1/guard/tool_call", {"agent": AGENT, "tool": "kb.search", "arguments": {"q": "x"}}),
]


@pytest.mark.parametrize("state", ["quarantined", "killed"])
@pytest.mark.parametrize("path,body", SURFACES)
def test_a_stopped_agent_is_refused_on_every_guard_surface(client, path, body, state):
    _stop(state)
    result = client.post(path, json=body).json()
    assert result["verdict"] == "block", result
    assert any(r.get("id", r.get("rule_id", "")) == f"agent.{state}" for r in result["rules_fired"])


def test_a_quarantined_agents_memory_write_does_not_persist(client):
    _stop()
    client.post("/v1/guard/memory_write", json={"agent": AGENT, "content": "remember this"})
    with session_scope() as s:
        agent = s.scalar(select(Agent).where(Agent.slug == AGENT))
        stored = s.scalars(select(MemoryEntry).where(MemoryEntry.agent_id == agent.id)).all()
    assert stored == []


def test_resuming_lifts_the_block(client):
    body = {"agent": AGENT, "content": "hello"}
    _stop()
    assert client.post("/v1/guard/input", json=body).json()["verdict"] == "block"
    _stop("active")
    assert client.post("/v1/guard/input", json=body).json()["verdict"] == "allow"


def _pending_approval() -> str:
    with session_scope() as s:
        agent = s.scalar(select(Agent).where(Agent.slug == AGENT))
        return request_approval(
            s, agent_id=agent.id, tool_key="refunds.issue", arguments={}, reason="test"
        ).id


def test_an_approval_cannot_be_granted_while_the_agent_is_stopped(client):
    approval_id = _pending_approval()
    _stop()
    response = client.post(
        f"/api/approvals/{approval_id}/approve",
        json={"rationale": "looks fine"},
        headers={"X-Nometria-User": "admin@example.com"},
    )
    assert response.status_code == 409, response.text
    assert "quarantined" in response.json()["detail"]
    with session_scope() as s, pytest.raises(AgentStopped):
        resolve_approval(s, approval_id, True, "usr_x")


def test_an_approval_can_still_be_denied_while_the_agent_is_stopped(client):
    approval_id = _pending_approval()
    _stop("killed")
    response = client.post(
        f"/api/approvals/{approval_id}/deny",
        json={"rationale": "incident"},
        headers={"X-Nometria-User": "admin@example.com"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "denied"


def test_an_approval_can_be_granted_once_resumed(client):
    approval_id = _pending_approval()
    _stop()
    _stop("active")
    response = client.post(
        f"/api/approvals/{approval_id}/approve",
        json={"rationale": "resolved"},
        headers={"X-Nometria-User": "admin@example.com"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
