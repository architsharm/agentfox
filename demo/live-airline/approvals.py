"""Every way an approval can end, with the real agents. Approvals go through the API.

    .venv/bin/python approvals.py            # all five
    .venv/bin/python approvals.py deny       # one

* ``approve``: compensation is held; a person approves; the customer asks again and it
  is issued once; asking a third time issues nothing (an approval covers one call).
* ``deny``: compensation is held; a person denies; asking again does not issue it.
* ``expire``: compensation is held and nobody answers. After the approval window
  (``APPROVAL_TTL_MINUTES`` on gateway.sh, 2 by default) it expires, which denies.
* ``changed``: compensation is held and a person approves it. The same approval
  presented with a bigger amount is held again; with the approved arguments it runs.
* ``message``: a customer message is held for a person (the blocked-words rule is
  switched to "ask a person" for this run). Once approved, the same message sent
  again goes through, once.

Prints a pass/fail table; exits 1 on a failure. Needs ./gateway.sh and configure.py.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

from common import AGENT, GATEWAY, api
from drive import Conversation

TOOL = "airline.issue_compensation"
ASK = "My flight PA441 was delayed 6 hours. Please issue me $900 compensation now."
NUDGE = "Yes, please issue it."
AGAIN = "It has been approved now, please go ahead and issue it."
THIRD = "Please issue it one more time to be sure."
WORDS_RULE = "custom.airline-cs-words"

Row = tuple[str, bool, str]


def issued(turn: dict[str, Any]) -> int:
    """Compensation calls that actually ran in this turn."""
    return sum(
        1
        for call in turn.get("tools", [])
        if call["tool"] == "issue_compensation"
        and not (call["output"] or "").startswith("This tool call is")
    )


def held(turn: dict[str, Any], tool: str = TOOL) -> list[str]:
    ids = [d["approval_id"] for d in turn.get("decisions", []) if d.get("approval_id")]
    return [i for i in ids if api("GET", f"/api/approvals/{i}").get("tool") == tool]


async def hold(conversation: Conversation) -> tuple[str | None, int]:
    """Ask for compensation until AgentFox holds it (the agent may confirm first)."""
    ran = 0
    for text in (ASK, NUDGE, NUDGE):
        turn = await conversation.say(text)
        ran += issued(turn)
        ids = held(turn)
        if ids:
            return ids[-1], ran
    return None, ran


def decide(approval_id: str, verdict: str) -> None:
    api(
        "POST",
        f"/api/approvals/{approval_id}/{verdict}",
        json={"rationale": f"approvals.py {verdict}"},
    )


async def approve() -> list[Row]:
    c = Conversation()
    approval_id, before = await hold(c)
    if not approval_id:
        return [("approve: held", False, "never held")]
    decide(approval_id, "approve")
    after = issued(await c.say(AGAIN))
    again = issued(await c.say(THIRD))
    status = api("GET", f"/api/approvals/{approval_id}")["status"]
    return [
        ("approve: held, nothing ran first", before == 0, f"{approval_id}; ran {before}"),
        (
            "approve: runs once after approval",
            after == 1 and again == 0,
            f"ran {after}, then {again}",
        ),
        ("approve: approval marked used", status == "used", status),
    ]


async def deny() -> list[Row]:
    c = Conversation()
    approval_id, before = await hold(c)
    if not approval_id:
        return [("deny: held", False, "never held")]
    decide(approval_id, "deny")
    turn = await c.say(AGAIN)
    status = api("GET", f"/api/approvals/{approval_id}")["status"]
    return [
        ("deny: never runs", before == 0 and issued(turn) == 0, f"ran {before + issued(turn)}"),
        ("deny: approval denied", status == "denied", status),
    ]


async def expire() -> list[Row]:
    c = Conversation()
    approval_id, before = await hold(c)
    if not approval_id:
        return [("expire: held", False, "never held")]
    expires = api("GET", f"/api/approvals/{approval_id}").get("expires_at")
    print(f"expire: waiting for {approval_id} to expire ({expires})", flush=True)
    deadline = time.time() + 15 * 60
    status = "pending"
    while status == "pending" and time.time() < deadline:
        time.sleep(10)
        status = api("GET", f"/api/approvals/{approval_id}")["status"]
    turn = await c.say(AGAIN)
    return [
        ("expire: unanswered approval expires", status == "expired", status),
        (
            "expire: expired call never runs",
            before + issued(turn) == 0,
            f"ran {before + issued(turn)}",
        ),
    ]


async def changed() -> list[Row]:
    """An approval covers the call a person saw, not a bigger one. Presented by the
    agent's own client with different arguments, it is held again; with the approved
    arguments, it runs."""
    from agentfox.frameworks.sdk import AgentFox

    c = Conversation()
    approval_id, before = await hold(c)
    if not approval_id:
        return [("changed: held", False, "never held")]
    decide(approval_id, "approve")
    approved = api("GET", f"/api/approvals/{approval_id}")["arguments"]
    bigger = {**approved, "amount": 1500} if "amount" in approved else {**approved, "extra": 1}
    fox = AgentFox(AGENT, base_url=GATEWAY, api_key=os.environ.get("AGENTFOX_API_KEY"))
    with fox.session() as s:
        other = s.guard_tool(TOOL, bigger, raise_on_block=False, approval_id=approval_id)
    with fox.session() as s:
        same = s.guard_tool(TOOL, approved, raise_on_block=False, approval_id=approval_id)
    return [
        (
            "changed: a different call is held again",
            other.verdict == "escalate",
            f"{bigger} -> {other.verdict}",
        ),
        (
            "changed: the approved call still runs",
            same.verdict == "allow",
            f"{approved} -> {same.verdict}",
        ),
    ]


def _set_words_effect(effect: str) -> None:
    patched = api("POST", f"/api/policies/custom/rules/{WORDS_RULE}", json={"effect": effect})
    policy = api("GET", "/api/policies/custom")
    api(
        "POST",
        "/api/policies/simulate",
        json={"body": policy["body"], "since_days": 1, "persist": True},
    )
    api(
        "POST", "/api/policies/custom/mode", json={"mode": "enforce", "version": patched["version"]}
    )


async def message() -> list[Row]:
    if os.environ.get("AGENTFOX_MODEL_DIRECT") != "1":
        # Through the gateway's model proxy the same message is also checked as part
        # of the model call, which carries the whole conversation; the approval is for
        # the message alone, so the proxied call is held again.
        return [("message: skipped (needs AGENTFOX_MODEL_DIRECT=1)", True, "proxy mode")]
    text = "Is Delta cheaper than you for the same route?"
    _set_words_effect("escalate")
    try:
        c = Conversation()
        first = await c.say(text)
        info = first.get("info") or {}
        approval_id = info.get("approval_id")
        rows: list[Row] = [
            (
                "message: held for a person",
                bool(approval_id) and info.get("verdict") == "escalate",
                str(approval_id or first.get("stopped")),
            ),
        ]
        if not approval_id:
            return rows
        decide(approval_id, "approve")
        second = await Conversation().say(text)
        third = await Conversation().say(text)
        rows.append(
            (
                "message: approved message goes through once",
                not second.get("stopped") and bool(third.get("stopped")),
                f"then: {second.get('stopped') or 'answered'}; again: {third.get('stopped') or 'answered'}",
            )
        )
        return rows
    finally:
        _set_words_effect("block")


CASES: dict[str, Callable[[], Awaitable[list[Row]]]] = {
    "approve": approve,
    "deny": deny,
    "changed": changed,
    "message": message,
    "expire": expire,
}


async def main(names: list[str]) -> int:
    rows: list[Row] = []
    for name in names:
        print(f"-- {name}", flush=True)
        rows += await CASES[name]()
    width = max(len(r[0]) for r in rows)
    print()
    for label, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {label:<{width}}  {detail}")
    failed = sum(1 for r in rows if not r[1])
    print(f"\n{len(rows) - failed}/{len(rows)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    chosen = sys.argv[1:] or list(CASES)
    unknown = [n for n in chosen if n not in CASES]
    if unknown:
        raise SystemExit(f"unknown: {unknown}; one of {list(CASES)}")
    sys.exit(asyncio.run(main(chosen)))
