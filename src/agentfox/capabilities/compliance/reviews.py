"""Control reviews: a named person attesting one control against one framework.

What "reviewed" used to mean
----------------------------
A single "Mark reviewed" click flipped every `framework_mappings` row of a control
for a framework from ``draft`` to ``reviewed``. It recorded who clicked and when, and
the only effect was that evidence packages stopped printing the DRAFT chip on those
rows. There was no outcome, no note, no record of what the reviewer looked at, and it
never lapsed: a click in 2026 still read "reviewed" in 2030.

What a review is now
--------------------
An attestation that can be argued with:

* **An outcome**, not a checkbox: ``meets``, ``partially_meets``, ``does_not_meet`` or
  ``not_applicable``. Anything short of ``meets`` needs a note saying why.
* **The evidence it was made on**, frozen on the row: the computed status and its
  rationale, the rules and policies that implement the control, when they last fired,
  open findings, and the newest evidence package covering it. A later reader sees
  what the reviewer saw, not what the telemetry says today.
* **An expiry** (`REVIEW_VALID_DAYS`). After it the review reads ``expired`` and the
  control needs re-reviewing. Controls drift; an attestation that never lapses is an
  attestation of a system that no longer exists.
* **An audit-chain entry** (``compliance.control_reviewed``), whose sequence number is
  stored on the row, so the attestation is as tamper-evident as the decisions it is
  about.

A review also confirms the mapping it was made against, so the evidence package's
DRAFT chip comes off those `framework_mappings` rows, as before.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    Control,
    ControlReview,
    Decision,
    EvidencePackage,
    Finding,
    FrameworkMapping,
    as_aware,
    utcnow,
)

OUTCOMES = ("meets", "partially_meets", "does_not_meet", "not_applicable")

#: How long an attestation stays current before the control must be re-reviewed.
REVIEW_VALID_DAYS = 90

#: How far back, and how many decisions, the "last fired" scan reads.
_FIRED_WINDOW_DAYS = 90
_FIRED_SCAN_LIMIT = 5000


class ReviewError(ValueError):
    """A review that cannot be recorded as asked (unknown control, missing note...)."""


def _iso(value: dt.datetime | None) -> str | None:
    value = as_aware(value)
    return value.isoformat() if value else None


# ---------------------------------------------------------------------------
# Evidence: what the platform computed for one control
# ---------------------------------------------------------------------------


def linked_rules(session: Session, control_key: str) -> list[dict[str, Any]]:
    """Every rule in a bound policy that declares it implements ``control_key``."""
    from agentfox.platform.policy.store import active_policies

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for doc, _version, binding in active_policies(session):
        for rule in doc.rules:
            if control_key not in (rule.controls or []):
                continue
            identity = (doc.key, rule.id)
            if identity in seen:
                continue
            seen.add(identity)
            out.append(
                {
                    "policy": doc.key,
                    "policy_name": doc.name or doc.key,
                    "rule_id": rule.id,
                    "description": rule.description,
                    "effect": rule.effect,
                    "severity": rule.severity,
                    "enabled": rule.enabled,
                    "mode": binding.mode,
                }
            )
    return out


def _fired_for(fired: dict[str, Any], control_key: str, rule_ids: set[str]) -> bool:
    return fired.get("rule_id") in rule_ids or control_key in (fired.get("controls") or [])


def rule_activity(
    session: Session, control_key: str, rule_ids: set[str], *, runs_limit: int = 10
) -> dict[str, Any]:
    """When the control's rules last fired, how often, and the runs they fired in."""
    since = utcnow() - dt.timedelta(days=_FIRED_WINDOW_DAYS)
    decisions = session.scalars(
        select(Decision)
        .where(Decision.created_at >= since)
        .order_by(Decision.created_at.desc())
        .limit(_FIRED_SCAN_LIMIT)
    )
    by_rule: dict[str, dict[str, Any]] = {}
    runs: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    fires = 0
    for decision in decisions:
        hit = False
        for fired in decision.rules_fired_json or []:
            if not isinstance(fired, dict) or not _fired_for(fired, control_key, rule_ids):
                continue
            hit = True
            rule_id = str(fired.get("rule_id") or "")
            stats = by_rule.setdefault(rule_id, {"fires": 0, "last_fired": None})
            stats["fires"] += 1
            stats["last_fired"] = stats["last_fired"] or _iso(decision.created_at)
            if decision.trace_id and decision.trace_id not in run_ids and len(runs) < runs_limit:
                run_ids.add(decision.trace_id)
                runs.append(
                    {
                        "trace_id": decision.trace_id,
                        "rule_id": rule_id,
                        "verdict": decision.verdict,
                        "mode": fired.get("mode") or decision.mode,
                        "at": _iso(decision.created_at),
                    }
                )
        fires += 1 if hit else 0
    last = max((s["last_fired"] for s in by_rule.values() if s["last_fired"]), default=None)
    return {
        "window_days": _FIRED_WINDOW_DAYS,
        "decisions": fires,
        "last_fired": last,
        "by_rule": by_rule,
        "runs": runs,
    }


