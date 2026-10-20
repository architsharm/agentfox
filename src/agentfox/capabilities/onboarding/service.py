"""Server side of onboarding: progress, the reported map, test runs and the
guardrails picked from them. Shapes match the dashboard's onboarding types.
"""

from __future__ import annotations

import copy
import datetime as dt
import secrets
from typing import Any

from agentfox.capabilities.onboarding.attacks import (
    ATTACK_TYPES,
    DEFAULT_SETS,
    LIBRARY,
    build_suite,
    counts,
)

STEPS = ["connect", "install", "structure", "test", "protect", "retest"]
INITIAL_STATE = {
    "currentStep": "connect",
    "completedSteps": [],
    "skipped": False,
    "completedAt": None,
}
EMPTY_STRUCTURE = {"sources": [], "agents": [], "tools": [], "systems": []}
#: A runner that hasn't polled for this long is treated as gone.
RUNNER_FRESH_SECONDS = 20
FEED_LINES = 16


def new_init_key() -> str:
    return "afi_" + secrets.token_urlsafe(24)


def clean_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("currentStep") not in STEPS:
        return dict(INITIAL_STATE)
    return {
        "currentStep": value["currentStep"],
        "completedSteps": [s for s in value.get("completedSteps") or [] if s in STEPS],
        "skipped": bool(value.get("skipped")),
        "completedAt": value.get("completedAt") or None,
        # The attack sets each project tests with, chosen on the map's panel.
        "tests": {
            str(project): sets
            for project, chosen in (value.get("tests") or {}).items()
            if (sets := clean_sets(chosen))
        },
    }


def clean_sets(value: Any) -> list[str]:
    """Known attack sets, in library order, each once."""
    chosen = set(value) if isinstance(value, list) else set()
    return [k for k in LIBRARY if k in chosen]


def project_sets(state: dict[str, Any] | None, project: str) -> list[str]:
    return (state or {}).get("tests", {}).get(project) or list(DEFAULT_SETS)


def runner_fresh(seen: dt.datetime | None, now: dt.datetime) -> bool:
    if seen is None:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=dt.UTC)
    return (now - seen).total_seconds() < RUNNER_FRESH_SECONDS


# --- Guardrails -------------------------------------------------------------------


def suggest_guardrails(structure: dict[str, Any] | None) -> list[dict[str, Any]]:
    structure = structure or EMPTY_STRUCTURE
    agents = {a["id"]: a["name"] for a in structure.get("agents", [])}
    kinds = {s["id"]: s["kind"] for s in structure.get("systems", [])}
    high = [t for t in structure.get("tools", []) if t.get("risk") == "high"]

    def where(tools: list[dict[str, Any]]) -> str:
        return ", ".join(f"{t['name']} · {agents.get(t['agentId'], '')}" for t in tools)

    money = [t for t in high if kinds.get(t.get("systemId", "")) == "payments"]
    personal = [t for t in high if kinds.get(t.get("systemId", "")) == "crm"]
    db_write = [t for t in high if kinds.get(t.get("systemId", "")) == "database"]
    everyone = ", ".join(agents.values())
    out: list[dict[str, Any]] = []
    if money:
        out.append(
            {
                "id": "refund-approval",
                "sentence": "Refunds need a person to approve",
                "appliesTo": where(money),
                "enabled": True,
            }
        )
    if personal:
        out.append(
            {
                "id": "block-bulk-export",
                "sentence": "Block bulk customer exports",
                "appliesTo": where(personal),
                "enabled": True,
            }
        )
    for t in db_write:
        out.append(
            {
                "id": f"block-sql-delete-{t['agentId']}",
                "sentence": f"Block DELETE / DROP from {agents.get(t['agentId'], 'this agent')}",
                "appliesTo": where([t]),
                "enabled": True,
            }
        )
    if agents:
        out.append(
            {
                "id": "prompt-attacks",
                "sentence": "Catch prompt attacks",
                "appliesTo": f"All agents · {everyone}",
                "enabled": True,
            }
        )
        out.append(
            {
                "id": "hide-personal-data",
                "sentence": "Hide personal data and secrets in replies",
                "appliesTo": f"All agents · {everyone}",
                "enabled": True,
            }
        )
    return out


