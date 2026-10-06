"""Tamper-evident audit log (NOM-AUD-02).

"Immutable" in most products means "we did not build a DELETE endpoint". That does
not survive an auditor. This is a genuine hash chain:

    payload_digest = SHA-256(canonical_json(payload))
    digest         = SHA-256(seq | occurred_at | action | payload_digest | prev_digest)

with periodic checkpoints signed by a key held **outside** the application database,
and a verifier that detects insertion, deletion, reordering and mutation.

Two properties make it credible rather than decorative:

1. :func:`verify` is a **pure function over exported rows**. A third party can run
   it against an evidence package with no access to our systems.
2. There is no update or delete path anywhere in the codebase for ``AuditEntry``.

This is cheap to build correctly at the start and effectively impossible to
retrofit — the entries you already wrote were never chained.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import AuditCheckpoint, AuditEntry, utcnow

#: prev_digest of the first entry. Fixed so an empty chain still verifies.
GENESIS = "0" * 64


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_payload_digest(payload: dict[str, Any]) -> str:
    return sha256(canonical_json(payload))


def compute_digest(
    seq: int, occurred_at: dt.datetime, action: str, payload_digest: str, prev_digest: str
) -> str:
    ts = (
        occurred_at.astimezone(dt.UTC).isoformat()
        if occurred_at.tzinfo
        else occurred_at.isoformat()
    )
    return sha256(f"{seq}|{ts}|{action}|{payload_digest}|{prev_digest}")


# ---------------------------------------------------------------------------
# Redaction at capture
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "key",
    "credential",
    "private_key",
    "access_key",
    "ssn",
}


def redact_payload(payload: Any, depth: int = 0) -> Any:
    """Strip obviously-sensitive values before they reach the chain.

    The audit log must not become the exact PII honeypot customers are afraid of.
    Detectors already store redacted samples with offsets; the
    chain stores structure and decisions, not raw content.
    """
    if depth > 8:
        return "<max-depth>"
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if any(marker in str(key).lower() for marker in _SENSITIVE_KEYS):
                out[key] = "<redacted>"
            else:
                out[key] = redact_payload(value, depth + 1)
        return out
    if isinstance(payload, list):
        return [redact_payload(v, depth + 1) for v in payload[:200]]
    if isinstance(payload, str) and len(payload) > 2000:
        return payload[:2000] + f"…<truncated {len(payload) - 2000} chars>"
    return payload


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------


def append(
    session: Session,
    action: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    subject_type: str = "",
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
    occurred_at: dt.datetime | None = None,
    org_id: str | None = None,
) -> AuditEntry:
    """Append one entry. The only write path for :class:`AuditEntry`.

    ``org_id`` names the chain this entry joins explicitly. It defaults to the
    session's own bound tenant (:func:`agentfox.core.tenancy.session_org`) — the ordinary
    case — but is accepted as an override for the one caller that has no ambient
    tenant to inherit: :mod:`agentfox.prove.audit.system_log`, appending to the reserved
    system-level chain from inside :func:`agentfox.core.tenancy.system_scope`.

    The "last entry" lookup below filters on this org explicitly rather than trusting
    :mod:`agentfox.core.tenancy`'s session-level ``with_loader_criteria`` hook to have done
    it, because that hook is *disabled* for the whole session inside
    ``system_scope`` (by design — reading across every tenant needs an unfiltered
    query). A caller that binds the session to a real tenant and then appends from
    inside ``system_scope`` — exactly what minting an operator token does, since the
    recipient's tenant is only known after a cross-tenant lookup — would otherwise
    have this query see every tenant's rows merged into one sequence instead of just
    its own, computing a ``seq``/``prev_digest`` against whichever tenant's chain
    runs furthest, not the one the entry is actually joining.
    """
    settings = get_settings()
    payload = payload or {}
    if settings.redact_at_capture:
        payload = redact_payload(payload)

    from agentfox.core.tenancy import session_org

    target_org = org_id or session_org(session)

    last = session.scalars(
        select(AuditEntry)
        .where(AuditEntry.org_id == target_org)
        .order_by(AuditEntry.seq.desc())
        .limit(1)
    ).first()
    seq = (last.seq + 1) if last else 1
    prev_digest = last.digest if last else GENESIS
    ts = occurred_at or utcnow()

    payload_digest = compute_payload_digest(payload)
    entry = AuditEntry(
        org_id=target_org,
        seq=seq,
        occurred_at=ts,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        payload_json=payload,
        payload_digest=payload_digest,
        prev_digest=prev_digest,
        digest=compute_digest(seq, ts, action, payload_digest, prev_digest),
    )
    session.add(entry)
    session.flush()

    if settings.audit_checkpoint_interval and seq % settings.audit_checkpoint_interval == 0:
        write_checkpoint(session, entry)
    return entry


def attribution(*, automated: bool, actor: str | None = None) -> dict[str, str]:
    """``actor_type``/``actor_id`` for an entry, splatted into :func:`append`.

    An automated change is recorded under the improvement loop's own identity and the
    distinct ``automation`` actor type — never as the person or operator who happened
    to trigger it — so the chain can always answer "did a human decide this?". A human
    step must name the human: an anonymous decision is refused rather than defaulted.
    Only attribution; it has no bearing on how an entry is hashed.
    """
    if automated:
        from agentfox.core.vocab import AUTOMATION_ACTOR_TYPE

        return {
            "actor_type": AUTOMATION_ACTOR_TYPE,
            "actor_id": get_settings().improvement_actor_id,
        }
    if not (actor or "").strip():
        raise ValueError("a human step must name the person who took it")
    return {"actor_type": "user", "actor_id": actor.strip()}


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


def sign(digest: str, key: str | None = None) -> str:
    key = key or get_settings().audit_signing_key
    return hmac.new(key.encode(), digest.encode(), hashlib.sha256).hexdigest()


def write_checkpoint(session: Session, entry: AuditEntry, key_id: str = "local") -> AuditCheckpoint:
    checkpoint = AuditCheckpoint(
        seq=entry.seq,
        digest=entry.digest,
        signature=sign(entry.digest),
        key_id=key_id,
    )
    session.add(checkpoint)
    session.flush()
    return checkpoint


def checkpoint_now(session: Session) -> AuditCheckpoint | None:
    last = session.scalars(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1)).first()
    return write_checkpoint(session, last) if last else None


# ---------------------------------------------------------------------------
# Verification — a pure function over rows
# ---------------------------------------------------------------------------


@dataclass
class ChainBreak:
    seq: int
    kind: str  # gap | prev_mismatch | digest_mismatch | payload_mismatch | order
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"seq": self.seq, "kind": self.kind, "detail": self.detail}


@dataclass
class VerificationResult:
    valid: bool = True
    entries_checked: int = 0
    first_seq: int | None = None
    last_seq: int | None = None
    breaks: list[ChainBreak] = field(default_factory=list)
    checkpoints_checked: int = 0
    checkpoint_failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def first_break(self) -> ChainBreak | None:
        return self.breaks[0] if self.breaks else None

    def to_json(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "entries_checked": self.entries_checked,
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "breaks": [b.to_json() for b in self.breaks],
            "first_break": self.first_break.to_json() if self.first_break else None,
            "checkpoints_checked": self.checkpoints_checked,
            "checkpoint_failures": self.checkpoint_failures,
        }


def entry_to_row(entry: AuditEntry) -> dict[str, Any]:
    """Serialise an entry to the exact shape :func:`verify` consumes."""
    occurred = entry.occurred_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=dt.UTC)
    return {
        "seq": entry.seq,
        "occurred_at": occurred.isoformat(),
        "actor_type": entry.actor_type,
        "actor_id": entry.actor_id,
        "action": entry.action,
        "subject_type": entry.subject_type,
        "subject_id": entry.subject_id,
        "payload": entry.payload_json,
        "payload_digest": entry.payload_digest,
        "prev_digest": entry.prev_digest,
        "digest": entry.digest,
    }


def verify(
    rows: Iterable[dict[str, Any]],
    checkpoints: Iterable[dict[str, Any]] | None = None,
    signing_key: str | None = None,
    expect_genesis: bool = True,
) -> VerificationResult:
    """Verify an exported chain. No database access, no shared state.

    Detects:
      * **mutation**  — recomputed payload/entry digest differs
      * **deletion**  — a gap in ``seq``
      * **insertion** — ``prev_digest`` does not match the preceding entry
      * **reordering** — sequence numbers out of order
      * **checkpoint forgery** — signature or anchored digest mismatch
    """
    result = VerificationResult()
    ordered = sorted(rows, key=lambda r: int(r["seq"]))
    if not ordered:
        return result

    result.first_seq = int(ordered[0]["seq"])
    result.last_seq = int(ordered[-1]["seq"])
    prev_digest = GENESIS if (expect_genesis and result.first_seq == 1) else None
    expected_seq = result.first_seq

    for row in ordered:
        seq = int(row["seq"])
        result.entries_checked += 1

        if seq != expected_seq:
            result.breaks.append(
                ChainBreak(
                    seq, "gap", f"expected seq {expected_seq}, found {seq} — entries deleted"
                )
            )
            expected_seq = seq
        expected_seq += 1

        # A scoped evidence package withholds the payload of entries about agents
        # outside its scope. The entry digest still covers the payload digest, so
        # the chain linkage is verified; only the payload itself cannot be.
        recomputed_payload = (
            row["payload_digest"]
            if row.get("payload_withheld") and row.get("payload") is None
            else compute_payload_digest(row.get("payload") or {})
        )
        if recomputed_payload != row["payload_digest"]:
            result.breaks.append(
                ChainBreak(seq, "payload_mismatch", "payload does not match its recorded digest")
            )

        occurred = dt.datetime.fromisoformat(row["occurred_at"])
        recomputed = compute_digest(
            seq, occurred, row["action"], row["payload_digest"], row["prev_digest"]
        )
        if recomputed != row["digest"]:
            result.breaks.append(
                ChainBreak(seq, "digest_mismatch", "entry digest does not match its contents")
            )

        if prev_digest is not None and row["prev_digest"] != prev_digest:
            result.breaks.append(
                ChainBreak(
                    seq,
                    "prev_mismatch",
                    "prev_digest does not match the preceding entry — insertion or reordering",
                )
            )
        prev_digest = row["digest"]

    by_seq = {int(r["seq"]): r for r in ordered}
    for checkpoint in checkpoints or []:
        result.checkpoints_checked += 1
        seq = int(checkpoint["seq"])
        expected_signature = sign(checkpoint["digest"], signing_key)
        if not hmac.compare_digest(expected_signature, str(checkpoint.get("signature", ""))):
            result.checkpoint_failures.append(
                {"seq": seq, "reason": "signature mismatch — checkpoint forged or key changed"}
            )
            continue
        anchored = by_seq.get(seq)
        if anchored and anchored["digest"] != checkpoint["digest"]:
            result.checkpoint_failures.append(
                {
                    "seq": seq,
                    "reason": "entry digest differs from signed checkpoint — history rewritten",
                }
            )

    result.valid = not result.breaks and not result.checkpoint_failures
    return result


def verify_range(
    session: Session, start_seq: int | None = None, end_seq: int | None = None
) -> VerificationResult:
    query = select(AuditEntry).order_by(AuditEntry.seq)
    if start_seq is not None:
        query = query.where(AuditEntry.seq >= start_seq)
    if end_seq is not None:
        query = query.where(AuditEntry.seq <= end_seq)
    entries = list(session.scalars(query))

    cp_query = select(AuditCheckpoint).order_by(AuditCheckpoint.seq)
    if start_seq is not None:
        cp_query = cp_query.where(AuditCheckpoint.seq >= start_seq)
    if end_seq is not None:
        cp_query = cp_query.where(AuditCheckpoint.seq <= end_seq)
    checkpoints = [
        {"seq": c.seq, "digest": c.digest, "signature": c.signature, "key_id": c.key_id}
        for c in session.scalars(cp_query)
    ]

    return verify(
        [entry_to_row(e) for e in entries],
        checkpoints,
        expect_genesis=start_seq in (None, 1),
    )


def chain_stats(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count()).select_from(AuditEntry)) or 0
    last = session.scalars(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1)).first()
    checkpoints = session.scalar(select(func.count()).select_from(AuditCheckpoint)) or 0
    return {
        "entries": total,
        "head_seq": last.seq if last else 0,
        "head_digest": last.digest if last else GENESIS,
        "checkpoints": checkpoints,
    }
