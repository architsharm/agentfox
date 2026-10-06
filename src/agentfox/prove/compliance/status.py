"""Continuous compliance monitoring (NOM-GOV-04).

**The difference between a compliance product and a compliance-theatre product.**

Credo AI and OneTrust largely collect attestations: someone fills in a form saying
the control operates. We compute status from the same execution data that drives
runtime enforcement — because we are inline, we can. That is a claim only an
agent-native platform can make, and it is why the compliance pillar had to be built
on top of the runtime pillar rather than beside it.

Every status carries the evidence that produced it and a rationale a human can argue
with. Two rules are deliberately strict:

* ``chain_valid`` is a **hard signal** — a single audit-chain verification failure is
  ``failing``, never ``degraded``. A chain that "mostly" verifies has no evidentiary
  value at all.
* A control whose evidence source is producing nothing is ``not_implemented``, not
  ``effective``. Silence is not success — and a detector that quietly stopped running
  while its control reports green is the exact failure mode this rule prevents.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    Agent,
    Control,
    ControlStatus,
    Decision,
    DetectorRun,
    EvalResult,
    Finding,
    Identity,
    RiskAssessment,
    utcnow,
)

STATUSES = ("effective", "degraded", "failing", "not_implemented", "not_applicable")

#: Tables a `presence` / `freshness` rule can name, mapped to their model.
_TABLES: dict[str, Any] = {}

#: A raw table name ("end_user_principals") means nothing to someone reading a
#: rationale on the Compliance page — this is the difference between "not
#: implemented" as a dead end and "not implemented, go here to fix it" as a next
#: step. Deliberately only covers tables a human actually fills in from a
#: dashboard page or CLI command; tables that only ever populate from real traffic
#: (traces, decisions, audit_entries, ...) are left unmapped rather than repeating
#: "send traffic through it", which the rationale already implies.
_TABLE_HINTS: dict[str, str] = {
    "end_user_principals": "Register a caller on the Entitlement page.",
    "resource_grants": "Add a grant on the Entitlement page.",
    "source_records": "Tier a source on the Sources page.",
    "knowledge_boundaries": "Declare what an agent may answer, from that agent's page.",
    "handoffs": "Raise or detect a hand-off on the Escalation page.",
    "retention_policies": (
        "Seeded worlds carry one. There is no command or screen to add another yet, "
        "so this stays open on a fresh tenant."
    ),
    "redteam_campaigns": "Run a red-team campaign on the Evaluation page.",
    "eval_runs": "Create and run an eval suite on the Evaluation page.",
    "budgets": (
        "Seeded worlds carry one. There is no command or screen to add another yet, "
        "so this stays open on a fresh tenant."
    ),
    "slos": "Declare a reliability objective on the Evaluation page.",
    "mcp_tool_snapshots": "Connect an MCP server on the Connect page.",
}


def _hint(tables: list[str]) -> str:
    hints = sorted({_TABLE_HINTS[t] for t in tables if t in _TABLE_HINTS})
    return (" " + " ".join(hints)) if hints else ""


def _table(name: str):
    global _TABLES
    if not _TABLES:
        from agentfox.core import models

        _TABLES = {
            m.__tablename__: m
            for m in vars(models).values()
            if isinstance(m, type) and hasattr(m, "__tablename__")
        }
    return _TABLES.get(name)


def _count(session: Session, table: str, since: dt.datetime | None = None) -> int:
    model = _table(table)
    if model is None:
        return 0
    query = select(func.count()).select_from(model)
    if since is not None and hasattr(model, "created_at"):
        query = query.where(model.created_at >= since)
    return int(session.scalar(query) or 0)


def _open_findings(session: Session, types: list[str], since: dt.datetime | None = None) -> int:
    if not types:
        return 0
    query = (
        select(func.count())
        .select_from(Finding)
        .where(Finding.type.in_(types), Finding.status == "open")
    )
    if since is not None:
        query = query.where(Finding.created_at >= since)
    return int(session.scalar(query) or 0)


def evaluate_control(
    session: Session,
    control: Control,
    *,
    window_days: int = 30,
    scope: dict[str, Any] | None = None,
) -> ControlStatus:
    rule = control.status_rule_json or {}
    kind = rule.get("kind", "presence")
    since = utcnow() - dt.timedelta(days=window_days)
    evidence: dict[str, Any] = {"window_days": window_days, "rule": kind}

    handler = _RULE_HANDLERS.get(kind, _rule_presence)

    status, rationale, detail = handler(session, control, rule, since)
    evidence.update(detail)

    # A rule can be downgraded by open findings of specific types, so that a control
    # cannot report effective while the very thing it governs is alarming.
    degrading = rule.get("open_findings_degrade") or []
    if status == "effective" and degrading:
        open_count = _open_findings(session, degrading, since)
        if open_count:
            status = "degraded"
            rationale += f" Downgraded: {open_count} open finding(s) of type {degrading}."
            evidence["open_findings"] = open_count

    record = ControlStatus(
        control_key=control.key,
        scope_json=scope or {},
        status=status,
        evidence_json=evidence,
        rationale=rationale,
    )
    session.add(record)
    session.flush()
    return record


# ---------------------------------------------------------------------------
# Rule handlers — each returns (status, rationale, evidence)
# ---------------------------------------------------------------------------


def _rule_presence(session, control, rule, since) -> tuple[str, str, dict]:
    required = rule.get("requires") or control.evidence_sources or []
    counts = {name: _count(session, name) for name in required}
    missing = [name for name, n in counts.items() if n == 0]
    if not counts:
        return "not_implemented", "No evidence source declared for this control.", {}
    if missing:
        return (
            "not_implemented" if len(missing) == len(counts) else "degraded",
            f"No records in {missing}; the control cannot be evidenced.{_hint(missing)}",
            {"counts": counts, "missing": missing},
        )
    return "effective", f"Evidence present in {sorted(counts)}.", {"counts": counts}


def _rule_ratio(session, control, rule, since) -> tuple[str, str, dict]:
    numerator = _measure(session, rule.get("numerator", ""))
    denominator = _measure(session, rule.get("denominator", ""))
    if denominator == 0:
        return "not_applicable", "No population in scope.", {"denominator": 0}
    value = numerator / denominator
    effective_at = float(rule.get("effective_at", 0.95))
    degraded_at = float(rule.get("degraded_at", 0.7))
    status = (
        "effective" if value >= effective_at else "degraded" if value >= degraded_at else "failing"
    )
    return (
        status,
        f"{rule.get('numerator')} / {rule.get('denominator')} = {numerator}/{denominator} "
        f"= {value:.1%} (effective at {effective_at:.0%}).",
        {"numerator": numerator, "denominator": denominator, "ratio": round(value, 4)},
    )


def _rule_freshness(session, control, rule, since) -> tuple[str, str, dict]:
    table = rule.get("table", "")
    max_age = int(rule.get("max_age_days", 30))
    model = _table(table)
    if model is None:
        return "not_implemented", f"Unknown evidence table '{table}'.", {}
    total = _count(session, table)
    if total == 0:
        return (
            "not_implemented",
            f"No records in '{table}' — the control has never run.{_hint([table])}",
            {},
        )
    recent = _count(session, table, utcnow() - dt.timedelta(days=max_age))
    if recent == 0:
        return (
            "failing",
            f"'{table}' has {total} record(s) but none within {max_age} days — "
            "the control has stopped operating.",
            {"total": total, "recent": 0, "max_age_days": max_age},
        )
    return (
        "effective",
        f"{recent} record(s) in '{table}' within {max_age} days.",
        {"total": total, "recent": recent, "max_age_days": max_age},
    )


def _rule_detector_coverage(session, control, rule, since) -> tuple[str, str, dict]:
    detectors = [rule.get("detector")] + list(rule.get("alternatives") or [])
    detectors = [d for d in detectors if d]
    total_decisions = int(
        session.scalar(
            select(func.count()).select_from(Decision).where(Decision.created_at >= since)
        )
        or 0
    )
    if total_decisions == 0:
        return "not_implemented", "No enforcement decisions in the window.", {}

    runs = list(
        session.scalars(
            select(DetectorRun).where(
                DetectorRun.detector_key.in_(detectors), DetectorRun.created_at >= since
            )
        )
    )
    covered_traces = {r.trace_id for r in runs if r.trace_id}
    decision_traces = {
        d.trace_id
        for d in session.scalars(select(Decision).where(Decision.created_at >= since))
        if d.trace_id
    }
    if not decision_traces:
        return "not_implemented", "No traced decisions in the window.", {}

    coverage = len(covered_traces & decision_traces) / len(decision_traces)
    effective_at = float(rule.get("effective_at", 0.99))
    degraded_at = float(rule.get("degraded_at", 0.9))
    status = (
        "effective"
        if coverage >= effective_at
        else "degraded"
        if coverage >= degraded_at
        else "failing"
    )
    healthy = sum(1 for r in runs if r.status == "ok")
    return (
        status,
        f"{detectors} ran on {coverage:.1%} of traced invocations "
        f"({len(covered_traces & decision_traces)}/{len(decision_traces)}); "
        f"{healthy}/{len(runs)} runs completed without timeout or error.",
        {
            "detectors": detectors,
            "coverage": round(coverage, 4),
            "runs": len(runs),
            "healthy_runs": healthy,
        },
    )


def _rule_decision_coverage(session, control, rule, since) -> tuple[str, str, dict]:
    surface = rule.get("surface", "tool_args")
    decisions = list(
        session.scalars(
            select(Decision).where(Decision.surface == surface, Decision.created_at >= since)
        )
    )
    if not decisions:
        return (
            "not_implemented",
            f"No '{surface}' decisions in the window — the control has not been exercised.",
            {},
        )
    with_policy = sum(1 for d in decisions if d.policy_version_id)
    coverage = with_policy / len(decisions)
    enforcing = sum(1 for d in decisions if d.mode == "enforce")
    effective_at = float(rule.get("effective_at", 0.99))
    degraded_at = float(rule.get("degraded_at", 0.9))
    status = (
        "effective"
        if coverage >= effective_at
        else "degraded"
        if coverage >= degraded_at
        else "failing"
    )
    # Observe mode is honest about itself: the control is operating, but it is not
    # preventing anything, and a report that hides that is misleading.
    if status == "effective" and enforcing == 0:
        status = "degraded"
        note = " All decisions were in observe mode — recorded but not enforced."
    else:
        note = ""
    return (
        status,
        f"{with_policy}/{len(decisions)} '{surface}' decisions bound to a policy version "
        f"({coverage:.1%}); {enforcing} enforced.{note}",
        {
            "decisions": len(decisions),
            "with_policy": with_policy,
            "enforcing": enforcing,
            "coverage": round(coverage, 4),
        },
    )


def _rule_degradation(session, control, rule, since) -> tuple[str, str, dict]:
    runs = list(session.scalars(select(DetectorRun).where(DetectorRun.created_at >= since)))
    if not runs:
        return "not_implemented", "No detector runs in the window.", {}
    degraded = [r for r in runs if r.status in ("timeout", "error", "skipped_budget")]
    ratio = len(degraded) / len(runs)
    max_ratio = float(rule.get("max_degraded_ratio", 0.01))
    warn_ratio = float(rule.get("degraded_ratio_warn", 0.05))
    status = "effective" if ratio <= max_ratio else "degraded" if ratio <= warn_ratio else "failing"
    by_status: dict[str, int] = {}
    for run in degraded:
        by_status[run.status] = by_status.get(run.status, 0) + 1
    latencies = sorted(r.duration_ms for r in runs)
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
    return (
        status,
        f"{len(degraded)}/{len(runs)} detector runs degraded ({ratio:.2%}, "
        f"budget {max_ratio:.2%}); p95 detector latency {p95:.1f}ms.",
        {
            "runs": len(runs),
            "degraded": len(degraded),
            "ratio": round(ratio, 4),
            "by_status": by_status,
            "p95_latency_ms": round(p95, 2),
        },
    )


def _rule_scorer_active(session, control, rule, since) -> tuple[str, str, dict]:
    scorer = rule.get("scorer", "")
    results = list(
        session.scalars(
            select(EvalResult).where(
                EvalResult.scorer_key == scorer, EvalResult.created_at >= since
            )
        )
    )
    if not results:
        return (
            "not_implemented",
            f"Scorer '{scorer}' has produced no results in the window.",
            {"scorer": scorer},
        )
    flagged = [r for r in results if not r.passed]
    return (
        "effective",
        f"Scorer '{scorer}' evaluated {len(results)} output(s); {len(flagged)} flagged.",
        {"scorer": scorer, "results": len(results), "flagged": len(flagged)},
    )


def _rule_chain_valid(session, control, rule, since) -> tuple[str, str, dict]:
    from agentfox.prove.audit.chain import chain_stats, verify_range

    stats = chain_stats(session)
    if stats["entries"] == 0:
        return "not_implemented", "The audit chain is empty.", stats
    result = verify_range(session)
    if not result.valid:
        first = result.first_break
        return (
            "failing",
            "Audit chain verification FAILED"
            + (f" at seq {first.seq}: {first.detail}" if first else "")
            + ". Every compliance claim depending on this log is void until resolved.",
            {**stats, "verification": result.to_json()},
        )
    return (
        "effective",
        f"Audit chain intact: {result.entries_checked} entries verified "
        f"(seq {result.first_seq}..{result.last_seq}), "
        f"{result.checkpoints_checked} checkpoint(s) validated.",
        {**stats, "verification": result.to_json()},
    )


def _rule_capability_active(session, control, rule, since) -> tuple[str, str, dict]:
    required = rule.get("requires") or control.evidence_sources or []
    optional = bool(rule.get("optional", False))
    counts = {name: _count(session, name) for name in required}
    if all(n == 0 for n in counts.values()):
        return (
            "not_applicable" if optional else "not_implemented",
            f"No records in {sorted(counts)}; the capability has not been exercised."
            + (" Marked not applicable — this capability is optional." if optional else ""),
            {"counts": counts},
        )
    return "effective", f"Capability exercised: {counts}.", {"counts": counts}


_RULE_HANDLERS = {
    "presence": _rule_presence,
    "ratio": _rule_ratio,
    "freshness": _rule_freshness,
    "detector_coverage": _rule_detector_coverage,
    "decision_coverage": _rule_decision_coverage,
    "degradation": _rule_degradation,
    "scorer_active": _rule_scorer_active,
    "chain_valid": _rule_chain_valid,
    "capability_active": _rule_capability_active,
}

#: Every ``status_rule.kind`` that ``evaluate_control`` understands. An unknown kind
#: silently falls back to ``presence``, which is why ``agentfox admin catalog validate``
#: checks the catalog against this set.
RULE_KINDS = frozenset(_RULE_HANDLERS)


# ---------------------------------------------------------------------------
# Measures for `ratio` rules
# ---------------------------------------------------------------------------


def _measure(session: Session, name: str) -> int:
    if name == "total_agents":
        return int(
            session.scalar(select(func.count()).select_from(Agent).where(Agent.status != "retired"))
            or 0
        )
    if name == "registered_agents":
        return int(
            session.scalar(
                select(func.count())
                .select_from(Agent)
                .where(Agent.registered.is_(True), Agent.status != "retired")
            )
            or 0
        )
    if name == "owned_agents":
        return sum(
            1 for a in session.scalars(select(Agent).where(Agent.status != "retired")) if a.is_owned
        )
    if name == "agents_with_identity":
        with_identity = {i.agent_id for i in session.scalars(select(Identity)) if i.agent_id}
        return sum(
            1
            for a in session.scalars(select(Agent).where(Agent.status != "retired"))
            if a.id in with_identity
        )
    if name == "assessed_agents":
        assessed = {r.agent_id for r in session.scalars(select(RiskAssessment))}
        return sum(
            1
            for a in session.scalars(select(Agent).where(Agent.status != "retired"))
            if a.id in assessed or a.slug in assessed
        )
    return 0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def compute_all(
    session: Session, window_days: int = 30, scope: dict[str, Any] | None = None
) -> list[ControlStatus]:
    return [
        evaluate_control(session, control, window_days=window_days, scope=scope)
        for control in session.scalars(select(Control).order_by(Control.key))
    ]


#: How old the newest control status may be before a reader-facing view recomputes.
COMPUTE_STALE_AFTER = dt.timedelta(hours=24)


def ensure_compliance_computed(session: Session, window_days: int = 30) -> bool:
    """Sync the catalog and compute control status if nobody has, or not recently.

    The board said "0% of 43 controls" on any deployment that had simply never run
    `agentfox admin catalog compute` — a false statement about the controls, made on
    the screen an executive reads. Views a person reads call this first. Returns
    whether anything was computed.
    """
    from agentfox.prove.compliance.catalog import sync_catalog

    if session.scalar(select(Control.id).limit(1)) is None:
        sync_catalog(session)
    latest = session.scalar(
        select(ControlStatus.computed_at).order_by(ControlStatus.computed_at.desc()).limit(1)
    )
    if latest is not None:
        latest = latest if latest.tzinfo else latest.replace(tzinfo=dt.UTC)
        if utcnow() - latest < COMPUTE_STALE_AFTER:
            return False
    compute_all(session, window_days)
    session.flush()
    return True


def latest_statuses(session: Session) -> dict[str, ControlStatus]:
    out: dict[str, ControlStatus] = {}
    for status in session.scalars(select(ControlStatus).order_by(ControlStatus.computed_at)):
        out[status.control_key] = status  # later rows overwrite earlier ones
    return out


def posture(session: Session, framework: str | None = None) -> dict[str, Any]:
    """Aggregate control posture, optionally scoped to one framework.

    Scoped to every control in the catalog, not just the ones with a computed
    ``ControlStatus`` row — a freshly-synced catalog has none, and counting only
    computed rows made a 41-control catalog report 0 controls of every status,
    itself included, with no visible account of where the other 41 went. A
    control with no status row is ``not_computed`` (matching ``list_controls``'s
    own default), and is counted as such rather than silently dropped.
    """
    from agentfox.core.models import FrameworkMapping

    statuses = latest_statuses(session)
    keys = set(session.scalars(select(Control.key)))
    if framework:
        keys &= {
            m.control_key
            for m in session.scalars(
                select(FrameworkMapping).where(FrameworkMapping.framework == framework)
            )
        }

    counts = dict.fromkeys((*STATUSES, "not_computed"), 0)
    for key in keys:
        status = statuses[key].status if key in statuses else "not_computed"
        counts[status] = counts.get(status, 0) + 1

    assessed = sum(counts[s] for s in ("effective", "degraded", "failing"))
    return {
        "framework": framework,
        "controls": len(keys),
        "counts": counts,
        "effectiveness": round(counts["effective"] / assessed, 4) if assessed else None,
        "failing_controls": sorted(
            k for k in keys if k in statuses and statuses[k].status == "failing"
        ),
        "degraded_controls": sorted(
            k for k in keys if k in statuses and statuses[k].status == "degraded"
        ),
        "not_implemented": sorted(
            k for k in keys if k in statuses and statuses[k].status == "not_implemented"
        ),
        "computed_at": max((statuses[k].computed_at for k in keys if k in statuses), default=None),
    }
