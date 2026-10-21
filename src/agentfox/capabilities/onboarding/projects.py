"""Disconnecting a project, so connecting it again starts from scratch, and putting an
agent's guardrails back when it is connected again.

Lives with onboarding because it undoes what `agentfox init` set up: the agents it
registered, their guardrails and tool grants, and the edges it declared.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, LineageEdge
from agentfox.platform.registry.projects import (
    GONE,
    REMOVED,
    TALKS_TO,
    TOUCHES,
    members_of,
    resolve,
)


def disconnect_set(session: Session, project: str) -> list[Agent]:
    """The agents disconnecting ``project`` removes: the members of the systems it
    names that came from the same place.

    ``project`` is a repository init mapped (``agents.project``): its agents, never
    another repository's agent that one of them hands work to. Or it is a system's
    root: the members mapped from the root's repository (for a system no init mapped,
    the members no init mapped either).
    """
    systems = resolve(session, project)
    if not systems:
        return []
    slugs = [m["slug"] for m in members_of(systems)]
    agents = list(session.scalars(select(Agent).where(Agent.slug.in_(slugs)).order_by(Agent.slug)))
    if any(a.project == project for a in agents):
        return [a for a in agents if a.project == project]
    roots = {s["root"] for s in systems}
    repos = {a.project for a in agents if a.slug in roots}
    return [a for a in agents if a.project in repos]


def _snapshot(session: Session, slug: str) -> dict[str, Any]:
    """The agent's own guardrail layers that have rules live: key -> version and mode."""
    from agentfox.capabilities.onboarding.service import basic_key
    from agentfox.capabilities.protection import layer_key
    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import current_binding, load_version_document

    out: dict[str, Any] = {}
    for key in (layer_key(slug), basic_key(slug)):
        policy = session.scalar(select(Policy).where(Policy.key == key))
        if policy is None:
            continue
        binding, live = current_binding(session, policy.id)
        if binding is None or live is None:
            continue
        rules = len(load_version_document(live).rules)
        if rules:
            out[key] = {"version": live.version, "mode": binding.mode, "rules": rules}
    return out


