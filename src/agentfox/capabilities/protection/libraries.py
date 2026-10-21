"""Libraries: sets of rules applied together, and which one a rule belongs to.

Most libraries are the packs that ship with AgentFox, applied to every agent. Two are
applied per agent instead: the basic guardrails (one click after the first attack
test) and the starter rules earlier versions of `agentfox init` set up, which only
watch. A rule set for one agent by hand belongs to no library.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

BASIC = "Basic guardrails"
STARTER = "Starter rules (watch only)"
OWN = "Set for this agent"


@lru_cache(maxsize=1)
def library_titles() -> dict[str, str]:
    """Policy key -> the title of the library that ships it."""
    from agentfox.platform.packs.loader import load_packs
    from agentfox.platform.policy import PolicyDocument

    titles: dict[str, str] = {}
    for pack in load_packs():
        for path in pack.files("policies"):
            try:
                key = PolicyDocument.from_yaml(path.read_text()).key
            except Exception:
                continue
            titles[key] = pack.manifest.title
    return titles


def library_of(rule_id: str, policy_key: str, level: str, name: str = "") -> str:
    """The library a rule in force comes from, by the policy it lives in."""
    if rule_id.startswith("basic.") or policy_key.endswith(".basic"):
        return BASIC
    if rule_id.startswith("watch."):
        return STARTER
    if level != "agent" and not policy_key.startswith("agent."):
        return library_titles().get(policy_key) or name or policy_key
    return OWN


def remove_starter(session: Any, *, actor: str) -> list[str]:
    """Take the starter rules (``watch.*``) out of every agent's own layer, keeping
    anything else that layer holds. A new, audited version each; returns the agents."""
    from sqlalchemy import select

    from agentfox.capabilities.protection import own_layer
    from agentfox.core.models import Policy
    from agentfox.platform.policy.publish import publish_in_current_mode

    changed = []
    for key in session.scalars(select(Policy.key).where(Policy.key.like("agent.%"))):
        slug = key.removeprefix("agent.")
        if slug.endswith(".basic"):
            continue
        doc = own_layer(session, slug)
        keep = [r for r in doc.rules if not r.id.startswith("watch.")]
        if len(keep) == len(doc.rules):
            continue
        publish_in_current_mode(
            session,
            doc.model_copy(update={"rules": keep}),
            actor=actor,
            notes="starter rules removed",
            level="agent",
            scope_id=slug,
            agent_slug=slug,
        )
        changed.append(slug)
    return changed
