"""Key rotation: previous keys keep data readable, rotation moves it to the current key.

Covers `core.crypto` (decrypt with a previous key), `platform.keys.rotation`
(re-encrypt, re-sign, the `audit.key_rotated` entry, idempotency, what it refuses to
touch), the scheduler hook, the CLI, `/api/version`, and that no key value ever leaves
the process in any of them.
"""

from __future__ import annotations

import json
import logging

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from agentfox.core.config import get_settings, reset_settings_cache
from agentfox.core.crypto import (
    DecryptionFailed,
    decrypt_secret,
    encrypt_secret,
    key_fingerprint,
)
from agentfox.core.db import session_scope
from agentfox.core.models import AgentSigningKey, AlertChannel, AuditCheckpoint, AuditEntry, Base
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.platform.keys import rotation
from agentfox.platform.ledger import chain

OLD_TOKEN_KEY = Fernet.generate_key().decode()
NEW_TOKEN_KEY = Fernet.generate_key().decode()
OLD_AUDIT_KEY = "old-audit-signing-key-0123456789abcdef"
NEW_AUDIT_KEY = "new-audit-signing-key-fedcba9876543210"
SECRETS = (OLD_TOKEN_KEY, NEW_TOKEN_KEY, OLD_AUDIT_KEY, NEW_AUDIT_KEY)


def _configure(monkeypatch, **env: str | None) -> None:
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    reset_settings_cache()
    rotation._reset_status_cache()


def _old_keys(monkeypatch) -> None:
    _configure(
        monkeypatch,
        AGENTFOX_TOKEN_ENCRYPTION_KEY=OLD_TOKEN_KEY,
        AGENTFOX_AUDIT_SIGNING_KEY=OLD_AUDIT_KEY,
        AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS=None,
        AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS=None,
    )


def _new_keys(monkeypatch, *, keep_previous: bool = True) -> None:
    _configure(
        monkeypatch,
        AGENTFOX_TOKEN_ENCRYPTION_KEY=NEW_TOKEN_KEY,
        AGENTFOX_AUDIT_SIGNING_KEY=NEW_AUDIT_KEY,
        AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS=OLD_TOKEN_KEY if keep_previous else None,
        AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS=OLD_AUDIT_KEY if keep_previous else None,
    )


def _seed_under_old_keys(monkeypatch, *, entries: int = 5) -> dict[str, str]:
    """Two encrypted rows and a checkpointed chain, all under the old keys."""
    _old_keys(monkeypatch)
    with session_scope() as s:
        bind_session(s, "org_default")
        channel = AlertChannel(
            kind="slack", url_encrypted=encrypt_secret("https://hooks.slack.com/x")
        )
        signing = AgentSigningKey(agent_id="agt_1", key_encrypted=encrypt_secret("hmac-secret"))
        s.add_all([channel, signing])
        s.flush()
        for i in range(entries):
            chain.append(s, "test.event", payload={"i": i})
        chain.checkpoint_now(s)
        ids = {"channel": channel.id, "signing": signing.id}
    return ids


def _report(s) -> dict:
    return rotation.rotate(s, actor_id="test")


# ---------------------------------------------------------------------------
# crypto
# ---------------------------------------------------------------------------


def test_decrypts_with_a_previous_key_and_encrypts_with_the_current_one(monkeypatch):
    _old_keys(monkeypatch)
    blob = encrypt_secret("ghp_example")
    _new_keys(monkeypatch)
    assert decrypt_secret(blob) == "ghp_example"
    fresh = encrypt_secret("ghp_example")
    assert Fernet(NEW_TOKEN_KEY.encode()).decrypt(fresh.encode()) == b"ghp_example"
    _new_keys(monkeypatch, keep_previous=False)
    with pytest.raises(DecryptionFailed):
        decrypt_secret(blob)


def test_previous_keys_parse_as_a_comma_separated_list(monkeypatch):
    third = Fernet.generate_key().decode()
    _configure(
        monkeypatch,
        AGENTFOX_TOKEN_ENCRYPTION_KEY=NEW_TOKEN_KEY,
        AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS=(
            f" {OLD_TOKEN_KEY} ,,{third},{NEW_TOKEN_KEY},{third}"
        ),
    )
    # Trimmed, deduplicated, and never the current key.
    assert get_settings().token_encryption_previous_keys == [OLD_TOKEN_KEY, third]


