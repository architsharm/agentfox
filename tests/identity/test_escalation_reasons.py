"""Why a call was held for a person must name the real cause (#16, #86)."""

from __future__ import annotations

import pytest

from agentfox.sdk import AgentFox, ApprovalRequired


def test_a_taint_ceiling_escalation_names_the_argument_not_the_grant(seeded):
    """support-triage holds crm.lookup with max_taint 'user' and no approval
    requirement. A customer id copied out of a tool result is held because of where
    the argument came from — saying "the granting capability requires human
    approval" sends the reader to a grant that requires nothing of the sort."""
    fox = AgentFox("support-triage", session=seeded)
    with fox.session(intent="look up the customer") as s:
        with pytest.raises(ApprovalRequired) as held:
            s.guard_tool(
                "crm.lookup",
                {"customer_id": "cus_123456"},
                provenance={"customer_id": "tool_result"},
            )

    reason = str(held.value)
    assert "granting capability requires human approval" not in reason
    assert "customer_id" in reason
    assert "tool_result" in reason
    assert "max_taint 'user'" in reason
    rule = next(
        r for r in held.value.result.rules_fired if r["rule_id"] == "capability.approval_required"
    )
    assert "customer_id" in rule["reason"]


def test_a_grant_that_requires_approval_still_says_so(seeded):
    """payments-ops holds email.send with requires_approval: the original sentence
    is the true one there and stays."""
    fox = AgentFox("payments-ops", session=seeded)
    with fox.session(intent="email the customer their receipt") as s:
        with pytest.raises(ApprovalRequired) as held:
            s.guard_tool(
                "email.send",
                {"to": "customer@example.com", "body": "receipt"},
                provenance={"to": "user", "body": "user"},
            )
    assert "The granting capability requires human approval for this action." in str(held.value)
