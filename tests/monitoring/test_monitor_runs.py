"""Running monitors: rescans diff against the last run, raise deduplicated findings, close
them when the condition clears, survive failures without closing anything, and honour
each monitor's own interval whatever the runner's cadence."""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
from sqlalchemy import select

from agentfox.apps import jobs as _handlers  # noqa: F401 - registers job kinds
from agentfox.core.config import get_settings
from agentfox.core.crypto import encrypt_secret
from agentfox.core.models import (
    Finding,
    GithubConnection,
    Job,
    JobSchedule,
    McpServer,
    McpToolSnapshot,
    Monitor,
    ScanRun,
    User,
)
from agentfox.monitoring import service as monitoring
from agentfox.monitoring import snapshots as snap
from agentfox.platform.jobs import scheduler
from agentfox.platform.jobs import store as jobs_db
from agentfox.platform.registry.service import scan_mcp_server, upsert_mcp_server
from tests.monitoring.conftest import T0

GOVERNED = """
import agentfox
from openai import OpenAI

agentfox.auto()
client = OpenAI()


def answer(question):
    return client.chat.completions.create(model="gpt-4o", messages=[])
"""

UNGOVERNED = GOVERNED.replace("import agentfox\n", "").replace("agentfox.auto()\n", "")

SUPPORT_BOT = """
from openai import OpenAI

client = OpenAI()

TOOLS = [
    {"type": "function", "function": {"name": "read_customer_record",
     "description": "Look up a customer by id.", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "fetch_url",
     "description": "Fetch a web page.", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "send_email",
     "description": "Send an email.", "parameters": {"type": "object"}}},
]


def triage(question):
    return client.chat.completions.create(model="gpt-4o", messages=[], tools=TOOLS)
"""


def _connect(session, encryption_key) -> GithubConnection:
    user = User(email="owner@acme.test", name="Owner", role="owner")
    session.add(user)
    session.flush()
    conn = GithubConnection(
        github_user_id="42",
        github_login="octo",
        access_token_encrypted=encrypt_secret("gho_test"),
        connected_by_user_id=user.id,
    )
    session.add(conn)
    session.flush()
    return conn


def _open(session, monitor):
    return sorted(f.type for f in monitoring.owned_findings(session, monitor, status="open"))


@pytest.fixture
def repo_monitor(session, encryption_key, fake_github):
    conn = _connect(session, encryption_key)
    fake_github.files = {"app/agent.py": GOVERNED}
    monitor, created = monitoring.ensure_monitor(
        session,
        kind="github_repo",
        target="acme/bot",
        config={"connection_id": conn.id},
        interval_seconds=3600,
    )
    assert created and monitor.next_run_at is None, "no baseline yet: due at once"
    return monitor


def test_first_run_stores_a_baseline_and_raises_nothing(session, repo_monitor, fake_github):
    result = monitoring.run_monitor(session, repo_monitor, now=T0)
    assert result["status"] == monitoring.BASELINE
    assert repo_monitor.baseline_json["type"] == "repo"
    assert _open(session, repo_monitor) == []
    assert fake_github.requests[0].url.path == "/repos/acme/bot/tarball"
    assert fake_github.requests[0].headers["authorization"] == "Bearer gho_test"
    run = session.get(ScanRun, result["summary"]["scan_run_id"])
    assert run.status == "completed" and run.summary_json["trigger"] == "monitor:schedule"


