"""The proposal lifecycle: filed, proven, approved, applied, verified — or undone.

This is the only path by which the improvement loop changes configuration, and the
place the rules in :mod:`agentfox.improvement.contract` are enforced rather than
merely stated:

* every transition is checked against ``contract.transition_allowed``;
* a change's direction is recomputed by its applier from the diff and the live
  configuration at filing, at decision and again at apply — a caller's label is never
  trusted;
* an org-level loosening needs two different named people;
* an automated apply needs an auto-apply autonomy level (after demotion for the class's
  rollback rate), a kind and direction the contract allows, the kill switch off, and
  headroom under the tenant's daily cap;
* every step writes an entry to the tenant's audit chain, attributed to the person who
  took it or — distinctly — to the automation actor.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import AuditEntry, ChangeProposal, utcnow
from agentfox.core.vocab import AUTOMATION_ACTOR_TYPE
from agentfox.improvement import contract
from agentfox.improvement.appliers import APPLY_ACTION, ApplierError, get_applier, has_applier
from agentfox.prove.audit import chain

SUBJECT_TYPE = "change_proposal"

FILE_ACTION = "proposal.filed"
EVIDENCE_ACTION = "proposal.evidence_updated"
PROOF_ACTION = "proposal.proof_attached"
DIRECTION_ACTION = "proposal.direction_recomputed"
DECIDE_ACTION = "operator.proposal.decided"
ROLLBACK_ACTION = "operator.proposal.rolled_back"
CANARY_COMPLETED_ACTION = "proposal.canary_completed"
CANARY_ROLLED_BACK_ACTION = "proposal.canary_rolled_back"
VERIFY_ACTION = "proposal.verified"
VERIFY_FAILED_ACTION = "proposal.verification_failed"


class ProposalError(ValueError):
    """The request is malformed or breaks a rule of the contract."""


class IllegalTransition(ProposalError):
    """The proposal is not in a state this step can move it from."""


class AutomationRefused(ProposalError):
    """Automation may not take this step; a person has to."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_transition(proposal: ChangeProposal, target: str, what: str) -> None:
    if not contract.transition_allowed(proposal.status, target):
        raise IllegalTransition(
            f"cannot {what} proposal {proposal.id}: it is '{proposal.status}', and "
            f"'{proposal.status}' -> '{target}' is not a legal transition"
        )


def _require_note(note: str | None, what: str) -> str:
    if not (note or "").strip():
        raise ProposalError(f"{what} needs a note saying why")
    return note.strip()


