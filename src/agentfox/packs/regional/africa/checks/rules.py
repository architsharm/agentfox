# Rules translated from examples/policies/african-regulatory/rego/ in https://github.com/microsoft/agent-governance-toolkit
# (commit c767f83). Copyright (c) Microsoft Corporation. Licensed under the MIT License;
# full text in THIRD_PARTY_NOTICES.md. Translated into an AgentFox rule table; see this
# pack's README for what was translated, how, and what was left out.

"""The rule table behind the regional/africa policies: one risk code per translated rule.

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
    "africa-human-approval": (
        R(
            "africa-human-approval.v-designated-as-human-approval-action",
            "escalate",
            "Human approval required: <value> is designated as a human-approval action.",
            (
                (
                    "action_in",
                    (
                        "approve_transfer",
                        "bulk_delete",
                        "close_account",
                        "delete_account",
                        "deploy_code",
                        "grant_admin",
                        "initiate_bulk_refund",
                        "mass_update",
                        "modify_permissions",
                        "revoke_access",
                        "self_approve",
                        "send_bulk_email",
                        "send_bulk_sms",
                    ),
                ),
            ),
        ),
        R(
            "africa-human-approval.action-risk-level-v-requires-human",
            "escalate",
            "Human approval required: action risk level <value> requires human authorisation.",
            (
                (
                    "ctx",
                    "risk_level",
                    "in",
                    (
                        "critical",
                        "high",
                    ),
                ),
                (
                    "not_action_in",
                    (
                        "approve_transfer",
                        "bulk_delete",
                        "close_account",
                        "delete_account",
                        "deploy_code",
                        "grant_admin",
                        "initiate_bulk_refund",
                        "mass_update",
                        "modify_permissions",
                        "revoke_access",
                        "self_approve",
                        "send_bulk_email",
                        "send_bulk_sms",
                    ),
                ),
            ),
        ),
        R(
            "africa-human-approval.transaction-amount-v-exceeds-configured-threshold",
            "escalate",
            "Human approval required: transaction amount <value> exceeds configured threshold <value>.",
            (
                ("param_num", "amount", ">", 1000000, 0),
                (
                    "not_action_in",
                    (
                        "approve_transfer",
                        "bulk_delete",
                        "close_account",
                        "delete_account",
                        "deploy_code",
                        "grant_admin",
                        "initiate_bulk_refund",
                        "mass_update",
                        "modify_permissions",
                        "revoke_access",
                        "self_approve",
                        "send_bulk_email",
                        "send_bulk_sms",
                    ),
                ),
            ),
        ),
        R(
            "africa-human-approval.bulk-operation-v-records-exceeds-threshold",
            "escalate",
            "Human approval required: bulk operation on <value> records exceeds threshold <value>.",
            (
                ("param_num", "record_count", ">", 500, 0),
                (
                    "not_action_in",
                    (
                        "approve_transfer",
                        "bulk_delete",
                        "close_account",
                        "delete_account",
                        "deploy_code",
                        "grant_admin",
                        "initiate_bulk_refund",
                        "mass_update",
                        "modify_permissions",
                        "revoke_access",
                        "self_approve",
                        "send_bulk_email",
                        "send_bulk_sms",
                    ),
                ),
            ),
        ),
    ),
    "africa-model-routing": (
        R(
            "africa-model-routing.model-v-not-approved-sensitive-task",
            "deny",
            "Model routing denied: model <value> is not approved for sensitive task type <value>.",
            (
                (
                    "ctx",
                    "task_type",
                    "in",
                    (
                        "aml_screening",
                        "authentication",
                        "credit_scoring",
                        "financial_decision",
                        "fraud_detection",
                        "kyc_review",
                        "legal_advice",
                        "medical_advice",
                        "pii_processing",
                    ),
                ),
                ("ctx_nonempty_str", "model"),
                (
                    "not_ctx",
                    "model",
                    "in",
                    (
                        "claude-opus-4",
                        "claude-opus-4-8",
                        "claude-sonnet-4",
                        "claude-sonnet-4-6",
                        "gemini-1.5-pro",
                        "gemini-ultra",
                        "gpt-4-turbo",
                        "gpt-4o",
                    ),
                ),
            ),
        ),
        R(
            "africa-model-routing.sensitive-task-type-v-requires-explicitly",
            "escalate",
            "Model routing: sensitive task type <value> requires an explicitly approved model — none specified.",
            (
                (
                    "ctx",
                    "task_type",
                    "in",
                    (
                        "aml_screening",
                        "authentication",
                        "credit_scoring",
                        "financial_decision",
                        "fraud_detection",
                        "kyc_review",
                        "legal_advice",
                        "medical_advice",
                        "pii_processing",
                    ),
                ),
                ("not_ctx_nonempty_str", "model"),
            ),
        ),
        R(
            "africa-model-routing.sensitive-task-v-processed-by-approved",
            "audit",
            "Model routing audit: sensitive task <value> processed by approved model <value>.",
            (
                (
                    "ctx",
                    "task_type",
                    "in",
                    (
                        "aml_screening",
                        "authentication",
                        "credit_scoring",
                        "financial_decision",
                        "fraud_detection",
                        "kyc_review",
                        "legal_advice",
                        "medical_advice",
                        "pii_processing",
                    ),
                ),
                ("ctx_nonempty_str", "model"),
                (
                    "ctx",
                    "model",
                    "in",
                    (
                        "claude-opus-4",
                        "claude-opus-4-8",
                        "claude-sonnet-4",
                        "claude-sonnet-4-6",
                        "gemini-1.5-pro",
                        "gemini-ultra",
                        "gpt-4-turbo",
                        "gpt-4o",
                    ),
                ),
            ),
        ),
    ),
    "africa-pii-leakage": (
        R(
            "africa-pii-leakage.credit-debit-card-number-detected-agent",
            "deny",
            "PII leakage: credit/debit card number detected in agent output — blocked.",
            (
                (
                    "text",
                    "\\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\\b",
                ),
            ),
        ),
        R(
            "africa-pii-leakage.bvn-nin-format-identifier-detected-agent",
            "deny",
            "PII leakage: BVN/NIN-format identifier (11-digit) detected in agent output — blocked.",
            (("text", "\\b[0-9]{11}\\b"),),
        ),
        R(
            "africa-pii-leakage.south-african-id-number-detected-agent",
            "deny",
            "PII leakage: South African ID number detected in agent output — blocked.",
            (("text", "\\b[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[0-9]{7}\\b"),),
        ),
        R(
            "africa-pii-leakage.email-address-detected-agent-output-route",
            "escalate",
            "PII leakage: email address detected in agent output — route to review.",
            (
                ("text", "[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}"),
                (
                    "not_text",
                    "\\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\\b",
                ),
                ("not_text", "\\b[0-9]{11}\\b"),
                ("not_text", "\\b[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[0-9]{7}\\b"),
            ),
        ),
        R(
            "africa-pii-leakage.phone-number-detected-agent-output-route",
            "escalate",
            "PII leakage: phone number detected in agent output — route to review.",
            (
                ("text", "(\\+[0-9]{1,3}[\\s\\-]?)?(\\([0-9]{1,4}\\)[\\s\\-]?)?[0-9]{6,14}\\b"),
                (
                    "not_text",
                    "\\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\\b",
                ),
                ("not_text", "\\b[0-9]{11}\\b"),
                ("not_text", "\\b[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[0-9]{7}\\b"),
            ),
        ),
        R(
            "africa-pii-leakage.action-may-produce-personal-data-output",
            "audit",
            "PII audit: action may produce personal data — output logged for compliance review.",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "generate_report",
                        "read_customer",
                        "respond_to_customer",
                        "send_email",
                        "send_sms",
                    ),
                ),
                (
                    "not_text",
                    "\\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\\b",
                ),
                ("not_text", "\\b[0-9]{11}\\b"),
                ("not_text", "\\b[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[0-9]{7}\\b"),
                ("not_text", "[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}"),
                ("not_text", "(\\+[0-9]{1,3}[\\s\\-]?)?(\\([0-9]{1,4}\\)[\\s\\-]?)?[0-9]{6,14}\\b"),
            ),
        ),
    ),
    "africa-prompt-injection": (
        R(
            "africa-prompt-injection.input-contains-known-injection-pattern-action",
            "deny",
            "Prompt injection detected: input contains known injection pattern — action blocked.",
            (
                (
                    "params_text_contains",
                    (
                        "content",
                        "input",
                        "instruction",
                        "message",
                        "prompt",
                        "query",
                        "text",
                        "user_input",
                    ),
                    (
                        "act as if you are",
                        "act as though you",
                        "bypass your",
                        "disregard all previous",
                        "disregard your instructions",
                        "forget previous instructions",
                        "forget your instructions",
                        "ignore all previous",
                        "ignore previous instructions",
                        "ignore your guidelines",
                        "ignore your rules",
                        "jailbreak",
                        "new instructions:",
                        "override your",
                        "pretend to be",
                        "pretend you are",
                        "you are now",
                        "your new purpose",
                        "your real instructions",
                    ),
                ),
            ),
        ),
        R(
            "africa-prompt-injection.structural-injection-marker-detected-route-review",
            "escalate",
            "Potential prompt injection: structural injection marker detected — route to review.",
            (
                (
                    "params_text_contains",
                    (
                        "content",
                        "input",
                        "instruction",
                        "message",
                        "prompt",
                        "query",
                        "text",
                        "user_input",
                    ),
                    (
                        "###system",
                        "---system---",
                        "</system>",
                        "<system>",
                        "<|system|>",
                        "[inst]",
                        "[system prompt]",
                    ),
                ),
                (
                    "not_params_text_contains",
                    (
                        "content",
                        "input",
                        "instruction",
                        "message",
                        "prompt",
                        "query",
                        "text",
                        "user_input",
                    ),
                    (
                        "act as if you are",
                        "act as though you",
                        "bypass your",
                        "disregard all previous",
                        "disregard your instructions",
                        "forget previous instructions",
                        "forget your instructions",
                        "ignore all previous",
                        "ignore previous instructions",
                        "ignore your guidelines",
                        "ignore your rules",
                        "jailbreak",
                        "new instructions:",
                        "override your",
                        "pretend to be",
                        "pretend you are",
                        "you are now",
                        "your new purpose",
                        "your real instructions",
                    ),
                ),
            ),
        ),
    ),
    "africa-tool-permissions": (
        R(
            "africa-tool-permissions.v-restricted-tool-route-authorization-queue",
            "escalate",
            "Tool requires human approval: <value> is a restricted tool — route to authorization queue.",
            (
                (
                    "action_in",
                    (
                        "bulk_delete",
                        "delete_record",
                        "deploy",
                        "drop_table",
                        "execute_code",
                        "file_delete",
                        "file_write",
                        "grant_admin",
                        "modify_permissions",
                        "revoke_access",
                        "send_bulk_email",
                        "send_email",
                        "send_sms",
                        "shell_exec",
                        "truncate_table",
                    ),
                ),
            ),
        ),
    ),
    "nigeria-bvn-nin": (
        R(
            "nigeria-bvn-nin.block-bvn-value-agent-output",
            "deny",
            "BVN Protection: BVN value detected in agent output — blocked (NDPA Schedule 1 biometric data)",
            (
                (
                    "text",
                    "(?i)(bvn\\s+is|bvn:\\s*|bvn\\s*=|your\\s+bvn|the\\s+bvn)[\\s:]*[0-9]{10,11}",
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.block-contextual-bvn-pattern-output",
            "deny",
            "BVN Protection: BVN pattern detected in agent output — blocked to prevent credential exposure",
            (("text", "(?i)(bvn|bank\\s+verification).{0,20}\\b[0-9]{11}\\b"),),
        ),
        R(
            "nigeria-bvn-nin.block-nin-value-agent-output",
            "deny",
            "NIN Protection: NIN value detected in agent output — blocked (NDPA Schedule 1 biometric data)",
            (
                (
                    "text",
                    "(?i)(nin\\s+is|nin:\\s*|nin\\s*=|your\\s+nin|the\\s+nin)[\\s:]*[0-9]{10,11}",
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.block-virtual-nin-output",
            "deny",
            "NIN Protection: Virtual NIN (vNIN) detected in agent output — blocked",
            (("text", "(?i)(vnin|virtual\\s+nin)[\\s:=]+[A-Z0-9]{16}"),),
        ),
        R(
            "nigeria-bvn-nin.block-direct-bvn-nin-transmission-external",
            "deny",
            "BVN/NIN Transmission: Direct BVN/NIN transmission blocked — use NIBSS tokenised verification flow",
            (
                (
                    "action_in",
                    (
                        "post_identity",
                        "relay_kyc",
                        "send_bvn",
                        "send_nin",
                        "share_bvn",
                        "share_nin",
                        "transmit_bvn",
                        "transmit_nin",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.block-bvn-present-params-from-being",
            "deny",
            "BVN/NIN Transmission: BVN detected in params with external transmission action — blocked",
            (
                ("param", "bvn_present", "==", True),
                (
                    "action_in",
                    (
                        "post_identity",
                        "relay_kyc",
                        "send_bvn",
                        "send_nin",
                        "share_bvn",
                        "share_nin",
                        "transmit_bvn",
                        "transmit_nin",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.block-bvn-disclosure-over-conversational-channels",
            "deny",
            "BVN/NIN Social Engineering: Attempt to disclose BVN/NIN through conversational channel — blocked",
            (
                (
                    "text",
                    "(?i)(customer\\s+(wants|needs|asked|requested).{0,30}(bvn|nin)|confirm.{0,20}(bvn|nin).{0,20}(over|via|through)\\s+(chat|call|whatsapp|email|sms))",
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.block-illegal-data-persistence",
            "deny",
            "NIMC Act 2026: Storing NIN/BVN data after verification is prohibited — illegal data persistence (₦20M corporate / 5yr individual penalty)",
            (
                (
                    "action_in",
                    (
                        "cache_bvn",
                        "cache_nin",
                        "log_nin",
                        "persist_identity",
                        "record_nin",
                        "save_bvn_data",
                        "save_nin_data",
                        "store_bvn",
                        "store_nin",
                        "write_nin_record",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.block-persist-nin-true-flag-params",
            "deny",
            "NIMC Act 2026: persist_nin=true detected — NIN data may not be stored after verification completes",
            (("param", "persist_nin", "==", True),),
        ),
        R(
            "nigeria-bvn-nin.block-bulk-nin-identity-data-export",
            "deny",
            "NIMC Act 2026: Bulk NIN/identity data export is prohibited — only individual authorised verifications are permitted",
            (
                (
                    "action_in",
                    (
                        "bulk_identity_export",
                        "bulk_nin_export",
                        "download_nin_records",
                        "export_nin_data",
                        "extract_identity_records",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.block-bulk-identity-export-true-flag",
            "deny",
            "NIMC Act 2026: bulk_identity_export=true detected — bulk identity extraction is prohibited",
            (("param", "bulk_identity_export", "==", True),),
        ),
        R(
            "nigeria-bvn-nin.bvn-verification-always-requires-human-approval",
            "escalate",
            "BVN Verification: BVN lookup requires human approval — CBN BVN Framework mandates audit trail for all lookups",
            (
                (
                    "action_in",
                    (
                        "bvn_lookup",
                        "check_bvn",
                        "nibss_bvn_verify",
                        "validate_bvn",
                        "verify_bvn",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.nin-verification-always-requires-human-approval",
            "escalate",
            "NIN Verification: NIN lookup requires human approval — NIMC Act requires documented purpose for each lookup",
            (
                (
                    "action_in",
                    (
                        "check_nin",
                        "nimc_nin_verify",
                        "nin_lookup",
                        "validate_nin",
                        "verify_nin",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.nin-bvn-lookup-without-declared-purpose",
            "escalate",
            "NIMC Act 2026: NIN lookup attempted without a declared purpose — purpose limitation requires stating the reason before each verification",
            (
                (
                    "action_in",
                    (
                        "check_nin",
                        "nimc_nin_verify",
                        "nin_lookup",
                        "validate_nin",
                        "verify_nin",
                    ),
                ),
                (
                    "ctx_get",
                    "nin_purpose",
                    "",
                    "in",
                    (
                        "",
                        None,
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.bvn-lookup-attempted-without-declared-purpose",
            "escalate",
            "NIMC Act 2026: BVN lookup attempted without a declared purpose — purpose limitation requires stating the reason before each verification",
            (
                (
                    "action_in",
                    (
                        "bvn_lookup",
                        "check_bvn",
                        "nibss_bvn_verify",
                        "validate_bvn",
                        "verify_bvn",
                    ),
                ),
                (
                    "ctx_get",
                    "nin_purpose",
                    "",
                    "in",
                    (
                        "",
                        None,
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.consented-purpose-differs-from-current-purpose",
            "escalate",
            "NIMC Act 2026: Purpose mismatch — NIN was consented for <value> but current purpose is <value>",
            (
                ("ctx", "nin_consented_purpose", "!=", ""),
                ("ctx", "purpose", "!=", ""),
                ("ctx_ne_ctx", "nin_consented_purpose", "purpose"),
            ),
        ),
        R(
            "nigeria-bvn-nin.escalate-if-identifier-type-bvn-nin",
            "escalate",
            "BVN/NIN Gate: Action <value> involves <value> identifier — requires human approval before proceeding",
            (
                (
                    "param",
                    "identifier_type",
                    "in",
                    (
                        "BVN",
                        "NIN",
                        "bvn",
                        "nin",
                    ),
                ),
                (
                    "not_action_in",
                    (
                        "post_identity",
                        "relay_kyc",
                        "send_bvn",
                        "send_nin",
                        "share_bvn",
                        "share_nin",
                        "transmit_bvn",
                        "transmit_nin",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.identity-related-action-logged-ndpa-s",
            "audit",
            "BVN/NIN Audit: Identity-related action logged — NDPA s.30 and CBN BVN audit trail requirement",
            (
                (
                    "action_has",
                    (
                        "bvn",
                        "nin",
                        "kyc",
                        "identity_verify",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-bvn-nin.regulated-services-require-verified-nin-defaulting",
            "audit",
            "NIMC Act 2026: Action <value> is a mandatory-NIN service — bank accounts, SIM, passports, land transactions, pension, insurance, and consumer credit require context.nin_verified = true",
            (
                (
                    "action_in",
                    (
                        "apply_credit",
                        "apply_government_service",
                        "apply_passport",
                        "create_account",
                        "insurance_enrollment",
                        "land_registration",
                        "open_account",
                        "pension_enrollment",
                        "register_voter",
                        "sim_registration",
                        "tax_registration",
                    ),
                ),
                ("ctx_get", "nin_verified", False, "!=", True),
            ),
        ),
    ),
    "nigeria-cbn-limits": (
        R(
            "nigeria-cbn-limits.agent-cannot-self-approve-transactions",
            "deny",
            "CBN Maker-Checker: AI agent cannot self-approve financial transactions — segregation of duties violated",
            (
                (
                    "action_in",
                    (
                        "approve_transfer",
                        "authorise_transaction",
                        "auto_approve",
                        "confirm_payment",
                        "self_approve",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-cbn-limits.single-transaction-cannot-exceed-10-000",
            "deny",
            "CBN NIP Framework: Transaction of ₦<value> exceeds ₦10,000,000 single-transaction cap — blocked",
            (
                (
                    "action_in",
                    (
                        "initiate_payment",
                        "instant_transfer",
                        "nip_transfer",
                        "send_money",
                        "transfer_funds",
                        "wire_transfer",
                    ),
                ),
                ("param", "amount", ">", 10000000),
            ),
        ),
        R(
            "nigeria-cbn-limits.detect-10m-text-output",
            "deny",
            "CBN NIP Framework: Transaction amount exceeding ₦10,000,000 detected in output — blocked",
            (("text", "(?i)(₦|NGN|naira)\\s*1[0-9],?[0-9]{3},?[0-9]{3}"),),
        ),
        R(
            "nigeria-cbn-limits.transfers-between-5m-10m-require-human",
            "escalate",
            "CBN Tier 3: Transfer of ₦<value> is at or above ₦5,000,000 daily ceiling — routed to human approval queue",
            (
                (
                    "action_in",
                    (
                        "initiate_payment",
                        "instant_transfer",
                        "nip_transfer",
                        "send_money",
                        "transfer_funds",
                        "wire_transfer",
                    ),
                ),
                ("param", "amount", ">=", 5000000),
                ("param", "amount", "<=", 10000000),
            ),
        ),
        R(
            "nigeria-cbn-limits.transfers-above-tier-2-ceiling-unverified",
            "escalate",
            "CBN Tier 2: Transfer of ₦<value> exceeds ₦200,000 Tier 2 daily limit — requires verification upgrade or approval",
            (
                (
                    "action_in",
                    (
                        "initiate_payment",
                        "instant_transfer",
                        "nip_transfer",
                        "send_money",
                        "transfer_funds",
                        "wire_transfer",
                    ),
                ),
                ("param", "amount", ">", 200000),
                ("ctx", "kyc_tier", "==", 2),
            ),
        ),
        R(
            "nigeria-cbn-limits.any-transfer-above-50-000-unverified",
            "escalate",
            "CBN Tier 1: Transfer of ₦<value> exceeds ₦50,000 Tier 1 limit — KYC upgrade required",
            (
                (
                    "action_in",
                    (
                        "initiate_payment",
                        "instant_transfer",
                        "nip_transfer",
                        "send_money",
                        "transfer_funds",
                        "wire_transfer",
                    ),
                ),
                ("param", "amount", ">", 50000),
                ("ctx", "kyc_tier", "==", 1),
            ),
        ),
        R(
            "nigeria-cbn-limits.all-refunds-require-human-approval-never",
            "escalate",
            "CBN / Fraud Controls: Refund action requires human approval — agent cannot autonomously issue refunds",
            (
                (
                    "action_in",
                    (
                        "credit_account",
                        "issue_refund",
                        "manual_refund",
                        "process_refund",
                        "reverse_charge",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-cbn-limits.bulk-payments-always-require-human-approval",
            "escalate",
            "CBN: Bulk/batch payment requires human approval — aggregate amount must be verified",
            (
                (
                    "action_in",
                    (
                        "batch_payment",
                        "bulk_disbursement",
                        "bulk_transfer",
                        "mass_payment",
                        "payroll_run",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-cbn-limits.ussd-transactions-require-approval",
            "escalate",
            "CBN USSD Guidelines: USSD transaction requires human review — verify ₦20,000 per-transaction / ₦100,000 daily limits",
            (("action_re", "^ussd_"),),
        ),
        R(
            "nigeria-cbn-limits.financial-transaction-action-logged-required-cbn",
            "audit",
            "CBN Record-Keeping: Financial transaction action logged — required for CBN examination and NFIU reporting",
            (
                (
                    "action_re",
                    "^(?:transfer_|payment_|refund_|reversal_|settlement_|credit_|debit_)",
                ),
            ),
        ),
    ),
    "egypt-pdpl": (
        R(
            "egypt-pdpl.block-breach-suppression-72h-pdpc-3",
            "deny",
            "Egypt PDPL No. 151/2020 Art. 7: Agent cannot suppress breach notifications — PDPC must be notified within 72 hours and data subjects within 3 working days",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+(report|notification))",
                ),
            ),
        ),
        R(
            "egypt-pdpl.block-biometric-data-triggers-art-7",
            "deny",
            "Egypt PDPL No. 151/2020 Art. 1/4: Biometric sensitive data detected — must not be transmitted; breach triggers 72h PDPC notification (Art. 7)",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "egypt-pdpl.block-egypt-national-id-output-format",
            "deny",
            "Egypt PDPL No. 151/2020 Art. 1/7: Egyptian National ID (14-digit) detected in agent output — blocked; triggers 72h PDPC breach notification",
            (
                (
                    "text",
                    "(?i)(egypt(ian)?\\s+(national\\s+)?(id|identity|card)|national\\s+id\\s+(no|number|#)|رقم\\s+قومي)[\\s:=]{0,5}[23][0-9]{13}",
                ),
            ),
        ),
        R(
            "egypt-pdpl.block-cross-border-transfer-non-permitted",
            "deny",
            "Egypt PDPL No. 151/2020 Art. 14: Cross-border transfer to region <value> blocked — PDPC approval or equivalent protection documentation required",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "EG",
                        "af-south-1",
                        "eg",
                        "egypt",
                        "me-central-1",
                        "me-south-1",
                    ),
                ),
            ),
        ),
        R(
            "egypt-pdpl.block-transfer-non-eg-country-without",
            "deny",
            "Egypt PDPL No. 151/2020 Arts. 14-15: Transfer to <value> blocked — no documented consent or Art. 15 derogation (vital interest, legal necessity, contract) on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "EG"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "egypt-pdpl.block-agents-advising-unlicensed-data-processing",
            "deny",
            "Egypt PDPL No. 151/2020 Art. 26: Agent cannot advise bypassing PDPC licensing — processing without registration is a criminal offence (up to EGP 2,000,000 + imprisonment)",
            (
                (
                    "text",
                    "(?i)(process(ing)?\\s+(without|skip|bypass|ignore).{0,30}(licen(s|c)e|PDPC|permit|registr)|no\\s+need\\s+(to\\s+)?(register|licen(s|c)e|notify\\s+PDPC))",
                ),
            ),
        ),
        R(
            "egypt-pdpl.block-disproportionate-bulk-record-exports",
            "deny",
            "Egypt PDPL No. 151/2020 Art. 6/14: Export of <value> records exceeds threshold — requires documented lawful basis and PDPC approval",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "egypt-pdpl.health-medical-sensitive-data",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 1/4: Health/medical/genetic sensitive data detected — requires explicit consent or Art. 5 exception (PDPC)",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|\\bHIV\\b|genetic\\s+(data|test)|mental\\s+health|disability|prescription|clinical\\s+data|psychological\\s+(assessment|report|status))",
                ),
            ),
        ),
        R(
            "egypt-pdpl.financial-data-unique-sensitive-category-egypt",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 1/4: Financial data is a sensitive category under Egyptian law — requires explicit consent (unique provision: financial data = sensitive in Egypt)",
            (
                (
                    "text",
                    "(?i)(account\\s+(balance|statement|number)|credit\\s+(score|report|history)|loan\\s+(default|history|status)|salary\\s+(slip|detail)|tax\\s+(return|record)|financial\\s+(statement|profile|data))",
                ),
            ),
        ),
        R(
            "egypt-pdpl.special-category-data",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 1/4: Special category personal data detected — requires explicit consent or Art. 5 exception (PDPC)",
            (
                (
                    "text",
                    "(?i)(religious\\s+belief|political\\s+(view|opinion)|criminal\\s+(record|conviction|offence)|ethnic\\s+origin|racial\\s+origin|sexual\\s+(orientation|life))",
                ),
            ),
        ),
        R(
            "egypt-pdpl.children-s-data-classified-as-sensitive",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 1/3: Children's data is a sensitive category — requires parental/guardian consent (unique classification in African data protection law)",
            (
                (
                    "text",
                    "(?i)(child(ren)?'?s?\\s+(data|record|profile|information)|minor\\s+(data|record|profile)|under(\\s+|-)(18|sixteen|eighteen)|student\\s+(record|data|profile)|guardian\\s+consent)",
                ),
            ),
        ),
        R(
            "egypt-pdpl.cross-border-language-output",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 14: Cross-border data transfer language detected — PDPC approval or documented Art. 15 derogation required",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+egypt|cross.?border|international\\s+transfer|offshore|foreign\\s+server)",
                ),
            ),
        ),
        R(
            "egypt-pdpl.transfer-action-with-missing-destination-metadata",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 14: Cross-border transfer with no destination metadata — cannot verify equivalent protection; requires PDPC review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "egypt-pdpl.moderate-record-exports",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 6/14: Export of <value> records requires documented lawful basis and PDPC cross-border approval",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "egypt-pdpl.bulk-export-actions",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 6: Bulk personal data export requires documented lawful basis, PDPC accountability, and licensing verification",
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
            "egypt-pdpl.dpo-escalate-if-agent-advises-against",
            "escalate",
            "Egypt PDPL No. 151/2020 Art. 8: DPO appointment is mandatory for all data controllers — agent cannot advise against it",
            (
                (
                    "text",
                    "(?i)(no\\s+need\\s+(for\\s+)?(a\\s+)?dpo|skip(ping)?\\s+(the\\s+)?dpo|don'?t\\s+need\\s+(a\\s+)?data\\s+protection\\s+officer)",
                ),
            ),
        ),
        R(
            "egypt-pdpl.personal-data-access-logged-data-subject",
            "audit",
            "Egypt PDPL No. 151/2020 Art. 2: Personal data access logged — data subject rights (access, information) and PDPC accountability requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "egypt-pdpl.personal-data-modification-erasure-logged-data",
            "audit",
            "Egypt PDPL No. 151/2020 Art. 2: Personal data modification/erasure logged — data subject rights (correction, deletion, objection) and PDPC accountability",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "delete_user",
                        "edit_customer",
                        "erase_data",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "ethiopia-pdp": (
        R(
            "ethiopia-pdp.block-breach-suppression-eca-must-notified",
            "deny",
            "Ethiopia PDPP 1321/2024 Art. 43: Agent cannot suppress breach notifications — ECA must be notified within 72 hours of awareness",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+report)",
                ),
            ),
        ),
        R(
            "ethiopia-pdp.block-biometric-data-transmission",
            "deny",
            "Ethiopia PDPP 1321/2024 Art. 9: Biometric data detected — must not be transmitted without documented lawful basis and ECA notification",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "ethiopia-pdp.block-cross-border-transfer-non-permitted",
            "deny",
            "Ethiopia PDPP 1321/2024 Art. 18: Cross-border transfer to <value> blocked — region not in ECA adequacy-approved list",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "ET",
                        "af-east-1",
                        "af-south-1",
                        "et",
                        "ethiopia",
                    ),
                ),
            ),
        ),
        R(
            "ethiopia-pdp.block-transfer-non-et-country-without",
            "deny",
            "Ethiopia PDPP 1321/2024 Art. 20: Transfer to <value> blocked — no documented consent or adequacy basis on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "ET"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "ethiopia-pdp.block-unauthorised-access-signals",
            "deny",
            "Ethiopia Proclamation 958/2016: Unauthorised system access signal detected — blocked. This constitutes a criminal offence.",
            (
                (
                    "text",
                    "(?i)(unauthori[sz]ed\\s+(access|login|entry)|bypass(ing)?\\s+(auth|security|login)|circumvent(ing)?\\s+(access|control))",
                ),
            ),
        ),
        R(
            "ethiopia-pdp.block-fayda-national-id-output-fayda",
            "deny",
            "Ethiopia PDPP 1321/2024 Art. 43: Fayda/National ID number detected in agent output — blocked to prevent identity data breach",
            (
                (
                    "text",
                    "(?i)(fayda\\s+(id|number|no)|ethiopia\\s+(national\\s+)?id|mosip\\s+id)[\\s:=]{0,5}[0-9]{10,16}",
                ),
            ),
        ),
        R(
            "ethiopia-pdp.block-large-record-exports-data-sovereignty",
            "deny",
            "Ethiopia PDPP 1321/2024 Art. 22: Export of <value> records is disproportionate — requires Data Protection Officer review and ECA notification",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "ethiopia-pdp.health-genetic-sensitive-data",
            "escalate",
            "Ethiopia PDPP 1321/2024 Art. 9: Health/genetic sensitive data detected — requires explicit consent or documented lawful condition",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|HIV|genetic\\s+(data|test)|mental\\s+health|disability|prescription)",
                ),
            ),
        ),
        R(
            "ethiopia-pdp.special-category-data",
            "escalate",
            "Ethiopia PDPP 1321/2024 Art. 9: Special category personal data detected — requires explicit consent or lawful processing condition",
            (
                (
                    "text",
                    "(?i)(ethnic\\s+origin|tribe|political\\s+opinion|religious\\s+belief|trade\\s+union|sexual\\s+orientation|criminal\\s+conviction)",
                ),
            ),
        ),
        R(
            "ethiopia-pdp.cross-border-language-agent-output",
            "escalate",
            "Ethiopia PDPP 1321/2024 Art. 18: Cross-border data transfer language detected — requires ECA adequacy verification",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+ethiopia|cross.?border|international\\s+transfer|offshore)",
                ),
            ),
        ),
        R(
            "ethiopia-pdp.transfer-action-with-missing-destination-metadata",
            "escalate",
            "Ethiopia PDPP 1321/2024 Art. 20: Cross-border transfer with no destination metadata — cannot verify adequacy, requires human review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "ethiopia-pdp.moderate-record-exports-data-sovereignty",
            "escalate",
            "Ethiopia PDPP 1321/2024 Art. 22: Export of <value> records requires Data Protection Officer approval",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "ethiopia-pdp.bulk-export-actions",
            "escalate",
            "Ethiopia PDPP 1321/2024 Art. 22: Bulk personal data export requires documented lawful basis and ECA notification",
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
            "ethiopia-pdp.personal-data-access-logged-record-processing",
            "audit",
            "Ethiopia PDPP 1321/2024 Art. 46/52: Personal data access logged — record of processing operations and accountability requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "ethiopia-pdp.personal-data-modification-logged-record-processing",
            "audit",
            "Ethiopia PDPP 1321/2024 Art. 46/52: Personal data modification logged — record of processing operations and accountability requirement",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "edit_customer",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "ghana-dpa": (
        R(
            "ghana-dpa.block-breach-suppression-dpc-must-notified",
            "deny",
            "Ghana DPA Act 843 s.31: Agent cannot suppress breach notifications — DPC and affected data subjects must be notified promptly",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+(report|notification))",
                ),
            ),
        ),
        R(
            "ghana-dpa.block-biometric-data-transmission",
            "deny",
            "Ghana DPA Act 843 s.37: Biometric data detected — must not be transmitted without explicit consent and DPC notification",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "ghana-dpa.block-cross-border-transfer-non-permitted",
            "deny",
            "Ghana DPA Act 843 s.18(2): Cross-border transfer to region <value> blocked — destination country adequacy not verified with DPC",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "GH",
                        "af-south-1",
                        "af-west-1",
                        "gh",
                        "ghana",
                    ),
                ),
            ),
        ),
        R(
            "ghana-dpa.block-transfer-non-gh-country-without",
            "deny",
            "Ghana DPA Act 843 s.18(2): Transfer to <value> blocked — no documented consent or adequacy basis on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "GH"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "ghana-dpa.block-ghana-card-national-id-output",
            "deny",
            "Ghana DPA Act 843 / NIA Act 707: Ghana Card national ID detected in agent output — blocked to prevent identity data exposure",
            (
                (
                    "text",
                    "(?:(?i:ghana\\s+(?:card|id|national\\s+id))[\\s:#-]{0,5})?\\b(?:GHA-[0-9]{9}-[0-9]|GHA[0-9]{10})\\b",
                ),
            ),
        ),
        R(
            "ghana-dpa.block-disproportionate-record-exports",
            "deny",
            "Ghana DPA Act 843 s.17: Export of <value> records is disproportionate — data minimisation principle requires DPC accountability",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "ghana-dpa.health-medical-special-personal-data",
            "escalate",
            "Ghana DPA Act 843 s.37: Health/medical special personal data detected — requires explicit consent or documented lawful basis",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|\\bHIV\\b|genetic\\s+(data|test)|mental\\s+health|disability|prescription|clinical\\s+data)",
                ),
            ),
        ),
        R(
            "ghana-dpa.special-category-data",
            "escalate",
            "Ghana DPA Act 843 s.37: Special personal data detected — requires explicit consent and restricted processing",
            (
                (
                    "text",
                    "(?i)(ethnic\\s+origin|racial\\s+origin|tribe|political\\s+opinion|religious\\s+belief|trade\\s+union|sexual\\s+(life|orientation)|criminal\\s+(offence|conviction|record)|court\\s+proceedings)",
                ),
            ),
        ),
        R(
            "ghana-dpa.cross-border-language-agent-output",
            "escalate",
            "Ghana DPA Act 843 s.18(2): Cross-border data transfer language detected — destination country adequacy must be verified with DPC",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+ghana|cross.?border|international\\s+transfer|offshore|foreign\\s+server)",
                ),
            ),
        ),
        R(
            "ghana-dpa.transfer-action-with-missing-destination-metadata",
            "escalate",
            "Ghana DPA Act 843 s.18(2): Cross-border transfer with no destination metadata — cannot verify adequacy, requires human review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "ghana-dpa.moderate-record-exports",
            "escalate",
            "Ghana DPA Act 843 s.17: Export of <value> records requires documented purpose and DPC accountability",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "ghana-dpa.bulk-export-actions",
            "escalate",
            "Ghana DPA Act 843 s.17: Bulk personal data export requires documented lawful purpose and DPC notification",
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
            "ghana-dpa.personal-data-access-logged-data-subject",
            "audit",
            "Ghana DPA Act 843 s.33: Personal data access logged — data subject participation and DPC accountability requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "ghana-dpa.personal-data-modification-deletion-logged-data",
            "audit",
            "Ghana DPA Act 843 s.33: Personal data modification/deletion logged — data subject participation and DPC accountability requirement",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "delete_user",
                        "edit_customer",
                        "erase_data",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "kenya-dpa": (
        R(
            "kenya-dpa.block-breach-suppression",
            "deny",
            "Kenya DPA s.41: Agent cannot suppress breach notifications — 72-hour ODPC reporting obligation applies",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+report)",
                ),
            ),
        ),
        R(
            "kenya-dpa.block-transfer-non-permitted-region",
            "deny",
            "Kenya DPA s.49: Cross-border transfer to <value> blocked — region not in ODPC adequacy-approved list",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "KE",
                        "af-east-1",
                        "af-south-1",
                        "ke",
                        "kenya",
                    ),
                ),
            ),
        ),
        R(
            "kenya-dpa.block-transfer-non-ke-country-without",
            "deny",
            "Kenya DPA s.49: Transfer to country <value> blocked — no documented consent or adequacy basis on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "KE"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "kenya-dpa.block-processing-explicitly-stated-without-consent",
            "deny",
            "Kenya DPA s.26: Data processing without consent is prohibited — valid consent or documented legal basis required",
            (
                (
                    "text",
                    "(?i)(process(ing)?|shar(ing)?|us(ing)?).{0,30}(without\\s+consent|no\\s+consent|bypass.{0,10}consent)",
                ),
            ),
        ),
        R(
            "kenya-dpa.block-biometric-data-transmission",
            "deny",
            "Kenya DPA s.25: Biometric data detected — must not be transmitted without documented lawful basis",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "kenya-dpa.block-national-id-output",
            "deny",
            "Kenya DPA: National ID number detected in agent output — blocked to prevent identity exposure",
            (("text", "(?i)(national\\s+id|id\\s+number|identity\\s+card)[\\s:=]{0,5}[0-9]{6,8}"),),
        ),
        R(
            "kenya-dpa.block-large-record-exports",
            "deny",
            "Kenya DPA s.30: Export of <value> records is disproportionate — requires Data Protection Officer review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "kenya-dpa.health-medical-data-requires-approval",
            "escalate",
            "Kenya DPA s.25: Health/medical sensitive personal data detected — requires explicit consent or documented legal basis",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|HIV|genetic\\s+(data|test)|mental\\s+health|disability|prescription)",
                ),
            ),
        ),
        R(
            "kenya-dpa.special-category-data-requires-approval",
            "escalate",
            "Kenya DPA s.25: Special category personal data detected — explicit consent or Schedule 3 condition required",
            (
                (
                    "text",
                    "(?i)(ethnic\\s+origin|race|religion|political\\s+opinion|sexual\\s+orientation|trade\\s+union|criminal\\s+conviction)",
                ),
            ),
        ),
        R(
            "kenya-dpa.cross-border-language-output",
            "escalate",
            "Kenya DPA s.49: Cross-border data transfer language detected — requires ODPC adequacy verification",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+kenya|cross.?border|international\\s+transfer|offshore)",
                ),
            ),
        ),
        R(
            "kenya-dpa.transfer-with-missing-destination-metadata",
            "escalate",
            "Kenya DPA s.49: Cross-border transfer with no destination metadata — cannot verify adequacy, requires human review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "kenya-dpa.moderate-record-exports",
            "escalate",
            "Kenya DPA s.30: Export of <value> records requires Data Protection Officer approval before execution",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "kenya-dpa.bulk-export-actions",
            "escalate",
            "Kenya DPA s.30: Bulk personal data export requires documented lawful basis and DPO approval",
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
            "kenya-dpa.all-personal-data-access-must-logged",
            "audit",
            "Kenya DPA s.31: Personal data access logged — ODPC accountability audit trail requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "kenya-dpa.all-personal-data-modifications-must-logged",
            "audit",
            "Kenya DPA s.31: Personal data modification logged — ODPC accountability audit trail requirement",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "edit_customer",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "mauritius-dpa": (
        R(
            "mauritius-dpa.72-hour-commissioner-notification-data-subjects",
            "deny",
            "Mauritius DPA 2017 (Breach Notification): Agent cannot suppress breach notifications — Commissioner must be notified within 72 hours; data subjects notified without undue delay where high risk",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+(report|notification))",
                ),
            ),
        ),
        R(
            "mauritius-dpa.biometric-data-uniquely-identifying-genetic-or",
            "deny",
            "Mauritius DPA 2017 (Special Categories): Biometric data detected — uniquely identifying biometrics are a special category; must not be transmitted without documented lawful basis and safeguards",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "mauritius-dpa.all-controllers-processors-must-register-registration",
            "deny",
            "Mauritius DPA 2017 (Registration): Agent cannot advise bypassing Commissioner registration — all controllers and processors must register (penalty: MUR 200,000 or 5 years imprisonment)",
            (
                (
                    "text",
                    "(?i)(process(ing)?\\s+(without|skip|bypass|ignore).{0,30}(register|registration|Commissioner|permit)|no\\s+need\\s+(to\\s+)?(register|notify\\s+(the\\s+)?Commissioner))",
                ),
            ),
        ),
        R(
            "mauritius-dpa.mauritius-national-id-card-format-z",
            "deny",
            "Mauritius DPA 2017 (Breach Notification / Security): Mauritius National ID Card (NIC) detected in agent output — blocked; triggers Commissioner breach notification within 72 hours",
            (
                (
                    "text",
                    "(?i)(mauritius\\s+(national\\s+)?(id|identity|nic|card)|national\\s+(identity\\s+)?card\\s+(no|number|#)|NIC\\s+(no|number|#))[\\s:=]{0,5}[A-Z][0-9]{13}",
                ),
            ),
        ),
        R(
            "mauritius-dpa.cross-border-non-permitted-region-requires",
            "deny",
            "Mauritius DPA 2017 (Transfer): Cross-border transfer to region <value> blocked — proof of appropriate safeguards must be filed with the Commissioner or a valid derogation (consent, contract, public interest, legal claims) established",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "MU",
                        "af-east-1",
                        "af-south-1",
                        "af-south-2",
                        "mauritius",
                        "mu",
                    ),
                ),
            ),
        ),
        R(
            "mauritius-dpa.transfer-non-mu-country-without-documented",
            "deny",
            "Mauritius DPA 2017 (Transfer): Transfer to <value> blocked — no documented consent or derogation (contract, vital interest, public interest, legal claims) filed with Commissioner",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "MU"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "mauritius-dpa.large-record-exports-without-documented-safeguards",
            "deny",
            "Mauritius DPA 2017 (Transfer / Security): Export of <value> records exceeds threshold — requires proof of appropriate safeguards filed with Commissioner and documented lawful basis",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "mauritius-dpa.health-medical-genetic-mental-health-data",
            "escalate",
            "Mauritius DPA 2017 (Special Categories): Health/genetic/mental health data detected — requires lawful basis + legitimate controller activities + appropriate safeguards filed with Commissioner",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|HIV|genetic\\s+(data|test)|mental\\s+health|disability|prescription|clinical\\s+data|psychological\\s+(report|assessment))",
                ),
            ),
        ),
        R(
            "mauritius-dpa.racial-ethnic-political-religious-trade-union",
            "escalate",
            "Mauritius DPA 2017 (Special Categories): Special category personal data detected — requires lawful basis + controller's legitimate activities + appropriate safeguards",
            (
                (
                    "text",
                    "(?i)(racial\\s+origin|ethnic\\s+origin|political\\s+opinion|political\\s+adherence|religious\\s+belief|philosophical\\s+belief|trade\\s+union|sexual\\s+(orientation|practice|preference)|criminal\\s+(proceeding|offence|conviction|record))",
                ),
            ),
        ),
        R(
            "mauritius-dpa.mandatory-all-controllers-processors-deny-if",
            "deny",
            "Mauritius DPA 2017 (DPO): DPO appointment is mandatory for ALL controllers and processors — stricter than GDPR; no size threshold exemption applies in Mauritius",
            (
                (
                    "text",
                    "(?i)(no\\s+need\\s+(for\\s+)?(a\\s+)?dpo|skip(ping)?\\s+(the\\s+)?dpo|don'?t\\s+need\\s+(a\\s+)?data\\s+protection\\s+officer|dpo\\s+(is\\s+)?(optional|not\\s+required))",
                ),
            ),
        ),
        R(
            "mauritius-dpa.cross-border-language-agent-output",
            "escalate",
            "Mauritius DPA 2017 (Transfer): Cross-border data transfer language detected — proof of appropriate safeguards must be filed with the Commissioner before data leaves Mauritius",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+mauritius|cross.?border|international\\s+transfer|offshore|foreign\\s+server)",
                ),
            ),
        ),
        R(
            "mauritius-dpa.transfer-action-with-missing-destination-metadata",
            "escalate",
            "Mauritius DPA 2017 (Transfer): Cross-border transfer action with no destination metadata — destination and safeguards must be documented before Commissioner review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "mauritius-dpa.moderate-record-exports",
            "escalate",
            "Mauritius DPA 2017 (Transfer / Security): Export of <value> records requires documented lawful basis and proof of appropriate safeguards filed with Commissioner",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "mauritius-dpa.bulk-export-actions",
            "escalate",
            "Mauritius DPA 2017 (Transfer / Security): Bulk personal data export requires proof of appropriate safeguards filed with Commissioner and documented lawful basis",
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
            "mauritius-dpa.transparency-obligation-data-subjects-must-informed",
            "escalate",
            "Mauritius DPA 2017 (Automated Decisions): Automated decision-making including profiling — data subject must be informed of the logic involved, significance and envisaged consequences before the decision is applied",
            (
                (
                    "action_in",
                    (
                        "algorithmic_decision",
                        "auto_approve",
                        "auto_deny",
                        "auto_reject",
                        "auto_score",
                        "automated_credit",
                    ),
                ),
            ),
        ),
        R(
            "mauritius-dpa.access-rectification-restriction-erasure-objection-complaint",
            "audit",
            "Mauritius DPA 2017 (Collection / Data Subject Rights): Personal data access logged — data subject rights (access, information) and Commissioner accountability requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "mauritius-dpa.personal-data-modification-erasure-logged-data",
            "audit",
            "Mauritius DPA 2017 (Collection / Data Subject Rights): Personal data modification/erasure logged — data subject rights (rectification, restriction, erasure) and Commissioner accountability",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "delete_user",
                        "edit_customer",
                        "erase_data",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "nigeria-ndpa": (
        R(
            "nigeria-ndpa.block-transfer-non-permitted-region",
            "deny",
            "NDPA s.25: Cross-border transfer to <value> blocked — region not in NDPC adequacy-approved list",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "NG",
                        "af-south-1",
                        "ng",
                        "ng-lag-1",
                        "nigeria",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-ndpa.block-transfer-non-nigerian-country-code",
            "deny",
            "NDPA s.25: Transfer to country <value> blocked — no documented consent or adequacy basis on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "NG"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "nigeria-ndpa.block-bulk-data-exports",
            "deny",
            "NDPA s.24: Bulk personal data export violates data minimisation principle — not permitted without documented legal basis",
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
            "nigeria-ndpa.block-large-record-exports",
            "deny",
            "NDPA s.24: Export of <value> records is presumptively disproportionate — requires Data Protection Officer review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "nigeria-ndpa.block-biometric-data-transmission",
            "deny",
            "NDPA Schedule 1: Biometric data detected — must not be transmitted by AI agents without documented lawful basis",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "nigeria-ndpa.block-breach-suppression",
            "deny",
            "NDPA s.22(5): Agent cannot suppress breach notifications — 72-hour NDPC reporting obligation applies",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+report)",
                ),
            ),
        ),
        R(
            "nigeria-ndpa.cross-border-transfer-with-missing-destination",
            "escalate",
            "NDPA s.25: Cross-border transfer action with no destination metadata — cannot verify adequacy, requires human review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "nigeria-ndpa.detected-cross-border-language-output",
            "escalate",
            "NDPA s.25: Cross-border data transfer language detected in output — requires NDPC adequacy verification",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+nigeria|cross.?border|international\\s+transfer|offshore)",
                ),
            ),
        ),
        R(
            "nigeria-ndpa.health-medical-data-requires-approval-before",
            "escalate",
            "NDPA Schedule 1: Health/medical data detected — sensitive personal data requires explicit lawful basis",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|HIV|mental\\s+health|disability|prescription)",
                ),
            ),
        ),
        R(
            "nigeria-ndpa.moderate-record-count-requires-approval",
            "escalate",
            "NDPA s.24: Export of <value> records requires Data Protection Officer approval before execution",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "nigeria-ndpa.all-pii-access-must-logged-ndpc",
            "audit",
            "NDPA s.30: Personal data access logged — accountability audit trail for NDPC compliance",
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
                    ),
                ),
            ),
        ),
        R(
            "nigeria-ndpa.all-pii-modifications-must-logged",
            "audit",
            "NDPA s.30: Personal data modification logged — accountability audit trail for NDPC compliance",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "edit_customer",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "nigeria-nfiu-aml": (
        R(
            "nigeria-nfiu-aml.transfer-exceeding-10m-cap-hard-block",
            "deny",
            "NFIU CTR / CBN NIP: ₦<value> exceeds ₦10,000,000 NIP single-transaction cap — blocked. CTR filing required.",
            (
                (
                    "action_in",
                    (
                        "disburse_funds",
                        "instant_payment",
                        "nip_transfer",
                        "send_money",
                        "transfer_funds",
                        "wire_transfer",
                    ),
                ),
                ("param", "amount", ">", 10000000),
            ),
        ),
        R(
            "nigeria-nfiu-aml.structuring-explicit-split-pattern-output",
            "deny",
            "NFIU Structuring (MLPPA s.14): Transaction splitting to avoid CTR threshold detected — constitutes structuring, a criminal offence",
            (
                (
                    "text",
                    "(?i)(split(ting)?|break(ing)?\\s+(up|down)|divide|multiple\\s+(transfers|payments|transactions)).{0,60}(avoid|under|below).{0,30}(threshold|limit|reporting|₦5|5\\s*million)",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.kyc-bypass-attempt",
            "deny",
            "NFIU / CBN AML: KYC bypass blocked — proceeding without customer verification violates MLPPA and CBN AML/CFT Framework",
            (
                (
                    "text",
                    "(?i)(skip\\s+(kyc|verification|identity\\s+check)|proceed\\s+without\\s+(verification|kyc)|waive\\s+(kyc|due\\s+diligence)|bypass\\s+(kyc|customer\\s+verification))",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.transaction-unverified-customer",
            "deny",
            "NFIU / CBN AML: Transaction for unverified customer blocked — KYC must be completed before processing",
            (
                (
                    "text",
                    "(?i)(unverified\\s+customer|customer\\s+not\\s+verified|no\\s+kyc|kyc\\s+(pending|incomplete|failed)).{0,40}(proceed|transfer|payment|transaction)",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.exact-numeric-ctr-threshold-structured-params",
            "escalate",
            "NFIU CTR (MLPPA s.10): Transfer of ₦<value> is at or above ₦5,000,000 CTR threshold — requires human review and CTR filing assessment",
            (
                (
                    "action_in",
                    (
                        "disburse_funds",
                        "instant_payment",
                        "nip_transfer",
                        "send_money",
                        "transfer_funds",
                        "wire_transfer",
                    ),
                ),
                ("param", "amount", ">=", 5000000),
                ("param", "amount", "<=", 10000000),
            ),
        ),
        R(
            "nigeria-nfiu-aml.round-trip-layering-pattern-output",
            "escalate",
            "NFIU STR Indicator: Round-trip or layering transaction pattern detected — requires human review for STR assessment",
            (
                (
                    "text",
                    "(?i)(transfer.{0,30}back|send.{0,20}return|round.?trip|circular.{0,20}transfer|layering)",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.unverified-or-unknown-counterparty",
            "escalate",
            "NFIU STR Indicator: Transfer to unverified or unknown counterparty — requires human review before execution",
            (
                (
                    "text",
                    "(?i)(unknown\\s+(account|beneficiary|recipient)|unverified\\s+(account|party)|no\\s+(kyc|verification)\\s+on\\s+(file|record))",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.cash-equivalent-or-crypto-conversion",
            "escalate",
            "NFIU STR Indicator: Cash-equivalent or crypto conversion — common money laundering typology, requires human review",
            (
                (
                    "text",
                    "(?i)(gift\\s+card|crypto|bitcoin|usdt|stable.?coin|mobile\\s+money\\s+to\\s+cash|convert.{0,20}to\\s+cash)",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.politically-exposed-person-transaction",
            "escalate",
            "NFIU STR / FATF Rec. 12: Politically Exposed Person (PEP) transaction detected — enhanced due diligence required",
            (
                (
                    "text",
                    "(?i)(PEP|politically\\s+exposed|government\\s+official|public\\s+servant|elected\\s+official|minister|senator|governor).{0,40}(transfer|payment|account|transaction)",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.financial-transaction-logged-5-year-retention",
            "audit",
            "NFIU Record-Keeping (MLPPA s.6): Financial transaction logged — 5-year retention required for NFIU examination on demand",
            (
                (
                    "action_re",
                    "^(?:transfer_|payment_|refund_|credit_|debit_|settlement_|reversal_|disbursement_)",
                ),
            ),
        ),
        R(
            "nigeria-nfiu-aml.amount-just-under-threshold-zone",
            "audit",
            "NFIU Structuring Alert: ₦<value> is just under ₦5M CTR threshold — logged for STR review. Multiple occurrences in session may indicate structuring.",
            (
                (
                    "action_in",
                    (
                        "disburse_funds",
                        "instant_payment",
                        "nip_transfer",
                        "send_money",
                        "transfer_funds",
                        "wire_transfer",
                    ),
                ),
                ("param", "amount", ">=", 4500000),
                ("param", "amount", "<", 5000000),
            ),
        ),
    ),
    "south-africa-popia": (
        R(
            "south-africa-popia.biometric-personal-information-output",
            "deny",
            "POPIA s.26(1)(f): Biometric personal information detected in agent output — requires documented POPIA s.27 exception",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data|record))",
                ),
            ),
        ),
        R(
            "south-africa-popia.children-s-personal-information",
            "deny",
            "POPIA s.26(1)(h): Children's personal information must not be processed by AI agents without a separate consent framework",
            (
                (
                    "text",
                    "(?i)(minor|child\\s+(data|record|profile|account)|under\\s+(18|sixteen|fourteen)|children'?s\\s+(data|information|personal\\s+info))",
                ),
            ),
        ),
        R(
            "south-africa-popia.sa-id-number-detected-output",
            "deny",
            "POPIA s.19: SA ID Number (13-digit) detected in agent output — blocked to prevent sensitive identifier exposure",
            (("text", "\\b[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[0-9]{7}\\b"),),
        ),
        R(
            "south-africa-popia.sa-id-number-with-contextual-label",
            "deny",
            "POPIA s.19: SA ID Number value detected in agent response — blocked",
            (
                (
                    "text",
                    "(?i)(id\\s+number|identity\\s+number|sa\\s+id|south\\s+african\\s+id)[\\s:=]+[0-9]{13}",
                ),
            ),
        ),
        R(
            "south-africa-popia.breach-notification-suppression",
            "deny",
            "POPIA s.22: Agent cannot suppress or delay breach notification — Information Regulator must be notified without unreasonable delay",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident|leak)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+report)",
                ),
            ),
        ),
        R(
            "south-africa-popia.transfer-non-adequate-country-without-consent",
            "deny",
            "POPIA s.72: Transfer to <value> blocked — country not recognised as having substantially similar data protection to POPIA",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                (
                    "not_param",
                    "destination_country",
                    "in",
                    (
                        "BE",
                        "CA",
                        "DE",
                        "DK",
                        "FI",
                        "FR",
                        "GB",
                        "IE",
                        "KE",
                        "NG",
                        "NL",
                        "NO",
                        "NZ",
                        "SE",
                        "ZA",
                    ),
                ),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "south-africa-popia.purpose-limitation-processing-beyond-original-consent",
            "deny",
            "POPIA s.11: Purpose limitation — agent cannot process personal information for a purpose beyond the original consent",
            (
                (
                    "text",
                    "(?i)(process(ing)?.{0,40}(beyond|outside|new\\s+purpose|repurpose|use\\s+for\\s+something\\s+else)|(data|information).{0,30}(without\\s+(consent|permission|authorisation)))",
                ),
            ),
        ),
        R(
            "south-africa-popia.any-cross-border-transfer-action-requires",
            "escalate",
            "POPIA s.72: Cross-border personal information transfer requires Information Officer approval and destination adequacy assessment",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
            ),
        ),
        R(
            "south-africa-popia.cross-border-transfer-language-output",
            "escalate",
            "POPIA s.72: Cross-border data transfer language detected — requires Information Officer approval",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?|upload(ing)?).{0,60}(outside\\s+south\\s+africa|cross.?border|international\\s+transfer|offshore|foreign\\s+server)",
                ),
            ),
        ),
        R(
            "south-africa-popia.health-medical-special-personal-information",
            "escalate",
            "POPIA s.26(1)(e): Health/medical special personal information detected — requires explicit lawful basis under POPIA s.27",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|HIV|mental\\s+health|disability|chronic\\s+illness|prescription|clinical)",
                ),
            ),
        ),
        R(
            "south-africa-popia.race-ethnic-origin-special-personal-information",
            "escalate",
            "POPIA s.26(1)(b): Race/ethnic origin special personal information — requires lawful basis and heightened controls",
            (
                (
                    "text",
                    "(?i)(race|ethnic\\s+origin|racial\\s+(group|classification)|coloured|population\\s+group)",
                ),
            ),
        ),
        R(
            "south-africa-popia.criminal-history-special-personal-information",
            "escalate",
            "POPIA s.26(1)(g): Criminal history special personal information — requires explicit lawful processing basis",
            (
                (
                    "text",
                    "(?i)(criminal\\s+(record|history|conviction|background)|prior\\s+(offence|offense|conviction)|police\\s+clearance)",
                ),
            ),
        ),
        R(
            "south-africa-popia.all-personal-information-access-must-logged",
            "audit",
            "POPIA s.17: Personal information access logged — RESPONSIBLE PARTY accountability record for Information Regulator",
            (
                (
                    "action_in",
                    (
                        "access_data",
                        "fetch_record",
                        "get_profile",
                        "lookup_account",
                        "query_personal",
                        "read_customer",
                    ),
                ),
            ),
        ),
    ),
    "nigeria-pos-geofencing": (
        R(
            "nigeria-pos-geofencing.location-must-verified-before-pos-action",
            "deny",
            "CBN POS Geo-Fencing: location must be verified before a POS action",
            (
                (
                    "action_in",
                    (
                        "pos_charge",
                        "pos_payment",
                        "pos_transaction",
                        "swipe_card",
                        "tap_pay",
                        "terminal_transaction",
                    ),
                ),
                ("ctx_get", "location_verified", False, "!=", True),
            ),
        ),
        R(
            "nigeria-pos-geofencing.terminal-location-does-not-match-its",
            "deny",
            "CBN POS Geo-Fencing: terminal location does not match its registered zone",
            (
                (
                    "text",
                    "(?i)(terminal|pos).{0,60}(outside|beyond|not\\s+in|mismatch|wrong).{0,40}(zone|region|location|registered\\s+area|geo.?fence)",
                ),
            ),
        ),
        R(
            "nigeria-pos-geofencing.location-verification-cannot-bypassed",
            "deny",
            "CBN POS Geo-Fencing: location verification cannot be bypassed",
            (
                (
                    "text",
                    "(?i)(bypass.{0,30}(geo.?fence|location\\s+check|geo.?zone)|disable.{0,30}(location\\s+verification|geo.?compliance)|skip.{0,20}(location|geo)\\s+(check|verify|validation))",
                ),
            ),
        ),
        R(
            "nigeria-pos-geofencing.terminal-registration-changes-require-human-approval",
            "escalate",
            "CBN Agent Banking: terminal registration changes require human approval",
            (
                (
                    "action_in",
                    (
                        "activate_terminal",
                        "deactivate_terminal",
                        "reassign_terminal",
                        "register_terminal",
                        "transfer_terminal",
                        "update_terminal_location",
                    ),
                ),
            ),
        ),
        R(
            "nigeria-pos-geofencing.high-value-pos-transaction-requires-human",
            "escalate",
            "CBN Agent Banking: high-value POS transaction requires human approval",
            (
                (
                    "text",
                    "(?i)(pos|terminal|point.of.sale).{0,60}(₦|NGN)\\s*[3-9][0-9]{2},?[0-9]{3}",
                ),
            ),
        ),
        R(
            "nigeria-pos-geofencing.terminal-action-recorded",
            "audit",
            "CBN POS Audit: terminal action recorded",
            (("action_re", "^(pos_|terminal_|merchant_).*"),),
        ),
    ),
    "rwanda-dpa": (
        R(
            "rwanda-dpa.block-breach-suppression-48-hour-ncsa",
            "deny",
            "Rwanda Law 058/2021 Art. 43: Agent cannot suppress breach notifications — NCSA must be notified within 48 hours (strictest timeline in Africa)",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+(report|notification))",
                ),
            ),
        ),
        R(
            "rwanda-dpa.block-biometric-data-transmission",
            "deny",
            "Rwanda Law 058/2021 Art. 3(2)/10: Biometric data detected — must not be transmitted without documented lawful basis and NCSA notification",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "rwanda-dpa.block-cross-border-transfer-non-permitted",
            "deny",
            "Rwanda Law 058/2021 Art. 48: Cross-border transfer to region <value> blocked — destination country adequacy not established with NCSA",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "RW",
                        "af-east-1",
                        "af-south-1",
                        "rw",
                        "rwanda",
                    ),
                ),
            ),
        ),
        R(
            "rwanda-dpa.block-transfer-non-rw-country-without",
            "deny",
            "Rwanda Law 058/2021 Art. 48/49: Transfer to <value> blocked — no documented consent or contractual safeguards on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "RW"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "rwanda-dpa.block-rwanda-national-id-output",
            "deny",
            "Rwanda Law 058/2021 Art. 43: Rwanda National ID (NIDA 16-digit) detected in agent output — blocked to prevent identity data breach",
            (
                (
                    "text",
                    "(?i)(rwanda\\s+(national\\s+)?id|nida\\s+(id|number|no)|rwandan\\s+id)[\\s:=]{0,5}[0-9]{16}",
                ),
            ),
        ),
        R(
            "rwanda-dpa.block-large-record-exports",
            "deny",
            "Rwanda Law 058/2021 Art. 50: Export of <value> records exceeds threshold — requires NCSA contractual safeguards and DPO review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "rwanda-dpa.health-medical-sensitive-data",
            "escalate",
            "Rwanda Law 058/2021 Art. 3(2)/10: Health/medical sensitive data detected — requires explicit consent or documented lawful basis",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|\\bHIV\\b|genetic\\s+(data|test)|mental\\s+health|disability|prescription|clinical\\s+data)",
                ),
            ),
        ),
        R(
            "rwanda-dpa.special-category-data",
            "escalate",
            "Rwanda Law 058/2021 Art. 3(2)/10: Special category personal data detected — requires specific processing grounds (Art. 10)",
            (
                (
                    "text",
                    "(?i)(racial\\s+origin|ethnic\\s+origin|social\\s+origin|political\\s+opinion|religious\\s+belief|philosophical\\s+belief|sexual\\s+(life|orientation)|family\\s+(detail|data)|criminal\\s+(record|conviction))",
                ),
            ),
        ),
        R(
            "rwanda-dpa.automated-individual-decision-making-data-subject",
            "escalate",
            "Rwanda Law 058/2021 Art. 21: Automated individual decision-making — data subject has right to contest; escalate for human oversight",
            (
                (
                    "action_in",
                    (
                        "algorithmic_decision",
                        "auto_approve",
                        "auto_deny",
                        "auto_reject",
                        "auto_score",
                        "automated_credit",
                    ),
                ),
            ),
        ),
        R(
            "rwanda-dpa.cross-border-language-output",
            "escalate",
            "Rwanda Law 058/2021 Art. 48: Cross-border data transfer language detected — adequacy and contractual safeguards (Art. 49) required",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+rwanda|cross.?border|international\\s+transfer|offshore|foreign\\s+server)",
                ),
            ),
        ),
        R(
            "rwanda-dpa.transfer-action-with-missing-destination-metadata",
            "escalate",
            "Rwanda Law 058/2021 Art. 48: Cross-border transfer with no destination metadata — cannot verify adequacy, requires human review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "rwanda-dpa.moderate-record-exports",
            "escalate",
            "Rwanda Law 058/2021 Art. 50: Export of <value> records requires NCSA contractual safeguard documentation",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "rwanda-dpa.bulk-export-actions",
            "escalate",
            "Rwanda Law 058/2021 Art. 50: Bulk personal data export requires documented lawful basis and NCSA notification",
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
            "rwanda-dpa.personal-data-access-logged-data-subject",
            "audit",
            "Rwanda Law 058/2021 Art. 18: Personal data access logged — data subject access right and NCSA accountability requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "rwanda-dpa.personal-data-modification-erasure-logged-data",
            "audit",
            "Rwanda Law 058/2021 Art. 23/24: Personal data modification/erasure logged — data subject rights and NCSA accountability requirement",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "delete_user",
                        "edit_customer",
                        "erase_data",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "tanzania-pdpa": (
        R(
            "tanzania-pdpa.block-breach-suppression",
            "deny",
            "Tanzania PDPA s.28: Agent cannot suppress breach notifications — 72-hour PDPC reporting obligation applies",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+report)",
                ),
            ),
        ),
        R(
            "tanzania-pdpa.block-biometric-data-transmission",
            "deny",
            "Tanzania PDPA s.17: Biometric data detected — must not be transmitted without documented lawful basis",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "tanzania-pdpa.block-transfer-non-permitted-region",
            "deny",
            "Tanzania PDPA s.13: Cross-border transfer to <value> blocked — region not in PDPC adequacy-approved list",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "TZ",
                        "af-east-1",
                        "af-south-1",
                        "tanzania",
                        "tz",
                    ),
                ),
            ),
        ),
        R(
            "tanzania-pdpa.block-transfer-non-tz-country-without",
            "deny",
            "Tanzania PDPA s.13: Transfer to country <value> blocked — no documented consent or adequacy basis on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "TZ"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "tanzania-pdpa.block-processing-without-consent",
            "deny",
            "Tanzania PDPA s.8: Data processing without lawful basis is prohibited — valid consent or documented legal basis required",
            (
                (
                    "text",
                    "(?i)(process(ing)?|shar(ing)?|us(ing)?).{0,30}(without\\s+consent|no\\s+consent|bypass.{0,10}consent)",
                ),
            ),
        ),
        R(
            "tanzania-pdpa.block-nida-national-id-output",
            "deny",
            "Tanzania PDPA: NIDA national ID number detected in agent output — blocked to prevent identity exposure",
            (
                (
                    "text",
                    "(?i)(nida\\s+(number|no|#)|national\\s+id|tanzania\\s+id)[\\s:=]{0,5}[0-9]{20}",
                ),
            ),
        ),
        R(
            "tanzania-pdpa.block-large-record-exports",
            "deny",
            "Tanzania PDPA s.30: Export of <value> records is disproportionate — requires Data Protection Officer review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "tanzania-pdpa.health-medical-data",
            "escalate",
            "Tanzania PDPA s.17: Health/medical special category data detected — requires explicit consent or documented legal basis",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|HIV|genetic\\s+(data|test)|mental\\s+health|disability|prescription)",
                ),
            ),
        ),
        R(
            "tanzania-pdpa.special-category-data",
            "escalate",
            "Tanzania PDPA s.17: Special category personal data detected — explicit consent or lawful processing condition required",
            (
                (
                    "text",
                    "(?i)(ethnic\\s+origin|race|tribe|political\\s+opinion|religious\\s+belief|trade\\s+union|sexual\\s+orientation|criminal\\s+conviction)",
                ),
            ),
        ),
        R(
            "tanzania-pdpa.cross-border-language-output",
            "escalate",
            "Tanzania PDPA s.13: Cross-border data transfer language detected — requires PDPC adequacy verification",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+tanzania|cross.?border|international\\s+transfer|offshore)",
                ),
            ),
        ),
        R(
            "tanzania-pdpa.transfer-with-missing-destination-metadata",
            "escalate",
            "Tanzania PDPA s.13: Cross-border transfer with no destination metadata — cannot verify adequacy, requires human review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "tanzania-pdpa.moderate-record-exports",
            "escalate",
            "Tanzania PDPA s.30: Export of <value> records requires Data Protection Officer approval",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "tanzania-pdpa.bulk-export-actions",
            "escalate",
            "Tanzania PDPA s.30: Bulk personal data export requires documented lawful basis and DPO approval",
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
            "tanzania-pdpa.personal-data-access-logged-pdpc-accountability",
            "audit",
            "Tanzania PDPA s.25: Personal data access logged — PDPC accountability audit trail requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "tanzania-pdpa.personal-data-modification-logged-pdpc-accountability",
            "audit",
            "Tanzania PDPA s.25: Personal data modification logged — PDPC accountability audit trail requirement",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "edit_customer",
                        "modify_profile",
                        "patch_account",
                        "update_user",
                    ),
                ),
            ),
        ),
    ),
    "uganda-dppa": (
        R(
            "uganda-dppa.block-breach-suppression",
            "deny",
            "Uganda DPPA s.22: Agent cannot suppress breach notifications — 72-hour PDPO reporting obligation applies",
            (
                (
                    "text",
                    "(?i)(don'?t\\s+(report|notify|disclose)|hide\\s+(the\\s+)?(breach|incident)|suppress\\s+(alert|notification)|delay\\s+(breach|incident)\\s+report)",
                ),
            ),
        ),
        R(
            "uganda-dppa.block-biometric-data-transmission",
            "deny",
            "Uganda DPPA s.13: Biometric data detected — must not be transmitted without documented lawful basis",
            (
                (
                    "text",
                    "(?i)(fingerprint|facial\\s+recognition|retina|iris\\s+scan|voice\\s+print|biometric\\s+(template|hash|data))",
                ),
            ),
        ),
        R(
            "uganda-dppa.block-transfer-non-permitted-region",
            "deny",
            "Uganda DPPA s.19: Cross-border transfer to <value> blocked — region not in PDPO adequacy-approved list",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_region", "!=", None),
                (
                    "not_param",
                    "destination_region",
                    "in",
                    (
                        "UG",
                        "af-east-1",
                        "af-south-1",
                        "ug",
                        "uganda",
                    ),
                ),
            ),
        ),
        R(
            "uganda-dppa.block-transfer-non-ug-country-without",
            "deny",
            "Uganda DPPA s.19: Transfer to country <value> blocked — no documented consent or adequacy basis on file",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "destination_country", "!=", None),
                ("param", "destination_country", "!=", "UG"),
                ("not_ctx", "consent_documented", "==", True),
            ),
        ),
        R(
            "uganda-dppa.block-national-id-output",
            "deny",
            "Uganda DPPA: National ID number (NIRA) detected in agent output — blocked to prevent identity exposure",
            (
                (
                    "text",
                    "(?i)(national\\s+id|nira\\s+number|uganda\\s+id)[\\s:=]{0,5}[A-Z]{2}[0-9]{9,12}",
                ),
            ),
        ),
        R(
            "uganda-dppa.block-large-record-exports",
            "deny",
            "Uganda DPPA s.4(e): Export of <value> records is disproportionate — requires Data Protection Officer review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 1000),
            ),
        ),
        R(
            "uganda-dppa.health-medical-data-requires-approval",
            "escalate",
            "Uganda DPPA s.13: Health/medical sensitive personal data detected — requires explicit consent or documented legal basis",
            (
                (
                    "text",
                    "(?i)(medical\\s+record|health\\s+(condition|status|data)|HIV|genetic\\s+(data|test)|mental\\s+health|disability|prescription)",
                ),
            ),
        ),
        R(
            "uganda-dppa.special-category-data-requires-approval",
            "escalate",
            "Uganda DPPA s.13: Special category personal data detected — explicit consent or lawful condition required",
            (
                (
                    "text",
                    "(?i)(ethnic\\s+origin|tribe|political\\s+opinion|religious\\s+belief|trade\\s+union|sexual\\s+orientation|criminal\\s+conviction)",
                ),
            ),
        ),
        R(
            "uganda-dppa.financial-data-requires-approval",
            "escalate",
            "Uganda DPPA s.13: Financial personal data detected — requires documented lawful basis",
            (
                (
                    "text",
                    "(?i)(bank\\s+account\\s+number|account\\s+balance|credit\\s+score|loan\\s+status|financial\\s+(record|data|history))",
                ),
            ),
        ),
        R(
            "uganda-dppa.cross-border-language-output",
            "escalate",
            "Uganda DPPA s.19: Cross-border data transfer language detected — requires PDPO adequacy verification",
            (
                (
                    "text",
                    "(?i)(send(ing)?|transfer(ring)?|export(ing)?).{0,60}(outside\\s+uganda|cross.?border|international\\s+transfer|offshore)",
                ),
            ),
        ),
        R(
            "uganda-dppa.transfer-with-missing-destination-metadata",
            "escalate",
            "Uganda DPPA s.19: Cross-border transfer with no destination metadata — cannot verify adequacy, requires human review",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("not_param_set", "destination_region"),
                ("not_param_set", "destination_country"),
            ),
        ),
        R(
            "uganda-dppa.moderate-record-exports",
            "escalate",
            "Uganda DPPA s.4(e): Export of <value> records requires Data Protection Officer approval",
            (
                (
                    "action_in",
                    (
                        "export_data",
                        "forward_to",
                        "relay_data",
                        "send_to_external",
                        "sync_to_remote",
                        "upload_to_cloud",
                    ),
                ),
                ("param", "record_count", ">", 100),
                ("param", "record_count", "<=", 1000),
            ),
        ),
        R(
            "uganda-dppa.bulk-export-actions",
            "escalate",
            "Uganda DPPA s.4(e): Bulk personal data export requires documented lawful basis and DPO approval",
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
            "uganda-dppa.all-personal-data-access-must-logged",
            "audit",
            "Uganda DPPA s.25: Personal data access logged — PDPO accountability audit trail requirement",
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
                    ),
                ),
            ),
        ),
        R(
            "uganda-dppa.all-personal-data-modifications-must-logged",
            "audit",
            "Uganda DPPA s.25: Personal data modification logged — PDPO accountability audit trail requirement",
            (
                (
                    "action_in",
                    (
                        "change_personal",
                        "edit_customer",
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


@check("pack.regional.africa", surfaces=["input", "output", "tool_args"])
def rules_regional_africa(ctx: CheckContext) -> dict[str, Any]:
    """Raises a risk for every translated regional/africa rule this call matches."""
    return run(RULES, ctx)
