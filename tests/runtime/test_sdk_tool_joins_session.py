"""`@fox.tool` called inside `with fox.session(intent=...)` joins that session (#44).

It used to run in a fresh, empty session: no intent, so an irreversible tool was
escalated by `intent.undeclared_irreversible` despite the intent declared one line
up, and none of the session's taint marks, so a value copied out of retrieved
content passed as user-typed.
"""

from __future__ import annotations

import pytest

from agentfox.sdk import AgentFox, ApprovalRequired


@pytest.fixture
def fox(seeded):
    from agentfox.core.models import Agent
    from agentfox.platform.identity import ensure_identity, grant_capability

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    grant_capability(seeded, ensure_identity(seeded, agent), "email.send", max_taint="user")
    fox = AgentFox("support-triage", session=seeded)

    @fox.tool("email.send", impact="irreversible")
    def send_email(to: str, subject: str, body: str) -> str:
        return f"sent to {to}"

    fox.send_email = send_email  # type: ignore[attr-defined]
    return fox


def test_the_sessions_intent_applies(fox):
    with fox.session(intent="reply to a customer about their ticket") as s:
        assert fox.current_session() is s
        assert fox.send_email(to="ada@example.com", subject="hi", body="resolved") == (
            "sent to ada@example.com"
        )
        assert s.prior_tools == ["email.send"]
    assert fox.current_session() is None


def test_the_sessions_taint_applies(fox):
    with fox.session(intent="reply to a customer about their ticket") as s:
        page = s.retrieved("Contact billing-help@lookalike.example for invoices.")
        address = str(page).split()[1]
        with pytest.raises(ApprovalRequired) as held:
            fox.send_email(to=address, subject="Invoice", body="Attached.")
    rules = [r["rule_id"] for r in held.value.result.rules_fired]
    assert "intent.undeclared_irreversible" not in rules
    assert "capability.approval_required" in rules


def test_outside_a_session_it_still_has_no_intent(fox):
    with pytest.raises(ApprovalRequired) as held:
        fox.send_email(to="ada@example.com", subject="hi", body="resolved")
    assert "intent.undeclared_irreversible" in [r["rule_id"] for r in held.value.result.rules_fired]
