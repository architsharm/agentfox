"""#1 — a ladder's own `mode` decides whether its outcome is applied.

The outcome used to follow whichever policy pack governed the decision: an
observe-mode ladder still escalated once `tool-containment` (enforce) was bound,
and an enforce-mode ladder was only recorded when no enforcing pack fired.
"""

from __future__ import annotations

from agentfox.capabilities.business import Ladder, save_ladder
from agentfox.core.db import session_scope
from agentfox.core.models import Agent
from agentfox.fixtures.seed import seed
from agentfox.platform.identity import ensure_identity, grant_capability
from agentfox.platform.policy import set_mode
from agentfox.runtime.enforcement import Enforcer

REFUND = {
    "key": "refund-approval",
    "tool": "payments.refund",
    "field": "arguments.amount",
    "unit": "USD",
    "bands": [
        {"upto": 10, "outcome": "allow"},
        {"outcome": "escalate", "approver_role": "finance"},
    ],
}


def _refund(ladder_mode: str, *, policies_mode: str | None = None):
    with session_scope() as session:
        seed(session)
        if policies_mode is not None:
            for key in ("baseline", "tool-containment", "eu-ai-act-high-risk"):
                set_mode(session, key, policies_mode)
        save_ladder(session, Ladder.model_validate({**REFUND, "mode": ladder_mode}))
        agent = session.query(Agent).filter_by(slug="payments-ops").one()
        grant_capability(session, ensure_identity(session, agent), "payments.refund")

    with session_scope() as session:
        return Enforcer(session).guard_tool_call(
            agent_slug="payments-ops", tool_key="payments.refund", arguments={"amount": 250}
        )


def _ladder_rule(result) -> dict:
    return next(r for r in result.rules_fired if r["rule_id"] == "business.refund-approval")


def test_an_observe_ladder_is_recorded_not_applied_under_an_enforcing_pack(isolated_db):
    result = _refund("observe")  # seed binds tool-containment in enforce
    assert result.effective_verdict == "escalate"
    assert result.verdict == "allow"
    assert _ladder_rule(result)["mode"] == "observe"


def test_an_enforce_ladder_is_applied_when_every_pack_observes(isolated_db):
    result = _refund("enforce", policies_mode="observe")
    assert result.verdict == "escalate"
    assert result.effective_verdict == "escalate"
    assert _ladder_rule(result)["mode"] == "enforce"
