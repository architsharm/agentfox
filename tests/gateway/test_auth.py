"""Authentication.

The finding: the control plane accepted an unverified `X-Nometria-User` header and
trusted it, so anyone who could reach the port was any user they named, with write
access to policy, controls and the kill switch. It was documented as an MVP shortcut
"confined to one function", which was true and was not a mitigation.

Tenant isolation landed first and is meaningless without this. Filtering by org_id is
exact and pointless if the caller picks their own identity — the two only work as a
pair, and the tests below check the pair.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import Agent, ApiToken, Trace, User, utcnow
from agentfox.core.tenancy import system_scope, tenant
from agentfox.gateway.app import create_app
from agentfox.gateway.auth import (
    API_KEY_PREFIX,
    AuthenticationRequired,
    authenticate,
    header_identity_allowed,
    issue_token,
    resolve_token,
    revoke_token,
)


@pytest.fixture
def ready(isolated_db):
    """Seeded and committed.

    Authentication opens its own session, so a fixture holding an uncommitted one
    would leave it looking at an empty database — a property of the test harness, not
    of the product.
    """
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)
    yield


@pytest.fixture
def production(monkeypatch):
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "auth_mode", "auto")
    yield


def _user(email: str = "admin@example.com") -> User:
    with system_scope("test setup"), session_scope() as session:
        return session.scalars(select(User).where(User.email == email)).one()


def _token(email: str = "admin@example.com", **kwargs) -> str:
    with system_scope("test setup"), session_scope() as session:
        user = session.scalars(select(User).where(User.email == email)).one()
        _record, raw = issue_token(session, user, **kwargs)
        return raw


# ---------------------------------------------------------------------------
# The finding itself
# ---------------------------------------------------------------------------


def test_production_refuses_header_only_identity(ready, production):
    """The exact request that used to return 200 with full admin write access."""
    client = TestClient(create_app())
    assert (
        client.get("/api/agents", headers={"X-Nometria-User": "admin@example.com"}).status_code
        == 401
    )


def test_production_refuses_header_only_writes(ready, production):
    client = TestClient(create_app())
    response = client.post(
        "/api/controls/compute", headers={"X-Nometria-User": "admin@example.com"}
    )
    assert response.status_code == 401


def test_the_refusal_says_how_to_fix_it(ready, production):
    """An error that does not tell an operator what to do next generates a support
    conversation instead of a token."""
    client = TestClient(create_app())
    detail = client.get("/api/agents", headers={"X-Nometria-User": "admin@example.com"}).json()[
        "detail"
    ]
    assert "production" in detail
    assert "agentfox admin auth issue" in detail


def test_a_valid_token_is_accepted_in_production(ready, production):
    raw = _token(name="ci")
    client = TestClient(create_app())
    assert client.get("/api/agents", headers={"Authorization": f"Bearer {raw}"}).status_code == 200


# ---------------------------------------------------------------------------
# Mode selection — the failure direction
# ---------------------------------------------------------------------------


def test_development_still_works_without_a_token(ready):
    client = TestClient(create_app())
    assert (
        client.get("/api/agents", headers={"X-Nometria-User": "admin@example.com"}).status_code
        == 200
    )


def test_an_unrecognised_environment_is_treated_as_production(ready, monkeypatch):
    """A typo in a deployment variable must not silently open the door."""
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "prodution")  # deliberate typo
    monkeypatch.setattr(get_settings(), "auth_mode", "auto")
    assert not header_identity_allowed()


def test_auth_mode_overrides_the_environment(ready, monkeypatch):
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "development")
    monkeypatch.setattr(get_settings(), "auth_mode", "token")
    assert not header_identity_allowed()


def test_a_real_credential_always_beats_the_header(ready, monkeypatch):
    """A caller must not be able to downgrade to header identity by omitting the
    Authorization header on a deployment that has tokens."""
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "development")
    raw = _token()
    with session_scope() as session:
        user = authenticate(session, authorization=f"Bearer {raw}", header_user="nobody@evil.test")
    assert user.email == "admin@example.com"


# ---------------------------------------------------------------------------
# Token lifecycle
# ---------------------------------------------------------------------------


def test_only_a_hash_is_stored(ready):
    """A database disclosure must not hand over working credentials — which is the
    reason the token store and the audit log can share a database."""
    raw = _token()
    with system_scope("verify"), session_scope() as session:
        stored = session.scalars(select(ApiToken)).all()
    assert all(raw not in token.key_hash for token in stored)
    assert all(token.key_hash.startswith("$argon2") for token in stored)


def test_a_revoked_token_stops_working(ready, production):
    raw = _token()
    client = TestClient(create_app())
    assert client.get("/api/agents", headers={"Authorization": f"Bearer {raw}"}).status_code == 200

    with system_scope("revoke"), session_scope() as session:
        token = session.scalars(select(ApiToken)).one()
        assert revoke_token(session, token.id)

    assert client.get("/api/agents", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_an_expired_token_stops_working(ready):
    raw = _token(ttl_days=1)
    with system_scope("age it"), session_scope() as session:
        session.scalars(select(ApiToken)).one().expires_at = utcnow() - dt.timedelta(minutes=1)
    with session_scope() as session:
        assert resolve_token(session, raw) is None


def test_a_token_without_an_expiry_is_permitted_but_explicit(ready):
    raw = _token(ttl_days=None)
    with session_scope() as session:
        assert resolve_token(session, raw) is not None


def test_a_forged_token_with_the_right_prefix_is_rejected(ready):
    """Prefix narrowing is a lookup optimisation, never a check."""
    raw = _token()
    forged = raw[:16] + "x" * (len(raw) - 16)
    with session_scope() as session:
        assert resolve_token(session, forged) is None


def test_a_token_for_a_deactivated_user_is_rejected(ready):
    raw = _token()
    with system_scope("deactivate"), session_scope() as session:
        session.scalars(select(User).where(User.email == "admin@example.com")).one().active = False
    with session_scope() as session:
        assert resolve_token(session, raw) is None


def test_tokens_are_unguessable(ready):
    assert len({_token() for _ in range(5)}) == 5
    raw = _token()
    assert raw.startswith(API_KEY_PREFIX)
    assert len(raw) >= 40


# ---------------------------------------------------------------------------
# Authentication binds the tenant — the pair
# ---------------------------------------------------------------------------


def test_a_token_binds_its_own_tenant(isolated_db, production):
    """Two operators, two orgs, one endpoint."""
    for org, slug in (("org_acme", "acme-bot"), ("org_globex", "globex-bot")):
        with tenant(org), session_scope() as session:
            session.add(Agent(slug=slug, name=slug, environment="production"))
            session.add(User(email=f"admin@{org}.com", name="A", role="admin", active=True))

    tokens = {org: _token(f"admin@{org}.com") for org in ("org_acme", "org_globex")}
    client = TestClient(create_app())
    for org, expected in (("org_acme", "acme-bot"), ("org_globex", "globex-bot")):
        body = client.get("/api/agents", headers={"Authorization": f"Bearer {tokens[org]}"}).json()
        assert [a["slug"] for a in body["agents"]] == [expected]


def test_an_agent_credential_binds_its_agents_tenant(isolated_db):
    """This path bound no tenant at all: every governed completion ran in the default
    org whatever the agent's owner, and once isolation existed the credential lookup
    was itself filtered to that org, so an agent elsewhere could not authenticate."""
    from agentfox.platform.identity import ensure_identity, issue_credential

    with tenant("org_acme"), session_scope() as session:
        agent = Agent(slug="acme-bot", name="acme-bot", environment="production")
        session.add(agent)
        session.flush()
        identity = ensure_identity(session, agent)
        _credential, raw = issue_credential(session, identity)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat/completions",
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {raw}", "X-Nometria-Agent": "acme-bot"},
    )
    assert response.status_code == 200

    with tenant("org_acme"), session_scope() as session:
        assert session.scalars(select(Trace)).all(), "the trace must land in the agent's tenant"
    with tenant("org_globex"), session_scope() as session:
        assert not session.scalars(select(Trace)).all(), "and nowhere else"


def test_unregistered_agents_are_still_observed(ready):
    """The inline path deliberately serves unknown agents so shadow traffic is
    observed rather than turned away (P1-6). An absent credential is not an error."""
    client = TestClient(create_app())
    response = client.post(
        "/v1/chat/completions",
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Nometria-Agent": "never-registered"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Noise
# ---------------------------------------------------------------------------


def test_routine_auth_lookups_do_not_warn(ready):
    """Authentication is unavoidably cross-tenant and happens on every request. If it
    warned, one line per request would bury the warnings that matter."""
    import logging

    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("agentfox.core.tenancy")
    handler = Capture(level=logging.WARNING)
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        TestClient(create_app()).get(
            "/api/agents", headers={"X-Nometria-User": "admin@example.com"}
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    assert records == [], f"authentication should not warn on every request: {records}"


def test_authenticate_raises_rather_than_returning_none(ready, production):
    """A None return would be trivially mistaken for a valid anonymous principal."""
    with session_scope() as session, pytest.raises(AuthenticationRequired):
        authenticate(session, authorization=None, header_user="admin@example.com")


def test_a_credential_with_an_expiry_does_not_crash_the_inline_path(ready):
    """Regression: SQLite returns a naive datetime for a value written as aware, so
    `Credential.active` raised TypeError on comparison. Every agent credential *with
    an expiry* was a 500 on the hot path, and nothing read the field until agent
    credentials began resolving there.
    """
    from agentfox.core.models import Credential
    from agentfox.platform.identity import ensure_identity, issue_credential

    with session_scope() as session:
        agent = session.scalars(select(Agent).where(Agent.slug == "support-triage")).one()
        identity = ensure_identity(session, agent)
        issue_credential(session, identity)

    with session_scope() as session:
        for credential in session.scalars(select(Credential)):
            assert credential.active in (True, False)


# ---------------------------------------------------------------------------
# Self-service tokens (/api/tokens) — the CLI/SDK path had no way for an
# already-signed-in dashboard user to get a token for their own scripts short of
# the GitHub-login provisioning flow, which only ever mints one server-to-server
# at sign-in.
# ---------------------------------------------------------------------------


def test_a_signed_in_user_can_mint_their_own_token(client):
    from tests.conftest import as_user

    body = client.post(
        "/api/tokens", json={"name": "my-laptop"}, headers=as_user("dana@example.com")
    ).json()
    assert body["token"].startswith(API_KEY_PREFIX)
    assert body["name"] == "my-laptop"

    # And it actually authenticates against production-style token auth.
    with session_scope() as session:
        user = authenticate(session, authorization=f"Bearer {body['token']}", header_user=None)
    assert user.email == "dana@example.com"


def test_minted_tokens_are_listed_without_the_raw_value(client):
    from tests.conftest import as_user

    headers = as_user("aisha@example.com")
    client.post("/api/tokens", json={"name": "ci-runner"}, headers=headers)
    body = client.get("/api/tokens", headers=headers).json()
    assert body["tokens"][0]["name"] == "ci-runner"
    assert "token" not in body["tokens"][0]
    assert body["tokens"][0]["key_prefix"]


def test_a_revoked_self_service_token_stops_authenticating(client):
    from tests.conftest import as_user

    headers = as_user("priya@example.com")
    minted = client.post("/api/tokens", json={"name": "temp"}, headers=headers).json()
    token_id = client.get("/api/tokens", headers=headers).json()["tokens"][0]["id"]

    client.post(f"/api/tokens/{token_id}/revoke", headers=headers)

    with session_scope() as session, pytest.raises(AuthenticationRequired):
        authenticate(session, authorization=f"Bearer {minted['token']}", header_user=None)


def test_doctor_reports_the_authentication_posture(ready, monkeypatch):
    """The check most likely to be wrong, and most costly when it is."""
    from typer.testing import CliRunner

    from agentfox.apps.cli.main import app
    from agentfox.core.config import get_settings

    flat = lambda text: " ".join(text.split())  # noqa: E731 - test readability

    development = flat(CliRunner().invoke(app, ["doctor"]).output)
    assert "any user they name" in development

    monkeypatch.setattr(get_settings(), "environment", "production")
    production = flat(CliRunner().invoke(app, ["doctor"]).output)
    assert "API tokens required" in production
