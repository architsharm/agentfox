"""Evaluation routes (Pillar 4).

``POST /api/eval/gate`` is the CI entry point: it returns the regression verdict plus
JUnit and SARIF so the result lands where the engineer already looks — the PR — rather
than in a dashboard nobody opens during a release.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    EvalAnnotation,
    EvalCase,
    EvalResult,
    EvalRun,
    EvalSuite,
    RedTeamCampaign,
    RedTeamFinding,
    Trace,
    User,
)
from agentfox.core.tenancy import session_org
from agentfox.evaluation import (
    all_scorers,
    compute_drift,
    evaluate_slos,
    gate,
    run_campaign,
    sample_production,
    set_slo,
    to_junit,
    to_sarif,
)
from agentfox.evaluation.adapters import available_runners, get_runner
from agentfox.evaluation.redteam import BUILTIN_PROBES
from agentfox.evaluation.runner import NativeEvalRunner, fit_envelope
from agentfox.evaluation.scorers import get_scorer
from agentfox.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.jobs import store as jobs_db
from agentfox.prove.audit import chain

router = APIRouter(prefix="/api", tags=["evaluation"])


# ---------------------------------------------------------------------------
# Suites & cases
# ---------------------------------------------------------------------------


class SuiteIn(BaseModel):
    key: str
    name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class CaseIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    labels: list[str] = Field(default_factory=list)
    split: str = "test"


@router.get("/eval/suites")
def list_suites(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    out = []
    for suite in session.scalars(select(EvalSuite).order_by(EvalSuite.key)):
        cases = session.scalars(select(EvalCase).where(EvalCase.suite_id == suite.id)).all()
        out.append(
            {
                "id": suite.id,
                "key": suite.key,
                "name": suite.name,
                "description": suite.description,
                "tags": suite.tags,
                "cases": len(cases),
            }
        )
    return {"suites": out}


@router.get("/eval/suites/{key}")
def get_suite(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    suite = _suite(session, key)
    cases = session.scalars(
        select(EvalCase).where(EvalCase.suite_id == suite.id).order_by(EvalCase.created_at)
    ).all()
    return {
        "id": suite.id,
        "key": suite.key,
        "name": suite.name,
        "description": suite.description,
        "tags": suite.tags,
        "cases": [
            {
                "id": c.id,
                "input": c.input_json,
                "expected": c.expected_json,
                "context": c.context_json,
                "labels": c.labels,
                "split": c.split,
                "source_trace_id": c.source_trace_id,
            }
            for c in cases
        ],
    }


@router.post("/eval/suites", status_code=201)
def create_suite(
    payload: SuiteIn, session: Session = Depends(db), _user: User = Depends(require("eval"))
) -> dict[str, Any]:
    suite = session.scalar(select(EvalSuite).where(EvalSuite.key == payload.key))
    if suite is None:
        suite = EvalSuite(**payload.model_dump())
        session.add(suite)
        session.flush()
    return {"id": suite.id, "key": suite.key}


@router.post("/eval/suites/{key}/cases", status_code=201)
def add_case(
    key: str,
    payload: CaseIn,
    session: Session = Depends(db),
    _user: User = Depends(require("eval")),
) -> dict[str, Any]:
    suite = _suite(session, key)
    case = EvalCase(
        suite_id=suite.id,
        input_json=payload.input,
        expected_json=payload.expected,
        context_json=payload.context,
        labels=payload.labels,
        split=payload.split,
    )
    session.add(case)
    session.flush()
    return {"id": case.id}


@router.post("/eval/suites/{key}/cases/from-trace", status_code=201)
def promote_trace(
    key: str, trace_id: str, session: Session = Depends(db), user: User = Depends(require("eval"))
) -> dict[str, Any]:
    """P4-6 — promote a production failure into a regression test.

    The shortest path from "this went wrong in production" to "this can never ship
    again" is the feature that makes an eval suite grow instead of rot.
    """
    from agentfox.prove.audit.trace import full_trace

    suite = _suite(session, key)
    trace = session.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(404, "unknown trace")
    detail = full_trace(session, trace_id) or {}

    retrieved: list[str] = []
    output = ""
    for span in detail.get("spans", []):
        attrs = span.get("attributes") or {}
        if attrs.get("agentfox.output"):
            output = str(attrs["agentfox.output"])
        if span.get("kind") == "retrieval" and attrs.get("agentfox.content"):
            retrieved.append(str(attrs["agentfox.content"]))

    case = EvalCase(
        suite_id=suite.id,
        input_json={"prompt": trace.intent or ""},
        expected_json={"goal": trace.intent or ""},
        context_json={"retrieved": retrieved, "observed_output": output},
        labels=["from-production", f"verdict:{trace.verdict}"],
        split="regression",
        source_trace_id=trace_id,
    )
    session.add(case)
    session.flush()
    chain.append(
        session,
        "eval.case_promoted",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="eval_case",
        subject_id=case.id,
        payload={"suite": key, "trace_id": trace_id},
    )
    return {"id": case.id, "suite": key, "source_trace_id": trace_id}


# ---------------------------------------------------------------------------
# Runs & gating
# ---------------------------------------------------------------------------


class RunIn(BaseModel):
    suite: str
    target: dict[str, Any] = Field(default_factory=dict)
    scorers: list[str] | None = None
    baseline_run_id: str | None = None
    runner: str | None = None


@router.post("/eval/runs", status_code=201)
def create_run(
    payload: RunIn, session: Session = Depends(db), user: User = Depends(require("eval"))
) -> dict[str, Any]:
    suite = _suite(session, payload.suite)
    runner = get_runner(payload.runner)
    if isinstance(runner, NativeEvalRunner):
        agent = payload.target.get("agent")
        run = runner.run(
            session,
            suite,
            payload.target,
            payload.scorers,
            baseline_run_id=payload.baseline_run_id,
            envelope=fit_envelope(session, agent) if agent else None,
        )
    else:
        run = runner.run(session, suite, payload.target, payload.scorers)

    chain.append(
        session,
        "eval.run",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="eval_run",
        subject_id=run.id,
        payload={
            "suite": payload.suite,
            "target": payload.target,
            "runner": run.runner,
            "summary": run.summary_json,
        },
    )
    return _run_json(run)


@router.get("/eval/runs")
def list_runs(
    suite: str | None = None,
    limit: int = 50,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    query = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
    if suite:
        query = query.where(EvalRun.suite_id == _suite(session, suite).id)
    return {"runs": [_run_json(r) for r in session.scalars(query)]}


@router.get("/eval/runs/{run_id}")
def get_run(
    run_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    run = session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    results = list(session.scalars(select(EvalResult).where(EvalResult.run_id == run_id)))
    return {
        **_run_json(run),
        "results": [
            {
                "id": r.id,
                "case_id": r.case_id,
                "scorer": r.scorer_key,
                "score": r.score,
                "passed": r.passed,
                "detail": r.detail_json,
                "output": r.output_json,
            }
            for r in results
        ],
    }


def _is_borderline_score(result: EvalResult, band: float) -> bool:
    scorer = get_scorer(result.scorer_key)
    threshold = getattr(scorer, "threshold", None) if scorer else None
    if threshold is None:
        return False
    return abs(result.score - threshold) <= band


@router.get("/eval/annotations/queue")
def eval_annotation_queue(
    run_id: str | None = None,
    band: float = 0.1,
    limit: int = 100,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Eval results a human should look at: score within `band` of the scorer's
    own pass/fail threshold, or scorers disagreeing on the same case — both are
    exactly the shape a human should review rather than trust blindly, not a
    finding-in-itself the way a failed scorer already is."""
    query = select(EvalResult).order_by(EvalResult.created_at.desc())
    if run_id:
        query = query.where(EvalResult.run_id == run_id)
    # A bounded scan (not the whole table) — this queue is meant to surface a
    # recent working set, not paginate the full eval history.
    results = list(session.scalars(query.limit(2000)))

    by_case: dict[tuple[str, str], list[EvalResult]] = {}
    for r in results:
        by_case.setdefault((r.run_id, r.case_id), []).append(r)

    borderline: list[EvalResult] = []
    for r in results:
        siblings = by_case[(r.run_id, r.case_id)]
        disagreement = len({s.passed for s in siblings}) > 1
        if disagreement or _is_borderline_score(r, band):
            borderline.append(r)
        if len(borderline) >= limit:
            break

    annotated_ids = set()
    if borderline:
        annotated_ids = {
            a.eval_result_id
            for a in session.scalars(
                select(EvalAnnotation).where(
                    EvalAnnotation.eval_result_id.in_([r.id for r in borderline])
                )
            )
        }

    return {
        "results": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "case_id": r.case_id,
                "scorer": r.scorer_key,
                "score": r.score,
                "passed": r.passed,
                "annotated": r.id in annotated_ids,
            }
            for r in borderline
        ],
    }


