"""Translating agent-governance policies: the published example corpus and the edges.

The corpus under `tests/corpus/agent_governance/` is the example policy library
published with the Agent Governance Toolkit, copied unmodified. Every file must
translate without an error, no deny may come out as anything weaker, and what does
not translate is listed here by name, so a change in coverage is a reviewed diff.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pytest

from agentfox.core.vocab import EFFECT_RANK
from agentfox.platform.policy import NativePolicyEngine, PolicyInput, lint_documents
from agentfox.platform.policy.compat.agent_governance import bundle_files, translate
from agentfox.platform.policy.compat.schema_check import validate

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "agent_governance" / "policies"
FILES = sorted(CORPUS.rglob("*.yaml"))
DENY_LIKE = {
    "deny",
    "denials",
    "require_approval",
    "escalate",
    "escalations",
    "blocked_tools",
}

UNTRANSLATABLE = [
    ("adk-agt-manifest.yaml", "adk_governance"),
    (
        "african-regulatory/agent-human-approval.yaml",
        "escalate: Human approval required: '%v' is designated as a human-appro",
    ),
    (
        "african-regulatory/agent-human-approval.yaml",
        "escalate: Human approval required: action risk level '%v' requires hum",
    ),
    (
        "african-regulatory/agent-human-approval.yaml",
        "escalate: Human approval required: bulk operation on %v records exceed",
    ),
    (
        "african-regulatory/agent-human-approval.yaml",
        "escalate: Human approval required: transaction amount %v exceeds confi",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "audit: Model routing audit: sensitive task '%v' processed by approved ",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "deny: Model routing denied: model '%v' is not approved for sensitive t",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "deny: Model routing denied: model '%v' is on the banned list.",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "escalate: Model routing: sensitive task type '%v' requires an explicit",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "audit: PII audit: action may produce personal data — output logged for",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "deny: PII leakage: BVN/NIN-format identifier (11-digit) detected in ag",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "deny: PII leakage: South African ID number detected in agent output — ",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "deny: PII leakage: credit/debit card number detected in agent output —",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "deny: PII leakage: custom high-sensitivity pattern detected in agent o",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "escalate: PII leakage: email address detected in agent output — route ",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "escalate: PII leakage: phone number detected in agent output — route t",
    ),
    (
        "african-regulatory/agent-prompt-injection.yaml",
        "deny: Prompt injection detected: input contains known injection patter",
    ),
    (
        "african-regulatory/agent-prompt-injection.yaml",
        "escalate: Potential prompt injection: structural injection marker dete",
    ),
    (
        "african-regulatory/agent-tool-permissions.yaml",
        "deny: Tool permission denied: '%v' is not in the allowed tools list.",
    ),
    (
        "african-regulatory/agent-tool-permissions.yaml",
        "deny: Tool permission denied: '%v' is on the denied list — action bloc",
    ),
    (
        "african-regulatory/agent-tool-permissions.yaml",
        "escalate: Tool requires human approval: '%v' is a restricted tool — ro",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "audit: NIMC Act 2026: Action '%v' is a mandatory-NIN service — bank ac",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "escalate: BVN/NIN Gate: Action '%v' involves %v identifier — requires ",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "escalate: NIMC Act 2026: BVN lookup attempted without a declared purpo",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "escalate: NIMC Act 2026: NIN lookup attempted without a declared purpo",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "escalate: NIMC Act 2026: Purpose mismatch — NIN was consented for '%v'",
    ),
    (
        "african-regulatory/cbn-transaction-limits.yaml",
        "escalate: CBN Tier 1: Transfer of ₦%v exceeds ₦50,000 Tier 1 limit — K",
    ),
    (
        "african-regulatory/cbn-transaction-limits.yaml",
        "escalate: CBN Tier 2: Transfer of ₦%v exceeds ₦200,000 Tier 2 daily li",
    ),
    (
        "african-regulatory/cbn-transaction-limits.yaml",
        "escalate: CBN Tier 3: Transfer of ₦%v is at or above ₦5,000,000 daily ",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "deny: Egypt PDPL No. 151/2020 Art. 14: Cross-border transfer to region",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "deny: Egypt PDPL No. 151/2020 Arts. 14-15: Transfer to '%v' blocked — ",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "escalate: Egypt PDPL No. 151/2020 Art. 14: Cross-border transfer with ",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "escalate: Egypt PDPL No. 151/2020 Art. 6/14: Export of %v records requ",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "deny: Ethiopia PDPP 1321/2024 Art. 18: Cross-border transfer to '%v' b",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "deny: Ethiopia PDPP 1321/2024 Art. 20: Transfer to '%v' blocked — no d",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "escalate: Ethiopia PDPP 1321/2024 Art. 20: Cross-border transfer with ",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "escalate: Ethiopia PDPP 1321/2024 Art. 22: Export of %v records requir",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "deny: Ghana DPA Act 843 s.18(2): Cross-border transfer to region '%v' ",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "deny: Ghana DPA Act 843 s.18(2): Transfer to '%v' blocked — no documen",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "escalate: Ghana DPA Act 843 s.17: Export of %v records requires docume",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "escalate: Ghana DPA Act 843 s.18(2): Cross-border transfer with no des",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "deny: Kenya DPA s.49: Cross-border transfer to '%v' blocked — region n",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "deny: Kenya DPA s.49: Transfer to country '%v' blocked — no documented",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "escalate: Kenya DPA s.30: Export of %v records requires Data Protectio",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "escalate: Kenya DPA s.49: Cross-border transfer with no destination me",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "deny: Mauritius DPA 2017 (Transfer): Cross-border transfer to region '",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "deny: Mauritius DPA 2017 (Transfer): Transfer to '%v' blocked — no doc",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "escalate: Mauritius DPA 2017 (Transfer / Security): Export of %v recor",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "escalate: Mauritius DPA 2017 (Transfer): Cross-border transfer action ",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "deny: NDPA s.25: Cross-border transfer to '%v' blocked — region not in",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "deny: NDPA s.25: Transfer to country '%v' blocked — no documented cons",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "escalate: NDPA s.24: Export of %v records requires Data Protection Off",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "escalate: NDPA s.25: Cross-border transfer action with no destination ",
    ),
    (
        "african-regulatory/nfiu-aml-str.yaml",
        "audit: NFIU Structuring Alert: ₦%v is just under ₦5M CTR threshold — l",
    ),
    (
        "african-regulatory/nfiu-aml-str.yaml",
        "escalate: NFIU CTR (MLPPA s.10): Transfer of ₦%v is at or above ₦5,000",
    ),
    (
        "african-regulatory/popia-south-africa.yaml",
        "deny: POPIA s.72: Transfer to '%v' blocked — country not recognised as",
    ),
    ("african-regulatory/pos-geofencing.yaml", "audit: CBN POS Audit: terminal action recorded"),
    (
        "african-regulatory/pos-geofencing.yaml",
        "deny: CBN POS Geo-Fencing: location must be verified before a POS acti",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "deny: Rwanda Law 058/2021 Art. 48/49: Transfer to '%v' blocked — no do",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "deny: Rwanda Law 058/2021 Art. 48: Cross-border transfer to region '%v",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "escalate: Rwanda Law 058/2021 Art. 48: Cross-border transfer with no d",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "escalate: Rwanda Law 058/2021 Art. 50: Export of %v records requires N",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "deny: Tanzania PDPA s.13: Cross-border transfer to '%v' blocked — regi",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "deny: Tanzania PDPA s.13: Transfer to country '%v' blocked — no docume",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "escalate: Tanzania PDPA s.13: Cross-border transfer with no destinatio",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "escalate: Tanzania PDPA s.30: Export of %v records requires Data Prote",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "deny: Uganda DPPA s.19: Cross-border transfer to '%v' blocked — region",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "deny: Uganda DPPA s.19: Transfer to country '%v' blocked — no document",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "escalate: Uganda DPPA s.19: Cross-border transfer with no destination ",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "escalate: Uganda DPPA s.4(e): Export of %v records requires Data Prote",
    ),
    ("atr-community-rules.yaml", "categories"),
    ("atr-community-rules.yaml", "suspicious_decoded_keywords"),
    ("conversation-guardian.yaml", "escalation_patterns"),
    ("conversation-guardian.yaml", "offensive_patterns"),
    ("conversation-guardian.yaml", "thresholds"),
    (
        "india-regulatory/aadhaar-pii-protection.yaml",
        "deny: Aadhaar Act s.29(4): no Aadhaar number shall be published, displ",
    ),
    (
        "india-regulatory/certin-2022-directions.yaml",
        "deny: CERT-In 2022 Directions (iv): logs must be retained within India",
    ),
    (
        "india-regulatory/certin-2022-directions.yaml",
        "escalate: CERT-In 2022 Directions (i): synchronise ICT system clocks t",
    ),
    (
        "india-regulatory/dpdp-data-protection.yaml",
        "deny: DPDP s.6: processing personal data requires a logged, purpose-sp",
    ),
    (
        "india-regulatory/dpdp-data-protection.yaml",
        "deny: DPDP s.8(5): personal data must be processed with reasonable sec",
    ),
    (
        "india-regulatory/rbi-data-localization.yaml",
        "deny: RBI 2018 (Storage of Payment System Data): payment data must be ",
    ),
    (
        "india-regulatory/rbi-data-localization.yaml",
        "deny: RBI 2018: payment data processed abroad must be purged and retur",
    ),
    (
        "india-regulatory/rbi-data-localization.yaml",
        "deny: RBI Master Direction KYC 2016: customer due diligence (KYC) is m",
    ),
    (
        "india-regulatory/sebi-governance.yaml",
        "deny: SEBI Amendment 10 Feb 2025: regulated entity is solely responsib",
    ),
    (
        "india-regulatory/sebi-governance.yaml",
        "deny: SEBI CSCRF 2024: audit logs must be retained within India, confi",
    ),
    (
        "india-regulatory/sebi-governance.yaml",
        "escalate: SEBI CSCRF 2024: periodic VAPT and cyber audit, data classif",
    ),
    (
        "lotl_prevention_policy.yaml",
        "denials: Potential remote code execution through a piped download",
    ),
    ("lotl_prevention_policy.yaml", "denials: Unauthorized access to sensitive system data"),
    ("mcp-security.yaml", "detection_patterns"),
    ("mcp-security.yaml", "suspicious_decoded_keywords"),
    ("pii-detection.yaml", "builtin_patterns"),
    ("production/enterprise.yaml", "denials: Tool call budget exceeded (50)"),
    ("production/financial.yaml", "denials: Tool call budget exceeded (30)"),
    ("production/healthcare.yaml", "denials: Tool call budget exceeded (25)"),
    ("production/minimal.yaml", "denials: Tool call budget exceeded (100)"),
    ("production/strict.yaml", "denials: Tool call budget exceeded (10)"),
    ("prompt-injection-safety.yaml", "detection_patterns"),
    ("prompt-injection-safety.yaml", "sensitivity_min_threat"),
    ("prompt-injection-safety.yaml", "sensitivity_thresholds"),
    ("prompt-injection-safety.yaml", "suspicious_decoded_keywords"),
    ("sandbox-safety.yaml", "sandbox"),
    ("semantic-policy.yaml", "signals"),
    ("sql-readonly.yaml", "sql_policy"),
    ("sql-safety.yaml", "sql_policy"),
    ("sql-strict.yaml", "sql_policy"),
    (
        "uk-regulatory/fca-financial-conduct.yaml",
        "deny: FCA market conduct: autonomous agent trading requires documented",
    ),
    (
        "uk-regulatory/fca-financial-conduct.yaml",
        "escalate: FCA Consumer Duty: AI-influenced pricing or eligibility deci",
    ),
    (
        "uk-regulatory/ico-automated-decisions.yaml",
        "escalate: UK GDPR Art. 22A: solely automated significant decision — ve",
    ),
    (
        "uk-regulatory/ico-automated-decisions.yaml",
        "escalate: UK GDPR Art. 22C(1): decision-specific explanation must be a",
    ),
    (
        "uk-regulatory/uk-gdpr-data-protection.yaml",
        "deny: UK GDPR Art. 44–46: transfer to '%v' blocked — requires adequacy",
    ),
    (
        "uk-regulatory/uk-gdpr-data-protection.yaml",
        "escalate: UK GDPR Art. 44–46: cross-border transfer action — confirm a",
    ),
]


@functools.cache
def _translate(path: Path):
    return translate(path.read_text(), bundle_files(path))


def test_corpus_is_present():
    assert len(FILES) == 45


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(CORPUS)))
def test_every_example_translates_without_error(path):
    out = _translate(path)
    assert out.errors == []
    assert out.items, "every file reports at least one item"
    for doc in out.documents:
        assert doc.mode == "observe"
        assert doc.default_effect == "allow"


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(CORPUS)))
def test_no_deny_comes_out_weaker(path):
    out = _translate(path)
    rules = {r.id: r for doc in out.documents for r in doc.rules}
    for item in out.items:
        if item.status == "untranslatable":
            assert item.reason and not item.rules
            continue
        if item.source_effect in DENY_LIKE:
            assert item.effect in ("block", "escalate"), item.source
            for rule_id in item.rules:
                assert EFFECT_RANK[rules[rule_id].effect] >= EFFECT_RANK["escalate"]


def test_untranslatable_rules_are_exactly_these():
    found = sorted(
        (str(path.relative_to(CORPUS)), item.source[:70])
        for path in FILES
        for item in _translate(path).untranslatable()
    )
    assert found == sorted(UNTRANSLATABLE)


def test_corpus_counts():
    totals = {"translated": 0, "translated_with_note": 0, "untranslatable": 0}
    for path in FILES:
        for key, count in _translate(path).counts().items():
            totals[key] += count
    assert totals == {"translated": 58, "translated_with_note": 175, "untranslatable": 111}


def test_translated_corpus_lints_clean():
    for path in FILES:
        findings = lint_documents(_translate(path).documents)
        assert not [f for f in findings if f.severity in ("critical", "high")], path


def test_every_manifest_in_the_corpus_matches_the_schema():
    import yaml

    for path in FILES:
        data = yaml.safe_load(path.read_text())
        if "agent_control_specification_version" in data:
            assert validate(data) == [], path


# ---------------------------------------------------------------------------
# Rule YAML
# ---------------------------------------------------------------------------


def _rules(body: str, default: str = "allow"):
    return translate(
        f"apiVersion: governance.toolkit/v1\nname: t\ndefault_action: {default}\nrules:\n{body}"
    )


def _item(out, name):
    return next(i for i in out.items if i.source == name)


def _decide(doc, **kwargs):
    doc = doc.model_copy(update={"mode": "enforce"})
    return NativePolicyEngine().evaluate(doc, PolicyInput(**kwargs)).effective_verdict


def test_field_to_field_is_reported_not_dropped():
    out = _rules(
        '  - name: owner-only\n    condition: "user.role == resource.owner"\n    action: deny\n'
    )
    item = _item(out, "owner-only")
    assert item.status == "untranslatable"
    assert "compares two fields" in item.reason
    assert "matches every call for a deny rule" in item.reason
    assert out.documents == []


def test_field_to_field_over_known_names_translates():
    out = _rules('  - name: self-call\n    condition: "tool_name == agent_id"\n    action: deny\n')
    item = _item(out, "self-call")
    assert item.status == "translated_with_note"
    doc = out.documents[0]
    assert _decide(doc, surface="tool_args", tool_key="bot", agent_slug="bot") == "block"
    assert _decide(doc, surface="tool_args", tool_key="search", agent_slug="bot") == "allow"


def test_default_allow_is_surfaced():
    out = _rules("  - name: no-rm\n    condition: \"tool_name == 'rm'\"\n    action: deny\n")
    payload = out.to_json()
    assert payload["unmatched_pass"] is True
    assert payload["default_action"][0]["source"] == "allow"
    assert "passes" in payload["default_action"][0]["note"]


def test_default_deny_blocks_unmatched_and_keeps_allow_exceptions():
    out = _rules(
        "  - name: reads\n"
        "    condition: \"tool_name startswith 'read_'\"\n"
        "    action: allow\n"
        "  - name: no-secrets\n"
        "    condition: \"tool_name == 'read_secrets'\"\n"
        "    action: deny\n",
        default="deny",
    )
    assert out.to_json()["unmatched_pass"] is False
    doc = out.documents[0]
    assert _decide(doc, surface="tool_args", tool_key="read_file") == "allow"
    assert _decide(doc, surface="tool_args", tool_key="write_file") == "block"
    # Their priority order would let an allow beat a deny; here the deny holds.
    assert _decide(doc, surface="tool_args", tool_key="read_secrets") == "block"
    assert _item(out, "reads").skippable is False


def test_allow_under_default_deny_that_tests_arguments_is_stricter_not_dropped():
    out = _rules(
        '  - name: small\n    condition: "amount < 10"\n    action: allow\n',
        default="deny",
    )
    assert _item(out, "small").status == "untranslatable"
    doc = out.documents[0]
    assert _decide(doc, surface="tool_args", tool_key="pay", arguments={"amount": 1}) == "block"


def test_regex_and_text_conditions_become_patterns():
    out = _rules(
        "  - name: injection\n"
        "    condition: \"message contains 'ignore previous'\"\n"
        "    action: deny\n"
        "    stage: pre_input\n"
    )
    item = _item(out, "injection")
    assert item.status == "translated_with_note"
    [pattern] = out.patterns
    assert pattern.pattern == "ignore\\ previous"
    assert pattern.surfaces == ["input"]
    rule = out.documents[0].rules[0]
    assert rule.when.detection.entity == pattern.entity


def test_rego_regex_on_action_becomes_globs_or_is_reported():
    from agentfox.platform.policy.compat.agent_governance import (
        Untranslatable,
        _regex_to_globs,
    )

    assert _regex_to_globs("^(read_|search_)") == ["read_*", "search_*"]
    assert _regex_to_globs("transfer_|payment_") == ["*transfer_*", "*payment_*"]
    assert _regex_to_globs("^exact$") == ["exact"]
    with pytest.raises(Untranslatable):
        _regex_to_globs("^[a-z]+_admin$")


def test_membership_fans_out_and_argument_comparison_translates():
    out = _rules(
        "  - name: big-pay\n"
        "    condition: \"amount > 1000 and tool_name in ['pay', 'wire']\"\n"
        "    action: require_approval\n"
        "    approvers: [cfo@example.com]\n"
    )
    item = _item(out, "big-pay")
    assert item.effect == "escalate"
    assert len(item.rules) == 2
    doc = out.documents[0]
    assert _decide(doc, surface="tool_args", tool_key="wire", arguments={"amount": 5000}) == (
        "escalate"
    )
    assert _decide(doc, surface="tool_args", tool_key="wire", arguments={"amount": 5}) == "allow"


def test_unrecognised_syntax_and_rate_limits_are_reported():
    out = _rules(
        '  - name: weird\n    condition: "not tool_name"\n    action: deny\n'
        "  - name: throttle\n    condition: \"tool_name == 'http'\"\n"
        "    action: rate_limit\n    limit: 3/minute\n"
    )
    assert _item(out, "weird").status == "untranslatable"
    assert "unrecognised" in _item(out, "weird").reason
    assert "rate limit" in _item(out, "throttle").reason


def test_warn_records_and_unknown_sections_are_reported():
    out = translate(
        "name: t\ndefault_action: allow\nrules:\n"
        "  - name: note\n    condition: \"tool_name == 'x'\"\n    action: warn\n"
        "max_tool_calls: 10\n"
    )
    assert _item(out, "note").effect == "allow"
    assert _item(out, "max_tool_calls").status == "untranslatable"


def test_bad_input_is_an_error_not_a_crash():
    assert translate("rules: [").errors
    assert translate("apiVersion: other/v9\nname: t\nrules: []").errors
    assert translate("- just\n- a list").errors


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

MANIFEST = """
agent_control_specification_version: 0.4.0-alpha.1
metadata: {name: demo}
policies:
  main: {type: rego, bundle: rego, query: data.demo.result}
