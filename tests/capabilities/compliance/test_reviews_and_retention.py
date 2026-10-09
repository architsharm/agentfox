"""Control attestations, retention policy and the retention purge.

* A review is an outcome, a note, the evidence it was made on, an expiry, and an
  audit-chain entry, made only by roles that answer for compliance.
* Changing retention is an audited, role-gated operator action.
* The purge deletes or redacts only what is past its class's period, keeps what a
  legal hold covers, and never removes an audit entry.
* The kill switch is a control, evidenced by its own use.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select

from agentfox.capabilities.compliance import reviews, sync_catalog
from agentfox.capabilities.compliance.retention import (
    RetentionError,
    overview,
    purge,
    set_policy,
)
from agentfox.capabilities.compliance.status import evaluate_control
from agentfox.core.models import (
    Agent,
    AuditEntry,
    Control,
    ControlReview,
    Decision,
    DetectionFinding,
    DetectorRun,
    FrameworkMapping,
    LegalHold,
    RetentionRun,
    Span,
    Trace,
    utcnow,
)
from agentfox.platform.ledger import chain
from tests.conftest import as_user

DANA = as_user("dana@example.com")  # compliance
AISHA = as_user("aisha@example.com")  # auditor
PRIYA = as_user("priya@example.com")  # developer
MARCUS = as_user("marcus@example.com")  # security


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


def test_a_review_records_outcome_evidence_expiry_and_an_audit_entry(client):
    r = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "eu-ai-act", "outcome": "meets"},
        headers=DANA,
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["reviewer"] == "dana@example.com"
    assert review["state"] == "current"
    reviewed = dt.datetime.fromisoformat(review["reviewed_at"])
    expires = dt.datetime.fromisoformat(review["expires_at"])
    assert (expires - reviewed).days == reviews.REVIEW_VALID_DAYS

    detail = client.get("/api/controls/NOM-AUD-02", headers=DANA).json()
    eu = next(f for f in detail["frameworks"] if f["framework"] == "eu-ai-act")
    assert eu["review"]["outcome"] == "meets"
    assert eu["review"]["reviewer"] == "dana@example.com"
    assert detail["history"][0]["id"] == review["id"]
    assert "status" in detail["evidence"] and "rules" in detail["evidence"]

    entries = client.get(
        "/api/audit/entries", params={"action": "compliance.control_reviewed"}, headers=DANA
    ).json()["entries"]
    assert entries and entries[0]["seq"] == review["audit_seq"]

    # The review confirms the mapping it was made against, so the package's DRAFT
    # chip comes off those rows.
    framework = client.get("/api/frameworks/eu-ai-act", headers=DANA).json()
    row = next(c for c in framework["controls"] if c["key"] == "NOM-AUD-02")
    assert row["review_status"] == "reviewed"
    assert row["review"]["state"] == "current"
    assert framework["attestations"]["current"] >= 1


def test_anything_short_of_meets_needs_a_note(client):
    for outcome in ("partially_meets", "does_not_meet", "not_applicable"):
        r = client.post(
            "/api/controls/NOM-AUD-02/reviews",
            json={"framework": "eu-ai-act", "outcome": outcome},
            headers=DANA,
        )
        assert r.status_code == 400, outcome
    r = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "eu-ai-act", "outcome": "partially_meets", "note": "no checkpoints"},
        headers=DANA,
    )
    assert r.status_code == 201
    assert r.json()["note"] == "no checkpoints"


def test_a_review_must_name_a_known_outcome_and_a_mapped_framework(client):
    bad_outcome = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "eu-ai-act", "outcome": "looks fine"},
        headers=DANA,
    )
    assert bad_outcome.status_code == 400
    unmapped = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "mitre-atlas", "outcome": "meets"},
        headers=DANA,
    )
    assert unmapped.status_code == 400
    unknown = client.post(
        "/api/controls/NOM-NOPE-01/reviews",
        json={"framework": "eu-ai-act", "outcome": "meets"},
        headers=DANA,
    )
    assert unknown.status_code == 400


def test_only_compliance_owners_and_auditors_may_attest(client):
    body = {"framework": "eu-ai-act", "outcome": "meets"}
    for headers in (PRIYA, MARCUS):
        r = client.post("/api/controls/NOM-AUD-02/reviews", json=body, headers=headers)
        assert r.status_code == 403
    assert (
        client.post("/api/controls/NOM-AUD-02/reviews", json=body, headers=AISHA).status_code == 201
    )


def test_a_review_expires_and_a_new_one_supersedes_it(seeded):
    sync_catalog(seeded)
    long_ago = utcnow() - dt.timedelta(days=reviews.REVIEW_VALID_DAYS + 5)
    old = reviews.record_review(
        seeded, "NOM-AUD-02", "soc2", "meets", reviewer="dana@example.com", now=long_ago
    )
    assert reviews.review_state(old) == "expired"
    latest = reviews.latest_reviews(seeded, "soc2")[("NOM-AUD-02", "soc2")]
    assert latest.id == old.id

    from agentfox.capabilities.compliance.catalog import framework_coverage

    assert framework_coverage(seeded, "soc2")["attestations"]["expired"] >= 1

    new = reviews.record_review(
        seeded,
        "NOM-AUD-02",
        "soc2",
        "does_not_meet",
        reviewer="aisha@example.com",
        note="checkpoint key rotated without re-signing",
    )
    latest = reviews.latest_reviews(seeded, "soc2")[("NOM-AUD-02", "soc2")]
    assert latest.id == new.id and reviews.review_state(latest) == "current"
    # Both attestations are kept: history is the point.
    assert len(reviews.review_history(seeded, "NOM-AUD-02")) == 2
    assert seeded.scalar(select(func.count()).select_from(ControlReview)) == 2


def test_the_one_click_mapping_route_is_gone(client):
    r = client.post(
        "/api/frameworks/review",
        json={"control_key": "NOM-AUD-02", "framework": "eu-ai-act"},
        headers=DANA,
    )
    assert r.status_code in (404, 405)


def test_a_framework_lists_requirements_with_their_controls(client):
    detail = client.get("/api/frameworks/eu-ai-act", headers=DANA).json()
    requirements = detail["requirements_detail"]
    assert requirements
    art14 = [r for r in requirements if r["reference"].startswith("Art. 14")]
    assert art14 and any(c["key"] == "NOM-RTG-14" for c in art14[0]["controls"])
    assert client.get("/api/frameworks/not-a-framework", headers=DANA).status_code == 404


# ---------------------------------------------------------------------------
# Retention policy
# ---------------------------------------------------------------------------


def test_changing_retention_is_audited_with_before_and_after(client):
    r = client.put(
        "/api/retention/traces",
        json={"retain_days": 30, "reason": "data minimisation review"},
        headers=DANA,
    )
    assert r.status_code == 200, r.text
    assert r.json()["retain_days"] == 30

    entry = client.get(
        "/api/audit/entries", params={"action": "operator.retention.changed"}, headers=DANA
    ).json()["entries"][0]
    payload = entry["payload"]
    assert payload["after"]["retain_days"] == 30
    assert payload["reason"] == "data minimisation review"
    assert entry["actor_id"] == "dana@example.com"

    again = client.put(
        "/api/retention/traces",
        json={"retain_days": 60, "reason": "legal asked for longer"},
        headers=DANA,
    )
    assert again.status_code == 200
    entry = client.get(
        "/api/audit/entries", params={"action": "operator.retention.changed"}, headers=DANA
    ).json()["entries"][0]
    assert entry["payload"]["before"]["retain_days"] == 30
    assert entry["payload"]["after"]["retain_days"] == 60

    classes = {
        c["data_class"]: c for c in client.get("/api/retention", headers=DANA).json()["classes"]
    }
    assert classes["traces"]["retain_days"] == 60


def test_retention_changes_are_role_gated_and_need_a_reason(client):
    body = {"retain_days": 30, "reason": "x"}
    for headers in (PRIYA, MARCUS, AISHA):
        assert client.put("/api/retention/traces", json=body, headers=headers).status_code == 403
    blank = client.put(
        "/api/retention/traces", json={"retain_days": 30, "reason": " "}, headers=DANA
    )
    assert blank.status_code == 400
    out_of_range = client.put(
        "/api/retention/traces", json={"retain_days": 0, "reason": "x"}, headers=DANA
    )
    assert out_of_range.status_code == 400
    audit = client.put(
        "/api/retention/audit", json={"retain_days": 30, "reason": "x"}, headers=DANA
    )
    assert audit.status_code == 400
    assert client.post("/api/retention/purge", headers=AISHA).status_code == 403


def test_the_audit_class_cannot_be_given_a_policy(session):
    with pytest.raises(RetentionError):
        set_policy(session, "audit", 30, actor="a@example.com", reason="nope")


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------


def _world(session):
    """Two agents, each with one old and one fresh run, decision and detector run."""
    now = utcnow()
    old = now - dt.timedelta(days=400)
    fresh = now - dt.timedelta(days=2)
    agents = {}
    for slug in ("held-bot", "free-bot"):
        agent = Agent(slug=slug, name=slug)
        session.add(agent)
        session.flush()
        agents[slug] = agent
        for label, when in (("old", old), ("fresh", fresh)):
            trace = Trace(
                id=f"tr_{slug}_{label}",
                agent_id=agent.id,
                agent_slug=slug,
                started_at=when,
                summary="what is my balance",
            )
            session.add(trace)
            session.add(
                Span(
                    id=f"sp_{slug}_{label}",
                    trace_id=trace.id,
                    started_at=when,
                    attributes_json={"agentfox.output": "your balance is 12", "gen_ai.x": 1},
                )
            )
            session.add(
                Decision(
                    id=f"dec_{slug}_{label}",
                    trace_id=trace.id,
                    agent_id=agent.id,
                    created_at=when,
                )
            )
            run = DetectorRun(
                id=f"dr_{slug}_{label}", trace_id=trace.id, detector_key="pii", created_at=when
            )
            session.add(run)
            session.add(
                DetectionFinding(
                    detector_run_id=run.id,
                    trace_id=trace.id,
                    entity_type="EMAIL",
                    sample="jane@example.com",
                    created_at=when,
                )
            )
    # Old audit entries: the purge must leave every one of them.
    for i in range(3):
        chain.append(session, "test.old", payload={"i": i}, occurred_at=old)
    session.flush()
    return agents


def _policies(session, days=365):
    for key in ("traces", "decisions", "prompt_content", "detection_sample"):
        set_policy(session, key, days, actor="dana@example.com", reason="test")


def test_the_purge_removes_only_rows_past_their_period_and_never_audit_entries(session):
    _world(session)
    _policies(session)
    audit_before = session.scalar(select(func.count()).select_from(AuditEntry))

    run = purge(session, trigger="manual", requested_by="dana@example.com")

    assert run.status == "done"
    assert session.get(Trace, "tr_free-bot_old") is None
    assert session.get(Span, "sp_free-bot_old") is None
    assert session.get(Decision, "dec_free-bot_old") is None
    assert session.get(DetectorRun, "dr_free-bot_old") is None
    # Fresh rows are untouched, content included.
    fresh = session.get(Span, "sp_free-bot_fresh")
    assert fresh.attributes_json["agentfox.output"] == "your balance is 12"
    assert session.get(Trace, "tr_free-bot_fresh").summary == "what is my balance"
    assert session.get(Decision, "dec_free-bot_fresh") is not None

    # Nothing removed from the chain: it grew by exactly the purge's own entry, and
    # still verifies end to end.
    audit_after = session.scalar(select(func.count()).select_from(AuditEntry))
    assert audit_after == audit_before + 1
    assert chain.verify_range(session).valid
    entry = session.scalar(select(AuditEntry).where(AuditEntry.action == "retention.purged"))
    assert entry.subject_id == run.id
    assert entry.payload_json["deleted"] > 0
    assert run.results_json["audit"] == {"skipped": "locked"}
    assert run.results_json["traces"]["runs_deleted"] == 2  # both agents' old runs


def test_content_is_redacted_before_the_run_is_deleted(session):
    _world(session)
    set_policy(session, "prompt_content", 30, actor="dana@example.com", reason="minimise")
    set_policy(session, "detection_sample", 30, actor="dana@example.com", reason="minimise")
    set_policy(session, "traces", 3650, actor="dana@example.com", reason="keep runs")

    run = purge(session)

    span = session.get(Span, "sp_free-bot_old")
    assert "agentfox.output" not in span.attributes_json
    assert span.attributes_json["gen_ai.x"] == 1  # non-content attributes stay
    assert session.get(Trace, "tr_free-bot_old").summary is None
    sample = session.scalar(
        select(DetectionFinding).where(DetectionFinding.trace_id == "tr_free-bot_old")
    )
    assert sample.sample == ""
    assert session.get(Span, "sp_free-bot_fresh").attributes_json["agentfox.output"]
    assert run.results_json["prompt_content"]["spans_redacted"] == 2
    # A second pass finds nothing left to redact.
    assert purge(session).results_json["prompt_content"]["spans_redacted"] == 0


def test_an_agent_scoped_legal_hold_keeps_that_agents_rows(session):
    _world(session)
    _policies(session)
    session.add(LegalHold(scope_json={"agents": ["held-bot"]}, reason="litigation"))
    session.flush()

    purge(session)

    assert session.get(Trace, "tr_held-bot_old") is not None
    assert session.get(Span, "sp_held-bot_old").attributes_json["agentfox.output"]
    assert session.get(Decision, "dec_held-bot_old") is not None
    assert session.get(DetectorRun, "dr_held-bot_old") is not None
    assert session.get(Trace, "tr_free-bot_old") is None


def test_an_unscoped_legal_hold_stops_the_purge(session):
    _world(session)
    _policies(session)
    session.add(LegalHold(scope_json={}, reason="regulator inquiry"))
    session.flush()

    run = purge(session)

    assert session.get(Trace, "tr_free-bot_old") is not None
    assert all(
        r.get("skipped") in ("legal hold", "locked", "no policy") for r in run.results_json.values()
    )


def test_a_class_with_no_policy_is_kept(session):
    _world(session)
    run = purge(session)
    assert session.get(Trace, "tr_free-bot_old") is not None
    assert run.results_json["traces"] == {"skipped": "no policy"}


def test_purge_now_runs_the_job_and_shows_last_and_next_run(client):
    from agentfox.core.db import session_scope
    from agentfox.platform.jobs.scheduler import ensure_default_schedules

    with session_scope() as s:
        ensure_default_schedules(s)

    r = client.post("/api/retention/purge", headers=DANA)
    assert r.status_code == 200, r.text
    assert r.json()["run"]["trigger"] == "manual"

    view = client.get("/api/retention", headers=DANA).json()
    assert view["last_run"]["id"] == r.json()["retention_run_id"]
    assert view["last_run"]["requested_by"] == "dana@example.com"
    assert view["next_run"]
    assert {c["data_class"] for c in view["classes"]} >= {
        "prompt_content",
        "traces",
        "decisions",
        "audit",
    }
    runs = client.get("/api/retention/runs", headers=DANA).json()["runs"]
    assert runs and runs[0]["id"] == view["last_run"]["id"]

    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(RetentionRun)) == 1


def test_the_purge_is_a_default_schedule(session):
    from agentfox.platform.jobs.scheduler import ensure_default_schedules

    kinds = {s.kind for s in ensure_default_schedules(session)}
    assert "retention.purge" in kinds
    assert overview(session)["next_run"]


# ---------------------------------------------------------------------------
# Kill switch control
# ---------------------------------------------------------------------------


def test_the_kill_switch_is_a_catalogued_control(session):
    sync_catalog(session)
    control = session.scalar(select(Control).where(Control.key == "NOM-RTG-14"))
    assert control is not None and control.status_rule_json["kind"] == "kill_switch"
    assert session.scalar(
        select(FrameworkMapping).where(
            FrameworkMapping.control_key == "NOM-RTG-14", FrameworkMapping.framework == "eu-ai-act"
        )
    )


def test_the_kill_switch_control_is_evidenced_by_its_use(seeded):
    from agentfox.platform.registry.control import kill

    sync_catalog(seeded)
    control = seeded.scalar(select(Control).where(Control.key == "NOM-RTG-14"))
    assert evaluate_control(seeded, control).status == "not_implemented"

    agent = seeded.scalar(select(Agent).where(Agent.status == "active"))
    kill(seeded, agent.slug, reason="drill", actor="marcus@example.com")
    held = evaluate_control(seeded, control)
    assert held.status == "effective", held.rationale

    # An allowed call after the stop means the switch leaked.
    seeded.add(
        Decision(
            agent_id=agent.id,
            verdict="allow",
            created_at=utcnow() + dt.timedelta(seconds=5),
        )
    )
    seeded.flush()
    leaked = evaluate_control(seeded, control)
    assert leaked.status == "failing"


def test_a_control_added_by_an_upgrade_reaches_a_workspace_with_the_old_catalog(client, seeded):
    """The catalog was only loaded into an empty workspace, so a control a new build
    adds was 'No such control' wherever an older catalog was already stored."""
    from agentfox.core.models import Control, FrameworkMapping

    seeded.query(FrameworkMapping).filter_by(control_key="NOM-RTG-14").delete()
    seeded.query(Control).filter_by(key="NOM-RTG-14").delete()
    seeded.commit()
    assert client.get("/api/controls/NOM-RTG-14").status_code == 200
    keys = {c["key"] for c in client.get("/api/controls").json()["controls"]}
    assert "NOM-RTG-14" in keys
