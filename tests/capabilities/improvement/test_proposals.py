"""The proposal lifecycle, through the real service, appliers and API.

These tests are about the rules that keep a self-improving governance product from
quietly rewriting its own guardrails: nothing is applied unproven or unapproved, a
loosening is never automatic, two people means two *different* people, the kill switch
and the daily cap hold, every step is attributable, and every change can be undone.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from agentfox.capabilities.detection.tuning import apply_suppression, record_feedback
from agentfox.capabilities.improvement import contract
from agentfox.capabilities.improvement.appliers import min_score_direction
from agentfox.capabilities.improvement.proposals import (
    AutomationRefused,
    IllegalTransition,
    ProposalError,
    apply_proposal,
    attach_proof,
    decide,
    effective_autonomy,
    file_proposal,
    rollback_proposal,
    rollback_rate,
    verify_proposal,
)
from agentfox.core.config import get_settings
from agentfox.core.models import (
    Agent,
    AuditEntry,
    ChangeProposal,
    Policy,
    PolicyBinding,
    PolicyCanary,
    PolicyVersion,
    Suppression,
    as_aware,
)
from agentfox.core.vocab import AUTOMATION_ACTOR_TYPE
from agentfox.platform.ledger.operator_log import PRIVILEGED, unaudited
from agentfox.platform.policy import PolicyDocument, save_policy
from tests.conftest import PII_TEXT, as_user

POLICY = """
key: proposal-test
mode: enforce
default_effect: allow
rules:
  - id: injection.block
    when: {detection: {entity_prefix: INJECTION, min_score: 0.8}}
    effect: block
    controls: [NOM-RTG-01]
