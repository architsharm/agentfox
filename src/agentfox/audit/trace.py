"""Execution-path tracing (P5-1, P5-6, NOM-AUD-01).

OpenTelemetry is the wire format (Appendix A.1: industry standard, multi-vendor
governance, near-zero exposure). What OTel does *not* give us is an agent-native
span model — the correlation of a prompt, its retrievals, its tool calls with their
argument provenance, its delegations and the guardrail decisions taken along the
way, as one auditable object. That correlation is the part we build.

Attribute names follow the OpenLLMetry semantic conventions so existing collectors,
dashboards and SIEMs understand our spans without a translation layer (X-2, P5-4).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ids import span_id as new_span_id
from ..models import Agent, Decision, DetectionFinding, DetectorRun, Span, TaintTag, Trace, utcnow

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
# Reconstruction (P5-6) — the object an auditor actually reads
# ---------------------------------------------------------------------------


def full_trace(session: Session, trace_id: str) -> dict[str, Any] | None:
    """Assemble the complete execution path: spans, decisions, detector runs, taint."""
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
            # Two different facts, and one field was being asked to carry both.
            # `status` answers "did this detector execute" — ok, timeout,
            # skipped_budget — and other code (P3-6 degradation) depends on that
            # meaning, so it is untouched. `matched` answers "did it find
            # anything", which is what a reader of the run table actually wants
            # and could not previously tell: the detector that drove a block and
            # the three that saw nothing all read `ok`.
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
    #
    # Imported here rather than at module scope: `guardrails.tuning` reaches
    # `operator_log`, which reaches `audit.chain`, which is this package — a cycle
    # that the test suite's import order happened to avoid and starting the gateway
    # did not.
    from ..guardrails.tuning import explain_recorded

    for row in decision_rows:
        row["explanation"] = explain_recorded(row, run_rows)

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
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = select(Trace).order_by(Trace.started_at.desc())
    if agent_slug:
        query = query.where(Trace.agent_slug == agent_slug)
    if verdict:
        query = query.where(Trace.verdict == verdict)
    if environment:
        query = query.where(Trace.environment == environment)
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
            "cost_usd": t.cost_usd,
        }
        for t in session.scalars(query.limit(limit))
    ]


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.isoformat()
