"""The threshold loop: labels in, a proposal a person decides out — never a silent edit."""

from __future__ import annotations

from sqlalchemy import select

from agentfox.improvement import contract
from agentfox.improvement.loops import propose_threshold_changes
from agentfox.improvement.proposals import apply_proposal, decide
from agentfox.core.models import ChangeProposal, GuardrailFeedback
from agentfox.policy import PolicyDocument, save_policy

POLICY = """
key: loop-test
mode: enforce
default_effect: allow
rules:
  - id: ssn.block
    when: {detection: {entity: PII_SSN, min_score: 0.3}}
    effect: block
  - id: anything.escalate
    when: {detection: {min_score: 0.2}}
    effect: escalate
  - id: email.block
    when: {detection: {entity_prefix: PII_EMAIL, min_score: 0.3}}
    effect: block
"""


def _label(session, label: str, score: float, detector="pii.native", entity="PII_SSN"):
    session.add(
        GuardrailFeedback(detector_key=detector, entity_type=entity, label=label, score=score)
    )
    session.flush()


def _clean_split(session, fps=(0.30, 0.35, 0.40, 0.42, 0.45), tps=(0.80, 0.90)):
    for s in fps:
        _label(session, "false_positive", s)
    for s in tps:
        _label(session, "true_positive", s)


def _proposals(session):
    return list(
        session.scalars(select(ChangeProposal).where(ChangeProposal.source == "tuning.threshold"))
    )


def test_clean_split_files_one_loosening_proposal_on_the_covering_rule(session):
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    _clean_split(session)
    report = propose_threshold_changes(session)

    [proposal] = _proposals(session)
    assert report.filed == [proposal.id]
    assert proposal.diff_json["rule_id"] == "ssn.block"
    assert proposal.diff_json["from"] == 0.3
    assert proposal.diff_json["to"] == 0.46
    assert proposal.direction == contract.LOOSENS
    assert proposal.status == contract.PROPOSED
    assert proposal.proposed_by  # attributed to automation, not blank
    reasons = {s.get("rule_id"): s["reason"] for s in report.skipped}
    assert reasons["anything.escalate"] == "rule matches every detection"
    assert "email.block" not in reasons  # does not cover PII_SSN at all


def test_rerunning_refreshes_instead_of_duplicating(session):
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    _clean_split(session)
    first = propose_threshold_changes(session)
    second = propose_threshold_changes(session)
    assert second.filed == []
    assert second.refreshed == first.filed
    assert len(_proposals(session)) == 1


def test_new_labels_supersede_a_stale_undecided_proposal(session):
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    _clean_split(session)
    [old_id] = propose_threshold_changes(session).filed
    _label(session, "false_positive", 0.6)  # the cut-off moves up
    report = propose_threshold_changes(session)
    assert report.superseded == [old_id]
    assert session.get(ChangeProposal, old_id).status == contract.SUPERSEDED
    [new_id] = report.filed
    assert session.get(ChangeProposal, new_id).diff_json["to"] == 0.61


def test_the_loop_cannot_apply_what_it_filed(session):
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    _clean_split(session)
    [pid] = propose_threshold_changes(session).filed
    proposal = session.get(ChangeProposal, pid)
    assert not contract.may_apply_automatically(
        direction=proposal.direction, kind=proposal.kind, autonomy_level="L4"
    )
    decide(session, proposal, approve=False, actor="sec@example.com", note="want more labels")
    assert proposal.status == contract.REJECTED
    try:
        apply_proposal(session, proposal, automated=True)
    except Exception:
        pass
    assert proposal.status == contract.REJECTED


def test_other_detectors_sharing_the_rule_are_named(session):
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    _clean_split(session)
    _label(session, "true_positive", 0.35, detector="pii.presidio")
    [pid] = propose_threshold_changes(session).filed
    evidence = session.get(ChangeProposal, pid).evidence_json
    assert evidence["other_detectors_on_this_rule"] == ["pii.presidio"]


def test_no_covering_rule_is_reported_not_dropped(session):
    _clean_split(session)
    report = propose_threshold_changes(session)
    assert report.filed == []
    assert any("no live rule covers" in s["reason"] for s in report.skipped)
