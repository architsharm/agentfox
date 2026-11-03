"""Tool calls from Vapi, Retell and Copilot Studio, governed before they run.

Each platform's webhook is translated into `/v1/guard/tool_call`'s decision for the
agent its connection names, and answered in the platform's own format: a refusal the
agent says or a `blockAction`, or the call forwarded to the customer's tool server.
The negatives matter as much: a delivery without the platform's proof is refused, a
tool server on a private network cannot be registered, and a disabled connection is
indistinguishable from one that never existed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from agentfox.core.db import session_scope
from agentfox.platform.identity import ensure_identity, grant_capability
from agentfox.platform.registry import platform_connections as connections
from agentfox.platform.registry.service import register_agent, upsert_tool
from tests.conftest import as_user

AGENT = "voice-desk"
ADMIN = as_user("admin@example.com")
RETELL_KEY = "key_retell_test_123"
TENANT = "11111111-2222-3333-4444-555555555555"
APP = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture
def desk(client, monkeypatch):
    """An agent allowed to look an order up, and nothing else (default deny)."""
    from cryptography.fernet import Fernet

    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "token_encryption_key", Fernet.generate_key().decode())
    with session_scope() as s:
        agent = register_agent(s, slug=AGENT, name="Voice desk")
        upsert_tool(s, key="lookup_order", impact="read")
        grant_capability(s, ensure_identity(s, agent), "lookup_order", granted_by="test")
    return client


@pytest.fixture
def upstream(monkeypatch):
    """The customer's tool server: records what it was sent, answers what it is told."""
    seen: list[dict[str, Any]] = []
    answer: dict[str, Any] = {"status": 200, "json": {}}

    def fake(connection, body, headers):
        seen.append({"body": json.loads(body), "headers": headers, "url": connection.upstream_url})
        return httpx.Response(answer["status"], json=answer["json"])

    monkeypatch.setattr(connections, "forward", fake)
    return seen, answer


def _connect(client, platform: str, **body: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/agents/{AGENT}/platform-connections",
        json={"platform": platform, **body},
        headers=ADMIN,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- Registering a connection -------------------------------------------------


def test_a_vapi_connection_makes_its_secret_once_and_says_where_to_point_vapi(desk):
    made = _connect(desk, "vapi", upstream_url="https://tools.example.com/vapi")
    assert made["secret"].startswith("afv_")
    assert made["hook_url"].endswith(f"/v1/hooks/vapi/{made['id']}")
    listed = desk.get(f"/api/agents/{AGENT}/platform-connections", headers=ADMIN).json()
    assert [c["id"] for c in listed["connections"]] == [made["id"]]
    assert "secret" not in listed["connections"][0]  # shown once


def test_forwarding_platforms_need_a_tool_server_and_retell_needs_its_key(desk):
    for platform, body in (("vapi", {}), ("retell", {"upstream_url": "https://x.example.com"})):
        response = desk.post(
            f"/api/agents/{AGENT}/platform-connections",
            json={"platform": platform, **body},
            headers=ADMIN,
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://tools.example.com",  # not https
        "https://10.0.0.5/tools",  # a private network
        "https://169.254.169.254/latest/meta-data",  # cloud metadata
        "https://localhost:8080",
        "https://user:pass@tools.example.com",  # credentials in the URL
    ],
)
def test_a_tool_server_the_gateway_may_not_forward_to_is_refused(monkeypatch, url):
    monkeypatch.setattr(connections, "is_development", lambda: False)
    with pytest.raises(connections.ConnectionError_):
        connections.check_upstream(url)


def test_forwarding_rechecks_where_the_host_points_now(monkeypatch):
    monkeypatch.setattr(connections, "is_development", lambda: False)
    monkeypatch.setattr(connections, "_resolves_public", lambda host: False)

    class Row:
        upstream_url = "https://tools.example.com/hook"

    with pytest.raises(connections.ForwardFailed):
        connections.forward(Row(), b"{}", {})  # type: ignore[arg-type]


# --- Vapi ----------------------------------------------------------------------