class AnnotateIn(BaseModel):
    verdict: str = "agree"
    note: str


@router.post("/eval/results/{result_id}/annotate")
def annotate_eval_result(
    result_id: str,
    payload: AnnotateIn,
    session: Session = Depends(db),
    user: User = Depends(require("eval")),
) -> dict[str, Any]:
    """Record a human's judgment on a borderline eval result. Requires a note —
    same reasoning as Finding's own suppress/resolve discipline
    (registry.py's patch_finding): a one-click verdict with nothing recorded is
    how a real disagreement about scorer correctness disappears without anyone
    having actually looked."""
    result = session.get(EvalResult, result_id)
    if result is None:
        raise HTTPException(404, "unknown eval result")
    if not payload.note:
        raise HTTPException(400, "annotating requires a note explaining the judgment")
    if payload.verdict not in ("agree", "disagree"):
        raise HTTPException(400, "verdict must be 'agree' or 'disagree'")

    existing = session.scalar(
        select(EvalAnnotation).where(
            EvalAnnotation.eval_result_id == result_id,
            EvalAnnotation.annotator == user.email,
        )
    )
    if existing is None:
        existing = EvalAnnotation(eval_result_id=result_id, annotator=user.email)
        session.add(existing)
    existing.verdict = payload.verdict
    existing.note = payload.note
    session.flush()
    chain.append(
        session,
        "eval_result.annotated",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="eval_result",
        subject_id=result_id,
        payload={"verdict": payload.verdict},
    )
    return {"id": existing.id, "eval_result_id": result_id, "verdict": existing.verdict}


