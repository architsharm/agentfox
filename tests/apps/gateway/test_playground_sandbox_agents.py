"""The playground's sandbox agents (fixtures/sandbox_agents.py): each suggested prompt
shows the outcome it names, through the real enforcement path, with no model key."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.fixtures.sandbox_agents import SANDBOX_AGENTS, simulate


@pytest.fixture(autouse=True)
def _reset_playground_rate_limits():
    from agentfox.apps.gateway import playground_sessions as pg

    pg.session_creation_limiter._hits.clear()
    pg.action_limiter._hits.clear()
    yield
    pg.session_creation_limiter._hits.clear()
    pg.action_limiter._hits.clear()


def _create(client) -> dict:
    resp = client.post("/api/playground/sessions")
    assert resp.status_code == 201
    return resp.json()


def _run(client, sid: str, slug: str, prompt: dict) -> dict:
    from agentfox.apps.gateway import playground_sessions as pg

    pg.action_limiter._hits.clear()
    if prompt.get("tool"):
        resp = client.post(
            f"/api/playground/sessions/{sid}/tool-call",
            json={
                "agent": slug,
                "tool": prompt["tool"],
                "arguments": prompt.get("args", {}),
                "intent": prompt.get("intent"),
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()
    resp = client.post(
        f"/api/playground/sessions/{sid}/chat", json={"agent": slug, "message": prompt["say"]}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_sandbox_agents_are_offered_first_with_tools_and_prompts(client):
    body = _create(client)
    slugs = [a["slug"] for a in body["agents"]]
    assert slugs[:2] == ["airline-cs", "support-crew"]
    assert {"support-triage", "payments-ops", "hr-screening"} <= set(slugs)
    airline = body["agents"][0]
    assert len(airline["tools"]) == 11
    held = {t["key"] for t in airline["tools"] if t["requires_approval"]}
    assert held == {"airline.issue_compensation", "airline.cancel_flight"}
    for agent in body["agents"][:2]:
        assert agent["summary"] and agent["purpose"]
        assert 6 <= len(agent["prompts"]) <= 10
        shown = {p["expect"] for p in agent["prompts"]}
        assert {"allow", "block", "held", "abstain", "withheld"} <= shown
    assert body["tools"]["airline.cancel_flight"]["impact"] == "irreversible"


@pytest.mark.parametrize(
    ("slug", "index"),
    [(a["slug"], i) for a in SANDBOX_AGENTS for i in range(len(a["prompts"]))],
)
def test_each_prompt_shows_its_outcome(client, slug, index):
    sid = _create(client)["session_id"]
    prompt = next(a for a in SANDBOX_AGENTS if a["slug"] == slug)["prompts"][index]
    body = _run(client, sid, slug, prompt)
    verdict = body if prompt.get("tool") else body["verdict"]
    expect = prompt["expect"]

    if expect == "allow":
        assert verdict["verdict"] == "allow", verdict["rules_fired"]
        assert verdict["effective_verdict"] == "allow", verdict["rules_fired"]
        if prompt.get("tool"):
            assert body["result"] is not None and body["result_withheld"] is False
        else:
            assert body["reply"]
    elif expect == "block":
        assert verdict["verdict"] == "block", verdict["rules_fired"]
    elif expect == "held":
        assert verdict["verdict"] == "escalate", verdict["rules_fired"]
        assert verdict["approval_id"]
        assert "result" not in body
    elif expect == "abstain":
        assert verdict["verdict"] == "abstain", verdict["rules_fired"]
    elif expect == "withheld":
        assert verdict["verdict"] == "allow"
        assert body["result_withheld"] is True and body["result"] is None
        rules = {r["rule_id"] for r in body["result_verdict"]["rules_fired"]}
        assert "injection.indirect" in rules
    elif expect == "flagged":
        assert verdict["verdict"] == "allow"
        assert verdict["effective_verdict"] in ("block", "escalate"), verdict["rules_fired"]
    else:  # pragma: no cover - a new expectation needs a branch here
        pytest.fail(f"unknown expectation {expect}")


def test_sandbox_traffic_is_playground_traffic(client):
    """Recorded as the playground environment, in the sandbox's own tenant."""
    from agentfox.apps.gateway.playground_sessions import get_store
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Trace

    sid = _create(client)["session_id"]
    prompt = SANDBOX_AGENTS[0]["prompts"][0]
    _run(client, sid, "airline-cs", prompt)
    _run(client, sid, "airline-cs", SANDBOX_AGENTS[0]["prompts"][5])

    with get_store().get(sid).session_scope() as s:
        envs = {t.environment for t in s.scalars(select(Trace))}
        agent = s.scalar(select(Agent).where(Agent.slug == "airline-cs"))
        assert envs == {"playground"}
        assert agent is not None and agent.environment == "playground"
    with session_scope() as s:
        assert s.scalar(select(Agent).where(Agent.slug == "airline-cs")) is None


def test_simulated_tools_are_deterministic_and_local():
    first = simulate("airline-cs", "airline.flight_status_tool", {"flight_number": "PA441"})
    assert first == simulate("airline-cs", "airline.flight_status_tool", {"flight_number": "PA441"})
    assert first["status"] == "on time"
    # Not a sandbox tool, or not this agent's: no result is invented.
    assert simulate("airline-cs", "payments.transfer", {}) is None
    assert simulate("support-triage", "kb.search", {}) is None
