# Rules translated from examples/policies/india-regulatory/rego/ in https://github.com/microsoft/agent-governance-toolkit
# (commit c767f83). Copyright (c) Microsoft Corporation. Licensed under the MIT License;
# full text in THIRD_PARTY_NOTICES.md. Translated into an AgentFox rule table; see this
# pack's README for what was translated, how, and what was left out.

"""The rule table behind the regional/india policies: one risk code per translated rule.

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
    "india-aadhaar": (
        R(
            "india-aadhaar.unmasked-12-digit-aadhaar-output",
            "deny",
            "Aadhaar Regulations 2021: mask the first 8 of 12 Aadhaar digits (only last 4 may be shown); full Aadhaar must not be output, logged, or stored unmasked",
            (("text", "(?i)(aadhaa?r|आधार)\\D{0,15}\\d{12}\\b"),),
        ),
        R(
            "india-aadhaar.unmasked-12-digit-run-near-uid",
            "deny",
            "Aadhaar Regulations 2021: unmasked 12-digit Aadhaar number detected near UID context - must be masked (last 4 only)",
            (("text", "(?i)(uid|uidai|unique\\s+id).{0,15}\\d{12}\\b"),),
        ),
        R(
            "india-aadhaar.1234-5678-9012-or-1234-5678",
            "deny",
            "Aadhaar Regulations 2021: a grouped 12-digit sequence (4-4-4) resembling an Aadhaar number must be masked; only the last 4 digits may be shown",
            (("text", "\\b\\d{4}[ -]\\d{4}[ -]\\d{4}\\b"),),
        ),
        R(
            "india-aadhaar.core-biometric-information-never-shared-displayed",
            "deny",
            "Aadhaar Act s.29(1): core biometric information must never be shared, displayed, or stored by unauthorised entities",
            (("text", "(?i)aadhaar.{0,20}(biometric|fingerprint|iris|face)"),),
        ),
        R(
            "india-aadhaar.no-public-display-posting-aadhaar-number",
            "deny",
            "Aadhaar Act s.29(4): no Aadhaar number shall be published, displayed, or posted publicly (2019 amendment); s.29(3) bars use or disclosure beyond the specified purpose",
            (
                (
                    "action_in",
                    (
                        "display_full_aadhaar",
                        "expose_uid",
                        "publish_aadhaar",
                    ),
                ),
                ("not_param", "aadhaar_masked", "==", True),
            ),
        ),
    ),
    "india-cert-in": (
        R(
            "india-cert-in.6-hour-reporting-cannot-suppress-delay",
            "deny",
            "CERT-In 2022 Directions (ii): cyber incidents must be reported to CERT-In within 6 hours; suppressing/delaying is prohibited",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify)|skip\\s+(the\\s+)?(cert.?in\\s+)?report|suppress\\s+(the\\s+)?(incident|breach)|delay\\s+(the\\s+)?(incident|breach)\\s+report)",
                ),
            ),
        ),
        R(
            "india-cert-in.180-day-india-log-retention",
            "deny",
            "CERT-In 2022 Directions (iv): ICT logs must be retained for 180 days, configured: <value>",
            (("param", "log_retention_days", "<", 180),),
        ),
    ),
    "india-dpdp": (
        R(
            "india-dpdp.consent-required-before-processing-personal-data",
            "deny",
            "DPDP s.6: processing personal data requires a logged, purpose-specific consent record",
            (
                (
                    "action_in",
                    (
                        "process_personal_data",
                        "profile_user",
                        "share_pii",
                        "store_pii",
                    ),
                ),
                ("not_param", "consent_logged", "==", True),
            ),
        ),
        R(
            "india-dpdp.security-safeguards-block-unencrypted-personal-data",
            "deny",
            "DPDP s.8(5): personal data must be processed with reasonable security safeguards (encryption, access control)",
            (
                (
                    "action_in",
                    (
                        "process_personal_data",
                        "profile_user",
                        "share_pii",
                        "store_pii",
                    ),
                ),
                ("not_param", "encrypted", "==", True),
            ),
        ),
        R(
            "india-dpdp.cannot-suppress-delay-breach-notification",
            "deny",
            "DPDP s.8(6) and Rule 7: agent cannot suppress or delay breach notification to the Data Protection Board and affected Data Principals (72h detailed report)",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(the\\s+)?(breach|notification)|delay\\s+breach\\s+(report|notification))",
                ),
            ),
        ),
        R(
            "india-dpdp.cross-border-transfer-escalate-adequacy-localization",
            "escalate",
            "DPDP s.16: cross-border personal-data transfer requires review (Central-Govt restriction list plus stricter sectoral localization under RBI/SEBI)",
            (
                (
                    "action_in",
                    (
                        "export_pii",
                        "send_to_external",
                        "transfer_personal_data",
                    ),
                ),
            ),
        ),
        R(
            "india-dpdp.sdf-algorithmic-due-diligence-audit-automated",
            "audit",
            "DPDP Rule 13 (Significant Data Fiduciary): verify algorithms/AI do not endanger Data Principal rights; DPIA plus annual independent audit",
            (
                (
                    "action_in",
                    (
                        "deploy_model",
                        "profile_personal_data",
                        "run_automated_decision",
                    ),
                ),
            ),
        ),
    ),
    "india-rbi": (
        R(
            "india-rbi.payment-system-data-stored-only-india",
            "deny",
            "RBI 2018 (Storage of Payment System Data): payment data must be stored only in India, configured region: <value>",
            (
                (
                    "param",
                    "data_class",
                    "in",
                    (
                        "card_data",
                        "payment_data",
                        "transaction_data",
                    ),
                ),
                ("not_param", "storage_region", "==", "IN"),
            ),
        ),
        R(
            "india-rbi.foreign-processed-payment-data-purged-returned",
            "deny",
            "RBI 2018: payment data processed abroad must be purged and returned to India within 24h, configured: <value>h",
            (
                ("param", "data_class", "==", "payment_data"),
                ("param", "processed_abroad", "==", True),
                ("param", "purge_within_hours", ">", 24),
            ),
        ),
        R(
            "india-rbi.kyc-mandatory-before-onboarding",
            "deny",
            "RBI Master Direction KYC 2016: customer due diligence (KYC) is mandatory before onboarding",
            (
                (
                    "action_in",
                    (
                        "activate_customer",
                        "onboard_customer",
                        "open_account",
                    ),
                ),
                ("not_param", "kyc_completed", "==", True),
            ),
        ),
        R(
            "india-rbi.third-party-cloud-ai-data-flows",
            "escalate",
            "RBI Master Directions Outsourcing of IT Services / IT Governance 2023: due diligence, audit rights, and data locality required for third-party/cloud/AI handling customer or payment data",
            (
                (
                    "action_in",
                    (
                        "invoke_external_ai",
                        "route_to_third_party",
                        "use_cloud_service",
                    ),
                ),
            ),
        ),
        R(
            "india-rbi.advisory-only-audit-never-deny",
            "audit",
            "ADVISORY (non-binding, RBI FREE-AI 2025): board-approved AI policy, AI incident reporting, and human oversight recommended for AI in financial services",
            (("text", "(?i)(ai|ml)\\s+model.{0,30}(credit|loan|fraud|financial)\\s+decision"),),
        ),
    ),
    "india-sebi": (
        R(
            "india-sebi.re-solely-responsible-ai-ml-output",
            "deny",
            "SEBI Amendment 10 Feb 2025: regulated entity is solely responsible for AI/ML output; liability cannot be disclaimed and human accountability is required",
            (
                (
                    "action_in",
                    (
                        "advise_investor",
                        "execute_trade",
                        "manage_portfolio",
                        "place_order",
                    ),
                ),
                ("not_param", "human_accountable", "==", True),
            ),
        ),
        R(
            "india-sebi.ai-ml-output-liability-cannot-disclaimed",
            "deny",
            "SEBI Amendment 10 Feb 2025: AI/ML output liability cannot be disclaimed by the regulated entity",
            (
                (
                    "text",
                    "(?i)(not\\s+responsible|disclaim\\s+liability|no\\s+human\\s+accountab).{0,40}(ai|ml|model)\\s+(output|decision)",
                ),
            ),
        ),
        R(
            "india-sebi.immutable-india-retained-audit-logging",
            "deny",
            "SEBI CSCRF 2024: maintain immutable, India-retained audit logging with continuous SOC monitoring",
            (
                (
                    "action_in",
                    (
                        "delete_audit_log",
                        "disable_audit_log",
                        "make_log_mutable",
                        "store_audit_log_offshore",
                    ),
                ),
            ),
        ),
        R(
            "india-sebi.incident-reporting-cannot-suppress",
            "deny",
            "SEBI CSCRF 2024: cyber incidents must be reported to SEBI and the relevant CERT within mandated timelines",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify)|suppress|delay).{0,30}(cyber\\s+)?(incident|breach)",
                ),
            ),
        ),
        R(
            "india-sebi.vapt-audit-before-production-escalate",
            "escalate",
            "SEBI CSCRF 2024: periodic VAPT and cyber audit, data classification, and access control are required before production",
            (
                ("action_in", ("deploy_to_production",)),
                ("not_param", "vapt_completed", "==", True),
            ),
        ),
        R(
            "india-sebi.draft-advisory-audit-only",
            "audit",
            "ADVISORY (draft, SEBI Consultation Paper 20 Jun 2025): board-approved AI governance, explainability, human-in-the-loop, and fallback plans proposed; not yet binding",
            (("text", "(?i)deploy.{0,20}(ai|ml)\\s+model.{0,20}(securities|trading|investor)"),),
        ),
    ),
}

RULES: tuple[TableRule, ...] = tuple(rule for table in TABLES.values() for rule in table)


@check("pack.regional.india", surfaces=["input", "output", "tool_args"])
def rules_regional_india(ctx: CheckContext) -> dict[str, Any]:
    """Raises a risk for every translated regional/india rule this call matches."""
    return run(RULES, ctx)