def test_changes_become_findings_once_and_close_when_they_clear(session, repo_monitor, fake_github):
    monitoring.run_monitor(session, repo_monitor, now=T0)

    # A push removes governance from the existing call and adds a support bot that
    # can read customer records, fetch pages and send email.
    fake_github.files = {"app/agent.py": UNGOVERNED, "bot/bot.py": SUPPORT_BOT}
    result = monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=1))
    assert result["status"] == monitoring.CHANGED
    opened = _open(session, repo_monitor)
    assert snap.GOVERNANCE_REMOVED in opened
    assert snap.LETHAL_TRIFECTA in opened
    assert snap.UNGOVERNED_MODEL_CALL in opened
    assert opened.count(snap.NEW_TOOL) == 3
    assert len(result["findings_opened"]) == len(opened)
    trifecta = next(
        f
        for f in monitoring.owned_findings(session, repo_monitor)
        if f.type == snap.LETHAL_TRIFECTA
    )
    assert trifecta.severity == "critical"
    assert trifecta.evidence_json["monitor_id"] == repo_monitor.id
    assert trifecta.evidence_json["target"] == "acme/bot"

    # Same code again: nothing new, nothing closed, no duplicate rows.
    count = session.query(Finding).count()
    again = monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=2))
    assert again["status"] == monitoring.OK
    assert session.query(Finding).count() == count
    assert again["findings_opened"] == [] and again["findings_closed"] == []

    # Governed again and the bot removed: every condition cleared, every finding closed.
    fake_github.files = {"app/agent.py": GOVERNED}
    cleared = monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=3))
    assert _open(session, repo_monitor) == []
    assert len(cleared["findings_closed"]) == len(opened)
    closed = session.get(Finding, cleared["findings_closed"][0])
    assert closed.status == "resolved" and closed.resolved_by == monitoring.ACTOR

    # The bot comes back: the same findings reopen, not new rows.
    fake_github.files = {"app/agent.py": GOVERNED, "bot/bot.py": SUPPORT_BOT}
    back = monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=4))
    assert back["findings_reopened"] and not back["findings_opened"]
    assert session.query(Finding).count() == count


def test_a_failed_run_closes_nothing_and_keeps_the_baseline(session, repo_monitor, fake_github):
    monitoring.run_monitor(session, repo_monitor, now=T0)
    fake_github.files = {"bot/bot.py": SUPPORT_BOT, "app/agent.py": GOVERNED}
    monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=1))
    before = _open(session, repo_monitor)
    baseline = dict(repo_monitor.baseline_json)

    fake_github.status = 502
    threshold = get_settings().monitor_failure_threshold
    for i in range(threshold):
        result = monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=2 + i))
        assert result["status"] == monitoring.FAILED
        assert "502" in result["error"]
    assert repo_monitor.consecutive_failures == threshold
    assert repo_monitor.baseline_json == baseline
    assert _open(session, repo_monitor) == sorted([*before, snap.MONITOR_FAILING])

    fake_github.status = 200
    ok = monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=9))
    assert ok["status"] == monitoring.OK
    assert repo_monitor.consecutive_failures == 0
    assert _open(session, repo_monitor) == before, "failing closed; the real findings stay"


def test_an_inconclusive_rescan_closes_nothing(session, repo_monitor, fake_github):
    monitoring.run_monitor(session, repo_monitor, now=T0)
    fake_github.files = {"bot/bot.py": SUPPORT_BOT, "app/agent.py": GOVERNED}
    monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=1))
    before = _open(session, repo_monitor)
    fake_github.files = {"README.md": "# moved to another repo"}
    result = monitoring.run_monitor(session, repo_monitor, now=T0 + dt.timedelta(hours=2))
    assert result["status"] == monitoring.INCONCLUSIVE
    assert _open(session, repo_monitor) == before


def test_a_push_reads_the_pushed_commit(session, repo_monitor, fake_github):
    monitoring.run_monitor(session, repo_monitor, now=T0, trigger="push", ref="deadbeef")
    assert fake_github.requests[-1].url.path == "/repos/acme/bot/tarball/deadbeef"
    assert repo_monitor.last_result_json["trigger"] == "push"


def test_no_connection_is_a_failure_not_a_crash(session):
    monitor, _ = monitoring.ensure_monitor(session, kind="github_repo", target="acme/none")
    result = monitoring.run_monitor(session, monitor, now=T0)
    assert result["status"] == monitoring.FAILED
    assert "no GitHub account" in monitor.last_error


# ---------------------------------------------------------------------------
# Scheduling: each monitor's own interval, whatever the runner's cadence
# ---------------------------------------------------------------------------


def test_run_due_honours_each_monitors_interval(session, repo_monitor):
    hourly = repo_monitor
    daily, _ = monitoring.ensure_monitor(
        session, kind="github_repo", target="acme/other", interval_seconds=86400
    )
    first = monitoring.run_due(session, now=T0)
    assert first["ran"] == 2

    # The runner fires every 30 minutes; nothing is due at +30m.
    assert monitoring.run_due(session, now=T0 + dt.timedelta(minutes=30))["ran"] == 0
    at_61 = monitoring.run_due(session, now=T0 + dt.timedelta(minutes=61))
    assert [r["monitor_id"] for r in at_61["results"]] == [hourly.id]
    assert monitoring.run_due(session, now=T0 + dt.timedelta(hours=24, minutes=1))["ran"] == 2
    assert daily.next_run_at is not None