class GateIn(BaseModel):
    suite: str
    target: dict[str, Any] = Field(default_factory=dict)
    scorers: list[str] | None = None
    baseline_run_id: str | None = None
    thresholds: dict[str, float] = Field(default_factory=dict)
    min_pass_rate: float | None = None


@router.post("/eval/gate")
def run_gate(
    payload: GateIn, session: Session = Depends(db), user: User = Depends(require("eval"))
) -> dict[str, Any]:
    """P4-1 — the CI entry point. Non-zero exit maps from ``passed: false``."""
    suite = _suite(session, payload.suite)
    agent = payload.target.get("agent")
    run = NativeEvalRunner().run(
        session,
        suite,
        payload.target,
        payload.scorers,
        baseline_run_id=payload.baseline_run_id,
        envelope=fit_envelope(session, agent) if agent else None,
    )
    result = gate(session, run, payload.baseline_run_id, payload.thresholds, payload.min_pass_rate)
    chain.append(
        session,
        "eval.gate",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="eval_run",
        subject_id=run.id,
        payload={
            "suite": payload.suite,
            "passed": result.passed,
            "regressions": len(result.regressions),
        },
    )
    return {
        **result.to_json(),
        "junit": to_junit(result, payload.suite),
        "sarif": to_sarif(result),
    }


# ---------------------------------------------------------------------------
# Online eval, drift, SLOs
# ---------------------------------------------------------------------------


class OnlineIn(BaseModel):
    agent: str
    scorers: list[str] | None = None
    since_days: int = 7
    rate: float | None = None


