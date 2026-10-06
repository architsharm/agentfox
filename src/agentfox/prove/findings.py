"""The one way a finding is raised, and the one way a condition that cleared closes it.

A finding queue is only a sensing surface if one row means one problem. Before this
module every producer constructed ``Finding(...)`` directly, so a detector that was
degraded for an hour filed a finding per request, a drift view filed one per page
load, and a red-team campaign re-run filed the same gap again. Counting those rows
measured traffic, not problems — and the improvement loop's sense stage reads exactly
that count.

Three rules live here:

* **Identity is a fingerprint.** A stable hash of the tenant, the finding type, the
  subject, and whatever the producer says distinguishes one instance of the problem
  from another (a detector key, a scorer, a probe). A repeat of an *open* problem
  increments ``occurrences`` and refreshes the evidence; it never adds a row.
* **Recurrence after a fix is news, not noise.** If the only match was resolved, the
  finding is reopened with its history intact and the recurrence is audited — that is
  precisely the signal the loop's verify stage needs to say a fix did not hold.
* **A suppressed finding stays suppressed.** Suppression is a person's recorded
  judgement; a recurrence is counted against it but does not overrule it.

``resolve_finding`` is the counterpart for conditions that clear on their own (a
budget window rolled, a degraded detector recovered, a drift window no longer
drifts). It is audited like a human resolution, with ``automated`` saying which one it
was, so an auto-closed finding is never mistaken for a person's decision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Finding, utcnow
from agentfox.core.tenancy import session_org
from agentfox.core.vocab import AUTOMATION_ACTOR_TYPE
from agentfox.prove.audit import chain

OPEN = "open"
SUPPRESSED = "suppressed"
RESOLVED = "resolved"
STATUSES = (OPEN, SUPPRESSED, RESOLVED)

#: Evidence keys this module owns. Kept out of the producer's namespace by prefix.
FIRST_SEEN_KEY = "first_seen_evidence"
RECURRENCES_KEY = "recurrences"

#: How many recurrence records a finding keeps. A finding that has reopened more
#: often than this is not short of history; it is short of a fix.
_MAX_RECURRENCES = 20
#: Audit actor type for lifecycle changes nobody decided: a recurrence, a condition
#: that cleared. The loop's own vocabulary, so these are never read as a human's call.
_SYSTEM_ACTOR_TYPE = AUTOMATION_ACTOR_TYPE


def fingerprint(
    org_id: str,
    type: str,
    subject_type: str | None,
    subject_id: str | None,
    parts: tuple[Any, ...] | None = None,
) -> str:
    """Stable identity of one underlying problem. 64 hex chars (sha256)."""
    material = [org_id, type, subject_type or "", subject_id or "", *(parts or ())]
    raw = json.dumps([_canonical(p) for p in material], separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_canonical(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    return str(value)


def _strip_owned(evidence: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (evidence or {}).items() if k not in (FIRST_SEEN_KEY, RECURRENCES_KEY)}


def raise_finding(
    session: Session,
    *,
    type: str,
    title: str,
    severity: str = "medium",
    subject_type: str = "agent",
    subject_id: str | None = None,
    evidence: dict[str, Any] | None = None,
    control_keys: list[str] | None = None,
    fingerprint_parts: tuple[Any, ...] | None = None,
    once: bool = False,
) -> tuple[Finding, bool]:
    """Raise a finding, or count another occurrence of one already raised.

    Returns ``(finding, created)``. ``created`` is True only when a new row was added;
    a reopened resolved finding returns False (it is the same problem, recurring).

    ``once=True`` is for findings about one past event that a periodic scan re-detects
    (a specific conversation turn, a specific hand-off). Seeing that event again is
    not a new occurrence and certainly not a recurrence after a fix, so an existing
    match in any status is returned untouched.
    """
    org_id = session_org(session)
    fp = fingerprint(org_id, type, subject_type, subject_id, fingerprint_parts)
    now = utcnow()
    evidence = dict(evidence or {})

    matches = list(
        session.scalars(
            select(Finding)
            .where(Finding.fingerprint == fp)
            .order_by(Finding.created_at.desc(), Finding.id.desc())
        )
    )
    if once and matches:
        return matches[0], False

    by_status = {
        status: next((f for f in matches if f.status == status), None) for status in STATUSES
    }

    existing = by_status[OPEN] or by_status[SUPPRESSED]
    if existing is not None:
        _count_occurrence(existing, evidence, title=title, severity=severity, now=now)
        session.flush()
        return existing, False

    resolved = by_status[RESOLVED]
    if resolved is not None:
        history = list((resolved.evidence_json or {}).get(RECURRENCES_KEY) or [])
        history.append(
            {
                "reopened_at": now.isoformat(),
                "resolved_at": resolved.resolved_at.isoformat() if resolved.resolved_at else None,
                "resolved_by": resolved.resolved_by,
                "resolution_note": resolved.resolution_note,
            }
        )
        _count_occurrence(resolved, evidence, title=title, severity=severity, now=now)
        resolved.evidence_json = {
            **(resolved.evidence_json or {}),
            RECURRENCES_KEY: history[-_MAX_RECURRENCES:],
        }
        resolved.status = OPEN
        resolved.resolved_at = None
        resolved.resolved_by = None
        resolved.resolution_note = None
        session.flush()
        chain.append(
            session,
            "finding.recurred",
            actor_type=_SYSTEM_ACTOR_TYPE,
            actor_id="agentfox.prove.findings",
            subject_type="finding",
            subject_id=resolved.id,
            payload={
                "type": resolved.type,
                "fingerprint": fp,
                "occurrences": resolved.occurrences,
                "previous_resolution": history[-1],
            },
        )
        return resolved, False

    finding = Finding(
        type=type,
        severity=severity,
        title=title[:300],
        subject_type=subject_type,
        subject_id=subject_id,
        evidence_json=evidence,
        control_keys=list(control_keys or []),
        fingerprint=fp,
        occurrences=1,
        last_seen_at=now,
    )
    session.add(finding)
    session.flush()
    return finding, True


def _count_occurrence(
    finding: Finding, evidence: dict[str, Any], *, title: str, severity: str, now: Any
) -> None:
    previous = finding.evidence_json or {}
    first = previous.get(FIRST_SEEN_KEY)
    if first is None:
        first = _strip_owned(previous)
    refreshed: dict[str, Any] = {**_strip_owned(evidence), FIRST_SEEN_KEY: first}
    if previous.get(RECURRENCES_KEY):
        refreshed[RECURRENCES_KEY] = previous[RECURRENCES_KEY]
    finding.evidence_json = refreshed
    finding.occurrences = (finding.occurrences or 1) + 1
    finding.last_seen_at = now
    finding.title = title[:300]
    # Severity only ratchets up while a problem stays open: a later, milder occurrence
    # must not quietly downgrade a finding someone is triaging as critical.
    if _rank(severity) > _rank(finding.severity):
        finding.severity = severity


def _rank(severity: str | None) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(str(severity or "").lower(), 0)


def open_finding(
    session: Session,
    *,
    type: str,
    subject_type: str = "agent",
    subject_id: str | None = None,
    fingerprint_parts: tuple[Any, ...] | None = None,
) -> Finding | None:
    """The open finding for this identity, if any — for callers that auto-resolve."""
    fp = fingerprint(session_org(session), type, subject_type, subject_id, fingerprint_parts)
    return session.scalar(
        select(Finding).where(Finding.fingerprint == fp, Finding.status == OPEN).limit(1)
    )


def resolve_finding(
    session: Session,
    finding: Finding,
    *,
    actor: str,
    note: str,
    automated: bool = False,
) -> Finding:
    """Close a finding, audited. ``automated`` marks a condition that cleared itself."""
    if not (note or "").strip():
        raise ValueError("resolving a finding requires a note describing why")
    if not (actor or "").strip():
        raise ValueError("resolving a finding requires an actor")
    if finding.status == RESOLVED:
        return finding
    previous = finding.status
    finding.status = RESOLVED
    finding.resolved_at = utcnow()
    finding.resolved_by = actor
    finding.resolution_note = note.strip()
    session.flush()
    chain.append(
        session,
        "finding.resolved",
        actor_type=_SYSTEM_ACTOR_TYPE if automated else "user",
        actor_id=actor,
        subject_type="finding",
        subject_id=finding.id,
        payload={
            "type": finding.type,
            "reason": finding.resolution_note,
            "automated": automated,
            "from": previous,
            "occurrences": finding.occurrences,
        },
    )
    return finding


def auto_resolve(
    session: Session,
    *,
    type: str,
    subject_type: str = "agent",
    subject_id: str | None = None,
    fingerprint_parts: tuple[Any, ...] | None = None,
    note: str,
    actor: str = "agentfox.prove.findings",
) -> Finding | None:
    """Resolve the open finding for this identity because its condition cleared."""
    finding = open_finding(
        session,
        type=type,
        subject_type=subject_type,
        subject_id=subject_id,
        fingerprint_parts=fingerprint_parts,
    )
    if finding is None:
        return None
    return resolve_finding(session, finding, actor=actor, note=note, automated=True)


# ---------------------------------------------------------------------------
# Detector degradation — the one hot-path producer that auto-resolves
# ---------------------------------------------------------------------------

#: How often, per tenant and agent, the request path looks for degraded-detector
#: findings to close. Recovery is a slow-moving fact; paying a query on every request
#: to notice it a few seconds sooner would be spending the latency budget this whole
#: control exists to protect. Tests set it to 0.
RECOVERY_CHECK_INTERVAL_SECONDS = 30.0
_recovery_checked: dict[tuple[str, str | None], float] = {}


def reset_recovery_checks() -> None:
    """Test hook: forget when each agent was last checked for recovered detectors."""
    _recovery_checked.clear()


def record_detector_health(
    session: Session, *, subject_id: str | None, surface: str, pipeline_result: Any
) -> None:
    """One ``budget_breach`` finding per degraded detector per agent, closed on recovery.

    Degradation is a property of the detector for this agent, not of the request, so the
    fingerprint is the detector key alone: an hour of timeouts is one finding with a
    count. A detector that has since completed normally for the same agent closes it.
    """
    degraded = list(getattr(pipeline_result, "degraded", None) or [])
    results = list(getattr(pipeline_result, "results", None) or [])
    status_by_key = {r.detector_key: r.status for r in results}
    summary = pipeline_result.summary() if hasattr(pipeline_result, "summary") else {}

    for key in dict.fromkeys(degraded):
        status = status_by_key.get(key, "degraded")
        raise_finding(
            session,
            type="budget_breach",
            severity="medium",
            title=f"Detector '{key}' degraded on {surface}: {status}",
            subject_type="agent",
            subject_id=subject_id,
            evidence={**summary, "detector_key": key, "status": status, "surface": surface},
            control_keys=["NOM-RTG-06"],
            fingerprint_parts=(key,),
        )

    healthy = [k for k, st in status_by_key.items() if st == "ok" and k not in degraded]
    if not healthy:
        return
    import time

    org_id = session_org(session)
    now = time.monotonic()
    marker = (org_id, subject_id)
    last = _recovery_checked.get(marker)
    if last is not None and now - last < RECOVERY_CHECK_INTERVAL_SECONDS:
        return
    _recovery_checked[marker] = now
    by_fp = {fingerprint(org_id, "budget_breach", "agent", subject_id, (k,)): k for k in healthy}
    for finding in list(
        session.scalars(
            select(Finding).where(Finding.fingerprint.in_(list(by_fp)), Finding.status == OPEN)
        )
    ):
        resolve_finding(
            session,
            finding,
            actor="agentfox.runtime.enforcement",
            note=f"detector '{by_fp[finding.fingerprint]}' completed normally on {surface}",
            automated=True,
        )


__all__ = [
    "OPEN",
    "RESOLVED",
    "STATUSES",
    "SUPPRESSED",
    "auto_resolve",
    "fingerprint",
    "open_finding",
    "raise_finding",
    "record_detector_health",
    "reset_recovery_checks",
    "resolve_finding",
]
