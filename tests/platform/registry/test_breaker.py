"""The agent circuit breaker: a burst of blocked calls pauses (or flags) the agent,
the cool-down ends in a probe, and clean calls close it again."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from agentfox.core.models import Agent, AgentControl, AuditEntry, Finding, utcnow
from agentfox.platform.registry import breaker
from tests.conftest import as_user

AGENT = "payments-ops"
ADMIN = as_user("admin@example.com")


def _blocked(enforcer):
    result = enforcer.guard_tool_call(
        agent_slug=AGENT,
        tool_key="payments.transfer",
        arguments={"amount": 25000, "currency": "USD", "to": "acct_x"},
        intent="settle an invoice",
    )
    assert result.blocked
    return result


def _agent(session) -> Agent:
    return session.scalar(select(Agent).where(Agent.slug == AGENT))


def _configure(session, **changes):
    defaults = {"min_calls": 3, "block_ratio": 0.5, "window_seconds": 300, "probe_calls": 2}
    return breaker.configure(session, _agent(session), {**defaults, **changes}, actor="test")


def _findings(session) -> list[Finding]:
    return list(session.scalars(select(Finding).where(Finding.type == breaker.FINDING_TYPE)))


def _end_cooldown(session) -> None:
    control = session.scalar(
        select(AgentControl).where(AgentControl.agent_id == _agent(session).id)
    )
    cfg = dict(control.breaker_json)
    cfg["retry_at"] = (utcnow() - dt.timedelta(seconds=1)).isoformat()
    control.breaker_json = cfg
    session.flush()


def test_pause_mode_trips_after_a_burst_and_refuses_calls(seeded, enforcer):
    _configure(seeded, mode="pause")
    for _ in range(3):
        _blocked(enforcer)
    status = breaker.status(seeded, _agent(seeded))
    assert status["state"] == "open" and status["trips"] == 1
    assert "3 of 3 calls blocked" in status["reason"]

    refused = _blocked(enforcer)
    assert refused.rules_fired[0]["rule_id"] == "agent.circuit_open"
    assert "Circuit breaker open" in refused.reason
    [issue] = _findings(seeded)
    assert issue.severity == "high" and issue.status == "open"


def test_alert_mode_raises_the_issue_and_refuses_nothing(seeded, enforcer):
    _configure(seeded, mode="alert")
    for _ in range(5):
        result = _blocked(enforcer)
        assert result.rules_fired[0]["rule_id"] != "agent.circuit_open"
    assert breaker.status(seeded, _agent(seeded))["state"] == "closed"
    [issue] = _findings(seeded)
    assert issue.severity == "medium" and "would have been paused" in issue.title
    assert issue.occurrences == 1, "one burst is one occurrence"


def test_off_mode_does_nothing(seeded, enforcer):
    _configure(seeded, mode="off")
    for _ in range(4):
        _blocked(enforcer)
    assert _findings(seeded) == []


def test_a_quiet_agent_does_not_trip_on_one_bad_call(seeded, enforcer):
    _configure(seeded, mode="pause", min_calls=10)
    for _ in range(3):
        _blocked(enforcer)
    assert breaker.status(seeded, _agent(seeded))["state"] == "closed"


def test_after_the_cooldown_a_blocked_probe_reopens_with_a_longer_cooldown(seeded, enforcer):
    _configure(seeded, mode="pause", cooldown_seconds=60)
    for _ in range(3):
        _blocked(enforcer)
    _end_cooldown(seeded)
    probe = _blocked(enforcer)  # goes through to the checks, which block it again
    assert probe.rules_fired[0]["rule_id"] != "agent.circuit_open"
    status = breaker.status(seeded, _agent(seeded))
    assert status["state"] == "open" and status["reopens"] == 1
    retry = dt.datetime.fromisoformat(status["retry_at"])
    assert retry - utcnow() > dt.timedelta(seconds=100), "the cool-down doubles"


def test_clean_probes_close_it_and_the_issue_closes_itself(seeded, enforcer):
    _configure(seeded, mode="pause")
    for _ in range(3):
        _blocked(enforcer)
    _end_cooldown(seeded)
    for _ in range(2):
        enforcer.guard_tool_call(
            agent_slug=AGENT,
            tool_key="payments.transfer",
            arguments={"amount": 10, "currency": "USD", "to": "acct_x"},
            intent="settle an invoice",
        )
    assert breaker.status(seeded, _agent(seeded))["state"] == "closed"
    [issue] = _findings(seeded)
    assert issue.status == "resolved"
    actions = [a for (a,) in seeded.execute(select(AuditEntry.action))]
    assert {"agent.breaker.tripped", "agent.breaker.probing", "agent.breaker.closed"} <= set(
        actions
    )


def test_a_persons_pause_wins_over_the_breaker(seeded, enforcer):
    from agentfox.platform.registry.control import set_state

    _configure(seeded, mode="pause")
    set_state(seeded, AGENT, "quarantined", reason="investigating", actor="test")
    for _ in range(4):
        enforcer.guard_tool_call(
            agent_slug=AGENT,
            tool_key="payments.transfer",
            arguments={"amount": 25000, "currency": "USD", "to": "acct_x"},
        )
    assert breaker.status(seeded, _agent(seeded))["trips"] == 0


def test_a_resumed_agent_is_judged_on_calls_after_the_resume(seeded, enforcer):
    _configure(seeded, mode="pause")
    for _ in range(3):
        _blocked(enforcer)
    breaker.reset(seeded, _agent(seeded), actor="test", reason="fixed")
    _blocked(enforcer)
    assert breaker.status(seeded, _agent(seeded))["state"] == "closed", (
        "the burst it was resumed from does not trip it again"
    )
    _blocked(enforcer)
    _blocked(enforcer)
    assert breaker.status(seeded, _agent(seeded))["state"] == "open"


def test_settings_are_bounded(seeded):
    with pytest.raises(ValueError):
        _configure(seeded, block_ratio=2)
    with pytest.raises(ValueError):
        _configure(seeded, mode="sometimes")


# --- over the API ------------------------------------------------------------------


def test_the_breaker_api_and_the_resume_fix(client):
    from agentfox.core.db import session_scope
    from agentfox.runtime.enforcement import Enforcer

    put = client.put(
        f"/api/agents/{AGENT}/breaker",
        json={"mode": "pause", "min_calls": 3, "probe_calls": 2},
        headers=ADMIN,
    )
    assert put.status_code == 200, put.text
    assert put.json()["mode"] == "pause"
    assert client.put(f"/api/agents/{AGENT}/breaker", json={"min_calls": 1}).status_code == 422

    with session_scope() as s:
        for _ in range(3):
            _blocked(Enforcer(s))
    body = client.get(f"/api/agents/{AGENT}/breaker").json()
    assert body["state"] == "open" and body["window"]["blocked"] == 3
    controls = client.get("/api/agent-controls").json()["controls"]
    assert next(c for c in controls if c["agent"] == AGENT)["breaker"]["state"] == "open"

    with session_scope() as s:
        issue = s.scalar(select(Finding).where(Finding.type == breaker.FINDING_TYPE))
        issue_id = issue.id
    remedies = {r["key"] for r in client.get(f"/api/findings/{issue_id}").json()["remedies"]}
    assert {"reset_breaker", "breaker_settings"} <= remedies
    done = client.post(
        f"/api/findings/{issue_id}/remedies/reset_breaker",
        json={"inputs": {"reason": "fixed the prompt"}},
        headers=ADMIN,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "resolved"
    assert client.get(f"/api/agents/{AGENT}/breaker").json()["state"] == "closed"
