"""Loops that turn what the platform has observed into change proposals.

A loop never edits configuration. It reads evidence, decides whether a concrete change
is warranted, and files a :class:`~agentfox.core.models.ChangeProposal` that a person (or,
for classes that have earned it, automation) takes through the lifecycle.

``propose_threshold_changes`` is the first loop. ``threshold_recommendations`` tells
operators which detectors could run at a higher cut-off; here that advice becomes a
proposal against the policy rule that actually enforces it, rather than a number on a
page. Raising a restrictive rule's ``min_score`` loosens it, so
these proposals always need a person to decide; the loop's job is to take the
arithmetic, the rule lookup and the blast-radius check off their plate.

Three properties keep a proposal no wider than its evidence:

* **Proven at filing.** Each proposal carries a replay proof — the labelled detections
  replayed against the proposed cut-off (and a count of recorded detections that would
  stop firing) — so a person can approve it; one that would lose a true positive is
  filed unproven and cannot be.
* **Scoped to where the labels came from.** A rule is proposed only when it fired on
  the labelled decisions (where the labels name one), and when the labels came from
  some of the agents the rule governs, the change is scoped to those agents: the rule
  is split so the others keep the current cut-off.
* **Withdrawn when the labels move.** An open proposal the latest labels no longer
  support is superseded rather than left to be approved on numbers that no longer hold.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    Agent,
    ChangeProposal,
    Decision,
    DetectionFinding,
    DetectorRun,
    GuardrailFeedback,
    Policy,
    Trace,
    utcnow,
)
from agentfox.detection.tuning import threshold_recommendations
from agentfox.improvement import contract
from agentfox.improvement.appliers import (
    ApplierError,
    _document,
    _live_policy,
    rule_agent_restriction,
)
from agentfox.improvement.proposals import SUBJECT_TYPE, attach_proof, file_proposal
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


def _fingerprint(
    policy_key: str, rule_id: str, detector_key: str, target: float, agents: list[str]
) -> str:
    raw = f"{KIND}|{policy_key}|{rule_id}|{detector_key}|{target:.3f}"
    if agents:
        raw += "|" + ",".join(sorted(agents))
    return hashlib.sha256(raw.encode()).hexdigest()


def _open_loop_proposals(session: Session) -> list[ChangeProposal]:
    return list(
        session.scalars(
            select(ChangeProposal).where(
                ChangeProposal.kind == KIND,
                ChangeProposal.source == SOURCE,
                ChangeProposal.status.in_([contract.PROPOSED, contract.PROVEN]),
            )
        )
    )


def _supersede(session: Session, stale: ChangeProposal, *, note: str, keep: str | None) -> bool:
    if not contract.transition_allowed(stale.status, contract.SUPERSEDED):
        return False
    from_status = stale.status
    stale.status = contract.SUPERSEDED
    stale.outcome_note = note
    stale.decided_at = utcnow()
    session.flush()
    chain.append(
        session,
        SUPERSEDE_ACTION,
        **chain.attribution(automated=True),
        subject_type=SUBJECT_TYPE,
        subject_id=stale.id,
        payload={"from_status": from_status, "superseded_by": keep, "note": note},
    )
    return True


def _supersede_stale(
    session: Session,
    *,
    policy_key: str,
    rule_id: str,
    detector_key: str,
    agents: list[str],
    keep: str,
) -> list[str]:
    """An open, undecided proposal for the same rule, detector and agent scope with an
    older target is replaced rather than left to be approved against numbers that no
    longer hold."""
    out: list[str] = []
    for stale in _open_loop_proposals(session):
        if stale.id == keep:
            continue
        diff = stale.diff_json or {}
        if (
            diff.get("policy"),
            diff.get("rule_id"),
            diff.get("detector_key"),
            sorted(diff.get("agents") or []),
        ) != (policy_key, rule_id, detector_key, sorted(agents)):
            continue
        if _supersede(
            session,
            stale,
            note=f"superseded by {keep}: labels now support a different cut-off",
            keep=keep,
        ):
            out.append(stale.id)
    return out


def _governed_agents(doc, rule, agents: dict[str, str]) -> set[str]:
    """Registered agents this rule can fire for: the pack's scope, the rule's own
    ``agent`` glob and any agent restriction a previous scoped change wrote into it."""
    allow, deny = rule_agent_restriction(rule)
    out: set[str] = set()
    for slug in agents.values():
        if not doc.matches_scope(slug, None):
            continue
        if rule.when.agent and not fnmatch.fnmatch(slug, rule.when.agent):
            continue
        if allow is not None and slug not in allow:
            continue
        if slug in deny:
            continue
        out.add(slug)
    return out


def _replay_proof(
    session: Session,
    *,
    condition,
    detector_key: str,
    current: float,
    target: float,
    labelled: list[GuardrailFeedback],
    agents: list[str],
    since: dt.datetime,
) -> tuple[dict[str, Any], bool]:
    """Replay the labelled detections, and the recorded ones, against the proposed
    cut-off. Passes when every labelled false positive stops firing and every labelled
    true positive still fires."""
    fps = [f for f in labelled if f.label == "false_positive"]
    tps = [f for f in labelled if f.label == "true_positive"]
    fp_removed = [f for f in fps if float(f.score) < target]
    tp_kept = [f for f in tps if float(f.score) >= target]

    # Recorded detections from this detector the rule fires on today and would not
    # after the change — the blast radius beyond the labels, within the same scope.
    stmt = (
        select(DetectionFinding.entity_type, DetectionFinding.score, Trace.agent_slug)
        .join(DetectorRun, DetectorRun.id == DetectionFinding.detector_run_id)
        .join(Trace, Trace.id == DetectionFinding.trace_id, isouter=True)
        .where(
            DetectorRun.detector_key == detector_key,
            DetectionFinding.score >= current,
            DetectionFinding.score < target,
            DetectionFinding.created_at >= since,
        )
    )
    would_stop = [
        row
        for row in session.execute(stmt)
        if _covers(condition, row.entity_type) and (not agents or row.agent_slug in agents)
    ]
    proof = {
        "method": "replay of the labelled detections against the proposed cut-off",
        "from": current,
        "to": target,
        "agents": agents or ["*"],
        "false_positives": len(fps),
        "false_positives_no_longer_firing": len(fp_removed),
        "true_positives": len(tps),
        "true_positives_still_firing": len(tp_kept),
        "true_positives_lost": len(tps) - len(tp_kept),
        "recorded_detections_that_would_stop_firing": len(would_stop),
        "feedback_ids": [f.id for f in labelled][:50],
    }
    return proof, bool(fps) and len(fp_removed) == len(fps) and len(tp_kept) == len(tps)


def propose_threshold_changes(session: Session, *, days: int = 30) -> LoopReport:
    """File a ``policy.rule_min_score`` proposal for each clean threshold recommendation.

    A recommendation maps onto a rule only when that rule's detection condition covers
    every entity type the detector was labelled on, names an entity (a catch-all rule
    is never retuned for one detector's noise), restricts rather than allows, and sits
    below the suggested cut-off — and, when the labels point at decisions, only when the
    rule fired on them. Other detectors that emit entities the rule covers are listed in
    the evidence, because raising the bar changes their outcomes too.

    Each proposal is scoped to the agents the labels came from (org-wide only when the
    labels cover every agent the rule governs, or name none) and carries a replay proof.
    Open proposals this run no longer supports are superseded.
    """
    report = LoopReport()
    since = utcnow() - dt.timedelta(days=days)
    recommendations = [
        r for r in threshold_recommendations(session, days=days) if r.action == "raise_threshold"
    ]
    supported: set[str] = set()

    feedback = list(
        session.scalars(select(GuardrailFeedback).where(GuardrailFeedback.created_at >= since))
    )
    policies = list(session.scalars(select(Policy).order_by(Policy.key)))
    agents_by_id = {a.id: a.slug for a in session.scalars(select(Agent))}

    for rec in recommendations:
        judged = [
            f
            for f in feedback
            if f.detector_key == rec.detector_key and f.label in ("false_positive", "true_positive")
        ]
        labelled = sorted({f.entity_type for f in judged if f.entity_type})
        if not labelled:
            report.skipped.append(
                {"detector_key": rec.detector_key, "reason": "labels carry no entity type"}
            )
            continue

        # Where the labels came from. A label with no agent is org-wide evidence.
        label_agents = {agents_by_id.get(f.agent_id) for f in judged}
        unattributed = None in label_agents
        label_agents.discard(None)

        # Which rules actually fired on the labelled decisions, when the labels say.
        fired: set[str] = set()
        decision_ids = [f.decision_id for f in judged if f.decision_id]
        if decision_ids:
            for decision in session.scalars(select(Decision).where(Decision.id.in_(decision_ids))):
                fired |= {str(r.get("rule_id")) for r in (decision.rules_fired_json or []) if r}

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
                if fired and rule.id not in fired:
                    report.skipped.append(
                        {**where, "reason": "rule did not fire on any labelled decision"}
                    )
                    continue
                current = float(condition.min_score)
                target = float(rec.suggested_threshold)
                if target <= current:
                    report.skipped.append(
                        {**where, "reason": f"rule already at {current}, at or above {target}"}
                    )
                    continue

                governed = _governed_agents(doc, rule, agents_by_id)
                if unattributed or not governed or governed <= label_agents:
                    scoped: list[str] = []
                else:
                    scoped = sorted(label_agents & governed)
                    if not scoped:
                        report.skipped.append(
                            {**where, "reason": "rule does not govern the labelled agents"}
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
                in_scope = [
                    f for f in judged if not scoped or agents_by_id.get(f.agent_id) in scoped
                ]
                proof, passed = _replay_proof(
                    session,
                    condition=condition,
                    detector_key=rec.detector_key,
                    current=current,
                    target=target,
                    labelled=in_scope,
                    agents=scoped,
                    since=since,
                )
                fingerprint = _fingerprint(policy.key, rule.id, rec.detector_key, target, scoped)
                existing_ids = set(
                    session.scalars(
                        select(ChangeProposal.id).where(ChangeProposal.fingerprint == fingerprint)
                    )
                )
                who = ", ".join(scoped) if scoped else ""
                diff: dict[str, Any] = {
                    "policy": policy.key,
                    "rule_id": rule.id,
                    "detector_key": rec.detector_key,
                    "from": current,
                    "to": target,
                    "stage": "canary",
                }
                if scoped:
                    diff["agents"] = scoped
                proposal = file_proposal(
                    session,
                    kind=KIND,
                    source=SOURCE,
                    target_type="policy",
                    target_ref=policy.key,
                    scope_level="agent" if scoped else "org",
                    scope_id=",".join(scoped) if scoped else "*",
                    title=(
                        f"Raise {policy.key}/{rule.id} min_score {current} → {target}"
                        + (f" for {who}" if who else "")
                    ),
                    rationale=rec.rationale,
                    direction=contract.LOOSENS,
                    diff=diff,
                    evidence={
                        "recommendation": rec.to_json(),
                        "window_days": days,
                        "labelled_entity_types": labelled,
                        "labelled_agents": sorted(label_agents),
                        "unattributed_labels": unattributed,
                        "agents_the_rule_governs": sorted(governed),
                        "other_detectors_on_this_rule": also_affected,
                    },
                    expected_effect={
                        "false_positives_removed": proof["false_positives_no_longer_firing"],
                        "true_positives_lost": proof["true_positives_lost"],
                    },
                    autonomy_level="L1",
                    fingerprint=fingerprint,
                )
                supported.add(proposal.id)
                (report.refreshed if proposal.id in existing_ids else report.filed).append(
                    proposal.id
                )
                if proposal.status == contract.PROPOSED:
                    attach_proof(session, proposal, proof, passed=passed)
                report.superseded += _supersede_stale(
                    session,
                    policy_key=policy.key,
                    rule_id=rule.id,
                    detector_key=rec.detector_key,
                    agents=scoped,
                    keep=proposal.id,
                )
        if not matched:
            report.skipped.append(
                {
                    "detector_key": rec.detector_key,
                    "reason": f"no live rule covers entity types {labelled}",
                }
            )

    # A proposal nothing filed this run is one the labels no longer support: the
    # detector stopped separating cleanly, lost its sample, or the rule moved. Leaving
    # it open would let someone approve a loosening on evidence that is gone.
    for stale in _open_loop_proposals(session):
        if stale.id in supported or stale.id in report.superseded:
            continue
        if _supersede(
            session,
            stale,
            note="superseded: the current labels no longer support this cut-off",
            keep=None,
        ):
            report.superseded.append(stale.id)
    return report


__all__ = ["LoopReport", "propose_threshold_changes"]
