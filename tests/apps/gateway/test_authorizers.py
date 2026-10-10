"""The workspace's own access check: asked before a tool call, with the end user."""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from agentfox.core import outbound
from agentfox.core.config import get_settings
from agentfox.platform.identity import authorizer as authz
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
AGENT = "support-triage"
TOOL = "crm.lookup"
SMALL = {"customer_id": "c_42"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    authz.clear_cache()
    yield
    authz.clear_cache()


def _serve(monkeypatch, handler, address="10.0.0.7"):
    calls: list[dict] = []

    def wrapped(request: httpx.Request):
        calls.append(json.loads(request.content))
        return handler(request)

    monkeypatch.setattr(outbound, "_TRANSPORT", httpx.MockTransport(wrapped))
    monkeypatch.setattr(
        outbound,
        "_getaddrinfo",
        lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))],
    )
    monkeypatch.setattr(get_settings(), "outbound_allow_private_hosts", True)
    return calls


def _register(client, **over):
    body = {
        "key": "corp-rbac",
        "name": "Corporate RBAC",
        "url": "http://rbac.internal/check",
        "tools": ["crm.*"],
        **over,
    }
    resp = client.post("/api/authorizers", json=body, headers=ADMIN)
    assert resp.status_code == 201, resp.text
    return resp.json()["authorizer"]


def _call(client, principal=None, arguments=None):
    return client.post(
        "/v1/guard/tool_call",
        json={
            "agent": AGENT,
            "tool": TOOL,
            "arguments": arguments or SMALL,
            **({"principal": principal} if principal is not None else {}),
        },
    ).json()


def _allow_only(subject):
    def handler(request):
        body = json.loads(request.content)
        allowed = body["input"]["subject"] == subject
        return httpx.Response(200, json={"allow": allowed, "reason": "not in support"})

    return handler


def test_the_end_user_is_asked_about_and_a_deny_blocks(client, monkeypatch):
    calls = _serve(monkeypatch, _allow_only("u_agent"))
    _register(client)
    assert _call(client, "u_agent")["verdict"] == "allow"
    denied = _call(client, {"subject": "u_intern", "groups": ["support"]})
    assert denied["verdict"] == "block"
    rule = next(r for r in denied["rules_fired"] if r["rule_id"] == "authz.corp-rbac.deny")
    assert "not in support" in rule["reason"]
    sent = calls[-1]
    assert sent["input"]["tool"] == TOOL and sent["input"]["groups"] == ["support"]
    assert sent["subject"] == "u_intern", "the top-level copy is there for plain endpoints"
    assert sent["input"]["arguments"] == SMALL


def test_a_deny_can_go_to_a_person_instead(client, monkeypatch):
    _serve(monkeypatch, lambda r: httpx.Response(200, json={"decision": "Deny"}))
    _register(client, on_deny="escalate")
    assert _call(client, "u_intern")["verdict"] == "escalate"


@pytest.mark.parametrize(
    "answer, allowed",
    [
        ({"result": True}, True),
        ({"result": {"allow": False}}, False),
        ({"decision": "permit"}, True),
        ({"allowed": False}, False),
    ],
)
def test_opa_and_cedar_shaped_answers_are_understood(client, monkeypatch, answer, allowed):
    _serve(monkeypatch, lambda r: httpx.Response(200, json=answer))
    _register(client)
    assert (_call(client, "u_1")["verdict"] == "allow") is allowed


def test_an_outage_fails_closed_by_default_and_open_when_asked(client, monkeypatch):
    _serve(monkeypatch, lambda r: httpx.Response(503))
    _register(client)
    closed = _call(client, "u_1")
    assert closed["verdict"] == "block"
    assert any(r["rule_id"] == "authz.corp-rbac.unavailable" for r in closed["rules_fired"])
    listed = client.get("/api/authorizers").json()["authorizers"][0]
    assert listed["last_error"]

    _register(client, fail_mode="open")
    assert _call(client, "u_2")["verdict"] == "allow"


