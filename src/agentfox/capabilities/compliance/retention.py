"""Retention: how long each class of recorded data is kept, and the purge that holds it.

Until this module, `retention_policies` rows existed (seeded worlds carried four) and
NOM-AUD-05 read them as evidence that retention was bounded, but nothing ever deleted
or redacted anything by `retain_days`. A retention schedule nobody enforces is a
statement about intent, and the control reported it as a fact.

Now:

* :data:`DATA_CLASSES` is the set of classes a policy can be set for, each with what
  the purge does to it (``delete`` the rows, or ``redact`` the content fields and keep
  the row) and which tables it touches.
* :func:`set_policy` changes one class's period. It is an operator action
  (``operator.retention.changed``) with a required reason and the before/after values,
  because shortening retention destroys records.
* :func:`purge` applies every policy: rows older than ``retain_days`` are deleted or
  redacted. A class with no policy is kept indefinitely. An active legal hold wins:
  a hold with no agent scope stops the purge for every class, an agent-scoped hold
  keeps that agent's rows. Each pass is a `retention_runs` row and an audit entry.
* The audit log is a class (``audit``) only so it can be shown, locked. It cannot be
  given a policy and the purge has no code path that touches `audit_entries` or
  `audit_checkpoints`: removing a row would break the digest over everything after
  it, which is the point of the chain.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import (
    Agent,
    ConversationTurn,
    Decision,
    DetectionFinding,
    DetectorRun,
    EvalResult,
    LegalHold,
    RetentionPolicy,
    RetentionRun,
    Span,
    Trace,
    TraceLink,
    as_aware,
    utcnow,
)

#: Bounds on `retain_days`. A day is the shortest period that still lets the runs
#: list and compliance computation see today's traffic; ten years covers every
#: regulated default we know of.
MIN_DAYS = 1
MAX_DAYS = 3650

#: Content keys stripped from span attributes when prompt content is redacted, on top
#: of the policy's own `redact_fields`. Matched on the last dotted segment, so
#: `agentfox.output` and `gen_ai.prompt` both count.
_CONTENT_KEYS = frozenset({"content", "messages", "input", "output", "prompt", "completion"})
_REDACTED_MARK = "agentfox.retention_redacted"


@dataclass(frozen=True)
class DataClass:
    key: str
    label: str
    #: delete | redact | locked
    action: str
    covers: str
    default_days: int | None


DATA_CLASSES: tuple[DataClass, ...] = (
    DataClass(
        "prompt_content",
        "Prompt and response content",
        "redact",
        "What users asked and agents answered: span content, run previews, conversation "
        "turns. The run, its timing and its decisions stay.",
        90,
    ),
    DataClass(
        "detection_sample",
        "Detection samples",
        "redact",
        "The matched text a detector kept as a sample. The detection itself stays.",
        365,
    ),
    DataClass(
        "traces",
        "Runs",
        "delete",
        "Traces, their spans, external trace links and conversation turns.",
        365,
    ),
    DataClass(
        "decisions",
        "Decisions",
        "delete",
        "Enforcement decisions, detector runs and detection results.",
        365,
    ),
    DataClass(
        "eval_output",
        "Evaluation output",
        "redact",
        "The model output stored with each eval result. Scores stay.",
        180,
    ),
    DataClass(
        "audit",
        "Audit log",
        "locked",
        "The hash-chained audit log. Never purged: removing an entry breaks the chain.",
        None,
    ),
)

_BY_KEY = {c.key: c for c in DATA_CLASSES}


class RetentionError(ValueError):
    pass


def data_class(key: str) -> DataClass:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise RetentionError(
            f"unknown data class '{key}'; one of {[c.key for c in DATA_CLASSES]}"
        ) from None


def _iso(value: dt.datetime | None) -> str | None:
    value = as_aware(value)
    return value.isoformat() if value else None


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def policies(session: Session) -> dict[str, RetentionPolicy]:
    return {p.data_class: p for p in session.scalars(select(RetentionPolicy))}


def set_policy(
    session: Session,
    key: str,
    retain_days: int,
    *,
    actor: str,
    reason: str,
    redact_fields: list[str] | None = None,
) -> RetentionPolicy:
    """Set how long one data class is kept. Audited, with before and after."""
    from agentfox.platform.ledger import operator_log

    spec = data_class(key)
    if spec.action == "locked":
        raise RetentionError("the audit log is append-only and is never purged")
    retain_days = int(retain_days)
    if not MIN_DAYS <= retain_days <= MAX_DAYS:
        raise RetentionError(f"retain_days must be between {MIN_DAYS} and {MAX_DAYS}")

    policy = session.scalar(select(RetentionPolicy).where(RetentionPolicy.data_class == key))
    before = (
        {"retain_days": policy.retain_days, "redact_fields": list(policy.redact_fields or [])}
        if policy
        else None
    )
    if policy is None:
        policy = RetentionPolicy(data_class=key, retain_days=retain_days, redact_fields=[])
        session.add(policy)
    policy.retain_days = retain_days
    if redact_fields is not None:
        policy.redact_fields = [f.strip() for f in redact_fields if f.strip()]
    session.flush()

    operator_log.record(
        session,
        "operator.retention.changed",
        actor=actor,
        reason=reason,
        subject_type="retention_policy",
        subject_id=key,
        before=before,
        after={"retain_days": policy.retain_days, "redact_fields": list(policy.redact_fields)},
    )
    return policy


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------


@dataclass
class _Holds:
    everything: bool
    agent_slugs: set[str]
    agent_ids: set[str]


def _active_holds(session: Session) -> _Holds:
    everything = False
    slugs: set[str] = set()
    for hold in session.scalars(select(LegalHold).where(LegalHold.released_at.is_(None))):
        agents = [a for a in ((hold.scope_json or {}).get("agents") or []) if a and a != "*"]
        if not agents:
            everything = True
        slugs.update(agents)
    ids = (
        {a.id for a in session.scalars(select(Agent).where(Agent.slug.in_(slugs)))}
        if slugs
        else set()
    )
    return _Holds(everything, slugs, ids)


def _held_trace_ids(session: Session, holds: _Holds, cutoff: dt.datetime) -> set[str]:
    if not holds.agent_slugs:
        return set()
    return set(
        session.scalars(
            select(Trace.id).where(
                Trace.started_at < cutoff, Trace.agent_slug.in_(holds.agent_slugs)
            )
        )
    )


def _redact_attributes(attributes: dict[str, Any], extra: set[str]) -> dict[str, Any] | None:
    """The attributes with content removed, or None when there was nothing to remove."""
    keys = _CONTENT_KEYS | extra
    kept = {k: v for k, v in attributes.items() if k.rsplit(".", 1)[-1] not in keys}
    if len(kept) == len(attributes):
        return None
    kept[_REDACTED_MARK] = True
    return kept


def _purge_prompt_content(session, cutoff, holds, policy) -> dict[str, int]:
    held = _held_trace_ids(session, holds, cutoff)
    extra = {f.rsplit(".", 1)[-1] for f in (policy.redact_fields or [])}
    spans = traces = turns = 0
    for span in session.scalars(select(Span).where(Span.started_at < cutoff)):
        if span.trace_id in held or (span.attributes_json or {}).get(_REDACTED_MARK):
            continue
        redacted = _redact_attributes(dict(span.attributes_json or {}), extra)
        if redacted is not None:
            span.attributes_json = redacted
            spans += 1
    for trace in session.scalars(
        select(Trace).where(
            Trace.started_at < cutoff, (Trace.summary.is_not(None)) | (Trace.intent.is_not(None))
        )
    ):
        if trace.id in held:
            continue
        trace.summary = None
        trace.intent = None
        traces += 1
    for turn in session.scalars(
        select(ConversationTurn).where(ConversationTurn.created_at < cutoff)
    ):
        if turn.agent_id in holds.agent_ids or turn.trace_id in held:
            continue
        if turn.user_text or turn.agent_text:
            turn.user_text = ""
            turn.agent_text = ""
            turns += 1
    return {"spans_redacted": spans, "runs_redacted": traces, "turns_redacted": turns}


def _purge_detection_sample(session, cutoff, holds, policy) -> dict[str, int]:
    held = _held_trace_ids(session, holds, cutoff)
    n = 0
    for row in session.scalars(
        select(DetectionFinding).where(
            DetectionFinding.created_at < cutoff, DetectionFinding.sample != ""
        )
    ):
        if row.trace_id in held:
            continue
        row.sample = ""
        n += 1
    return {"samples_redacted": n}


def _purge_traces(session, cutoff, holds, policy) -> dict[str, int]:
    query = select(Trace.id).where(Trace.started_at < cutoff)
    if holds.agent_slugs:
        query = query.where(
            (Trace.agent_slug.is_(None)) | (Trace.agent_slug.not_in(holds.agent_slugs))
        )
    ids = list(session.scalars(query))
    counts = {"runs_deleted": 0, "spans_deleted": 0, "links_deleted": 0, "turns_deleted": 0}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        counts["spans_deleted"] += session.execute(
            delete(Span).where(Span.trace_id.in_(chunk))
        ).rowcount
        counts["links_deleted"] += session.execute(
            delete(TraceLink).where(TraceLink.trace_id.in_(chunk))
        ).rowcount
        counts["turns_deleted"] += session.execute(
            delete(ConversationTurn).where(ConversationTurn.trace_id.in_(chunk))
        ).rowcount
        counts["runs_deleted"] += session.execute(delete(Trace).where(Trace.id.in_(chunk))).rowcount
    return counts


def _purge_decisions(session, cutoff, holds, policy) -> dict[str, int]:
    held = _held_trace_ids(session, holds, cutoff)
    query = select(Decision.id).where(Decision.created_at < cutoff)
    if holds.agent_ids:
        query = query.where(
            (Decision.agent_id.is_(None)) | (Decision.agent_id.not_in(holds.agent_ids))
        )
    ids = list(session.scalars(query))
    run_ids = [
        rid
        for rid, trace_id in session.execute(
            select(DetectorRun.id, DetectorRun.trace_id).where(DetectorRun.created_at < cutoff)
        )
        if trace_id not in held
    ]
    counts = {"decisions_deleted": 0, "detector_runs_deleted": 0, "detections_deleted": 0}
    for i in range(0, len(ids), 500):
        counts["decisions_deleted"] += session.execute(
            delete(Decision).where(Decision.id.in_(ids[i : i + 500]))
        ).rowcount
    for i in range(0, len(run_ids), 500):
        chunk = run_ids[i : i + 500]
        counts["detections_deleted"] += session.execute(
            delete(DetectionFinding).where(DetectionFinding.detector_run_id.in_(chunk))
        ).rowcount
        counts["detector_runs_deleted"] += session.execute(
            delete(DetectorRun).where(DetectorRun.id.in_(chunk))
        ).rowcount
    return counts


def _purge_eval_output(session, cutoff, holds, policy) -> dict[str, int]:
    n = 0
    for row in session.scalars(select(EvalResult).where(EvalResult.created_at < cutoff)):
        if row.output_json:
            row.output_json = {}
            n += 1
    return {"outputs_redacted": n}


_PURGERS = {
    "prompt_content": _purge_prompt_content,
    "detection_sample": _purge_detection_sample,
    "traces": _purge_traces,
    "decisions": _purge_decisions,
    "eval_output": _purge_eval_output,
}

#: Classes whose rows carry no agent, so an agent-scoped hold cannot be applied row by
#: row. The purge skips them entirely while any hold is active.
_UNSCOPED = frozenset({"eval_output"})


def purge(
    session: Session,
    *,
    trigger: str = "schedule",
    requested_by: str = "",
    actor_type: str = "system",
    now: dt.datetime | None = None,
) -> RetentionRun:
    """Apply every retention policy once. Never touches the audit chain's rows."""
    from agentfox.platform.ledger import chain

    now = now or utcnow()
    run = RetentionRun(trigger=trigger, requested_by=requested_by, started_at=now)
    session.add(run)
    session.flush()

    configured = policies(session)
    holds = _active_holds(session)
    results: dict[str, Any] = {}
    for spec in DATA_CLASSES:
        policy = configured.get(spec.key)
        if spec.action == "locked":
            results[spec.key] = {"skipped": "locked"}
            continue
        if policy is None:
            results[spec.key] = {"skipped": "no policy"}
            continue
        if holds.everything or (holds.agent_slugs and spec.key in _UNSCOPED):
            results[spec.key] = {"skipped": "legal hold", "retain_days": policy.retain_days}
            continue
        cutoff = now - dt.timedelta(days=int(policy.retain_days))
        counts = _PURGERS[spec.key](session, cutoff, holds, policy)
        results[spec.key] = {
            "retain_days": policy.retain_days,
            "cutoff": _iso(cutoff),
            "action": spec.action,
            **counts,
        }
    session.flush()

    run.results_json = results
    run.status = "done"
    run.finished_at = utcnow()
    totals = {
        "deleted": sum(v for r in results.values() for k, v in r.items() if k.endswith("_deleted")),
        "redacted": sum(
            v for r in results.values() for k, v in r.items() if k.endswith("_redacted")
        ),
    }
    chain.append(
        session,
        "retention.purged",
        actor_type=actor_type,
        actor_id=requested_by or "retention",
        subject_type="retention_run",
        subject_id=run.id,
        payload={
            "trigger": trigger,
            "legal_hold": "all" if holds.everything else sorted(holds.agent_slugs) or None,
            **totals,
            "classes": {
                k: {kk: vv for kk, vv in v.items() if kk != "cutoff"} for k, v in results.items()
            },
        },
    )
    session.flush()
    return run