def test_fingerprint_is_short_stable_and_not_the_key():
    fp = key_fingerprint(NEW_AUDIT_KEY)
    assert fp == key_fingerprint(NEW_AUDIT_KEY) and len(fp) == 8
    assert fp not in NEW_AUDIT_KEY and fp != key_fingerprint(OLD_AUDIT_KEY)


def test_every_encrypted_column_is_rotated():
    """A new `*_encrypted` / `*_ciphertext` column that rotation does not know about
    would silently stay on the old key, and break when that key is removed."""
    covered = {rotation.field_name(model, attr) for model, attr in rotation.ENCRYPTED_FIELDS}
    found = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith(("_encrypted", "_ciphertext"))
    }
    assert found == covered


# ---------------------------------------------------------------------------
# audit chain
# ---------------------------------------------------------------------------


def test_checkpoints_record_the_key_fingerprint(monkeypatch):
    _old_keys(monkeypatch)
    with session_scope() as s:
        chain.append(s, "test.event", payload={})
        cp = chain.checkpoint_now(s)
        assert cp.key_id == key_fingerprint(OLD_AUDIT_KEY)
        assert cp.org_id == "org_default"


def test_chain_verifies_across_a_key_change(monkeypatch):
    _seed_under_old_keys(monkeypatch)
    _new_keys(monkeypatch)
    with session_scope() as s:
        chain.append(s, "after.change", payload={})
        chain.checkpoint_now(s)
        result = chain.verify_range(s)
        assert result.valid, result.to_json()
        assert result.checkpoints_checked == 2
    # Without the previous key, the old checkpoint no longer verifies.
    _new_keys(monkeypatch, keep_previous=False)
    with session_scope() as s:
        result = chain.verify_range(s)
        assert not result.valid
        assert [f["seq"] for f in result.checkpoint_failures] == [5]


def test_verify_takes_one_key_or_several(monkeypatch):
    _seed_under_old_keys(monkeypatch)
    with session_scope() as s:
        rows = [chain.entry_to_row(e) for e in s.scalars(select(AuditEntry))]
        cps = [
            {"seq": c.seq, "digest": c.digest, "signature": c.signature, "key_id": c.key_id}
            for c in s.scalars(select(AuditCheckpoint))
        ]
    assert chain.verify(rows, cps, signing_key=OLD_AUDIT_KEY).valid
    assert not chain.verify(rows, cps, signing_key=NEW_AUDIT_KEY).valid
    assert chain.verify(rows, cps, signing_key=[NEW_AUDIT_KEY, OLD_AUDIT_KEY]).valid


# ---------------------------------------------------------------------------
# rotation
# ---------------------------------------------------------------------------