def guardrails_for(
    row_guardrails: list[Any] | None, structure: dict[str, Any] | None
) -> list[dict[str, Any]]:
    suggested = suggest_guardrails(structure)
    if not row_guardrails:
        return suggested
    saved = {g.get("id"): bool(g.get("enabled")) for g in row_guardrails if isinstance(g, dict)}
    return [{**g, "enabled": saved.get(g["id"], g["enabled"])} for g in suggested]


# --- Test runs ----------------------------------------------------------------------


def new_run(
    phase: str,
    structure: dict[str, Any],
    now: dt.datetime,
    *,
    project: str | None = None,
    guards: list[str] | None = None,
    sets: list[str] | None = None,
) -> dict[str, Any]:
    """A queued attack test. ``project`` ties it to a project's panel; ``guards`` are
    the guardrails the runner applies (None: the setup wizard's own choice); ``sets``
    the attack sets it runs (None: the default ones)."""
    sets = clean_sets(sets) or list(DEFAULT_SETS)
    suite = build_suite(structure, sets)
    return {
        "id": "run_" + secrets.token_hex(8),
        "project": project,
        "guards": guards,
        "sets": sets,
        "phase": phase,
        "status": "queued",
        "total": len(suite),
        "totals": counts(suite),
        "results": [],
        "error": None,
        "createdAt": now.isoformat(),
        "startedAt": None,
        "finishedAt": None,
    }


def add_results(
    run: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    done: bool,
    error: str | None,
    now: dt.datetime,
) -> dict[str, Any]:
    run = copy.deepcopy(run)
    seen = {r["id"] for r in run["results"]}
    for r in results:
        if isinstance(r, dict) and r.get("id") not in seen and r.get("type") in ATTACK_TYPES:
            run["results"].append(
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "type",
                        "gotThrough",
                        "error",
                        "sentence",
                        "attack",
                        "toolCall",
                        "owasp",
                        "severity",
                        "calls",
                    )
                }
            )
            seen.add(r["id"])
    if error:
        run["status"], run["error"], run["finishedAt"] = "failed", error[:500], now.isoformat()
    elif done:
        errors = [r for r in run["results"] if r.get("error")]
        # Most attacks never reached the model: the run says nothing about the agent.
        if run["results"] and len(errors) > len(run["results"]) / 2:
            run["status"] = "failed"
            from agentfox.capabilities.onboarding.runner import explain_model_error

            run["error"] = explain_model_error(str(errors[0]["error"]))
        else:
            run["status"] = "done"
        run["finishedAt"] = now.isoformat()
    return run


def to_test_run(run: dict[str, Any], *, runner_connected: bool, now: dt.datetime) -> dict[str, Any]:
    results = run["results"]
    by_type = []
    for kind, label in ATTACK_TYPES.items():
        if kind not in run["totals"]:
            continue
        mine = [r for r in results if r["type"] == kind]
        by_type.append(
            {
                "type": kind,
                "label": label,
                "total": run["totals"].get(kind, 0),
                "done": len(mine),
                "gotThrough": sum(1 for r in mine if r.get("gotThrough")),
            }
        )
    done = len(results)
    status = "running" if run["status"] in ("queued", "running") else run["status"]
    remaining = None
    if run.get("startedAt") and done:
        started = dt.datetime.fromisoformat(run["startedAt"])
        elapsed = (now - started).total_seconds() * 1000
        remaining = max(0, int(elapsed / done * (run["total"] - done)))
    feed = [
        {
            "id": r["id"],
            "result": "error"
            if r.get("error")
            else "got_through"
            if r.get("gotThrough")
            else "resisted",
            "sentence": r.get("sentence") or "",
        }
        for r in reversed(results[-FEED_LINES:])
    ]
    worst = None
    if status == "done":
        through = [r for r in results if r.get("gotThrough")]
        if through:
            w = max(through, key=lambda r: (r.get("severity") or 0, r["type"] == "unsafe_tool_use"))
            worst = {
                "headline": w.get("sentence") or "",
                "attack": w.get("attack") or "",
                "toolCall": w.get("toolCall") or "",
                "owasp": w.get("owasp") or [],
            }
    return {
        "id": run["id"],
        "project": run.get("project"),
        "status": status,
        "phase": run["phase"],
        "createdAt": run.get("createdAt"),
        "finishedAt": run.get("finishedAt"),
        "total": run["total"],
        "gotThrough": sum(1 for r in results if r.get("gotThrough")),
        "byType": by_type,
        "feed": feed,
        "worst": worst,
        "remainingMs": remaining,
        "waitingForRunner": run["status"] == "queued" and not runner_connected,
        "errors": sum(1 for r in results if r.get("error")),
        "error": run.get("error"),
    }