def _package_covers(package: EvidencePackage, control_key: str) -> bool:
    controls = (package.scope_json or {}).get("controls")
    return not controls or "*" in controls or control_key in controls


def control_evidence(session: Session, control_key: str) -> dict[str, Any]:
    """The evidence a reviewer is shown, and that their review freezes."""
    from agentfox.capabilities.compliance.status import latest_statuses

    status = latest_statuses(session).get(control_key)
    rules = linked_rules(session, control_key)
    activity = rule_activity(session, control_key, {r["rule_id"] for r in rules})
    for rule in rules:
        stats = activity["by_rule"].get(rule["rule_id"]) or {}
        rule["fires"] = stats.get("fires", 0)
        rule["last_fired"] = stats.get("last_fired")

    findings = [
        {
            "id": f.id,
            "type": f.type,
            "severity": f.severity,
            "title": f.title,
            "created_at": _iso(f.created_at),
        }
        for f in session.scalars(
            select(Finding).where(Finding.status == "open").order_by(Finding.created_at.desc())
        )
        if control_key in (f.control_keys or [])
    ][:20]

    packages = [
        {
            "id": p.id,
            "built_at": _iso(p.built_at),
            "requested_by": p.requested_by,
            "chain_valid": (p.chain_verification_json or {}).get("valid"),
        }
        for p in session.scalars(select(EvidencePackage).order_by(EvidencePackage.built_at.desc()))
        if _package_covers(p, control_key)
    ][:5]

    return {
        "status": status.status if status else "not_computed",
        "rationale": status.rationale if status else None,
        "computed_at": _iso(status.computed_at) if status else None,
        "telemetry": status.evidence_json if status else {},
        "rules": rules,
        "last_fired": activity["last_fired"],
        "fires": activity["decisions"],
        "fired_window_days": activity["window_days"],
        "runs": activity["runs"],
        "open_findings": findings,
        "evidence_packages": packages,
    }


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


def review_state(review: ControlReview | None, now: dt.datetime | None = None) -> str:
    """``none``, ``current`` or ``expired``."""
    if review is None:
        return "none"
    expires = as_aware(review.expires_at)
    return "expired" if expires is not None and expires <= (now or utcnow()) else "current"


def review_json(review: ControlReview | None, now: dt.datetime | None = None) -> dict | None:
    if review is None:
        return None
    return {
        "id": review.id,
        "control_key": review.control_key,
        "framework": review.framework,
        "outcome": review.outcome,
        "note": review.note,
        "reviewer": review.reviewer,
        "reviewed_at": _iso(review.reviewed_at),
        "expires_at": _iso(review.expires_at),
        "state": review_state(review, now),
        "audit_seq": review.audit_seq,
        "status_at_review": (review.evidence_json or {}).get("status"),
    }