def test_rotate_reencrypts_resigns_and_records_it(monkeypatch):
    ids = _seed_under_old_keys(monkeypatch)
    _new_keys(monkeypatch)
    with session_scope() as s:
        before = rotation.status(s)
        assert before["token_encryption"]["state"] == "pending"
        assert before["audit_signing"]["state"] == "pending"
        report = _report(s)
    enc, sig = report["token_encryption"], report["audit_signing"]
    assert enc["reencrypted"] == 2 and enc["undecryptable"] == 0
    assert sig["resigned"] == 1 and sig["entries_written"] == 1
    assert enc["state"] == "complete" and sig["state"] == "complete"
    assert report["changed"] is True

    new_fernet = Fernet(NEW_TOKEN_KEY.encode())
    with session_scope() as s:
        channel = s.get(AlertChannel, ids["channel"])
        assert new_fernet.decrypt(channel.url_encrypted.encode()) == b"https://hooks.slack.com/x"
        signing = s.get(AgentSigningKey, ids["signing"])
        assert new_fernet.decrypt(signing.key_encrypted.encode()) == b"hmac-secret"

        entry = s.scalars(
            select(AuditEntry).where(AuditEntry.action == rotation.ROTATED_ACTION)
        ).one()
        payload = entry.payload_json
        assert payload["encryption"]["from"] == [key_fingerprint(OLD_TOKEN_KEY)]
        assert payload["encryption"]["to"] == key_fingerprint(NEW_TOKEN_KEY)
        assert payload["encryption"]["rows_reencrypted"] == 2
        assert {f["field"] for f in payload["encryption"]["fields"]} == {
            "alert_channels.url_encrypted",
            "agent_signing_keys.key_encrypted",
        }
        assert payload["signing"] == {
            "from": [key_fingerprint(OLD_AUDIT_KEY)],
            "to": key_fingerprint(NEW_AUDIT_KEY),
            "checkpoints_resigned": 1,
            "verified_through_seq": 5,
        }
        # A checkpoint at the new head, signed with the new key.
        head = s.scalars(select(AuditCheckpoint).order_by(AuditCheckpoint.seq.desc())).first()
        assert head.seq == entry.seq
        assert head.signature == chain.sign(head.digest, NEW_AUDIT_KEY)
        assert head.key_id == key_fingerprint(NEW_AUDIT_KEY)

    # With the previous keys gone, everything still decrypts and verifies.
    _new_keys(monkeypatch, keep_previous=False)
    with session_scope() as s:
        assert chain.verify_range(s).valid
        assert decrypt_secret(s.get(AgentSigningKey, ids["signing"]).key_encrypted) == "hmac-secret"


def test_a_second_rotation_is_a_no_op(monkeypatch):
    _seed_under_old_keys(monkeypatch)
    _new_keys(monkeypatch)
    with session_scope() as s:
        _report(s)
    with session_scope() as s:
        snapshot = {c.id: (c.signature, c.key_id) for c in s.scalars(select(AuditCheckpoint))} | {
            r.id: r.key_encrypted for r in s.scalars(select(AgentSigningKey))
        }
        entries = s.query(AuditEntry).count()
        again = _report(s)
    assert again["changed"] is False
    assert again["token_encryption"]["reencrypted"] == 0
    assert again["audit_signing"]["resigned"] == 0
    assert again["audit_signing"]["entries_written"] == 0
    with session_scope() as s:
        assert s.query(AuditEntry).count() == entries
        after = {c.id: (c.signature, c.key_id) for c in s.scalars(select(AuditCheckpoint))} | {
            r.id: r.key_encrypted for r in s.scalars(select(AgentSigningKey))
        }
    assert after == snapshot


def test_an_undecryptable_row_is_reported_and_left_untouched(monkeypatch):
    ids = _seed_under_old_keys(monkeypatch)
    stranger = Fernet(Fernet.generate_key()).encrypt(b"lost").decode()
    with session_scope() as s:
        bind_session(s, "org_default")
        s.get(AlertChannel, ids["channel"]).url_encrypted = stranger
    _new_keys(monkeypatch)
    with session_scope() as s:
        report = _report(s)
    enc = report["token_encryption"]
    assert enc["undecryptable"] == 1 and enc["reencrypted"] == 1
    field = next(f for f in enc["fields"] if f["field"] == "alert_channels.url_encrypted")
    assert field["undecryptable_ids"] == [ids["channel"]]
    with session_scope() as s:
        assert s.get(AlertChannel, ids["channel"]).url_encrypted == stranger


def test_a_broken_chain_is_not_resigned(monkeypatch):
    _seed_under_old_keys(monkeypatch)
    with session_scope() as s, system_scope("test: tampering"):
        entry = s.scalars(select(AuditEntry).where(AuditEntry.seq == 2)).one()
        entry.payload_json = {"i": "tampered"}
    _new_keys(monkeypatch)
    with session_scope() as s:
        report = _report(s)
    item = report["audit_signing"]["chains"][0]
    assert item["state"] == "chain_broken"
    assert report["audit_signing"]["resigned"] == 0
    assert report["audit_signing"]["state"] == "pending"
    with session_scope() as s:
        cp = s.scalars(select(AuditCheckpoint).where(AuditCheckpoint.seq == 5)).one()
        assert cp.signature == chain.sign(cp.digest, OLD_AUDIT_KEY)
        # The rotation itself is still recorded (secrets were re-encrypted), but no
        # checkpoint is signed over the damage.
        rotated = s.scalars(
            select(AuditEntry).where(AuditEntry.action == rotation.ROTATED_ACTION)
        ).one()
        assert "signing" not in rotated.payload_json
        assert (
            s.scalars(select(AuditCheckpoint).where(AuditCheckpoint.seq == rotated.seq)).first()
            is None
        )


