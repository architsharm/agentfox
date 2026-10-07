"""Move stored data off retired keys: re-encrypt secrets, re-sign audit checkpoints.

Two keys protect data that outlives a deploy:

* ``AGENTFOX_TOKEN_ENCRYPTION_KEY`` encrypts every secret held at rest
  (:data:`ENCRYPTED_FIELDS`).
* ``AGENTFOX_AUDIT_SIGNING_KEY`` signs audit checkpoints.

Each has a ``*_PREVIOUS`` companion (comma-separated retired keys). While a previous
key is configured, reads keep working: decryption and checkpoint verification try it
after the current key. :func:`rotate` then moves everything onto the current key, so
the previous one can be deleted:

1. **Encrypted columns**, one table column at a time inside a savepoint (atomic per
   column): a value that decrypts only under a previous key is re-encrypted under the
   current one. A value no configured key decrypts is reported by row id and left
   exactly as it is.
2. **Audit chains**, one tenant at a time inside a savepoint: the whole chain is
   verified under every configured key first. Only an intact chain has its
   previous-key checkpoints re-signed with the current key — re-signing a tampered
   chain would launder it. Then one ``audit.key_rotated`` entry records the key
   fingerprints (never the keys) and the counts, and a checkpoint at the new head is
   signed with the current key.

Idempotent: a second run finds nothing on a previous key and writes nothing, and no
audit entry is appended when nothing changed. :func:`status` is the same pass with
no writes. Fingerprints are :func:`agentfox.core.crypto.key_fingerprint` — the first
8 hex characters of the key's SHA-256 — so every report can say *which* key without
revealing anything usable about it.

Triggered by ``agentfox admin keys rotate``, or automatically: the job runner
(:func:`agentfox.platform.jobs.scheduler.run_due`, i.e. ``/api/internal/jobs/run``)
calls :func:`enqueue_if_pending`, which costs nothing when no previous key is set.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.crypto import (
    DecryptionFailed,
    InvalidEncryptionKey,
    decrypt_with,
    key_fingerprint,
    keyring,
)
from agentfox.core.models import (
    AgentSigningKey,
    AlertChannel,
    AuditCheckpoint,
    AuditEntry,
    GithubConnection,
    Job,
    ProbeTarget,
    SourceConnection,
    utcnow,
)
from agentfox.core.tenancy import system_scope
from agentfox.platform.ledger import chain

log = logging.getLogger(__name__)

ROTATED_ACTION = "audit.key_rotated"
JOB_KIND = "keys.rotate"

#: Every column that holds a value encrypted with `core.crypto`. A new encrypted
#: column must be added here, or rotation silently leaves it on the old key:
#: `tests/platform/test_key_rotation.py` fails for any `*_encrypted` / `*_ciphertext`
#: column that is missing.
ENCRYPTED_FIELDS: tuple[tuple[type, str], ...] = (
    (GithubConnection, "access_token_encrypted"),
    (GithubConnection, "webhook_secret_encrypted"),
    (SourceConnection, "credential_encrypted"),
    (AlertChannel, "url_encrypted"),
    (ProbeTarget, "auth_header_ciphertext"),
    (AgentSigningKey, "key_encrypted"),
)

#: Rotation states, per key.
NOT_CONFIGURED = "not_configured"  # no previous key is set: nothing to rotate from
PENDING = "pending"  # some data or checkpoint still needs a previous key
COMPLETE = "complete"  # a previous key is set, and nothing needs it any more
MISCONFIGURED = "misconfigured"  # a configured key cannot be used (named, never shown)

#: How long :func:`status_summary` reuses an answer, and how long after a finished
#: rotation job the scheduler waits before enqueuing another one that could not
#: finish (a broken chain stays pending until a person looks at it).
STATUS_TTL_SECONDS = 60
RETRY_AFTER = dt.timedelta(hours=1)


def field_name(model: type, attr: str) -> str:
    return f"{model.__tablename__}.{attr}"  # type: ignore[attr-defined]


@contextlib.contextmanager
def _savepoint(session: Session, write: bool) -> Iterator[None]:
    if write:
        with session.begin_nested():
            yield
    else:
        yield


# ---------------------------------------------------------------------------
# Encrypted columns
# ---------------------------------------------------------------------------


def _scan_encrypted(session: Session, *, write: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-encrypt (``write``) or count what still needs a previous key.

    Returns the report and, per tenant, what was re-encrypted there (for its audit
    entry): ``{org_id: {"rows": n, "fields": {field: n}, "from": {fingerprint}}}``.
    """
    settings = get_settings()
    previous = settings.token_encryption_previous_keys
    report: dict[str, Any] = {
        "state": NOT_CONFIGURED,
        "current": key_fingerprint(settings.token_encryption_key)
        if settings.token_encryption_key
        else None,
        "previous": [key_fingerprint(k) for k in previous],
        "fields": [],
        "rows_on_previous_key": 0,
        "reencrypted": 0,
        "undecryptable": 0,
    }
    by_org: dict[str, Any] = {}
    if not settings.token_encryption_key:
        if previous:
            report["state"] = MISCONFIGURED
            report["detail"] = (
                "AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS is set but "
                "AGENTFOX_TOKEN_ENCRYPTION_KEY is not: there is no key to rotate to."
            )
        return report, by_org
    try:
        ring = keyring()
    except InvalidEncryptionKey as exc:
        report["state"] = MISCONFIGURED
        report["detail"] = str(exc)
        return report, by_org
    current = ring[0][1]

    for model, attr in ENCRYPTED_FIELDS:
        column = getattr(model, attr)
        field = {
            "field": field_name(model, attr),
            "rows": 0,
            "on_current_key": 0,
            "on_previous_key": 0,
            "reencrypted": 0,
            "undecryptable_ids": [],
        }
        changed: dict[str, Any] = {}
        try:
            with _savepoint(session, write):
                rows = list(session.scalars(select(model).where(column.is_not(None), column != "")))
                for row in rows:
                    field["rows"] += 1
                    try:
                        plaintext, index = decrypt_with(getattr(row, attr), ring)
                    except DecryptionFailed:
                        field["undecryptable_ids"].append(row.id)
                        continue
                    if index == 0:
                        field["on_current_key"] += 1
                        continue
                    field["on_previous_key"] += 1
                    if not write:
                        continue
                    setattr(row, attr, current.encrypt(plaintext.encode()).decode())
                    field["reencrypted"] += 1
                    org = changed.setdefault(row.org_id, {"rows": 0, "fields": {}, "from": set()})
                    org["rows"] += 1
                    org["fields"][field["field"]] = org["fields"].get(field["field"], 0) + 1
                    org["from"].add(ring[index][0])
                if write:
                    session.flush()
        except Exception as exc:  # noqa: BLE001 - one column failing must not stop the rest
            # The savepoint is rolled back: nothing in this column changed.
            log.warning("key rotation: %s left unchanged: %s", field["field"], type(exc).__name__)
            field["error"] = f"{type(exc).__name__}: rolled back, nothing in this column changed"
            field["reencrypted"] = 0
            changed = {}
        for org_id, counts in changed.items():
            target = by_org.setdefault(org_id, {"rows": 0, "fields": {}, "from": set()})
            target["rows"] += counts["rows"]
            target["from"] |= counts["from"]
            for name, n in counts["fields"].items():
                target["fields"][name] = target["fields"].get(name, 0) + n
        report["fields"].append(field)
        report["reencrypted"] += field["reencrypted"]
        report["rows_on_previous_key"] += field["on_previous_key"] - field["reencrypted"]
        report["undecryptable"] += len(field["undecryptable_ids"])

    if previous:
        report["state"] = PENDING if report["rows_on_previous_key"] else COMPLETE
    return report, by_org


