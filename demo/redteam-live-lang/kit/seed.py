"""One-time setup for a red-team live demo agent (shared by both demos).

Registers the calling demo's agent and its identity, capability grants and tool
registrations, following the exact pattern `agentfox admin seed` and
`tests/capabilities/detection/test_composition.py`'s `_governor` fixture already use — `ensure_identity`,
`grant_capability`, `register_agent`, `McpGovernor.register_tools` — rather than
inventing a new one. Both demos seed the same shape, grants and policy packs; only the
agent slug, display name, purpose text and `framework` label differ, and each demo's
own `seed_demo_agent.py` passes those in.

Deliberately a separate, smaller seed than `agentfox admin seed`'s (which creates three
different demo agents plus a full compliance catalog): it only sets up what the demo
needs, against that demo's own database file (see `kit/env.py`) so it never touches the
main dev database, nor the other demo's `demo.db`.

Idempotent — re-running it is safe and just confirms the existing state.
"""

from __future__ import annotations

from agentfox.core.db import init_db, session_scope
from agentfox.frameworks.mcp import McpGovernor, tool_key
from agentfox.platform.identity import ensure_identity, grant_capability
from agentfox.platform.policy import load_from_dir, save_policy
from agentfox.platform.registry.service import register_agent, upsert_tool

from .support_tools import (
    CAPABILITY_GRANTS,
    SERVER_NAME,
    TOOL_DESCRIPTORS,
    declared_tool_keys,
)


def seed(agent_slug: str, *, name: str, purpose: str, framework: str, notes: str) -> None:
    """Register `agent_slug` with the demo's tools, grants and policy packs."""
    init_db()
    with session_scope() as session:
        agent = register_agent(
            session,
            agent_slug,
            name=name,
            purpose=purpose,
            owner_email="solutions-eng@agentfox.example",
            owner_team="Solutions Engineering",
            environment="production",
            risk_tier="high",  # it holds a money-moving tool and a PII lookup
            declared_models=["gpt-4o-mini", "anthropic/claude-3-5-haiku-20241022"],
            declared_tools=declared_tool_keys(),
            data_classes=["pii", "financial"],
            framework=framework,
        )
        identity = ensure_identity(session, agent)

        governor = McpGovernor(
            session=session, agent_slug=agent_slug, server_name=SERVER_NAME, trust_level="internal"
        )
        # First seed registers the listing; re-seeding an unchanged listing is a
        # no-op. A *changed* listing is not accepted here: accepting one is a
        # two-person loosening (`McpGovernor.register_tools`), which a seed script
        # cannot be. It is held as drift with an `mcp.tool.accept` proposal for two
        # people to approve; for a local demo, deleting demo.db and re-seeding is
        # simpler. (Passing `accept_changes=True` without an actor now raises.)
        governor.register_tools(TOOL_DESCRIPTORS)
        # `register_tools` infers each tool's impact from its name/description
        # (`platform/registry/impact.py`'s `infer_impact` — no DB access, just keyword
        # hints). "issue_refund" contains neither a write nor an irreversible hint
        # word, so it is misread as "read" — the one axis every containment and
        # composition rule reasons over, so it has to be right. Set explicitly
        # here from the same TOOL_DESCRIPTORS the tools themselves implement,
        # rather than trusting the heuristic.
        for descriptor in TOOL_DESCRIPTORS:
            upsert_tool(
                session, tool_key(SERVER_NAME, descriptor["name"]), impact=descriptor["impact"]
            )

        granted = 0
        for grant in CAPABILITY_GRANTS:
            key = tool_key(SERVER_NAME, grant["tool"])
            if any(c.tool_key == key for c in identity.capabilities):
                continue
            grant_capability(
                session,
                identity,
                key,
                constraints=grant.get("constraints"),
                requires_approval=grant.get("requires_approval", False),
                max_taint=grant.get("max_taint", "user"),
                granted_by="seed_demo_agent.py",
            )
            granted += 1

        # The shipped baseline + tool-containment policy packs (observe mode, as
        # they ship) -- the same packs `agentfox admin seed` loads -- so
        # `agentfox test redteam` and the agent's own input/output checks have real
        # rules to match against. Loaded here directly, at org scope, because this
        # demo's database is deliberately its own file (see kit/env.py) rather than
        # sharing the main dev database's seeded state, or the other demo's.
        policy_keys = []
        for doc in load_from_dir():
            save_policy(session, doc, author="seed_demo_agent.py", notes=notes)
            policy_keys.append(doc.key)

    print(f"seeded agent      {agent_slug!r} (risk_tier=high, framework={framework})")
    print(f"capability grants {granted} new (of {len(CAPABILITY_GRANTS)} total)")
    print(f"tools registered  {[d['name'] for d in TOOL_DESCRIPTORS]}")
    print(f"policies loaded   {policy_keys} (mode=observe, as shipped)")
    print()
    print("Next: `agentfox test probes` to see the built-in probe library, then")
    print(f"`agentfox test redteam {agent_slug}` to run it against this agent.")