def run_json(run: RetentionRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "trigger": run.trigger,
        "requested_by": run.requested_by,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "results": run.results_json,
        "error": run.error or None,
    }


def overview(session: Session) -> dict[str, Any]:
    """Every data class with its policy, plus the last purge and the next scheduled one."""
    from agentfox.core.models import JobSchedule

    configured = policies(session)
    last = session.scalar(select(RetentionRun).order_by(RetentionRun.started_at.desc()).limit(1))
    schedule = session.scalar(select(JobSchedule).where(JobSchedule.kind == "retention.purge"))
    classes = []
    for spec in DATA_CLASSES:
        policy = configured.get(spec.key)
        classes.append(
            {
                "data_class": spec.key,
                "label": spec.label,
                "action": spec.action,
                "covers": spec.covers,
                "retain_days": policy.retain_days if policy else None,
                "redact_fields": list(policy.redact_fields or []) if policy else [],
                "default_days": spec.default_days,
                "updated_at": _iso(policy.updated_at) if policy else None,
                "last_result": (last.results_json or {}).get(spec.key) if last else None,
            }
        )
    # Classes stored before this list existed are shown rather than hidden.
    for key, policy in configured.items():
        if key not in _BY_KEY:
            classes.append(
                {
                    "data_class": key,
                    "label": key,
                    "action": "unenforced",
                    "covers": "Not a class the purge knows; nothing is removed for it.",
                    "retain_days": policy.retain_days,
                    "redact_fields": list(policy.redact_fields or []),
                    "default_days": None,
                    "updated_at": _iso(policy.updated_at),
                    "last_result": None,
                }
            )
    next_run = None
    if schedule is not None and schedule.enabled:
        next_run = _iso(schedule.next_due_at) or "due"
    elif schedule is None and get_settings().scheduler_enabled:
        # The default schedule row is created by the first cron pass for this tenant,
        # which then runs it at once.
        next_run = "due"
    return {
        "classes": classes,
        "last_run": run_json(last),
        "next_run": next_run,
        "schedule_enabled": bool(schedule and schedule.enabled),
        "interval_seconds": schedule.interval_seconds if schedule else None,
    }
