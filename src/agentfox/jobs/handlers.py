"""Handlers for the deferrable job kinds that had a name but nothing behind them.

`jobs.DEFERRABLE` has listed `eval.run` and `compliance.recompute` for a long time, but
only `evidence.package` and `redteam.sweep` were ever registered, so enqueueing either of
the others raised `KeyError`. This module registers real handlers for them, plus the
kinds the scheduler (`agentfox.jobs.scheduler`) fills the queue with:

=====================  ===========================================================
kind                   what it does
=====================  ===========================================================
``eval.run``           Runs one eval suite (``suite``, ``target``, ``scorers``,
                       ``baseline_run_id``, ``runner``) through the same runner the
                       ``POST /api/eval/runs`` route uses.
``compliance.recompute``  Recomputes every control's status (``window_days``), the
                       same ``compute_all`` behind ``POST /api/controls/compute``.
``canary.advance``     Puts every rolling policy canary in the tenant through the
                       two-way health gate (``policy.canary.canary_rollout``):
                       advance after dwell, hold, or roll back a candidate that
                       blocks more *or less* than stable.
``drift.check``        Computes and **persists** score drift (``scorer``) for every
                       agent with enough online samples. This is where drift
                       windows and drift findings are written now that
                       ``GET /api/eval/drift`` is read-only.
``escalation.scan``    The missed-escalation second pass (``since_hours``): findings
                       for every agent, retroactive hand-offs where the escalation
                       policy's mode is ``enforce``, and SLA breaches marked.
``redteam.posture``    Runs an adaptive red-team campaign against every active agent
                       (``budget``, ``seed``). Expensive and finding-producing, so its
                       default schedule is created disabled.
``monitors.run``       Runs every due monitor of connected sources (GitHub repos,
                       hosted-API specs, MCP servers), or one (``monitor_id``,
                       ``ref``, ``trigger``) — see ``agentfox.monitoring``.
``probes.run``         Sends the live probe library to every *opted-in* probe target
                       in the tenant that is due (``evaluation.live_probes``), records
                       a campaign per target and opens/closes ``live_probe_escape``
                       findings. A no-op in a tenant with no opted-in target.
=====================  ===========================================================

Handlers take a session already bound to the job's tenant (see
`jobs_db.run_pending`) and return a JSON-serialisable result dict.

Every change a handler makes is attributed on the audit chain. Work a person requested
carries that person (`payload["requested_by"]`); work a schedule enqueued carries
`contract.AUTOMATION_ACTOR_TYPE` and `settings.improvement_actor_id`, so an automated
change is never recorded as a human decision.

Imported by `gateway/routes/jobs.py`, so registration happens wherever the jobs router
(and therefore the cron endpoint that drains these kinds) is loaded.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import Agent, EvalSuite, Policy, PolicyCanary, utcnow
from agentfox.improvement.contract import AUTOMATION_ACTOR_TYPE
from agentfox.jobs import store as jobs_db
from agentfox.prove.audit import chain


def _actor(payload: dict[str, Any]) -> tuple[str, str]:
    """(actor_type, actor_id) for the audit chain."""
    if payload.get("actor_type") == AUTOMATION_ACTOR_TYPE or not payload.get("requested_by"):
        return AUTOMATION_ACTOR_TYPE, get_settings().improvement_actor_id
    return str(payload.get("actor_type") or "user"), str(payload["requested_by"])


# ---------------------------------------------------------------------------
# eval.run
# ---------------------------------------------------------------------------


def run_eval(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from agentfox.evaluation.adapters import get_runner
    from agentfox.evaluation.runner import NativeEvalRunner, fit_envelope

    suite_key = payload.get("suite")
    if not suite_key:
        raise ValueError("eval.run requires a 'suite'")
    suite = session.scalar(select(EvalSuite).where(EvalSuite.key == suite_key))
    if suite is None:
        raise LookupError(f"unknown eval suite '{suite_key}'")
    target = dict(payload.get("target") or {})
    scorers = payload.get("scorers")
    runner = get_runner(payload.get("runner"))
    if isinstance(runner, NativeEvalRunner):
        agent = target.get("agent")
        run = runner.run(
            session,
            suite,
            target,
            scorers,
            baseline_run_id=payload.get("baseline_run_id"),
            envelope=fit_envelope(session, agent) if agent else None,
        )
    else:
        run = runner.run(session, suite, target, scorers)
    actor_type, actor_id = _actor(payload)
    chain.append(
        session,
        "eval.run",
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type="eval_run",
        subject_id=run.id,
        payload={
            "suite": suite_key,
            "target": target,
            "runner": run.runner,
            "summary": run.summary_json,
        },
    )
    return {"eval_run_id": run.id, "status": run.status, "summary": run.summary_json}


# ---------------------------------------------------------------------------
# compliance.recompute
# ---------------------------------------------------------------------------


def recompute_compliance(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from agentfox.prove.compliance import compute_all, posture

    window_days = int(payload.get("window_days") or 30)
    statuses = compute_all(session, window_days)
    actor_type, actor_id = _actor(payload)
    chain.append(
        session,
        "compliance.computed",
        actor_type=actor_type,
        actor_id=actor_id,
        payload={"controls": len(statuses), "window_days": window_days},
    )
    return {"computed": len(statuses), "window_days": window_days, "posture": posture(session)}


# ---------------------------------------------------------------------------
# canary.advance
# ---------------------------------------------------------------------------


def advance_canaries(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from agentfox.policy.canary import canary_rollout, evaluate_gate

    actor_type, actor_id = _actor(payload)
    outcomes: list[dict[str, Any]] = []
    rolling = list(session.scalars(select(PolicyCanary).where(PolicyCanary.status == "rolling")))
    for canary in rolling:
        policy = session.get(Policy, canary.policy_id)
        key = policy.key if policy else canary.policy_id
        before_status, before_percent = canary.status, canary.percent
        now = utcnow()
        decision = evaluate_gate(session, canary, now)
        canary = canary_rollout(session, canary.id, now)
        changed = canary.status != before_status or canary.percent != before_percent
        if changed:
            chain.append(
                session,
                "policy.canary_rolled_back"
                if canary.status == "rolled_back"
                else (
                    "policy.canary_completed"
                    if canary.status == "completed"
                    else "policy.canary_advanced"
                ),
                actor_type=actor_type,
                actor_id=actor_id,
                subject_type="policy",
                subject_id=key,
                payload={
                    "canary_id": canary.id,
                    "status": canary.status,
                    "percent": canary.percent,
                    "reason": canary.rollback_reason or decision.reason,
                },
            )
        outcomes.append(
            {
                "canary_id": canary.id,
                "policy": key,
                "action": decision.action,
                "status": canary.status,
                "percent": canary.percent,
                "reason": canary.rollback_reason or decision.reason,
            }
        )
    return {"canaries": outcomes}


# ---------------------------------------------------------------------------
# drift.check
# ---------------------------------------------------------------------------


def check_drift(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from agentfox.evaluation import compute_drift

    scorer = payload.get("scorer") or "groundedness"
    agents = payload.get("agents") or [
        a.slug for a in session.scalars(select(Agent).order_by(Agent.slug))
    ]
    reports = []
    for slug in agents:
        report = compute_drift(session, slug, scorer, persist=True)
        if report is not None:
            reports.append(report.to_json())
    return {
        "scorer": scorer,
        "agents_checked": len(agents),
        "windows_recorded": len(reports),
        "drifted": [r["agent"] for r in reports if r["drifted"]],
    }


# ---------------------------------------------------------------------------
# redteam.posture
# ---------------------------------------------------------------------------


def redteam_posture(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from agentfox.evaluation import run_campaign

    actor_type, actor_id = _actor(payload)
    agents = payload.get("agents") or [
        a.slug
        for a in session.scalars(select(Agent).where(Agent.status == "active").order_by(Agent.slug))
    ]
    campaigns = []
    for slug in agents:
        campaign = run_campaign(
            session,
            slug,
            name=payload.get("name") or "scheduled posture",
            adaptive=True,
            budget=int(payload.get("budget", 3)),
            seed=int(payload.get("seed", 1337)),
        )
        chain.append(
            session,
            "redteam.campaign",
            actor_type=actor_type,
            actor_id=actor_id,
            subject_type="redteam_campaign",
            subject_id=campaign.id,
            payload=campaign.summary_json,
        )
        campaigns.append(
            {
                "agent": slug,
                "campaign_id": campaign.id,
                "headline": campaign.summary_json.get("headline"),
            }
        )
    return {"campaigns": campaigns}


# ---------------------------------------------------------------------------
# probes.run
# ---------------------------------------------------------------------------


def run_live_probes(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Probe every opted-in, due target in the tenant. Consent is per target and
    checked inside `run_target`; a tenant without one does nothing here."""
    from agentfox.evaluation.live_probes import run_due

    return run_due(session, payload)