@router.post("/eval/online")
def run_online(
    payload: OnlineIn, session: Session = Depends(db), _user: User = Depends(require("eval"))
) -> dict[str, Any]:
    run = sample_production(
        session,
        payload.agent,
        scorers=payload.scorers,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=payload.since_days),
        rate=payload.rate,
    )
    if run is None:
        return {"sampled": 0, "note": "no production traffic matched the window"}
    return _run_json(run)


@router.get("/eval/drift")
def drift(
    agent: str,
    scorer: str = "groundedness",
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Read-only. Viewing drift used to persist a DriftWindow — and a Finding when
    drifted — on every page load, so the number of drift findings measured how often
    someone looked, not how often the agent drifted. Recording is the scheduled
    `drift.check` job (or `agentfox report drift` locally)."""
    report = compute_drift(session, agent, scorer, persist=False)
    if report is None:
        return {
            "drifted": None,
            "note": "insufficient online samples in the current and baseline windows",
        }
    return report.to_json()


@router.get("/eval/slos")
def slos(
    agent: str | None = None, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"slos": evaluate_slos(session, agent)}


class SloIn(BaseModel):
    agent: str
    scorer: str
    objective: str = ""
    window: str = "7d"
    target: float = Field(0.9, ge=0.0, le=1.0)


@router.post("/eval/slos", status_code=201)
def declare_slo(
    payload: SloIn, session: Session = Depends(db), _user: User = Depends(require("eval"))
) -> dict[str, Any]:
    """Declare a reliability target for one agent+scorer pair.

    Without this, `evaluate_slos` has nothing to measure against — a page that only
    reads SLOs and never lets anyone set one is a dead end for every org that hasn't
    already seeded them by hand.
    """
    get_agent_or_404(session, payload.agent)
    slo = set_slo(
        session,
        agent_slug=payload.agent,
        scorer_key=payload.scorer,
        objective=payload.objective,
        window=payload.window,
        target=payload.target,
    )
    return {"slo_id": slo.id, "agent": slo.agent_id, "scorer": slo.scorer_key, "target": slo.target}


@router.get("/eval/scorers")
def scorers(_user: User = Depends(current_user)) -> dict[str, Any]:
    return {
        "scorers": [
            {
                "key": s.key,
                "kind": s.kind,
                "higher_is_better": getattr(s, "higher_is_better", True),
                "threshold": getattr(s, "threshold", None),
            }
            for s in all_scorers().values()
        ],
        "runners": available_runners(),
    }


# ---------------------------------------------------------------------------
# Red team (P4-4)
# ---------------------------------------------------------------------------


class CampaignIn(BaseModel):
    agent: str
    name: str = ""
    probes: list[str] | None = None
    runner: str = "native"
    #: Mutation loop + deployment-targeted probes + posture delta (see run_campaign).
    adaptive: bool = False
    #: Attempts per blocked attack probe in adaptive mode.
    budget: int = Field(3, ge=1, le=20)
    #: Fixes the mutation search so a campaign is reproducible.
    seed: int = 1337
    #: Adaptive only: generate probes from this deployment's grants, tools and policies.
    include_deployment_probes: bool = True


def _run_redteam_sweep(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """PL-5 — the job's handler. See governance.py's _run_evidence_package for
    why the audit-chain entry lives here rather than in the route: this is what
    actually ran, whether that happened synchronously in the enqueueing
    request or later via the cron backstop."""
    campaign = run_campaign(
        session,
        payload["agent"],
        name=payload.get("name", ""),
        runner=payload.get("runner", "native"),
        probes=payload.get("probes"),
        adaptive=bool(payload.get("adaptive", False)),
        budget=int(payload.get("budget", 3)),
        seed=int(payload.get("seed", 1337)),
        include_deployment_probes=bool(payload.get("include_deployment_probes", True)),
    )
    findings = list(
        session.scalars(select(RedTeamFinding).where(RedTeamFinding.campaign_id == campaign.id))
    )
    chain.append(
        session,
        "redteam.campaign",
        actor_type="user",
        actor_id=payload.get("requested_by") or "system",
        subject_type="redteam_campaign",
        subject_id=campaign.id,
        payload=campaign.summary_json,
    )
    return {
        "campaign_id": campaign.id,
        "status": campaign.status,
        "headline": campaign.summary_json.get("headline"),
        "summary": campaign.summary_json,
        "findings": [
            {
                "probe": f.probe,
                "severity": f.severity,
                "succeeded": f.succeeded,
                "owasp_id": f.owasp_id,
                "atlas_id": f.atlas_id,
                "evidence": f.evidence_json,
            }
            for f in findings
        ],
    }


jobs_db.register("redteam.sweep", _run_redteam_sweep)


@router.post("/redteam/campaigns", status_code=201)
def create_campaign(
    payload: CampaignIn, session: Session = Depends(db), user: User = Depends(require("eval"))
) -> dict[str, Any]:
    """Enqueues through jobs_db (PL-5) and processes within this same request
    — see jobs_db's own module docstring and governance.py's build_evidence
    for the same reasoning applied to the other named candidate operation."""
    job = jobs_db.enqueue(
        session,
        "redteam.sweep",
        payload={
            "agent": payload.agent,
            "name": payload.name,
            "runner": payload.runner,
            "probes": payload.probes,
            "adaptive": payload.adaptive,
            "budget": payload.budget,
            "seed": payload.seed,
            "include_deployment_probes": payload.include_deployment_probes,
            "requested_by": user.email,
        },
        org_id=session_org(session),
        requested_by=user.email,
    )
    # Run exactly this job — run_pending(limit=1) would pick the tenant's oldest
    # eligible job, which need not be this one.
    jobs_db.run_job(session, job)
    session.refresh(job)
    if job.status == "dead":
        raise HTTPException(502, f"red-team campaign failed: {job.last_error}")
    if job.status != "done":
        # The first attempt failed and the job is queued for retry with backoff.
        # Saying so — not returning 201 with an empty campaign — is the whole point.
        return JSONResponse(
            status_code=202,
            content={
                "id": None,
                "status": "queued_for_retry",
                "job_id": job.id,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "last_error": job.last_error,
                "retry_after": jobs_db.job_json(job)["available_at"],
            },
        )
    result = job.result_json
    return {
        "id": result.get("campaign_id"),
        "status": result.get("status"),
        "headline": result.get("headline"),
        "summary": result.get("summary"),
        "findings": result.get("findings"),
        "job_id": job.id,
    }


@router.get("/redteam/campaigns")
def list_campaigns(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "runner": c.runner,
                "status": c.status,
                "summary": c.summary_json,
                "created_at": _iso(c.created_at),
            }
            for c in session.scalars(
                select(RedTeamCampaign).order_by(RedTeamCampaign.created_at.desc())
            )
        ]
    }


@router.get("/redteam/probes")
def list_probes(_user: User = Depends(current_user)) -> dict[str, Any]:
    from agentfox.evaluation.redteam import available_runners as rt_runners

    return {
        "probes": [
            {
                "key": p.key,
                "category": p.category,
                "severity": p.severity,
                "owasp_id": p.owasp_id,
                "atlas_id": p.atlas_id,
                "surface": p.surface,
                "description": p.description,
            }
            for p in BUILTIN_PROBES
        ],
        "runners": rt_runners(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _suite(session: Session, key: str) -> EvalSuite:
    suite = session.scalar(select(EvalSuite).where(EvalSuite.key == key))
    if suite is None:
        raise HTTPException(404, f"unknown eval suite '{key}'")
    return suite


def _run_json(run: EvalRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "suite_id": run.suite_id,
        "target": run.target_json,
        "scorers": run.scorer_keys,
        "status": run.status,
        "runner": run.runner,
        "mode": run.mode,
        "summary": run.summary_json,
        "baseline_run_id": run.baseline_run_id,
        "created_at": _iso(run.created_at),
    }


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).isoformat()
