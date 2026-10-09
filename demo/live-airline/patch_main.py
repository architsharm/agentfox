"""Add the AgentFox hook to the upstream main.py. Idempotent.

Two insertions: ``import agentfox_wiring`` before the agents are imported (it sets the
default OpenAI client to the gateway), and ``agentfox_wiring.govern(...)`` once they
exist (it attaches AgentFox guardrails to every agent and tool).
"""

from __future__ import annotations

import sys
from pathlib import Path

IMPORT_ANCHOR = "from airline.agents import ("
IMPORT_LINE = "import agentfox_wiring  # noqa: F401  (route model calls through AgentFox)\n"
GOVERN_ANCHOR = "chat_server = AirlineServer()"
GOVERN_BLOCK = """agentfox_wiring.govern(
    triage_agent,
    faq_agent,
    seat_special_services_agent,
    flight_information_agent,
    booking_cancellation_agent,
    refunds_compensation_agent,
)

"""


def patch(text: str) -> str:
    if "import agentfox_wiring" in text:
        return text
    for anchor in (IMPORT_ANCHOR, GOVERN_ANCHOR):
        if text.count(anchor) != 1:
            raise SystemExit(f"main.py changed upstream: expected one '{anchor}'")
    text = text.replace(IMPORT_ANCHOR, IMPORT_LINE + IMPORT_ANCHOR)
    return text.replace(GOVERN_ANCHOR, GOVERN_BLOCK + GOVERN_ANCHOR)


def main(path: str) -> None:
    file = Path(path)
    before = file.read_text()
    after = patch(before)
    if after == before:
        print(f"hook: already in {file}")
        return
    file.write_text(after)
    print(f"hook: added to {file}")


if __name__ == "__main__":
    main(sys.argv[1])
