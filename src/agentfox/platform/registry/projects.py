"""Projects: a multi-agent system, and the map of one.

A project is a **system**: a root agent (the entry point) and every agent it hands
work to, directly or through another (its ``delegates_to`` closure in lineage, of any
kind: handoff, as_tool, delegates, member). It is the same thing whether the system
was proposed by a repository scan and added with "Add all" (``approve-system``) or
reported by `agentfox init`, and a hand-off across repositories is part of it. An
agent that hands nothing on and that nobody hands work to is a project of its own.

``agents.project`` is only provenance: the repository `agentfox init` mapped an agent
from. It pre-groups (a system lists the repositories its members came from) and
resolves the names init and older links used (``/api/projects/<repo>``), but it is
never a project's identity: two repositories each with a "Triage Agent" are two
agents, and a system can span both.

The map is read from the registry: each agent's declared models and tools, and the
lineage edges `agentfox init` declares (who talks to the agent, what each tool
touches) or traffic records (models used, tools called, data read, hand-offs).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, LineageEdge, Tool

#: Edges `agentfox init` declares from the code. What else each says is in
#: ``LineageEdge.attrs`` (``kind`` is only a delegation's relation).
TALKS_TO = "talks_to"  # input -> agent: who sends the agent its messages; attrs.detail
TOUCHES = "touches"  # tool -> resource: the system a tool reads or changes; attrs.resource_kind

#: An agent whose project was disconnected. It is off every project list and map;
#: running `agentfox init` in its repository again brings it back as a proposal.
REMOVED = "removed"
#: Statuses that are not part of any system: dismissed proposals and disconnected agents.
GONE = ("rejected", REMOVED)

#: How a parent hands work to a child, strongest first (``discovery.agents.RELATIONS``).
_RANK = {"handoff": 0, "as_tool": 1, "delegates": 2, "member": 3}

Edge = tuple[str, str, str | None]


def project_of(agent: Agent) -> str:
    """The repository init mapped the agent from, else the agent itself (provenance)."""
    return agent.project or agent.slug


# --- Systems, from the delegation graph --------------------------------------------


def systems_of(nodes: Iterable[str], edges: Iterable[Edge]) -> list[dict[str, Any]]:
    """Group ``nodes`` into systems by the ``(parent, child, relation)`` ``edges``.

    Roots, in order:

    1. every node no other node hands work to, by name;
    2. then, for what is left (agents only reachable through a cycle, like an airline
       desk where every specialist hands back to triage), the node that hands work to
       the most of the others left, ties broken by name.

    Each system is its root and everything the root reaches, breadth first: ``depth``
    is the shortest number of hand-offs from the root and ``relation``/``parent`` how
    it was first reached. A node reached from two roots is a member of both. Returns
    ``[{"root", "members": [{"slug", "depth", "relation", "parent"}]}]``, deterministic.
    """
    names = sorted(set(nodes))
    known = set(names)
    children: dict[str, list[tuple[str, str | None]]] = {n: [] for n in names}
    inbound: dict[str, int] = dict.fromkeys(names, 0)
    seen_pairs: set[tuple[str, str]] = set()
    for parent, child, relation in sorted(
        edges, key=lambda e: (e[0], _RANK.get(e[2] or "", 9), e[1])
    ):
        if parent == child or parent not in known or child not in known:
            continue
        if (parent, child) in seen_pairs:
            continue
        seen_pairs.add((parent, child))
        children[parent].append((child, relation))
        inbound[child] += 1
    for kids in children.values():
        kids.sort(key=lambda c: c[0])

    def closure(root: str) -> list[dict[str, Any]]:
        members = [{"slug": root, "depth": 0, "relation": None, "parent": None}]
        reached = {root}
        queue = deque([(root, 0)])
        while queue:
            current, depth = queue.popleft()
            for child, relation in children[current]:
                if child in reached:
                    continue
                reached.add(child)
                members.append(
                    {"slug": child, "depth": depth + 1, "relation": relation, "parent": current}
                )
                queue.append((child, depth + 1))
        return members

    systems: list[dict[str, Any]] = []
    placed: set[str] = set()
    for root in names:
        if inbound[root] == 0:
            members = closure(root)
            placed.update(m["slug"] for m in members)
            systems.append({"root": root, "members": members})
    while len(placed) < len(names):
        left = [n for n in names if n not in placed]
        root = min(
            left,
            key=lambda n: (-sum(1 for c, _ in children[n] if c not in placed), n),
        )
        members = closure(root)
        placed.update(m["slug"] for m in members)
        systems.append({"root": root, "members": members})
    return systems


def _graph(session: Session) -> tuple[dict[str, Agent], list[Edge]]:
    """Every agent that is part of a system, and every hand-off between two of them."""
    agents = {a.slug: a for a in session.scalars(select(Agent).where(Agent.status.not_in(GONE)))}
    edges = [
        (e.src_id, e.dst_id, e.kind)
        for e in session.scalars(
            select(LineageEdge).where(
                LineageEdge.relation == "delegates_to", LineageEdge.dst_type == "agent"
            )
        )
        if e.src_id in agents and e.dst_id in agents
    ]
    return agents, edges


def _systems(session: Session) -> tuple[dict[str, Agent], list[dict[str, Any]]]:
    agents, edges = _graph(session)
    return agents, systems_of(agents, edges)


def resolve(session: Session, key: str) -> list[dict[str, Any]]:
    """The systems ``key`` names, most specific first:

    * a system's root slug: that system;
    * a repository `agentfox init` mapped (``agents.project``, the name older links
      and the init CLI use): every system with one of its agents;
    * any agent's slug: every system it is a member of.

    Empty when ``key`` names nothing.
    """
    agents, systems = _systems(session)
    by_root = [s for s in systems if s["root"] == key]
    if by_root:
        return by_root
    repo = {slug for slug, a in agents.items() if a.project == key}
    if repo:
        return [s for s in systems if repo & {m["slug"] for m in s["members"]}]
    return [s for s in systems if key in {m["slug"] for m in s["members"]}]


def members_of(systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The members of several systems, each once, at its shallowest."""
    out: dict[str, dict[str, Any]] = {}
    for system in systems:
        for m in system["members"]:
            if m["slug"] not in out or m["depth"] < out[m["slug"]]["depth"]:
                out[m["slug"]] = {**m, "root": system["root"]}
    return sorted(out.values(), key=lambda m: (m["depth"], m["slug"]))


