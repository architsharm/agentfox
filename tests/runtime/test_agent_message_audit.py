"""#19, X3, #18 — agent_message overrides are applied before the decision is recorded.

The replay / unregistered-sender / bad-signature overrides were applied to the
result *after* `evaluate()` had already written the Decision row and the audit
chain entry, so a message the caller was told was blocked sat in the audit chain
as `decision.allow`. And a missing nonce was stored as "", so a sender's second
nonce-less message collided with its first and was blocked as a replay.
"""

from __future__ import annotations

from sqlalchemy import select

from agentfox.core.models import AgentMessageLog, AuditEntry, Decision


def _recorded(session, decision_id: str) -> tuple[str, str]:
    decision = session.get(Decision, decision_id)
    entry = session.scalar(
        select(AuditEntry).where(
            AuditEntry.subject_type == "decision", AuditEntry.subject_id == decision_id
        )
    )
    return decision.verdict, entry.action


def test_a_replayed_message_is_recorded_as_blocked(seeded, enforcer):
    enforcer.guard_agent_message(sender_slug="support-triage", content="first", nonce="dup")
    result = enforcer.guard_agent_message(
        sender_slug="support-triage", content="second", nonce="dup"
    )
    assert result.verdict == "block"
    assert _recorded(seeded, result.decision_id) == ("block", "decision.block")
    assert any(r["rule_id"] == "agent_message.replay" for r in result.rules_fired)


def test_an_unregistered_sender_is_recorded_as_escalated(seeded, enforcer):
    result = enforcer.guard_agent_message(
        sender_slug="totally-unregistered-agent", content="hello", nonce="n1"
    )
    assert result.verdict == "escalate"
    assert _recorded(seeded, result.decision_id) == ("escalate", "decision.escalate")
    payload = seeded.scalar(
        select(AuditEntry.payload_json).where(AuditEntry.subject_id == result.decision_id)
    )
    assert "agent_message.agent_card_mismatch" in [r["rule_id"] for r in payload["rules_fired"]]


def test_nonce_less_messages_are_not_replays_of_each_other(seeded, enforcer):
    first = enforcer.guard_agent_message(sender_slug="support-triage", content="one")
    second = enforcer.guard_agent_message(sender_slug="support-triage", content="two")
    assert first.verdict == "allow"
    assert second.verdict == "allow"
    assert not any(r["rule_id"] == "agent_message.replay" for r in second.rules_fired)
    # The gap is declared, not hidden: no nonce means no replay protection.
    assert any(r["rule_id"] == "agent_message.no_nonce" for r in second.rules_fired)
    assert second.taint.get("replay_protected") is False
    rows = seeded.scalars(
        select(AgentMessageLog).where(AgentMessageLog.sender_slug == "support-triage")
    ).all()
    assert {r.decision_id for r in rows} == {first.decision_id, second.decision_id}
