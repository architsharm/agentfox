"""An approval can complete the call it held (#12, #14, #24).

Before: approving an escalated call and sending it again escalated again and filed a
new approval, so a held call could never run through the product. A retry that
presents the approval now runs once — the same agent, tool and arguments a person
approved, before it expires.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from agentfox.core.models import Agent, ApprovalRequest, Identity, utcnow
from agentfox.identity import issue_credential, redeem_approval, resolve_approval
from agentfox.sdk import AgentFox, ApprovalRequired, PolicyViolation
from tests.conftest import as_user

EMAIL = {"to": "customer@example.com", "body": "your receipt"}
USER_PROVENANCE = {"to": "user", "body": "user"}


def _held(seeded, arguments=EMAIL):
    """payments-ops holds email.send with requires_approval."""
    fox = AgentFox("payments-ops", session=seeded)
    with fox.session(intent="email the customer their receipt") as s:
        with pytest.raises(ApprovalRequired) as held:
            s.guard_tool("email.send", dict(arguments), provenance=USER_PROVENANCE)
    return fox, held.value.approval_id


def _approve(session, approval_id):
    assert resolve_approval(session, approval_id, True, "usr_test", "checked").status == "approved"


def test_an_approved_call_runs_once_on_retry(seeded):
    fox, approval_id = _held(seeded)
    _approve(seeded, approval_id)

    with fox.session(intent="email the customer their receipt") as s:
        result = s.guard_tool(
            "email.send", dict(EMAIL), provenance=USER_PROVENANCE, approval_id=approval_id
        )
    assert result.verdict == "allow"
    assert "approval.redeemed" in [r["rule_id"] for r in result.rules_fired]
    assert seeded.get(ApprovalRequest, approval_id).status == "used"

    # Single use: the same approval does not let a second call through.
    with fox.session(intent="email the customer their receipt") as s:
        with pytest.raises(ApprovalRequired) as again:
            s.guard_tool(
                "email.send", dict(EMAIL), provenance=USER_PROVENANCE, approval_id=approval_id
            )
    assert again.value.approval_id != approval_id
    assert "already used" in str(again.value)


def test_an_approval_does_not_cover_different_arguments(seeded):
    fox, approval_id = _held(seeded)
    _approve(seeded, approval_id)
    with fox.session(intent="email the customer their receipt") as s:
        with pytest.raises(ApprovalRequired) as held:
            s.guard_tool(
                "email.send",
                {**EMAIL, "to": "someone-else@example.com"},
                provenance=USER_PROVENANCE,
                approval_id=approval_id,
            )
    assert "different arguments" in str(held.value)
    # Not spent by the mismatched attempt.
    assert seeded.get(ApprovalRequest, approval_id).status == "approved"


def test_an_approval_does_not_cover_another_agent_or_tool(seeded):
    _fox, approval_id = _held(seeded)
    _approve(seeded, approval_id)
    other = seeded.scalar(select(Agent).where(Agent.slug == "support-triage"))
    payments = seeded.scalar(select(Agent).where(Agent.slug == "payments-ops"))

    spent, why = redeem_approval(
        seeded, approval_id, agent_id=other.id, tool_key="email.send", arguments=EMAIL
    )
    assert spent is None and "different agent" in why
    spent, why = redeem_approval(
        seeded, approval_id, agent_id=payments.id, tool_key="payments.transfer", arguments=EMAIL
    )
    assert spent is None and "not 'payments.transfer'" in why


@pytest.mark.parametrize("decision", ["pending", "denied", "expired"])
def test_only_an_approved_unexpired_approval_redeems(seeded, decision):
    fox, approval_id = _held(seeded)
    if decision == "denied":
        resolve_approval(seeded, approval_id, False, "usr_test", "no")
    elif decision == "expired":
        _approve(seeded, approval_id)
        seeded.get(ApprovalRequest, approval_id).expires_at = utcnow() - dt.timedelta(minutes=1)
        seeded.flush()
    with fox.session(intent="email the customer their receipt") as s:
        with pytest.raises(ApprovalRequired):
            s.guard_tool(
                "email.send", dict(EMAIL), provenance=USER_PROVENANCE, approval_id=approval_id
            )


def test_an_approval_never_releases_a_block(seeded):
    """payments.transfer over the grant's limit is a block, not a hold: presenting an
    approval (even an approved one for something else) changes nothing."""
    _fox, approval_id = _held(seeded)
    _approve(seeded, approval_id)
    fox = AgentFox("payments-ops", session=seeded)
    with fox.session(intent="refund") as s:
        with pytest.raises(PolicyViolation):
            s.guard_tool(
                "payments.transfer",
                {"amount": 5000, "currency": "USD", "to": "acct_1"},
                provenance={"amount": "user", "currency": "user", "to": "user"},
                approval_id=approval_id,
            )
    assert seeded.get(ApprovalRequest, approval_id).status == "approved"


def test_approving_restarts_the_redeem_window(seeded):
    """A decision made at minute 29 of a 30-minute wait must leave time to retry."""
    _fox, approval_id = _held(seeded)
    seeded.get(ApprovalRequest, approval_id).expires_at = utcnow() + dt.timedelta(seconds=5)
    seeded.flush()
    _approve(seeded, approval_id)
    remaining = seeded.get(ApprovalRequest, approval_id).expires_at
    remaining = remaining if remaining.tzinfo else remaining.replace(tzinfo=dt.UTC)
    assert remaining - utcnow() > dt.timedelta(minutes=20)


def test_wait_for_approval_returns_the_decision(seeded):
    fox, approval_id = _held(seeded)
    assert fox.wait_for_approval(approval_id, timeout=0) == "pending"
    _approve(seeded, approval_id)
    assert fox.wait_for_approval(approval_id, timeout=1, interval=0.01) == "approved"


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


def _agent_key(session, slug="payments-ops") -> str:
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    identity = session.scalar(select(Identity).where(Identity.agent_id == agent.id))
    _credential, raw = issue_credential(session, identity)
    session.commit()
    return raw


def _token_mode(monkeypatch):
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("NOMETRIA_AUTH_MODE", "token")
    reset_settings_cache()


TOOL_CALL = {
    "agent": "payments-ops",
    "tool": "email.send",
    "arguments": EMAIL,
    "provenance": USER_PROVENANCE,
    "intent": "email the customer their receipt",
}


def test_http_retry_with_the_approval_runs(client):
    held = client.post("/v1/guard/tool_call", json=TOOL_CALL).json()
    assert held["verdict"] == "escalate"
    approval_id = held["approval_id"]
    decided = client.post(
        f"/api/approvals/{approval_id}/approve",
        json={"rationale": "ok"},
        headers=as_user("admin@example.com"),
    )
    assert decided.json()["status"] == "approved"

    retry = client.post("/v1/guard/tool_call", json={**TOOL_CALL, "approval_id": approval_id})
    assert retry.json()["verdict"] == "allow", retry.json()
    again = client.post("/v1/guard/tool_call", json={**TOOL_CALL, "approval_id": approval_id})
    assert again.json()["verdict"] == "escalate"


def test_an_agent_key_reads_its_own_approval_and_no_one_elses(client, monkeypatch):
    from agentfox.core.db import session_scope

    approval_id = client.post("/v1/guard/tool_call", json=TOOL_CALL).json()["approval_id"]
    with session_scope() as session:
        own = _agent_key(session, "payments-ops")
        other = _agent_key(session, "support-triage")
    _token_mode(monkeypatch)

    mine = client.get(f"/api/approvals/{approval_id}", headers={"Authorization": f"Bearer {own}"})
    assert mine.status_code == 200, mine.text
    assert mine.json()["status"] == "pending"
    theirs = client.get(
        f"/api/approvals/{approval_id}", headers={"Authorization": f"Bearer {other}"}
    )
    assert theirs.status_code == 404
    bogus = client.get(
        f"/api/approvals/{approval_id}", headers={"Authorization": "Bearer nom_agt_nope"}
    )
    assert bogus.status_code == 401
    # Reading is all an agent key may do: deciding stays with an operator.
    decide = client.post(
        f"/api/approvals/{approval_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {own}"},
    )
    assert decide.status_code == 401


_HOLD_CARDS = """
key: hold-cards
name: Hold card numbers for a person
version: 1
mode: enforce
default_effect: allow
scope:
  agents: ["*"]
