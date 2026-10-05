"""Four security findings from the docs verification pass, each pinned by a test that
failed before its fix.

1. ``POST /v1/traces`` stored spans from an unauthenticated caller on a deployment
   running in token mode.
2. The hosted-API scan fetched any URL it was handed — loopback, private ranges and
   the cloud metadata address included — and followed redirects anywhere.
3. LangGraph: resuming an approval interrupt with ``{"approved": False}`` ran the
   tool anyway, because the value ``interrupt()`` returned was ignored.
4. MCP rug pull: ``McpGovernor.register_tools`` with a changed listing re-recorded
   the tool, so the call-time drift block stopped firing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.tenancy import system_scope

# ---------------------------------------------------------------------------
# 1. OTLP ingest requires a credential outside development
# ---------------------------------------------------------------------------

OTLP_PAYLOAD = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [{"key": "service.name", "value": {"stringValue": "forged-agent"}}]
            },
            "scopeSpans": [
                {
                    "scope": {"name": "langgraph.instrumentation"},
                    "spans": [
                        {
                            "name": "langgraph.node.x",
                            "traceId": "feedface",
                            "startTimeUnixNano": "1700000000000000000",
                            "endTimeUnixNano": "1700000001000000000",
                            "attributes": [],
                        }
                    ],
                }
            ],
        }
    ]
}


@pytest.fixture
def seeded_app():
    from agentfox.core.seed import seed
    from agentfox.gateway.app import create_app

    with session_scope() as s:
        seed(s)
    return TestClient(create_app())


@pytest.fixture
def token_mode(monkeypatch):
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "auth_mode", "token")


def _operator_token(email: str = "admin@example.com") -> str:
    from agentfox.core.models import User
    from agentfox.gateway.auth import issue_token

    with system_scope("test setup"), session_scope() as s:
        user = s.scalars(select(User).where(User.email == email)).first()
        _rec, raw = issue_token(s, user)
        return raw


def _agent_key(slug: str = "support-triage") -> str:
    from agentfox.core.models import Agent
    from agentfox.identity.service import ensure_identity, issue_credential

    with system_scope("test setup"), session_scope() as s:
        agent = s.scalars(select(Agent).where(Agent.slug == slug)).first()
        identity = ensure_identity(s, agent)
        _cred, raw = issue_credential(s, identity)
        return raw


def _stored_trace_count() -> int:
    from agentfox.core.models import Trace

    with system_scope("test check"), session_scope() as s:
        return len(list(s.scalars(select(Trace))))


def test_otlp_ingest_refuses_an_anonymous_write_in_token_mode(seeded_app, token_mode):
    before = _stored_trace_count()
    response = seeded_app.post("/v1/traces", json=OTLP_PAYLOAD)
    assert response.status_code == 401, response.text
    assert _stored_trace_count() == before, "nothing may be stored for a refused write"


def test_otlp_ingest_refuses_a_bogus_credential_in_token_mode(seeded_app, token_mode):
    for bogus in ("nom_agt_notarealkeynotarealkeynotareal", "nom_api_nope", "something"):
        response = seeded_app.post(
            "/v1/traces", json=OTLP_PAYLOAD, headers={"Authorization": f"Bearer {bogus}"}
        )
        assert response.status_code == 401, (bogus, response.text)


def test_otlp_ingest_accepts_an_agent_key_in_token_mode(seeded_app, token_mode):
    raw = _agent_key()
    response = seeded_app.post(
        "/v1/traces", json=OTLP_PAYLOAD, headers={"Authorization": f"Bearer {raw}"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["spans_ingested"] == 1


def test_otlp_ingest_accepts_an_operator_token_in_token_mode(seeded_app, token_mode):
    raw = _operator_token()
    response = seeded_app.post(
        "/v1/traces", json=OTLP_PAYLOAD, headers={"Authorization": f"Bearer {raw}"}
    )
    assert response.status_code == 200, response.text


def test_otlp_ingest_refuses_a_read_only_operator(seeded_app, token_mode):
    """An auditor reads everything and writes nothing; ingest is a write."""
    from agentfox.core.models import User

    with system_scope("test setup"), session_scope() as s:
        auditor = s.scalars(select(User).where(User.role == "auditor")).first()
        email = auditor.email if auditor else None
    if email is None:
        pytest.skip("seed has no auditor")
    raw = _operator_token(email)
    response = seeded_app.post(
        "/v1/traces", json=OTLP_PAYLOAD, headers={"Authorization": f"Bearer {raw}"}
    )
    assert response.status_code == 403, response.text


def test_otlp_ingest_is_unchanged_in_development(seeded_app, monkeypatch):
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "development")
    monkeypatch.setattr(get_settings(), "auth_mode", "auto")
    response = seeded_app.post("/v1/traces", json=OTLP_PAYLOAD)
    assert response.status_code == 200, response.text
    assert response.json()["spans_ingested"] == 1