def test_no_end_user_skips_it_unless_one_is_required(client, monkeypatch):
    calls = _serve(monkeypatch, lambda r: httpx.Response(200, json={"allow": False}))
    _register(client)
    assert _call(client)["verdict"] == "allow" and calls == []
    _register(client, require_principal=True)
    refused = _call(client)
    assert refused["verdict"] == "block" and calls == []


def test_answers_are_cached_per_user_and_arguments(client, monkeypatch):
    calls = _serve(monkeypatch, lambda r: httpx.Response(200, json={"allow": True}))
    _register(client, cache_seconds=60)
    _call(client, "u_1")
    _call(client, "u_1")
    assert len(calls) == 1
    _call(client, "u_2")
    _call(client, "u_1", {"customer_id": "c_43"})
    assert len(calls) == 3


def test_only_matching_tools_and_agents_are_asked(client, monkeypatch):
    calls = _serve(monkeypatch, lambda r: httpx.Response(200, json={"allow": False}))
    _register(client, tools=["payments.*"])
    assert _call(client, "u_1")["verdict"] == "allow" and calls == []
    _register(client, tools=["*"], agents=["some-other-agent"])
    assert _call(client, "u_1")["verdict"] == "allow" and calls == []


def test_a_registered_principals_groups_are_sent(client, monkeypatch):
    from agentfox.capabilities.grounding.entitlement import upsert_principal
    from agentfox.core.db import session_scope

    calls = _serve(monkeypatch, lambda r: httpx.Response(200, json={"allow": True}))
    with session_scope() as s:
        upsert_principal(s, subject="u_9", groups=["finance", "emea"])
    _register(client)
    _call(client, "u_9")
    assert calls[-1]["input"]["groups"] == ["finance", "emea"]


def test_managing_and_testing_one(client, monkeypatch):
    _serve(monkeypatch, lambda r: httpx.Response(200, json={"allow": True, "reason": "ok"}))
    monkeypatch.setattr(get_settings(), "token_encryption_key", _key())
    row = _register(client, auth_header="Authorization", auth_secret="Bearer s3cret")
    assert row["has_secret"] is True and "auth_secret" not in row
    tested = client.post(
        "/api/authorizers/corp-rbac/test",
        json={"subject": "u_1", "tool": TOOL},
        headers=ADMIN,
    ).json()
    assert tested == {"ok": True, "allowed": True, "reason": "ok"}
    off = client.post("/api/authorizers/corp-rbac/enabled", json={"enabled": False}, headers=ADMIN)
    assert off.json()["authorizer"]["enabled"] is False
    assert client.delete("/api/authorizers/corp-rbac", headers=ADMIN).status_code == 200
    assert client.get("/api/authorizers").json()["authorizers"] == []


def test_a_public_endpoint_needs_egress(client, monkeypatch):
    _serve(monkeypatch, lambda r: httpx.Response(200, json={}), address="93.184.216.34")
    monkeypatch.setattr(get_settings(), "allow_egress", False)
    resp = client.post(
        "/api/authorizers",
        json={"key": "pub", "name": "Pub", "url": "https://rbac.example.com/check"},
        headers=ADMIN,
    )
    assert resp.status_code == 409 and "egress" in resp.json()["detail"]


def _key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def test_a_call_already_refused_is_not_sent_out(client, monkeypatch):
    calls = _serve(monkeypatch, lambda r: httpx.Response(200, json={"allow": True}))
    _register(client, tools=["*"])
    refused = client.post(
        "/v1/guard/tool_call",
        json={
            "agent": "payments-ops",
            "tool": "payments.transfer",
            "arguments": {"amount": 25000, "currency": "USD", "to": "acct_x"},
            "principal": "u_1",
        },
    ).json()
    assert refused["verdict"] == "block" and calls == [], "its arguments never left"
