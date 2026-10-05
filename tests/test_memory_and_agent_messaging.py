"""Memory write governance (NOM-RTG-13, ASI06) and inter-agent message
security (NOM-IAM-08, ASI07)."""

from __future__ import annotations

import pytest

from agentfox.containment.agent_messaging import mint_signing_key, sign_message
from agentfox.core.models import Agent, AgentMessageLog, MemoryEntry
from agentfox.policy import set_mode

from .conftest import INDIRECT_INJECTION, SECRET_TEXT, as_user


@pytest.fixture
def encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("NOMETRIA_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    reset_settings_cache()
    yield
    reset_settings_cache()


# ---------------------------------------------------------------------------
# Memory write governance (P14, NOM-RTG-13)
# ---------------------------------------------------------------------------


def test_a_clean_write_persists_unverified_and_default_closed(seeded, enforcer):
    result = enforcer.guard_memory_write(
        agent_slug="support-triage",
        content="The customer prefers email over phone.",
        subject="cust-42",
    )
    assert result.verdict == "allow"
    entry_id = result.taint["memory_entry_id"]
    entry = seeded.get(MemoryEntry, entry_id)
    assert entry is not None
    assert entry.verified_by is None
    assert entry.expires_at is not None  # unverified => decays, doesn't persist forever
    assert entry.active is True


def test_a_verified_write_never_expires(seeded, enforcer):
    result = enforcer.guard_memory_write(
        agent_slug="support-triage",
        content="Refund policy is 30 days.",
        verified_by="dana@example.com",
    )
    entry = seeded.get(MemoryEntry, result.taint["memory_entry_id"])
    assert entry.expires_at is None
    assert entry.active is True


def test_an_unverified_entry_with_no_expiry_defaults_closed():
    """Direct construction (bypassing guard_memory_write) still can't accidentally
    read as active — the model's own default is closed, not open like Suppression."""
    entry = MemoryEntry(content="x", taint_source="user")
    assert entry.verified_by is None
    assert entry.expires_at is None
    assert entry.active is False


def test_enforced_secret_write_is_blocked_and_never_persists(seeded, enforcer):
    set_mode(seeded, "baseline", "enforce")
    before = seeded.query(MemoryEntry).count()
    result = enforcer.guard_memory_write(agent_slug="support-triage", content=SECRET_TEXT)
    assert result.blocked
    assert "memory_entry_id" not in result.taint
    assert seeded.query(MemoryEntry).count() == before


def test_enforced_injection_write_is_blocked(seeded, enforcer):
    set_mode(seeded, "baseline", "enforce")
    result = enforcer.guard_memory_write(agent_slug="support-triage", content=INDIRECT_INJECTION)
    assert result.blocked
    assert any(r["rule_id"] == "injection.memory_and_agent_message" for r in result.rules_fired)


def test_observe_mode_still_writes_but_reports_the_counterfactual(seeded, enforcer):
    """Same R3 semantics as every other surface — observe never blocks."""
    result = enforcer.guard_memory_write(agent_slug="support-triage", content=SECRET_TEXT)
    assert result.verdict == "allow"
    assert result.effective_verdict == "block"
    assert "memory_entry_id" in result.taint


def test_pii_write_persists_redacted(seeded, enforcer):
    """An email alone hits the memory/agent-message redact rule, not the
    higher-severity SSN/card block rule PII_TEXT would also trip."""
    set_mode(seeded, "baseline", "enforce")
    result = enforcer.guard_memory_write(
        agent_slug="support-triage", content="Contact jane.doe@example.com for follow-up."
    )
    assert result.verdict == "redact"
    entry = seeded.get(MemoryEntry, result.taint["memory_entry_id"])
    assert "jane.doe@example.com" not in entry.content


def test_guard_memory_write_endpoint(client):
    payload = {"agent": "support-triage", "content": "The user's timezone is PST."}
    resp = client.post(
        "/v1/guard/memory_write", json=payload, headers=as_user("marcus@example.com")
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "allow"
    entry_id = body["taint"]["memory_entry_id"]

    listed = client.get("/api/memory", headers=as_user("marcus@example.com"))
    assert listed.status_code == 200
    ids = [e["id"] for e in listed.json()["entries"]]
    assert entry_id in ids

    verified = client.post(f"/api/memory/{entry_id}/verify", headers=as_user("admin@example.com"))
    assert verified.status_code == 200
    assert verified.json()["verified_by"] == "admin@example.com"
    assert verified.json()["expires_at"] is None

    revoked = client.post(f"/api/memory/{entry_id}/revoke", headers=as_user("admin@example.com"))
    assert revoked.status_code == 200
    assert revoked.json()["active"] is False


# ---------------------------------------------------------------------------
# Inter-agent message security (P17, NOM-IAM-08)
# ---------------------------------------------------------------------------


def test_unsigned_message_is_reported_not_silently_trusted(seeded, enforcer):
    result = enforcer.guard_agent_message(
        sender_slug="support-triage", content="Ticket escalated to tier 2.", nonce="n1"
    )
    assert result.taint.get("unsigned") is True
    assert any(r["rule_id"] == "agent_message.unsigned" for r in result.rules_fired)


def test_unregistered_sender_fails_the_agent_card_check(seeded, enforcer):
    result = enforcer.guard_agent_message(
        sender_slug="totally-unregistered-agent", content="hello", nonce="n2"
    )
    assert result.verdict == "escalate"
    assert any(r["rule_id"] == "agent_message.agent_card_mismatch" for r in result.rules_fired)


def test_replayed_nonce_is_blocked(seeded, enforcer):
    enforcer.guard_agent_message(sender_slug="support-triage", content="first", nonce="dupe")
    result = enforcer.guard_agent_message(
        sender_slug="support-triage", content="second", nonce="dupe"
    )
    assert result.blocked
    assert any(r["rule_id"] == "agent_message.replay" for r in result.rules_fired)


def test_signed_message_verifies(seeded, enforcer, encryption_key):
    agent = seeded.query(Agent).filter_by(slug="support-triage").first()
    _key, raw = mint_signing_key(seeded, agent.id)
    seeded.flush()
    signature, ts = sign_message(raw, sender="support-triage", nonce="sig1", payload="hello there")
    result = enforcer.guard_agent_message(
        sender_slug="support-triage",
        content="hello there",
        nonce="sig1",
        timestamp=ts,
        signature=signature,
    )
    assert "unsigned" not in result.taint
    assert not any(r["rule_id"] == "agent_message.bad_signature" for r in result.rules_fired)
    log = (
        seeded.query(AgentMessageLog).filter_by(sender_slug="support-triage", nonce="sig1").first()
    )
    assert log.signature_valid is True


def test_tampered_signature_is_blocked(seeded, enforcer, encryption_key):
    agent = seeded.query(Agent).filter_by(slug="support-triage").first()
    _key, raw = mint_signing_key(seeded, agent.id)
    seeded.flush()
    signature, ts = sign_message(
        raw, sender="support-triage", nonce="sig2", payload="original payload"
    )
    result = enforcer.guard_agent_message(
        sender_slug="support-triage",
        content="a different payload entirely",  # signed payload doesn't match
        nonce="sig2",
        timestamp=ts,
        signature=signature,
    )
    assert result.blocked
    assert any(r["rule_id"] == "agent_message.bad_signature" for r in result.rules_fired)


def test_enforced_injection_in_agent_message_is_blocked(seeded, enforcer):
    set_mode(seeded, "baseline", "enforce")
    result = enforcer.guard_agent_message(
        sender_slug="support-triage", content=INDIRECT_INJECTION, nonce="inj1"
    )
    assert result.blocked


def test_mint_and_use_signing_key_over_http(client, encryption_key):
    minted = client.post(
        "/api/agents/support-triage/signing-key", headers=as_user("admin@example.com")
    )
    assert minted.status_code == 200
    raw = minted.json()["key"]
    assert raw

    status = client.get(
        "/api/agents/support-triage/signing-key", headers=as_user("marcus@example.com")
    )
    assert status.json()["has_key"] is True

    signature, ts = sign_message(raw, sender="support-triage", nonce="http1", payload="msg body")
    resp = client.post(
        "/v1/guard/agent_message",
        json={
            "sender": "support-triage",
            "content": "msg body",
            "nonce": "http1",
            "timestamp": ts,
            "signature": signature,
        },
        headers=as_user("marcus@example.com"),
    )
    assert resp.status_code == 200
    assert "unsigned" not in resp.json()["taint"]

    listed = client.get("/api/agent-messages", headers=as_user("marcus@example.com"))
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
