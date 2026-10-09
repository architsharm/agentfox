"""Where each guardrail sits for one agent: the map the dashboard draws.

A request passes through steps — the user's message comes in, the agent calls tools,
their results come back, the agent replies — and different guardrails watch each
step. This works out, for one agent, which ones: the rules in force for it (from every
level of the hierarchy, with each rule's own mode), the detectors that run on each
step, and for every tool the agent may call, its permission, risk, limits and the
rules aimed at it. Recent traffic is attached so a step shows how often it stopped
something.

Placement of a rule:

* it names surfaces (``when.surface``) → those steps;
* it is about tool calls (tool, impact, permission, arguments, the action itself) →
  the tool-call step, or a specific tool when it names it or its impact;
* it is a detection with no surface → every step that carries content;
* budgets, loops, degraded detectors → "every step".
"""

from __future__ import annotations

import datetime as dt
import fnmatch
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection.detector_settings import enabled_for
from agentfox.core.models import (
    Agent,
    BusinessRule,
    Capability,
    Decision,
    Identity,
    LineageEdge,
    Tool,
)
from agentfox.platform.policy import Rule, effective_for

WINDOW_DAYS = 7


@dataclass(frozen=True)
class Stage:
    key: str
    title: str
    surfaces: tuple[str, ...]
    #: Shown even when nothing is configured there: the steps every agent has.
    core: bool = True


STAGES: tuple[Stage, ...] = (
    Stage("input", "User message", ("input",)),
    Stage(
        "context", "Documents & memory", ("retrieved", "memory_write", "agent_message"), core=False
    ),
    Stage("tool_call", "Tool calls", ("tool_args",)),
    Stage("tool_result", "Tool results", ("tool_result",)),
    Stage("output", "Agent reply", ("output",)),
    Stage("completion", "Finishing", ("completion",), core=False),
)
CONTENT_STAGES = ("input", "context", "tool_result", "output")
_TOOL_FIELDS = (
    "tool",
    "tool_impact",
    "tool_known",
    "capability",
    "argument",
    "taint_exceeds",
    "action_operation",
    "blast_radius_at_least",
    "action_reversible",
    "action_risk",
    "intent_declared",
)
_EVERYWHERE_FIELDS = ("budget_exceeded", "loop_detected", "detector_degraded")


def _stages_for(rule: Rule) -> list[str]:
    when = rule.when
    if when.surface:
        return [s.key for s in STAGES if set(s.surfaces) & set(when.surface)]
    if when.completion_requires:
        return ["completion"]
    if any(getattr(when, f) not in (None, []) for f in _TOOL_FIELDS):
        return ["tool_call"]
    if any(getattr(when, f) is not None for f in _EVERYWHERE_FIELDS):
        return ["everywhere"]
    if when.detection is not None:
        return list(CONTENT_STAGES)
    return ["everywhere"]


def _matches_tool(rule: Rule, tool_key: str, impact: str | None) -> bool:
    when = rule.when
    if when.tool and fnmatch.fnmatch(tool_key, when.tool):
        return True
    return bool(when.tool_impact and impact and impact in when.tool_impact)


def _rule_json(rule: Rule, mode: str, level: str, hits: Counter) -> dict[str, Any]:
    return {
        "id": rule.id,
        "description": rule.description,
        "effect": rule.effect,
        "mode": mode,
        "level": level,
        "message": rule.message,
        "hits": hits.get(rule.id, 0),
    }


