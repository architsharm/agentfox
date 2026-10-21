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

Lines and views. The agent's line to its LLM (``prompt``: "To the LLM", ``response``:
"From the LLM") is a second view of steps the map already has: what goes to the LLM
is the user's message, documents and tool results; what comes back is the reply.
Drawn as lines of their own, they must not count anything twice:

* every decision counts once, on the stage that *owns* its surface (``Stage.owns``);
  ``stats`` on all stages add up to the decisions in the window (``decisions``). A
  view stage owns only what no other stage shows (``reasoning`` on "From the LLM"),
  and also carries ``lineStats``: everything that crossed that line, overlapping
  other stages, never to be added to them (``derived: true`` says so);
* a rule appears on a view stage only as a copy flagged ``sharedWith`` (the stages
  it belongs to), not as another rule; ``detectorsSharedWith`` does the same for
  checks.
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
from agentfox.capabilities.detection.catalog import (
    Feed,
    can_fire,
    checks_for_rule,
    feeds_for,
    rule_finds,
    rule_surfaces,
    source_of,
)
from agentfox.capabilities.detection.detector_settings import enabled_for
from agentfox.capabilities.protection import layer_key
from agentfox.capabilities.protection.scope import agent_changes
from agentfox.core.models import (
    Agent,
    BusinessRule,
    Capability,
    CustomRule,
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
    #: A second view of other stages' surfaces (the LLM line). It owns only the
    #: surfaces in ``only``; everything else on it is counted where it belongs.
    derived: bool = False
    #: For a derived stage, the surfaces no other stage shows.
    only: tuple[str, ...] = ()

    @property
    def owns(self) -> tuple[str, ...]:
        """The surfaces whose decisions count here, and nowhere else."""
        return self.only if self.derived else self.surfaces


STAGES: tuple[Stage, ...] = (
    Stage("input", "User message", ("input",)),
    Stage(
        "context", "Documents & memory", ("retrieved", "memory_write", "agent_message"), core=False
    ),
    Stage("tool_call", "Tool calls", ("tool_args",)),
    Stage("tool_result", "Tool results", ("tool_result",)),
    Stage("output", "Agent reply", ("output",)),
    # The agent's line to its LLM, both ways: a view of the steps above (see the
    # module docstring). Everything sent to the LLM is checked before the call, each
    # part on the surface it came in on (the user's message as input, documents as
    # retrieved, tool results as tool_result). What the agent writes to memory is not
    # sent to the LLM. What the LLM answers is checked after the call as output, and
    # its reasoning, where a framework reports it: reasoning is shown nowhere else, so
    # it belongs to this line.
    Stage(
        "prompt",
        "To the LLM",
        ("input", "retrieved", "agent_message", "tool_result"),
        derived=True,
    ),
    Stage("response", "From the LLM", ("output", "reasoning"), derived=True, only=("reasoning",)),
    # The agent saying it is done ("your refund is processed"), checked against what
    # the caller observed (`completion_requires`). Not a line to the LLM.
    Stage("completion", "Done check", ("completion",), core=False),
)
CONTENT_STAGES = ("input", "context", "tool_result", "output", "prompt", "response")
STAGE_BY_KEY = {s.key: s for s in STAGES}
#: The one stage a decision on each surface counts on.
OWNER_OF_SURFACE = {surface: s.key for s in STAGES for surface in s.owns}
#: Where a decision on a surface no stage shows (``tool_call``, ``mcp``) counts.
DEFAULT_STAGE = "input"
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


def _home_stages(rule: Rule, stages: list[str]) -> list[str]:
    """The stages a rule belongs to; on the rest of ``stages`` it is a shared copy.

    A rule naming surfaces belongs to the stages that own one of them; one naming
    none, to every stage it is on that is not a view of others. A rule only a view
    stage can show (on ``reasoning``) belongs there.
    """
    surfaces = rule.when.surface
    if surfaces:
        home = [
            k for k in stages if k in STAGE_BY_KEY and set(STAGE_BY_KEY[k].owns) & set(surfaces)
        ]
    else:
        home = [k for k in stages if k not in STAGE_BY_KEY or not STAGE_BY_KEY[k].derived]
    return home or stages


def _matches_tool(rule: Rule, tool_key: str, impact: str | None) -> bool:
    when = rule.when
    if when.tool and fnmatch.fnmatch(tool_key, when.tool):
        return True
    return bool(when.tool_impact and impact and impact in when.tool_impact)


def _tool_sources(
    session: Session, agent: Agent | None, called: set[str]
) -> tuple[list[Capability], set[str], set[str]]:
    """``(grants, in_code, seen)``: where an agent's tools are known from.

    Its identity's grants, the tools its code defines (a repo scan or a registration),
    and the tools it was seen calling. Red-team tools are simulated, never its own.
    """
    grants: list[Capability] = []
    if agent:
        identity = session.scalar(select(Identity).where(Identity.agent_id == agent.id))
        if identity is not None:
            grants = list(identity.capabilities)
    in_code = set(agent.declared_tools or []) if agent else set()
    seen = {k for k in called if not k.startswith("redteam.")}
    return grants, in_code, seen


def _granted_keys(grants: list[Capability]) -> set[str]:
    """Named grants. A wildcard grants a pattern, not a tool to list."""
    return {
        g.tool_key
        for g in grants
        if "*" not in g.tool_key and not g.tool_key.startswith("redteam.")
    }


def _grant_for(grants: list[Capability], key: str) -> Capability | None:
    """The tool's own grant first, then any pattern that covers it."""
    return next((g for g in grants if g.tool_key == key), None) or next(
        (g for g in grants if fnmatch.fnmatch(key, g.tool_key)), None
    )


def _permission(grant: Capability | None) -> str:
    if grant is None:
        return "not_granted"
    return "ask" if grant.requires_approval else "allowed"


def _sources(key: str, grant: Capability | None, in_code: set[str], seen: set[str]) -> list[str]:
    return [
        name
        for name, has in (
            ("code", key in in_code),
            ("granted", grant is not None),
            ("seen", key in seen),
        )
        if has
    ]


def agent_tools(session: Session, slug: str) -> dict[str, Any]:
    """The tools one agent can be tested with: the same set its guardrail map shows.

    Each carries where it is known from and a blank argument skeleton to fill in.
    """
    from agentfox.platform.registry.service import argument_skeleton

    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=WINDOW_DAYS)
    called: set[str] = set()
    if agent:
        called = {
            k
            for k in session.scalars(
                select(Decision.tool_key)
                .where(
                    Decision.agent_id == agent.id,
                    Decision.created_at >= since,
                    Decision.tool_key.is_not(None),
                )
                .distinct()
            )
            if k
        }
    grants, in_code, seen = _tool_sources(session, agent, called)
    registry = {t.key: t for t in session.scalars(select(Tool))}
    out = []
    for key in sorted(_granted_keys(grants) | in_code | seen):
        grant = _grant_for(grants, key)
        tool = registry.get(key)
        out.append(
            {
                "key": key,
                "name": (tool.name if tool else "") or key,
                "impact": tool.impact if tool else None,
                "permission": _permission(grant),
                "sources": _sources(key, grant, in_code, seen),
                "arguments": argument_skeleton(session, key),
            }
        )
    return {"agent": slug, "window_days": WINDOW_DAYS, "tools": out}


