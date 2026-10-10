"""Tool-call paths an agent takes in production, and the ones it never took before.

Evaluation suites are written from the paths a team imagined. Production finds the
others: a refund that now looks up the order twice, a new tool slotted between two
old ones, a path that skips the check it used to make. Each is a case the suite does
not cover, and the only place it shows up is the telemetry.

A *path* is the ordered tools one run of an agent called. Every tool decision records
the tools called before it in the same session (``taint_summary.prior_tools``), so a
decision's path is those plus its own tool; a run (a session, or a trace when there is
no session) takes its longest. Repeats in a row collapse to one: calling the same
lookup three times is the same path.

*New* means first seen inside the window and never in the baseline before it. A new
*step* is a pair of consecutive tools never seen together before, which catches a new
tool slotted into an old path without the whole path being unfamiliar.

A path is *covered* when a test case expects it (``EvalCase.expected_json["tools"]``,
what the tool-trajectory scorer checks).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, Decision, EvalCase, EvalSuite, Finding, Trace, utcnow
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.findings import OPEN, raise_finding, resolve_finding

#: Longest path kept; a run that calls more tools than this is cut, oldest first.
MAX_PATH = 12

#: Finding type for a new path no test expects.
FINDING_TYPE = "new_tool_path"

#: Most new-path findings one scan raises per agent: past this the paths are noise from
#: a changed agent, and the tool-paths screen lists them all anyway.
MAX_FINDINGS_PER_AGENT = 10


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _collapse(tools: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for tool in tools:
        if tool and (not out or out[-1] != tool):
            out.append(tool)
    return tuple(out[-MAX_PATH:])


@dataclass
class PathStats:
    path: tuple[str, ...]
    runs: int = 0
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None
    sample_trace_id: str | None = None
    stopped: int = 0
    in_window: int = 0
    new_steps: list[tuple[str, str]] = field(default_factory=list)

    def to_json(self, covered: bool, new: bool) -> dict[str, Any]:
        return {
            "path": list(self.path),
            "runs": self.in_window,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "sample_trace_id": self.sample_trace_id,
            "stopped": self.stopped,
            "new": new,
            "new_steps": [list(s) for s in self.new_steps],
            "covered": covered,
        }


def _runs(
    session: Session, agent_id: str, since: dt.datetime
) -> list[tuple[tuple[str, ...], dt.datetime, str | None, bool]]:
    """One (path, when, sample trace, stopped) per run since ``since``."""
    rows = session.execute(
        select(Decision, Trace.session_id)
        .outerjoin(Trace, Trace.id == Decision.trace_id)
        .where(
            Decision.agent_id == agent_id,
            Decision.tool_key.is_not(None),
            Decision.created_at >= since,
        )
        .order_by(Decision.created_at)
    ).all()
    best: dict[str, tuple[tuple[str, ...], dt.datetime, str | None, bool]] = {}
    for decision, session_id in rows:
        if (decision.tool_key or "").startswith("redteam."):
            continue  # a probe's simulated tool is a test, not a path the agent took
        prior = list((decision.taint_summary_json or {}).get("prior_tools") or [])
        path = _collapse([*prior, decision.tool_key])
        key = session_id or decision.trace_id or decision.id
        stopped = decision.verdict in ("block", "escalate")
        when = _aware(decision.created_at)
        current = best.get(key)
        if current is None:
            best[key] = (path, when, decision.trace_id, stopped)
            continue
        # The run's path is the longest one any of its decisions saw.
        longer = path if len(path) >= len(current[0]) else current[0]
        best[key] = (longer, when, decision.trace_id or current[2], current[3] or stopped)
    return list(best.values())


def covered_paths(session: Session) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for expected in session.scalars(select(EvalCase.expected_json)):
        tools = (expected or {}).get("tools")
        if isinstance(tools, list) and tools:
            out.add(_collapse([str(t) for t in tools]))
    return out


def tool_paths(
    session: Session,
    agent_id: str,
    *,
    window_days: int = 7,
    baseline_days: int = 30,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Every path in the window, newest first-seen first, with what is new about it."""
    now = now or utcnow()
    window_start = now - dt.timedelta(days=window_days)
    baseline_start = window_start - dt.timedelta(days=baseline_days)

    stats: dict[tuple[str, ...], PathStats] = {}
    seen_steps_before: set[tuple[str, str]] = set()
    window_runs = []
    for path, when, trace_id, stopped in _runs(session, agent_id, baseline_start):
        s = stats.setdefault(path, PathStats(path=path))
        s.runs += 1
        s.first_seen = min(s.first_seen, when) if s.first_seen else when
        if s.last_seen is None or when >= s.last_seen:
            s.last_seen, s.sample_trace_id = when, trace_id or s.sample_trace_id
        if when >= window_start:
            s.in_window += 1
            s.stopped += 1 if stopped else 0
            window_runs.append(path)
        else:
            seen_steps_before.update(zip(path, path[1:], strict=False))

    covered = covered_paths(session)
    paths = []
    new_steps: dict[tuple[str, str], int] = {}
    for s in stats.values():
        if not s.in_window:
            continue
        is_new = s.first_seen is not None and s.first_seen >= window_start
        s.new_steps = [
            step for step in zip(s.path, s.path[1:], strict=False) if step not in seen_steps_before
        ]
        for step in s.new_steps:
            new_steps[step] = new_steps.get(step, 0) + s.in_window
        paths.append(s.to_json(covered=s.path in covered, new=is_new))
    paths.sort(key=lambda p: (not p["new"], -p["runs"]))
    return {
        "window_days": window_days,
        "baseline_days": baseline_days,
        "runs": len(window_runs),
        "paths": paths,
        "new_paths": sum(1 for p in paths if p["new"]),
        "uncovered_new": sum(1 for p in paths if p["new"] and not p["covered"]),
        "new_steps": [
            {"from": a, "to": b, "runs": n}
            for (a, b), n in sorted(new_steps.items(), key=lambda kv: -kv[1])
        ],
    }


