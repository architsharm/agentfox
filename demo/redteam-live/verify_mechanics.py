"""Non-LLM verification of the tool-call governance path — and a scripted fallback.

Runs the shared checks (`kit/verify_mechanics.py`, which explains what each one
proves) against this demo's seeded agent, through the same `GovernedToolkit` the
live agent's tools call into. No LLM, no API key.

Run after `seed_demo_agent.py`:

    python verify_mechanics.py
"""

from __future__ import annotations

import _env  # noqa: F401  -- must run before anything imports agentfox settings
from kit.verify_mechanics import run
from support_tools import GovernedToolkit


def main() -> None:
    run(GovernedToolkit)


if __name__ == "__main__":
    main()
