"""Disconnecting a project, so connecting it again starts from scratch.

Lives with onboarding because it undoes what `agentfox init` set up: the agents it
registered, their guardrails and tool grants, and the edges it declared.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, LineageEdge
from agentfox.platform.registry.projects import REMOVED, TOUCHES, project_agents


def remove_project(session: Session, project: str, *, actor: str) -> dict[str, Any]:
    """Disconnect a project so connecting it again starts from scratch.

    For each of its agents: off the dashboard (status ``removed``, no project), its
    own guardrail layer emptied and set back to watching (a new, audited version; a
    policy is never deleted), its tool permissions revoked, and what `agentfox init`
    declared from the code (who talks to it, what its tools touch, hand-offs) cleared.
    The setup card forgets the connection. Traffic, issues and the audit chain are
    kept: history is not something a button erases.

    Re-running init then registers the agents again with their permissions and no
    guardrails, and tests them, as for any new project.
    """
    from agentfox.capabilities.onboarding.service import basic_key
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
        for key in (layer_key(agent.slug), basic_key(agent.slug)):
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

    # The setup card's memory of the connection, and the project's attack tests: the
    # next init is a new one, tested afresh.
    for row in session.scalars(select(OnboardingSession)):
        agent_slugs = {a.get("slug") for a in (row.structure or {}).get("agents", [])}
        if agent_slugs & set(slugs):
            row.structure = None
            row.structure_at = None
        runs = row.runs or {}
        if any(r.get("project") == project for r in runs.values()):
            row.runs = {k: r for k, r in runs.items() if r.get("project") != project}

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
