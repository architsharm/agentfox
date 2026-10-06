"""The HTTP side: monitors created by the connect flows, the operator CRUD, the GitHub
push webhook, and alerts going out through the finding webhook and Slack."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from agentfox.core.config import get_settings
from agentfox.core.crypto import decrypt_secret, encrypt_secret
from agentfox.core.db import session_scope
from agentfox.core.models import AlertChannel, Finding, GithubConnection, Job, Monitor, User
from agentfox.monitoring import alerts
from agentfox.monitoring import github as gh
from agentfox.monitoring import service as monitoring
from agentfox.monitoring import snapshots as snap
from tests.conftest import as_user
from tests.monitoring.test_monitor_runs import GOVERNED, SUPPORT_BOT

ADMIN = as_user("admin@example.com")
AUDITOR = as_user("aisha@example.com")
HOOK = "/api/integrations/github/webhook"


def _connection(encryption_key) -> str:
    with session_scope() as s:
        owner = s.scalar(select(User).where(User.email == "admin@example.com"))
        conn = GithubConnection(
            github_user_id="42",
            github_login="octo",
            access_token_encrypted=encrypt_secret("gho_test"),
            connected_by_user_id=owner.id,
        )
        s.add(conn)
        s.flush()
        return conn.id


# ---------------------------------------------------------------------------
# Created by the connect flows
# ---------------------------------------------------------------------------


def test_scanning_a_connected_repo_starts_monitoring_it(client, encryption_key, fake_github):
    _connection(encryption_key)
    fake_github.files = {"app/agent.py": GOVERNED}
    response = client.post(
        "/api/integrations/github/scan", json={"repo_full_name": "acme/bot"}, headers=ADMIN
    )
    assert response.status_code == 200, response.text
    monitor_id = response.json()["summary"]["monitor_id"]
    monitor = client.get(f"/api/monitors/{monitor_id}", headers=ADMIN).json()
    assert monitor["kind"] == "github_repo" and monitor["target"] == "acme/bot"
    assert monitor["has_baseline"] and monitor["status"] == "baseline"
    assert monitor["next_run_at"], "waits a full interval: the scan just looked"

    # Scanning again does not add a second monitor.
    client.post("/api/integrations/github/scan", json={"repo_full_name": "acme/bot"}, headers=ADMIN)
    listing = client.get("/api/monitors", headers=ADMIN).json()["monitors"]
    assert [m["target"] for m in listing] == ["acme/bot"]


def test_a_failed_download_is_reported_as_a_bad_gateway(client, encryption_key, fake_github):
    _connection(encryption_key)
    fake_github.status = 404
    response = client.post(
        "/api/integrations/github/scan", json={"repo_full_name": "acme/gone"}, headers=ADMIN
    )
    assert response.status_code == 502
    assert client.get("/api/monitors", headers=ADMIN).json()["monitors"] == []


def test_scanning_a_hosted_api_spec_starts_monitoring_it(client, monkeypatch):
    import agentfox.gateway.routes.integrations as integrations

    spec = {"info": {"title": "Pets"}, "paths": {"/pets": {"get": {"summary": "List"}}}}
    monkeypatch.setattr(integrations, "fetch_spec", lambda url: spec)
    response = client.post(
        "/api/integrations/hosted-api/scan",
        json={
            "endpoint_url": "https://pets.example.com/v1",
            "openapi_spec_url": "https://pets.example.com/openapi.json",
        },
        headers=ADMIN,
    )
    assert response.status_code == 200, response.text
    monitor = client.get(
        f"/api/monitors/{response.json()['summary']['monitor_id']}", headers=ADMIN
    ).json()
    assert monitor["kind"] == "hosted_api"
    assert monitor["target"] == "https://pets.example.com/openapi.json"
    assert monitor["config"]["endpoint_url"] == "https://pets.example.com/v1"


def test_a_hosted_api_without_a_spec_has_nothing_to_monitor(client):
    response = client.post(
        "/api/integrations/hosted-api/scan",
        json={"endpoint_url": "https://nospec.example.com"},
        headers=ADMIN,
    )
    assert response.json()["summary"]["monitor_id"] is None


def test_registering_an_mcp_server_starts_monitoring_it(client):
    response = client.post(
        "/api/mcp-servers",
        json={"name": "docs", "url": "https://mcp.example.com/mcp", "transport": "streamable-http"},
        headers=ADMIN,
    )
    assert response.status_code == 201
    monitor_id = response.json()["monitor_id"]
    monitor = client.get(f"/api/monitors/{monitor_id}", headers=ADMIN).json()
    assert monitor["kind"] == "mcp_server" and monitor["target"] == "docs"
    assert monitor["next_run_at"] is None, "no baseline: due on the next runner call"


# ---------------------------------------------------------------------------
# Operator CRUD
# ---------------------------------------------------------------------------


def test_create_pause_resume_retune_and_delete(client):
    created = client.post(
        "/api/monitors",
        json={"kind": "github_repo", "target": "acme/bot", "interval_seconds": 60},
        headers=ADMIN,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["interval_seconds"] == monitoring.MIN_INTERVAL_SECONDS, "clamped"
    mid = body["id"]

    assert (
        client.post(
            "/api/monitors", json={"kind": "github_repo", "target": "acme/bot"}, headers=ADMIN
        ).status_code
        == 409
    )
    assert client.post(f"/api/monitors/{mid}/pause", headers=ADMIN).json()["enabled"] is False
    assert (
        client.get("/api/monitors?enabled=false", headers=ADMIN).json()["monitors"][0]["id"] == mid
    )
    assert client.post(f"/api/monitors/{mid}/resume", headers=ADMIN).json()["enabled"] is True
    patched = client.patch(
        f"/api/monitors/{mid}", json={"interval_seconds": 7200, "name": "Bot"}, headers=ADMIN
    ).json()
    assert patched["interval_seconds"] == 7200 and patched["name"] == "Bot"
    assert client.delete(f"/api/monitors/{mid}", headers=ADMIN).json()["deleted"] is True
    assert client.get(f"/api/monitors/{mid}", headers=ADMIN).status_code == 404


def test_monitor_targets_are_validated(client):
    bad = [
        {"kind": "github_repo", "target": "not a repo"},
        {"kind": "hosted_api", "target": "file:///etc/passwd"},
        {"kind": "ftp", "target": "x"},
    ]
    for payload in bad:
        assert client.post("/api/monitors", json=payload, headers=ADMIN).status_code == 422
    missing = client.post(
        "/api/monitors", json={"kind": "mcp_server", "target": "nope"}, headers=ADMIN
    )
    assert missing.status_code == 404


def test_an_auditor_can_read_monitors_but_not_change_them(client):
    assert client.get("/api/monitors", headers=AUDITOR).status_code == 200
    response = client.post(
        "/api/monitors", json={"kind": "github_repo", "target": "acme/bot"}, headers=AUDITOR
    )
    assert response.status_code == 403


def test_run_now_runs_through_the_job_queue(client, encryption_key, fake_github):
    _connection(encryption_key)
    fake_github.files = {"app/agent.py": GOVERNED}
    mid = client.post(
        "/api/monitors", json={"kind": "github_repo", "target": "acme/bot"}, headers=ADMIN
    ).json()["id"]
    body = client.post(f"/api/monitors/{mid}/run", headers=ADMIN).json()
    assert body["job"]["kind"] == "monitors.run" and body["job"]["status"] == "done"
    assert body["monitor"]["status"] == "baseline"
    fake_github.files = {"app/agent.py": GOVERNED, "bot/bot.py": SUPPORT_BOT}
    body = client.post(f"/api/monitors/{mid}/run", headers=ADMIN).json()
    assert body["monitor"]["status"] == "changed"
    detail = client.get(f"/api/monitors/{mid}", headers=ADMIN).json()
    assert snap.LETHAL_TRIFECTA in {f["type"] for f in detail["open_findings"]}


# ---------------------------------------------------------------------------
# GitHub push webhook
# ---------------------------------------------------------------------------


def _push(repo="acme/bot", branch="main", after="c0ffee", event="push"):
    body = json.dumps(
        {
            "ref": f"refs/heads/{branch}",
            "after": after,
            "repository": {"full_name": repo, "default_branch": "main"},
        }
    ).encode()
    return body, event


def _deliver(client, body, event, secret):
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if secret is not None:
        headers["X-Hub-Signature-256"] = gh.sign(secret, body)
    return client.post(HOOK, content=body, headers=headers)


@pytest.fixture
def monitored_repo(client, encryption_key, fake_github):
    conn_id = _connection(encryption_key)
    fake_github.files = {"app/agent.py": GOVERNED}
    mid = client.post(
        "/api/monitors",
        json={"kind": "github_repo", "target": "acme/bot", "config": {"connection_id": conn_id}},
        headers=ADMIN,
    ).json()["id"]
    return mid


def test_a_signed_push_to_the_default_branch_rescans_that_commit(
    client, monkeypatch, monitored_repo, fake_github
):
    monkeypatch.setattr(get_settings(), "github_webhook_secret", "whsec")
    body, event = _push()
    response = _deliver(client, body, event, "whsec")
    assert response.status_code == 202, response.text
    queued = response.json()["queued"]
    assert [q["monitor_id"] for q in queued] == [monitored_repo]
    # TestClient runs background tasks before returning: the rescan already ran.
    assert fake_github.requests[-1].url.path == "/repos/acme/bot/tarball/c0ffee"
    with session_scope() as s:
        job = s.get(Job, queued[0]["job_id"])
        assert job.status == "done" and job.payload_json["trigger"] == "push"
        assert s.get(Monitor, monitored_repo).last_result_json["ref"] == "c0ffee"


def test_a_badly_signed_or_unsigned_push_is_refused(client, monkeypatch, monitored_repo):
    monkeypatch.setattr(get_settings(), "github_webhook_secret", "whsec")
    body, event = _push()
    assert _deliver(client, body, event, "wrong").status_code == 401
    assert _deliver(client, body, event, None).status_code == 401
    with session_scope() as s:
        assert s.query(Job).filter(Job.kind == "monitors.run").count() == 0


def test_no_secret_configured_refuses_every_delivery(client, monitored_repo):
    body, event = _push()
    assert _deliver(client, body, event, "anything").status_code == 503


def test_pushes_elsewhere_and_other_events_queue_nothing(client, monkeypatch, monitored_repo):
    monkeypatch.setattr(get_settings(), "github_webhook_secret", "whsec")
    body, event = _push(branch="feature/x")
    response = _deliver(client, body, event, "whsec").json()
    assert response["queued"] == [] and "feature/x" in response["skipped"][0]["reason"]
    body, _ = _push()
    assert _deliver(client, body, "ping", "whsec").json()["event"] == "ping"
    assert _deliver(client, body, "issues", "whsec").json()["accepted"] is False
    body, event = _push(repo="acme/unmonitored")
    assert _deliver(client, body, event, "whsec").json()["queued"] == []


def test_a_connection_can_carry_its_own_webhook_secret(client, monitored_repo, fake_github):
    issued = client.post("/api/integrations/github/webhook-secret", headers=ADMIN)
    assert issued.status_code == 200, issued.text
    secret = issued.json()["secret"]
    with session_scope() as s:
        conn = s.scalar(select(GithubConnection))
        assert decrypt_secret(conn.webhook_secret_encrypted) == secret
        assert secret not in conn.webhook_secret_encrypted
    body, event = _push()
    assert _deliver(client, body, event, secret).status_code == 202
    assert _deliver(client, body, event, "someone-elses").status_code == 401


# ---------------------------------------------------------------------------
# Alerts: the finding webhook and Slack
# ---------------------------------------------------------------------------


def _changed_run(client, fake_github, mid):
    client.post(f"/api/monitors/{mid}/run", headers=ADMIN)  # baseline
    fake_github.files = {"app/agent.py": GOVERNED, "bot/bot.py": SUPPORT_BOT}
    return client.post(f"/api/monitors/{mid}/run", headers=ADMIN).json()


def test_monitor_findings_reach_slack_with_a_link(
    client, monkeypatch, monitored_repo, fake_github, slack
):
    monkeypatch.setattr(get_settings(), "allow_egress", True)
    monkeypatch.setattr(
        get_settings(), "slack_webhook_url", "https://hooks.slack.com/services/T/B/X"
    )
    monkeypatch.setattr(get_settings(), "slack_min_severity", "high")
    monkeypatch.setattr(get_settings(), "console_url", "https://console.example.com")
    _changed_run(client, fake_github, monitored_repo)
    assert alerts.wait_for_delivery(5)
    texts = [body["text"] for _url, body in slack]
    assert any("CRITICAL" in t and "lethal trifecta" in t for t in texts), texts
    assert all("/app/findings/fnd" in t or "/app/findings/" in t for t in texts)
    assert not any("new tool" in t for t in texts), "medium findings are below the bar"

    # Cleared: the closing message goes out too.
    slack.clear()
    fake_github.files = {"app/agent.py": GOVERNED}
    client.post(f"/api/monitors/{monitored_repo}/run", headers=ADMIN)
    assert alerts.wait_for_delivery(5)
    assert any("Cleared" in body["text"] for _url, body in slack)


def test_no_egress_means_no_slack(client, monkeypatch, monitored_repo, fake_github, slack):
    monkeypatch.setattr(
        get_settings(), "slack_webhook_url", "https://hooks.slack.com/services/T/B/X"
    )
    _changed_run(client, fake_github, monitored_repo)
    assert alerts.wait_for_delivery(5)
    assert slack == []


def test_monitor_findings_go_out_through_the_finding_webhook(
    client, monkeypatch, monitored_repo, fake_github
):
    from agentfox.core import webhooks

    sent = []
    monkeypatch.setattr(get_settings(), "allow_egress", True)
    monkeypatch.setattr(get_settings(), "webhook_url", "https://receiver.example.com/hook")
    monkeypatch.setattr(
        webhooks, "_deliver", lambda target, body: sent.append(body) or (True, "ok")
    )
    _changed_run(client, fake_github, monitored_repo)
    assert webhooks.wait_for_delivery(5)
    types = {b["finding"]["type"] for b in sent if b["event"] == "finding.created"}
    assert snap.LETHAL_TRIFECTA in types


def test_a_tenant_slack_channel_is_validated_encrypted_and_used(
    client, monkeypatch, encryption_key, monitored_repo, fake_github, slack
):
    bad = client.put("/api/alerts/slack", json={"url": "https://evil.example.com/x"}, headers=ADMIN)
    assert bad.status_code == 422
    url = "https://hooks.slack.com/services/T0/B0/tenant"
    ok = client.put(
        "/api/alerts/slack", json={"url": url, "min_severity": "critical"}, headers=ADMIN
    )
    assert ok.status_code == 200, ok.text
    with session_scope() as s:
        row = s.scalar(select(AlertChannel))
        assert url not in row.url_encrypted
    assert client.get("/api/alerts/slack", headers=ADMIN).json()["configured"] is True
    assert (
        client.put(
            "/api/alerts/slack", json={"url": url}, headers=as_user("priya@example.com")
        ).status_code
        == 403
    )

    monkeypatch.setattr(get_settings(), "allow_egress", True)
    _changed_run(client, fake_github, monitored_repo)
    assert alerts.wait_for_delivery(5)
    assert slack and all(u == url for u, _ in slack)
    assert all("CRITICAL" in b["text"] for _, b in slack)
    assert client.delete("/api/alerts/slack", headers=ADMIN).json()["configured"] is False


def test_slack_messages_for_rolled_back_work_are_never_sent(session, monkeypatch, slack):
    monkeypatch.setattr(get_settings(), "allow_egress", True)
    monkeypatch.setattr(
        get_settings(), "slack_webhook_url", "https://hooks.slack.com/services/T/B/X"
    )
    finding = Finding(type="monitor_new_tool", severity="high", title="x", subject_type="monitor")
    session.add(finding)
    session.flush()
    assert alerts.queue_finding_alert(session, finding, "finding.created") == 1
    session.rollback()
    session.commit()
    assert alerts.wait_for_delivery(5)
    assert slack == []
