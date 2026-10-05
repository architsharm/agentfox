"""Findings hygiene — one row per problem, a count per occurrence, and a lifecycle.

The improvement loop's sense stage reads the finding queue. A queue where a degraded
detector files a row per request, a drift view files one per page load and a resolved
problem that comes back files a brand-new row is measuring traffic, not problems —
and hides exactly the recurrence-after-a-fix signal the verify stage needs.
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from agentfox.prove import findings as findings_mod
from agentfox.core import webhooks
from agentfox.core.db import session_scope
from agentfox.prove.findings import (
    fingerprint,
    raise_finding,
    record_detector_health,
    resolve_finding,
)
from agentfox.core.models import Agent, AuditEntry, Budget, Finding

from .conftest import as_user
from .test_webhooks import configure, receiver  # noqa: F401 - the shared harness


@pytest.fixture(autouse=True)
def _fresh_recovery_checks(monkeypatch):
    monkeypatch.setattr(findings_mod, "RECOVERY_CHECK_INTERVAL_SECONDS", 0.0)
    findings_mod.reset_recovery_checks()
    yield
    findings_mod.reset_recovery_checks()


def _raise(session, **overrides):
    kwargs = dict(
        type="unit_problem",
        title="Something is wrong",
        severity="medium",
        subject_type="agent",
        subject_id="agent_1",
        evidence={"n": 1},
        control_keys=["NOM-RTG-01"],
        fingerprint_parts=("detector.a",),
    )
    kwargs.update(overrides)
    return raise_finding(session, **kwargs)


def _rows(session, type_: str) -> list[Finding]:
    return list(session.scalars(select(Finding).where(Finding.type == type_)))


# ---------------------------------------------------------------------------
# raise_finding / resolve_finding
# ---------------------------------------------------------------------------


def test_a_repeated_condition_is_one_finding_with_a_growing_count(session):
    first, created = _raise(session, evidence={"n": 1})
    assert created
    assert first.occurrences == 1 and first.fingerprint and first.last_seen_at

    for n in (2, 3):
        again, created = _raise(session, evidence={"n": n})
        assert not created
        assert again.id == first.id

    rows = _rows(session, "unit_problem")
    assert len(rows) == 1
    assert rows[0].occurrences == 3
    # Latest evidence on top, the first sighting kept.
    assert rows[0].evidence_json["n"] == 3
    assert rows[0].evidence_json["first_seen_evidence"] == {"n": 1}


def test_fingerprint_parts_and_subject_separate_problems(session):
    _raise(session)
    _raise(session, fingerprint_parts=("detector.b",))
    _raise(session, subject_id="agent_2")
    assert len(_rows(session, "unit_problem")) == 3


def test_the_fingerprint_is_stable_and_tenant_scoped():
    a = fingerprint("org_a", "drift", "agent", "x", ("scorer",))
    assert a == fingerprint("org_a", "drift", "agent", "x", ("scorer",))
    assert a != fingerprint("org_b", "drift", "agent", "x", ("scorer",))
    assert len(a) == 64


def test_severity_ratchets_up_never_down_while_open(session):
    finding, _ = _raise(session, severity="high")
    _raise(session, severity="low")
    assert finding.severity == "high"
    _raise(session, severity="critical")
    assert finding.severity == "critical"


def test_a_resolved_finding_that_recurs_reopens_with_its_history(session):
    finding, _ = _raise(session)
    resolve_finding(session, finding, actor="sec@example.com", note="patched the detector")
    assert finding.status == "resolved"

    again, created = _raise(session, evidence={"n": 2})
    assert not created, "a recurrence is the same problem, not a new row"
    assert again.id == finding.id
    assert again.status == "open"
    assert again.occurrences == 2
    assert again.resolved_at is None and again.resolution_note is None
    history = again.evidence_json["recurrences"]
    assert history[-1]["resolved_by"] == "sec@example.com"
    assert history[-1]["resolution_note"] == "patched the detector"
    assert len(_rows(session, "unit_problem")) == 1

    actions = [e.action for e in session.scalars(select(AuditEntry).order_by(AuditEntry.seq))]
    assert "finding.resolved" in actions
    assert "finding.recurred" in actions

    # History survives further occurrences while open.
    _raise(session, evidence={"n": 3})
    assert again.evidence_json["recurrences"] == history


def test_a_suppressed_finding_counts_but_stays_suppressed(session):
    finding, _ = _raise(session)
    finding.status = "suppressed"
    session.flush()
    again, created = _raise(session)
    assert not created and again.id == finding.id
    assert again.status == "suppressed"
    assert again.occurrences == 2


def test_once_findings_are_not_recounted_by_a_rescan(session):
    finding, _ = _raise(session, once=True)
    resolve_finding(session, finding, actor="a@example.com", note="followed up")
    again, created = _raise(session, once=True)
    assert not created
    assert again.status == "resolved", "re-detecting a past event is not a recurrence"
    assert again.occurrences == 1


def test_resolution_is_audited_and_marks_automation(session):
    finding, _ = _raise(session)
    resolve_finding(session, finding, actor="agentfox.test", note="cleared", automated=True)
    entry = session.scalar(select(AuditEntry).where(AuditEntry.action == "finding.resolved"))
    assert entry.actor_type == "automation"
    assert entry.payload_json["automated"] is True
    with pytest.raises(ValueError):
        resolve_finding(session, _raise(session, subject_id="z")[0], actor="x", note=" ")


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------


def _pipeline(**statuses):
    results = [SimpleNamespace(detector_key=k, status=v) for k, v in statuses.items()]
    return SimpleNamespace(
        results=results,
        degraded=[k for k, v in statuses.items() if v in ("timeout", "skipped_budget")],
        summary=lambda: {"statuses": statuses},
    )


def test_a_degraded_detector_is_one_finding_and_closes_on_recovery(session):
    for _ in range(3):
        record_detector_health(
            session,
            subject_id="agent_1",
            surface="input",
            pipeline_result=_pipeline(**{"pii.native": "timeout", "secrets.native": "ok"}),
        )
    rows = _rows(session, "budget_breach")
    assert len(rows) == 1, "a degraded detector used to file a finding per request"
    assert rows[0].occurrences == 3
    assert rows[0].evidence_json["detector_key"] == "pii.native"

    record_detector_health(
        session,
        subject_id="agent_1",
        surface="input",
        pipeline_result=_pipeline(**{"pii.native": "ok"}),
    )
    assert rows[0].status == "resolved"
    assert "completed normally" in rows[0].resolution_note

    record_detector_health(
        session,
        subject_id="agent_1",
        surface="input",
        pipeline_result=_pipeline(**{"pii.native": "skipped_budget"}),
    )
    assert rows[0].status == "open" and len(_rows(session, "budget_breach")) == 1


def test_recovery_checks_are_throttled_on_the_request_path(session, monkeypatch):
    monkeypatch.setattr(findings_mod, "RECOVERY_CHECK_INTERVAL_SECONDS", 3600.0)
    record_detector_health(
        session,
        subject_id="agent_1",
        surface="input",
        pipeline_result=_pipeline(**{"secrets.native": "ok"}),
    )
    record_detector_health(
        session,
        subject_id="agent_1",
        surface="input",
        pipeline_result=_pipeline(**{"pii.native": "timeout"}),
    )
    record_detector_health(
        session,
        subject_id="agent_1",
        surface="input",
        pipeline_result=_pipeline(**{"pii.native": "ok"}),
    )
    assert _rows(session, "budget_breach")[0].status == "open"


def test_budget_exhaustion_counts_then_closes_when_the_window_rolls(seeded, enforcer):
    from agentfox.runtime.reliability import check_budget

    agent = seeded.scalar(select(Agent).where(Agent.slug == "support-triage"))
    budget = seeded.scalar(select(Budget).where(Budget.scope_id == agent.id))
    budget.max_calls = 0
    seeded.flush()

    for _ in range(2):
        enforcer.run_completion(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "hi"}],
            model="echo-1",
        )
    rows = _rows(seeded, "budget_exhausted")
    assert len(rows) == 1 and rows[0].occurrences == 2

    budget.window_started_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    budget.max_calls = 1000
    seeded.flush()
    assert not check_budget(seeded, "agent", agent.id).exceeded
    assert rows[0].status == "resolved"
    assert "rolled" in rows[0].resolution_note

    # The next breach is visible again, as a recurrence — it used to hide behind the
    # never-closed finding from an earlier window.
    budget.max_calls = 0
    seeded.flush()
    enforcer.run_completion(
        agent_slug="support-triage", messages=[{"role": "user", "content": "hi"}], model="echo-1"
    )
    assert rows[0].status == "open"
    assert rows[0].evidence_json["recurrences"]


def test_drift_is_one_finding_per_scorer_and_closes_when_the_window_is_clean(session, monkeypatch):
    from agentfox.evaluation import drift

    series = {"current": [0.9, 0.92, 0.95, 0.91], "baseline": [0.1, 0.12, 0.15, 0.11]}
    calls = {"n": 0}

    def fake_scores(_session, _agent, _scorer, _start, _end):
        calls["n"] += 1
        return series["current"] if calls["n"] % 2 else series["baseline"]

    monkeypatch.setattr(drift, "_scores", fake_scores)
    for _ in range(3):
        assert drift.compute(session, "support-triage", "faithfulness", threshold=0.2).drifted
    rows = _rows(session, "drift")
    assert len(rows) == 1 and rows[0].occurrences == 3

    series["current"] = series["baseline"]
    assert not drift.compute(session, "support-triage", "faithfulness", threshold=0.2).drifted
    assert rows[0].status == "resolved"


def test_a_false_resolution_rescan_does_not_refile(seeded):
    from agentfox.containment.escalation import detect_false_resolution, record_turn

    agent = seeded.scalar(select(Agent).where(Agent.slug == "support-triage"))
    record_turn(
        seeded,
        session_id="fr-1",
        agent_id=agent.id,
        user_text="my card was declined",
        agent_text="I've resolved that for you.",
    )
    record_turn(
        seeded,
        session_id="fr-1",
        agent_id=agent.id,
        user_text="it's still declined",
        agent_text="Let me check again.",
    )
    for _ in range(3):
        detect_false_resolution(seeded)
    rows = _rows(seeded, "false_resolution")
    assert len(rows) == 1
    assert rows[0].occurrences == 1


def test_a_repeatedly_stopped_loop_is_one_finding_per_session(seeded):
    from agentfox.gateway.routes.inline import _record_loop_stop

    verdict = SimpleNamespace(decision="stop", reason="same call repeated", step=4, evidence={})
    steps = [SimpleNamespace(tool="search")] * 4
    for _ in range(3):
        _record_loop_stop(
            seeded, agent_slug="support-triage", session_id="s-1", verdict=verdict, steps=steps
        )
    _record_loop_stop(
        seeded, agent_slug="support-triage", session_id="s-2", verdict=verdict, steps=steps
    )
    rows = sorted(_rows(seeded, "agent_loop_stopped"), key=lambda f: f.occurrences)
    assert [f.occurrences for f in rows] == [1, 3]


def test_a_rerun_red_team_campaign_counts_then_closes_once_retested_clean(seeded, monkeypatch):
    from agentfox.evaluation import redteam

    attacks = [p.key for p in redteam.BUILTIN_PROBES if p.expect_blocked]
    gap = set(attacks[:2])
    escaping = set(gap)

    def fake_run(self, session, agent_slug, probes):
        return [
            redteam.ProbeOutcome(
                probe=p,
                blocked=p.expect_blocked and p.key not in escaping,
                verdict="allow" if p.key in escaping else "block",
            )
            for p in probes
        ]

    monkeypatch.setattr(redteam.NativeRedTeamRunner, "run_probes", fake_run)
    for _ in range(3):
        redteam.run_campaign(seeded, "support-triage")
    rows = _rows(seeded, "redteam")
    assert len(rows) == 1, "every re-run used to file the same gap again"
    assert rows[0].occurrences == 3
    assert sorted(rows[0].evidence_json["probe_keys"]) == sorted(gap)

    escaping.clear()  # the gap is fixed from here on
    # A campaign that re-ran only other probes has not re-tested this gap.
    redteam.run_campaign(seeded, "support-triage", probes=attacks[2:3])
    assert rows[0].status == "open"

    # Re-running every probe in it with none reproducing closes it, automatically.
    redteam.run_campaign(seeded, "support-triage", probes=sorted(gap))
    assert rows[0].status == "resolved"
    assert "none reproduced" in rows[0].resolution_note


def test_resuming_an_agent_closes_its_stop_finding_and_a_new_stop_reopens_it(seeded):
    from agentfox.registry.control import quarantine, resume

    quarantine(seeded, "support-triage", reason="odd tool use", actor="marcus@example.com")
    finding = _rows(seeded, "agent_stopped")[0]
    resume(seeded, "support-triage", reason="root cause fixed", actor="marcus@example.com")
    assert finding.status == "resolved"
    assert finding.resolved_by == "marcus@example.com"

    quarantine(seeded, "support-triage", reason="again", actor="marcus@example.com")
    assert finding.status == "open"
    assert len(_rows(seeded, "agent_stopped")) == 1
    assert finding.occurrences == 2


# ---------------------------------------------------------------------------
# PATCH /api/findings/{id} and lifecycle webhooks
# ---------------------------------------------------------------------------


def _committed_finding(severity: str = "high") -> str:
    with session_scope() as s:
        finding, _ = raise_finding(
            s,
            type="unit_problem",
            title="Needs a human",
            severity=severity,
            subject_type="agent",
            subject_id="agent_1",
            evidence={"k": "v"},
            control_keys=["NOM-RTG-01"],
        )
        return finding.id


def test_an_unknown_status_is_refused(client):
    finding_id = _committed_finding()
    response = client.patch(
        f"/api/findings/{finding_id}",
        json={"status": "wontfix", "note": "meh"},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 400
    assert "open, suppressed, resolved" in response.json()["detail"]
    detail = client.get(f"/api/findings/{finding_id}", headers=as_user("admin@example.com"))
    assert detail.json()["status"] == "open"
    assert detail.json()["occurrences"] == 1


def _bodies(receiver):  # noqa: F811 - fixture name reused as parameter
    return [json.loads(r["raw"]) for r in receiver.received]


def test_resolving_and_suppressing_emit_signed_webhook_events(
    monkeypatch,
    receiver,  # noqa: F811 - the fixture shadows the import above, deliberately
    client,
):
    configure(monkeypatch, receiver.url)
    resolved_id = _committed_finding()
    suppressed_id = _committed_finding(severity="critical")
    assert webhooks.wait_for_delivery(5)
    receiver.received.clear()

    ok = client.patch(
        f"/api/findings/{resolved_id}",
        json={"status": "resolved", "note": "rotated the key"},
        headers=as_user("marcus@example.com"),
    )
    assert ok.status_code == 200, ok.text
    ok = client.patch(
        f"/api/findings/{suppressed_id}",
        json={"status": "suppressed", "suppression_reason": "accepted risk"},
        headers=as_user("marcus@example.com"),
    )
    assert ok.status_code == 200, ok.text
    assert webhooks.wait_for_delivery(5)

    events = {b["event"]: b for b in _bodies(receiver)}
    assert set(events) == {"finding.resolved", "finding.suppressed"}
    assert events["finding.resolved"]["finding"]["id"] == resolved_id
    assert events["finding.resolved"]["finding"]["resolved_by"] == "marcus@example.com"
    assert events["finding.resolved"]["finding"]["resolution_note"] == "rotated the key"
    assert events["finding.suppressed"]["finding"]["suppression_reason"] == "accepted risk"
    for request in receiver.received:
        headers = {k.lower(): v for k, v in request["headers"].items()}
        assert headers["x-nometria-signature"].startswith("sha256=")


def test_automated_resolution_and_recurrence_emit_events(monkeypatch, receiver):  # noqa: F811
    configure(monkeypatch, receiver.url)
    finding_id = _committed_finding()
    with session_scope() as s:
        finding = s.get(Finding, finding_id)
        resolve_finding(s, finding, actor="agentfox.test", note="cleared", automated=True)
    with session_scope() as s:
        _raise(
            s,
            type="unit_problem",
            title="Needs a human",
            severity="high",
            subject_id="agent_1",
            fingerprint_parts=None,
        )
    assert webhooks.wait_for_delivery(5)
    assert [b["event"] for b in _bodies(receiver)] == [
        "finding.created",
        "finding.resolved",
        "finding.reopened",
    ]


def test_status_events_stay_behind_egress_gating(monkeypatch, receiver, client):  # noqa: F811
    configure(monkeypatch, receiver.url, egress=False)
    finding_id = _committed_finding()
    client.patch(
        f"/api/findings/{finding_id}",
        json={"status": "resolved", "note": "fixed"},
        headers=as_user("marcus@example.com"),
    )
    assert webhooks.wait_for_delivery(5)
    assert receiver.received == []


def test_a_status_rolled_back_is_not_announced(monkeypatch, receiver):  # noqa: F811
    configure(monkeypatch, receiver.url)
    finding_id = _committed_finding()
    assert webhooks.wait_for_delivery(5)
    receiver.received.clear()
    with pytest.raises(RuntimeError), session_scope() as s:
        finding = s.get(Finding, finding_id)
        finding.status = "resolved"
        s.flush()
        raise RuntimeError("abort")
    assert webhooks.wait_for_delivery(5)
    assert receiver.received == []
