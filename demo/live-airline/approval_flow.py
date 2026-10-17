"""Hold a flight cancellation for a person's approval, then let the agent finish it.

    .venv/bin/python approval_flow.py                 # approve it on the dashboard
    .venv/bin/python approval_flow.py --auto-approve  # approve it through the API

1. The customer asks to cancel. `cancel_flight` is irreversible and needs approval, so
   AgentFox holds the call and the agent tells the customer it is waiting.
2. Someone approves it: on the dashboard's Approvals page, or with --auto-approve via
   POST /api/approvals/{id}/approve.
3. The customer asks again. The AgentFox tool guardrail retries the same call with the
   approval, and the flight is cancelled.
4. The customer asks a third time. The approval was for one call, so nothing is
   cancelled twice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from common import api
from drive import Conversation

ASK = "Please cancel my flight, booking IR-D204. Yes, I'm sure."
NUDGE = "Yes, please cancel it now."
AFTER_APPROVAL = "It's been approved now, please go ahead and cancel it."
AGAIN = "Please cancel it one more time to be sure."
CANCELLED = "successfully cancelled"


def _show(turn: dict[str, Any]) -> None:
    print(json.dumps({k: turn.get(k) for k in ("user", "agent", "stopped", "reply")}), flush=True)
    for call in turn.get("tools", []):
        print(f"    tool {call['tool']}: {(call['output'] or '')[:140]}", flush=True)


def held_cancellations(turn: dict[str, Any]) -> list[str]:
    """Approval ids AgentFox opened in this turn for `airline.cancel_flight`."""
    ids = [d["approval_id"] for d in turn.get("decisions", []) if d.get("approval_id")]
    return [
        i for i in ids if api("GET", f"/api/approvals/{i}").get("tool") == "airline.cancel_flight"
    ]


def cancellations(turn: dict[str, Any]) -> int:
    return sum(
        1
        for call in turn.get("tools", [])
        if call["tool"] == "cancel_flight" and CANCELLED in (call["output"] or "")
    )


def wait_for(approval_id: str, auto_approve: bool, timeout: float = 900) -> str:
    if auto_approve:
        api(
            "POST",
            f"/api/approvals/{approval_id}/approve",
            json={"rationale": "approved by approval_flow.py --auto-approve"},
        )
        return "approved"
    print(f"waiting for a person to approve {approval_id} (dashboard: Approvals)", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = api("GET", f"/api/approvals/{approval_id}").get("status")
        if status != "pending":
            return status
        time.sleep(3)
    return "timed out"


async def run(auto_approve: bool) -> dict[str, Any]:
    conversation = Conversation()
    turns = [await conversation.say(ASK)]
    _show(turns[-1])
    held = held_cancellations(turns[-1])
    if not held:  # the agent asked to confirm first; confirm once
        turns.append(await conversation.say(NUDGE))
        _show(turns[-1])
        held = held_cancellations(turns[-1])
    outcome: dict[str, Any] = {
        "held": held,
        "ran_before_approval": sum(cancellations(t) for t in turns),
    }
    if not held:
        return {**outcome, "status": "never held"}
    # A retried call replaces the held one, so the newest approval is the one to grant.
    approval_id = held[-1]
    print(json.dumps({"held_for_approval": approval_id}), flush=True)
    outcome["approval_id"] = approval_id
    outcome["status"] = wait_for(approval_id, auto_approve)
    print(json.dumps({"approval": outcome["status"]}), flush=True)
    if outcome["status"] != "approved":
        return outcome

    after = await conversation.say(AFTER_APPROVAL)
    _show(after)
    again = await conversation.say(AGAIN)
    _show(again)
    outcome["ran_after_approval"] = cancellations(after)
    outcome["ran_again"] = cancellations(again)
    outcome["turns"] = [*turns, after, again]
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--auto-approve", action="store_true", help="approve through the API")
    args = parser.parse_args()
    outcome = asyncio.run(run(args.auto_approve))
    print(json.dumps({k: v for k, v in outcome.items() if k != "turns"}, indent=1))


if __name__ == "__main__":
    main()
