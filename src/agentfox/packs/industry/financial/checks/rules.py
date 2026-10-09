# Rules translated from examples/policies/production/rego/ in https://github.com/microsoft/agent-governance-toolkit
# (commit c767f83). Copyright (c) Microsoft Corporation. Licensed under the MIT License;
# full text in THIRD_PARTY_NOTICES.md. Translated into an AgentFox rule table; see this
# pack's README for what was translated, how, and what was left out.

"""The rule table behind the industry/financial policies: one risk code per translated rule.

Each rule's code is the policy rule id that turns it into an effect (`action_risk`).
Rules whose only test is a single tool name are policy conditions instead, and are
not in this table. `agentfox.platform.packs.rule_table` documents the conditions."""

from __future__ import annotations

from typing import Any

from agentfox.platform.checks import CheckContext, check
from agentfox.platform.packs.rule_table import TableRule, run

R = TableRule

#: Policy key -> its translated rules, in source order.
TABLES: dict[str, tuple[TableRule, ...]] = {
    "industry-financial": (
        R(
            "industry-financial.credit-card-number-detected",
            "deny",
            "PCI: Credit card number detected",
            (("text", "\\b(?:\\d[ -]*?){13,16}\\b"),),
        ),
        R(
            "industry-financial.ssn-pattern-detected",
            "deny",
            "PII: SSN pattern detected",
            (("text", "\\b\\d{3}-\\d{2}-\\d{4}\\b"),),
        ),
        R(
            "industry-financial.financial-transactions-require-compliance-approval",
            "escalate",
            "Financial transactions require compliance approval",
            (("action_re", "transfer_|payment_|trade_"),),
        ),
    ),
}

RULES: tuple[TableRule, ...] = tuple(rule for table in TABLES.values() for rule in table)


@check("pack.industry.financial", surfaces=["input", "output", "tool_args"])
def rules_industry_financial(ctx: CheckContext) -> dict[str, Any]:
    """Raises a risk for every translated industry/financial rule this call matches."""
    return run(RULES, ctx, args_as_text=True)
