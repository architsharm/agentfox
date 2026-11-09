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
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.ids import span_id as new_span_id
from agentfox.core.models import (
    Agent,
    ApprovalRequest,
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


#: The span kind a refusal before any check is recorded as (see `note_refusal`).
REFUSAL_SPAN = "refusal"


def note_refusal(
    session: Session,
    trace: Trace,
    result: dict[str, Any],
    *,
    surface: str,
    tool: str | None = None,
) -> None:
    """Record on the trace that a killed, paused or tripped agent was refused.

    That refusal comes before any check, so no Decision is written (on purpose: the
    breaker counts decisions, and a pause must not trip it on resume). Without this
    the run listed as allowed and "Not checked", and a refused tool call as a model
    call. A span says what was refused and by which rule; `search_traces` reads it.
    """
    if result.get("decision_id") or result.get("verdict") != "block":
        return
    rules = [r.get("rule_id") for r in result.get("rules_fired") or [] if isinstance(r, dict)]
    if not any(isinstance(r, str) and r.startswith("agent.") for r in rules):
        return
    trace.verdict = "block"
    add_span(
        session,
        trace,
        kind=REFUSAL_SPAN,
        name=tool or surface,
        status="blocked",
        attributes={
            "surface": surface,
            "tool": tool,
            "rules": [r for r in rules if r],
            "reason": result.get("reason") or "",
        },
    )


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

    approvals = _approvals_of(session, decisions)
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
            # What became of the approval this decision filed (or redeemed): a held
            # call's run reads "Held" only while nobody has answered.
            "approval": approvals.get(d.approval_id or ""),
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


def _approvals_of(session: Session, decisions: list[Decision]) -> dict[str, dict[str, Any]]:
    """Each approval the decisions name: its status, who decided it, when and why."""
    from agentfox.core.models import User

    ids = {d.approval_id for d in decisions if d.approval_id}
    if not ids:
        return {}
    rows = list(session.scalars(select(ApprovalRequest).where(ApprovalRequest.id.in_(ids))))
    users = {r.resolver_user_id for r in rows if r.resolver_user_id}
    emails = (
        {u.id: u.email or u.id for u in session.scalars(select(User).where(User.id.in_(users)))}
        if users
        else {}
    )
    return {
        r.id: {
            "id": r.id,
            "status": r.status,
            # The CLI records its `--as` name (or "cli") in place of a user id.
            "resolver": emails.get(r.resolver_user_id or "") or r.resolver_user_id,
            "resolved_at": None if r.status == "pending" else _iso(r.updated_at),
            "rationale": r.resolution_rationale or None,
        }
        for r in rows
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
    """Runs, newest first. ``group`` folds the runs of one conversation turn into one row.

    An agent framework checks a message, its model call, each tool and the reply
    separately, and each can be its own run; a person reads one conversation turn.
    Grouped, a row is the turn (`_group_turns`): what the person asked, its worst
    outcome, every tool and rule, ``runs`` for how many runs it folds and
    ``trace_ids`` for which, oldest first.
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
        return _group_turns(rows)[:limit]
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
    # The approval a held call filed, so a list of runs can say Approved or Denied
    # once a person has answered instead of "Held" for ever.
    held: dict[str, str] = {}
    # Which runs carry something the person said: a turn starts at one of these, and
    # a run checking only a tool call, a tool's result or a reply continues one.
    asked: set[str] = set()
    if traces:
        from agentfox.platform.ledger.decision_scope import decision_scope, recorded_only

        for d in session.scalars(
            select(Decision).where(Decision.trace_id.in_({t.id for t in traces}))
        ):
            checks[d.trace_id] = checks.get(d.trace_id, 0) + 1
            if d.surface == "input" and (d.taint_summary_json or {}).get("max_source") in (
                None,
                "user",
            ):
                asked.add(d.trace_id)
            if d.verdict == "escalate" and d.approval_id:
                held.setdefault(d.trace_id, d.approval_id)
            scope = (
                decision_scope(d.taint_summary_json)
                if d.surface == "tool_args"
                else ("enforced", frozenset())
            )
            for r in d.rules_fired_json or []:
                rid = r.get("rule_id") if isinstance(r, dict) else None
                if rid and rid not in fired.setdefault(d.trace_id, []):
                    fired[d.trace_id].append(rid)
                effect = r.get("effect") if isinstance(r, dict) else None
                # A rule that only watched: its pack observes, or the caller ran the
                # call past it (auto() in observe mode, the no-grants carve-out).
                if (
                    isinstance(r, dict)
                    and effect in strength
                    and (r.get("mode") == "observe" or recorded_only(r, scope))
                ):
                    if strength[effect] > strength.get(would.get(d.trace_id, ""), 0):
                        would[d.trace_id] = effect
            if d.tool_key and d.tool_key not in tools.setdefault(d.trace_id, []):
                tools[d.trace_id].append(d.tool_key)
            if d.surface and d.surface not in surfaces.setdefault(d.trace_id, []):
                surfaces[d.trace_id].append(d.surface)
        statuses = (
            dict(
                session.execute(
                    select(ApprovalRequest.id, ApprovalRequest.status).where(
                        ApprovalRequest.id.in_(set(held.values()))
                    )
                ).all()
            )
            if held
            else {}
        )
        # A refusal before any check (a paused agent) left a span, not a decision.
        for sp in session.scalars(
            select(Span).where(Span.trace_id.in_({t.id for t in traces}), Span.kind == REFUSAL_SPAN)
        ):
            attrs = sp.attributes_json or {}
            checks[sp.trace_id] = checks.get(sp.trace_id, 0) + 1
            for rid in attrs.get("rules") or []:
                if rid not in fired.setdefault(sp.trace_id, []):
                    fired[sp.trace_id].append(rid)
            tool = attrs.get("tool")
            if tool and tool not in tools.setdefault(sp.trace_id, []):
                tools[sp.trace_id].append(tool)
            surface = attrs.get("surface")
            if surface == "input":
                asked.add(sp.trace_id)
            if surface and surface not in surfaces.setdefault(sp.trace_id, []):
                surfaces[sp.trace_id].append(surface)

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
            "approval_status": statuses.get(held.get(t.id, "")) if held else None,
            # A run nothing checked (telemetry only) may still be a person's message.
            "asked": t.id in asked or (not checks.get(t.id) and bool(t.summary)),
        }
        for t in traces
    ]


_OUTCOME_RANK = {"block": 5, "escalate": 4, "abstain": 3, "redact": 2, "mask": 2, "allow": 0}


#: The longest pause between two runs of one turn: a model call, its tool calls and
#: the call that reads their results follow each other within seconds; a person's
#: next message to an agent with no session id is a new turn after this long.
TURN_GAP = dt.timedelta(minutes=5)


def _turn_key(row: dict[str, Any]) -> tuple[str, ...]:
    if row.get("session_id"):
        return ("session", row["session_id"])
    return ("agent", row.get("agent") or "", row.get("environment") or "")


def _group_turns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold rows (newest first) into one row per conversation turn, newest first.

    A turn starts at a run that carries what the person said (``asked``) and takes
    the runs after it on the same conversation (its ``session_id``, else the same
    agent and environment within `TURN_GAP`) that only check a tool call, a tool's
    result or the reply. A run that re-checks the same message (a framework sends
    the whole conversation on each model call) continues the turn too, until the
    turn has replied: the same question asked again after an answer is a new turn.
    Without the fold, one question read as three rows, the second and third headed
    by a tool's name and a tool's output.

    A hand-off continues the turn it came from (`_handoff_ack`): the agent handed to
    checks the hand-off's acknowledgement as its input, under its own name, and its
    runs belong to the question the person asked the first agent.
    """
    out: list[dict[str, Any]] = []
    open_turns: dict[tuple[str, ...], tuple[dict[str, Any], dt.datetime | None]] = {}
    # The turn each environment touched last, for a hand-off to continue.
    latest: dict[str, tuple[dict[str, Any], dt.datetime | None]] = {}
    for row in reversed(rows):
        key = _turn_key(row)
        env = str(row.get("environment") or "")
        at = _parse(row.get("started_at"))
        if _handoff_ack(row):
            row = {**row, "asked": False, "summary": None}
            source = open_turns.get(key) if key[0] == "session" else latest.get(env)
            if source is not None and _near(key, at, source[1]):
                turn = source[0]
                _fold(turn, row)
                open_turns[key] = latest[env] = (turn, at or source[1])
                continue
        current = open_turns.get(key)
        if current is not None:
            turn, last = current
            same_message = (
                bool(row.get("summary"))
                and row.get("summary") == turn.get("summary")
                and "output" not in turn["surfaces"]
            )
            if _near(key, at, last) and (not row.get("asked") or same_message):
                _fold(turn, row)
                open_turns[key] = latest[env] = (turn, at or last)
                continue
        turn = {
            **row,
            "runs": 1,
            "trace_ids": [row["id"]],
            "rules": list(row["rules"]),
            "tools": list(row["tools"]),
            "surfaces": list(row["surfaces"]),
        }
        open_turns[key] = latest[env] = (turn, at)
        out.append(turn)
    out.reverse()
    return out


def _near(key: tuple[str, ...], at: dt.datetime | None, last: dt.datetime | None) -> bool:
    return key[0] == "session" or (at is not None and last is not None and at - last <= TURN_GAP)


def _handoff_ack(row: dict[str, Any]) -> bool:
    """Whether the run's message is an OpenAI Agents SDK hand-off's acknowledgement,
    ``{"assistant": "<agent name>"}``: the tool output the agent handed to reads as its
    input, and nothing the person said."""
    summary = str(row.get("summary") or "").strip()
    if not (summary.startswith("{") and summary.endswith("}")):
        return False
    try:
        value = json.loads(summary)
    except ValueError:
        return False
    return isinstance(value, dict) and list(value) == ["assistant"] and isinstance(
        value["assistant"], str
    )


def _fold(turn: dict[str, Any], row: dict[str, Any]) -> None:
    turn["runs"] += 1
    turn["trace_ids"].append(row["id"])
    turn["checks"] += row["checks"]
    turn["cost_usd"] = (turn.get("cost_usd") or 0) + (row.get("cost_usd") or 0) or None
    for key in ("rules", "tools", "surfaces"):
        for item in row[key]:
            if item not in turn[key]:
                turn[key].append(item)
    if _OUTCOME_RANK.get(row["verdict"], 0) > _OUTCOME_RANK.get(turn["verdict"], 0):
        turn["verdict"] = row["verdict"]
        turn["approval_status"] = row.get("approval_status")
    if _OUTCOME_RANK.get(row.get("would_verdict") or "", 0) > _OUTCOME_RANK.get(
        turn.get("would_verdict") or "", 0
    ):
        turn["would_verdict"] = row["would_verdict"]
    if row.get("status") == "error":
        turn["status"] = "error"
    # A turn that opened on a tool's run (its message fell outside the range or the
    # filter) takes the first message it meets.
    if not turn.get("asked") and row.get("asked") and row.get("summary"):
        turn["summary"] = row["summary"]
        turn["asked"] = True
    turn["model"] = turn.get("model") or row.get("model")


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.isoformat()
