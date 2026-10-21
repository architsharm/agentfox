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
#: send and what goes back to them, nothing on tools. The test run again applies them
#: as if they block (the runner's own copy, ``BASIC_TEST_GUARDS``), so it shows what
#: they would stop; in production they watch until simulated and promoted like any
#: policy (``basic_guardrails``). The rest is set up from the map. Kept in a pack of
#: their own per agent, so switching them on never changes the mode of anything else
#: the agent has.
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


def basic_mode(session: Any, slug: str) -> str | None:
    """How the agent's basic guardrails are live: ``"enforce"``, ``"observe"``, or None
    when it has none (never added, or emptied when its project was disconnected)."""
    from sqlalchemy import select

    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import current_binding, load_version_document

    policy = session.scalar(select(Policy).where(Policy.key == basic_key(slug)))
    if policy is None:
        return None
    binding, live = current_binding(session, policy.id)
    if binding is None or live is None or not load_version_document(live).rules:
        return None
    return binding.mode


def has_basic_guardrails(session: Any, slug: str) -> bool:
    """Whether the agent has its basic guardrails, watching or blocking."""
    return basic_mode(session, slug) is not None


def basic_document(slug: str) -> Any:
    """The basic guardrails for one agent, as a policy document."""
    from agentfox.platform.policy.model import Condition, DetectionCondition, PolicyDocument, Rule

    return PolicyDocument(
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


def basic_guardrails(session: Any, slug: str, *, actor: str, may_enforce: bool) -> str | None:
    """Add the basic guardrails to one agent. Returns the mode they went live in, or
    None when the agent already has them.

    They go live the way any policy does (``routes/policy.py`` ``change_mode``): saved
    and bound watching, and switched to blocking only for a caller who may change
    production policy (``may_enforce``) and only once these exact rules have been
    simulated against recorded traffic (``simulation_for``). Otherwise they watch, and
    the Policies page's simulate-then-promote finishes the job.
    """
    from sqlalchemy import select

    from agentfox.core.models import Policy, PolicyVersion
    from agentfox.platform.policy.publish import publish_in_current_mode
    from agentfox.platform.policy.simulate import simulation_for
    from agentfox.platform.policy.store import set_mode

    if has_basic_guardrails(session, slug):
        return None
    doc = basic_document(slug)
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
    if published.mode == "enforce":  # the pack was already enforcing: it stays so
        return "enforce"
    if not may_enforce:
        return "observe"
    policy = session.scalar(select(Policy).where(Policy.key == doc.key))
    version = session.scalar(
        select(PolicyVersion).where(
            PolicyVersion.policy_id == policy.id, PolicyVersion.version == published.version
        )
    )
    if version is None or simulation_for(session, version) is None:
        return "observe"
    set_mode(session, doc.key, "enforce", version=published.version)
    return "enforce"


# --- Registering what `agentfox init` found -------------------------------------------


def _merge(old: list[str] | None, new: list[str]) -> list[str]:
    return list(dict.fromkeys([*(old or []), *new]))


def register_structure(
    session: Any, structure: dict[str, Any], project: str | None = None, *, actor: str
) -> dict[str, Any]:
    """Put what `agentfox init` found in the registry, the way a repository scan does:
    as proposals a person adds (``platform/registry/service.propose_draft``).

    The setup key can propose; it cannot change what is live:

    * an agent it has not seen is proposed as a draft of this project;
    * a draft (or a rejected or removed agent) of the same name is proposed again;
    * a live agent of this same project gets the newly found models and tools added
      to its declaration, and nothing else (risk tier, environment, purpose, status,
      owner and project stay as a person set them);
    * a live agent of another project, or of none, is never touched: the agent is
      proposed under ``<project>-<name>`` instead, or skipped when that is taken too.

    No tool is granted: a draft does nothing until it is added, and access is granted
    by a person (``POST /api/agents/{slug}/access``). New tools are recorded with an
    inferred impact; a declared impact is never replaced. Returns the structure with
    each agent's registry slug (None when skipped) and what happened to it.
    """
    from sqlalchemy import select

    from agentfox.core.models import Agent, Tool
    from agentfox.platform.ledger import chain
    from agentfox.platform.registry.projects import TALKS_TO, TOUCHES
    from agentfox.platform.registry.service import (
        PROPOSABLE,
        impact_source_of,
        propose_draft,
        record_edge,
        slugify,
        upsert_tool,
    )

    def owned(agent: Any) -> bool:
        return agent.status in PROPOSABLE or bool(project and agent.project == project)

    def place(name: str) -> tuple[str, Any] | None:
        for candidate in [slugify(name), *([slugify(f"{project}-{name}")] if project else [])]:
            existing = session.scalar(select(Agent).where(Agent.slug == candidate))
            if existing is None or owned(existing):
                return candidate, existing
        return None

    kinds = {x["id"]: x.get("kind", "") for x in structure.get("systems", [])}
    systems = {x["id"]: x for x in structure.get("systems", [])}
    sources = {x["id"]: x for x in structure.get("sources", [])}
    agents: list[dict[str, Any]] = []
    report: dict[str, list[str]] = {"proposed": [], "updated": [], "skipped": [], "tools": []}
    for agent in structure.get("agents", []):
        tools = [t for t in structure.get("tools", []) if t.get("agentId") == agent["id"]]
        tool_names = [t["name"] for t in tools]
        models = [
            m for m in (agent.get("models") or [agent.get("model")]) if m and m != "unknown model"
        ]
        placed = place(agent["name"])
        if placed is None:
            report["skipped"].append(agent["name"])
            agents.append({**agent, "slug": None, "registry": "skipped"})
            continue
        slug, existing = placed
        if existing is not None and existing.status not in PROPOSABLE:
            existing.declared_tools = _merge(existing.declared_tools, tool_names)
            existing.declared_models = _merge(existing.declared_models, models)
            existing.framework = existing.framework or agent.get("framework")
            report["updated"].append(slug)
            outcome = "updated"
        else:
            propose_draft(
                session,
                slug=slug,
                name=agent["name"],
                purpose="" if existing is not None else "Found by agentfox init.",
                declared_models=models,
                declared_tools=tool_names,
                framework=agent.get("framework") or "langchain",
                project=project,
                # A draft keeps what a reviewer may already have set on it.
                risk_tier=existing.risk_tier if existing is not None else "limited",
                environment=existing.environment if existing is not None else "production",
            )
            report["proposed"].append(slug)
            outcome = "proposed"
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
            known = session.scalar(select(Tool).where(Tool.key == t["name"]))
            if known is None or impact_source_of(known) == "inferred":
                upsert_tool(
                    session,
                    t["name"],
                    name=t["name"],
                    impact=impact_for(t, kinds),
                    description=t.get("whatItDoes", ""),
                    impact_source="inferred",
                    actor=actor,
                )
                report["tools"].append(t["name"])
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
        agents.append({**agent, "slug": slug, "registry": outcome})
    # Who hands work to whom, from the code: the map draws these between agents.
    slug_of = {a["id"]: a["slug"] for a in agents if a["slug"]}
    for a in agents:
        if not a["slug"]:
            continue
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
    chain.append(
        session,
        "onboarding.structure.reported",
        actor_type="user",
        actor_id=actor,
        subject_type="project",
        subject_id=project or "",
        payload=report,
    )
    return {**structure, "agents": agents, "project": project}
