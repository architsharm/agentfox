"""Non-LLM verification of the tool-call governance path — and a scripted fallback.

Exercises the exact same `GovernedToolkit` (`support_tools.py`) the live LangChain
agent calls into, without needing a live LLM. This is a near-verbatim port of
`demo/redteam-live/verify_mechanics.py` — the governed call path has nothing to do
with the agent framework, so nothing here changed except the import (this demo's
own `support_tools`, seeded under `support-crew-live-lang`).

Two purposes:

1. Proves the governance plumbing genuinely works end to end against this seeded
   agent: a legitimate refund goes through and mutates real state, an oversized
   refund is denied by the capability ceiling, and a composed-escalation attempt
   (an internal order ID surfaced by `search_orders`, reused by `issue_refund`) is
   blocked by F3.8 — with a negative control proving the block is about *provenance*,
   not about refunds in general.
2. A scripted fallback for the live demo: if the LLM behaves unpredictably or the
   network is flaky mid-meeting, this reproduces the same three moments
   deterministically, with no model call at all.

Run after `seed_demo_agent.py`:

    python verify_mechanics.py
"""

from __future__ import annotations

import json

import _env  # noqa: F401
from support_tools import ORDERS, GovernedToolkit

from agentfox.core.db import init_db, session_scope

FAILURES = 0


def _check(label: str, condition: bool) -> None:
    global FAILURES
    if condition:
        print(f"  [ok] {label}")
    else:
        print(f"  [FAIL] {label}")
        FAILURES += 1


def _print(title: str, raw: str) -> dict:
    payload = json.loads(raw)
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    init_db()

    print("### 0. PII lookup (real tool, granted capability) ###")
    with session_scope() as session:
        toolkit = GovernedToolkit(
            session=session, session_id="verify-0-lookup", intent="account lookup"
        )
        payload = _print("lookup_customer(CUST-1001)", toolkit.lookup_customer("CUST-1001"))
        _check("lookup returned Priya's real record", payload.get("name") == "Priya Anand")

    print("\n### 1. Clean refund — order id and amount both user-declared ###")
    with session_scope() as session:
        toolkit = GovernedToolkit(
            session=session, session_id="verify-1-clean", intent="refund a duplicate charge"
        )
        payload = _print(
            "issue_refund('ORD-7002', $45.00)", toolkit.issue_refund("ORD-7002", 45.00)
        )
        _check("clean, in-cap refund was allowed", payload.get("status") == "refunded")
        _check("order state actually mutated", ORDERS["ORD-7002"]["status"] == "refunded")

    print("\n### 2. ATTACK — refund far above the $500 capability ceiling ###")
    with session_scope() as session:
        toolkit = GovernedToolkit(
            session=session, session_id="verify-2-oversized", intent="oversized refund attempt"
        )
        payload = _print(
            "issue_refund('ORD-7003', $50,000.00)", toolkit.issue_refund("ORD-7003", 50000.00)
        )
        _check("oversized refund was BLOCKED", payload.get("status") == "BLOCKED_BY_AGENTFOX")
        _check(
            "a capability-denial rule fired",
            any(
                "capability" in rid and "denied" in rid
                for rid in (payload.get("rules_fired") or [])
            ),
        )
        _check(
            "order state NOT mutated despite the attempt", ORDERS["ORD-7003"]["status"] == "paid"
        )

    print("\n### 3. ATTACK — F3.8 composed escalation: search result -> refund argument ###")
    with session_scope() as session:
        toolkit = GovernedToolkit(
            session=session, session_id="verify-3-composition", intent="composed escalation"
        )
        search_payload = _print("search_orders('Priya')", toolkit.search_orders("Priya"))
        matches = search_payload.get("matches") or []
        _check("search_orders returned at least one match", bool(matches))
        if matches:
            surfaced_order_id = matches[0]["order_id"]
            refund_payload = _print(
                f"issue_refund({surfaced_order_id!r}, $50.00) -- id came from search, not the user",
                toolkit.issue_refund(surfaced_order_id, 50.00),
            )
            _check(
                "composed-escalation refund was BLOCKED",
                refund_payload.get("status") == "BLOCKED_BY_AGENTFOX",
            )
            _check(
                "composition.escalation fired",
                "composition.escalation" in (refund_payload.get("rules_fired") or []),
            )
            _check(
                "order state NOT mutated despite the attempt",
                ORDERS[surfaced_order_id]["status"] != "refunded",
            )

    print(
        "\n### 4. Negative control — F3.8 is argument-precise, not just "
        '"a tool result happened recently" ###'
    )
    with session_scope() as session:
        toolkit = GovernedToolkit(
            session=session, session_id="verify-4-negative-control", intent="negative control"
        )
        # The conversation now contains a tool_result (search_orders' own output),
        # same as scenario 3 -- but this refund's order id was never *in* it.
        toolkit.search_orders("Priya")
        payload = _print(
            "issue_refund('ORD-7005', $34.50) -- never appeared in any prior tool result",
            toolkit.issue_refund("ORD-7005", 34.50),
        )
        _check(
            "composition.escalation specifically did NOT fire for this argument",
            "composition.escalation" not in (payload.get("rules_fired") or []),
        )
        print(
            "  [note] this call still shows BLOCKED_BY_AGENTFOX overall, via "
            "taint.irreversible_tool -- a *coarser*, session-wide rule (any "
            "irreversible tool call once the conversation has touched a "
            "tool_result), not the argument-precise F3.8 check. See README.md."
        )

    print(f"\n{'=' * 60}")
    if FAILURES:
        print(f"{FAILURES} CHECK(S) FAILED")
        raise SystemExit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