# ---------------------------------------------------------------------------
# tuning.propose
# ---------------------------------------------------------------------------


def propose_threshold_changes(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Turn labelled false positives into rule cut-off proposals a person decides."""
    from agentfox.improvement.loops import propose_threshold_changes as run_loop

    return run_loop(session, days=int(payload.get("days", 30))).to_json()


# ---------------------------------------------------------------------------
# grants.propose
# ---------------------------------------------------------------------------


def propose_from_traffic(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Turn observed tool calls into tool-declaration and grant proposals a person decides."""
    from agentfox.improvement.traffic import propose_from_traffic as run_loop

    return run_loop(
        session, agent=payload.get("agent"), days=int(payload.get("days", 30))
    ).to_json()


# ---------------------------------------------------------------------------
# escalation.scan
# ---------------------------------------------------------------------------


def scan_escalations(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Missed escalations, false resolutions and SLA breaches, on a schedule."""
    from agentfox.containment.escalation import scheduled_scan

    return scheduled_scan(session, since_hours=int(payload.get("since_hours", 24)))


# ---------------------------------------------------------------------------
# monitors.run
# ---------------------------------------------------------------------------


def run_monitors(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Re-check connected sources: every due monitor, or the one ``monitor_id`` names."""
    from agentfox.monitoring.service import handle_job

    return handle_job(session, payload)


HANDLERS = {
    "escalation.scan": scan_escalations,
    "tuning.propose": propose_threshold_changes,
    "grants.propose": propose_from_traffic,
    "eval.run": run_eval,
    "compliance.recompute": recompute_compliance,
    "canary.advance": advance_canaries,
    "drift.check": check_drift,
    "redteam.posture": redteam_posture,
    "monitors.run": run_monitors,
    "probes.run": run_live_probes,
}


def register_all() -> None:
    for kind, handler in HANDLERS.items():
        jobs_db.register(kind, handler)


register_all()
