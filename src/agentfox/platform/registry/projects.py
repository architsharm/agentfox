"""Projects: the agents that live in one repository, and the map of one project.

A project is what one `agentfox init` run mapped: a repository and the agents in it.
The map shows one project at a time; agents from two projects are never drawn
together, and there is no view of every agent at once. An agent registered some
other way (the API, a seed, traffic from an unregistered agent) is a project of its
own, named by its slug, until it is mapped into one.

The map is read from the registry: each agent's declared models and tools, and the
lineage edges `agentfox init` declares (who talks to the agent, what each tool
touches) or traffic records (models used, tools called, data read, hand-offs).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, LineageEdge, Tool

#: Edges `agentfox init` declares from the code.
TALKS_TO = "talks_to"  # input -> agent: who sends the agent its messages
TOUCHES = "touches"  # tool -> resource: the system a tool reads or changes


def project_of(agent: Agent) -> str:
    """The agent's project: the repository init mapped it from, else just itself."""
    return agent.project or agent.slug


def list_projects(session: Session) -> list[dict[str, Any]]:
    """Every project with how many agents it has, the newest-mapped first."""
    projects: dict[str, dict[str, Any]] = {}
    for agent in session.scalars(select(Agent).where(Agent.status.not_in(("rejected", "removed")))):
        key = project_of(agent)
        p = projects.setdefault(key, {"project": key, "agents": 0, "updated_at": None})
        p["agents"] += 1
        seen = agent.updated_at or agent.created_at
        if seen and (p["updated_at"] is None or seen > p["updated_at"]):
            p["updated_at"] = seen
    ordered = sorted(
        projects.values(),
        key=lambda p: -(p["updated_at"].timestamp() if p["updated_at"] else 0),
    )
    return [
        {**p, "updated_at": p["updated_at"].isoformat() if p["updated_at"] else None}
        for p in ordered
    ]


def project_map(session: Session, project: str) -> dict[str, Any]:
    """One project's map: inputs -> agents -> tools -> resources, plus each agent's models."""
    # An agent with no project is its own: matched by slug, and only when unassigned.
    where = or_(Agent.project == project, (Agent.project.is_(None)) & (Agent.slug == project))
    agents = list(
        session.scalars(
            select(Agent)
            .where(where, Agent.status.not_in(("rejected", "removed")))
            .order_by(Agent.slug)
        )
    )
    slugs = [a.slug for a in agents]

    edges = (
        list(
            session.scalars(
                select(LineageEdge).where(
                    or_(LineageEdge.src_id.in_(slugs), LineageEdge.dst_id.in_(slugs))
                )
            )
        )
        if slugs
        else []
    )
    by_src: dict[str, list[LineageEdge]] = {}
    for e in edges:
        by_src.setdefault(e.src_id, []).append(e)

    tool_keys: set[str] = set()
    out_agents = []
    for a in agents:
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
        out_agents.append(
            {
                "slug": a.slug,
                "name": a.name or a.slug,
                "registered": a.registered,
                "framework": a.framework,
                "models": models,
                "tools": tools,
                "data": [e.dst_id for e in mine if e.relation == "reads_data"],
                "hands_off_to": [
                    e.dst_id for e in mine if e.relation == "delegates_to" and e.dst_id in slugs
                ],
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
        r = resources.setdefault(
            e.dst_id, {"name": e.dst_id, "kind": e.kind or "service", "tools": [], "agents": []}
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
        if e.relation == TALKS_TO and e.dst_id in slugs:
            i = inputs.setdefault(
                e.src_id, {"label": e.src_id, "detail": e.kind or "", "agents": []}
            )
            i["agents"].append(e.dst_id)

    return {
        "project": project,
        "inputs": list(inputs.values()),
        "agents": out_agents,
        "tools": [{"key": k, "impact": impacts.get(k, "read")} for k in sorted(tool_keys)],
        "resources": list(resources.values()),
    }


#: An agent whose project was removed. It is off every project list and map; running
#: `agentfox init` in its repository again brings it back as if it were new.
REMOVED = "removed"


def project_agents(session: Session, project: str) -> list[Agent]:
    where = or_(Agent.project == project, (Agent.project.is_(None)) & (Agent.slug == project))
    return list(
        session.scalars(select(Agent).where(where, Agent.status.not_in(("rejected", REMOVED))))
    )


def remove_project(session: Session, project: str, *, actor: str) -> dict[str, Any]:
    """Disconnect a project so connecting it again starts from scratch.

    For each of its agents: off the dashboard (status ``removed``, no project), its
    own guardrail layer emptied and set back to watching (a new, audited version; a
    policy is never deleted), its tool permissions revoked, and what `agentfox init`
    declared from the code (who talks to it, what its tools touch, hand-offs) cleared.
    The setup card forgets the connection. Traffic, issues and the audit chain are
    kept: history is not something a button erases.

    Re-running init then registers the agents again, sees an empty layer, and gives
    them their first, watch-only guardrails and permissions, as for any new project.
    """
    from agentfox.capabilities.protection import layer_key
    from agentfox.core.models import Identity, OnboardingSession, Policy
    from agentfox.platform.identity.service import revoke_capability
    from agentfox.platform.ledger import chain
    from agentfox.platform.policy.model import PolicyDocument
    from agentfox.platform.policy.publish import publish_in_current_mode
    from agentfox.platform.policy.store import set_mode

    agents = project_agents(session, project)
    slugs = [a.slug for a in agents]
    if not agents:
        return {"project": project, "removed": []}

    for agent in agents:
        # Its own guardrails: an empty version, watching.
        key = layer_key(agent.slug)
        if session.scalar(select(Policy).where(Policy.key == key)) is not None:
            publish_in_current_mode(
                session,
                PolicyDocument(key=key, name=f"{agent.slug} protection", rules=[]),
                actor=actor,
                notes=f"project '{project}' removed",
                level="agent",
                scope_id=agent.slug,
                agent_slug=agent.slug,
            )
            set_mode(session, key, "observe")
        # Its tool permissions.
        for identity in session.scalars(select(Identity).where(Identity.agent_id == agent.id)):
            for cap in list(identity.capabilities):
                revoke_capability(session, cap.id)
        agent.status = REMOVED
        agent.registered = False
        agent.project = None

    # What init declared from the code: inputs, hand-offs, what its tools touch.
    tools = {t for a in agents for t in (a.declared_tools or [])}
    still_used = {
        t
        for a in session.scalars(select(Agent).where(Agent.status.not_in(("rejected", REMOVED))))
        for t in (a.declared_tools or [])
    }
    declared = select(LineageEdge).where(
        LineageEdge.declared.is_(True),
        or_(
            LineageEdge.src_id.in_(slugs),
            LineageEdge.dst_id.in_(slugs),
            (LineageEdge.relation == TOUCHES) & LineageEdge.src_id.in_(tools - still_used),
        ),
    )
    for edge in session.scalars(declared):
        if edge.observed_count:
            edge.declared = False  # seen in traffic: keep the observation, drop the claim
        else:
            session.delete(edge)

    # The setup card's memory of the connection: the next init is a new one.
    for row in session.scalars(
        select(OnboardingSession).where(OnboardingSession.structure.is_not(None))
    ):
        agent_slugs = {a.get("slug") for a in (row.structure or {}).get("agents", [])}
        if agent_slugs & set(slugs):
            row.structure = None
            row.structure_at = None

    chain.append(
        session,
        "project.removed",
        actor_type="user",
        actor_id=actor,
        subject_type="project",
        subject_id=project,
        payload={"agents": slugs},
    )
    session.flush()
    return {"project": project, "removed": slugs}
