"""One-time setup for the red-team-live demo agent (`support-crew-live`, CrewAI).

The seed itself is shared with the LangChain demo (`kit/seed.py`: same shape, same
grants, same policy packs); this file only names this demo's agent. It writes to this
demo's own database file (see `_env.py`), never the main dev database.

Idempotent — re-running it is safe and just confirms the existing state.

    python seed_demo_agent.py
"""

from __future__ import annotations

import _env  # noqa: F401  -- must run before anything imports agentfox settings
from kit.seed import seed
from support_tools import AGENT_SLUG


def main() -> None:
    seed(
        AGENT_SLUG,
        name="Live Customer Support Crew",
        purpose=(
            "CrewAI customer-support crew for the red-team live demo: looks up "
            "customers, searches the order database, issues refunds and sends "
            "email — a real target for adversarial tool-call probes, not a mock."
        ),
        framework="crewai",
        notes="Red-team live demo",
    )


if __name__ == "__main__":
    main()