def agent_map(session: Session, slug: str) -> dict[str, Any]:
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=WINDOW_DAYS)

    # --- traffic -------------------------------------------------------------
    decisions = (
        list(
            session.scalars(
                select(Decision).where(Decision.agent_id == agent.id, Decision.created_at >= since)
            )
        )
        if agent
        else []
    )
    stage_of_surface = {s: st.key for st in STAGES for s in st.surfaces}
    stage_stats: dict[str, Counter] = defaultdict(Counter)
    tool_stats: dict[str, Counter] = defaultdict(Counter)
    hits: Counter = Counter()
    for d in decisions:
        outcome = {"block": "blocked", "escalate": "held"}.get(d.verdict) or (
            "masked" if d.verdict in ("redact", "mask", "tokenize") else "allowed"
        )
        stage = stage_of_surface.get(d.surface, "input")
        stage_stats[stage]["total"] += 1
        stage_stats[stage][outcome] += 1
        if d.tool_key:
            tool_stats[d.tool_key]["total"] += 1
            tool_stats[d.tool_key][outcome] += 1
        for r in d.rules_fired_json or []:
            if isinstance(r, dict) and r.get("rule_id"):
                hits[r["rule_id"]] += 1

    # --- rules in force ------------------------------------------------------
    effective = effective_for(session, slug)
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tool_rules: list[tuple[Rule, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for layer in effective.applicable:
        mode = layer.document.mode
        for rule in effective.rules_in_force(layer):
            if not rule.enabled or (rule.id, mode) in seen:
                continue
            seen.add((rule.id, mode))
            entry = _rule_json(rule, mode, layer.level, hits)
            stages = _stages_for(rule)
            if stages == ["tool_call"] and (rule.when.tool or rule.when.tool_impact):
                tool_rules.append((rule, entry))
                continue
            for stage in stages:
                by_stage[stage].append(entry)

    # --- detectors -----------------------------------------------------------
    detectors = all_detectors()
    running = enabled_for(session)
    detectors_by_stage: dict[str, list[str]] = defaultdict(list)
    for key in sorted(running):
        detector = detectors.get(key)
        if detector is None or not detector.available():
            continue
        for stage in STAGES:
            if set(stage.surfaces) & set(detector.surfaces):
                detectors_by_stage[stage.key].append(key)

    # --- tools ---------------------------------------------------------------
    grants: list[Capability] = []
    if agent:
        identity = session.scalar(select(Identity).where(Identity.agent_id == agent.id))
        if identity is not None:
            grants = list(identity.capabilities)
    registry = {t.key: t for t in session.scalars(select(Tool))}
    ladders = list(
        session.scalars(
            select(BusinessRule).where(
                BusinessRule.enabled.is_(True), BusinessRule.tool.is_not(None)
            )
        )
    )
    # Red-team grants are for simulated tools, never the agent's own.
    granted = {
        g.tool_key
        for g in grants
        if "*" not in g.tool_key and not g.tool_key.startswith("redteam.")
    }
    in_code = set(agent.declared_tools or []) if agent else set()
    seen_keys = {k for k in tool_stats if not k.startswith("redteam.")}
    keys = granted | in_code | seen_keys
    tools = []
    for key in sorted(keys):
        grant = next((g for g in grants if fnmatch.fnmatch(key, g.tool_key)), None)
        tool = registry.get(key)
        impact = tool.impact if tool else None
        tools.append(
            {
                "key": key,
                "name": (tool.name if tool else "") or key,
                "impact": impact,
                "permission": "not_granted"
                if grant is None
                else "ask"
                if grant.requires_approval
                else "allowed",
                "limits": grant.constraints_json if grant else {},
                "rules": [e for r, e in tool_rules if _matches_tool(r, key, impact)],
                "ladders": [
                    {
                        "key": b.key,
                        "mode": b.mode,
                        "field": b.field_path,
                        "name": (b.definition_json or {}).get("name") or b.key,
                    }
                    for b in ladders
                    if (b.agent_id in (None, agent.id if agent else None))
                    and fnmatch.fnmatch(key, b.tool or "")
                ],
                "stats": dict(tool_stats.get(key, Counter())),
                # Where this tool is known from: the agent's code (a repo scan or a
                # registration), a grant, or calls actually seen.
                "sources": [
                    name
                    for name, has in (
                        ("code", key in in_code),
                        ("granted", grant is not None),
                        ("seen", key in seen_keys),
                    )
                    if has
                ],
            }
        )

    # --- sub-agents ----------------------------------------------------------
    subagents = []
    if agent:
        for edge in session.scalars(
            select(LineageEdge).where(
                LineageEdge.src_id == slug,
                LineageEdge.dst_type == "agent",
                LineageEdge.relation == "delegates_to",
            )
        ):
            subagents.append({"slug": edge.dst_id, "calls": edge.observed_count})

    stages = [
        {
            "key": s.key,
            "title": s.title,
            "surfaces": list(s.surfaces),
            "detectors": detectors_by_stage.get(s.key, []),
            "rules": by_stage.get(s.key, []),
            "stats": dict(stage_stats.get(s.key, Counter())),
        }
        for s in STAGES
        if s.core or by_stage.get(s.key) or stage_stats.get(s.key)
    ]
    return {
        "agent": {
            "slug": slug,
            "name": (agent.name if agent else "") or slug,
            "known": agent is not None,
        },
        "window_days": WINDOW_DAYS,
        "stages": stages,
        "everywhere": by_stage.get("everywhere", []),
        "tools": tools,
        "subagents": subagents,
    }
