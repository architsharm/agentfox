"""Execution-path tracing (NOM-AUD-01).

OpenTelemetry is the wire format (industry standard, multi-vendor
governance, near-zero exposure). What OTel does *not* give us is an agent-native
span model — the correlation of a prompt, its retrievals, its tool calls with their
argument provenance, its delegations and the guardrail decisions taken along the
way, as one auditable object. That correlation is the part we build.

Attribute names follow the OpenLLMetry semantic conventions so existing collectors,
dashboards and SIEMs understand our spans without a translation layer.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.ids import span_id as new_span_id
from agentfox.core.models import (
    Agent,
    Decision,
    DetectionFinding,
    DetectorRun,
    Span,
    TaintTag,
    Trace,
    utcnow,
)

# OpenLLMetry / OTel GenAI semantic conventions.
ATTR_SYSTEM = "gen_ai.system"
ATTR_REQUEST_MODEL = "gen_ai.request.model"
ATTR_RESPONSE_MODEL = "gen_ai.response.model"
ATTR_USAGE_INPUT = "gen_ai.usage.input_tokens"
ATTR_USAGE_OUTPUT = "gen_ai.usage.output_tokens"
ATTR_OPERATION = "gen_ai.operation.name"
ATTR_TOOL_NAME = "gen_ai.tool.name"
# Our namespace, for the agent-native attributes OTel has no convention for.
ATTR_AGENT = "agentfox.agent"
ATTR_VERDICT = "agentfox.verdict"
ATTR_TAINT = "agentfox.taint.max_source"
ATTR_TOOL_IMPACT = "agentfox.tool.impact"


def commit_before_checks(session: Session) -> None:
    """Commit what a request has written so far (the trace, a shadow agent, last
    seen) before its detectors run. Held open, that write transaction kept SQLite's
    single write lock and Postgres's row locks for the whole check, so concurrent
    requests queued behind each other's detectors (the 2026-10-27 latency study:
    ~15 req/s ceiling, 5 s tails, "database is locked"). The decision rows are
    written in a second, short transaction once the verdict is known.

    Only a transaction the session began on its own (autobegin, the request
    session's normal case): a caller that opened one with ``session.begin()`` owns
    when it ends, and committing inside it would break that caller."""
    trans = session.get_transaction()
    origin = getattr(trans, "origin", None) if trans is not None else None
    if (
        trans is not None
        and getattr(origin, "name", "") == "AUTOBEGIN"
        and not session.in_nested_transaction()  # inside a caller's savepoint
    ):
        session.commit()


def start_trace(
    session: Session,
    *,
    agent_id: str | None,
    agent_slug: str | None,
    session_id: str | None = None,
    environment: str = "production",
    intent: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    trace_id: str | None = None,
) -> Trace:
    trace = Trace(
        agent_id=agent_id,
        agent_slug=agent_slug,
        session_id=session_id,
        environment=environment,
        intent=intent,
        model=model,
        provider=provider,
    )
    if trace_id:
        trace.id = trace_id
    session.add(trace)
    session.flush()
    return trace


def end_trace(
    session: Session,
    trace: Trace,
    *,
    verdict: str = "allow",
    status: str = "ok",
    usage: dict[str, Any] | None = None,
    cost_usd: float = 0.0,
) -> Trace:
    trace.ended_at = utcnow()
    trace.verdict = verdict
    trace.status = status
    if usage:
        trace.token_usage_json = usage
    trace.cost_usd = cost_usd
    session.flush()
    return trace


def add_span(
    session: Session,
    trace: Trace | str,
    *,
    kind: str,
    name: str,
    parent_span_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    duration_ms: float = 0.0,
    status: str = "ok",
    error: str | None = None,
    span_id: str | None = None,
) -> Span:
    trace_id = trace if isinstance(trace, str) else trace.id
    started = utcnow()
    span = Span(
        id=span_id or new_span_id(),
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        kind=kind,
        name=name,
        started_at=started,
        ended_at=started + dt.timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        attributes_json=attributes or {},
        status=status,
        error=error,
    )
    session.add(span)
    session.flush()
    return span


@contextmanager
def span(
    session: Session, trace: Trace | str, *, kind: str, name: str, **attrs: Any
) -> Iterator[dict[str, Any]]:
    """Time a block and record it as a span. Errors are recorded, then re-raised."""
    import time

    started = time.perf_counter()
    bag: dict[str, Any] = dict(attrs)
    error: str | None = None
    try:
        yield bag
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        add_span(
            session,
            trace,
            kind=kind,
            name=name,
            attributes=bag,
            duration_ms=(time.perf_counter() - started) * 1000,
            status="error" if error else "ok",
            error=error,
        )


# ---------------------------------------------------------------------------
# Reconstruction — the object an auditor actually reads
# ---------------------------------------------------------------------------


def full_trace(
    session: Session,
    trace_id: str,
    *,
    explain: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any] | None:
    """Assemble the complete execution path: spans, decisions, detector runs, taint.

    ``explain`` rebuilds each decision's "why" from what was recorded; callers pass
    `capabilities.detection.tuning.explain_recorded`. It is a parameter because the
    explanation is detection's to give, and the ledger sits below detection.
    """
    trace = session.get(Trace, trace_id)
    if trace is None:
        return None

    spans = list(
        session.scalars(select(Span).where(Span.trace_id == trace_id).order_by(Span.started_at))
    )
    decisions = list(
        session.scalars(
            select(Decision).where(Decision.trace_id == trace_id).order_by(Decision.created_at)
        )
    )
    runs = list(session.scalars(select(DetectorRun).where(DetectorRun.trace_id == trace_id)))
    findings = list(
        session.scalars(select(DetectionFinding).where(DetectionFinding.trace_id == trace_id))
    )
    taints = list(session.scalars(select(TaintTag).where(TaintTag.trace_id == trace_id)))
    agent = session.get(Agent, trace.agent_id) if trace.agent_id else None

    # A detector run has no FK to the decision it fed — decisions instead carry a
    # `detector_run_ids` list — so invert it here once rather than making every
    # caller (e.g. the guardrail-feedback form) re-derive "which decision was this?".
    decision_by_run: dict[str, str] = {}
    for d in decisions:
        for run_id in d.detector_run_ids or []:
            decision_by_run[run_id] = d.id

    findings_by_run: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        findings_by_run.setdefault(f.detector_run_id, []).append(
            {
                "entity_type": f.entity_type,
                "score": f.score,
                "start": f.start,
                "end": f.end,
                "sample": f.sample,
                "action_taken": f.action_taken,
                "owasp_id": f.owasp_id,
                "atlas_id": f.atlas_id,
            }
        )

    decision_rows = [
        {
            "id": d.id,
            "surface": d.surface,
            "tool": d.tool_key,
            "verdict": d.verdict,
            "mode": d.mode,
            "rules_fired": d.rules_fired_json,
            "policy_version_id": d.policy_version_id,
            "latency_ms": d.latency_ms,
            "approval_id": d.approval_id,
            "taint": d.taint_summary_json,
            "detector_run_ids": d.detector_run_ids or [],
        }
        for d in decisions
    ]
    run_rows = [
        {
            "id": r.id,
            "detector": r.detector_key,
            "version": r.detector_version,
            "surface": r.surface,
            # Two different facts, kept in two fields. `status` answers "did
            # this detector execute" — ok, timeout, skipped_budget — and
            # degradation handling depends on that meaning. `matched` answers
            # "did it find anything", which is what a reader of the run table
            # actually wants: otherwise the detector that drove a block and the
            # three that saw nothing would all read `ok`.
            "status": r.status,
            "matched": bool(findings_by_run.get(r.id)),
            "duration_ms": r.duration_ms,
            "score": r.score,
            "findings": findings_by_run.get(r.id, []),
            "decision_id": decision_by_run.get(r.id),
        }
        for r in runs
    ]

    # The "why", rebuilt from what was recorded. Attached per decision rather than
    # once per trace because a trace can hold several — an input that escalated and
    # an output that blocked are two different answers to "why", and merging them
    # would produce a third that is true of neither.
    for row in decision_rows:
        row["explanation"] = explain(row, run_rows)

    return {
        "trace": {
            "id": trace.id,
            "agent": trace.agent_slug,
            "agent_id": trace.agent_id,
            "agent_name": agent.name if agent else None,
            "session_id": trace.session_id,
            "environment": trace.environment,
            "started_at": _iso(trace.started_at),
            "ended_at": _iso(trace.ended_at),
            "status": trace.status,
            "verdict": trace.verdict,
            "intent": trace.intent,
            "model": trace.model,
            "provider": trace.provider,
            "usage": trace.token_usage_json,
            "cost_usd": trace.cost_usd,
        },
        "spans": [
            {
                "id": s.id,
                "parent_span_id": s.parent_span_id,
                "kind": s.kind,
                "name": s.name,
                "started_at": _iso(s.started_at),
                "duration_ms": s.duration_ms,
                "status": s.status,
                "error": s.error,
                "attributes": s.attributes_json,
            }
            for s in spans
        ],
        "decisions": decision_rows,
        "detector_runs": run_rows,
        "taint": [
            {"path": t.path, "source": t.source, "trust": t.trust, "from": t.propagated_from}
            for t in taints
        ],
    }


def search_traces(
    session: Session,
    *,
    agent_slug: str | None = None,
    verdict: str | None = None,
    environment: str | None = None,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    entity_type: str | None = None,
    tool_key: str | None = None,
    rule_id: str | None = None,
    errors_only: bool = False,
    limit: int = 100,
    group: bool = False,
) -> list[dict[str, Any]]:
    """Runs, newest first. ``group`` folds the runs of one conversation into one row.

    An agent framework checks a message, its model call, each tool and the reply
    separately, and each can be its own run; a person reads one conversation turn.
    Grouped, a row is the conversation (its ``session_id``): its first message, its
    worst outcome, every tool and rule, and ``runs`` for how many it folds.
    """
    if group:
        rows = search_traces(
            session,
            agent_slug=agent_slug,
            verdict=verdict,
            environment=environment,
            since=since,
            until=until,
            entity_type=entity_type,
            tool_key=tool_key,
            rule_id=rule_id,
            errors_only=errors_only,
            limit=min(limit * 10, 2000),
        )
        return _group_conversations(rows)[:limit]
    query = select(Trace).order_by(Trace.started_at.desc())
    if agent_slug:
        query = query.where(Trace.agent_slug == agent_slug)
    if verdict:
        # Comma-separated: the dashboard's "held" covers escalate, its "masked"
        # covers redact/mask/tokenize.
        verdicts = [v.strip() for v in verdict.split(",") if v.strip()]
        query = query.where(Trace.verdict.in_(verdicts))
    if errors_only:
        failed = {s.trace_id for s in session.scalars(select(Span).where(Span.status == "error"))}
        query = query.where((Trace.status == "error") | Trace.id.in_(failed or {"__none__"}))
    if environment:
        query = query.where(Trace.environment == environment)
    else:
        # The dashboard's "Try it" runs; listed only when asked for by name.
        query = query.where(Trace.environment != "playground")
    if since:
        query = query.where(Trace.started_at >= since)
    if until:
        query = query.where(Trace.started_at <= until)

    if entity_type:
        trace_ids = {
            f.trace_id
            for f in session.scalars(
                select(DetectionFinding).where(DetectionFinding.entity_type.like(f"{entity_type}%"))
            )
            if f.trace_id
        }
        query = query.where(Trace.id.in_(trace_ids or {"__none__"}))
    if tool_key:
        trace_ids = {
            d.trace_id
            for d in session.scalars(select(Decision).where(Decision.tool_key == tool_key))
            if d.trace_id
        }
        query = query.where(Trace.id.in_(trace_ids or {"__none__"}))
    if rule_id:
        decisions = select(Decision).where(Decision.trace_id.is_not(None))
        if since:
            decisions = decisions.where(Decision.created_at >= since)
        trace_ids = {
            d.trace_id
            for d in session.scalars(decisions)
            if any(
                isinstance(r, dict) and r.get("rule_id") == rule_id
                for r in d.rules_fired_json or []
            )
        }
        query = query.where(Trace.id.in_(trace_ids or {"__none__"}))

    traces = list(session.scalars(query.limit(limit)))
    # Which rules fired and which tools were called, per trace — so a list of runs
    # can say why each one was stopped without opening it.
    fired: dict[str, list[str]] = {}
    tools: dict[str, list[str]] = {}
    surfaces: dict[str, list[str]] = {}
    # How many checks ran. A run that reached us only as telemetry has none, and
    # must not read as "allowed": nothing decided anything about it.
    checks: dict[str, int] = {}
    # What a rule that is only watching would have done: the strongest effect among
    # fired rules in observe mode. A run that was allowed but would have been
    # blocked is the fact a team needs before switching a rule to enforce.
    would: dict[str, str] = {}
    strength = {"block": 3, "escalate": 2, "redact": 1, "mask": 1, "tokenize": 1}
    if traces:
        for d in session.scalars(
            select(Decision).where(Decision.trace_id.in_({t.id for t in traces}))
        ):
            checks[d.trace_id] = checks.get(d.trace_id, 0) + 1
            for r in d.rules_fired_json or []:
                rid = r.get("rule_id") if isinstance(r, dict) else None
                if rid and rid not in fired.setdefault(d.trace_id, []):
                    fired[d.trace_id].append(rid)
                effect = r.get("effect") if isinstance(r, dict) else None
                if (
                    r.get("mode") if isinstance(r, dict) else None
                ) == "observe" and effect in strength:
                    if strength[effect] > strength.get(would.get(d.trace_id, ""), 0):
                        would[d.trace_id] = effect
            if d.tool_key and d.tool_key not in tools.setdefault(d.trace_id, []):
                tools[d.trace_id].append(d.tool_key)
            if d.surface and d.surface not in surfaces.setdefault(d.trace_id, []):
                surfaces[d.trace_id].append(d.surface)

    return [
        {
            "id": t.id,
            "agent": t.agent_slug,
            "environment": t.environment,
            "started_at": _iso(t.started_at),
            "verdict": t.verdict,
            "status": t.status,
            "model": t.model,
            "provider": t.provider,
            "intent": t.intent,
            "summary": t.summary,
            "cost_usd": t.cost_usd,
            "rules": fired.get(t.id, []),
            "tools": tools.get(t.id, []),
            "surfaces": surfaces.get(t.id, []),
            "would_verdict": would.get(t.id),
            "checks": checks.get(t.id, 0),
            "session_id": t.session_id,
        }
        for t in traces
    ]


_OUTCOME_RANK = {"block": 5, "escalate": 4, "abstain": 3, "redact": 2, "mask": 2, "allow": 0}


def _group_conversations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold rows (newest first) sharing a session into one row per conversation."""
    out: list[dict[str, Any]] = []
    by_session: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = row.get("session_id")
        if not sid:
            out.append({**row, "runs": 1})
            continue
        group = by_session.get(sid)
        if group is None:
            group = {**row, "runs": 1, "rules": list(row["rules"]), "tools": list(row["tools"])}
            group["surfaces"] = list(row["surfaces"])
            by_session[sid] = group
            out.append(group)
            continue
        group["runs"] += 1
        group["checks"] += row["checks"]
        group["cost_usd"] = (group.get("cost_usd") or 0) + (row.get("cost_usd") or 0) or None
        for key in ("rules", "tools", "surfaces"):
            for item in row[key]:
                if item not in group[key]:
                    group[key].append(item)
        if _OUTCOME_RANK.get(row["verdict"], 0) > _OUTCOME_RANK.get(group["verdict"], 0):
            group["verdict"] = row["verdict"]
        if _OUTCOME_RANK.get(row.get("would_verdict") or "", 0) > _OUTCOME_RANK.get(
            group.get("would_verdict") or "", 0
        ):
            group["would_verdict"] = row["would_verdict"]
        # Rows come newest first, so the last summary seen is the conversation's first.
        if row.get("summary"):
            group["summary"] = row["summary"]
        group["model"] = group.get("model") or row.get("model")
    return out


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.isoformat()