def _vapi(calls: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call-1"},
            "toolCallList": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}
                for cid, name, args in calls
            ],
            "toolWithToolCallList": [
                {"type": "function", "toolCall": {"id": cid}} for cid, _, _ in calls
            ],
        }
    }


def test_vapi_blocks_one_call_and_forwards_the_other(desk, upstream):
    seen, answer = upstream
    made = _connect(desk, "vapi", upstream_url="https://tools.example.com/vapi")
    answer["json"] = {
        "results": [{"toolCallId": "c1", "name": "lookup_order", "result": "shipped"}]
    }
    response = desk.post(
        f"/v1/hooks/vapi/{made['id']}",
        json=_vapi([("c1", "lookup_order", {"id": "o1"}), ("c2", "issue_refund", {"amount": 900})]),
        headers={"Authorization": f"Bearer {made['secret']}"},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["toolCallId"] for r in results] == ["c1", "c2"]
    assert results[0]["result"] == "shipped"
    assert "not done" in results[1]["error"] and "\n" not in results[1]["error"]
    # Only the allowed call reached the tool server, in Vapi's own shape.
    sent = seen[0]["body"]["message"]
    assert [c["id"] for c in sent["toolCallList"]] == ["c1"]
    assert [t["toolCall"]["id"] for t in sent["toolWithToolCallList"]] == ["c1"]
    # With the credential Vapi sent, so the tool server's own check still passes.
    assert seen[0]["headers"]["authorization"] == f"Bearer {made['secret']}"


def test_vapi_can_reuse_the_token_the_tool_server_already_checks(desk, upstream):
    made = _connect(
        desk, "vapi", upstream_url="https://tools.example.com/vapi", secret="existing-token"
    )
    assert "secret" not in made  # nothing new to show
    upstream[1]["json"] = {"results": [{"toolCallId": "c1", "result": "ok"}]}
    response = desk.post(
        f"/v1/hooks/vapi/{made['id']}",
        json=_vapi([("c1", "lookup_order", {"id": "o1"})]),
        headers={"Authorization": "Bearer existing-token"},
    )
    assert response.json()["results"][0]["result"] == "ok"
    assert upstream[0][0]["headers"]["authorization"] == "Bearer existing-token"


def test_vapi_arguments_sent_as_a_json_string_are_read(desk, upstream):
    made = _connect(desk, "vapi", upstream_url="https://tools.example.com/vapi")
    upstream[1]["json"] = {"results": [{"toolCallId": "c1", "result": "ok"}]}
    body = _vapi([("c1", "lookup_order", {})])
    body["message"]["toolCallList"][0]["function"]["arguments"] = json.dumps({"id": "o1"})
    response = desk.post(
        f"/v1/hooks/vapi/{made['id']}", json=body, headers={"X-Vapi-Secret": made["secret"]}
    )
    assert response.json()["results"][0]["result"] == "ok"


def test_vapi_without_the_secret_is_refused_and_other_messages_are_acknowledged(desk, upstream):
    made = _connect(desk, "vapi", upstream_url="https://tools.example.com/vapi")
    hook = f"/v1/hooks/vapi/{made['id']}"
    assert desk.post(hook, json=_vapi([("c1", "lookup_order", {})])).status_code == 401
    wrong = {"Authorization": "Bearer afv_wrong"}
    assert desk.post(hook, json=_vapi([]), headers=wrong).status_code == 401
    status = desk.post(
        hook,
        json={"message": {"type": "status-update"}},
        headers={"Authorization": f"Bearer {made['secret']}"},
    )
    assert status.json() == {} and upstream[0] == []


def test_an_unreachable_tool_server_is_a_refusal_the_agent_can_speak(desk, monkeypatch):
    def down(connection, body, headers):
        raise connections.ForwardFailed("the tool server did not answer")

    monkeypatch.setattr(connections, "forward", down)
    made = _connect(desk, "vapi", upstream_url="https://tools.example.com/vapi")
    response = desk.post(
        f"/v1/hooks/vapi/{made['id']}",
        json=_vapi([("c1", "lookup_order", {"id": "o1"})]),
        headers={"Authorization": f"Bearer {made['secret']}"},
    )
    assert response.status_code == 200  # Vapi ignores anything else
    assert "could not be reached" in response.json()["results"][0]["error"]


