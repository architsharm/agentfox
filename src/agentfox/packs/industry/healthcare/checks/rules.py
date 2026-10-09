# Rules translated from examples/policies/production/rego/ in https://github.com/microsoft/agent-governance-toolkit
# (commit c767f83). Copyright (c) Microsoft Corporation. Licensed under the MIT License;
# full text in THIRD_PARTY_NOTICES.md. Translated into an AgentFox rule table; see this
# pack's README for what was translated, how, and what was left out.

"""The rule table behind the industry/healthcare policies: one risk code per translated rule.

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
    "industry-healthcare": (
        R(
            "industry-healthcare.ssn-pattern-detected",
            "deny",
            "PHI: SSN pattern detected",
            (("text", "\\b\\d{3}-\\d{2}-\\d{4}\\b"),),
        ),
        R(
            "industry-healthcare.medical-record-number-detected",
            "deny",
            "PHI: Medical Record Number detected",
            (("text", "(?i)MRN[:\\s]*\\d{6,}"),),
        ),
        R(
            "industry-healthcare.deletion-prohibited-healthcare",
            "deny",
            "Deletion prohibited in healthcare",
            (("action_re", "^delete_"),),
        ),
        R(
            "industry-healthcare.clinical-data-requires-clinician-approval",
            "escalate",
            "Clinical data requires clinician approval",
            (("action_re", "patient_|clinical_|medical_"),),
        ),
    ),
}

RULES: tuple[TableRule, ...] = tuple(rule for table in TABLES.values() for rule in table)


@check("pack.industry.healthcare", surfaces=["input", "output", "tool_args"])
def rules_industry_healthcare(ctx: CheckContext) -> dict[str, Any]:
    """Raises a risk for every translated industry/healthcare rule this call matches."""
    return run(RULES, ctx, args_as_text=True)
