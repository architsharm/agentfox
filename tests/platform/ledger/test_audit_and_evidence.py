"""Pillar 5 — the tamper-evident chain and evidence packages.

These are the tests that decide whether the compliance claims mean anything. If the
chain has a bug, every control status and every evidence package built on it is void
(Appendix E.2.3), so each tamper mode is asserted individually.
"""

from __future__ import annotations

import json

import pytest

from agentfox.core.models import AuditEntry
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.chain import GENESIS, entry_to_row, verify, verify_range


@pytest.fixture
def chained(session):
    for i in range(12):
        chain.append(
            session,
            "test.event",
            subject_type="thing",
            subject_id=f"s{i}",
            payload={"i": i, "note": f"entry {i}"},
        )
    return session


def rows(session) -> list[dict]:
    return [entry_to_row(e) for e in session.query(AuditEntry).order_by(AuditEntry.seq)]


# ---------------------------------------------------------------------------
# Chain integrity (P5-2, NFR-5)
# ---------------------------------------------------------------------------


def test_empty_chain_verifies(session):
    assert verify_range(session).valid


def test_intact_chain_verifies(chained):
    result = verify_range(chained)
    assert result.valid
    assert result.entries_checked == 12
    assert result.first_seq == 1 and result.last_seq == 12
    assert not result.breaks


def test_genesis_linkage(chained):
    first = chained.query(AuditEntry).filter_by(seq=1).one()
    assert first.prev_digest == GENESIS


def test_detects_mutation(chained):
    entry = chained.query(AuditEntry).filter_by(seq=5).one()
    entry.payload_json = {"i": 5, "note": "rewritten"}
    chained.flush()
    result = verify_range(chained)
    assert not result.valid
    assert result.first_break.kind == "payload_mismatch"
    assert result.first_break.seq == 5


def test_detects_deletion(chained):
    chained.delete(chained.query(AuditEntry).filter_by(seq=6).one())
    chained.flush()
    result = verify_range(chained)
    assert not result.valid
    kinds = {b.kind for b in result.breaks}
    assert "gap" in kinds


def test_detects_insertion(chained):
    """A forged entry cannot produce a prev_digest that links correctly."""
    forged = AuditEntry(
        seq=13,
        occurred_at=chain.utcnow(),
        actor_type="attacker",
        action="fake.event",
        subject_type="x",
        subject_id="y",
        payload_json={"forged": True},
        payload_digest=chain.compute_payload_digest({"forged": True}),
        prev_digest="0" * 64,
        digest="f" * 64,
    )
    chained.add(forged)
    chained.flush()
    result = verify_range(chained)
    assert not result.valid
    assert {"digest_mismatch", "prev_mismatch"} & {b.kind for b in result.breaks}


def test_detects_reordering(chained):
    exported = rows(chained)
    exported[3], exported[4] = exported[4], exported[3]
    for i, row in enumerate(exported):
        row["seq"] = i + 1
    result = verify(exported)
    assert not result.valid


def test_verify_is_pure_over_exported_rows(chained):
    """An auditor must be able to verify without access to our systems (P5-7)."""
    exported = json.loads(json.dumps(rows(chained), default=str))
    assert verify(exported).valid
    exported[2]["payload"]["note"] = "changed"
    assert not verify(exported).valid


def test_checkpoint_signature_verified(chained):
    checkpoint = chain.checkpoint_now(chained)
    assert checkpoint is not None
    result = verify_range(chained)
    assert result.valid and result.checkpoints_checked == 1


def test_forged_checkpoint_detected(chained):
    checkpoint = chain.checkpoint_now(chained)
    checkpoint.signature = "0" * 64
    chained.flush()
    result = verify_range(chained)
    assert not result.valid
    assert result.checkpoint_failures


def test_checkpoint_over_rewritten_history_detected(chained):
    chain.checkpoint_now(chained)
    entry = chained.query(AuditEntry).filter_by(seq=12).one()
    entry.payload_json = {"rewritten": True}
    chained.flush()
    result = verify_range(chained)
    assert not result.valid


def test_payload_redacted_at_capture(session):
    """The audit log must not become a new PII liability (P5-5 / R8)."""
    entry = chain.append(
        session,
        "credential.issued",
        payload={
            "api_key": "sk-proj-supersecret",
            "nested": {"password": "hunter2"},
            "safe": "value",
        },
    )
    assert entry.payload_json["api_key"] == "<redacted>"
    assert entry.payload_json["nested"]["password"] == "<redacted>"
    assert entry.payload_json["safe"] == "value"


def test_long_strings_truncated(session):
    entry = chain.append(session, "x", payload={"blob": "a" * 5000})
    assert len(entry.payload_json["blob"]) < 2200
    assert "truncated" in entry.payload_json["blob"]


def test_no_orm_update_path_for_entries():
    """The absence of a mutation API is the control (P5-2)."""
    from agentfox.apps.gateway.routes import governance

    audit_routes = [
        (r.path, m)
        for r in governance.router.routes
        for m in getattr(r, "methods", set())
        if "/audit/entries" in getattr(r, "path", "")
    ]
    assert audit_routes, "expected a read route to exist"
    assert all(m == "GET" for _p, m in audit_routes), audit_routes


# ---------------------------------------------------------------------------
# Evidence packages (P5-3, P5-7)
# ---------------------------------------------------------------------------
