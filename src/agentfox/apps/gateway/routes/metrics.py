"""Aggregates for the dashboard's Observe views and policy performance.

Every list endpoint elsewhere returns records; a dashboard needs counts over time,
split by something, compared with the period before. Computing those in the
browser from a capped list of traces is wrong as soon as there are more traces than
the cap, so they are computed here, over the whole window.

Four shapes, all filtered the same way (`range`, `agent`, `environment`):

* ``/summary``   — totals, one series per outcome, the previous period's totals
* ``/breakdown`` — the same counts split by agent, environment, model, tool or surface
* ``/rules``     — per rule: how often it fired, enforced vs only watching, trend
* ``/errors``    — failed steps (tool and model errors), grouped
* ``/activity``  — when the last request was, and the smallest range that shows it,
  so a view with no range chosen opens on data instead of an empty week

Outcomes use the dashboard's four words, not the six verdicts: ``allowed``,
``masked`` (redact/mask/tokenize), ``held`` (escalate) and ``blocked``.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db
from agentfox.core.models import Agent, Decision, Span, Trace, User

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

#: Window length and bucket size for each range the dashboard offers.
RANGES: dict[str, tuple[dt.timedelta, dt.timedelta]] = {
    "24h": (dt.timedelta(hours=24), dt.timedelta(hours=1)),
    "7d": (dt.timedelta(days=7), dt.timedelta(hours=6)),
    "30d": (dt.timedelta(days=30), dt.timedelta(days=1)),
    "90d": (dt.timedelta(days=90), dt.timedelta(days=3)),
}

OUTCOMES = ("allowed", "masked", "held", "blocked")

_OUTCOME = {
    "allow": "allowed",
    "redact": "masked",
    "mask": "masked",
    "tokenize": "masked",
    "escalate": "held",
    "block": "blocked",
}

DIMENSIONS = ("agent", "environment", "model", "tool", "surface")

#: Requests sent from the dashboard's "Try it". Excluded unless asked for by name.
PLAYGROUND = "playground"


def outcome(verdict: str | None) -> str:
    return _OUTCOME.get(verdict or "allow", "allowed")


def _aware(value: dt.datetime) -> dt.datetime:
    # SQLite returns naive datetimes for timezone-aware columns.
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


class Window:
    def __init__(self, key: str, now: dt.datetime | None = None) -> None:
        if key not in RANGES:
            raise HTTPException(422, f"range must be one of {', '.join(RANGES)}")
        self.key = key
        self.length, self.step = RANGES[key]
        self.end = now or dt.datetime.now(dt.UTC)
        self.start = self.end - self.length
        self.prev_start = self.start - self.length
        self.count = int(self.length / self.step)

    def index(self, at: dt.datetime) -> int | None:
        at = _aware(at)
        if at < self.start or at > self.end:
            return None
        return min(self.count - 1, int((at - self.start) / self.step))

    def bucket_starts(self) -> list[str]:
        return [(self.start + i * self.step).isoformat() for i in range(self.count)]


def _agent_id(session: Session, slug: str | None) -> str | None:
    if not slug:
        return None
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    return agent.id if agent else "__none__"


def _traces(
    session: Session,
    since: dt.datetime,
    until: dt.datetime,
    agent: str | None,
    environment: str | None,
):
    q = select(Trace).where(Trace.started_at >= since, Trace.started_at <= until)
    if agent:
        q = q.where(Trace.agent_slug == agent)
    if environment:
        q = q.where(Trace.environment == environment)
    else:
        q = q.where(Trace.environment != PLAYGROUND)
    return list(session.scalars(q))


def _decisions(session: Session, w: Window, agent: str | None, environment: str | None):
    q = select(Decision).where(Decision.created_at >= w.start, Decision.created_at <= w.end)
    agent_id = _agent_id(session, agent)
    if agent_id:
        q = q.where(Decision.agent_id == agent_id)
    # Every number on these views links to the runs behind it, so a check that
    # belongs to no run (and a red-team probe's simulated `redteam.*` tool, which is
    # a test and not traffic) is left out rather than counted and then unopenable.
    q = q.where(Decision.trace_id.is_not(None))
    decisions = [d for d in session.scalars(q) if not (d.tool_key or "").startswith("redteam.")]
    played = {
        t.id
        for t in session.scalars(
            select(Trace).where(
                Trace.id.in_({d.trace_id for d in decisions if d.trace_id}),
                Trace.environment == PLAYGROUND,
            )
        )
    }
    if played and environment != PLAYGROUND:
        decisions = [d for d in decisions if d.trace_id not in played]
    if environment:
        trace_env = {
            t.id: t.environment
            for t in session.scalars(
                select(Trace).where(Trace.id.in_({d.trace_id for d in decisions if d.trace_id}))
            )
        }
        decisions = [d for d in decisions if trace_env.get(d.trace_id or "") == environment]
    return decisions


def _error_trace_ids(session: Session, trace_ids: set[str]) -> set[str]:
    if not trace_ids:
        return set()
    return {
        s.trace_id
        for s in session.scalars(
            select(Span).where(Span.trace_id.in_(trace_ids), Span.status == "error")
        )
    }


def _totals(traces: list[Trace], errors: set[str]) -> dict[str, Any]:
    counts = Counter(outcome(t.verdict) for t in traces)
    return {
        "requests": len(traces),
        **{o: counts.get(o, 0) for o in OUTCOMES},
        "errors": sum(1 for t in traces if t.id in errors or t.status == "error"),
        "cost_usd": round(sum(t.cost_usd or 0.0 for t in traces), 6),
        "agents": len({t.agent_slug for t in traces if t.agent_slug}),
    }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(p * (len(values) - 1))))
    return round(values[k], 2)


@router.get("/activity")
def activity(
    agent: str | None = None,
    environment: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    q = select(func.max(Trace.started_at))
    if agent:
        q = q.where(Trace.agent_slug == agent)
    if environment:
        q = q.where(Trace.environment == environment)
    else:
        q = q.where(Trace.environment != PLAYGROUND)
    last = session.scalar(q)
    if last is None:
        return {"last_request_at": None, "range": "7d"}
    age = dt.datetime.now(dt.UTC) - _aware(last)
    # The smallest range from the default week up that contains it; past the
    # longest, the longest. Never narrower than a week: recent traffic still
    # reads better against its week than against one day.
    fits = [k for k, (length, _step) in RANGES.items() if k != "24h" and age <= length]
    return {
        "last_request_at": _aware(last).isoformat(),
        "range": fits[0] if fits else list(RANGES)[-1],
    }


@router.get("/summary")
def summary(
    window: str = Query("7d", alias="range"),
    agent: str | None = None,
    environment: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    w = Window(window)
    traces = _traces(session, w.start, w.end, agent, environment)
    previous = _traces(session, w.prev_start, w.start, agent, environment)
    errors = _error_trace_ids(session, {t.id for t in traces} | {t.id for t in previous})

    series = [{o: 0 for o in (*OUTCOMES, "errors")} for _ in range(w.count)]
    for t in traces:
        i = w.index(t.started_at)
        if i is None:
            continue
        series[i][outcome(t.verdict)] += 1
        if t.id in errors or t.status == "error":
            series[i]["errors"] += 1

    latencies = [d.latency_ms for d in _decisions(session, w, agent, environment) if d.latency_ms]
    return {
        "range": w.key,
        "start": w.start.isoformat(),
        "end": w.end.isoformat(),
        "bucket_seconds": int(w.step.total_seconds()),
        "buckets": [{"t": t, **s} for t, s in zip(w.bucket_starts(), series, strict=True)],
        "totals": _totals(traces, errors),
        "previous": _totals(previous, errors),
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
    }


@router.get("/breakdown")
def breakdown(
    dim: str = Query("agent"),
    window: str = Query("7d", alias="range"),
    agent: str | None = None,
    environment: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    if dim not in DIMENSIONS:
        raise HTTPException(422, f"dim must be one of {', '.join(DIMENSIONS)}")
    w = Window(window)
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"requests": 0, **{o: 0 for o in OUTCOMES}, "errors": 0, "cost_usd": 0.0}
    )

    if dim in ("tool", "surface"):
        # A tool call or a check surface is a decision, not a whole request.
        for d in _decisions(session, w, agent, environment):
            key = (d.tool_key if dim == "tool" else d.surface) or ""
            if not key:
                continue
            row = rows[key]
            row["requests"] += 1
            row[outcome(d.verdict)] += 1
    else:
        traces = _traces(session, w.start, w.end, agent, environment)
        errors = _error_trace_ids(session, {t.id for t in traces})
        for t in traces:
            key = {"agent": t.agent_slug, "environment": t.environment, "model": t.model}[
                dim
            ] or "(unknown)"
            row = rows[key]
            row["requests"] += 1
            row[outcome(t.verdict)] += 1
            row["errors"] += 1 if (t.id in errors or t.status == "error") else 0
            row["cost_usd"] = round(row["cost_usd"] + (t.cost_usd or 0.0), 6)

    ordered = sorted(rows.items(), key=lambda kv: kv[1]["requests"], reverse=True)
    return {"range": w.key, "dim": dim, "rows": [{"key": k, **v} for k, v in ordered]}


#: What a rule caught, by the detection it matched on — the first thing a fired rule
#: records — so `eu.art15.injection_resistance` counts as an attack, not compliance.
_ENTITY_CATEGORY = (
    ("INJECTION", "attacks"),
    ("JAILBREAK", "attacks"),
    ("PII", "data"),
    ("SECRET", "data"),
    ("SAFETY", "content"),
    ("TOXIC", "content"),
    ("GROUNDING", "quality"),
    ("SCHEMA", "quality"),
    ("HALLUCINATION", "quality"),
    ("CUSTOM", "custom"),
)
_ID_CATEGORY = (
    ("custom.", "custom"),
    ("injection.", "attacks"),
    ("pii.", "data"),
    ("secrets.", "data"),
    ("safety.", "content"),
    ("eu.", "compliance"),
    ("disclosure.", "compliance"),
    ("budget.", "cost"),
    ("loop.", "cost"),
    ("schema.", "quality"),
    ("completion.", "quality"),
    ("grounding.", "quality"),
    ("answerability.", "quality"),
    ("control_plane.", "platform"),
    ("pipeline.", "platform"),
)


def rule_category(rule_id: str, fired: dict[str, Any] | None = None) -> str:
    """attacks, data, content, quality, custom, compliance, cost, platform or actions."""
    for entity in [*(fired or {}).get("entity_prefixes", []), *(fired or {}).get("entities", [])]:
        head = str(entity).upper()
        for prefix, category in _ENTITY_CATEGORY:
            if head.startswith(prefix):
                return category
    if rule_id == "tool.not_declared":
        return "quality"
    for prefix, category in _ID_CATEGORY:
        if rule_id.startswith(prefix):
            return category
    return "actions"


@router.get("/rules")
def rules(
    window: str = Query("7d", alias="range"),
    agent: str | None = None,
    environment: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """How each rule behaved: fired, stopped something, or only watched.

    ``enforced`` counts fires that changed the outcome; ``watched`` counts fires in
    observe mode — what the rule would have done had it been enforcing. That second
    number is the one a team needs before promoting a rule.
    """
    w = Window(window)
    agent_slug = {a.id: a.slug for a in session.scalars(select(Agent))}
    stats: dict[str, dict[str, Any]] = {}
    for d in _decisions(session, w, agent, environment):
        for fired in d.rules_fired_json or []:
            rule_id = fired.get("rule_id") if isinstance(fired, dict) else None
            if not rule_id:
                continue
            s = stats.setdefault(
                rule_id,
                {
                    "rule_id": rule_id,
                    "fires": 0,
                    "enforced": 0,
                    "watched": 0,
                    "effect": fired.get("effect"),
                    "severity": fired.get("severity"),
                    "last_fired": None,
                    "series": [0] * w.count,
                    "agents": Counter(),
                    "tools": Counter(),
                    "sample_trace_ids": [],
                    "category": rule_category(rule_id, fired),
                },
            )
            s["fires"] += 1
            watched = (fired.get("mode") or d.mode) == "observe"
            s["watched" if watched else "enforced"] += 1
            at = _aware(d.created_at)
            if not s["last_fired"] or at.isoformat() > s["last_fired"]:
                s["last_fired"] = at.isoformat()
            i = w.index(at)
            if i is not None:
                s["series"][i] += 1
            if d.agent_id:
                s["agents"][agent_slug.get(d.agent_id, d.agent_id)] += 1
            if d.tool_key:
                s["tools"][d.tool_key] += 1
            if (
                d.trace_id
                and d.trace_id not in s["sample_trace_ids"]
                and len(s["sample_trace_ids"]) < 5
            ):
                s["sample_trace_ids"].append(d.trace_id)

    out = []
    for s in sorted(stats.values(), key=lambda s: s["fires"], reverse=True):
        out.append(
            {
                **s,
                "agents": dict(s["agents"].most_common(5)),
                "tools": dict(s["tools"].most_common(5)),
            }
        )
    return {
        "range": w.key,
        "bucket_seconds": int(w.step.total_seconds()),
        "rules": out,
        "checked": checked_categories(session),
    }


def checked_categories(session: Session) -> dict[str, bool]:
    """Which areas any enabled rule in force covers, so a view can tell "nothing
    happened" (0) from "nothing is looking" (not checked)."""
    from agentfox.core.models import KnowledgeBoundary
    from agentfox.platform.policy.store import active_layers

    seen: set[str] = set()
    for layer in active_layers(session):
        for rule in layer.document.rules:
            if not rule.enabled:
                continue
            detection = rule.when.detection
            fired = (
                {
                    "entity_prefixes": [detection.entity_prefix] if detection.entity_prefix else [],
                    "entities": [detection.entity] if detection.entity else [],
                }
                if detection
                else None
            )
            seen.add(rule_category(rule.id, fired))
    if session.scalar(select(func.count()).select_from(KnowledgeBoundary)):
        seen.add("quality")
    return {c: c in seen for c in ("attacks", "data", "content", "quality", "actions", "custom")}