def list_projects(session: Session) -> list[dict[str, Any]]:
    """Every project (system), the most recently changed first.

    ``project`` is the root's slug, the key every other ``/api/projects/{p}`` route
    takes; ``repos`` the repositories its members were mapped from."""
    agents, systems = _systems(session)
    out = []
    for system in systems:
        rows = [agents[m["slug"]] for m in system["members"]]
        seen = [a.updated_at or a.created_at for a in rows if a.updated_at or a.created_at]
        updated = max(seen) if seen else None
        root = agents[system["root"]]
        out.append(
            {
                "project": system["root"],
                "root": system["root"],
                "name": root.name or root.slug,
                "agents": len(rows),
                "slugs": [a.slug for a in rows],
                "members": [
                    {
                        **m,
                        "name": agents[m["slug"]].name or m["slug"],
                        "repo": agents[m["slug"]].project,
                        "status": agents[m["slug"]].status,
                    }
                    for m in system["members"]
                ],
                "repos": sorted({a.project for a in rows if a.project}),
                "updated_at": updated,
            }
        )
    out.sort(
        key=lambda p: (
            -(p["updated_at"].timestamp() if p["updated_at"] else 0),
            p["repos"][0] if p["repos"] else "",
            p["root"],
        )
    )
    return [
        {**p, "updated_at": p["updated_at"].isoformat() if p["updated_at"] else None} for p in out
    ]


def project_agents(session: Session, project: str) -> list[Agent]:
    """The agents an action on ``project`` acts on ("Add all", basic guardrails).

    A system's root: every member of the system, sub-agents in other repositories
    included. A repository `agentfox init` mapped: the agents mapped from it, not a
    parent in another repository that hands one of them work (the map draws that
    parent; acting on the repository does not reach into another one). Any other
    agent: the systems it is a member of."""
    systems = resolve(session, project)
    slugs = [m["slug"] for m in members_of(systems)]
    if not slugs:
        return []
    agents = list(session.scalars(select(Agent).where(Agent.slug.in_(slugs)).order_by(Agent.slug)))
    if any(s["root"] == project for s in systems):
        return agents
    return [a for a in agents if a.project == project] or agents