def _same_person(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _refresh_direction(
    session: Session, proposal: ChangeProposal, *, automated: bool, actor: str | None
) -> str:
    """Recompute direction from the live configuration; record it if it moved."""
    if not has_applier(proposal.kind):
        return proposal.direction
    try:
        computed = get_applier(proposal.kind).direction(session, proposal)
    except ApplierError as exc:
        raise ProposalError(str(exc)) from exc
    if computed != proposal.direction:
        before = proposal.direction
        proposal.direction = computed
        session.flush()
        chain.append(
            session,
            DIRECTION_ACTION,
            **chain.attribution(automated=automated, actor=actor),
            subject_type=SUBJECT_TYPE,
            subject_id=proposal.id,
            payload={"before": before, "after": computed},
        )
    return computed


def automated_applies_last_day(session: Session) -> int:
    from agentfox.core.tenancy import session_org

    since = utcnow() - dt.timedelta(days=1)
    return int(
        session.scalar(
            select(func.count())
            .select_from(AuditEntry)
            .where(
                AuditEntry.org_id == session_org(session),
                AuditEntry.action == APPLY_ACTION,
                AuditEntry.actor_type == AUTOMATION_ACTOR_TYPE,
                AuditEntry.occurred_at >= since,
            )
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_proposal(session: Session, proposal_id: str) -> ChangeProposal | None:
    return session.scalar(select(ChangeProposal).where(ChangeProposal.id == proposal_id))


def list_proposals(
    session: Session,
    *,
    status: str | None = None,
    kind: str | None = None,
    scope_level: str | None = None,
    scope_id: str | None = None,
    limit: int = 200,
) -> list[ChangeProposal]:
    query = select(ChangeProposal)
    if status:
        query = query.where(ChangeProposal.status == status)
    if kind:
        query = query.where(ChangeProposal.kind == kind)
    if scope_level:
        query = query.where(ChangeProposal.scope_level == scope_level)
    if scope_id:
        query = query.where(ChangeProposal.scope_id == scope_id)
    return list(session.scalars(query.order_by(ChangeProposal.created_at.desc()).limit(limit)))


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def proposal_json(proposal: ChangeProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "kind": proposal.kind,
        "source": proposal.source,
        "target_type": proposal.target_type,
        "target_ref": proposal.target_ref,
        "scope_level": proposal.scope_level,
        "scope_id": proposal.scope_id,
        "title": proposal.title,
        "rationale": proposal.rationale,
        "direction": proposal.direction,
        "autonomy_level": proposal.autonomy_level,
        "status": proposal.status,
        "fingerprint": proposal.fingerprint,
        "diff": proposal.diff_json,
        "evidence": proposal.evidence_json,
        "proof": proposal.proof_json,
        "expected_effect": proposal.expected_effect_json,
        "related_finding_ids": proposal.related_finding_ids,
        "proposed_by": proposal.proposed_by,
        "decided_by": proposal.decided_by,
        "second_approver": proposal.second_approver,
        "awaiting_second_approver": (
            proposal.status == contract.PROVEN
            and proposal.decided_by is not None
            and proposal.second_approver is None
        ),
        "decided_at": _iso(proposal.decided_at),
        "decision_note": proposal.decision_note,
        "applied_at": _iso(proposal.applied_at),
        "verified_at": _iso(proposal.verified_at),
        "rolled_back_at": _iso(proposal.rolled_back_at),
        "outcome_note": proposal.outcome_note,
        "applier": has_applier(proposal.kind),
        "created_at": _iso(proposal.created_at),
    }


# ---------------------------------------------------------------------------
# Filing and proof
# ---------------------------------------------------------------------------


def _open_with_fingerprint(session: Session, fingerprint: str) -> ChangeProposal | None:
    return session.scalar(
        select(ChangeProposal)
        .where(
            ChangeProposal.fingerprint == fingerprint,
            ChangeProposal.status.in_(sorted(contract.OPEN)),
        )
        .order_by(ChangeProposal.created_at.desc())
        .limit(1)
    )


def _merge_evidence(
    session: Session,
    existing: ChangeProposal,
    fingerprint: str,
    evidence: dict[str, Any],
    related_finding_ids: list[str] | None,
    attribution: dict[str, str],
) -> ChangeProposal:
    """The same problem seen again adds evidence to the open proposal, never a second one."""
    existing.evidence_json = {**(existing.evidence_json or {}), **evidence}
    if related_finding_ids:
        merged = list(existing.related_finding_ids or [])
        merged += [f for f in related_finding_ids if f not in merged]
        existing.related_finding_ids = merged
    session.flush()
    chain.append(
        session,
        EVIDENCE_ACTION,
        **attribution,
        subject_type=SUBJECT_TYPE,
        subject_id=existing.id,
        payload={"fingerprint": fingerprint, "evidence_fields": sorted(evidence)},
    )
    return existing


def file_proposal(
    session: Session,
    *,
    kind: str,
    source: str,
    target_type: str,
    target_ref: str,
    scope_level: str,
    scope_id: str,
    title: str,
    rationale: str,
    direction: str,
    diff: dict[str, Any],
    evidence: dict[str, Any],
    expected_effect: dict[str, Any] | None = None,
    autonomy_level: str = "L1",
    fingerprint: str | None = None,
    related_finding_ids: list[str] | None = None,
    proposed_by: str | None = None,
) -> ChangeProposal:
    """File a proposal, or refresh the open one already filed for the same problem.

    ``proposed_by=None`` means the loop filed it, and it is attributed to automation.
    """
    if not (kind or "").strip():
        raise ProposalError("kind is required")
    if not (title or "").strip():
        raise ProposalError("title is required")
    if scope_level not in contract.SCOPE_LEVELS:
        raise ProposalError(f"scope_level must be one of {contract.SCOPE_LEVELS}")
    if direction not in contract.DIRECTIONS:
        raise ProposalError(f"direction must be one of {contract.DIRECTIONS}")
    if autonomy_level not in contract.AUTONOMY_LEVELS:
        raise ProposalError(f"autonomy_level must be one of {contract.AUTONOMY_LEVELS}")
    if not isinstance(diff, dict) or not isinstance(evidence, dict):
        raise ProposalError("diff and evidence must be objects")

    automated = proposed_by is None
    attribution = chain.attribution(automated=automated, actor=proposed_by)

    if fingerprint:
        existing = _open_with_fingerprint(session, fingerprint)
        if existing is not None:
            return _merge_evidence(
                session, existing, fingerprint, evidence, related_finding_ids, attribution
            )

    proposal = ChangeProposal(
        kind=kind.strip(),
        source=source or "",
        target_type=target_type or "",
        target_ref=target_ref or "",
        scope_level=scope_level,
        scope_id=scope_id or "*",
        title=title.strip(),
        rationale=rationale or "",
        direction=direction,
        autonomy_level=autonomy_level,
        status=contract.PROPOSED,
        fingerprint=fingerprint,
        diff_json=dict(diff),
        evidence_json=dict(evidence),
        proof_json={},
        expected_effect_json=dict(expected_effect or {}),
        related_finding_ids=list(related_finding_ids or []),
        proposed_by=attribution["actor_id"],
    )
    claimed = direction
    if has_applier(proposal.kind):
        try:
            proposal.direction = get_applier(proposal.kind).direction(session, proposal)
        except ApplierError as exc:
            raise ProposalError(str(exc)) from exc

    try:
        # A savepoint, so losing a race to a concurrent filing of the same problem rolls
        # back only this insert. The partial unique index is what actually decides it.
        with session.begin_nested():
            session.add(proposal)
            session.flush()
    except IntegrityError:
        if not fingerprint:
            raise
        existing = _open_with_fingerprint(session, fingerprint)
        if existing is None:
            raise
        return _merge_evidence(
            session, existing, fingerprint, evidence, related_finding_ids, attribution
        )
    chain.append(
        session,
        FILE_ACTION,
        **attribution,
        subject_type=SUBJECT_TYPE,
        subject_id=proposal.id,
        payload={
            "kind": proposal.kind,
            "source": proposal.source,
            "target": f"{proposal.target_type}:{proposal.target_ref}",
            "scope": f"{proposal.scope_level}:{proposal.scope_id}",
            "direction": proposal.direction,
            "claimed_direction": claimed,
            "autonomy_level": proposal.autonomy_level,
            "fingerprint": fingerprint,
            "title": proposal.title,
        },
    )
    return proposal


def attach_proof(
    session: Session,
    proposal: ChangeProposal,
    proof: dict[str, Any],
    *,
    passed: bool,
    actor: str | None = None,
) -> ChangeProposal:
    """Record the proof bundle. Only a passing proof makes a proposal ``proven``."""
    if proposal.status != contract.PROPOSED:
        raise IllegalTransition(
            f"proof can only be attached to a proposed change; {proposal.id} is '{proposal.status}'"
        )
    if not isinstance(proof, dict) or not proof:
        raise ProposalError("proof must be a non-empty object")
    if passed:
        _require_transition(proposal, contract.PROVEN, "prove")

    proposal.proof_json = {**proof, "passed": bool(passed), "attached_at": utcnow().isoformat()}
    if passed:
        proposal.status = contract.PROVEN
    session.flush()
    chain.append(
        session,
        PROOF_ACTION,
        **chain.attribution(automated=actor is None, actor=actor),
        subject_type=SUBJECT_TYPE,
        subject_id=proposal.id,
        payload={"passed": bool(passed), "status": proposal.status, "proof_fields": sorted(proof)},
    )
    return proposal


# ---------------------------------------------------------------------------
# Decision (privileged)
# ---------------------------------------------------------------------------


def decide(
    session: Session, proposal: ChangeProposal, *, approve: bool, actor: str, note: str
) -> ChangeProposal:
    """A person approves or rejects. An org-level loosening needs two of them."""
    note = _require_note(note, "a decision")
    attribution = chain.attribution(automated=False, actor=actor)
    actor = attribution["actor_id"]
    from_status = proposal.status

    if not approve:
        _require_transition(proposal, contract.REJECTED, "reject")
        proposal.status = contract.REJECTED
        proposal.decided_by = actor
        proposal.decided_at = utcnow()
        proposal.decision_note = note
        session.flush()
        chain.append(
            session,
            DECIDE_ACTION,
            **attribution,
            subject_type=SUBJECT_TYPE,
            subject_id=proposal.id,
            payload={
                "approve": False,
                "reason": note,
                "from_status": from_status,
                "status": proposal.status,
            },
        )
        return proposal

    if proposal.status == contract.PROPOSED:
        raise IllegalTransition(
            f"cannot approve proposal {proposal.id}: it has not been proven yet"
        )
    _require_transition(proposal, contract.APPROVED, "approve")
    direction = _refresh_direction(session, proposal, automated=False, actor=actor)

    two_person = contract.requires_second_approver(
        direction=direction, scope_level=proposal.scope_level
    )
    awaiting = False
    if two_person and proposal.decided_by is None:
        proposal.decided_by = actor
        proposal.decided_at = utcnow()
        proposal.decision_note = note
        awaiting = True
    elif two_person:
        if _same_person(proposal.decided_by, actor):
            raise ProposalError(
                f"{actor} already approved proposal {proposal.id}; an org-level loosening "
                "needs a second approver who is a different person"
            )
        proposal.second_approver = actor
        proposal.decision_note = f"{proposal.decision_note}\n{actor}: {note}".strip()
        proposal.status = contract.APPROVED
    else:
        proposal.decided_by = actor
        proposal.decided_at = utcnow()
        proposal.decision_note = note
        proposal.status = contract.APPROVED
    session.flush()

    chain.append(
        session,
        DECIDE_ACTION,
        **attribution,
        subject_type=SUBJECT_TYPE,
        subject_id=proposal.id,
        payload={
            "approve": True,
            "reason": note,
            "direction": direction,
            "scope": f"{proposal.scope_level}:{proposal.scope_id}",
            "two_person": two_person,
            "awaiting_second_approver": awaiting,
            "from_status": from_status,
            "status": proposal.status,
        },
    )
    return proposal


# ---------------------------------------------------------------------------
# Apply (privileged)
# ---------------------------------------------------------------------------


def apply_proposal(
    session: Session, proposal: ChangeProposal, *, actor: str | None = None, automated: bool
) -> ChangeProposal:
    """Make the change, directly or as a canary; or settle a canary that has finished.

    ``automated=True`` means the loop is acting with nobody deciding; ``actor`` is then
    ignored and the step is attributed to the automation actor.
    """
    settings = get_settings()
    attribution = chain.attribution(automated=automated, actor=actor)
    actor_id = attribution["actor_id"]
    try:
        applier = get_applier(proposal.kind)
    except ApplierError as exc:
        raise ProposalError(str(exc)) from exc

    # --- settling a staged change ---------------------------------------
    if proposal.status == contract.CANARY:
        if applier.stage_status is None:
            raise ProposalError(f"kind '{proposal.kind}' cannot be staged")
        try:
            stage = applier.stage_status(session, proposal)
        except ApplierError as exc:
            raise ProposalError(str(exc)) from exc
        if stage == "rolling":
            raise IllegalTransition(
                f"proposal {proposal.id} is still in canary; it is applied when the canary "
                "completes"
            )
        if stage == "completed":
            _require_transition(proposal, contract.APPLIED, "complete")
            proposal.status = contract.APPLIED
            proposal.applied_at = utcnow()
            action = CANARY_COMPLETED_ACTION
        else:
            _require_transition(proposal, contract.ROLLED_BACK, "roll back")
            proposal.status = contract.ROLLED_BACK
            proposal.rolled_back_at = utcnow()
            proposal.outcome_note = "canary health gate rolled the change back"
            action = CANARY_ROLLED_BACK_ACTION
        session.flush()
        chain.append(
            session,
            action,
            **attribution,
            subject_type=SUBJECT_TYPE,
            subject_id=proposal.id,
            payload={"canary": stage, "status": proposal.status},
        )
        return proposal

    # --- making the change ------------------------------------------------
    target = (
        contract.CANARY
        if (proposal.diff_json or {}).get("stage") == "canary"
        else (contract.APPLIED)
    )
    direction = _refresh_direction(session, proposal, automated=automated, actor=actor_id)
    level = proposal.autonomy_level
    from_status = proposal.status

    if automated:
        if proposal.status not in (contract.PROVEN, contract.APPROVED):
            raise IllegalTransition(
                f"cannot apply proposal {proposal.id} automatically: it is "
                f"'{proposal.status}', and only a proven change can be applied"
            )
        if settings.improvement_frozen:
            raise AutomationRefused("the improvement loop is frozen; no automated change applies")
        level = effective_autonomy(session, proposal.kind, proposal.autonomy_level)
        if not contract.may_apply_automatically(
            direction=direction, kind=proposal.kind, autonomy_level=level
        ):
            raise AutomationRefused(
                f"proposal {proposal.id} ({proposal.kind}, {direction}, effective autonomy "
                f"{level}) may not be applied automatically; a person has to decide"
            )
        cap = settings.improvement_max_auto_changes_per_day
        if automated_applies_last_day(session) >= cap:
            raise AutomationRefused(
                f"the daily cap of {cap} automated changes for this tenant is reached"
            )
        if proposal.status == contract.PROVEN:
            _require_transition(proposal, contract.APPROVED, "approve")
            proposal.status = contract.APPROVED
            proposal.decided_by = actor_id
            proposal.decided_at = utcnow()
            proposal.decision_note = f"auto-approved at autonomy {level}"
            session.flush()
            chain.append(
                session,
                DECIDE_ACTION,
                **attribution,
                subject_type=SUBJECT_TYPE,
                subject_id=proposal.id,
                payload={
                    "approve": True,
                    "reason": proposal.decision_note,
                    "direction": direction,
                    "autonomy_level": level,
                    "from_status": contract.PROVEN,
                    "status": contract.APPROVED,
                },
            )
    else:
        if proposal.status != contract.APPROVED:
            raise IllegalTransition(
                f"cannot apply proposal {proposal.id}: it is '{proposal.status}', and only an "
                "approved change can be applied"
            )
        if (
            contract.requires_second_approver(direction=direction, scope_level=proposal.scope_level)
            and not proposal.second_approver
        ):
            raise ProposalError(
                f"proposal {proposal.id} now loosens at org level and has one approver; a "
                "second, different person must approve it before it is applied"
            )

    _require_transition(proposal, target, "apply")
    try:
        changed = applier.apply(session, proposal, actor=actor_id)
    except ApplierError as exc:
        raise ProposalError(str(exc)) from exc

    proposal.status = contract.CANARY if changed.get("staged") == "canary" else contract.APPLIED
    proposal.applied_at = utcnow()
    session.flush()
    chain.append(
        session,
        APPLY_ACTION,
        **attribution,
        subject_type=SUBJECT_TYPE,
        subject_id=proposal.id,
        payload={
            "automated": automated,
            "kind": proposal.kind,
            "direction": direction,
            "autonomy_level": level,
            "from_status": from_status,
            "status": proposal.status,
            "changed": changed,
        },
    )
    return proposal


# ---------------------------------------------------------------------------
# Rollback (privileged) and verification
# ---------------------------------------------------------------------------


def rollback_proposal(
    session: Session,
    proposal: ChangeProposal,
    *,
    reason: str,
    actor: str | None = None,
    automated: bool = False,
) -> ChangeProposal:
    """Undo an applied or canaried change.

    Reverting a tightening loosens, so automation may only roll back changes that did
    not tighten; undoing a tightening is a decision for a person.
    """
    reason = _require_note(reason, "a rollback")
    attribution = chain.attribution(automated=automated, actor=actor)
    _require_transition(proposal, contract.ROLLED_BACK, "roll back")
    if automated and not contract.may_rollback_automatically(direction=proposal.direction):
        raise AutomationRefused(
            f"rolling back proposal {proposal.id} would loosen a control; a person has to "
            "decide that"
        )
    try:
        restored = get_applier(proposal.kind).revert(
            session, proposal, actor=attribution["actor_id"]
        )
    except ApplierError as exc:
        raise ProposalError(str(exc)) from exc

    from_status = proposal.status
    proposal.status = contract.ROLLED_BACK
    proposal.rolled_back_at = utcnow()
    proposal.outcome_note = reason
    session.flush()
    chain.append(
        session,
        ROLLBACK_ACTION,
        **attribution,
        subject_type=SUBJECT_TYPE,
        subject_id=proposal.id,
        payload={
            "reason": reason,
            "automated": automated,
            "kind": proposal.kind,
            "from_status": from_status,
            "restored": restored,
        },
    )
    return proposal


def verify_proposal(
    session: Session,
    proposal: ChangeProposal,
    *,
    verified: bool,
    note: str,
    actor: str | None = None,
) -> ChangeProposal:
    """Close the loop on an applied change.

    ``verified=False`` records the failure and rolls the change back. If the rollback
    is one automation may not take (it would loosen), the proposal stays applied with
    the failure recorded, for a person to act on.
    """
    note = _require_note(note, "a verification")
    automated = actor is None
    attribution = chain.attribution(automated=automated, actor=actor)

    if verified:
        _require_transition(proposal, contract.VERIFIED, "verify")
        proposal.status = contract.VERIFIED
        proposal.verified_at = utcnow()
        proposal.outcome_note = note
        session.flush()
        chain.append(
            session,
            VERIFY_ACTION,
            **attribution,
            subject_type=SUBJECT_TYPE,
            subject_id=proposal.id,
            payload={"verified": True, "note": note},
        )
        return proposal

    _require_transition(proposal, contract.ROLLED_BACK, "fail verification of")
    proposal.outcome_note = f"verification failed: {note}"
    session.flush()
    chain.append(
        session,
        VERIFY_FAILED_ACTION,
        **attribution,
        subject_type=SUBJECT_TYPE,
        subject_id=proposal.id,
        payload={"verified": False, "note": note},
    )
    try:
        return rollback_proposal(
            session,
            proposal,
            reason=f"verification failed: {note}",
            actor=actor,
            automated=automated,
        )
    except AutomationRefused:
        return proposal


# ---------------------------------------------------------------------------
# Track record
# ---------------------------------------------------------------------------


def rollback_rate(session: Session, *, kind: str, window_days: int = 30) -> float:
    """Share of this kind's changes that reached production in the window and were undone."""
    since = utcnow() - dt.timedelta(days=window_days)
    rows = session.execute(
        select(ChangeProposal.status).where(
            ChangeProposal.kind == kind,
            ChangeProposal.status.in_(
                [contract.CANARY, contract.APPLIED, contract.VERIFIED, contract.ROLLED_BACK]
            ),
            or_(ChangeProposal.applied_at >= since, ChangeProposal.rolled_back_at >= since),
        )
    ).all()
    if not rows:
        return 0.0
    rolled_back = sum(1 for (status,) in rows if status == contract.ROLLED_BACK)
    return rolled_back / len(rows)


def effective_autonomy(session: Session, kind: str, requested_level: str) -> str:
    """The level a class has actually earned: one lower while it is over its rollback budget."""
    if requested_level not in contract.AUTONOMY_LEVELS:
        return "L1"
    if rollback_rate(session, kind=kind) > get_settings().improvement_rollback_budget:
        return contract.lower_autonomy(requested_level)
    return requested_level


__all__ = [
    "AutomationRefused",
    "IllegalTransition",
    "ProposalError",
    "apply_proposal",
    "attach_proof",
    "automated_applies_last_day",
    "decide",
    "effective_autonomy",
    "file_proposal",
    "get_proposal",
    "list_proposals",
    "proposal_json",
    "rollback_proposal",
    "rollback_rate",
    "verify_proposal",
]