@router.get("/errors")
def errors(
    window: str = Query("7d", alias="range"),
    agent: str | None = None,
    environment: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Steps that failed — a tool that threw, a model call that errored — grouped."""
    w = Window(window)
    traces = {t.id: t for t in _traces(session, w.start, w.end, agent, environment)}
    rows, _ = _error_rows(session, traces)
    return {"range": w.key, "rows": rows}


def _error_rows(
    session: Session, traces: dict[str, Trace]
) -> tuple[list[dict[str, Any]], list[dt.datetime]]:
    """Failed steps in these traces, grouped by step, and when each one failed."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    when: list[dt.datetime] = []
    if traces:
        for s in session.scalars(
            select(Span).where(Span.trace_id.in_(set(traces)), Span.status == "error")
        ):
            key = (s.kind, s.name or s.kind)
            g = groups.setdefault(
                key,
                {
                    "kind": s.kind,
                    "name": s.name or s.kind,
                    "count": 0,
                    "agents": Counter(),
                    "last": None,
                    "sample_trace_id": s.trace_id,
                    "message": (s.error or "")[:200],
                },
            )
            g["count"] += 1
            t = traces.get(s.trace_id)
            if t and t.agent_slug:
                g["agents"][t.agent_slug] += 1
            started = _aware(s.started_at)
            when.append(started)
            at = started.isoformat()
            if not g["last"] or at > g["last"]:
                g["last"], g["sample_trace_id"] = at, s.trace_id
    rows = sorted(groups.values(), key=lambda g: g["count"], reverse=True)
    return [{**g, "agents": dict(g["agents"])} for g in rows], when


#: Finding types that say an answer or an outcome was wrong, rather than unsafe.
_QUALITY_FINDING_OWNERS = ("grounding",)
_QUALITY_FINDING_TYPES = ("drift", "missed_escalation", "false_resolution", "incomplete_handoff")


@router.get("/quality")
def quality(
    agent: str,
    window: str = Query("7d", alias="range"),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Is this agent giving right answers: every quality signal already recorded for it.

    * ``wrong_answers`` — fires of the rules that catch a wrong result (grounding,
      answerability abstentions, reply format, unverified completion, made-up tools)
    * ``failed_steps`` — tool and model calls that errored
    * ``evals`` — scored runs of its production traffic, and its reliability targets
    * ``feedback`` — what people said about its decisions
    * ``handoffs`` — conversations that should have reached a person
    * ``findings`` — open quality issues

    ``checked`` says whether any rule looks for wrong results at all, so "0" can be
    told apart from "nothing is looking".
    """
    from agentfox.capabilities.containment.escalation import escalation_report
    from agentfox.capabilities.evaluation.drift import evaluate_slos
    from agentfox.core.models import EvalRun, Finding, GuardrailFeedback
    from agentfox.platform.ledger.finding_types import all_types

    record = session.scalar(select(Agent).where(Agent.slug == agent))
    if record is None:
        raise HTTPException(404, f"unknown agent '{agent}'")
    w = Window(window)
    traces = {t.id: t for t in _traces(session, w.start, w.end, agent, None)}

    # --- wrong answers -----------------------------------------------------------
    rules: dict[str, dict[str, Any]] = {}
    wrong_series = [0] * w.count
    wrong_traces: set[str] = set()
    abstained = 0
    for d in _decisions(session, w, agent, None):
        fired_quality = [
            f
            for f in d.rules_fired_json or []
            if isinstance(f, dict)
            and f.get("rule_id")
            and rule_category(f["rule_id"], f) == "quality"
        ]
        if d.verdict == "abstain":
            abstained += 1
        if not fired_quality:
            continue
        i = w.index(d.created_at)
        if i is not None:
            wrong_series[i] += 1
        if d.trace_id:
            wrong_traces.add(d.trace_id)
        at = _aware(d.created_at).isoformat()
        for fired in fired_quality:
            r = rules.setdefault(
                fired["rule_id"],
                {
                    "rule_id": fired["rule_id"],
                    "fires": 0,
                    "enforced": 0,
                    "watched": 0,
                    "last_fired": None,
                    "sample_trace_id": d.trace_id,
                    "series": [0] * w.count,
                },
            )
            r["fires"] += 1
            watched = (fired.get("mode") or d.mode) == "observe"
            r["watched" if watched else "enforced"] += 1
            if i is not None:
                r["series"][i] += 1
            if not r["last_fired"] or at > r["last_fired"]:
                r["last_fired"], r["sample_trace_id"] = at, d.trace_id

    # --- failed steps and requests -----------------------------------------------
    error_rows, error_times = _error_rows(session, traces)
    error_series = [0] * w.count
    for at in error_times:
        if (i := w.index(at)) is not None:
            error_series[i] += 1
    request_series = [0] * w.count
    for t in traces.values():
        if (i := w.index(t.started_at)) is not None:
            request_series[i] += 1
    failed_traces = _error_trace_ids(session, set(traces)) | {
        t.id for t in traces.values() if t.status == "error"
    }

    # --- evaluations -------------------------------------------------------------
    runs = [
        r
        for r in session.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(200))
        if (r.target_json or {}).get("agent") == agent
    ][:10]

    def scorer_rates(run: EvalRun) -> dict[str, float | None]:
        scorers = (run.summary_json or {}).get("scorers") or {}
        return {k: v.get("pass_rate") for k, v in scorers.items() if isinstance(v, dict)}

    def mean(values: list[float | None]) -> float | None:
        known = [v for v in values if v is not None]
        return round(sum(known) / len(known), 4) if known else None

    evals = [
        {
            "id": r.id,
            "mode": r.mode,
            "status": r.status,
            "created_at": _aware(r.created_at).isoformat() if r.created_at else None,
            "cases": (r.summary_json or {}).get("cases"),
            "pass_rate": mean(list(scorer_rates(r).values())),
            "scorers": scorer_rates(r),
        }
        for r in runs
    ]

    # --- feedback ----------------------------------------------------------------
    labels: Counter = Counter()
    recent_feedback = []
    for row in session.scalars(
        select(GuardrailFeedback)
        .where(GuardrailFeedback.agent_id == record.id, GuardrailFeedback.created_at >= w.start)
        .order_by(GuardrailFeedback.created_at.desc())
    ):
        labels[row.label] += 1
        if len(recent_feedback) < 5:
            recent_feedback.append(
                {
                    "label": row.label,
                    "detector_key": row.detector_key,
                    "trace_id": row.trace_id,
                    "note": row.note,
                    "actor": row.actor,
                    "at": _aware(row.created_at).isoformat(),
                }
            )

    # --- open quality findings ---------------------------------------------------
    quality_types = {t.type for t in all_types() if t.owner in _QUALITY_FINDING_OWNERS} | set(
        _QUALITY_FINDING_TYPES
    )
    findings = [
        {"id": f.id, "type": f.type, "severity": f.severity, "title": f.title}
        for f in session.scalars(
            select(Finding)
            .where(
                Finding.subject_id.in_([record.id, agent]),
                Finding.status == "open",
                Finding.type.in_(quality_types),
            )
            .order_by(Finding.created_at.desc())
        )
    ]

    hours = int(w.length.total_seconds() // 3600)
    escalation = escalation_report(session, since_hours=hours, agent_slug=agent)
    total = len(traces)
    return {
        "agent": agent,
        "range": w.key,
        "bucket_seconds": int(w.step.total_seconds()),
        "buckets": w.bucket_starts(),
        "checked": checked_categories(session)["quality"],
        "requests": total,
        "trend": {
            "requests": request_series,
            "wrong_answers": wrong_series,
            "failed_steps": error_series,
        },
        "wrong_answers": {
            "total": sum(r["fires"] for r in rules.values()),
            "requests": len(wrong_traces),
            "rate": round(len(wrong_traces) / total, 4) if total else None,
            "abstained": abstained,
            "rules": sorted(rules.values(), key=lambda r: r["fires"], reverse=True),
        },
        "failed_steps": {
            "total": len(error_times),
            "requests": len(failed_traces),
            "rate": round(len(failed_traces) / total, 4) if total else None,
            "rows": error_rows,
        },
        "evals": {"runs": evals, "slos": evaluate_slos(session, agent)},
        "feedback": {
            "labels": {
                k: labels.get(k, 0) for k in ("false_positive", "true_positive", "false_negative")
            },
            "recent": recent_feedback,
        },
        "handoffs": {
            "handoffs": escalation["handoffs"],
            "qualified": escalation["qualified_for_escalation"],
            "missed": escalation["missed_escalations"],
            "false_resolutions": escalation["false_resolutions"],
        },
        "findings": findings,
    }
