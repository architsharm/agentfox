"""Simulate a business rule on recorded traffic before it starts blocking.

The same gate a policy pack has (`platform/policy/simulate.py`): switching a rule to
enforce changes what production traffic is held, so it is replayed over recent calls
first, the result is recorded, and the `/mode` route refuses ``enforce`` without a
recorded simulation of exactly the rule being enforced. A business rule used to go
straight to enforcing on one click, with nothing to say what it would hold.

A ladder only reads the call's arguments, which every tool-call decision records
(``taint_summary_json.arguments_snapshot``), so the replay is exact: the band each
recorded call would have landed in today.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.business.ladder import Ladder
from agentfox.capabilities.business.ladder import evaluate as evaluate_ladder
from agentfox.core.models import BusinessRule, Decision, SimulationRun

#: How far back "Start blocking" replays, like a pack's simulation.
SIMULATE_DAYS = 7

#: Outcomes that stop a call from running on its own.
_STOPS = ("block", "escalate", "verify")


def fingerprint(rule: BusinessRule) -> str:
    """What a simulation tested: the bands and what they read, not the mode."""
    definition = dict(rule.definition_json or {})
    return json.dumps(
        {
            "tool": rule.tool,
            "agent": rule.agent_id,
            "field": definition.get("field") or definition.get("field_path"),
            "unit": definition.get("unit"),
            "bands": definition.get("bands"),
        },
        sort_keys=True,
        default=str,
    )


def simulate_rule(
    session: Session,
    rule: BusinessRule,
    *,
    since_days: int = SIMULATE_DAYS,
    limit: int = 2000,
    run_by: str = "system",
) -> dict[str, Any]:
    """Replay recent tool calls through ``rule`` as if it enforced, and record it.

    ``would_stop`` counts calls that went through and that the rule would now hold
    (or block); ``already_stopped`` those something else already held or blocked."""
    ladder = Ladder.model_validate(
        {k: v for k, v in dict(rule.definition_json or {}).items() if k != "kind"}
    )
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days)
    query = (
        select(Decision)
        .where(Decision.surface == "tool_args", Decision.created_at >= since)
        .order_by(Decision.created_at.desc())
        .limit(limit)
    )
    if rule.tool:
        query = query.where(Decision.tool_key == rule.tool)
    if rule.agent_id:
        query = query.where(Decision.agent_id == rule.agent_id)

    replayed = 0
    runs: set[str] = set()
    would_stop: list[dict[str, Any]] = []
    already = 0
    for decision in session.scalars(query):
        arguments = dict((decision.taint_summary_json or {}).get("arguments_snapshot") or {})
        if not arguments:
            continue  # the ladder check only runs on a call with arguments
        replayed += 1
        if decision.trace_id:
            runs.add(decision.trace_id)
        outcome = evaluate_ladder(ladder, {"arguments": arguments, "tool": decision.tool_key})
        if outcome.outcome not in _STOPS:
            continue
        if (decision.verdict or "allow") in ("block", "escalate"):
            already += 1
            continue
        would_stop.append(
            {
                "decision_id": decision.id,
                "trace_id": decision.trace_id,
                "tool": decision.tool_key,
                "now": outcome.outcome,
                "value": outcome.value,
                "reason": outcome.reason,
            }
        )
    result = {
        "rule": rule.key,
        "since_days": since_days,
        "replayed": replayed,
        "runs_replayed": len(runs),
        "would_stop": would_stop[:50],
        "already_stopped": already,
        "counts": {"would_stop": len(would_stop), "already_stopped": already},
        "runs_own_would_stop": len({r["trace_id"] or r["decision_id"] for r in would_stop}),
    }
    run = SimulationRun(
        policy_id=None,
        candidate_body=fingerprint(rule),
        scope_json={
            "business_rule": rule.key,
            "fingerprint": fingerprint(rule),
            "since_days": since_days,
        },
        replayed_count=replayed,
        diff_json=result,
        run_by=run_by,
    )
    session.add(run)
    session.flush()
    result["simulation_id"] = run.id
    return result


def simulation_for_rule(session: Session, rule: BusinessRule) -> SimulationRun | None:
    """The newest recorded simulation of exactly this rule's bands, if any."""
    target = fingerprint(rule)
    for run in session.scalars(
        select(SimulationRun)
        .where(SimulationRun.policy_id.is_(None))
        .order_by(SimulationRun.created_at.desc())
        .limit(500)
    ):
        scope = run.scope_json or {}
        if scope.get("business_rule") == rule.key and scope.get("fingerprint") == target:
            return run
    return None