rules:
  - id: pii.card_to_person
    when:
      surface: [input]
      detection: {entity_prefix: PII, min_score: 0.5}
    effect: escalate
    severity: medium
    reason: "Card numbers in a support conversation go to a person."
"""


def test_a_held_message_is_filed_with_its_content_and_completes_on_retry(client):
    """#24: a message held for a person used to be filed with `tool: null` and empty
    arguments, so the approver had nothing to decide on. #20: the proxy's hold is an
    error status a provider SDK raises on, not a 202 it parses as a completion."""
    from agentfox.core.db import session_scope
    from agentfox.policy.model import PolicyDocument
    from agentfox.policy.store import save_policy

    with session_scope() as session:
        save_policy(session, PolicyDocument.from_yaml(_HOLD_CARDS), bind_mode="enforce")

    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "My card 4111 1111 1111 1111 was charged twice."}],
    }
    headers = {"X-Nometria-Agent": "support-triage"}
    held = client.post("/v1/chat/completions", json=body, headers=headers)
    assert held.status_code == 428, held.text
    error = held.json()["error"]
    assert error["type"] == "agentfox_approval_required"
    approval_id = error["approval_id"]
    assert held.json()["approval_id"] == approval_id  # the 202 body's fields, kept

    with session_scope() as session:
        approval = session.get(ApprovalRequest, approval_id)
        assert approval.tool_key == "message:input"
        assert approval.arguments_json["surface"] == "input"
        assert "charged twice" in approval.arguments_json["content"]
        assert "4111 1111 1111 1111" not in approval.arguments_json["content"]
        assert approval.arguments_json["content_sha256"]

    client.post(
        f"/api/approvals/{approval_id}/approve", json={}, headers=as_user("admin@example.com")
    )
    retry = client.post(
        "/v1/chat/completions", json=body, headers={**headers, "X-Nometria-Approval": approval_id}
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["choices"][0]["message"]["content"]