# ---------------------------------------------------------------------------
# Audit checkpoints
# ---------------------------------------------------------------------------


def _checkpoint_row(cp: AuditCheckpoint) -> dict[str, Any]:
    return {"seq": cp.seq, "digest": cp.digest, "signature": cp.signature, "key_id": cp.key_id}


def _verify_chain(session: Session, org_id: str, keys: list[str]) -> chain.VerificationResult:
    entries = session.scalars(
        select(AuditEntry).where(AuditEntry.org_id == org_id).order_by(AuditEntry.seq)
    )
    checkpoints = session.scalars(
        select(AuditCheckpoint)
        .where(AuditCheckpoint.org_id == org_id)
        .order_by(AuditCheckpoint.seq)
    )
    return chain.verify(
        [chain.entry_to_row(e) for e in entries],
        [_checkpoint_row(c) for c in checkpoints],
        signing_key=keys,
    )


def _scan_checkpoints(
    session: Session,
    *,
    write: bool,
    encrypted_by_org: dict[str, Any],
    token_fingerprint: str | None,
    actor_type: str,
    actor_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    current = settings.audit_signing_key
    previous = settings.audit_signing_previous_keys
    keys = [current, *previous]
    current_fp = key_fingerprint(current)
    report: dict[str, Any] = {
        "state": NOT_CONFIGURED,
        "current": current_fp,
        "previous": [key_fingerprint(k) for k in previous],
        "chains": [],
        "checkpoints_on_previous_key": 0,
        "resigned": 0,
        "unverifiable": 0,
        "entries_written": 0,
    }
    orgs = set(session.scalars(select(AuditCheckpoint.org_id).distinct())) | set(encrypted_by_org)
    for org_id in sorted(o for o in orgs if o):
        checkpoints = list(
            session.scalars(
                select(AuditCheckpoint)
                .where(AuditCheckpoint.org_id == org_id)
                .order_by(AuditCheckpoint.seq)
            )
        )
        item: dict[str, Any] = {
            "org_id": org_id,
            "checkpoints": len(checkpoints),
            "on_current_key": 0,
            "on_previous_key": 0,
            "unverifiable": 0,
            "resigned": 0,
            "state": "ok",
        }
        on_previous: list[AuditCheckpoint] = []
        relabel: list[AuditCheckpoint] = []
        used: set[str] = set()
        for cp in checkpoints:
            signer = chain.checkpoint_signer(_checkpoint_row(cp), keys)
            if signer is None:
                item["unverifiable"] += 1
            elif signer == current:
                item["on_current_key"] += 1
                if cp.key_id != current_fp:
                    relabel.append(cp)
            else:
                item["on_previous_key"] += 1
                on_previous.append(cp)
                used.add(key_fingerprint(signer))
        encrypted = encrypted_by_org.get(org_id)
        if item["unverifiable"]:
            item["state"] = "unverifiable_checkpoints"

        if write and (on_previous or relabel or encrypted):
            try:
                with session.begin_nested():
                    # A checkpoint's key_id was "local" before fingerprints existed. One
                    # that verifies under the current key only needs its label fixed;
                    # the signature, which is what counts, is untouched.
                    for cp in relabel:
                        cp.key_id = current_fp
                    verified = None
                    if on_previous or encrypted:
                        verified = _verify_chain(session, org_id, keys)
                        if not verified.valid:
                            item["state"] = "chain_broken"
                            item["breaks"] = len(verified.breaks) + len(
                                verified.checkpoint_failures
                            )
                    if on_previous and verified is not None and verified.valid:
                        for cp in on_previous:
                            cp.signature = chain.sign(cp.digest, current)
                            cp.key_id = current_fp
                        item["resigned"] = len(on_previous)
                    if item["resigned"] or encrypted:
                        payload: dict[str, Any] = {"reason": "key rotation"}
                        if encrypted:
                            payload["encryption"] = {
                                "from": sorted(encrypted["from"]),
                                "to": token_fingerprint,
                                "rows_reencrypted": encrypted["rows"],
                                "fields": [
                                    {"field": name, "rows": n}
                                    for name, n in sorted(encrypted["fields"].items())
                                ],
                            }
                        if item["resigned"]:
                            payload["signing"] = {
                                "from": sorted(used),
                                "to": current_fp,
                                "checkpoints_resigned": item["resigned"],
                                "verified_through_seq": verified.last_seq if verified else None,
                            }
                        entry = chain.append(
                            session,
                            ROTATED_ACTION,
                            actor_type=actor_type,
                            actor_id=actor_id,
                            subject_type="deployment",
                            payload=payload,
                            org_id=org_id,
                        )
                        report["entries_written"] += 1
                        # Anchor the new head under the current key — but never over a
                        # chain that failed verification: that would sign the damage.
                        intact = verified is not None and verified.valid
                        already = session.scalar(
                            select(AuditCheckpoint.id).where(
                                AuditCheckpoint.org_id == org_id,
                                AuditCheckpoint.seq == entry.seq,
                            )
                        )
                        if intact and already is None:
                            chain.write_checkpoint(session, entry)
                        item["state"] = "rotated" if intact else item["state"]
                    session.flush()
            except Exception as exc:  # noqa: BLE001 - one chain failing must not stop the rest
                log.warning("key rotation: chain %s left unchanged: %s", org_id, type(exc).__name__)
                item["state"] = "error"
                item["error"] = f"{type(exc).__name__}: rolled back, this chain is unchanged"
                item["resigned"] = 0

        report["chains"].append(item)
        report["resigned"] += item["resigned"]
        report["checkpoints_on_previous_key"] += item["on_previous_key"] - item["resigned"]
        report["unverifiable"] += item["unverifiable"]

    if previous:
        report["state"] = PENDING if report["checkpoints_on_previous_key"] else COMPLETE
    return report


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def rotate(
    session: Session,
    *,
    dry_run: bool = False,
    actor_type: str = "system",
    actor_id: str = "key-rotation",
) -> dict[str, Any]:
    """Move every encrypted value and audit checkpoint onto the current keys.

    ``dry_run`` changes nothing and reports what a real run would do (that is
    :func:`status`). The caller commits. Safe to run any number of times.
    """
    reason = (
        "key rotation status: counting what still needs a previous key, across every tenant"
        if dry_run
        else "key rotation: re-encrypting secrets and re-signing checkpoints in every tenant"
    )
    with system_scope(reason, routine=dry_run):
        encryption, by_org = _scan_encrypted(session, write=not dry_run)
        signing = _scan_checkpoints(
            session,
            write=not dry_run,
            encrypted_by_org=by_org,
            token_fingerprint=encryption["current"],
            actor_type=actor_type,
            actor_id=actor_id,
        )
    _reset_status_cache()
    return {
        "dry_run": dry_run,
        "token_encryption": encryption,
        "audit_signing": signing,
        "changed": bool(
            encryption["reencrypted"] or signing["resigned"] or signing["entries_written"]
        ),
    }


def status(session: Session) -> dict[str, Any]:
    """Fingerprints in use, and whether any data or checkpoint still needs a previous
    key. Changes nothing."""
    return rotate(session, dry_run=True)


def _previous_configured() -> tuple[bool, bool]:
    settings = get_settings()
    return (
        bool(settings.token_encryption_previous_keys),
        bool(settings.audit_signing_previous_keys),
    )


def _config_fingerprint() -> str:
    """One fingerprint over every configured key: changes whenever any key does."""
    settings = get_settings()
    return key_fingerprint(
        "|".join(
            [
                settings.token_encryption_key or "",
                *settings.token_encryption_previous_keys,
                "",
                settings.audit_signing_key,
                *settings.audit_signing_previous_keys,
            ]
        )
    )


def _token_key_state() -> str:
    """``misconfigured`` when a set encryption key is not a usable Fernet key (no
    database access): every encrypt and decrypt would fail, and this says so."""
    if not get_settings().token_encryption_key:
        return NOT_CONFIGURED
    try:
        keyring()
    except InvalidEncryptionKey:
        return MISCONFIGURED
    return NOT_CONFIGURED


_cache_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _reset_status_cache() -> None:
    with _cache_lock:
        _cache.clear()


def status_summary(session: Session | None = None, *, fresh: bool = False) -> dict[str, str]:
    """``{"token_encryption": state, "audit_signing": state}``, safe to publish.

    No database access at all when no previous key is configured (the normal case).
    Otherwise reuses an answer for :data:`STATUS_TTL_SECONDS`, so a public route can
    show it without turning every request into a scan.
    """
    token_prev, audit_prev = _previous_configured()
    if not (token_prev or audit_prev):
        return {"token_encryption": _token_key_state(), "audit_signing": NOT_CONFIGURED}
    cache_key = _config_fingerprint()
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(cache_key)
        if hit and not fresh and now - hit[0] < STATUS_TTL_SECONDS:
            return dict(hit[1])

    def _compute(s: Session) -> dict[str, str]:
        report = status(s)
        return {
            "token_encryption": report["token_encryption"]["state"],
            "audit_signing": report["audit_signing"]["state"],
        }

    if session is not None:
        value = _compute(session)
    else:
        from agentfox.core.db import session_scope

        with session_scope() as own:
            value = _compute(own)
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), dict(value))
    return value


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def enqueue_if_pending(session: Session) -> str | None:
    """Put one ``keys.rotate`` job on the queue when rotation has work to do.

    Free when no previous key is configured. Otherwise enqueues only if something is
    still on a previous key, no rotation job is already pending or running, and none
    finished in the last :data:`RETRY_AFTER` with the same keys configured (a chain
    that fails verification stays pending until a person fixes it, and retrying it
    every cron call helps nobody; a change of keys is worth an immediate retry).
    Returns the job id, or ``None``.
    """
    if not any(_previous_configured()):
        return None
    from agentfox.platform.jobs import store as jobs_db
    from agentfox.platform.jobs.queue import DEAD, DONE, RUNNING
    from agentfox.platform.jobs.queue import PENDING as JOB_PENDING
    from agentfox.platform.ledger.system_log import SYSTEM_ORG_ID

    if not jobs_db.is_registered(JOB_KIND):
        return None
    if PENDING not in status_summary(session, fresh=True).values():
        return None
    now = utcnow()
    with system_scope("key rotation: looking for an earlier keys.rotate job", routine=True):
        latest = session.scalars(
            select(Job).where(Job.kind == JOB_KIND).order_by(Job.enqueued_at.desc()).limit(1)
        ).first()
    if latest is not None:
        if latest.status in (JOB_PENDING, RUNNING):
            return None
        finished = _aware(latest.finished_at)
        same_keys = (latest.payload_json or {}).get("config") == _config_fingerprint()
        recent = finished is not None and now - finished < RETRY_AFTER
        if latest.status in (DONE, DEAD) and recent and same_keys:
            return None
    job = jobs_db.enqueue(
        session,
        JOB_KIND,
        {"actor_type": "system", "requested_by": "key-rotation", "config": _config_fingerprint()},
        org_id=SYSTEM_ORG_ID,
        requested_by="scheduler:key-rotation",
    )
    return job.id
