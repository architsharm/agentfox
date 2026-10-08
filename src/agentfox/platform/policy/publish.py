"""Publishing a generated policy without changing whether it enforces.

Some packs are written by the product rather than by hand: the workspace's own
rules (`custom`), and each agent's protection layer (`agent.<slug>`). When their
rules change, the new version has to go live *in the mode the pack is already in*
— an operator who chose to enforce should not find it silently back in observe,
and one who chose to watch should not find it enforcing.

The enforcing gate still holds: making a version live in an enforcing pack needs a
recorded simulation of exactly that version (the `/mode` route's rule), so an
enforcing pack is replayed over recent traffic first and the impact returned for
the screen to show. A pack with no binding yet is bound in observe.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Policy
from agentfox.platform.policy.model import PolicyDocument
from agentfox.platform.policy.simulate import record_simulation, simulate
from agentfox.platform.policy.store import current_binding, save_policy, set_mode

#: How far back an enforcing pack's new version is replayed before it goes live.
REPLAY_DAYS = 7


@dataclass
class Published:
    version: int | None = None
    mode: str | None = None
    #: Present when the pack enforces: what the new version would have changed.
    simulation: dict[str, Any] | None = None
    rules: list[str] = field(default_factory=list)


def current_mode(session: Session, key: str) -> str | None:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    binding = current_binding(session, policy.id)[0] if policy else None
    return binding.mode if binding else None


def publish_in_current_mode(
    session: Session,
    doc: PolicyDocument,
    *,
    actor: str,
    notes: str,
    level: str = "org",
    scope_id: str = "*",
    compose: str = "extend",
    agent_slug: str | None = None,
) -> Published:
    """Save ``doc`` as a new version and make it live in its pack's current mode.

    ``level``/``scope_id``/``compose`` place a new pack in the hierarchy; an existing
    pack keeps the placement it has. ``agent_slug`` narrows the replay to one agent's
    traffic when the pack only applies to that agent.
    """
    policy = session.scalar(select(Policy).where(Policy.key == doc.key))
    binding = current_binding(session, policy.id)[0] if policy else None
    mode = binding.mode if binding else "observe"
    doc = doc.model_copy(update={"mode": mode})
    _policy, version = save_policy(
        session,
        doc,
        author=actor,
        notes=notes,
        bind_mode="observe",
        level=binding.level if binding else level,
        scope_id=binding.scope_id if binding else scope_id,
        compose=binding.compose if binding else compose,
        rebind=False,
    )
    result = Published(version=version.version, mode=mode, rules=[r.id for r in doc.rules])
    if binding is None:
        return result  # a new pack is bound in observe by `save_policy`
    if mode == "enforce":
        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=REPLAY_DAYS)
        diff = simulate(session, doc, agent_slug=agent_slug, since=since)
        record_simulation(session, doc, diff, run_by=actor, scope={"source": notes})
        result.simulation = diff.to_json()
    set_mode(session, doc.key, mode, version=version.version)
    return result
