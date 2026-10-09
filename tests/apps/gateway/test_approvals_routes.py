"""What the Approvals pages read: who decided and when, and an approval that ran out
while someone was deciding it."""

from __future__ import annotations

import datetime as dt

from agentfox.core.models import ApprovalRequest, utcnow
from tests.conftest import as_user

TOOL_CALL = {
    "agent": "payments-ops",
    "tool": "email.send",
    "arguments": {"to": "customer@example.com", "body": "your receipt"},
    "provenance": {"to": "user", "body": "user"},
    "intent": "email the customer their receipt",
}
ADMIN = as_user("admin@example.com")


def _held(client) -> str:
    held = client.post("/v1/guard/tool_call", json=TOOL_CALL).json()
    assert held["verdict"] == "escalate", held
    return held["approval_id"]


def _by_id(client, status: str, approval_id: str) -> dict:
    rows = client.get(f"/api/approvals?status={status}", headers=ADMIN).json()["approvals"]
    return next(a for a in rows if a["id"] == approval_id)


def test_history_and_detail_say_who_decided_and_why(client):
    approval_id = _held(client)
    pending = _by_id(client, "pending", approval_id)
    assert pending["resolver"] is None and pending["resolved_at"] is None

    decided = client.post(
        f"/api/approvals/{approval_id}/deny", json={"rationale": "wrong customer"}, headers=ADMIN
    )
    assert decided.status_code == 200

    row = _by_id(client, "denied", approval_id)
    assert row["resolver"] == "admin@example.com"
    assert row["rationale"] == "wrong customer"
    assert row["resolved_at"]
    detail = client.get(f"/api/approvals/{approval_id}", headers=ADMIN).json()
    assert detail["resolver"] == "admin@example.com"
    assert detail["requested_at"] and detail["trace_id"] and detail["reason"]
    assert detail["arguments"] == TOOL_CALL["arguments"]


def test_an_unanswered_approval_has_no_decider(client):
    from agentfox.core.db import session_scope

    approval_id = _held(client)
    with session_scope() as s:
        s.get(ApprovalRequest, approval_id).expires_at = utcnow() - dt.timedelta(seconds=1)
    row = _by_id(client, "expired", approval_id)
    assert row["resolver"] is None and row["resolved_at"]


def test_deciding_after_expiry_is_refused_not_reported_as_approved(client):
    from agentfox.core.db import session_scope

    approval_id = _held(client)
    with session_scope() as s:
        s.get(ApprovalRequest, approval_id).expires_at = utcnow() - dt.timedelta(seconds=1)

    late = client.post(f"/api/approvals/{approval_id}/approve", json={}, headers=ADMIN)
    assert late.status_code == 409
    assert "expired" in late.json()["detail"]
    # The expiry stuck, and nobody is recorded as having decided it.
    with session_scope() as s:
        row = s.get(ApprovalRequest, approval_id)
        assert row.status == "expired" and row.resolver_user_id is None
    retry = client.post("/v1/guard/tool_call", json={**TOOL_CALL, "approval_id": approval_id})
    assert retry.json()["verdict"] == "escalate"
