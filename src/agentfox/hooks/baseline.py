"""The working baseline `agentfox admin hooks install --write` sets up.

Without it, installing the hooks leaves the agent unable to do anything: the hook
agent is first seen as a shadow agent in ``production`` with no identity and no
grants, so capability default-deny refuses ``ls``, ``Read`` and ``Edit`` alike, and
every shell command also trips ``action.production_irreversible``. An operator who
meets that on the first tool call removes the hook.

What install does, in one place so the CLI and tests share it:

* registers the agent — ``development`` unless the operator names an environment,
  and an existing registered agent keeps its own;
* declares the harness's built-in tools with the impact each really has
  (`harness.HARNESS_TOOLS`);
* grants those built-in tools to the agent, attributed to ``hooks install``, so the
  ordinary work of a coding agent goes through. What still stops a call is what
  should: a destructive command (``shell.destructive``), a protected path, the
  control plane's own tamper rule — facts about the call, not a missing grant.

Anything else the agent calls (an MCP tool, a tool the harness adds later) has no
grant and is refused until someone grants it; `agentfox policy proposals from-traffic`
files those grants from what the agent was seen to call, for a person to approve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, Capability, Tool
from agentfox.hooks.harness import HARNESS_TOOLS
from agentfox.platform.registry.impact import infer_impact

GRANTED_BY = "hooks install"
DEFAULT_ENVIRONMENT = "development"


@dataclass
class Baseline:
    agent: str
    environment: str
    registered: bool = False
    environment_changed: bool = False
    tools_declared: list[str] = field(default_factory=list)
    tools_granted: list[str] = field(default_factory=list)


def install_baseline(
    session: Session,
    *,
    harness: str,
    agent_slug: str,
    environment: str | None = None,
    grant: bool = True,
) -> Baseline:
    """Register the hook agent, declare the harness's tools and grant them. Idempotent."""
    from agentfox.platform.identity.service import ensure_identity, grant_capability
    from agentfox.platform.ledger import chain
    from agentfox.platform.registry.service import register_agent, slugify

    slug = slugify(agent_slug)
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    out = Baseline(agent=slug, environment=environment or DEFAULT_ENVIRONMENT)

    if agent is None or not agent.registered:
        # New, or only ever seen as a shadow agent (the hook ran before install): a
        # coding agent on someone's machine, so development unless told otherwise.
        previous = agent.environment if agent is not None else None
        agent = register_agent(
            session,
            slug,
            name=(agent.name if agent is not None else "") or slug,
            purpose=f"coding agent governed by {harness} hooks",
            environment=environment or DEFAULT_ENVIRONMENT,
            framework=harness,
        )
        out.registered = True
        out.environment_changed = previous is not None and previous != agent.environment
    elif environment and agent.environment != environment:
        agent.environment = environment
        out.environment_changed = True
    out.environment = agent.environment

    tools = HARNESS_TOOLS.get(harness, {})
    for key in tools:
        impact = infer_impact(key, declared=tools)
        if session.scalar(select(Tool).where(Tool.key == key)) is None:
            session.add(
                Tool(
                    key=key,
                    name=f"{harness}:{key}",
                    impact=impact,
                    description=f"{harness} built-in tool",
                )
            )
            out.tools_declared.append(key)
    session.flush()

    if grant:
        identity = ensure_identity(session, agent)
        held = set(
            session.scalars(
                select(Capability.tool_key).where(Capability.identity_id == identity.id)
            )
        )
        for key in HARNESS_TOOLS.get(harness, {}):
            if key in held:
                continue
            capability = grant_capability(session, identity, key, granted_by=GRANTED_BY)
            chain.append(
                session,
                "capability.granted",
                actor_type="user",
                actor_id="cli",
                subject_type="capability",
                subject_id=capability.id,
                payload={
                    "principal": identity.principal,
                    "tool_key": key,
                    "actions": ["*"],
                    "granted_by": GRANTED_BY,
                    "why": f"{harness} built-in tool, granted by hooks install",
                },
            )
            out.tools_granted.append(key)
    return out


__all__ = ["DEFAULT_ENVIRONMENT", "GRANTED_BY", "Baseline", "install_baseline"]