def test_paused_monitors_do_not_run_and_the_batch_is_bounded(session, repo_monitor, monkeypatch):
    for i in range(3):
        monitoring.ensure_monitor(session, kind="github_repo", target=f"acme/r{i}")
    repo_monitor.enabled = False
    monkeypatch.setattr(get_settings(), "monitor_batch_limit", 2)
    result = monitoring.run_due(session, now=T0)
    assert result["ran"] == 2 and result["remaining_due"] == 1
    assert repo_monitor.id not in [r["monitor_id"] for r in result["results"]]


def test_a_connected_scan_baseline_makes_the_monitor_wait_a_full_interval(session):
    monitor, _ = monitoring.ensure_monitor(
        session,
        kind="hosted_api",
        target="https://api.example.com/openapi.json",
        baseline={"type": "openapi", "operations": {}},
        now=T0,
    )
    assert monitor.status == monitoring.BASELINE
    assert monitoring.due_monitors(session, T0 + dt.timedelta(hours=1)) == []
    assert monitoring.due_monitors(session, T0 + dt.timedelta(hours=6, seconds=1)) == [monitor]


def test_the_scheduler_enqueues_monitors_run_and_the_job_runs_due_monitors(session, repo_monitor):
    created = scheduler.ensure_default_schedules(session)
    schedule = next(s for s in created if s.kind == "monitors.run")
    assert schedule.enabled and schedule.interval_seconds == 600

    jobs = scheduler.enqueue_due(session, now=T0)
    job = next(j for j in jobs if j.kind == "monitors.run")
    jobs_db.run_job(session, job, now=T0)
    assert job.status == "done", job.last_error
    assert job.result_json["ran"] == 1
    assert repo_monitor.status == monitoring.BASELINE

    # A second runner call inside ten minutes enqueues nothing.
    again = scheduler.enqueue_due(session, now=T0 + dt.timedelta(minutes=5))
    assert "monitors.run" not in [j.kind for j in again]
    assert session.scalar(select(JobSchedule).where(JobSchedule.kind == "monitors.run"))


def test_request_run_does_not_pile_up_jobs(session, repo_monitor):
    first = monitoring.request_run(session, repo_monitor, trigger="push", ref="a1")
    second = monitoring.request_run(session, repo_monitor, trigger="push", ref="b2")
    assert first.id == second.id
    assert second.payload_json["ref"] == "b2"
    assert session.query(Job).filter(Job.kind == "monitors.run").count() == 1


# ---------------------------------------------------------------------------
# Hosted APIs
# ---------------------------------------------------------------------------

SPEC_URL = "https://api.example.com/openapi.json"


def test_hosted_api_monitor_refetches_the_spec_and_flags_destructive_endpoints(session, fake_web):
    fake_web.routes["/openapi.json"] = {
        "info": {"title": "Pets", "version": "1"},
        "paths": {"/pets": {"get": {"summary": "List pets"}}},
    }
    monitor, _ = monitoring.ensure_monitor(session, kind="hosted_api", target=SPEC_URL)
    assert monitoring.run_monitor(session, monitor, now=T0)["status"] == monitoring.BASELINE

    fake_web.routes["/openapi.json"] = {
        "info": {"title": "Pets", "version": "2"},
        "paths": {
            "/pets": {"get": {"summary": "List pets"}},
            "/pets/{id}": {"delete": {"summary": "Remove a pet"}},
            "/search": {"post": {"summary": "Search pets"}},
        },
    }
    result = monitoring.run_monitor(session, monitor, now=T0 + dt.timedelta(hours=6))
    assert result["status"] == monitoring.CHANGED
    by_type = {f.type: f for f in monitoring.owned_findings(session, monitor, status="open")}
    assert by_type[snap.API_DESTRUCTIVE_ENDPOINT].severity == "high"
    assert "DELETE /pets/{id}" in by_type[snap.API_DESTRUCTIVE_ENDPOINT].title
    assert by_type[snap.API_NEW_ENDPOINT].severity == "low"
    assert fake_web.requests[-1].headers["host"] == "api.example.com"

    # The endpoint is withdrawn: its finding closes.
    fake_web.routes["/openapi.json"] = {
        "info": {"title": "Pets", "version": "3"},
        "paths": {"/pets": {"get": {"summary": "List pets"}}, "/search": {"post": {}}},
    }
    monitoring.run_monitor(session, monitor, now=T0 + dt.timedelta(hours=12))
    assert [f.type for f in monitoring.owned_findings(session, monitor, status="open")] == [
        snap.API_NEW_ENDPOINT
    ]


