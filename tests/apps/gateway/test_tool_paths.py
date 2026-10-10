"""Tool-call paths seen in production, the new ones, and turning them into tests."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import Decision, EvalCase, Finding, utcnow

AGENT = "support-triage"


def _call(client, tool: str, prior: list[str], session_id: str) -> None:
    client.post(
        "/v1/guard/tool_call",
        json={
            "agent": AGENT,
            "tool": tool,
            "arguments": {},
            "prior_tools": prior,
            "session_id": session_id,
        },
    ).raise_for_status()


def _run(client, tools: list[str], session_id: str) -> None:
    for i, tool in enumerate(tools):
        _call(client, tool, tools[:i], session_id)


def _age(session_id_prefix: str, days: int) -> None:
    """Move a run's decisions back in time, into the baseline."""
    from agentfox.core.models import Trace

    with session_scope() as s:
        ids = [t.id for t in s.query(Trace).filter(Trace.session_id.like(f"{session_id_prefix}%"))]
        for d in s.query(Decision).filter(Decision.trace_id.in_(ids)):
            d.created_at = utcnow() - dt.timedelta(days=days)


def test_new_paths_and_new_steps_are_found(client):
    # An old, familiar path: lookup then summarise.
    _run(client, ["kb.search", "tickets.read"], "old-1")
    _age("old-1", 20)
    # This week: the familiar path again, and a new one with a new step in it.
    _run(client, ["kb.search", "tickets.read"], "now-1")
    _run(client, ["kb.search", "email.send", "tickets.read"], "now-2")

    body = client.get(f"/api/agents/{AGENT}/tool-paths?days=7").json()
    by_path = {tuple(p["path"]): p for p in body["paths"]}
    assert by_path[("kb.search", "tickets.read")]["new"] is False
    fresh = by_path[("kb.search", "email.send", "tickets.read")]
    assert fresh["new"] is True and fresh["covered"] is False
    assert ["kb.search", "email.send"] in fresh["new_steps"]
    assert body["new_paths"] == 1 and body["uncovered_new"] == 1
    assert {"from": "kb.search", "to": "email.send", "runs": 1} in body["new_steps"]


def test_a_path_added_to_tests_is_covered_and_scored_by_trajectory(client):
    _run(client, ["kb.search", "email.send"], "t-1")
    body = client.get(f"/api/agents/{AGENT}/tool-paths").json()
    path = body["paths"][0]
    resp = client.post(
        f"/api/agents/{AGENT}/tool-paths/tests",
        json={"path": path["path"], "trace_id": path["sample_trace_id"]},
    )
    assert resp.status_code == 201
    assert resp.json()["tools"] == ["kb.search", "email.send"]
    again = client.post(
        f"/api/agents/{AGENT}/tool-paths/tests",
        json={"path": path["path"], "trace_id": path["sample_trace_id"]},
    ).json()
    assert again["id"] == resp.json()["id"], "one case per path"
    after = client.get(f"/api/agents/{AGENT}/tool-paths").json()
    assert after["paths"][0]["covered"] is True and after["uncovered_new"] == 0


def test_repeats_collapse_and_redteam_tools_are_not_paths(client):
    _run(client, ["kb.search", "kb.search", "kb.search", "tickets.read"], "r-1")
    _run(client, ["redteam.sim.issue_refund"], "r-2")
    paths = [
        tuple(p["path"]) for p in client.get(f"/api/agents/{AGENT}/tool-paths").json()["paths"]
    ]
    assert ("kb.search", "tickets.read") in paths
    assert not any(p and p[0].startswith("redteam.") for p in paths)


# --- surfacing: the scheduled scan raises an issue, adding the path closes it ---------


def _scan() -> dict:
    from agentfox.apps import jobs as job_handlers

    with session_scope() as s:
        return job_handlers.HANDLERS["paths.scan"](s, {"days": 1})


def _path_findings() -> list[Finding]:
    with session_scope() as s:
        rows = list(s.scalars(select(Finding).where(Finding.type == "new_tool_path")))
        for f in rows:
            s.expunge(f)
        return rows


def test_the_scan_raises_one_issue_per_new_uncovered_path(client):
    _run(client, ["kb.search", "tickets.read"], "old-s")
    _age("old-s", 10)
    _run(client, ["kb.search", "tickets.read"], "s-1")
    _run(client, ["kb.search", "email.send"], "s-2")

    assert _scan()["new_uncovered"] == {AGENT: 1}
    _scan()
    found = _path_findings()
    assert len(found) == 1, "the same path again is an occurrence, not a new issue"
    issue = found[0]
    assert issue.severity == "low" and issue.status == "open"
    assert issue.evidence_json["path"] == ["kb.search", "email.send"]
    assert issue.occurrences == 2


def test_the_add_path_fix_adds_a_case_and_closes_the_issue(client):
    _run(client, ["kb.search", "email.send"], "f-1")
    _scan()
    issue = _path_findings()[0]
    body = client.get(f"/api/findings/{issue.id}").json()
    keys = {r["key"]: r for r in body["remedies"]}
    assert keys["add_path_to_tests"]["primary"] is True
    assert keys["open_tool_paths"]["href"] == f"/app/test?tab=paths&agent={AGENT}"

    resp = client.post(f"/api/findings/{issue.id}/remedies/add_path_to_tests", json={"inputs": {}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolved"] is True
    with session_scope() as s:
        cases = [c for c in s.scalars(select(EvalCase)) if "tool-path" in (c.labels or [])]
        assert [c.expected_json["tools"] for c in cases] == [["kb.search", "email.send"]]
    _scan()
    assert [f.status for f in _path_findings()] == ["resolved"], "a covered path stays closed"


def test_adding_the_path_from_the_paths_screen_also_closes_the_issue(client):
    _run(client, ["kb.search", "email.send"], "g-1")
    _scan()
    client.post(
        f"/api/agents/{AGENT}/tool-paths/tests", json={"path": ["kb.search", "email.send"]}
    ).raise_for_status()
    assert [f.status for f in _path_findings()] == ["resolved"]


def test_the_scan_is_a_default_daily_schedule_with_a_handler():
    from agentfox.apps import jobs as job_handlers
    from agentfox.platform.jobs import scheduler
    from agentfox.platform.jobs import store as jobs_db

    schedule = {d.kind: d for d in scheduler.DEFAULT_SCHEDULES}["paths.scan"]
    assert schedule.enabled
    assert job_handlers.HANDLERS["paths.scan"] is jobs_db._HANDLERS["paths.scan"]
