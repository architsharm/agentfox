# Rules translated from examples/policies/uk-regulatory/rego/ in https://github.com/microsoft/agent-governance-toolkit
# (commit c767f83). Copyright (c) Microsoft Corporation. Licensed under the MIT License;
# full text in THIRD_PARTY_NOTICES.md. Translated into an AgentFox rule table; see this
# pack's README for what was translated, how, and what was left out.

"""The rule table behind the regional/uk policies: one risk code per translated rule.

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
    "uk-fca-conduct": (
        R(
            "uk-fca-conduct.consumer-harm-language",
            "deny",
            "FCA Consumer Duty (PRIN 2A): agent cannot propose actions that foreseeably harm customers",
            (
                (
                    "text",
                    "(?i)(mislead\\s+(the\\s+)?customer|hide\\s+(fees|charges|risks)|exploit\\s+(vulnerability|vulnerabilities)|target\\s+vulnerable\\s+customer|dark\\s+pattern|push\\s+unsuitable\\s+product)",
                ),
            ),
        ),
        R(
            "uk-fca-conduct.fair-value-bypass",
            "deny",
            "FCA Consumer Duty (PRIN 2A.4): firms must ensure products and services provide fair value",
            (
                (
                    "text",
                    "(?i)(skip\\s+fair\\s+value|bypass\\s+value\\s+assessment|no\\s+need\\s+to\\s+(check|assess)\\s+(fair\\s+)?value|ignore\\s+consumer\\s+duty)",
                ),
            ),
        ),
        R(
            "uk-fca-conduct.accountability-delegation-ai",
            "deny",
            "FCA SM&CR: senior managers remain accountable for AI risks — delegating to an algorithm does not transfer responsibility",
            (
                (
                    "text",
                    "(?i)(the\\s+ai\\s+(decides|is\\s+responsible)|algorithm\\s+accountable|no\\s+senior\\s+manager\\s+(needed|required)|delegate\\s+accountability\\s+to\\s+(the\\s+)?(model|ai|algorithm))",
                ),
            ),
        ),
        R(
            "uk-fca-conduct.autonomous-trading-without-platform-documented-approval",
            "deny",
            "FCA market conduct: autonomous agent trading requires documented governance and senior manager approval",
            (
                (
                    "action_in",
                    (
                        "agent_place_order",
                        "autonomous_trade",
                        "execute_trade_without_approval",
                        "self_directed_trading",
                    ),
                ),
            ),
        ),
        R(
            "uk-fca-conduct.pricing-without-assessment",
            "escalate",
            "FCA Consumer Duty: AI-influenced pricing or eligibility decision — document testing for fairness and foreseeable harm",
            (
                (
                    "action_in",
                    (
                        "adjust_rate",
                        "calculate_premium",
                        "determine_eligibility",
                        "score_creditworthiness",
                        "set_price",
                    ),
                ),
                ("not_param", "consumer_duty_assessed", "==", True),
            ),
        ),
        R(
            "uk-fca-conduct.customer-communications",
            "audit",
            "FCA Consumer Duty: AI-generated customer communication — verify clarity, accuracy, and information needs",
            (
                (
                    "action_in",
                    (
                        "create_marketing_content",
                        "draft_product_recommendation",
                        "generate_customer_communication",
                        "send_financial_advice",
                    ),
                ),
            ),
        ),
        R(
            "uk-fca-conduct.third-party-ai",
            "audit",
            "FCA operational resilience: third-party AI component — map to governance, testing, and critical third-party risk",
            (
                (
                    "action_in",
                    (
                        "call_third_party_model",
                        "deploy_critical_third_party_ai",
                        "invoke_external_ai",
                        "use_vendor_ai",
                    ),
                ),
            ),
        ),
    ),
    "uk-automated-decisions": (
        R(
            "uk-automated-decisions.withhold-explanation",
            "deny",
            "UK GDPR Art. 22C(1): individuals must receive decision-specific information explaining how and why the outcome was reached",
            (
                (
                    "text",
                    "(?i)((don'?t|do\\s+not)\\s+explain|no\\s+explanation|withhold\\s+(the\\s+)?(reason|rationale)|hide\\s+how\\s+(the\\s+)?decision|refuse\\s+to\\s+explain)",
                ),
            ),
        ),
        R(
            "uk-automated-decisions.block-human-review",
            "deny",
            "UK GDPR Art. 22C(2)-(3): individuals must be able to make representations and obtain genuine human intervention",
            (
                (
                    "text",
                    "(?i)(no\\s+human\\s+(review|intervention|oversight)|refuse\\s+human\\s+review|cannot\\s+request\\s+human|deny\\s+human\\s+intervention|automated\\s+only\\s*[—\\-–]\\s*no\\s+appeal)",
                ),
            ),
        ),
        R(
            "uk-automated-decisions.block-contest-right",
            "deny",
            "UK GDPR Art. 22C(4): individuals must be able to contest the decision through an accessible process",
            (
                (
                    "text",
                    "(?i)(cannot\\s+contest|no\\s+(right\\s+to\\s+)?(appeal|challenge)|final\\s+decision\\s*[—\\-–]\\s*no\\s+recourse|waive\\s+(the\\s+)?right\\s+to\\s+contest)",
                ),
            ),
        ),
        R(
            "uk-automated-decisions.special-category-adm-explicit-consent-or",
            "deny",
            "UK GDPR Art. 22B: automated decisions based on special category data require explicit consent or legal authorisation — human review alone is insufficient",
            (
                (
                    "action_in",
                    (
                        "automated_decision_on_biometric",
                        "automated_decision_on_health",
                        "automated_decision_on_special_category",
                    ),
                ),
            ),
        ),
        R(
            "uk-automated-decisions.significant-decision-without-safeguards-metadata",
            "escalate",
            "UK GDPR Art. 22A: solely automated significant decision — verify Art. 22C safeguards (information, representations, human intervention, contest)",
            (
                (
                    "action_in",
                    (
                        "automated_credit_decision",
                        "automated_eligibility",
                        "automated_hiring_decision",
                        "deploy_scoring_model",
                        "profile_for_decision",
                        "run_automated_decision",
                    ),
                ),
                ("not_param", "human_review_available", "==", True),
            ),
        ),
        R(
            "uk-automated-decisions.significant-decision-without-explanation",
            "escalate",
            "UK GDPR Art. 22C(1): decision-specific explanation must be available to the individual",
            (
                (
                    "action_in",
                    (
                        "automated_credit_decision",
                        "automated_eligibility",
                        "automated_hiring_decision",
                        "deploy_scoring_model",
                        "profile_for_decision",
                        "run_automated_decision",
                    ),
                ),
                ("not_param", "explanation_provided", "==", True),
            ),
        ),
        R(
            "uk-automated-decisions.recruitment-adm-language",
            "escalate",
            "ICO March 2026: automated recruitment decisions are in scope of Art. 22A — review safeguards before proceeding",
            (
                (
                    "text",
                    "(?i)(reject\\s+(the\\s+)?(candidate|applicant)|hire\\s+decision|shortlist|score\\s+(the\\s+)?(candidate|applicant)).{0,40}(automated|without\\s+human|ai\\s+only)",
                ),
            ),
        ),
        R(
            "uk-automated-decisions.agentic-orchestration-step",
            "escalate",
            "UK GDPR Art. 22A (agentic AI): each orchestration step taking a solely automated significant decision must meet Art. 22C safeguards and Art. 28 processor contracts",
            (
                (
                    "action_in",
                    (
                        "chain_automated_step",
                        "delegate_decision",
                        "orchestrate_agent",
                        "spawn_sub_agent",
                    ),
                ),
            ),
        ),
        R(
            "uk-automated-decisions.dpia-deployment",
            "audit",
            "UK GDPR Art. 35: data protection impact assessment required before deploying high-risk automated decision-making",
            (
                (
                    "action_in",
                    (
                        "deploy_agent",
                        "deploy_model",
                        "launch_automated_system",
                        "scale_automated_decisions",
                    ),
                ),
            ),
        ),
        R(
            "uk-automated-decisions.significant-decision-audit-trail",
            "audit",
            "UK GDPR Art. 22A: solely automated significant decision logged — verify lawful basis and Art. 22C safeguards",
            (
                (
                    "action_in",
                    (
                        "automated_credit_decision",
                        "automated_eligibility",
                        "automated_hiring_decision",
                        "deploy_scoring_model",
                        "profile_for_decision",
                        "run_automated_decision",
                    ),
                ),
            ),
        ),
    ),
    "uk-gdpr": (
        R(
            "uk-gdpr.block-breach-suppression",
            "deny",
            "UK GDPR Art. 33: where a breach is likely to result in a risk to rights and freedoms, notify the ICO without undue delay and, where feasible, within 72 hours — agent cannot suppress or delay notification",
            (
                (
                    "text",
                    "(?i)((don'?t|do\\s+not)\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(the\\s+)?(breach|notification)|delay\\s+(breach|incident)\\s+(report|notification)|wait\\s+before\\s+report(ing)?\\s+(to\\s+)?(the\\s+)?ico)",
                ),
            ),
        ),
        R(
            "uk-gdpr.block-suppression-individual-notification",
            "deny",
            "UK GDPR Art. 34: individuals must be informed without undue delay where breach poses high risk",
            (
                (
                    "text",
                    "(?i)((don'?t|do\\s+not)\\s+(tell|inform|notify)\\s+(the\\s+)?(data\\s+subject|individual|customer|user)|hide\\s+(breach|incident)\\s+from\\s+(customer|user|individual))",
                ),
            ),
        ),
        R(
            "uk-gdpr.block-unencrypted-personal-data-handling-output",
            "deny",
            "UK GDPR Art. 32: personal data must be processed with appropriate technical and organisational security measures proportionate to risk (encryption, access control, or equivalent safeguards)",
            (
                (
                    "text",
                    "(?i)(store|transmit|log|cache).{0,30}(personal\\s+data|pii).{0,30}(unencrypted|plaintext|clear\\s*text|without\\s+encryption)",
                ),
            ),
        ),
        R(
            "uk-gdpr.block-complaints-bypass",
            "deny",
            "DPA 2018 s.164A (DUAA): data subjects must be able to raise data protection complaints with the controller (30-day acknowledgment) before ICO escalation",
            (
                (
                    "text",
                    "(?i)(skip|bypass|ignore|refuse).{0,30}(data\\s+protection\\s+complaint|ico\\s+complaint|complaints?\\s+(process|procedure|handling))",
                ),
            ),
        ),
        R(
            "uk-gdpr.nhs-number-output",
            "deny",
            "UK GDPR: NHS number detected in agent output — blocked to prevent health identity exposure",
            (
                (
                    "text",
                    "(?i)(national\\s+health\\s+service|nhs)\\s*(number|no\\.?|ref(?:erence)?)?(?:\\s+(?:is|of))?[\\s:=]{0,5}[0-9]{3}[\\s-]?[0-9]{3}[\\s-]?[0-9]{4}",
                ),
            ),
        ),
        R(
            "uk-gdpr.national-insurance-number-output",
            "deny",
            "UK GDPR: National Insurance number detected in agent output — blocked to prevent identity exposure",
            (
                (
                    "text",
                    "(?i)(national\\s+insurance|ni)\\s*(number|no\\.?)?(?:\\s+(?:is|of))?[\\s:=]{0,5}[A-Z]{2}[\\s-]?[0-9]{2}[\\s-]?[0-9]{2}[\\s-]?[0-9]{2}[\\s-]?[A-D]",
                ),
            ),
        ),
        R(
            "uk-gdpr.block-transfer-without-adequacy-platform-set",
            "deny",
            "UK GDPR Art. 44–46: transfer to <value> blocked — requires adequacy, IDTA/UK Addendum safeguards, and data protection test (DUAA 'not materially lower' standard)",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "transfer_personal_data",
                        "upload_to_cloud",
                    ),
                ),
                ("param_set", "destination_country"),
                (
                    "not_param",
                    "destination_country",
                    "in",
                    (
                        "AD",
                        "AR",
                        "AT",
                        "BE",
                        "BG",
                        "CH",
                        "CY",
                        "CZ",
                        "DE",
                        "DK",
                        "EE",
                        "ES",
                        "FI",
                        "FO",
                        "FR",
                        "GB",
                        "GG",
                        "GI",
                        "GR",
                        "HR",
                        "HU",
                        "IE",
                        "IL",
                        "IM",
                        "IS",
                        "IT",
                        "JE",
                        "KR",
                        "LI",
                        "LT",
                        "LU",
                        "LV",
                        "MT",
                        "NL",
                        "NO",
                        "NZ",
                        "PL",
                        "PT",
                        "RO",
                        "SE",
                        "SI",
                        "SK",
                        "UY",
                    ),
                ),
            ),
        ),
        R(
            "uk-gdpr.block-large-exports-without-review",
            "deny",
            "UK GDPR Art. 5(1)(c): export of <value> records is disproportionate — requires data minimisation review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "transfer_personal_data",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "uk-gdpr.special-category-health-data",
            "escalate",
            "UK GDPR Art. 9: health data is special category — requires Art. 9(2) condition and Schedule 1 DPA basis",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|nhs\\s+number|genetic\\s+(data|test)|mental\\s+health|disability|prescription)",
                ),
            ),
        ),
        R(
            "uk-gdpr.other-special-category-data",
            "escalate",
            "UK GDPR Art. 9: special category personal data detected — explicit consent or Schedule 1 DPA condition required",
            (
                (
                    "text",
                    "(?i)(ethnic\\s+origin|race|religion|political\\s+opinion|sexual\\s+orientation|trade\\s+union|criminal\\s+conviction|biometric\\s+(template|data))",
                ),
            ),
        ),
        R(
            "uk-gdpr.purpose-limitation-language-output",
            "escalate",
            "UK GDPR Art. 5(1)(b): personal data must not be further processed incompatibly — verify compatible purpose or DUAA recognised legitimate interests before repurposing",
            (
                (
                    "text",
                    "(?i)(reuse|repurpose|secondary\\s+use|use\\s+for\\s+another\\s+purpose).{0,40}(personal\\s+data|pii)",
                ),
            ),
        ),
        R(
            "uk-gdpr.escalate-transfer-action-when-destination-not",
            "escalate",
            "UK GDPR Art. 44–46: cross-border transfer action — confirm adequacy coverage or binding safeguards plus documented data protection test before export",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "transfer_personal_data",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "uk-gdpr.cross-border-language-without-structured-params",
            "escalate",
            "UK GDPR Art. 44: restricted transfer language detected — verify adequacy, safeguards, and data protection test",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+(the\\s+)?uk|cross.?border|international\\s+transfer|third\\s+country|offshore)",
                ),
            ),
        ),
        R(
            "uk-gdpr.bulk-export-actions",
            "escalate",
            "UK GDPR Art. 5(1)(c): bulk personal data export requires documented necessity and DPO review",
            (
                (
                    "action_in",
                    (
                        "batch_download_pii",
                        "bulk_export",
                        "download_all_records",
                        "dump_database",
                        "export_all",
                        "full_table_export",
                    ),
                ),
            ),
        ),
        R(
            "uk-gdpr.personal-data-access-audit",
            "audit",
            "UK GDPR Art. 5(2) / Art. 30: personal data access logged for accountability and records of processing",
            (
                (
                    "action_in",
                    (
                        "access_pii",
                        "fetch_profile",
                        "get_customer",
                        "lookup_account",
                        "query_personal",
                        "read_user",
                        "subject_access_request",
                    ),
                ),
            ),
        ),
        R(
            "uk-gdpr.personal-data-modification-audit",
            "audit",
            "UK GDPR Art. 5(2) / Art. 30: personal data modification logged for accountability and records of processing",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "edit_customer",
                        "erase_personal_data",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
}

RULES: tuple[TableRule, ...] = tuple(rule for table in TABLES.values() for rule in table)


@check("pack.regional.uk", surfaces=["input", "output", "tool_args"])
def rules_regional_uk(ctx: CheckContext) -> dict[str, Any]:
    """Raises a risk for every translated regional/uk rule this call matches."""
    return run(RULES, ctx)
