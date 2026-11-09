"""A decision's ``mode`` is the mode of what decided it (audit 2026-11-08, B1): a
transfer held for a person read ``mode: observe`` because a watching pack fired the
same effect first."""

from __future__ import annotations

from agentfox.runtime.enforcement.enforcer import _deciding_mode


def test_an_applied_verdict_reads_enforce_whatever_the_packs_mode():
    assert _deciding_mode("escalate", "escalate", "observe") == "enforce"
    assert _deciding_mode("block", "block", "observe") == "enforce"


def test_a_verdict_only_recorded_reads_observe():
    assert _deciding_mode("allow", "block", "enforce") == "observe"


def test_nothing_fired_keeps_the_binding():
    assert _deciding_mode("allow", "allow", "enforce") == "enforce"
    assert _deciding_mode("allow", "allow", "observe") == "observe"


def test_a_tool_call_held_by_an_enforcing_pack_reports_enforce(enforcer):
    """Every pack watching except tool-containment, which holds an irreversible call
    with no task; the response's mode says the rule that held it enforces."""
    result = enforcer.guard_tool_call(
        agent_slug="payments-ops",
        tool_key="payments.transfer",
        arguments={"amount": 50, "to": "acct-1"},
        dry_run=False,
    )
    if result.verdict in ("block", "escalate"):
        assert result.mode == "enforce", result.to_json()
    elif result.effective_verdict != "allow":
        assert result.mode == "observe"
