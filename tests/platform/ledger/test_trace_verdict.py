"""A trace must report the strongest thing that happened on it.

`Trace.verdict` defaults to "allow" and used to be written only by `end_trace`,
which is called from the completion path alone — `preflight`,
`_finish_completion`, `run_completion_stream`. Nothing on the tool-call path
called it, so a trace whose tool call was blocked or escalated sat in the
database, and in the Traces list, reading `allow`.

That is the worst direction for the error to run in. Tool containment is the
control this product sells as the one that holds after a content filter has been
fooled (see test_containment_under_bypass.py), and every trace it acted on
reported that nothing had happened. The containment tests all passed throughout,
because they assert on the EnforcementResult and never looked at the row an
operator actually reads.

These pin the row.
"""

from __future__ import annotations

import pytest

from agentfox.platform.ledger.trace import start_trace
from agentfox.platform.registry.service import slugify

CONTAINED = {"block", "escalate"}


def _trace(session, enforcer, agent_slug: str, intent: str):
    agent, _identity, _shadow = enforcer.resolve(agent_slug)
    return start_trace(
        session,
        agent_id=agent.id if agent else None,
        agent_slug=slugify(agent_slug),
        session_id="trace-verdict-test",
        intent=intent,
    )


@pytest.mark.parametrize(
    "agent,tool,arguments,provenance",
    [
        # No capability grant at all — default deny.
        ("support-triage", "payments.transfer", {"amount": 50000, "to": "acct_x"}, None),
        # Granted, but the call is destructive and unbounded.
        ("support-triage", "db.query", {"sql": "DELETE FROM customers"}, None),
        # Granted and bounded, but the argument came from retrieved content.
        (
            "support-triage",
            "redteam.sim.close_account",
            {"account_id": "ACCT-4471982"},
            {"account_id": "retrieved"},
        ),
    ],
)
def test_a_contained_tool_call_leaves_the_trace_contained(
    seeded, enforcer, agent, tool, arguments, provenance
):
    trace = _trace(seeded, enforcer, agent, "contained call")
    result = enforcer.guard_tool_call(
        agent_slug=agent,
        tool_key=tool,
        arguments=arguments,
        provenance=provenance,
        intent="contained call",
        trace=trace,
    )
    seeded.flush()
    seeded.refresh(trace)

    assert result.verdict in CONTAINED, result.to_json()
    # The row an operator reads must agree with the decision that was made.
    assert trace.verdict == result.verdict
    assert trace.status != "ok"


def test_an_allowed_tool_call_leaves_the_trace_allowed(seeded, enforcer):
    """The fix must not over-report: a clean call stays clean."""
    trace = _trace(seeded, enforcer, "support-triage", "ordinary lookup")
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="crm.lookup",
        arguments={"customer": "cus_1"},
        intent="ordinary lookup",
        trace=trace,
    )
    seeded.flush()
    seeded.refresh(trace)

    assert result.verdict == "allow"
    assert trace.verdict == "allow"
    assert trace.status == "ok"


def test_one_blocked_call_survives_later_allowed_ones(seeded, enforcer):
    """A trace is one request and carries many decisions.

    The verdict is a high-water mark, not last-write-wins: an agent that is
    refused a transfer and then makes three ordinary lookups has had something
    stopped, and a trace list that showed `allow` for it would be hiding exactly
    the event it exists to record.
    """
    trace = _trace(seeded, enforcer, "support-triage", "blocked, then fine")
    blocked = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="payments.transfer",
        arguments={"amount": 50000, "to": "acct_x"},
        intent="blocked, then fine",
        trace=trace,
    )
    assert blocked.verdict in CONTAINED

    for _ in range(3):
        enforcer.guard_tool_call(
            agent_slug="support-triage",
            tool_key="crm.lookup",
            arguments={"customer": "cus_1"},
            intent="blocked, then fine",
            trace=trace,
        )

    seeded.flush()
    seeded.refresh(trace)
    assert trace.verdict == blocked.verdict