def latest_reviews(
    session: Session, framework: str | None = None
) -> dict[tuple[str, str], ControlReview]:
    """The newest review per (control, framework)."""
    query = select(ControlReview).order_by(ControlReview.reviewed_at)
    if framework:
        query = query.where(ControlReview.framework == framework)
    out: dict[tuple[str, str], ControlReview] = {}
    for review in session.scalars(query):
        out[(review.control_key, review.framework)] = review  # later rows win
    return out


def review_history(session: Session, control_key: str) -> list[ControlReview]:
    return list(
        session.scalars(
            select(ControlReview)
            .where(ControlReview.control_key == control_key)
            .order_by(ControlReview.reviewed_at.desc())
        )
    )


def record_review(
    session: Session,
    control_key: str,
    framework: str,
    outcome: str,
    *,
    reviewer: str,
    note: str = "",
    valid_days: int = REVIEW_VALID_DAYS,
    now: dt.datetime | None = None,
) -> ControlReview:
    """Record one attestation, freeze the evidence it was made on, and chain it."""
    from agentfox.platform.ledger import chain

    if outcome not in OUTCOMES:
        raise ReviewError(f"outcome must be one of {list(OUTCOMES)}")
    note = (note or "").strip()
    if outcome != "meets" and not note:
        raise ReviewError("say why in a note: only 'meets' may be recorded without one")
    if not reviewer:
        raise ReviewError("a review needs a named reviewer")
    if not 1 <= int(valid_days) <= 366:
        raise ReviewError("a review is valid for 1 to 366 days")
    control = session.scalar(select(Control).where(Control.key == control_key))
    if control is None:
        raise ReviewError(f"unknown control '{control_key}'")
    mappings = list(
        session.scalars(
            select(FrameworkMapping).where(
                FrameworkMapping.control_key == control_key,
                FrameworkMapping.framework == framework,
            )
        )
    )
    if not mappings:
        raise ReviewError(f"'{control_key}' is not mapped to '{framework}'")

    now = now or utcnow()
    evidence = control_evidence(session, control_key)
    # The snapshot keeps what a later reader needs to see what was attested, not the
    # whole run list, which is reachable from the audit entry's time anyway.
    snapshot = {
        "status": evidence["status"],
        "rationale": evidence["rationale"],
        "computed_at": evidence["computed_at"],
        "rules": [
            {k: r[k] for k in ("policy", "rule_id", "effect", "mode", "fires", "last_fired")}
            for r in evidence["rules"]
        ],
        "last_fired": evidence["last_fired"],
        "open_findings": len(evidence["open_findings"]),
        "evidence_package": (evidence["evidence_packages"] or [{}])[0].get("id"),
        "references": sorted(m.reference for m in mappings),
    }
    review = ControlReview(
        control_key=control_key,
        framework=framework,
        outcome=outcome,
        note=note,
        reviewer=reviewer,
        reviewed_at=now,
        expires_at=now + dt.timedelta(days=int(valid_days)),
        evidence_json=snapshot,
    )
    session.add(review)
    session.flush()

    for mapping in mappings:
        mapping.review_status = "reviewed"
        mapping.reviewed_by = reviewer
        mapping.reviewed_at = now

    entry = chain.append(
        session,
        "compliance.control_reviewed",
        actor_type="user",
        actor_id=reviewer,
        subject_type="control",
        subject_id=control_key,
        payload={
            "review_id": review.id,
            "control_key": control_key,
            "framework": framework,
            "references": snapshot["references"],
            "outcome": outcome,
            "note": note,
            "expires_at": _iso(review.expires_at),
            "status_at_review": snapshot["status"],
            "evidence_package": snapshot["evidence_package"],
        },
    )
    review.audit_seq = entry.seq
    session.flush()
    return review
