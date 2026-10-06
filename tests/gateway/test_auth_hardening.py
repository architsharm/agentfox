"""Authentication hardening — each test failed before its fix.

* #53/X0  A production gateway on the published service secret let anyone call the
          GitHub provisioning route and mint an owner token.
* #21     An invalid or revoked ``nom_agt_`` key was accepted and the call
          attributed to whichever agent the body named.
* #72     Sign Out left the session token valid; every sign-in added another one.
* #22     The token-mode 401 blamed 'development' when auth_mode was the reason.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agentfox.core.config import (
    DEFAULT_AUDIT_SIGNING_KEY,
    DEFAULT_SERVICE_AUTH_SECRET,
    InsecureConfigurationError,
    get_settings,
    insecure_production_secrets,
)
from agentfox.core.db import session_scope
from agentfox.core.models import Agent, ApiToken, User
from agentfox.core.tenancy import system_scope
from agentfox.gateway.app import create_app

SECRET = "test-service-secret"  # what tests/conftest.py sets


@pytest.fixture
def ready(isolated_db):
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)
    yield


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "auth_mode", "auto")


def _app() -> TestClient:
    return TestClient(create_app())


def _provision(client: TestClient, gh_id: str = "4242", email: str = "dev@corp.example", **kw):
    return client.post(
        "/api/auth/github/provision",
        headers={"X-Nometria-Service-Secret": kw.pop("secret", SECRET)},
        json={"github_user_id": gh_id, "github_login": "dev", "email": email, **kw},
    )


# ---------------------------------------------------------------------------
# X0 / #53 — published secrets in production
# ---------------------------------------------------------------------------


def test_production_refuses_to_start_on_the_published_service_secret(production, monkeypatch):
    monkeypatch.setattr(get_settings(), "service_auth_secret", DEFAULT_SERVICE_AUTH_SECRET)
    with pytest.raises(InsecureConfigurationError, match="AGENTFOX_SERVICE_AUTH_SECRET"):
        create_app()


def test_production_refuses_to_start_on_the_published_signing_key(production, monkeypatch):
    monkeypatch.setattr(get_settings(), "audit_signing_key", DEFAULT_AUDIT_SIGNING_KEY)
    with pytest.raises(InsecureConfigurationError, match="AGENTFOX_AUDIT_SIGNING_KEY"):
        create_app()


def test_compose_placeholder_counts_as_published(production, monkeypatch):
    monkeypatch.setattr(get_settings(), "audit_signing_key", "change-me-before-any-real-deployment")
    assert insecure_production_secrets()


def test_development_keeps_the_defaults_as_a_convenience(monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "development")
    monkeypatch.setattr(get_settings(), "service_auth_secret", DEFAULT_SERVICE_AUTH_SECRET)
    monkeypatch.setattr(get_settings(), "audit_signing_key", DEFAULT_AUDIT_SIGNING_KEY)
    assert insecure_production_secrets() == []
    _app()  # does not raise


def test_an_unrecognised_environment_is_production(monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "prodution")  # a typo
    monkeypatch.setattr(get_settings(), "service_auth_secret", DEFAULT_SERVICE_AUTH_SECRET)
    assert insecure_production_secrets()


def test_cli_imports_of_the_gateway_do_not_trip_the_startup_guard(production, monkeypatch):
    """`agentfox admin auth issue` imports gateway.auth; only *serving* refuses."""
    import importlib
    import sys

    monkeypatch.setattr(get_settings(), "service_auth_secret", DEFAULT_SERVICE_AUTH_SECRET)
    for name in [m for m in sys.modules if m == "agentfox.gateway" or m == "agentfox.gateway.auth"]:
        monkeypatch.delitem(sys.modules, name)
    importlib.import_module("agentfox.gateway.auth")


def test_provision_refuses_the_published_secret_even_past_startup(ready, production, monkeypatch):
    """The exact takeover: the default secret, sent by anyone, minted an owner token."""
    client = _app()
    monkeypatch.setattr(get_settings(), "service_auth_secret", DEFAULT_SERVICE_AUTH_SECRET)
    response = _provision(client, secret=DEFAULT_SERVICE_AUTH_SECRET)
    assert response.status_code == 503, response.text
    assert "token" not in response.json()


def test_provision_refuses_a_wrong_secret(ready, production):
    response = _provision(_app(), secret="guess")
    assert response.status_code == 401


def test_provision_finds_the_same_user_only_by_github_id(ready, production):
    client = _app()
    first = _provision(client, gh_id="111", email="shared@corp.example").json()
    again = _provision(client, gh_id="111", email="shared@corp.example").json()
    assert again["user"]["id"] == first["user"]["id"]
    # Another GitHub account reporting the same email is not that user.
    other = _provision(client, gh_id="222", email="shared@corp.example").json()
    assert other["user"]["id"] != first["user"]["id"]
    assert other["user"]["org_id"] != first["user"]["org_id"]


def test_provision_refuses_a_deactivated_user(ready, production):
    client = _app()
    user_id = _provision(client, gh_id="333").json()["user"]["id"]
    with system_scope("test"), session_scope() as s:
        s.get(User, user_id).active = False
    assert _provision(client, gh_id="333").status_code == 403


# ---------------------------------------------------------------------------
# #72 — sign out revokes; sign-in does not accumulate tokens
# ---------------------------------------------------------------------------


def test_logout_revokes_the_session_token(ready, production):
    client = _app()
    token = _provision(client).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/me", headers=auth).status_code == 200
    assert client.post("/api/auth/logout", headers=auth).json() == {"revoked": True}
    assert client.get("/api/me", headers=auth).status_code == 401
    # Idempotent: signing out twice is not an error.
    assert client.post("/api/auth/logout", headers=auth).json() == {"revoked": False}
    assert client.post("/api/auth/logout").json() == {"revoked": False}


def test_logout_revokes_only_the_presented_token(ready, production):
    client = _app()
    a = _provision(client, gh_id="555").json()["token"]
    b = _provision(client, gh_id="555").json()["token"]
    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {a}"})
    assert client.get("/api/me", headers={"Authorization": f"Bearer {b}"}).status_code == 200


def test_sign_in_keeps_a_bounded_number_of_login_tokens(ready, production):
    from agentfox.gateway.routes.integrations import MAX_LOGIN_SESSIONS

    client = _app()
    tokens = [
        _provision(client, gh_id="777").json()["token"] for _ in range(MAX_LOGIN_SESSIONS + 3)
    ]
    with system_scope("test"), session_scope() as s:
        user = s.scalar(select(User).where(User.external_id == "777"))
        live = s.scalars(
            select(ApiToken).where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
        ).all()
    assert len(live) == MAX_LOGIN_SESSIONS
    # The newest still works, the oldest has been retired.
    assert (
        client.get("/api/me", headers={"Authorization": f"Bearer {tokens[-1]}"}).status_code == 200
    )
    assert (
        client.get("/api/me", headers={"Authorization": f"Bearer {tokens[0]}"}).status_code == 401
    )


# ---------------------------------------------------------------------------
# #21 — invalid agent keys; credential-less /api outside development
# ---------------------------------------------------------------------------

BOGUS_AGENT_KEY = "nom_agt_notarealkeynotarealkeynotareal"


def _agent_key(slug: str = "support-triage") -> tuple[str, str]:
    from agentfox.identity.service import ensure_identity, issue_credential

    with system_scope("test setup"), session_scope() as s:
        agent = s.scalars(select(Agent).where(Agent.slug == slug)).first()
        identity = ensure_identity(s, agent)
        cred, raw = issue_credential(s, identity)
        return raw, cred.id


GUARD_CALLS = [
    ("/v1/guard/input", {"agent": "support-triage", "content": "hello"}),
    ("/v1/guard/output", {"agent": "support-triage", "content": "hello"}),
    ("/v1/guard/memory_write", {"agent": "support-triage", "content": "likes tea"}),
    (
        "/v1/guard/tool_call",
        {"agent": "support-triage", "tool": "kb.search", "arguments": {"q": "x"}},
    ),
    ("/v1/guard/agent_message", {"sender": "support-triage", "content": "hi", "nonce": "n1"}),
]


@pytest.mark.parametrize("path,body", GUARD_CALLS)
def test_an_invalid_agent_key_is_refused_in_token_mode(ready, production, path, body):
    response = _app().post(path, json=body, headers={"Authorization": f"Bearer {BOGUS_AGENT_KEY}"})
    assert response.status_code == 401, response.text


def test_an_invalid_agent_key_is_refused_in_development_too(ready):
    response = _app().post(
        "/v1/guard/input",
        json={"agent": "support-triage", "content": "hello"},
        headers={"Authorization": f"Bearer {BOGUS_AGENT_KEY}"},
    )
    assert response.status_code == 401, response.text


def test_a_revoked_agent_key_is_refused(ready, production):
    from agentfox.identity.service import revoke_credential

    raw, cred_id = _agent_key()
    client = _app()
    body = {"agent": "support-triage", "content": "hello"}
    headers = {"Authorization": f"Bearer {raw}"}
    assert client.post("/v1/guard/input", json=body, headers=headers).status_code == 200
    with system_scope("test"), session_scope() as s:
        revoke_credential(s, cred_id)
    assert client.post("/v1/guard/input", json=body, headers=headers).status_code == 401


def test_no_credential_is_still_served_as_shadow_traffic(ready, production):
    response = _app().post("/v1/guard/input", json={"agent": "brand-new-bot", "content": "hi"})
    assert response.status_code == 200, response.text


def test_enforcer_never_upgrades_a_bad_key_to_the_named_agents_identity(seeded):
    from agentfox.runtime.enforcement import Enforcer

    agent, identity, _ = Enforcer(seeded).resolve("support-triage", BOGUS_AGENT_KEY)
    assert agent is not None
    assert identity is None
    # Without a credential the shadow-traffic rule still applies.
    _agent, named, _ = Enforcer(seeded).resolve("support-triage")
    assert named is not None


def test_token_mode_never_treats_a_credential_less_api_request_as_owner(ready, production):
    client = _app()
    assert client.get("/api/agents").status_code == 401
    assert (
        client.get("/api/agents", headers={"X-Nometria-User": "admin@example.com"}).status_code
        == 401
    )


# ---------------------------------------------------------------------------
# #22 — say why the header was refused
# ---------------------------------------------------------------------------


def test_token_mode_401_names_auth_mode_not_the_environment(ready, monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "development")
    monkeypatch.setattr(get_settings(), "auth_mode", "token")
    detail = _app().get("/api/agents").json()["detail"]
    assert "auth_mode='token'" in detail
    assert "runs in 'development'" not in detail


def test_production_401_names_the_environment(ready, production):
    detail = _app().get("/api/agents").json()["detail"]
    assert "'production'" in detail
