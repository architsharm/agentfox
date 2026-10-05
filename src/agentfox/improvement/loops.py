"""Loops that turn what the platform has observed into change proposals.

A loop never edits configuration. It reads evidence, decides whether a concrete change
is warranted, and files a :class:`~agentfox.core.models.ChangeProposal` that a person (or,
for classes that have earned it, automation) takes through the lifecycle.

``propose_threshold_changes`` is the first loop. ``threshold_recommendations`` has told
operators for a long time which detectors could run at a higher cut-off, but the number
was only ever shown on a page. Here that advice becomes a proposal against the policy
rule that actually enforces it. Raising a restrictive rule's ``min_score`` loosens it, so
these proposals always need a person to decide; the loop's job is to take the
arithmetic, the rule lookup and the blast-radius check off their plate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import ChangeProposal, GuardrailFeedback, Policy, utcnow
from agentfox.detection.tuning import threshold_recommendations
from agentfox.improvement import contract
from agentfox.improvement.appliers import ApplierError, _document, _live_policy
from agentfox.improvement.proposals import SUBJECT_TYPE, file_proposal
from agentfox.prove.audit import chain

KIND = "policy.rule_min_score"
SOURCE = "tuning.threshold"
SUPERSEDE_ACTION = "proposal.superseded"


@dataclass
class LoopReport:
    filed: list[str] = field(default_factory=list)
    refreshed: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    #: Recommendations that could not become a proposal, and why. Reported, not dropped.
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "filed": self.filed,
            "refreshed": self.refreshed,
            "superseded": self.superseded,
            "skipped": self.skipped,
        }


def _covers(condition, entity_type: str) -> bool:
    if condition.entity is not None:
        return entity_type == condition.entity
    if condition.entity_prefix:
        return entity_type.startswith(condition.entity_prefix)
    return True


def _fingerprint(policy_key: str, rule_id: str, detector_key: str, target: float) -> str:
    raw = f"{KIND}|{policy_key}|{rule_id}|{detector_key}|{target:.3f}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _supersede_stale(
    session: Session, *, policy_key: str, rule_id: str, detector_key: str, keep: str
) -> list[str]:
    """An open, undecided proposal for the same rule and detector with an older target
    is replaced rather than left to be approved against numbers that no longer hold."""
    out: list[str] = []
    candidates = session.scalars(
        select(ChangeProposal).where(
            ChangeProposal.kind == KIND,
            ChangeProposal.source == SOURCE,
            ChangeProposal.status.in_([contract.PROPOSED, contract.PROVEN]),
            ChangeProposal.id != keep,
        )
    )
    for stale in candidates:
        diff = stale.diff_json or {}
        if (diff.get("policy"), diff.get("rule_id"), diff.get("detector_key")) != (
            policy_key,
            rule_id,
            detector_key,
        ):
            continue
        if not contract.transition_allowed(stale.status, contract.SUPERSEDED):
            continue
        from_status = stale.status
        stale.status = contract.SUPERSEDED
        stale.outcome_note = f"superseded by {keep}: labels now support a different cut-off"
        stale.decided_at = utcnow()
        session.flush()
        chain.append(
            session,
            SUPERSEDE_ACTION,
            **chain.attribution(automated=True),
            subject_type=SUBJECT_TYPE,
            subject_id=stale.id,
            payload={"from_status": from_status, "superseded_by": keep},
        )
        out.append(stale.id)
    return out


def propose_threshold_changes(session: Session, *, days: int = 30) -> LoopReport:
    """File a ``policy.rule_min_score`` proposal for each clean threshold recommendation.

    A recommendation maps onto a rule only when that rule's detection condition covers
    every entity type the detector was labelled on, names an entity (a catch-all rule
    is never retuned for one detector's noise), restricts rather than allows, and sits
    below the suggested cut-off. Other detectors that emit entities the rule covers are
    listed in the evidence, because raising the bar changes their outcomes too.
    """
    report = LoopReport()
    recommendations = [
        r for r in threshold_recommendations(session, days=days) if r.action == "raise_threshold"
    ]
    if not recommendations:
        return report

    feedback = list(session.scalars(select(GuardrailFeedback)))
    policies = list(session.scalars(select(Policy).order_by(Policy.key)))

    for rec in recommendations:
        labelled = sorted(
            {
                f.entity_type
                for f in feedback
                if f.detector_key == rec.detector_key
                and f.label in ("false_positive", "true_positive")
                and f.entity_type
            }
        )
        if not labelled:
            report.skipped.append(
                {"detector_key": rec.detector_key, "reason": "labels carry no entity type"}
            )
            continue
        matched = False
        for policy in policies:
            try:
                _policy, version, _binding = _live_policy(session, policy.key)
            except ApplierError:
                continue
            doc = _document(version)
            for rule in doc.rules:
                condition = rule.when.detection
                if condition is None or not all(_covers(condition, e) for e in labelled):
                    continue
                matched = True
                where = {"detector_key": rec.detector_key, "policy": policy.key, "rule_id": rule.id}
                if condition.entity is None and not condition.entity_prefix:
                    report.skipped.append({**where, "reason": "rule matches every detection"})
                    continue
                if rule.effect == "allow":
                    report.skipped.append({**where, "reason": "allow rules are not retuned"})
                    continue
                current = float(condition.min_score)
                target = float(rec.suggested_threshold)
                if target <= current:
                    report.skipped.append(
                        {**where, "reason": f"rule already at {current}, at or above {target}"}
                    )
                    continue
                also_affected = sorted(
                    {
                        f.detector_key
                        for f in feedback
                        if f.detector_key
                        and f.detector_key != rec.detector_key
                        and f.entity_type
                        and _covers(condition, f.entity_type)
                    }
                )
                fingerprint = _fingerprint(policy.key, rule.id, rec.detector_key, target)
                existing_ids = set(
                    session.scalars(
                        select(ChangeProposal.id).where(ChangeProposal.fingerprint == fingerprint)
                    )
                )
                proposal = file_proposal(
                    session,
                    kind=KIND,
                    source=SOURCE,
                    target_type="policy",
                    target_ref=policy.key,
                    scope_level="org",
                    scope_id="*",
                    title=f"Raise {policy.key}/{rule.id} min_score {current} → {target}",
                    rationale=rec.rationale,
                    direction=contract.LOOSENS,
                    diff={
                        "policy": policy.key,
                        "rule_id": rule.id,
                        "detector_key": rec.detector_key,
                        "from": current,
                        "to": target,
                        "stage": "canary",
                    },
                    evidence={
                        "recommendation": rec.to_json(),
                        "window_days": days,
                        "labelled_entity_types": labelled,
                        "other_detectors_on_this_rule": also_affected,
                    },
                    expected_effect={
                        "false_positives_removed": rec.false_positives_removed,
                        "true_positives_lost": rec.true_positives_lost,
                    },
                    autonomy_level="L1",
                    fingerprint=fingerprint,
                )
                (report.refreshed if proposal.id in existing_ids else report.filed).append(
                    proposal.id
                )
                report.superseded += _supersede_stale(
                    session,
                    policy_key=policy.key,
                    rule_id=rule.id,
                    detector_key=rec.detector_key,
                    keep=proposal.id,
                )
        if not matched:
            report.skipped.append(
                {
                    "detector_key": rec.detector_key,
                    "reason": f"no live rule covers entity types {labelled}",
                }
            )
    return report


__all__ = ["LoopReport", "propose_threshold_changes"]
