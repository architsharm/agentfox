"""Which agents the coding-agent pack applies to.

`coding-agent.yaml` is tuned for an agent that edits code and runs shell commands
on a developer machine. Its scope said ``agents: ["*"]`` and `agentfox init` loaded
every available pack, so the first customer-support bot in a fresh deployment got
"Personal data in a tool-call argument from a coding session" on an ordinary email to a customer.
The rules were right for the job they were written for and wrong for every other.

Two ways to stop that: give the rules a condition only a coding agent meets, or
bind the pack only to agents that are coding agents. The first needs a condition
type nothing else uses and a signal the agent would have to report about itself.
The second uses a fact the product already holds, from an action the operator
already took: the agents that `agentfox admin hooks install` wired into a coding harness.
So the pack is bound to exactly those slugs —

* `agentfox init` binds it scoped to the agents named in this repository's
  ``.claude/settings.json`` hook commands, and skips it when there are none;
* `agentfox admin hooks install --write` adds the agent it just installed to the scope.

An agent nobody installed hooks for never matches. An operator who wants it
everywhere can still say so explicitly with a project pack, which is honoured as
written — only the shipped wildcard is narrowed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.policy.model import PolicyDocument

CODING_PACK = "coding-agent"

#: Files `hooks install` writes, relative to the project root.
HOOK_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")

#: The command `hooks install` writes: ``agentfox hooks run --harness X --agent Y``.
_HOOK_COMMAND = re.compile(r"agentfox hooks run\b[^\"\n]*?--agent[ =]([A-Za-z0-9_.:@/-]+)")


def hooked_agents(root: Path | None = None) -> list[str]:
    """Agent slugs this project's coding-harness hooks govern, if any."""
    root = Path(root or Path.cwd())
    slugs: set[str] = set()
    for rel in HOOK_SETTINGS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        slugs.update(_HOOK_COMMAND.findall(text))
    return sorted(slugs)


def _is_wildcard(scope: dict[str, Any] | None) -> bool:
    agents = (scope or {}).get("agents")
    return not agents or all(str(a).strip() == "*" for a in agents)


def scope_coding_pack(
    documents: list[PolicyDocument], agents: list[str]
) -> tuple[list[PolicyDocument], list[str] | None]:
    """Narrow the shipped coding-agent pack to ``agents``; drop it if there are none.

    Returns ``(documents, scoped_to)``. ``scoped_to`` is ``None`` when the pack was
    absent or carried an explicit scope of its own (left as written), ``[]`` when it
    was skipped, and the slug list otherwise.
    """
    out: list[PolicyDocument] = []
    scoped_to: list[str] | None = None
    for doc in documents:
        if doc.key != CODING_PACK or not _is_wildcard(doc.scope):
            out.append(doc)
            continue
        if not agents:
            scoped_to = []
            continue
        doc.scope = {**(doc.scope or {}), "agents": sorted(set(agents))}
        scoped_to = doc.scope["agents"]
        out.append(doc)
    return out, scoped_to


#: Authors of a binding this module may narrow: the ones the CLI wrote on the
#: operator's behalf. A binding a person made is never touched.
_TOOL_AUTHORS = frozenset({"init", "seed", "hooks install"})


def _open_binding(session: Session) -> tuple[Any, Any] | tuple[None, None]:
    from agentfox.core.models import Policy, PolicyBinding, PolicyVersion

    policy = session.scalar(select(Policy).where(Policy.key == CODING_PACK))
    if policy is None:
        return None, None
    versions = {
        v.id: v
        for v in session.scalars(select(PolicyVersion).where(PolicyVersion.policy_id == policy.id))
    }
    binding = session.scalar(
        select(PolicyBinding)
        .where(
            PolicyBinding.policy_version_id.in_(list(versions)),
            PolicyBinding.effective_to.is_(None),
        )
        .order_by(PolicyBinding.effective_from.desc())
        .limit(1)
    )
    if binding is None:
        return None, None
    return binding, versions.get(binding.policy_version_id)


def retire_tool_wildcard(session: Session) -> bool:
    """Unbind a coding-agent pack that an earlier `init` or `seed` bound to every agent.

    That binding is the defect this module exists for, written by this CLI rather
    than by a person, so a re-run of `init` is entitled to take it back. Returns
    whether anything was unbound.
    """
    from agentfox.core.models import utcnow

    binding, version = _open_binding(session)
    if binding is None or not _is_wildcard(binding.scope_json):
        return False
    if version is None or version.author not in _TOOL_AUTHORS:
        return False
    binding.effective_to = utcnow()
    session.flush()
    return True


def enable_for_agent(session: Session, slug: str, *, author: str = "hooks install") -> list[str]:
    """Bind the coding-agent pack to ``slug`` as well as whoever it already covers.

    Keeps the mode the pack is currently bound in, so a pack someone promoted to
    enforce is not quietly demoted by installing a hook for a second agent.
    Returns the agents the pack now covers (``["*"]`` if a person bound it to all).
    """
    from agentfox.policy.store import load_available, save_policy

    doc = next((d for d in load_available() if d.key == CODING_PACK), None)
    if doc is None:
        return []

    current_agents: list[str] = []
    mode: str | None = None
    binding, version = _open_binding(session)
    if binding is not None:
        mode = binding.mode
        scope = binding.scope_json or {}
        if not _is_wildcard(scope):
            current_agents = [str(a) for a in scope.get("agents") or []]
        elif version is None or version.author not in _TOOL_AUTHORS:
            # A person bound it to everything. Narrowing it here would take
            # coverage away from agents someone chose to include.
            return ["*"]

    if not _is_wildcard(doc.scope):
        # A project pack with its own scope: honoured as written.
        current_agents = [*current_agents, *(str(a) for a in doc.scope.get("agents") or [])]
    agents = sorted({*current_agents, slug})
    doc.scope = {**(doc.scope or {}), "agents": agents}
    save_policy(
        session,
        doc,
        author=author,
        notes=f"coding-agent pack scoped to hooked agents: {', '.join(agents)}",
        bind_mode=mode,
    )
    return agents


__all__ = [
    "CODING_PACK",
    "HOOK_SETTINGS",
    "enable_for_agent",
    "hooked_agents",
    "retire_tool_wildcard",
    "scope_coding_pack",
]