def promote_path(
    session: Session,
    suite: EvalSuite,
    *,
    trace_id: str | None,
    path: list[str],
    actor: str,
) -> EvalCase:
    """A regression case that expects this tool path, from the run that took it.

    One case per (suite, path): adding the same path again returns the case it made.
    The prompt is what the run was asked (its summary), so the suite can replay it and
    the tool-trajectory scorer can check the agent took the same path.
    """
    wanted = list(_collapse([str(t) for t in path]))
    if not wanted:
        raise ValueError("a path needs at least one tool")
    for case in session.scalars(select(EvalCase).where(EvalCase.suite_id == suite.id)):
        if list(_collapse([str(t) for t in (case.expected_json or {}).get("tools") or []])) == (
            wanted
        ):
            return case
    trace = session.get(Trace, trace_id) if trace_id else None
    prompt = (trace.summary or trace.intent or "") if trace else ""
    case = EvalCase(
        suite_id=suite.id,
        input_json={"prompt": prompt},
        expected_json={"tools": wanted, "goal": (trace.intent if trace else "") or ""},
        context_json={},
        labels=["from-production", "tool-path"],
        split="regression",
        source_trace_id=trace_id,
    )
    session.add(case)
    session.flush()
    chain.append(
        session,
        "eval.path_promoted",
        actor_type="user",
        actor_id=actor,
        subject_type="eval_case",
        subject_id=case.id,
        payload={"suite": suite.key, "tools": wanted, "trace_id": trace_id},
    )
    _close_covered(session, {tuple(wanted)})
    return case


def _close_covered(session: Session, covered: set[tuple[str, ...]]) -> int:
    """Resolve the open new-path findings whose path a test now expects."""
    closed = 0
    for finding in session.scalars(
        select(Finding).where(Finding.type == FINDING_TYPE, Finding.status == OPEN)
    ).all():
        path = _collapse([str(t) for t in (finding.evidence_json or {}).get("path") or []])
        if path and path in covered:
            resolve_finding(
                session,
                finding,
                actor="agentfox.paths",
                note="A test now expects this path",
                automated=True,
            )
            closed += 1
    return closed


def path_label(path: list[str] | tuple[str, ...]) -> str:
    return " \u2192 ".join(path)


def scan_new_paths(
    session: Session,
    *,
    window_days: int = 1,
    baseline_days: int = 30,
    agents: list[str] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Raise a finding for each new path no test expects; close the ones a test now does.

    One finding per (agent, path), so the same path seen again is another occurrence,
    not another issue. Low severity: a new path is something to look at and usually
    to add to the tests, not a failure.
    """
    _close_covered(session, covered_paths(session))

    query = select(Agent).order_by(Agent.slug)
    if agents:
        query = query.where(Agent.slug.in_(agents))
    raised = 0
    by_agent: dict[str, int] = {}
    for agent in session.scalars(query).all():
        report = tool_paths(
            session, agent.id, window_days=window_days, baseline_days=baseline_days, now=now
        )
        fresh = [p for p in report["paths"] if p["new"] and not p["covered"]]
        for p in fresh[:MAX_FINDINGS_PER_AGENT]:
            steps = ", ".join(path_label(s) for s in p["new_steps"])
            raise_finding(
                session,
                type=FINDING_TYPE,
                title=f"{agent.slug} took a new tool path: {path_label(p['path'])}"[:300],
                severity="low",
                subject_type="agent",
                subject_id=agent.slug,
                evidence={
                    "agent": agent.slug,
                    "path": p["path"],
                    "runs": p["runs"],
                    "first_seen": p["first_seen"],
                    "trace_id": p["sample_trace_id"],
                    "new_steps": p["new_steps"],
                    "stopped": p["stopped"],
                    "detail": (
                        "No test expects this sequence of tool calls."
                        + (f" New steps: {steps}." if steps else "")
                    ),
                },
                fingerprint_parts=tuple(p["path"]),
            )
        if fresh:
            by_agent[agent.slug] = len(fresh)
            raised += min(len(fresh), MAX_FINDINGS_PER_AGENT)
    return {"window_days": window_days, "new_uncovered": by_agent, "findings_raised": raised}


__all__ = [
    "FINDING_TYPE",
    "MAX_PATH",
    "covered_paths",
    "path_label",
    "promote_path",
    "scan_new_paths",
    "tool_paths",
]
