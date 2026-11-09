"""Self-service account deletion (`POST /api/account/delete`, routes/integrations.py).

The privacy page promises a signed-in owner can delete their workspace themselves.
These pin down that it removes every row of that workspace, touches nothing in any
other, and refuses rather than half-deletes in the cases its docstring names.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from agentfox.apps.gateway.app import create_app
from agentfox.core.config import get_settings
from agentfox.core.db import session_scope
from agentfox.core.models import ApiToken, AuditEntry, LegalHold, User
from agentfox.core.tenancy import bind_session, system_scope

SECRET = "test-service-secret"  # what tests/conftest.py sets


@pytest.fixture
def client(isolated_db, monkeypatch):
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)
    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "auth_mode", "auto")
    return TestClient(create_app())


def _sign_in(client: TestClient, subject: str, email: str) -> tuple[dict[str, str], str]:
    body = client.post(
        "/api/auth/oauth/provision",
        headers={"X-AgentFox-Service-Secret": SECRET},
        json={"provider": "google", "subject": subject, "email": email, "name": "Ada"},
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}, body["user"]["org_id"]


def _rows(org_id: str, model) -> int:
    with system_scope("test"), session_scope() as s:
        return s.scalar(select(func.count()).select_from(model).where(model.org_id == org_id))


def test_an_owner_deletes_their_whole_workspace_and_nothing_else(client):
    auth, org = _sign_in(client, "del-1", "ada@corp.example")
    _, other_org = _sign_in(client, "del-2", "bob@corp.example")
    assert _rows(org, User) == 1 and _rows(org, AuditEntry) > 0
    other_audit = _rows(other_org, AuditEntry)

    resp = client.post("/api/account/delete", headers=auth, json={"confirm": "Ada@Corp.example "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True

    for model in (User, ApiToken, AuditEntry):
        assert _rows(org, model) == 0
    assert _rows(other_org, User) == 1
    assert _rows(other_org, AuditEntry) == other_audit
    # The session is gone with the user it belonged to.
    assert client.get("/api/me", headers=auth).status_code == 401


def test_the_email_must_be_typed_back(client):
    auth, org = _sign_in(client, "del-3", "ada@corp.example")
    for confirm in ("", "someone@else.example"):
        assert (
            client.post("/api/account/delete", headers=auth, json={"confirm": confirm}).status_code
            == 400
        )
    assert _rows(org, User) == 1


def test_an_active_legal_hold_stops_it(client):
    auth, org = _sign_in(client, "del-4", "ada@corp.example")
    with session_scope() as s:
        bind_session(s, org)
        s.add(LegalHold(scope_json={}, reason="case 1", placed_by="ada@corp.example"))
    resp = client.post("/api/account/delete", headers=auth, json={"confirm": "ada@corp.example"})
    assert resp.status_code == 409
    assert "legal hold" in resp.json()["detail"]
    assert _rows(org, User) == 1


def test_a_workspace_with_another_member_is_not_deleted(client):
    auth, org = _sign_in(client, "del-5", "ada@corp.example")
    with session_scope() as s:
        bind_session(s, org)
        s.add(User(email="colleague@corp.example", role="developer"))
    resp = client.post("/api/account/delete", headers=auth, json={"confirm": "ada@corp.example"})
    assert resp.status_code == 409
    assert _rows(org, User) == 2


def test_only_an_owner_may_delete(client):
    auth, org = _sign_in(client, "del-6", "ada@corp.example")
    with system_scope("test"), session_scope() as s:
        s.scalar(select(User).where(User.org_id == org)).role = "developer"
    resp = client.post("/api/account/delete", headers=auth, json={"confirm": "ada@corp.example"})
    assert resp.status_code == 403
    assert _rows(org, User) == 1
