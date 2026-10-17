"""Outbound finding webhooks: sent after commit, never for rolled-back work,
never with egress off, and never raising into the committing code."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentfox.core import webhooks
from agentfox.core.config import Settings, reset_settings_cache
from agentfox.core.db import get_sessionmaker, session_scope
from agentfox.core.models import Finding

SECRET = "whsec-test"


class _Recorder(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        server = self.server
        server.received.append({"headers": dict(self.headers), "raw": raw})
        if server.delay:
            time.sleep(server.delay)
        code = server.codes.pop(0) if server.codes else 200
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def receiver():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    server.received = []
    server.codes = []
    server.delay = 0.0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.url = f"http://127.0.0.1:{server.server_address[1]}/hooks/agentfox"
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def _drain(monkeypatch):
    monkeypatch.setattr(webhooks, "_RETRY_BACKOFF_SECONDS", 0.01)
    webhooks.reset_webhook_state()
    yield
    assert webhooks.wait_for_delivery(10)
    webhooks.reset_webhook_state()


def configure(monkeypatch, url, *, egress=True, secret=SECRET, min_severity=None):
    monkeypatch.setenv("AGENTFOX_ALLOW_EGRESS", "true" if egress else "false")
    monkeypatch.setenv("AGENTFOX_WEBHOOK_URL", url)
    monkeypatch.setenv("AGENTFOX_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("AGENTFOX_WEBHOOK_TIMEOUT_SECONDS", "1")
    if min_severity:
        monkeypatch.setenv("AGENTFOX_WEBHOOK_MIN_SEVERITY", min_severity)
    reset_settings_cache()


def make_finding(severity="high", title="Prompt injection reached a tool call"):
    return Finding(
        type="enforcement.block",
        severity=severity,
        title=title,
        subject_type="agent",
        subject_id="agent_support",
        evidence_json={"detector": "injection.heuristic"},
        control_keys=["NOM-RTG-01"],
    )


def test_committed_high_finding_is_delivered_once_and_signed(monkeypatch, receiver):
    configure(monkeypatch, receiver.url)
    with session_scope() as s:
        finding = make_finding()
        s.add(finding)
    assert webhooks.wait_for_delivery(5)

    assert len(receiver.received) == 1
    request = receiver.received[0]
    headers = {k.lower(): v for k, v in request["headers"].items()}
    body = json.loads(request["raw"])

    assert body["event"] == "finding.created"
    assert body["org_id"] == "org_default"
    assert body["sent_at"]
    assert body["finding"]["id"] == finding.id
    assert body["finding"]["severity"] == "high"
    assert body["finding"]["title"] == "Prompt injection reached a tool call"
    assert body["finding"]["controls"] == ["NOM-RTG-01"]
    assert body["finding"]["evidence"] == {"detector": "injection.heuristic"}

    assert headers["content-type"] == "application/json"
    assert headers["user-agent"].startswith("agentfox/")
    assert headers["x-agentfox-timestamp"].isdigit()
    expected = hmac.new(SECRET.encode(), request["raw"], hashlib.sha256).hexdigest()
    assert headers["x-agentfox-signature"] == f"sha256={expected}"


def test_below_threshold_is_not_sent(monkeypatch, receiver):
    configure(monkeypatch, receiver.url)
    with session_scope() as s:
        s.add(make_finding(severity="low"))
        s.add(make_finding(severity="medium"))
        s.add(make_finding(severity="critical", title="the one"))
    assert webhooks.wait_for_delivery(5)
    assert [json.loads(r["raw"])["finding"]["title"] for r in receiver.received] == ["the one"]


def test_min_severity_is_configurable(monkeypatch, receiver):
    configure(monkeypatch, receiver.url, min_severity="LOW")
    with session_scope() as s:
        s.add(make_finding(severity="low"))
    assert webhooks.wait_for_delivery(5)
    assert len(receiver.received) == 1


def test_invalid_min_severity_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENTFOX_WEBHOOK_MIN_SEVERITY", "urgent")
    with pytest.raises(Exception, match="webhook_min_severity"):
        Settings()


def test_rolled_back_finding_is_not_sent(monkeypatch, receiver):
    configure(monkeypatch, receiver.url)
    s = get_sessionmaker()()
    s.add(make_finding())
    s.flush()
    s.rollback()
    s.close()

    with pytest.raises(RuntimeError):
        with session_scope() as s2:
            s2.add(make_finding())
            s2.flush()
            raise RuntimeError("request failed after the finding was flushed")

    assert webhooks.wait_for_delivery(5)
    assert receiver.received == []


def test_savepoint_rollback_drops_only_its_own_findings(monkeypatch, receiver):
    configure(monkeypatch, receiver.url)
    with session_scope() as s:
        s.add(make_finding(title="kept"))
        s.flush()
        nested = s.begin_nested()
        s.add(make_finding(title="rolled back"))
        s.flush()
        nested.rollback()
    assert webhooks.wait_for_delivery(5)
    assert [json.loads(r["raw"])["finding"]["title"] for r in receiver.received] == ["kept"]


def test_egress_disabled_sends_nothing(monkeypatch, receiver, caplog):
    configure(monkeypatch, receiver.url, egress=False)
    with caplog.at_level(logging.INFO, logger="agentfox.core.webhooks"):
        for _ in range(2):
            with session_scope() as s:
                s.add(make_finding(severity="critical"))
    assert webhooks.wait_for_delivery(5)
    assert receiver.received == []
    notices = [r for r in caplog.records if "egress is disabled" in r.getMessage()]
    assert len(notices) == 1 and notices[0].levelno == logging.INFO
    assert webhooks.send_test_event()[0] is False


def test_unreachable_url_never_raises_into_the_caller(monkeypatch, caplog):
    with socket.socket() as sock:  # a port nothing is listening on
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    configure(monkeypatch, f"http://127.0.0.1:{port}/hook")
    with caplog.at_level(logging.WARNING, logger="agentfox.core.webhooks"):
        with session_scope() as s:
            s.add(make_finding())
        assert webhooks.wait_for_delivery(10)
    assert "delivery of finding.created" in caplog.text
    assert "/hook" not in caplog.text  # only scheme://host is logged


def test_5xx_is_retried_once_with_the_same_delivery(monkeypatch, receiver):
    configure(monkeypatch, receiver.url)
    receiver.codes = [503, 200]
    with session_scope() as s:
        s.add(make_finding())
    assert webhooks.wait_for_delivery(5)
    assert len(receiver.received) == 2
    first, second = ({k.lower(): v for k, v in r["headers"].items()} for r in receiver.received)
    assert first["x-agentfox-delivery"] == second["x-agentfox-delivery"]
    assert receiver.received[0]["raw"] == receiver.received[1]["raw"]


def test_commit_does_not_wait_on_the_network(monkeypatch, receiver):
    configure(monkeypatch, receiver.url)
    receiver.delay = 0.6  # slow receiver, but inside the 1s webhook timeout
    started = time.monotonic()
    with session_scope() as s:
        s.add(make_finding())
    assert time.monotonic() - started < 0.3
    assert webhooks.wait_for_delivery(5)
    assert len(receiver.received) == 1


def test_no_url_configured_sends_nothing(monkeypatch, receiver):
    monkeypatch.setenv("AGENTFOX_ALLOW_EGRESS", "true")
    monkeypatch.delenv("AGENTFOX_WEBHOOK_URL", raising=False)
    reset_settings_cache()
    with session_scope() as s:
        s.add(make_finding(severity="critical"))
    assert webhooks.wait_for_delivery(5)
    assert receiver.received == []
    ok, detail = webhooks.send_test_event()
    assert not ok and "webhook_url" in detail


def test_send_test_event(monkeypatch, receiver):
    configure(monkeypatch, receiver.url)
    ok, detail = webhooks.send_test_event()
    assert ok, detail
    body = json.loads(receiver.received[0]["raw"])
    assert body["event"] == "webhook.test"


def test_listener_install_is_idempotent():
    factory = get_sessionmaker()
    assert webhooks.install(factory) is factory
    assert webhooks.install(factory) is factory
