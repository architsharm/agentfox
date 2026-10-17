"""The threshold loop: labels in, a proposal a person decides out — never a silent edit."""

from __future__ import annotations

from sqlalchemy import select

from agentfox.capabilities.improvement import contract
from agentfox.capabilities.improvement.loops import propose_threshold_changes
from agentfox.capabilities.improvement.proposals import apply_proposal, decide
from agentfox.core.models import ChangeProposal, GuardrailFeedback
from agentfox.platform.policy import PolicyDocument, save_policy

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
    # Filed with a passing replay proof, so a person can approve it (#27).
    assert proposal.status == contract.PROVEN
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


# ---------------------------------------------------------------------------
# #27 a proof is attached, so a person can approve; #28 scope and staleness
# ---------------------------------------------------------------------------


def _agent(session, slug):
    from agentfox.core.models import Agent

    agent = Agent(slug=slug, name=slug)
    session.add(agent)
    session.flush()
    return agent


def test_a_filed_proposal_carries_a_replay_proof_and_can_be_approved(session):
    """#27: from-labels proposals had no proof, so `decide` refused every one of them
    with "has not been proven yet"."""
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    _clean_split(session)
    [pid] = propose_threshold_changes(session).filed
    proposal = session.get(ChangeProposal, pid)
    proof = proposal.proof_json
    assert proof["passed"] is True
    assert proof["false_positives"] == 5 and proof["false_positives_no_longer_firing"] == 5
    assert proof["true_positives_lost"] == 0

    decide(session, proposal, approve=True, actor="sec@example.com", note="labels look right")
    decide(session, proposal, approve=True, actor="grc@example.com", note="agreed")
    assert proposal.status == contract.APPROVED


def test_a_cut_off_that_would_lose_a_true_positive_is_filed_unproven(session):
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    # Max FP 0.45 -> suggested 0.46; a TP at 0.455 sits between them.
    _clean_split(session, tps=(0.455, 0.9))
    [pid] = propose_threshold_changes(session).filed
    proposal = session.get(ChangeProposal, pid)
    assert proposal.proof_json["passed"] is False
    assert proposal.proof_json["true_positives_lost"] == 1
    assert proposal.status == contract.PROPOSED


def test_labels_from_one_agent_scope_the_change_to_that_agent(session):
    """#28: labels from one agent filed an org-wide loosening for every agent."""
    from agentfox.capabilities.improvement.proposals import apply_proposal
    from agentfox.platform.policy.engine import NativePolicyEngine
    from agentfox.platform.policy.model import PolicyInput

    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    noisy = _agent(session, "noisy-bot")
    _agent(session, "other-bot")
    for score in (0.30, 0.35, 0.40, 0.42, 0.45):
        session.add(
            GuardrailFeedback(
                detector_key="pii.native",
                entity_type="PII_SSN",
                label="false_positive",
                score=score,
                agent_id=noisy.id,
            )
        )
    for score in (0.80, 0.90):
        session.add(
            GuardrailFeedback(
                detector_key="pii.native",
                entity_type="PII_SSN",
                label="true_positive",
                score=score,
                agent_id=noisy.id,
            )
        )
    session.flush()

    [pid] = propose_threshold_changes(session).filed
    proposal = session.get(ChangeProposal, pid)
    assert (proposal.scope_level, proposal.scope_id) == ("agent", "noisy-bot")
    assert proposal.diff_json["agents"] == ["noisy-bot"]
    assert proposal.evidence_json["agents_the_rule_governs"] == ["noisy-bot", "other-bot"]

    # An agent-scoped loosening needs one approver, not two.
    decide(session, proposal, approve=True, actor="sec@example.com", note="noisy-bot only")
    assert proposal.status == contract.APPROVED
    apply_proposal(session, proposal, actor="sec@example.com", automated=False)

    from agentfox.capabilities.improvement.appliers import _document
    from agentfox.core.models import Policy, PolicyVersion

    # Staged as a canary: the candidate version is the newest one.
    policy = session.scalars(select(Policy).where(Policy.key == "loop-test")).one()
    version = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version.desc())
    ).first()
    doc = _document(version)
    assert [r.id for r in doc.rules][:2] == ["ssn.block", "ssn.block.for.noisy-bot"]
    engine = NativePolicyEngine()
    detection = [{"entity_type": "PII_SSN", "score": 0.40}]

    def fired(slug):
        decision = engine.evaluate(
            doc, PolicyInput(agent_slug=slug, surface="input", detections=detection)
        )
        return {r.rule_id for r in decision.rules_fired}

    assert not any(r.startswith("ssn.block") for r in fired("noisy-bot"))
    assert "ssn.block" in fired("other-bot")
    high = [{"entity_type": "PII_SSN", "score": 0.95}]
    still = engine.evaluate(
        doc, PolicyInput(agent_slug="noisy-bot", surface="input", detections=high)
    )
    assert any(r.rule_id.startswith("ssn.block") for r in still.rules_fired)


def test_only_rules_that_fired_on_the_labelled_decisions_are_proposed(session):
    """#28: every rule covering the entity got a proposal, including rules that never
    fired on the labelled traffic."""
    from agentfox.core.models import Decision

    two_rules = (
        POLICY
        + """  - id: ssn.escalate
    when: {detection: {entity: PII_SSN, min_score: 0.25}}
    effect: escalate
"""
    )
    save_policy(session, PolicyDocument.from_yaml(two_rules), bind_mode="enforce")
    decision = Decision(
        surface="input", verdict="block", rules_fired_json=[{"rule_id": "ssn.block"}]
    )
    session.add(decision)
    session.flush()
    for label, score in [("false_positive", s) for s in (0.30, 0.35, 0.40, 0.42, 0.45)] + [
        ("true_positive", 0.8),
        ("true_positive", 0.9),
    ]:
        session.add(
            GuardrailFeedback(
                detector_key="pii.native",
                entity_type="PII_SSN",
                label=label,
                score=score,
                decision_id=decision.id,
            )
        )
    session.flush()
    report = propose_threshold_changes(session)
    assert [session.get(ChangeProposal, p).diff_json["rule_id"] for p in report.filed] == [
        "ssn.block"
    ]
    reasons = {s.get("rule_id"): s["reason"] for s in report.skipped}
    assert reasons["ssn.escalate"] == "rule did not fire on any labelled decision"


def test_a_proposal_the_labels_no_longer_support_is_superseded(session):
    """#28: when the recommendation went away the stale proposal stayed open."""
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")
    _clean_split(session)
    [old_id] = propose_threshold_changes(session).filed
    _label(session, "true_positive", 0.31)  # no clean separation any more
    report = propose_threshold_changes(session)
    assert report.filed == []
    assert old_id in report.superseded
    assert session.get(ChangeProposal, old_id).status == contract.SUPERSEDED