def test_a_disabled_connection_is_the_same_404_as_an_unknown_one(desk, upstream):
    made = _connect(desk, "vapi", upstream_url="https://tools.example.com/vapi")
    desk.delete(f"/api/agents/{AGENT}/platform-connections/{made['id']}", headers=ADMIN)
    auth = {"Authorization": f"Bearer {made['secret']}"}
    gone = desk.post(f"/v1/hooks/vapi/{made['id']}", json=_vapi([]), headers=auth)
    unknown = desk.post("/v1/hooks/vapi/plc_nope", json=_vapi([]), headers=auth)
    assert gone.status_code == unknown.status_code == 404
    assert gone.json() == unknown.json()


# --- Retell --------------------------------------------------------------------


def _sign(body: bytes, key: str = RETELL_KEY, at_ms: int | None = None) -> str:
    stamp = str(at_ms if at_ms is not None else int(time.time() * 1000))
    digest = hmac.new(key.encode(), body + stamp.encode(), hashlib.sha256).hexdigest()
    return f"v={stamp},d={digest}"


def _retell_body(name: str, args: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "name": name,
            "args": args,
            "call": {
                "call_id": "rc-1",
                "transcript_object": [{"role": "user", "content": "refund order o1 please"}],
            },
        }
    ).encode()


def test_retell_refuses_with_a_sentence_and_forwards_with_its_own_signature(desk, upstream):
    seen, answer = upstream
    made = _connect(
        desk, "retell", upstream_url="https://tools.example.com/retell", secret=RETELL_KEY
    )
    hook = f"/v1/hooks/retell/{made['id']}"

    blocked = _retell_body("issue_refund", {"order_id": "o1"})
    response = desk.post(hook, content=blocked, headers={"X-Retell-Signature": _sign(blocked)})
    assert response.status_code == 200 and "not done" in response.json()["result"]
    assert seen == []

    answer["json"] = {"result": "order o1 shipped"}
    allowed = _retell_body("lookup_order", {"order_id": "o1"})
    signature = _sign(allowed)
    response = desk.post(hook, content=allowed, headers={"X-Retell-Signature": signature})
    assert response.json() == {"result": "order o1 shipped"}
    assert seen[0]["headers"]["x-retell-signature"] == signature  # the server can verify it


def test_retell_args_only_payloads_take_the_function_from_the_url(desk, upstream):
    made = _connect(
        desk, "retell", upstream_url="https://tools.example.com/retell", secret=RETELL_KEY
    )
    body = json.dumps({"amount": 900}).encode()
    response = desk.post(
        f"/v1/hooks/retell/{made['id']}?tool=issue_refund",
        content=body,
        headers={"X-Retell-Signature": _sign(body)},
    )
    assert "not done" in response.json()["result"]


@pytest.mark.parametrize(
    "case",
    ["missing", "malformed", "another body", "another key", "ten minutes old"],
)
def test_retell_deliveries_that_do_not_verify_are_refused(desk, upstream, case):
    # Built here, not in the parametrize list: a signature carries the time it was
    # made, and every test worker must collect the same test ids.
    body = _retell_body("lookup_order", {})
    signature = {
        "missing": None,
        "malformed": "v=1,d=deadbeef",
        "another body": _sign(b"other body"),
        "another key": _sign(body, key="someone_elses_key"),
        "ten minutes old": _sign(body, at_ms=int(time.time() * 1000) - 10 * 60 * 1000),
    }[case]
    made = _connect(
        desk, "retell", upstream_url="https://tools.example.com/retell", secret=RETELL_KEY
    )
    headers = {"X-Retell-Signature": signature} if signature else {}
    response = desk.post(
        f"/v1/hooks/retell/{made['id']}",
        content=_retell_body("lookup_order", {}),
        headers=headers,
    )
    assert response.status_code == 401
    assert upstream[0] == []