_IMPACT_WORDS = {
    "read": "read-only",
    "write": "writing",
    "high_impact": "high-impact",
    "irreversible": "irreversible",
}
_CAPABILITY_WORDS = {
    "denied": "tools this agent may not use",
    "requires_approval": "tools that need approval",
    "granted": "tools this agent may use",
    "constraint_violated": "calls outside a tool's allowed limits",
}


def rule_kind(rule: Rule) -> str:
    """``content``: a check found something (fed by regex, ML and LLM checks);
    ``action``: about a tool call itself; ``run``: about the run as a whole."""
    when = rule.when
    if when.detection is not None:
        return "content"
    if any(getattr(when, f) not in (None, []) for f in _TOOL_FIELDS):
        return "action"
    return "run"


def rule_about(rule: Rule) -> str:
    """What a rule that isn't about content looks at, in a few plain words."""
    w = rule.when
    parts: list[str] = []
    if w.tool:
        parts.append(f"tool {w.tool}")
    if w.tool_impact:
        parts.append(" or ".join(_IMPACT_WORDS.get(i, i) for i in w.tool_impact) + " tools")
    if w.tool_known is False:
        parts.append("tools the code never declared")
    if w.capability:
        parts.append(_CAPABILITY_WORDS.get(w.capability, f"capability {w.capability}"))
    if w.argument:
        parts.append(f"argument {w.argument.path}")
    if w.taint_exceeds:
        parts.append(f"arguments that came from {w.taint_exceeds.replace('_', ' ')} or worse")
    if w.action_operation:
        parts.append(" or ".join(w.action_operation) + " actions")
    if w.action_risk:
        parts.append(
            "risky actions: " + w.action_risk.replace(".*", "").replace("-", " ").replace("_", " ")
        )
    if w.blast_radius_at_least:
        parts.append(f"blast radius {w.blast_radius_at_least} or more")
    if w.action_reversible is False:
        parts.append("actions that can't be undone")
    if w.intent_declared is False:
        parts.append("no declared intent")
    if w.budget_exceeded:
        parts.append("budget used up")
    if w.loop_detected:
        parts.append("the agent going round in a loop")
    if w.detector_degraded:
        parts.append("a check is down")
    if w.completion_requires:
        parts.append("saying it's done without " + ", ".join(w.completion_requires))
    if w.risk_tier:
        parts.append(" or ".join(w.risk_tier) + "-risk agents")
    if w.expr:
        parts.append("a custom condition")
    return " · ".join(parts)


