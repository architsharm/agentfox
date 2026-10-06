"""One-time setup for the red-team-live demo agent.

Registers `support-crew-live` and its identity, capability grants and tool
registrations, following the exact pattern `agentfox admin seed` and
`tests/capabilities/detection/test_composition.py`'s `_governor` fixture already use — `ensure_identity`,
`grant_capability`, `register_agent`, `McpGovernor.register_tools` — rather than
inventing a new one. This is deliberately a separate, smaller seed than
`agentfox admin seed`'s (which creates three different demo agents plus a full compliance
catalog): it only sets up what this specific demo needs, against its own database
file (see `_env.py`) so it never touches the main dev database.

Idempotent — re-running it is safe and just confirms the existing state.

    python seed_demo_agent.py
"""

from __future__ import annotations

import _env  # noqa: F401  -- must run before anything imports agentfox settings
from support_tools import (
    AGENT_SLUG,
    CAPABILITY_GRANTS,
    SERVER_NAME,
    TOOL_DESCRIPTORS,
    declared_tool_keys,
)

from agentfox.core.db import init_db, session_scope
from agentfox.integrations.mcp import McpGovernor, tool_key
from agentfox.platform.identity import ensure_identity, grant_capability
from agentfox.platform.policy import load_from_dir, save_policy
from agentfox.platform.registry.service import register_agent, upsert_tool


def main() -> None:
    init_db()
    with session_scope() as session:
        agent = register_agent(
            session,
            AGENT_SLUG,
            name="Live Customer Support Crew",
            purpose=(
                "CrewAI customer-support crew for the red-team live demo: looks up "
                "customers, searches the order database, issues refunds and sends "
                "email — a real target for adversarial tool-call probes, not a mock."
            ),
            owner_email="solutions-eng@agentfox.example",
            owner_team="Solutions Engineering",
            environment="production",
            risk_tier="high",  # it holds a money-moving tool and a PII lookup
            declared_models=["gpt-4o-mini", "anthropic/claude-3-5-haiku-20241022"],
            declared_tools=declared_tool_keys(),
            data_classes=["pii", "financial"],
            framework="crewai",
        )
        identity = ensure_identity(session, agent)

        governor = McpGovernor(
            session=session, agent_slug=AGENT_SLUG, server_name=SERVER_NAME, trust_level="internal"
        )
        # The listing is defined in this repo, so re-seeding after it changes is the
        # reviewed change: accept it rather than holding it as drift.
        governor.register_tools(TOOL_DESCRIPTORS, accept_changes=True)
        # `register_tools` infers each tool's impact from its name/description
        # (`integrations/mcp.py`'s `infer_impact` — no DB access, just keyword
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
        # `agentfox test redteam` and the crew's own input/output checks have real
        # rules to match against. Loaded here directly, at org scope, because this
        # demo's database is deliberately its own file (see _env.py) rather than
        # sharing the main dev database's seeded state.
        policy_keys = []
        for doc in load_from_dir():
            save_policy(session, doc, author="seed_demo_agent.py", notes="Red-team live demo")
            policy_keys.append(doc.key)

    print(f"seeded agent      {AGENT_SLUG!r} (risk_tier=high, framework=crewai)")
    print(f"capability grants {granted} new (of {len(CAPABILITY_GRANTS)} total)")
    print(f"tools registered  {[d['name'] for d in TOOL_DESCRIPTORS]}")
    print(f"policies loaded   {policy_keys} (mode=observe, as shipped)")
    print()
    print("Next: `agentfox test probes` to see the built-in probe library, then")
    print(f"`agentfox test redteam {AGENT_SLUG}` to run it against this agent.")


if __name__ == "__main__":
    main()
