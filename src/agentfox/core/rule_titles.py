"""Rules by name: what a person reads where a rule id would be.

`RULE_TITLES` mirrors the dashboard's (``RULE_TITLES`` in
``dashboard/lib/product/vocab.ts``), so a refusal raised in the user's own process
(`agentfox.Blocked`) names a rule the way the dashboard does;
``tests/core/test_rule_titles.py`` keeps the two in step. `rule_title` falls back the
way the dashboard's ``ruleTitle`` does.
"""

from __future__ import annotations

#: Mirrors ``RULE_TITLES`` in dashboard/lib/product/vocab.ts.
RULE_TITLES: dict[str, str] = {
    "agent.quarantined": "Agent paused",
    "agent.killed": "Agent stopped",
    "agent.circuit_open": "Circuit breaker open",
    "injection.direct": "Jailbreaks & prompt injection",
    "injection.indirect": "Injection in documents or tool results",
    "injection.system_prompt_leak": "System prompt extraction",
    "injection.memory_and_agent_message": "Injection via memory or other agents",
    "injection.adopted_in_reasoning": "Injected instructions in reasoning",
    "injection.in_tool_arguments": "Injected instructions in tool calls",
    "secrets.block": "Secrets & API keys",
    "secrets.credential_file": "Credential files",
    "secrets.in_tool_arguments": "Secrets sent to tools",
    "pii.outbound_redact": "Personal data in replies",
    "pii.inbound_tokenize": "Personal data sent to models",
    "pii.high_sensitivity": "ID numbers & payment cards",
    "pii.memory_and_agent_message": "Personal data in memory or between agents",
    "safety.harm": "Harmful or toxic content",
    "schema.violation": "Reply in the wrong format",
    "pipeline.degraded_high_risk": "High-risk agent with degraded checks",
    "eu.art14.human_oversight": "Human sign-off on irreversible actions",
    "eu.art14.no_covert_action": "Acting without telling the user",
    "eu.art15.no_degraded_enforcement": "Degraded protection on high-risk agents",
    "eu.art15.injection_resistance": "Hijack attempts on high-risk agents",
    "eu.art10.special_category_data": "Special-category data to third parties",
    "eu.art50.impersonation": "AI claiming to be human",
    "eu.art5.prohibited_tier": "Prohibited AI systems",
    "taint.irreversible_tool": "Irreversible actions on untrusted data",
    "taint.high_impact_tool": "High-impact actions on untrusted data",
    "taint.write_from_tool_result": "Writes copied from tool output",
    "capability.denied": "Tools the agent wasn't given",
    "capability.constraint_violated": "Calls outside allowed limits",
    "capability.approval_required": "Actions that need approval",
    "intent.undeclared_irreversible": "Irreversible action with no task",
    "budget.exceeded": "Spending or usage limit",
    "loop.runaway": "Runaway loops",
    "completion.unverified_claim": "Done without proof",
    "completion.irreversible_unconfirmed": "Irreversible action not confirmed",
    "tool.not_declared": "Unknown or made-up tools",
    "action.remote_code_execution": "Running downloaded code",
    "action.supply_chain_publish": "Publishing packages",
    "action.infrastructure_mutation": "Changing live infrastructure",
    "action.history_rewrite": "Destroying history",
    "control_plane.tamper": "Disabling AgentFox",
    "cascade.reaches_destructive": "Triggers a destructive action",
    "cascade.reaches_notification": "Triggers an unrecallable message",
    "cascade.cycle": "Trigger loops",
    "cascade.blast_radius": "Large blast radius",
    "access.unscoped_table": "Queries beyond the caller's rows",
    "access.undeclared_table": "Queries on undeclared tables",
    "intent.misaligned": "Actions off the user's task",
    "code.insecure": "Insecure code",
    "grounding.unsupported": "Answers not backed by sources",
    "answerability.unknowable": "Questions nobody can know (abstained)",
    "answerability.out_of_coverage": "Outside the history it covers (abstained)",
    "answerability.out_of_scope_entity": "About something it does not know (abstained)",
    "answerability.unsupported_question_type": "A kind of question it may not answer (abstained)",
    "answerability.out_of_domain": "Outside its topics (abstained)",
}

#: Rules raised in process, which the dashboard does not list under these ids.
_PROCESS_TITLES: dict[str, str] = {
    "capability.default_deny": "Tools the agent wasn't given",
    "capability.requires_approval": "Actions that need approval",
    "autoguard.fail_closed": "Checks unavailable, so the call was refused",
}

_ACRONYMS = {"PII", "API", "URL", "SQL", "ID", "LLM", "MCP", "AI", "EU"}


def rule_title(rule_id: str, description: str | None = None) -> str:
    """A rule's name. A custom rule is named by its author: pass its description
    (a fired custom rule's reason starts with it)."""
    rule_id = str(rule_id or "")
    if rule_id in RULE_TITLES:
        return RULE_TITLES[rule_id]
    if rule_id in _PROCESS_TITLES:
        return _PROCESS_TITLES[rule_id]
    if rule_id.startswith("watch.") and description:
        return description
    if rule_id.startswith("custom.") and description:
        return description.split(": your rule")[0].split(" — your rule")[0]
    tail = " ".join(rule_id.split(".")[1:]) or rule_id
    words = [
        w.upper() if w.upper() in _ACRONYMS else w
        for w in tail.replace("_", " ").replace("-", " ").split()
    ]
    text = " ".join(words)
    return text[:1].upper() + text[1:]
