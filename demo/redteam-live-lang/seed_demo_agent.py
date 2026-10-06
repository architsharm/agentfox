"""One-time setup for the red-team-live-lang demo agent (`support-crew-live-lang`).

The seed itself is shared with the CrewAI demo (`kit/seed.py`: same shape, same grants,
same policy packs); this file only names this demo's agent. It writes to this demo's
own database (see `_env.py`), never the main dev database nor the CrewAI demo's.
`web.py` calls `main()` lazily on the first request of a deployment.

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
        name="Live Customer Support Agent (LangChain)",
        purpose=(
            "LangChain tool-calling customer-support agent for the red-team live "
            "demo: looks up customers, searches the order database, issues "
            "refunds and sends email — a real target for adversarial tool-call "
            "probes, not a mock. Same governance story as "
            "demo/redteam-live's CrewAI crew, framework swapped."
        ),
        framework="langchain",
        notes="Red-team live demo (LangChain)",
    )


if __name__ == "__main__":
    main()