def all_results(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Every attack with its outcome, for "See all with full traces" and the report."""
    return [
        {
            k: r.get(k)
            for k in (
                "id",
                "type",
                "gotThrough",
                "error",
                "sentence",
                "attack",
                "toolCall",
                "owasp",
                "calls",
            )
        }
        for r in run["results"]
    ]


# --- Registering what `agentfox init` found -------------------------------------


#: The registry's impact vocabulary, from the onboarding risk and what a tool touches.
def impact_for(tool: dict[str, Any], kinds: dict[str, str]) -> str:
    if tool.get("risk") == "high":
        kind = kinds.get(tool.get("systemId", ""), "")
        text = f"{tool.get('name', '')} {tool.get('whatItDoes', '')}".lower()
        if kind == "payments" or any(w in text for w in ("delete", "drop", "remove", "refund")):
            return "irreversible"
        return "high_impact"
    if tool.get("risk") == "outside":
        return "write"
    return "read"


#: The basic guardrails, added with one click after the first attack test: what users
#: send and what goes back to them, nothing on tools. They block (or hide) from the
#: start, so running the test again shows what they stop; the rest is set up from the
#: map. Kept in a pack of their own per agent, so switching them on never changes the
#: mode of anything else the agent has.
BASIC: tuple[tuple[str, str, tuple[str, ...], str, float, str], ...] = (
    # (rule id, what it does, surfaces, entity prefix, min score, effect)
    (
        "basic.input.attacks",
        "Block prompt attacks and jailbreaks in what users send",
        ("input",),
        "INJECTION",
        0.7,
        "block",
    ),
    (
        "basic.reply.personal_data",
        "Hide personal data in replies",
        ("output",),
        "PII",
        0.8,
        "redact",
    ),
    ("basic.reply.secrets", "Hide secrets in replies", ("output",), "SECRET", 0.9, "redact"),
)
#: The same guardrails as the attack runner applies them (runner.py): the user's
#: message checked for prompt attacks, the reply's personal data and secrets hidden.
BASIC_TEST_GUARDS = ["input-attacks", "hide-personal-data"]


def basic_key(slug: str) -> str:
    return f"agent.{slug}.basic"


def has_basic_guardrails(session: Any, slug: str) -> bool:
    from sqlalchemy import select

    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import current_binding

    policy = session.scalar(select(Policy).where(Policy.key == basic_key(slug)))
    if policy is None:
        return False
    binding, _live = current_binding(session, policy.id)
    return binding is not None and binding.mode == "enforce"


def basic_guardrails(session: Any, slug: str, *, actor: str) -> bool:
    """Switch on the basic guardrails for one agent, enforcing. False when they are
    already on."""
    from agentfox.platform.policy.model import Condition, DetectionCondition, PolicyDocument, Rule
    from agentfox.platform.policy.publish import publish_in_current_mode
    from agentfox.platform.policy.store import set_mode

    if has_basic_guardrails(session, slug):
        return False
    doc = PolicyDocument(
        key=basic_key(slug),
        name=f"{slug} basic guardrails",
        description=f"What users send to '{slug}' and what goes back to them.",
        rules=[
            Rule(
                id=rid,
                description=what,
                effect=effect,
                when=Condition(
                    surface=list(surfaces),
                    detection=DetectionCondition(entity_prefix=prefix, min_score=score),
                ),
                reason=f"{what} (basic guardrails)",
            )
            for rid, what, surfaces, prefix, score, effect in BASIC
        ],
    )
    published = publish_in_current_mode(
        session,
        doc,
        actor=actor,
        notes="basic guardrails",
        level="agent",
        scope_id=slug,
        compose="extend",
        agent_slug=slug,
    )
    set_mode(session, doc.key, "enforce", version=published.version)
    return True


def _grant_found_tools(session: Any, slug: str, tools: list[str], *, actor: str) -> None:
    from sqlalchemy import select

    from agentfox.core.models import Agent
    from agentfox.platform.identity import ensure_identity
    from agentfox.platform.identity.service import grant_capability
    from agentfox.platform.ledger import chain

    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    if agent is None:
        return
    identity = ensure_identity(session, agent)
    have = {c.tool_key for c in identity.capabilities}
    for tool in tools:
        if tool in have:
            continue
        cap = grant_capability(session, identity, tool, granted_by=actor)
        chain.append(
            session,
            "capability.granted",
            actor_type="system",
            actor_id=actor,
            subject_type="capability",
            subject_id=cap.id,
            payload={
                "agent": slug,
                "tool_key": tool,
                "why": "found in the agent's code; first guardrails watch only",
            },
        )


def register_structure(
    session: Any, structure: dict[str, Any], project: str | None = None
) -> dict[str, Any]:
    """Register every detected agent and its tools in the registry, so they show up
    under Projects like any other agent, and return the structure with each agent's
    registry slug filled in. Upserts: running `agentfox init` again updates, never
    duplicates. Impacts are recorded as inferred, so a human's declaration wins."""
    from agentfox.platform.registry.projects import TALKS_TO, TOUCHES
    from agentfox.platform.registry.service import record_edge, register_agent, slugify, upsert_tool

    kinds = {x["id"]: x.get("kind", "") for x in structure.get("systems", [])}
    systems = {x["id"]: x for x in structure.get("systems", [])}
    sources = {x["id"]: x for x in structure.get("sources", [])}
    agents = []
    for agent in structure.get("agents", []):
        tools = [t for t in structure.get("tools", []) if t.get("agentId") == agent["id"]]
        slug = slugify(agent["name"])
        register_agent(
            session,
            slug,
            name=agent["name"],
            purpose="Found by agentfox init.",
            declared_models=[
                m
                for m in (agent.get("models") or [agent.get("model")])
                if m and m != "unknown model"
            ],
            declared_tools=[t["name"] for t in tools],
            framework=agent.get("framework") or "langchain",
            project=project,
        )
        # Who sends this agent its messages: the box the map starts from.
        for sid in agent.get("sourceIds", []):
            src = sources.get(sid)
            if src:
                record_edge(
                    session,
                    "input",
                    src["label"],
                    "agent",
                    slug,
                    TALKS_TO,
                    declared=True,
                    kind=(src.get("detail") or "")[:32] or None,
                )
        for t in tools:
            upsert_tool(
                session,
                t["name"],
                name=t["name"],
                impact=impact_for(t, kinds),
                description=t.get("whatItDoes", ""),
                impact_source="inferred",
            )
            # What the tool reads or changes: a resource on the map.
            system = systems.get(t.get("systemId", ""))
            if system:
                record_edge(
                    session,
                    "tool",
                    t["name"],
                    "resource",
                    system["name"],
                    TOUCHES,
                    declared=True,
                    kind=(system.get("kind") or None),
                )
        # No guardrails yet: the first attack test shows the agent as it is, then the
        # basic guardrails are one click. Its own tools may run (default deny would
        # otherwise refuse every one of them).
        _grant_found_tools(session, slug, [t["name"] for t in tools], actor="agentfox init")
        agents.append({**agent, "slug": slug})
    # Who hands work to whom, from the code: the map draws these between agents.
    slug_of = {a["id"]: a["slug"] for a in agents}
    for a in agents:
        for child in a.get("handsOffTo") or []:
            if child in slug_of and slug_of[child] != a["slug"]:
                record_edge(
                    session,
                    "agent",
                    a["slug"],
                    "agent",
                    slug_of[child],
                    "delegates_to",
                    declared=True,
                    kind="handoff",
                )
    return {**structure, "agents": agents, "project": project}
