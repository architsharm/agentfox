"""Libraries: sets of rules applied together, and which one a rule belongs to.

A library is applied to chosen agents, the agents of one project: each gets its own
copy (`agent.<slug>.<library policy>`), bound to that agent alone, so a library on one
project never reaches another. Libraries applied before this, workspace-wide, still
count where they apply. The basic guardrails (one click after the first attack test)
are applied the same way, and the starter rules earlier versions of `agentfox init`
set up are a library too. A rule set for one agent by hand belongs to no library.
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


def agent_copy_key(slug: str, policy_key: str) -> str:
    """The key of one agent's copy of a library policy."""
    return f"agent.{slug}.{policy_key}"


def library_of(rule_id: str, policy_key: str, level: str, name: str = "") -> str:
    """The library a rule in force comes from, by the policy it lives in."""
    if rule_id.startswith("basic.") or policy_key.endswith(".basic"):
        return BASIC
    # An agent's copy of a library: agent.<slug>.<library policy key>.
    parts = policy_key.split(".", 2)
    if len(parts) == 3 and parts[0] == "agent" and parts[2] in library_titles():
        return library_titles()[parts[2]]
    if rule_id.startswith("watch."):
        return STARTER
    if level != "agent" and not policy_key.startswith("agent."):
        return library_titles().get(policy_key) or name or policy_key
    return OWN


def remove_starter(session: Any, *, actor: str, slugs: list[str] | None = None) -> list[str]:
    """Take the starter rules (``watch.*``) out of every agent's own layer, keeping
    anything else that layer holds. A new, audited version each; returns the agents."""
    from sqlalchemy import select

    from agentfox.capabilities.protection import own_layer
    from agentfox.core.models import Policy
    from agentfox.platform.policy.publish import publish_in_current_mode

    changed = []
    for key in session.scalars(select(Policy.key).where(Policy.key.like("agent.%"))):
        slug = key.removeprefix("agent.")
        if "." in slug or (slugs is not None and slug not in slugs):
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


def _library_docs(pack_id: str) -> tuple[str, list[Any]] | None:
    from agentfox.platform.packs.loader import load_packs
    from agentfox.platform.policy import PolicyDocument

    for pack in load_packs():
        if pack.id != pack_id:
            continue
        docs = []
        for path in pack.files("policies"):
            try:
                docs.append(PolicyDocument.from_yaml(path.read_text()))
            except Exception:
                continue
        return pack.manifest.title, docs
    return None


def apply_library(session: Any, pack_id: str, slugs: list[str], *, actor: str) -> list[str] | None:
    """Apply a library to these agents only, watching first: each agent gets its own
    copy of the library's policies. Agents that already have it are left alone.
    None when there is no such library."""
    from sqlalchemy import select

    from agentfox.core.models import Policy
    from agentfox.platform.policy.publish import publish_in_current_mode

    found = _library_docs(pack_id)
    if found is None:
        return None
    title, docs = found
    added = []
    for slug in slugs:
        new = False
        for doc in docs:
            key = agent_copy_key(slug, doc.key)
            if session.scalar(select(Policy.id).where(Policy.key == key)) is not None:
                continue
            publish_in_current_mode(
                session,
                doc.model_copy(update={"key": key, "name": title, "mode": "observe"}),
                actor=actor,
                notes=f"library '{title}' applied",
                level="agent",
                scope_id=slug,
                compose="extend",
                agent_slug=slug,
            )
            new = True
        if new:
            added.append(slug)
    return added


def library_mode(session: Any, pack_id: str, slugs: list[str], mode: str) -> list[str] | None:
    """Watch or block with a library on these agents. Returns the agents changed."""
    from sqlalchemy import select

    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import set_mode

    found = _library_docs(pack_id)
    if found is None:
        return None
    _title, docs = found
    changed = []
    for slug in slugs:
        hit = False
        for doc in docs:
            key = agent_copy_key(slug, doc.key)
            if session.scalar(select(Policy.id).where(Policy.key == key)) is not None:
                set_mode(session, key, mode)
                hit = True
        if hit:
            changed.append(slug)
    return changed


def library_status(session: Any, pack_id: str, slugs: list[str]) -> dict[str, Any]:
    """On which of these agents a library is applied, and whether it blocks there."""
    from sqlalchemy import select

    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import current_binding, load_version_document

    found = _library_docs(pack_id)
    if found is None:
        return {"agents": [], "blocking": False, "workspace": False}
    _title, docs = found
    on, modes = [], []
    workspace = False
    for doc in docs:
        whole = session.scalar(select(Policy).where(Policy.key == doc.key))
        if whole is not None and (current_binding(session, whole.id)[0] is not None):
            workspace = True
            modes.append(current_binding(session, whole.id)[0].mode)
    for slug in slugs:
        for doc in docs:
            policy = session.scalar(
                select(Policy).where(Policy.key == agent_copy_key(slug, doc.key))
            )
            binding, live = current_binding(session, policy.id) if policy else (None, None)
            # An emptied copy (its project was disconnected) applies nothing.
            if binding is not None and live is not None and load_version_document(live).rules:
                on.append(slug)
                modes.append(binding.mode)
                break
    return {
        "agents": on,
        "workspace": workspace,
        "blocking": bool(modes) and all(m == "enforce" for m in modes),
    }
