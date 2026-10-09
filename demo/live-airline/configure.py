"""Configure the gateway for the airline agent through its HTTP API, as the dashboard does.

1. Warm up: one harmless check under the agent's name, so the gateway records the agent
   (agents appear on first traffic; the access and protection routes need the row).
2. Access: grant each airline tool with its risk. Compensation and cancellation need a
   person's approval.
3. Protect the agent: prompt attacks and secrets at high, off-task actions on, the
   competitors' names as blocked words, topics to avoid, and the message users see.
4. Enforce: switch the agent's protection pack and the custom-rules pack from watching
   to enforcing. The gateway only enforces a version that has been simulated, so each
   pack is simulated over the last 7 days first (the dashboard's "Start enforcing").

Run again at any time; every step overwrites the previous one.
"""

from __future__ import annotations

from common import AGENT, BLOCK_MESSAGE, GATEWAY, api

from agentfox.frameworks.sdk import AgentFox

# (tool, risk, needs a person's approval)
ACCESS = [
    ("faq_lookup_tool", "read", False),
    ("get_trip_details", "read", False),
    ("flight_status_tool", "read", False),
    ("baggage_tool", "read", False),
    ("get_matching_flights", "read", False),
    ("display_seat_map", "read", False),
    ("update_seat", "write", False),
    ("assign_special_service_seat", "write", False),
    ("book_new_flight", "write", False),
    ("issue_compensation", "high_impact", True),
    ("cancel_flight", "irreversible", True),
]

PROTECTION = {
    "protections": {"attacks": "high", "secrets": "high", "off_task": "on"},
    "words": ["Delta", "United", "American Airlines"],
    "avoid": "legal advice, lawsuits, medical advice",
    "message": BLOCK_MESSAGE,
}

PACKS = [f"agent.{AGENT}", "custom"]


def warm_up() -> None:
    AgentFox(AGENT, base_url=GATEWAY).check("Hello, I have a question about my trip.")
    agent = api("GET", f"/api/agents/{AGENT}")
    print(f"agent      {agent['slug']} recorded by the gateway")


def grant_access() -> None:
    for tool, impact, approval in ACCESS:
        api(
            "POST",
            f"/api/agents/{AGENT}/access",
            json={"tool_key": f"airline.{tool}", "impact": impact, "requires_approval": approval},
        )
        print(f"access     airline.{tool:<28} {impact:<12} {'approval' if approval else ''}")


def protect() -> None:
    saved = api("POST", f"/api/agents/{AGENT}/protection", json=PROTECTION)
    print(f"protection {saved['policy']['key']} v{saved['policy']['version']}, custom rules saved")


def enforce(key: str) -> None:
    policy = api("GET", f"/api/policies/{key}")
    sim = api(
        "POST",
        "/api/policies/simulate",
        json={"body": policy["body"], "since_days": 7, "persist": True},
    )
    version = policy["latest_version"]
    api("POST", f"/api/policies/{key}/mode", json={"mode": "enforce", "version": version})
    stopped = sim.get("counts", {}).get("newly_blocked", 0)
    print(f"enforce    {key} v{version} (simulated: {stopped} past request(s) would stop)")


def main() -> None:
    print(f"gateway    {GATEWAY}")
    warm_up()
    grant_access()
    protect()
    for key in PACKS:
        enforce(key)


if __name__ == "__main__":
    main()
