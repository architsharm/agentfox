"""The v2 entry digest covers who acted and on what, and old chains still verify.

v1 digested only seq, time, action and payload, so an entry's actor or subject could be
edited and `agentfox report verify` still said the chain was intact.
"""

from __future__ import annotations

import datetime as dt

from agentfox.core.models import AuditEntry
from agentfox.platform.ledger import chain


def _rows(session) -> list[dict]:
    return [chain.entry_to_row(e) for e in session.query(AuditEntry).order_by(AuditEntry.seq)]


def _append(session, n: int = 4) -> None:
    for i in range(n):
        chain.append(
            session,
            "test.event",
            actor_type="user",
            actor_id="aisha@example.com",
            subject_type="agent",
            subject_id=f"agt_{i}",
            payload={"i": i},
        )


def test_new_entries_are_v2_and_verify(session):
    _append(session)
    rows = _rows(session)
    assert {r["digest_version"] for r in rows} == {2}
    assert chain.verify(rows).valid
    assert chain.verify_range(session).valid


def test_an_actor_edit_breaks_the_chain(session):
    _append(session)
    entry = session.query(AuditEntry).filter_by(seq=2).one()
    entry.actor_id = "someone-else@example.com"
    session.flush()
    result = chain.verify_range(session)
    assert not result.valid
    assert result.first_break.kind == "digest_mismatch"
    assert result.first_break.seq == 2


def test_an_actor_type_edit_breaks_the_chain(session):
    _append(session)
    rows = _rows(session)
    rows[1]["actor_type"] = "automation"
    assert not chain.verify(rows).valid


def test_a_subject_edit_breaks_the_chain(session):
    _append(session)
    rows = _rows(session)
    rows[2]["subject_id"] = "agt_other"
    result = chain.verify(rows)
    assert not result.valid
    assert {b.kind for b in result.breaks} >= {"digest_mismatch"}

    rows = _rows(session)
    rows[2]["subject_type"] = "trace"
    assert not chain.verify(rows).valid


def test_relabelling_an_entry_as_v1_does_not_escape_the_actor_check(session):
    """A forger edits the actor of the newest entry, marks it v1 and recomputes the v1
    digest: there is no later entry whose prev_digest would break, so only the
    no-downgrade rule catches it."""
    _append(session)
    rows = _rows(session)
    last = rows[-1]
    last["actor_id"] = "forger"
    last["digest_version"] = 1
    last["digest"] = chain.compute_digest(
        last["seq"],
        dt.datetime.fromisoformat(last["occurred_at"]),
        last["action"],
        last["payload_digest"],
        last["prev_digest"],
    )
    result = chain.verify(rows)
    assert not result.valid
    assert [b.kind for b in result.breaks] == ["version_downgrade"]


def test_a_chain_written_under_v1_still_verifies(session):
    """Entries written before v2 keep verifying under the scheme they were written in,
    and a v2 entry can follow them."""
    prev = chain.GENESIS
    for seq in (1, 2):
        ts = dt.datetime(2026, 10, 1, 12, seq, tzinfo=dt.UTC)
        payload = {"seq": seq}
        payload_digest = chain.compute_payload_digest(payload)
        digest = chain.compute_digest(seq, ts, "legacy.event", payload_digest, prev)
        session.add(
            AuditEntry(
                seq=seq,
                occurred_at=ts,
                actor_type="user",
                actor_id="old@example.com",
                action="legacy.event",
                subject_type="",
                subject_id=None,
                payload_json=payload,
                payload_digest=payload_digest,
                prev_digest=prev,
                digest=digest,
            )
        )
        prev = digest
    session.flush()
    _append(session, 2)

    rows = _rows(session)
    assert [r["digest_version"] for r in rows] == [1, 1, 2, 2]
    assert chain.verify_range(session).valid