"""

PROOF = {"replay": {"decisions": 200, "newly_blocked": 0}}


# --- fixtures -----------------------------------------------------------------


def _suppression(seeded, enforcer) -> Suppression:
    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    result = enforcer.evaluate(agent=agent, identity=None, content=PII_TEXT, surface="output")
    feedback = record_feedback(
        seeded,
        decision_id=result.decision_id,
        label="false_positive",
        detector_key="pii.native",
        actor="dev@example.com",
    )
    return apply_suppression(seeded, feedback_id=feedback.id, actor="sec@example.com", ttl_days=7)


def _file_revoke(session, suppression, **overrides) -> ChangeProposal:
    fields = dict(
        kind="suppression.revoke",
        source="tuning.suppression_hygiene",
        target_type="suppression",
        target_ref=suppression.id,
        scope_level="agent",
        scope_id=suppression.agent_id or "*",
        title="Revoke unused suppression",
        rationale="no hits in 30 days",
        direction="tightens",
        diff={"suppression_id": suppression.id},
        evidence={"hits": 0},
        autonomy_level="L3",
    )
    fields.update(overrides)
    return file_proposal(session, **fields)


def _policy(session) -> None:
    save_policy(session, PolicyDocument.from_yaml(POLICY), bind_mode="enforce")


def _file_min_score(session, to: float, *, scope_level="org", stage="direct", **overrides):
    fields = dict(
        kind="policy.rule_min_score",
        source="tuning.threshold",
        target_type="policy",
        target_ref="proposal-test",
        scope_level=scope_level,
        scope_id="*",
        title=f"Set injection.block min_score to {to}",
        rationale="precision report",
        direction="tightens",  # deliberately wrong for a raise: must be recomputed
        diff={
            "policy": "proposal-test",
            "rule_id": "injection.block",
            "from": 0.8,
            "to": to,
            "stage": stage,
        },
        evidence={"precision": 0.4},
        autonomy_level="L3",
    )
    fields.update(overrides)
    return file_proposal(session, **fields)


def _live_min_score(session) -> tuple[float, PolicyVersion]:
    policy = session.scalar(select(Policy).where(Policy.key == "proposal-test"))
    for version in session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version.desc())
    ):
        open_binding = session.scalar(
            select(PolicyBinding).where(
                PolicyBinding.policy_version_id == version.id,
                PolicyBinding.effective_to.is_(None),
            )
        )
        if open_binding is not None:
            rule = version.compiled_json["rules"][0]
            return rule["when"]["detection"]["min_score"], version
    raise AssertionError("no live binding")


def _entries(session, proposal) -> list[AuditEntry]:
    return list(
        session.scalars(
            select(AuditEntry).where(AuditEntry.subject_id == proposal.id).order_by(AuditEntry.seq)
        )
    )


# --- filing -----------------------------------------------------------------------


def test_the_same_problem_is_one_open_proposal(seeded, enforcer):
    suppression = _suppression(seeded, enforcer)
    first = _file_revoke(
        seeded, suppression, fingerprint="fp-1", evidence={"hits": 0}, related_finding_ids=["f1"]
    )
    second = _file_revoke(
        seeded,
        suppression,
        fingerprint="fp-1",
        evidence={"days_idle": 31},
        related_finding_ids=["f1", "f2"],
    )
    assert second.id == first.id
    assert seeded.query(ChangeProposal).count() == 1
    assert first.evidence_json == {"hits": 0, "days_idle": 31}
    assert first.related_finding_ids == ["f1", "f2"]
    assert [e.action for e in _entries(seeded, first)][-1] == "proposal.evidence_updated"

    # A closed proposal no longer absorbs new evidence: the problem is new again.
    decide(seeded, first, approve=False, actor="marcus@example.com", note="not now")
    third = _file_revoke(seeded, suppression, fingerprint="fp-1")
    assert third.id != first.id


def test_losing_a_filing_race_merges_instead_of_duplicating(seeded, enforcer, monkeypatch):
    """Simulate a concurrent filing: the look-up misses, the database index catches it."""
    from agentfox.capabilities.improvement import proposals as module

    suppression = _suppression(seeded, enforcer)
    first = _file_revoke(seeded, suppression, fingerprint="fp-race", evidence={"hits": 0})

    real_lookup = module._open_with_fingerprint
    calls = {"n": 0}

    def stale_then_real(session, fingerprint):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_lookup(session, fingerprint)

    monkeypatch.setattr(module, "_open_with_fingerprint", stale_then_real)
    second = _file_revoke(seeded, suppression, fingerprint="fp-race", evidence={"days_idle": 9})

    assert second.id == first.id
    assert seeded.query(ChangeProposal).filter_by(fingerprint="fp-race").count() == 1
    assert first.evidence_json == {"hits": 0, "days_idle": 9}


def test_enums_are_validated_against_the_contract(seeded, enforcer):
    suppression = _suppression(seeded, enforcer)
    for bad in ({"scope_level": "galaxy"}, {"direction": "sideways"}, {"autonomy_level": "L9"}):
        with pytest.raises(ProposalError):
            _file_revoke(seeded, suppression, **bad)


def test_direction_is_computed_from_the_diff_not_trusted(seeded):
    _policy(seeded)
    raise_it = _file_min_score(seeded, 0.95, direction="tightens")
    lower_it = _file_min_score(seeded, 0.5, direction="loosens")
    assert raise_it.direction == contract.LOOSENS
    assert lower_it.direction == contract.TIGHTENS
    filed = _entries(seeded, raise_it)[0]
    assert filed.payload_json["claimed_direction"] == "tightens"
    assert filed.payload_json["direction"] == "loosens"
    # An allow rule firing less or more cannot be reasoned about locally: a person decides.
    assert min_score_direction("allow", 0.8, 0.5) == contract.LOOSENS
    assert min_score_direction("allow", 0.8, 0.9) == contract.LOOSENS


# --- transitions --------------------------------------------------------------------


def test_cannot_apply_unproven_or_unapproved(seeded, enforcer):
    suppression = _suppression(seeded, enforcer)
    proposal = _file_revoke(seeded, suppression, autonomy_level="L1")

    with pytest.raises(IllegalTransition):
        apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)
    with pytest.raises(IllegalTransition):
        apply_proposal(seeded, proposal, automated=True)
    with pytest.raises(IllegalTransition, match="not been proven"):
        decide(seeded, proposal, approve=True, actor="marcus@example.com", note="looks fine")

    attach_proof(seeded, proposal, {"replay": "regressed"}, passed=False)
    assert proposal.status == contract.PROPOSED

    attach_proof(seeded, proposal, PROOF, passed=True)
    assert proposal.status == contract.PROVEN
    with pytest.raises(IllegalTransition, match="only an approved change"):
        apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)
    with pytest.raises(IllegalTransition):
        verify_proposal(seeded, proposal, verified=True, note="early", actor="marcus@example.com")
    with pytest.raises(IllegalTransition):
        rollback_proposal(seeded, proposal, reason="nothing applied", actor="marcus@example.com")
    assert suppression.active


def test_a_decision_needs_a_note_and_a_name(seeded, enforcer):
    suppression = _suppression(seeded, enforcer)
    proposal = _file_revoke(seeded, suppression)
    attach_proof(seeded, proposal, PROOF, passed=True)
    with pytest.raises(ProposalError):
        decide(seeded, proposal, approve=True, actor="marcus@example.com", note="  ")
    with pytest.raises(ValueError):
        decide(seeded, proposal, approve=True, actor="", note="fine")


# --- automation -------------------------------------------------------------------


def test_automation_never_applies_a_loosening_at_any_autonomy_level(seeded):
    _policy(seeded)
    for level in contract.AUTONOMY_LEVELS:
        proposal = _file_min_score(seeded, 0.95, autonomy_level=level, scope_level="team")
        attach_proof(seeded, proposal, PROOF, passed=True)
        with pytest.raises(AutomationRefused):
            apply_proposal(seeded, proposal, automated=True)
        assert proposal.status == contract.PROVEN
    assert _live_min_score(seeded)[0] == 0.8


def test_automation_applies_a_tightening_at_an_earned_level_only(seeded, enforcer):
    suppression = _suppression(seeded, enforcer)
    proposal = _file_revoke(seeded, suppression, autonomy_level="L2")
    attach_proof(seeded, proposal, PROOF, passed=True)
    with pytest.raises(AutomationRefused):
        apply_proposal(seeded, proposal, automated=True)

    proposal.autonomy_level = "L3"
    apply_proposal(seeded, proposal, automated=True)
    assert proposal.status == contract.APPLIED
    assert proposal.decided_by == get_settings().improvement_actor_id
    assert not suppression.active


def test_frozen_loop_applies_nothing(seeded, enforcer, monkeypatch):
    monkeypatch.setattr(get_settings(), "improvement_frozen", True)
    suppression = _suppression(seeded, enforcer)
    proposal = _file_revoke(seeded, suppression)
    attach_proof(seeded, proposal, PROOF, passed=True)
    with pytest.raises(AutomationRefused, match="frozen"):
        apply_proposal(seeded, proposal, automated=True)
    assert suppression.active
    # The freeze stops the loop, not people.
    decide(seeded, proposal, approve=True, actor="marcus@example.com", note="do it by hand")
    apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)
    assert proposal.status == contract.APPLIED


def test_daily_cap_on_automated_applies(seeded, enforcer, monkeypatch):
    monkeypatch.setattr(get_settings(), "improvement_max_auto_changes_per_day", 1)
    first_sup = _suppression(seeded, enforcer)
    second_sup = _suppression(seeded, enforcer)
    first = _file_revoke(seeded, first_sup)
    second = _file_revoke(seeded, second_sup)
    for p in (first, second):
        attach_proof(seeded, p, PROOF, passed=True)

    apply_proposal(seeded, first, automated=True)
    with pytest.raises(AutomationRefused, match="daily cap"):
        apply_proposal(seeded, second, automated=True)
    assert second_sup.active

    # Applies older than a day no longer count against the cap.
    for entry in seeded.scalars(
        select(AuditEntry).where(AuditEntry.action == "operator.proposal.applied")
    ):
        entry.occurred_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
    seeded.flush()
    apply_proposal(seeded, second, automated=True)
    assert second.status == contract.APPLIED


def test_autonomy_demotes_when_the_class_rolls_back_too_often(seeded, enforcer):
    now = dt.datetime.now(dt.UTC)
    assert rollback_rate(seeded, kind="suppression.revoke") == 0.0
    assert effective_autonomy(seeded, "suppression.revoke", "L3") == "L3"
    for status in (contract.APPLIED, contract.VERIFIED, contract.ROLLED_BACK):
        seeded.add(
            ChangeProposal(
                kind="suppression.revoke",
                title="history",
                direction="tightens",
                status=status,
                applied_at=now,
                rolled_back_at=now if status == contract.ROLLED_BACK else None,
            )
        )
    seeded.flush()
    assert rollback_rate(seeded, kind="suppression.revoke") == pytest.approx(1 / 3)
    assert effective_autonomy(seeded, "suppression.revoke", "L3") == "L2"
    assert effective_autonomy(seeded, "suppression.revoke", "L1") == "L1"
    assert effective_autonomy(seeded, "other.kind", "L3") == "L3"

    # And the demotion is what the apply path actually uses.
    suppression = _suppression(seeded, enforcer)
    proposal = _file_revoke(seeded, suppression, autonomy_level="L3")
    attach_proof(seeded, proposal, PROOF, passed=True)
    with pytest.raises(AutomationRefused, match="effective autonomy L2"):
        apply_proposal(seeded, proposal, automated=True)


def test_automation_cannot_undo_a_tightening(seeded, enforcer):
    suppression = _suppression(seeded, enforcer)
    proposal = _file_revoke(seeded, suppression)
    attach_proof(seeded, proposal, PROOF, passed=True)
    apply_proposal(seeded, proposal, automated=True)
    with pytest.raises(AutomationRefused):
        rollback_proposal(seeded, proposal, reason="noisy", automated=True)
    # A failed automated verification is recorded but left for a person.
    verify_proposal(seeded, proposal, verified=False, note="precision dropped")
    assert proposal.status == contract.APPLIED
    assert "verification failed" in proposal.outcome_note
    assert not suppression.active


# --- two-person rule -----------------------------------------------------------


def test_org_level_loosening_needs_two_different_people(seeded):
    _policy(seeded)
    proposal = _file_min_score(seeded, 0.95, scope_level="org")
    attach_proof(seeded, proposal, PROOF, passed=True)

    decide(seeded, proposal, approve=True, actor="marcus@example.com", note="precision is poor")
    assert proposal.status == contract.PROVEN
    assert proposal.decided_by == "marcus@example.com"
    with pytest.raises(ProposalError, match="different person"):
        decide(seeded, proposal, approve=True, actor="Marcus@example.com", note="again")
    with pytest.raises(IllegalTransition):
        apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)

    decide(seeded, proposal, approve=True, actor="admin@example.com", note="agreed")
    assert proposal.status == contract.APPROVED
    assert proposal.second_approver == "admin@example.com"
    apply_proposal(seeded, proposal, actor="admin@example.com", automated=False)
    assert proposal.status == contract.APPLIED
    assert _live_min_score(seeded)[0] == 0.95


def test_a_tightening_or_team_loosening_needs_one_person(seeded):
    _policy(seeded)
    tighten = _file_min_score(seeded, 0.6, scope_level="org")
    loosen_team = _file_min_score(seeded, 0.9, scope_level="team")
    for p in (tighten, loosen_team):
        attach_proof(seeded, p, PROOF, passed=True)
        decide(seeded, p, approve=True, actor="marcus@example.com", note="ok")
        assert p.status == contract.APPROVED


# --- appliers, for real -------------------------------------------------------------


def test_suppression_revoke_applies_and_reverts(seeded, enforcer):
    suppression = _suppression(seeded, enforcer)
    original_expiry = suppression.expires_at
    proposal = _file_revoke(seeded, suppression)
    attach_proof(seeded, proposal, PROOF, passed=True)
    decide(seeded, proposal, approve=True, actor="marcus@example.com", note="unused")
    apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)
    assert not suppression.active
    assert suppression.revoked_at is not None

    rollback_proposal(
        seeded, proposal, reason="detector is noisy again", actor="marcus@example.com"
    )
    assert proposal.status == contract.ROLLED_BACK
    restored = [
        s for s in seeded.scalars(select(Suppression)) if s.id != suppression.id and s.active
    ]
    assert len(restored) == 1
    assert restored[0].agent_id == suppression.agent_id
    assert restored[0].detector_key == suppression.detector_key
    assert restored[0].entity_type == suppression.entity_type
    assert as_aware(restored[0].expires_at) == as_aware(original_expiry)
    assert "reverting change proposal" in restored[0].reason

    actions = [e.action for e in seeded.scalars(select(AuditEntry).order_by(AuditEntry.seq))]
    assert "operator.guardrail.unsuppressed" in actions
    assert actions.count("operator.guardrail.suppressed") == 2


def test_policy_min_score_creates_a_version_and_rollback_rebinds_the_prior(seeded):
    _policy(seeded)
    before_score, before_version = _live_min_score(seeded)
    proposal = _file_min_score(seeded, 0.6, scope_level="team")
    assert proposal.direction == contract.TIGHTENS
    attach_proof(seeded, proposal, PROOF, passed=True)
    decide(seeded, proposal, approve=True, actor="marcus@example.com", note="misses too much")
    apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)

    after_score, after_version = _live_min_score(seeded)
    assert after_score == 0.6
    assert after_version.version == before_version.version + 1
    assert before_version.compiled_json["rules"][0]["when"]["detection"]["min_score"] == 0.8

    rollback_proposal(seeded, proposal, reason="too many blocks", actor="marcus@example.com")
    score, version = _live_min_score(seeded)
    assert (score, version.id) == (before_score, before_version.id)
    # Rebinding, not re-saving: no third version was manufactured.
    assert seeded.query(PolicyVersion).filter_by(policy_id=before_version.policy_id).count() == 2


def test_policy_apply_refuses_a_drifted_rule(seeded):
    _policy(seeded)
    proposal = _file_min_score(seeded, 0.6, scope_level="team")
    attach_proof(seeded, proposal, PROOF, passed=True)
    decide(seeded, proposal, approve=True, actor="marcus@example.com", note="ok")
    save_policy(seeded, PolicyDocument.from_yaml(POLICY.replace("0.8", "0.7")), bind_mode="enforce")
    with pytest.raises(ProposalError, match="drifted"):
        apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)


def test_policy_change_can_be_staged_through_the_canary(seeded):
    _policy(seeded)
    _, stable = _live_min_score(seeded)
    proposal = _file_min_score(seeded, 0.6, scope_level="team", stage="canary")
    attach_proof(seeded, proposal, PROOF, passed=True)
    decide(seeded, proposal, approve=True, actor="marcus@example.com", note="canary it")
    apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)
    assert proposal.status == contract.CANARY

    canary = seeded.scalar(select(PolicyCanary))
    assert canary.status == "rolling"
    assert canary.stable_version_id == stable.id
    assert _live_min_score(seeded)[1].id == stable.id  # the binding stays on stable

    with pytest.raises(IllegalTransition, match="still in canary"):
        apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)

    rollback_proposal(seeded, proposal, reason="abandon", actor="marcus@example.com")
    assert canary.status == "rolled_back"
    assert proposal.status == contract.ROLLED_BACK


def test_a_completed_canary_settles_the_proposal_as_applied(seeded):
    from agentfox.platform.policy.canary import _rebind

    _policy(seeded)
    proposal = _file_min_score(seeded, 0.6, scope_level="team", stage="canary")
    attach_proof(seeded, proposal, PROOF, passed=True)
    decide(seeded, proposal, approve=True, actor="marcus@example.com", note="canary it")
    apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)
    canary = seeded.scalar(select(PolicyCanary))
    canary.status = "completed"
    _rebind(seeded, canary, canary.candidate_version_id)

    apply_proposal(seeded, proposal, actor="marcus@example.com", automated=False)
    assert proposal.status == contract.APPLIED
    assert _live_min_score(seeded)[0] == 0.6
    verify_proposal(
        seeded, proposal, verified=True, note="precision up", actor="marcus@example.com"
    )
    assert proposal.status == contract.VERIFIED


# --- attribution ---------------------------------------------------------------------


def test_every_step_is_on_the_chain_with_the_right_actor(seeded, enforcer):
    automation = AUTOMATION_ACTOR_TYPE
    improver = get_settings().improvement_actor_id

    suppression = _suppression(seeded, enforcer)
    auto = _file_revoke(seeded, suppression)
    attach_proof(seeded, auto, PROOF, passed=True)
    apply_proposal(seeded, auto, automated=True)
    verify_proposal(seeded, auto, verified=True, note="no regressions")
    trail = [(e.action, e.actor_type, e.actor_id) for e in _entries(seeded, auto)]
    assert trail == [
        ("proposal.filed", automation, improver),
        ("proposal.proof_attached", automation, improver),
        ("operator.proposal.decided", automation, improver),
        ("operator.proposal.applied", automation, improver),
        ("proposal.verified", automation, improver),
    ]
    applied = _entries(seeded, auto)[3].payload_json
    assert applied["automated"] is True
    assert applied["changed"]["revoked"] == suppression.id

    _policy(seeded)
    human = _file_min_score(seeded, 0.6, scope_level="team", proposed_by="priya@example.com")
    attach_proof(seeded, human, PROOF, passed=True, actor="priya@example.com")
    decide(seeded, human, approve=True, actor="marcus@example.com", note="ok")
    apply_proposal(seeded, human, actor="marcus@example.com", automated=False)
    rollback_proposal(seeded, human, reason="undo", actor="admin@example.com")
    trail = [(e.action, e.actor_type, e.actor_id) for e in _entries(seeded, human)]
    assert trail == [
        ("proposal.filed", "user", "priya@example.com"),
        ("proposal.proof_attached", "user", "priya@example.com"),
        ("operator.proposal.decided", "user", "marcus@example.com"),
        ("operator.proposal.applied", "user", "marcus@example.com"),
        ("operator.proposal.rolled_back", "user", "admin@example.com"),
    ]


def test_proposal_operations_are_registered_privileged_and_record():
    targets = {e.target: e.action for e in PRIVILEGED}
    assert (
        targets["agentfox.capabilities.improvement.proposals.decide"] == "operator.proposal.decided"
    )
    assert (
        targets["agentfox.capabilities.improvement.proposals.apply_proposal"]
        == "operator.proposal.applied"
    )
    assert (
        targets["agentfox.capabilities.improvement.proposals.rollback_proposal"]
        == "operator.proposal.rolled_back"
    )
    assert unaudited() == []


# --- API ----------------------------------------------------------------------------


def _api_proposal(to: float = 0.6, scope_level: str = "team") -> str:
    from agentfox.core.db import session_scope

    with session_scope() as s:
        if s.scalar(select(Policy).where(Policy.key == "proposal-test")) is None:
            _policy(s)
        proposal = _file_min_score(s, to, scope_level=scope_level)
        attach_proof(s, proposal, PROOF, passed=True)
        return proposal.id


def test_api_reads_are_open_to_operators_and_writes_need_policy_production(client):
    pid = _api_proposal()
    for reader in ("priya@example.com", "aisha@example.com", "dana@example.com"):
        listed = client.get("/api/proposals?status=proven", headers=as_user(reader))
        assert listed.status_code == 200
        assert [p["id"] for p in listed.json()["proposals"]] == [pid]
        assert client.get(f"/api/proposals/{pid}", headers=as_user(reader)).status_code == 200

    body = {"approve": True, "note": "ok"}
    for writer_denied in ("priya@example.com", "aisha@example.com", "dana@example.com"):
        headers = as_user(writer_denied)
        assert (
            client.post(f"/api/proposals/{pid}/decide", json=body, headers=headers).status_code
            == 403
        )
        assert client.post(f"/api/proposals/{pid}/apply", headers=headers).status_code == 403
        assert (
            client.post(
                f"/api/proposals/{pid}/rollback", json={"reason": "x"}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/proposals/{pid}/verify",
                json={"verified": True, "note": "x"},
                headers=headers,
            ).status_code
            == 403
        )

    assert (
        client.get("/api/proposals/chp_nope", headers=as_user("priya@example.com")).status_code
        == 404
    )
    assert (
        client.get("/api/proposals?kind=other", headers=as_user("priya@example.com")).json()[
            "proposals"
        ]
        == []
    )


def test_api_lifecycle_end_to_end(client):
    pid = _api_proposal()
    sec = as_user("marcus@example.com")

    early = client.post(f"/api/proposals/{pid}/apply", headers=sec)
    assert early.status_code == 409

    decided = client.post(
        f"/api/proposals/{pid}/decide", json={"approve": True, "note": "ok"}, headers=sec
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"

    applied = client.post(f"/api/proposals/{pid}/apply", headers=sec)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"

    rolled = client.post(
        f"/api/proposals/{pid}/rollback",
        json={"reason": "undo"},
        headers=as_user("admin@example.com"),
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["status"] == "rolled_back"
    assert (
        client.post(
            f"/api/proposals/{pid}/rollback", json={"reason": "again"}, headers=sec
        ).status_code
        == 409
    )

    from agentfox.core.db import session_scope

    with session_scope() as s:
        trail = [
            (e.action, e.actor_type, e.actor_id)
            for e in s.scalars(
                select(AuditEntry).where(AuditEntry.subject_id == pid).order_by(AuditEntry.seq)
            )
        ]
    assert ("operator.proposal.decided", "user", "marcus@example.com") in trail
    assert ("operator.proposal.rolled_back", "user", "admin@example.com") in trail


def test_api_org_loosening_same_person_twice_is_refused(client):
    pid = _api_proposal(to=0.95, scope_level="org")
    sec = as_user("marcus@example.com")
    body = {"approve": True, "note": "ok"}
    first = client.post(f"/api/proposals/{pid}/decide", json=body, headers=sec)
    assert first.status_code == 200
    assert first.json()["awaiting_second_approver"] is True
    again = client.post(f"/api/proposals/{pid}/decide", json=body, headers=sec)
    assert again.status_code == 400
    assert "different person" in again.json()["detail"]
    second = client.post(
        f"/api/proposals/{pid}/decide", json=body, headers=as_user("admin@example.com")
    )
    assert second.json()["status"] == "approved"


# --- CLI ----------------------------------------------------------------------------


def test_cli_proposals_group(client):
    """`client` only for its seeded database; the CLI shares it."""
    from typer.testing import CliRunner

    from agentfox.apps.cli.main import app

    runner = CliRunner()
    pid = _api_proposal(to=0.95, scope_level="org")

    listed = runner.invoke(app, ["policy", "proposals", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert pid in listed.output
    assert runner.invoke(app, ["policy", "proposals", "show", pid]).exit_code == 0

    first = runner.invoke(
        app,
        ["policy", "proposals", "approve", pid, "--actor", "marcus@example.com", "--note", "ok"],
    )
    assert first.exit_code == 0 and "awaiting a second approver" in first.output
    same = runner.invoke(
        app,
        ["policy", "proposals", "approve", pid, "--actor", "marcus@example.com", "--note", "ok"],
    )
    assert same.exit_code == 1 and "different person" in same.output
    auto = runner.invoke(app, ["policy", "proposals", "apply", pid, "--automated"])
    assert auto.exit_code == 1
    second = runner.invoke(
        app,
        ["policy", "proposals", "approve", pid, "--actor", "admin@example.com", "--note", "agreed"],
    )
    assert second.exit_code == 0 and "approved" in second.output
    applied = runner.invoke(
        app, ["policy", "proposals", "apply", pid, "--actor", "admin@example.com"]
    )
    assert applied.exit_code == 0, applied.output
    rolled = runner.invoke(
        app,
        [
            "policy",
            "proposals",
            "rollback",
            pid,
            "--actor",
            "admin@example.com",
            "--reason",
            "undo",
        ],
    )
    assert rolled.exit_code == 0 and "rolled_back" in rolled.output
    assert (
        runner.invoke(
            app,
            [
                "policy",
                "proposals",
                "reject",
                pid,
                "--actor",
                "admin@example.com",
                "--note",
                "late",
            ],
        ).exit_code
        == 1
    )