def test_hosted_api_monitor_refuses_internal_addresses(session, monkeypatch):
    import socket

    from agentfox.core import outbound

    monkeypatch.setattr(
        outbound,
        "_getaddrinfo",
        lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))
        ],
    )
    monitor, _ = monitoring.ensure_monitor(session, kind="hosted_api", target=SPEC_URL)
    result = monitoring.run_monitor(session, monitor, now=T0)
    assert result["status"] == monitoring.FAILED
    assert "link-local" in monitor.last_error


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------

TOOLS_V1 = [{"name": "search", "description": "Search docs.", "inputSchema": {"type": "object"}}]
TOOLS_V2 = [
    *TOOLS_V1,
    {"name": "export", "description": "Export everything.", "inputSchema": {"type": "object"}},
]


def _mcp_endpoint(tools_ref: dict):
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "x"}},
                headers={"mcp-session-id": "s1"},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        assert request.headers["mcp-session-id"] == "s1"
        payload = {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": tools_ref["tools"]}}
        # Streamable HTTP may answer as an event stream.
        return httpx.Response(
            200,
            text=f"event: message\ndata: {json.dumps(payload)}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    return handle


def test_remote_mcp_monitor_reads_the_listing_and_raises_drift(session, fake_web):
    tools = {"tools": TOOLS_V1}
    fake_web.routes["/mcp"] = _mcp_endpoint(tools)
    server = upsert_mcp_server(
        session,
        "docs",
        url="https://mcp.example.com/mcp",
        transport="streamable-http",
        pinned_version="1.0",
    )
    monitor, _ = monitoring.ensure_monitor(
        session, kind="mcp_server", target="docs", config={"mcp_server_id": server.id}
    )
    first = monitoring.run_monitor(session, monitor, now=T0)
    assert first["status"] == monitoring.BASELINE
    assert first["summary"]["tools"] == 1

    unchanged = monitoring.run_monitor(session, monitor, now=T0 + dt.timedelta(hours=1))
    assert unchanged["status"] == monitoring.OK
    snapshots = session.query(McpToolSnapshot).filter_by(mcp_server_id=server.id).count()
    assert snapshots == 1, "an unchanged listing adds no snapshot"

    tools["tools"] = TOOLS_V2
    drifted = monitoring.run_monitor(session, monitor, now=T0 + dt.timedelta(hours=2))
    assert drifted["status"] == monitoring.CHANGED
    assert drifted["summary"]["drifted"] is True
    drift = session.scalar(
        select(Finding).where(Finding.type == "schema_drift", Finding.subject_id == server.id)
    )
    assert drift is not None and drift.evidence_json["added"] == ["export"]


def test_a_stdio_mcp_server_is_never_started_its_pushed_listing_is_watched(session, fake_web):
    server = upsert_mcp_server(session, "local", transport="stdio")
    monitor, _ = monitoring.ensure_monitor(session, kind="mcp_server", target="local")
    scan_mcp_server(session, server, TOOLS_V1)
    assert monitoring.run_monitor(session, monitor, now=T0)["status"] == monitoring.BASELINE
    scan_mcp_server(session, server, TOOLS_V2)  # pushed by `agentfox scan mcp --file`
    result = monitoring.run_monitor(session, monitor, now=T0 + dt.timedelta(hours=1))
    assert result["status"] == monitoring.CHANGED
    assert result["summary"]["live"] is False
    assert fake_web.requests == []


def test_an_mcp_monitor_whose_server_was_removed_fails_cleanly(session):
    monitor, _ = monitoring.ensure_monitor(session, kind="mcp_server", target="gone")
    assert monitoring.run_monitor(session, monitor, now=T0)["status"] == monitoring.FAILED
    assert session.scalar(select(McpServer).where(McpServer.name == "gone")) is None
    assert session.get(Monitor, monitor.id).status == monitoring.FAILED