intervention_points:
  input: {policy_target: $.input.body, policy: {id: main}}
  pre_tool_call: {policy_target: $.tool_call.args, policy: {id: main}}
"""
REGO = """
package demo
import rego.v1
blocked := {"wipe_disk", "drop_db"}
denials contains "No destructive tools" if {
    input.action in blocked
}
denials contains "No card numbers" if {
    regex.match(`(?i)card\\\\s*number`, input.output)
}
escalations contains msg if {
    input.params.amount > 1000
    msg := sprintf("Large amount %v", [input.params.amount])
}
denials contains "Wrong region" if {
    not input.params.region in {"eu"}
}
result := {"decision": "allow"} if { count(denials) == 0 }
"""


def test_manifest_with_bundle_translates():
    out = translate(MANIFEST, {"demo.rego": REGO})
    assert out.format == "manifest" and out.errors == []
    by_reason = {i.source.split(": ", 1)[1]: i for i in out.items}
    assert by_reason["No destructive tools"].effect == "block"
    assert len(by_reason["No destructive tools"].rules) == 2
    assert by_reason["No card numbers"].patterns
    assert by_reason["Large amount %v"].effect == "escalate"
    assert by_reason["Wrong region"].status == "untranslatable"
    assert "negated" in by_reason["Wrong region"].reason
    assert out.patterns[0].case_sensitive is False


def test_manifest_without_bundle_reports_the_policy():
    out = translate(MANIFEST)
    [item] = out.items
    assert item.status == "untranslatable" and "bundle" in item.reason


def test_manifest_schema_errors_are_reported_and_nothing_is_translated():
    out = translate(
        "agent_control_specification_version: 0.4.0-alpha.1\n"
        "policies:\n  p: {type: cedar}\n"
        "intervention_points:\n  nowhere: {policy: {id: p}}\n"
        "surprise: true\n"
    )
    assert out.documents == [] and out.errors
    messages = {e.path: e.message for e in out.schema_errors}
    assert "'surprise' is not an allowed field" in messages["/surprise"]
    assert "/intervention_points/nowhere" in messages
    assert "/policies/p" in messages


def test_schema_check_covers_approval_and_cedar_advice():
    assert validate({"on_timeout": "later"}, "approval.schema.json")
    assert validate({"timeout_seconds": 30, "on_timeout": "deny"}, "approval.schema.json") == []
    assert validate({"verdict": "transform"}, "cedar_advice.schema.json")
    assert validate({"verdict": "warn", "reason": "x"}, "cedar_advice.schema.json") == []
    assert validate(
        {"verdict": "warn", "transform": {"path": "$target", "value": 1}},
        "cedar_advice.schema.json",
    )


def test_cedar_policy_is_reported():
    out = translate(
        "agent_control_specification_version: 0.4.0-alpha.1\n"
        "policies:\n  c: {type: cedar, policy_set: 'forbid(principal, action, resource);'}\n"
        "intervention_points:\n  input: {policy: {id: c}}\n"
    )
    assert [i.status for i in out.items] == ["untranslatable"]
    assert "Cedar" in out.items[0].reason