def remove_project(session: Session, project: str, *, actor: str) -> dict[str, Any]:
    """Disconnect a project so connecting it again starts from scratch.

    For each agent of :func:`disconnect_set`: off the dashboard (status ``removed``;
    ``agents.project`` kept as provenance), its own guardrail layers recorded
    (``Agent.guardrails_snapshot``: live version and mode of each) and then emptied
    and set back to watching (a new, audited version; a policy is never deleted), its
    tool permissions revoked, and what `agentfox init` declared from the code cleared:
    who talks to it, what its tools touch, and the hand-offs between agents of the
    set. A hand-off to or from an agent outside the set stays (it is the other
    project's too), and no other agent's guardrails or rule copies are touched. The
    setup card forgets the connection. Traffic, issues and the audit chain are kept:
    history is not something a button erases.

    Re-running init then proposes the agents again with no guardrails and no grants;
    each offers its snapshot back (:func:`restore_guardrails`).
    """
    from agentfox.capabilities.onboarding.service import basic_key
    from agentfox.capabilities.protection import layer_key
    from agentfox.core.models import Identity, OnboardingSession, Policy
    from agentfox.platform.identity.service import revoke_capability
    from agentfox.platform.ledger import chain
    from agentfox.platform.policy.model import PolicyDocument
    from agentfox.platform.policy.publish import publish_in_current_mode
    from agentfox.platform.policy.store import set_mode

    agents = disconnect_set(session, project)
    slugs = [a.slug for a in agents]
    if not agents:
        return {"project": project, "removed": []}
    repos = sorted({a.project for a in agents if a.project})

    snapshots: dict[str, dict[str, Any]] = {}
    for agent in agents:
        snap = _snapshot(session, agent.slug)
        if snap:
            agent.guardrails_snapshot = snap
            snapshots[agent.slug] = snap
        # Its own guardrails: an empty version, watching.
        for key in (layer_key(agent.slug), basic_key(agent.slug)):
            if session.scalar(select(Policy).where(Policy.key == key)) is not None:
                publish_in_current_mode(
                    session,
                    PolicyDocument(key=key, name=f"{agent.slug} protection", rules=[]),
                    actor=actor,
                    notes=f"project '{project}' disconnected",
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
    session.flush()

    # What init declared from the code: inputs, hand-offs inside the set, what its
    # tools touch when no remaining agent has the tool.
    gone = set(slugs)
    tools = {t for a in agents for t in (a.declared_tools or [])}
    still_used = {
        t
        for a in session.scalars(select(Agent).where(Agent.status.not_in(GONE)))
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
        if edge.relation == "delegates_to" and not (edge.src_id in gone and edge.dst_id in gone):
            continue  # a hand-off across projects belongs to the other one too
        if edge.relation not in ("delegates_to", TALKS_TO, TOUCHES):
            continue  # traffic's own edges (models, tools called) are history
        if edge.observed_count:
            edge.declared = False  # seen in traffic: keep the observation, drop the claim
        else:
            session.delete(edge)

    # The setup card's memory of the connection, and the project's attack tests: the
    # next init is a new one, tested afresh.
    for row in session.scalars(select(OnboardingSession)):
        agent_slugs = {a.get("slug") for a in (row.structure or {}).get("agents", [])}
        if agent_slugs & gone or (row.structure or {}).get("project") in {project, *repos}:
            row.structure = None
            row.structure_at = None
    from agentfox.capabilities.onboarding import runs, sessions

    for repo in repos or [project]:
        runs.remove_project(session, repo)
        connected = sessions.find_project(session, repo)
        if connected is not None:
            session.delete(connected)

    chain.append(
        session,
        "project.removed",
        actor_type="user",
        actor_id=actor,
        subject_type="project",
        subject_id=project,
        payload={"agents": slugs, "repos": repos, "snapshots": snapshots},
    )
    session.flush()
    return {"project": project, "removed": slugs, "repos": repos, "restorable": sorted(snapshots)}


def restore_guardrails(
    session: Session, agent: Agent, *, actor: str, may_enforce: bool
) -> dict[str, Any] | None:
    """Put back the guardrail layers ``agent`` had when its project was disconnected.

    Each layer's recorded version is made live again (the version itself, not a copy:
    the rules are exactly what they were, and so is any simulation recorded against
    them). It goes live watching, and blocking again only when it was blocking, the
    caller may change production policy (``may_enforce``) and that version has a
    recorded simulation, the same gate as ``POST /api/policies/{key}/mode``. Returns
    None when there is nothing to restore; the snapshot is used once.
    """
    from agentfox.core.models import Policy, PolicyVersion
    from agentfox.platform.ledger import chain
    from agentfox.platform.policy.simulate import simulation_for
    from agentfox.platform.policy.store import set_mode

    snapshot = agent.guardrails_snapshot or {}
    if not snapshot:
        return None
    restored: dict[str, Any] = {}
    for key, was in snapshot.items():
        policy = session.scalar(select(Policy).where(Policy.key == key))
        if policy is None or not isinstance(was, dict) or not was.get("version"):
            continue
        version = session.scalar(
            select(PolicyVersion).where(
                PolicyVersion.policy_id == policy.id, PolicyVersion.version == was["version"]
            )
        )
        if version is None:
            continue
        mode = "observe"
        if was.get("mode") == "enforce" and may_enforce and simulation_for(session, version):
            mode = "enforce"
        set_mode(session, key, mode, version=version.version)
        restored[key] = {"version": version.version, "mode": mode, "was": was.get("mode")}
    agent.guardrails_snapshot = None
    chain.append(
        session,
        "agent.guardrails.restored",
        actor_type="user",
        actor_id=actor,
        subject_type="agent",
        subject_id=agent.id,
        payload={"slug": agent.slug, "restored": restored},
    )
    session.flush()
    return {"slug": agent.slug, "restored": restored}