def _rule_json(
    rule: Rule,
    mode: str,
    level: str,
    hits: Counter,
    feeds: list[Feed] | None = None,
    running: set[str] | None = None,
) -> dict[str, Any]:
    """One rule as the map shows it.

    ``checks``: the detectors on for this agent that can fire it (they report what it
    looks for, on a surface it covers). ``checksOff``: those that could, but are off
    or not installed here. Both empty for a rule that isn't about content.
    """
    detection = rule.when.detection
    can = checks_for_rule(rule, feeds) if feeds is not None and detection else []
    on = [k for k in can if running is None or k in running]
    return {
        "id": rule.id,
        "description": rule.description,
        "effect": rule.effect,
        "mode": mode,
        "level": level,
        "message": rule.message,
        "hits": hits.get(rule.id, 0),
        "kind": rule_kind(rule),
        # What a content rule looks for (`PII`, `INJECTION.JAILBREAK`) and how sure a
        # check must be; the checks that report that kind of finding feed it.
        # `any` for a detection rule that names neither: any finding fires it.
        "finds": rule_finds(rule),
        "minScore": detection.min_score if detection else None,
        "about": "" if detection else rule_about(rule),
        # The surfaces it is limited to; None: every surface.
        "surfaces": rule_surfaces(rule),
        "checks": on,
        "checksOff": [k for k in can if k not in on],
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
    # Each decision counts once, on the stage that owns its surface; a view stage
    # (the LLM line) adds up what crossed it separately, as `lineStats`.
    stage_stats: dict[str, Counter] = defaultdict(Counter)
    line_stats: dict[str, Counter] = defaultdict(Counter)
    views = [s for s in STAGES if s.derived]
    tool_stats: dict[str, Counter] = defaultdict(Counter)
    hits: Counter = Counter()
    for d in decisions:
        outcome = {"block": "blocked", "escalate": "held"}.get(d.verdict) or (
            "masked" if d.verdict in ("redact", "mask", "tokenize") else "allowed"
        )
        stage = OWNER_OF_SURFACE.get(d.surface or "", DEFAULT_STAGE)
        stage_stats[stage]["total"] += 1
        stage_stats[stage][outcome] += 1
        for view in views:
            if d.surface in view.surfaces:
                line_stats[view.key]["total"] += 1
                line_stats[view.key][outcome] += 1
        if d.tool_key:
            tool_stats[d.tool_key]["total"] += 1
            tool_stats[d.tool_key][outcome] += 1
        for r in d.rules_fired_json or []:
            if isinstance(r, dict) and r.get("rule_id"):
                hits[r["rule_id"]] += 1

    # --- rules in force ------------------------------------------------------
    # One entry per rule: the copy that won for this agent (its own, when it has
    # one), plus what the workspace copy does when they differ. `policy` is the pack
    # a per-agent change is made against.
    effective = effective_for(session, slug)
    own_key = layer_key(slug)
    defaults = {c["rule_id"]: c["default"] for c in agent_changes(session, slug)} if agent else {}
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tool_rules: list[tuple[Rule, dict[str, Any]]] = []
    # A custom rule written for some agents lives in the one workspace `custom` pack,
    # but its detection only runs for those agents; on anyone else's map it would be a
    # rule that can never fire.
    scoped_away = {
        f"custom.{r.key}"
        for r in session.scalars(select(CustomRule))
        if r.agents_json and not any(fnmatch.fnmatch(slug, a) for a in r.agents_json)
    }
    tier = (agent.risk_tier if agent else None) or "limited"
    detectors = all_detectors()
    running = {k for k in enabled_for(session, slug) if k in detectors and detectors[k].available()}
    feeds = feeds_for(detectors, session)
    for resolved in effective.rules:
        rule, layer = resolved.rule, resolved.layer
        if layer is None or rule.id in scoped_away:
            continue
        # A rule written for other risk levels ("prohibited systems", "high-risk agent
        # with degraded checks") can never fire for this agent; listing it on every
        # limited-risk map was noise a reader had to rule out each time.
        if rule.when.risk_tier and tier not in rule.when.risk_tier:
            continue
        own = layer.document.key == own_key
        if not rule.enabled and not own:
            continue
        mode = layer.document.mode
        entry = _rule_json(rule, mode, layer.level, hits, feeds, running)
        base = defaults.get(rule.id) if own else None
        broader = [(src, r) for src, r in resolved.superseded if r.enabled]
        entry.update(
            enabled=rule.enabled,
            own=own,
            policy=(base or {}).get("policy") or layer.document.key,
            overridable=bool(base["overridable"]) if base else rule.overridable,
            # Broader copies still in force beside a tightened one, each in its own
            # layer's mode: an enforcing workspace rule keeps enforcing.
            also=[{"effect": r.effect, "mode": src.document.mode} for src, r in broader],
        )
        if own and base:
            entry["workspace"] = {"effect": base["effect"], "enabled": base["enabled"]}
        stages = _stages_for(rule)
        if stages == ["tool_call"] and (rule.when.tool or rule.when.tool_impact):
            tool_rules.append((rule, entry))
            continue
        home = _home_stages(rule, stages)
        for stage in stages:
            # On a view of other stages it is the same rule, not another one.
            by_stage[stage].append(entry if stage in home else {**entry, "sharedWith": home})

    # --- detectors -----------------------------------------------------------
    detectors_by_stage: dict[str, list[str]] = defaultdict(list)
    # On a view stage: the checks that run there only because they run on the
    # stages it shows, and which those are.
    shared_detectors: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for key in sorted(running):
        surfaces = set(detectors[key].surfaces)
        for stage in STAGES:
            if not set(stage.surfaces) & surfaces:
                continue
            detectors_by_stage[stage.key].append(key)
            if stage.derived and not set(stage.owns) & surfaces:
                shared_detectors[stage.key][key] = list(
                    dict.fromkeys(
                        OWNER_OF_SURFACE[x]
                        for x in stage.surfaces
                        if x in surfaces and x in OWNER_OF_SURFACE
                    )
                )

    # --- tools ---------------------------------------------------------------
    grants, in_code, seen_keys = _tool_sources(session, agent, set(tool_stats))
    registry = {t.key: t for t in session.scalars(select(Tool))}
    ladders = list(
        session.scalars(
            select(BusinessRule).where(
                BusinessRule.enabled.is_(True), BusinessRule.tool.is_not(None)
            )
        )
    )
    tools = []
    for key in sorted(_granted_keys(grants) | in_code | seen_keys):
        grant = _grant_for(grants, key)
        tool = registry.get(key)
        impact = tool.impact if tool else None
        tools.append(
            {
                "key": key,
                "name": (tool.name if tool else "") or key,
                "impact": impact,
                "permission": _permission(grant),
                "limits": grant.constraints_json if grant else {},
                # The grant behind the permission, so it can be changed in place. Its
                # key is a pattern when the tool is reached through a wildcard grant.
                "grant": {
                    "id": grant.id,
                    "key": grant.tool_key,
                    "max_taint": grant.max_taint,
                    "actions": list(grant.actions or ["*"]),
                }
                if grant
                else None,
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
                "sources": _sources(key, grant, in_code, seen_keys),
            }
        )

    # --- sub-agents and parents ------------------------------------------------
    subagents, parents = _hierarchy(session, slug) if agent else ([], [])

    stages = [
        {
            "key": s.key,
            "title": s.title,
            "surfaces": list(s.surfaces),
            "detectors": detectors_by_stage.get(s.key, []),
            "rules": by_stage.get(s.key, []),
            # Decisions on the surfaces this stage owns: summed over stages, every
            # decision in the window once.
            "stats": dict(stage_stats.get(s.key, Counter())),
            "derived": s.derived,
            **(
                {
                    # Everything that crossed this line, overlapping other stages'
                    # `stats`: a view, never to be added to them.
                    "lineStats": dict(line_stats.get(s.key, Counter())),
                    "detectorsSharedWith": shared_detectors.get(s.key, {}),
                }
                if s.derived
                else {}
            ),
        }
        for s in STAGES
        if s.core or by_stage.get(s.key) or stage_stats.get(s.key)
    ]
    return {
        "agent": {
            "slug": slug,
            "name": (agent.name if agent else "") or slug,
            "known": agent is not None,
            "framework": agent.framework if agent else None,
            # The LLMs it runs on: declared in code, or seen in its traffic.
            "models": _models_of(session, slug, agent, since),
        },
        "window_days": WINDOW_DAYS,
        # Decisions in the window: what every stage's `stats.total` adds up to.
        "decisions": len(decisions),
        "stages": stages,
        "everywhere": by_stage.get("everywhere", []),
        "tools": tools,
        "subagents": subagents,
        "parents": parents,
    }


def _models_of(session: Session, slug: str, agent: Agent | None, since: dt.datetime) -> list[str]:
    """The LLMs an agent runs on: declared in its code, or seen in the map's window.

    Only edges from the agent (anything else that shares its id is not it); a model
    last seen before the window is history, not what it runs on now, unless declared.
    """
    seen = session.scalars(
        select(LineageEdge.dst_id).where(
            LineageEdge.src_type == "agent",
            LineageEdge.src_id == slug,
            LineageEdge.relation == "uses_model",
            (LineageEdge.last_observed_at >= since) | LineageEdge.declared.is_(True),
        )
    )
    return list(dict.fromkeys([*((agent.declared_models or []) if agent else []), *seen]))


def rule_checks(session: Session, rule: Rule, agent: str | None = None) -> dict[str, Any]:
    """The checks that can fire a rule, for the rule's page ("Checked by").

    A check can fire it when it reports what the rule looks for, on a surface the rule
    covers (`catalog.can_fire`); the workspace's own models and rules count by what
    they were registered to report. With an agent, each says whether it is on for it.
    """
    detectors = all_detectors()
    feeds = [f for f in feeds_for(detectors, session) if can_fire(rule, f)]
    on = enabled_for(session, agent) if agent else None
    wanted = set(rule.when.surface or [])
    checks = []
    for key in sorted({f.detector for f in feeds}):
        d = detectors[key]
        mine = [f for f in feeds if f.detector == key]
        runs_on = {s for f in mine for s in f.surfaces}
        checks.append(
            {
                "key": key,
                "label": getattr(d, "label", None),
                "source": source_of(d),
                # What it reports that this rule matches: a kind, or an exact entity
                # for the workspace's own models and rules.
                "finds": sorted({f.finds for f in mine}),
                # Where it can fire this rule: where it runs and the rule looks.
                "surfaces": sorted(runs_on & wanted if wanted else runs_on),
                # The workspace's own models or rules behind it (`model:<key>`).
                "via": sorted({f.via for f in mine if f.via}),
                "available": d.available(),
                "on": (key in on) if on is not None else None,
            }
        )
    return {
        "rule_id": rule.id,
        "kind": rule_kind(rule),
        "finds": rule_finds(rule),
        "surfaces": rule_surfaces(rule),
        "agent": agent,
        "checks": checks,
    }


def _edge_json(edge: LineageEdge, other: str, names: dict[str, str]) -> dict[str, Any]:
    return {
        "slug": other,
        "name": names.get(other) or other,
        "calls": edge.observed_count,
        # Read from the code by a repo scan, and/or actually seen in traffic: a
        # sub-agent the code hands work to shows before it has ever been called.
        "declared": bool(edge.declared),
        "seen": edge.observed_count > 0,
        # How the work is handed over, when the code says (``discovery.agents``);
        # None for a delegation only ever seen in a span.
        "relation": edge.kind,
    }


def _hierarchy(session: Session, slug: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(subagents, parents)``: who this agent hands work to, and who hands it work.

    A proposal someone dismissed, or an agent whose project was disconnected, is left
    off both: it is not part of the system they chose to govern, even though the code
    still names it.
    """
    edges = list(
        session.scalars(
            select(LineageEdge).where(
                LineageEdge.relation == "delegates_to",
                LineageEdge.dst_type == "agent",
                (LineageEdge.src_id == slug) | (LineageEdge.dst_id == slug),
            )
        )
    )
    others = {e.dst_id if e.src_id == slug else e.src_id for e in edges}
    rows = list(session.scalars(select(Agent).where(Agent.slug.in_(others)))) if others else []
    dismissed = {a.slug for a in rows if a.status in ("rejected", "removed")}
    names = {a.slug: a.name for a in rows}
    subagents = [
        _edge_json(e, e.dst_id, names)
        for e in sorted(edges, key=lambda e: (-e.observed_count, e.dst_id))
        if e.src_id == slug and e.dst_id != slug and e.dst_id not in dismissed
    ]
    parents = [
        _edge_json(e, e.src_id, names)
        for e in sorted(edges, key=lambda e: e.src_id)
        if e.dst_id == slug and e.src_id != slug and e.src_id not in dismissed
    ]
    return subagents, parents