def project_map(session: Session, project: str) -> dict[str, Any] | None:
    """One project's map: inputs -> agents -> tools -> resources, plus each agent's
    models. Every member of the system is drawn, from whichever repository, with who
    hands work to whom. None when ``project`` names nothing (:func:`resolve`)."""
    systems = resolve(session, project)
    if not systems:
        return None
    members = members_of(systems)
    slugs = [m["slug"] for m in members]
    rows = {a.slug: a for a in session.scalars(select(Agent).where(Agent.slug.in_(slugs)))}
    edges = list(
        session.scalars(
            select(LineageEdge).where(
                or_(LineageEdge.src_id.in_(slugs), LineageEdge.dst_id.in_(slugs))
            )
        )
    )
    by_src: dict[str, list[LineageEdge]] = {}
    for e in edges:
        by_src.setdefault(e.src_id, []).append(e)

    tool_keys: set[str] = set()
    out_agents = []
    for m in members:
        a = rows[m["slug"]]
        mine = by_src.get(a.slug, [])
        models = list(
            dict.fromkeys(
                [
                    *(a.declared_models or []),
                    *(e.dst_id for e in mine if e.relation == "uses_model"),
                ]
            )
        )
        tools = list(
            dict.fromkeys(
                [*(a.declared_tools or []), *(e.dst_id for e in mine if e.relation == "calls_tool")]
            )
        )
        tool_keys.update(tools)
        handoffs = sorted(
            (
                e
                for e in mine
                if e.relation == "delegates_to" and e.dst_id in rows and e.dst_id != a.slug
            ),
            key=lambda e: (_RANK.get(e.kind or "", 9), e.dst_id),
        )
        out_agents.append(
            {
                "slug": a.slug,
                "name": a.name or a.slug,
                "registered": a.registered,
                "status": a.status,
                "framework": a.framework,
                "repo": a.project,
                "depth": m["depth"],
                "relation": m["relation"],
                "parent": m["parent"],
                "models": models,
                "tools": tools,
                "data": [e.dst_id for e in mine if e.relation == "reads_data"],
                "hands_off_to": [e.dst_id for e in handoffs],
                "handoffs": [{"slug": e.dst_id, "relation": e.kind} for e in handoffs],
                "restorable": bool(a.guardrails_snapshot),
            }
        )

    impacts = (
        {t.key: t.impact for t in session.scalars(select(Tool).where(Tool.key.in_(tool_keys)))}
        if tool_keys
        else {}
    )
    touches = (
        list(
            session.scalars(
                select(LineageEdge).where(
                    LineageEdge.relation == TOUCHES, LineageEdge.src_id.in_(tool_keys)
                )
            )
        )
        if tool_keys
        else []
    )

    resources: dict[str, dict[str, Any]] = {}
    for e in touches:
        kind = (e.attrs or {}).get("resource_kind") or e.kind or "service"
        r = resources.setdefault(
            e.dst_id, {"name": e.dst_id, "kind": kind, "tools": [], "agents": []}
        )
        r["tools"].append(e.src_id)
    for a in out_agents:
        for name in a["data"]:
            r = resources.setdefault(
                name, {"name": name, "kind": "data", "tools": [], "agents": []}
            )
            r["agents"].append(a["slug"])

    inputs: dict[str, dict[str, Any]] = {}
    for e in edges:
        if e.relation == TALKS_TO and e.dst_id in rows:
            detail = (e.attrs or {}).get("detail") or e.kind or ""
            i = inputs.setdefault(e.src_id, {"label": e.src_id, "detail": detail, "agents": []})
            i["agents"].append(e.dst_id)

    roots = [s["root"] for s in systems]
    return {
        "project": project,
        "root": roots[0],
        "roots": roots,
        "repos": sorted({a.project for a in rows.values() if a.project}),
        "inputs": list(inputs.values()),
        "agents": out_agents,
        "tools": [{"key": k, "impact": impacts.get(k, "read")} for k in sorted(tool_keys)],
        "resources": list(resources.values()),
    }
