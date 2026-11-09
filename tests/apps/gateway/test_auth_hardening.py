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

from agentfox.apps.gateway.app import create_app
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
        headers={"X-AgentFox-Service-Secret": kw.pop("secret", SECRET)},
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
    """Importing the auth modules (the CLI mints tokens through identity.operators)
    never trips the startup guard; only *serving* refuses."""
    import importlib
    import sys

    monkeypatch.setattr(get_settings(), "service_auth_secret", DEFAULT_SERVICE_AUTH_SECRET)
    for name in [
        m for m in sys.modules if m == "agentfox.apps.gateway" or m == "agentfox.apps.gateway.auth"
    ]:
        monkeypatch.delitem(sys.modules, name)
    importlib.import_module("agentfox.apps.gateway.auth")
    importlib.import_module("agentfox.platform.identity.operators")


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


def _provision_oauth(client: TestClient, provider: str = "google", subject: str = "1001", **kw):
    return client.post(
        "/api/auth/oauth/provision",
        headers={"X-AgentFox-Service-Secret": kw.pop("secret", SECRET)},
        json={"provider": provider, "subject": subject, "email": "dev@corp.example", **kw},
    )


def test_oauth_provision_keys_on_the_provider_subject(ready, production):
    client = _app()
    first = _provision_oauth(client, subject="g-1").json()
    again = _provision_oauth(client, subject="g-1").json()
    assert again["user"]["id"] == first["user"]["id"]
    # A different Google account with the same email is someone else.
    assert _provision_oauth(client, subject="g-2").json()["user"]["id"] != first["user"]["id"]


def test_oauth_subjects_never_collide_across_providers(ready, production):
    client = _app()
    github = _provision(client, gh_id="555").json()
    google = _provision_oauth(client, "google", "555").json()
    microsoft = _provision_oauth(client, "microsoft", "555").json()
    assert len({github["user"]["id"], google["user"]["id"], microsoft["user"]["id"]}) == 3


def test_oauth_provision_refuses_bad_input_and_bad_secrets(ready, production, monkeypatch):
    client = _app()
    assert _provision_oauth(client, provider="myspace").status_code == 400
    assert _provision_oauth(client, subject="  ").status_code == 400
    assert _provision_oauth(client, secret="guess").status_code == 401
    monkeypatch.setattr(get_settings(), "service_auth_secret", DEFAULT_SERVICE_AUTH_SECRET)
    assert _provision_oauth(client, secret=DEFAULT_SERVICE_AUTH_SECRET).status_code == 503


def test_oauth_sign_in_mints_a_working_session(ready, production):
    client = _app()
    token = _provision_oauth(client, "microsoft", "ms-7").json()["token"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


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
    from agentfox.apps.gateway.routes.integrations import MAX_LOGIN_SESSIONS

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
    from agentfox.platform.identity.service import ensure_identity, issue_credential

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
    from agentfox.platform.identity.service import revoke_credential

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
        client.get("/api/agents", headers={"X-AgentFox-User": "admin@example.com"}).status_code
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


# ---------------------------------------------------------------------------
# Launch audit — failed authentication is logged and throttled; security headers
# ---------------------------------------------------------------------------


def test_failed_authentication_is_logged_without_the_credential(ready, production, caplog):
    forged = "nom_api_" + "x" * 40
    with caplog.at_level("WARNING", logger="agentfox.apps.gateway.deps"):
        response = _app().get("/api/agents", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    lines = [r.getMessage() for r in caplog.records if "refused" in r.getMessage()]
    assert lines and "/api/agents" in lines[0]
    assert all("xxxxxxxx" not in line and "nom_api_" not in line for line in lines)


def test_repeated_bad_credentials_are_throttled_but_a_good_one_still_works(ready, production):
    from agentfox.apps.gateway.deps import failed_auth_limiter

    client = _app()
    good = {"Authorization": f"Bearer {_provision(client).json()['token']}"}
    bad = {"Authorization": "Bearer nom_api_" + "y" * 40}
    statuses = [
        client.get("/api/agents", headers=bad).status_code
        for _ in range(failed_auth_limiter.limit + 1)
    ]
    assert statuses[:-1] == [401] * failed_auth_limiter.limit
    assert statuses[-1] == 429
    # The same address with a valid token is never locked out by someone's guessing.
    assert client.get("/api/me", headers=good).status_code == 200
    throttled = client.post(
        "/v1/guard/input",
        json={"agent": "a", "content": "hi"},
        headers={"Authorization": f"Bearer {BOGUS_AGENT_KEY}"},
    )
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) >= 1


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/messages"])
def test_an_anonymous_caller_cannot_pick_a_paid_provider(ready, production, path):
    """X-AgentFox-Provider spends the deployment's API key; anonymous callers get the default."""
    client = _app()
    body = {"model": "gpt-4o", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}
    chosen = client.post(path, json=body, headers={"X-AgentFox-Provider": "openai"})
    assert chosen.status_code == 401, chosen.text
    assert "X-AgentFox-Provider" in chosen.json()["detail"]
    # No header, or naming the default, is still served as shadow traffic.
    default = get_settings().default_provider
    assert client.post(path, json=body).status_code == 200
    assert client.post(path, json=body, headers={"X-AgentFox-Provider": default}).status_code == 200
    # With an agent key the choice is the caller's (the provider itself may then fail).
    raw, _ = _agent_key()
    keyed = client.post(
        path,
        json=body,
        headers={"X-AgentFox-Provider": "openai", "Authorization": f"Bearer {raw}"},
    )
    assert keyed.status_code != 401


def test_a_hosted_provider_is_never_called_with_egress_off(ready, monkeypatch):
    """allow_egress=false was only checked when listing providers; naming one in a
    request still sent the prompt to it."""
    from agentfox.platform.providers.remote import OpenAIProvider

    monkeypatch.setattr(get_settings(), "allow_egress", False)

    called = []
    monkeypatch.setattr(OpenAIProvider, "complete", lambda self, request: called.append(request))
    raw, _ = _agent_key()
    response = _app().post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-AgentFox-Provider": "openai", "Authorization": f"Bearer {raw}"},
    )
    assert called == []
    # Said plainly, not a bare 500.
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "agentfox_provider_unavailable"


def test_an_oversized_body_is_refused_before_it_is_read(ready, production, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_bytes", 1000)
    client = _app()
    big = {"agent": "support-triage", "content": "a" * 2000}
    response = client.post("/v1/guard/input", json=big)
    assert response.status_code == 413
    assert "max_request_bytes" in response.json()["detail"]
    assert response.headers["x-content-type-options"] == "nosniff"

    def chunks():
        yield b'{"agent": "support-triage", "content": "'
        for _ in range(20):
            yield b"a" * 100
        yield b'"}'

    chunked = client.post(
        "/v1/guard/input", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert chunked.status_code == 413
    small = client.post("/v1/guard/input", json={"agent": "support-triage", "content": "hi"})
    assert small.status_code == 200


@pytest.mark.parametrize("path", ["/api/health", "/api/agents", "/docs"])
def test_gateway_responses_carry_security_headers(ready, production, path):
    response = _app().get(path)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