def test_status_without_previous_keys_is_not_configured(monkeypatch):
    _seed_under_old_keys(monkeypatch)
    with session_scope() as s:
        report = rotation.status(s)
    assert report["token_encryption"]["state"] == "not_configured"
    assert report["audit_signing"]["state"] == "not_configured"
    assert rotation.status_summary() == {
        "token_encryption": "not_configured",
        "audit_signing": "not_configured",
    }


def test_an_invalid_fernet_key_is_misconfigured_and_named_not_shown(monkeypatch):
    bad = "a" * 64  # what `openssl rand -hex 32` produces: not a Fernet key
    _configure(monkeypatch, AGENTFOX_TOKEN_ENCRYPTION_KEY=bad)
    assert rotation.status_summary()["token_encryption"] == "misconfigured"
    _configure(monkeypatch, AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS=OLD_TOKEN_KEY)
    with session_scope() as s:
        report = rotation.status(s)
    assert report["token_encryption"]["state"] == "misconfigured"
    assert "AGENTFOX_TOKEN_ENCRYPTION_KEY" in report["token_encryption"]["detail"]
    assert bad not in json.dumps(report)


# ---------------------------------------------------------------------------
# scheduler, CLI, /api/version
# ---------------------------------------------------------------------------


def test_the_job_runner_rotates_when_a_previous_key_is_set(monkeypatch):
    from agentfox.apps import jobs as _registers_kinds  # noqa: F401
    from agentfox.core.models import Job
    from agentfox.platform.jobs.scheduler import run_due

    _seed_under_old_keys(monkeypatch)
    with session_scope() as s:
        assert run_due(s)["key_rotation"] is None  # no previous key: nothing
    _new_keys(monkeypatch)
    with session_scope() as s:
        result = run_due(s)
    outcome = result["key_rotation"]
    assert outcome["status"] == "done", outcome
    assert outcome["reencrypted"] == 2 and outcome["resigned"] == 1
    assert outcome["token_encryption"] == outcome["audit_signing"] == "complete"
    assert not any(secret in json.dumps(result) for secret in SECRETS)
    with session_scope() as s, system_scope("test"):
        job = s.get(Job, outcome["job"])
        assert job.status == "done", job.last_error
        assert job.result_json["token_encryption"]["reencrypted"] == 2
    assert rotation.status_summary(fresh=True) == {
        "token_encryption": "complete",
        "audit_signing": "complete",
    }
    with session_scope() as s:
        assert run_due(s)["key_rotation"] is None  # complete: nothing more to do


def test_cli_status_and_rotate(monkeypatch):
    from typer.testing import CliRunner

    from agentfox.apps.cli.main import app

    _seed_under_old_keys(monkeypatch)
    _new_keys(monkeypatch)
    runner = CliRunner()
    status = runner.invoke(app, ["admin", "keys", "status", "--json"])
    assert status.exit_code == 0, status.output
    data = json.loads(status.output)
    assert data["token_encryption"]["state"] == "pending"
    assert data["token_encryption"]["current"] == key_fingerprint(NEW_TOKEN_KEY)
    assert data["token_encryption"]["previous"] == [key_fingerprint(OLD_TOKEN_KEY)]
    assert data["audit_signing"]["previous"] == [key_fingerprint(OLD_AUDIT_KEY)]

    rotated = runner.invoke(app, ["admin", "keys", "rotate"])
    assert rotated.exit_code == 0, rotated.output
    assert "re-encrypted 2 value(s), re-signed 1 checkpoint(s)" in " ".join(rotated.output.split())
    status = runner.invoke(app, ["admin", "keys", "status"])
    assert "complete" in status.output and "can be removed" in " ".join(status.output.split())
    for text in (status.output, rotated.output):
        assert not any(secret in text for secret in SECRETS)


