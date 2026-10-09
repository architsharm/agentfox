"""Run the demo end to end and check what AgentFox did, not what the model said.

    .venv/bin/python check.py --auto-approve    # unattended
    .venv/bin/python check.py                   # a person approves the cancellation

Replies vary from run to run, so every check is a governance fact: which tools ran,
what came back from a held or blocked call, the message a blocked user saw, and the
traces and approvals the gateway recorded. Prints a pass/fail table; exits 1 on any
failure. Needs ./gateway.sh running and configure.py applied.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import time
from collections.abc import Callable
from typing import Any

import approval_flow
from common import AGENT, BLOCK_MESSAGE, api
from run_all import run

Turns = list[dict[str, Any]]
Result = tuple[bool, str]


def ran(turns: Turns, tool: str) -> list[str]:
    """Outputs of `tool` calls that actually ran (not held or blocked by AgentFox)."""
    return [
        call["output"] or ""
        for turn in turns
        for call in turn.get("tools", [])
        if call["tool"] == tool and not (call["output"] or "").startswith("This tool call is")
    ]


def answered_with_reads(turns: Turns) -> Result:
    last = turns[-1]
    reads = {"flight_status_tool", "get_trip_details"}
    used = sorted({c["tool"] for t in turns for c in t.get("tools", []) if c["tool"] in reads})
    if last.get("stopped") or not last.get("reply"):
        return False, f"not answered: {last.get('stopped')}"
    if not any(ran(turns, tool) for tool in reads):
        return False, "no flight lookup ran"
    return True, f"answered by {last['agent']}; ran {', '.join(used)}"


def seat_changed(turns: Turns) -> Result:
    outputs = ran(turns, "update_seat") + ran(turns, "assign_special_service_seat")
    if not any("23A" in o for o in outputs):
        return (
            False,
            f"no seat change ran: {[t.get('stopped') or t.get('reply', '')[:80] for t in turns]}",
        )
    return True, outputs[0][:70]


def compensation_held(turns: Turns) -> Result:
    held = [
        d["approval_id"]
        for t in turns
        for d in t.get("decisions", [])
        if d.get("verdict") == "escalate" and d.get("approval_id")
    ]
    tools = {i: api("GET", f"/api/approvals/{i}")["tool"] for i in held}
    mine = [i for i, tool in tools.items() if tool == "airline.issue_compensation"]
    if ran(turns, "issue_compensation"):
        return False, "issue_compensation ran without approval"
    if not mine:
        return False, f"no approval opened for airline.issue_compensation (held: {tools})"
    return True, f"held as {mine[0]}; not run"


def blocked_by(rule_prefix: str) -> Callable[[Turns], Result]:
    def check(turns: Turns) -> Result:
        turn = turns[0]
        info = turn.get("info") or {}
        if not turn.get("stopped"):
            return False, f"not stopped; reply: {turn.get('reply', '')[:80]}"
        if not info.get("trace_id"):
            return False, f"stopped by {turn['stopped']}, not by AgentFox"
        trace = api("GET", f"/api/traces/{info['trace_id']}")
        fired = [r for d in trace["decisions"] for r in d.get("rules_fired") or []]
        # The shipped packs may fire the same rule while watching; the agent's own
        # layer is the copy that carries its message.
        matching = [r for r in fired if r["rule_id"].startswith(rule_prefix)]
        rule = next((r for r in matching if r.get("message")), matching[0] if matching else None)
        if trace["trace"]["verdict"] != "block" or rule is None:
            rules = [r["rule_id"] for r in fired]
            return (
                False,
                f"trace {info['trace_id']}: verdict {trace['trace']['verdict']}, rules {rules}",
            )
        if rule.get("message") != BLOCK_MESSAGE:
            return False, f"rule {rule['rule_id']} carries message {rule.get('message')!r}"
        status = info.get("status")
        if info.get("user_message") == BLOCK_MESSAGE:
            return True, f"HTTP {status or 'error'} with user_message; rule {rule['rule_id']}"
        if status is None:
            # The streamed model call lost the race to report the block. The gateway's
            # SSE error event carries no user_message (a known gap); the decision does.
            return True, f"stream error; user_message only in trace; rule {rule['rule_id']}"
        return False, f"HTTP {status} without the user_message: {info.get('user_message')!r}"

    return check


CHECKS: list[tuple[str, str, Callable[[Turns], Result]]] = [
    ("status", "normal question answered with read tools", answered_with_reads),
    ("seat", "write tool runs", seat_changed),
    ("compensation", "high-impact tool held for approval", compensation_held),
    ("competitor", "competitor name blocked", blocked_by("custom.airline-cs-words")),
    ("legal", "avoided topic blocked", blocked_by("custom.airline-cs-avoid")),
    ("injection", "prompt injection blocked", blocked_by("injection.")),
    ("secret", "pasted secret blocked", blocked_by("secrets.")),
]


def check_approval(outcome: dict[str, Any], since: str) -> list[tuple[str, bool, str]]:
    rows = []
    held = bool(outcome.get("held")) and outcome.get("ran_before_approval") == 0
    rows.append(
        (
            "cancel held before approval",
            held,
            f"held as {outcome.get('approval_id')}" if held else str(outcome)[:120],
        )
    )
    if outcome.get("status") != "approved":
        rows.append(("cancel approved", False, f"approval {outcome.get('status')}"))
        return rows
    once = outcome.get("ran_after_approval") == 1 and outcome.get("ran_again") == 0
    rows.append(
        (
            "cancel runs once after approval",
            once,
            f"ran {outcome.get('ran_after_approval')} after approval, {outcome.get('ran_again')} when asked again",
        )
    )
    approval = api("GET", f"/api/approvals/{outcome['approval_id']}")
    traces = api(
        "GET",
        "/api/traces",
        params={"agent": AGENT, "tool": "airline.cancel_flight", "start": since, "limit": 50},
    )["traces"]
    verdicts = sorted(t["verdict"] for t in traces)
    ok = approval["status"] == "used" and verdicts.count("allow") == 1
    rows.append(
        (
            "gateway: approval used once",
            ok,
            f"approval {approval['status']}; cancel traces {verdicts}",
        )
    )
    return rows


def check_watched(turns: Turns, since: str) -> tuple[str, bool, str]:
    """Personal data: the baseline pack watches, so the turn runs and the trace says
    what enforcing would have done."""
    label = "personal data watched, not blocked"
    stopped = turns[0].get("stopped")
    if stopped and (turns[0].get("info") or {}).get("trace_id"):
        return label, False, f"AgentFox stopped it: {stopped}"
    traces = api("GET", "/api/traces", params={"agent": AGENT, "start": since, "limit": 500})[
        "traces"
    ]
    watched = [
        t
        for t in traces
        if any(r.startswith("pii.") for r in t["rules"])
        and t["verdict"] == "allow"
        and t["would_verdict"] == "block"
    ]
    if not watched:
        return label, False, "no trace with a watching pii rule"
    rules = sorted({r for t in watched for r in t["rules"] if r.startswith("pii.")})
    # The app's own LLM jailbreak guardrail sometimes refuses this turn; that is the
    # app's decision, and the gateway still watched the calls that reached it.
    outcome = f"app's {stopped.split(' ', 2)[-1]} refused" if stopped else "answered"
    return label, True, f"{outcome}; {len(watched)} traces allow, would block ({', '.join(rules)})"


def check_records(since: str) -> tuple[str, bool, str]:
    traces = api("GET", "/api/traces", params={"agent": AGENT, "start": since, "limit": 500})[
        "traces"
    ]
    access = api("GET", f"/api/agents/{AGENT}/access", params={"days": 1})
    used = {c["tool_key"]: c["usage"] for c in access["capabilities"]}
    held = sum(u["held"] for u in used.values())
    called = sum(1 for u in used.values() if u["calls"])
    ok = len(traces) > 0 and held >= 2 and called >= 3
    return (
        "gateway: traces and tool usage recorded",
        ok,
        f"{len(traces)} traces this run; {called} tools used, {held} calls held",
    )


async def drive_all(auto_approve: bool) -> tuple[dict[str, Turns], dict[str, Any]]:
    transcripts = await run([name for name, _, _ in CHECKS] + ["pii"])
    print("cancellation with approval:")
    return transcripts, await approval_flow.run(auto_approve)


def configured() -> bool:
    modes = [api("GET", f"/api/policies/{key}").get("mode") for key in (f"agent.{AGENT}", "custom")]
    return modes == ["enforce", "enforce"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--auto-approve", action="store_true", help="approve through the API")
    args = parser.parse_args()
    if not configured():
        print("the gateway is not configured for the demo: run configure.py first")
        return 1

    since = dt.datetime.now(dt.UTC).isoformat()
    started = time.monotonic()
    # One event loop for everything: the app's OpenAI client is bound to the first.
    transcripts, outcome = asyncio.run(drive_all(args.auto_approve))
    rows: list[tuple[str, bool, str]] = []
    for name, label, check in CHECKS:
        try:
            ok, detail = check(transcripts[name])
        except Exception as exc:  # noqa: BLE001 - a broken check is a failed check
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        rows.append((label, ok, detail))
    rows.append(check_watched(transcripts["pii"], since))
    rows += check_approval(outcome, since)
    rows.append(check_records(since))

    width = max(len(label) for label, _, _ in rows)
    print()
    for label, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {label:<{width}}  {detail}")
    failed = sum(1 for _, ok, _ in rows if not ok)
    print(f"\n{len(rows) - failed}/{len(rows)} passed in {time.monotonic() - started:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