# --- Copilot Studio ------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture
def entra(monkeypatch):
    """A signing key published as the tenant's JWKS, and a way to mint tokens with it."""
    from agentfox.platform.identity import entra as module

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "k1",
                "n": _b64(numbers.n.to_bytes(256, "big")),
                "e": _b64(numbers.e.to_bytes(3, "big")),
            }
        ]
    }
    module._cache.clear()
    monkeypatch.setattr(module, "fetch_keys", lambda tenant: jwks)

    def mint(**claims: Any) -> str:
        now = int(time.time())
        body = {
            "aud": "http://testserver",
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "tid": TENANT,
            "azp": APP,
            "exp": now + 600,
            "nbf": now - 10,
            **claims,
        }
        head = _b64(json.dumps({"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode())
        payload = _b64(json.dumps(body).encode())
        signature = key.sign(f"{head}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{head}.{payload}.{_b64(signature)}"

    assert key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return mint


def _copilot(tool: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "plannerContext": {"userMessage": "help me", "chatHistory": []},
        "toolDefinition": {"id": "t1", "type": "PrebuiltToolDefinition", "name": tool},
        "inputValues": inputs,
        "conversationMetadata": {
            "agent": {"id": "a", "tenantId": TENANT, "environmentId": "e", "isPublished": True},
            "conversationId": "conv-1",
        },
    }


def test_copilot_studio_validates_and_decides_each_planned_tool(desk, entra):
    made = _connect(desk, "copilot_studio", config={"tenant_id": TENANT, "app_id": APP})
    base = f"/v1/hooks/copilot-studio/{made['id']}"
    auth = {"Authorization": f"Bearer {entra()}"}
    ok = desk.post(f"{base}/validate?api-version=2025-05-01", headers=auth)
    assert ok.json() == {"isSuccessful": True, "status": "OK"}

    allowed = desk.post(
        f"{base}/analyze-tool-execution?api-version=2025-05-01",
        json=_copilot("lookup_order", {"id": "o1"}),
        headers=auth,
    )
    assert allowed.json() == {"blockAction": False}

    blocked = desk.post(
        f"{base}/analyze-tool-execution?api-version=2025-05-01",
        json=_copilot("issue_refund", {"amount": 900}),
        headers=auth,
    ).json()
    assert blocked["blockAction"] is True and blocked["reasonCode"] == 100
    assert isinstance(blocked["diagnostics"], str)  # pre-serialised, as Copilot wants


@pytest.mark.parametrize(
    "claims",
    [
        {"azp": "99999999-0000-0000-0000-000000000000"},  # another app in the tenant
        {"tid": "99999999-0000-0000-0000-000000000000"},  # another tenant
        {"aud": "https://elsewhere.example.com"},
        {"exp": "an hour ago"},  # made into a timestamp in the test (stable test ids)
    ],
)
def test_copilot_studio_refuses_a_token_that_is_not_the_configured_apps(desk, entra, claims):
    if claims.get("exp") == "an hour ago":
        claims = {"exp": int(time.time()) - 3600}
    made = _connect(desk, "copilot_studio", config={"tenant_id": TENANT, "app_id": APP})
    response = desk.post(
        f"/v1/hooks/copilot-studio/{made['id']}/analyze-tool-execution",
        json=_copilot("lookup_order", {}),
        headers={"Authorization": f"Bearer {entra(**claims)}"},
    )
    assert response.status_code == 401
    assert response.json()["errorCode"] == 2003


def test_copilot_studio_refuses_a_forged_signature(desk, entra):
    made = _connect(desk, "copilot_studio", config={"tenant_id": TENANT, "app_id": APP})
    head, body, _sig = entra().split(".")
    forged = f"{head}.{body}.{_b64(b'x' * 256)}"
    response = desk.post(
        f"/v1/hooks/copilot-studio/{made['id']}/validate",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert response.status_code == 401


def test_copilot_studio_needs_its_tenant_and_app(desk):
    response = desk.post(
        f"/api/agents/{AGENT}/platform-connections",
        json={"platform": "copilot_studio", "config": {"tenant_id": TENANT}},
        headers=ADMIN,
    )
    assert response.status_code == 422 and "app_id" in response.json()["detail"]