def test_version_reports_rotation_state_without_secrets(monkeypatch, client):
    _seed_under_old_keys(monkeypatch)
    _new_keys(monkeypatch)
    body = client.get("/api/version").json()
    assert body["key_rotation"] == {"token_encryption": "pending", "audit_signing": "pending"}
    with session_scope() as s:
        _report(s)
    body = client.get("/api/version").json()
    assert body["key_rotation"] == {"token_encryption": "complete", "audit_signing": "complete"}
    text = json.dumps(body)
    assert not any(secret in text for secret in SECRETS)
    assert key_fingerprint(NEW_AUDIT_KEY) not in text  # states only on a public route


def test_no_key_value_reaches_logs_audit_entries_or_reports(monkeypatch, caplog):
    _seed_under_old_keys(monkeypatch)
    _new_keys(monkeypatch)
    caplog.set_level(logging.DEBUG)
    with session_scope() as s:
        reports = [rotation.status(s), _report(s), rotation.status(s)]
    with session_scope() as s, system_scope("test"):
        entries = [e.payload_json for e in s.scalars(select(AuditEntry))]
    haystack = json.dumps([reports, entries]) + caplog.text
    for secret in SECRETS:
        assert secret not in haystack


def test_rotation_is_atomic_per_column(monkeypatch):
    """A failure part-way through a column rolls that whole column back; the other
    columns still rotate."""
    _old_keys(monkeypatch)
    with session_scope() as s:
        for org in ("org_a", "org_b"):
            bind_session(s, org)
            s.add(AlertChannel(kind="slack", url_encrypted=encrypt_secret(f"https://{org}")))
            s.flush()
        bind_session(s, "org_a")
        s.add(AgentSigningKey(agent_id="agt_1", key_encrypted=encrypt_secret("hmac")))
    with session_scope() as s, system_scope("test"):
        before = {c.id: c.url_encrypted for c in s.scalars(select(AlertChannel))}
    _new_keys(monkeypatch)

    real_encrypt = Fernet.encrypt
    calls = {"n": 0}

    def flaky(self, data):
        calls["n"] += 1
        if calls["n"] == 3:  # agent_signing_keys first (1 row), then the 2nd channel
            raise RuntimeError("disk full")
        return real_encrypt(self, data)

    monkeypatch.setattr(Fernet, "encrypt", flaky)
    order = [f for f in rotation.ENCRYPTED_FIELDS]
    order.sort(key=lambda f: f[0] is not AgentSigningKey)
    monkeypatch.setattr(rotation, "ENCRYPTED_FIELDS", tuple(order))
    with session_scope() as s:
        report = _report(s)
    fields = {f["field"]: f for f in report["token_encryption"]["fields"]}
    assert fields["agent_signing_keys.key_encrypted"]["reencrypted"] == 1
    assert fields["alert_channels.url_encrypted"]["reencrypted"] == 0
    assert "rolled back" in fields["alert_channels.url_encrypted"]["error"]
    assert report["token_encryption"]["state"] == "pending"
    with session_scope() as s, system_scope("test"):
        after = {c.id: c.url_encrypted for c in s.scalars(select(AlertChannel))}
    assert after == before


def test_an_unfinishable_rotation_is_retried_hourly_or_when_keys_change(monkeypatch):
    from agentfox.apps import jobs as _registers_kinds  # noqa: F401
    from agentfox.platform.jobs.scheduler import run_due

    _seed_under_old_keys(monkeypatch)
    with session_scope() as s, system_scope("test: tampering"):
        s.scalars(select(AuditEntry).where(AuditEntry.seq == 2)).one().payload_json = {"x": 1}
    _new_keys(monkeypatch)
    with session_scope() as s:
        first = run_due(s)["key_rotation"]
    assert first["status"] == "done" and first["chains_not_rotated"] == 1
    assert first["audit_signing"] == "pending"
    with session_scope() as s:
        assert run_due(s)["key_rotation"] is None  # same keys, within the hour
    _configure(monkeypatch, AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS=f"{OLD_AUDIT_KEY},another")
    with session_scope() as s:
        assert run_due(s)["key_rotation"] is not None  # keys changed: retried at once
