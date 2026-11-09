"""After a retention purge, what still points at a deleted run says so.

Runs and decisions have separate retention periods, so a decision can outlive its run.
The audit found control pages linking those runs to "No such run … nothing has
created one yet", and SIEM events for those decisions with no agent or environment.
"""

from __future__ import annotations

import datetime as dt
import json

from agentfox.capabilities.compliance.retention import purge, removed_runs, set_policy
from agentfox.core.models import Agent, Decision, Finding, Trace, utcnow
from agentfox.exporters import siem


def _old_run(session, slug: str = "retained-bot"):
    old = utcnow() - dt.timedelta(days=60)
    agent = Agent(slug=slug, name=slug, environment="staging")
    session.add(agent)
    session.flush()
    session.add(
        Trace(
            id="tr_old", agent_id=agent.id, agent_slug=slug, environment="staging", started_at=old
        )
    )
    session.add(
        Decision(
            id="dec_old",
            trace_id="tr_old",
            agent_id=agent.id,
            created_at=old,
            verdict="block",
            rules_fired_json=[{"rule_id": "r1", "controls": ["NOM-RTG-01"]}],
        )
    )
    session.flush()
    # Runs kept 30 days, decisions a year: the decision outlives its run.
    set_policy(session, "traces", 30, actor="dana@example.com", reason="test")
    set_policy(session, "decisions", 365, actor="dana@example.com", reason="test")
    run = purge(session, trigger="manual", requested_by="dana@example.com")
    assert session.get(Trace, "tr_old") is None
    assert session.get(Decision, "dec_old") is not None
    return agent, run, old


def test_removed_runs_names_the_purge_that_deleted_a_run(session):
    _agent, run, old = _old_run(session)
    day = run.finished_at.date().isoformat()
    assert removed_runs(session, {"tr_old": old}) == {"tr_old": day}
    # A run no purge explains is not claimed as removed.
    assert removed_runs(session, {"tr_never": utcnow()}) == {}


def test_a_siem_event_keeps_its_agent_after_the_run_is_purged(session):
    agent, _run, _old = _old_run(session)
    session.add(Finding(type="containment", title="t", subject_type="agent", subject_id=agent.id))
    session.flush()
    events = [json.loads(line) for line in siem.export(session, "jsonl").splitlines()]
    decision = next(e for e in events if e["event_id"] == "dec_old")
    assert decision["agent"] == "retained-bot"
    assert decision["environment"] == "staging"
    finding = next(e for e in events if e["event_type"] == "governance.finding.containment")
    assert finding["agent"] == "retained-bot"


def test_cef_carries_the_product_version(session):
    from agentfox import __version__

    _old_run(session)
    line = siem.export(session, "cef").splitlines()[0]
    assert line.startswith(f"CEF:0|AgentFox|ControlPlane|{__version__}|")


def test_the_run_page_says_the_run_was_removed(client, session):
    from tests.conftest import as_user

    _old_run(session)
    session.commit()
    r = client.get("/api/traces/tr_old", headers=as_user("dana@example.com"))
    assert r.status_code == 404
    assert "removed by retention on" in r.json()["detail"]
    r = client.get("/api/traces/tr_nothing", headers=as_user("dana@example.com"))
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown trace"
