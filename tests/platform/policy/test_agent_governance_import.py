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
        "agt_policies_agent.human_approval.escalate: Human approval required: '",
    ),
    (
        "african-regulatory/agent-human-approval.yaml",
        "agt_policies_agent.human_approval.escalate: Human approval required: a",
    ),
    (
        "african-regulatory/agent-human-approval.yaml",
        "agt_policies_agent.human_approval.escalate: Human approval required: b",
    ),
    (
        "african-regulatory/agent-human-approval.yaml",
        "agt_policies_agent.human_approval.escalate: Human approval required: t",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "agt_policies_agent.model_routing.audit: Model routing audit: sensitive",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "agt_policies_agent.model_routing.deny: Model routing denied: model '%v",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "agt_policies_agent.model_routing.deny: Model routing denied: model '%v",
    ),
    (
        "african-regulatory/agent-model-routing.yaml",
        "agt_policies_agent.model_routing.escalate: Model routing: sensitive ta",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "agt_policies_agent.pii_leakage.audit: PII audit: action may produce pe",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "agt_policies_agent.pii_leakage.deny: PII leakage: BVN/NIN-format ident",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "agt_policies_agent.pii_leakage.deny: PII leakage: South African ID num",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "agt_policies_agent.pii_leakage.deny: PII leakage: credit/debit card nu",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "agt_policies_agent.pii_leakage.deny: PII leakage: custom high-sensitiv",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "agt_policies_agent.pii_leakage.escalate: PII leakage: email address de",
    ),
    (
        "african-regulatory/agent-pii-leakage.yaml",
        "agt_policies_agent.pii_leakage.escalate: PII leakage: phone number det",
    ),
    (
        "african-regulatory/agent-prompt-injection.yaml",
        "agt_policies_agent.prompt_injection.deny: Prompt injection detected: i",
    ),
    (
        "african-regulatory/agent-prompt-injection.yaml",
        "agt_policies_agent.prompt_injection.escalate: Potential prompt injecti",
    ),
    (
        "african-regulatory/agent-tool-permissions.yaml",
        "agt_policies_agent.tool_permissions.deny: Tool permission denied: '%v'",
    ),
    (
        "african-regulatory/agent-tool-permissions.yaml",
        "agt_policies_agent.tool_permissions.deny: Tool permission denied: '%v'",
    ),
    (
        "african-regulatory/agent-tool-permissions.yaml",
        "agt_policies_agent.tool_permissions.escalate: Tool requires human appr",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "agt_policies_nigeria.bvn_nin.audit: NIMC Act 2026: Action '%v' is a ma",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "agt_policies_nigeria.bvn_nin.escalate: BVN/NIN Gate: Action '%v' invol",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "agt_policies_nigeria.bvn_nin.escalate: NIMC Act 2026: BVN lookup attem",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "agt_policies_nigeria.bvn_nin.escalate: NIMC Act 2026: NIN lookup attem",
    ),
    (
        "african-regulatory/bvn-nin-protection.yaml",
        "agt_policies_nigeria.bvn_nin.escalate: NIMC Act 2026: Purpose mismatch",
    ),
    (
        "african-regulatory/cbn-transaction-limits.yaml",
        "agt_policies_nigeria.cbn.escalate: CBN Tier 1: Transfer of ₦%v exceeds",
    ),
    (
        "african-regulatory/cbn-transaction-limits.yaml",
        "agt_policies_nigeria.cbn.escalate: CBN Tier 2: Transfer of ₦%v exceeds",
    ),
    (
        "african-regulatory/cbn-transaction-limits.yaml",
        "agt_policies_nigeria.cbn.escalate: CBN Tier 3: Transfer of ₦%v is at o",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "agt_policies_africa.egypt_pdpl.deny: Egypt PDPL No. 151/2020 Art. 14: ",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "agt_policies_africa.egypt_pdpl.deny: Egypt PDPL No. 151/2020 Arts. 14-",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "agt_policies_africa.egypt_pdpl.escalate: Egypt PDPL No. 151/2020 Art. ",
    ),
    (
        "african-regulatory/egypt-pdpl.yaml",
        "agt_policies_africa.egypt_pdpl.escalate: Egypt PDPL No. 151/2020 Art. ",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "agt_policies_africa.ethiopia_pdp.deny: Ethiopia PDPP 1321/2024 Art. 18",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "agt_policies_africa.ethiopia_pdp.deny: Ethiopia PDPP 1321/2024 Art. 20",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "agt_policies_africa.ethiopia_pdp.escalate: Ethiopia PDPP 1321/2024 Art",
    ),
    (
        "african-regulatory/ethiopia-pdp.yaml",
        "agt_policies_africa.ethiopia_pdp.escalate: Ethiopia PDPP 1321/2024 Art",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "agt_policies_africa.ghana_dpa.deny: Ghana DPA Act 843 s.18(2): Cross-b",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "agt_policies_africa.ghana_dpa.deny: Ghana DPA Act 843 s.18(2): Transfe",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "agt_policies_africa.ghana_dpa.escalate: Ghana DPA Act 843 s.17: Export",
    ),
    (
        "african-regulatory/ghana-dpa.yaml",
        "agt_policies_africa.ghana_dpa.escalate: Ghana DPA Act 843 s.18(2): Cro",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "agt_policies_africa.kdpa.deny: Kenya DPA s.49: Cross-border transfer t",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "agt_policies_africa.kdpa.deny: Kenya DPA s.49: Transfer to country '%v",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "agt_policies_africa.kdpa.escalate: Kenya DPA s.30: Export of %v record",
    ),
    (
        "african-regulatory/kenya-dpa.yaml",
        "agt_policies_africa.kdpa.escalate: Kenya DPA s.49: Cross-border transf",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "agt_policies_africa.mauritius_dpa.deny: Mauritius DPA 2017 (Transfer):",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "agt_policies_africa.mauritius_dpa.deny: Mauritius DPA 2017 (Transfer):",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "agt_policies_africa.mauritius_dpa.escalate: Mauritius DPA 2017 (Transf",
    ),
    (
        "african-regulatory/mauritius-dpa.yaml",
        "agt_policies_africa.mauritius_dpa.escalate: Mauritius DPA 2017 (Transf",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "agt_policies_nigeria.ndpa.deny: NDPA s.25: Cross-border transfer to '%",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "agt_policies_nigeria.ndpa.deny: NDPA s.25: Transfer to country '%v' bl",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "agt_policies_nigeria.ndpa.escalate: NDPA s.24: Export of %v records re",
    ),
    (
        "african-regulatory/ndpa-data-residency.yaml",
        "agt_policies_nigeria.ndpa.escalate: NDPA s.25: Cross-border transfer a",
    ),
    (
        "african-regulatory/nfiu-aml-str.yaml",
        "agt_policies_nigeria.nfiu.audit: NFIU Structuring Alert: ₦%v is just u",
    ),
    (
        "african-regulatory/nfiu-aml-str.yaml",
        "agt_policies_nigeria.nfiu.escalate: NFIU CTR (MLPPA s.10): Transfer of",
    ),
    (
        "african-regulatory/popia-south-africa.yaml",
        "agt_policies_africa.popia.deny: POPIA s.72: Transfer to '%v' blocked —",
    ),
    (
        "african-regulatory/pos-geofencing.yaml",
        "agt_policies_nigeria.pos_geofencing.audit: CBN POS Audit: terminal act",
    ),
    (
        "african-regulatory/pos-geofencing.yaml",
        "agt_policies_nigeria.pos_geofencing.deny: CBN POS Geo-Fencing: locatio",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "agt_policies_africa.rwanda_dpa.deny: Rwanda Law 058/2021 Art. 48/49: T",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "agt_policies_africa.rwanda_dpa.deny: Rwanda Law 058/2021 Art. 48: Cros",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "agt_policies_africa.rwanda_dpa.escalate: Rwanda Law 058/2021 Art. 48: ",
    ),
    (
        "african-regulatory/rwanda-dpa.yaml",
        "agt_policies_africa.rwanda_dpa.escalate: Rwanda Law 058/2021 Art. 50: ",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "agt_policies_africa.tanzania_pdpa.deny: Tanzania PDPA s.13: Cross-bord",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "agt_policies_africa.tanzania_pdpa.deny: Tanzania PDPA s.13: Transfer t",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "agt_policies_africa.tanzania_pdpa.escalate: Tanzania PDPA s.13: Cross-",
    ),
    (
        "african-regulatory/tanzania-pdpa.yaml",
        "agt_policies_africa.tanzania_pdpa.escalate: Tanzania PDPA s.30: Export",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "agt_policies_africa.uganda_dppa.deny: Uganda DPPA s.19: Cross-border t",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "agt_policies_africa.uganda_dppa.deny: Uganda DPPA s.19: Transfer to co",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "agt_policies_africa.uganda_dppa.escalate: Uganda DPPA s.19: Cross-bord",
    ),
    (
        "african-regulatory/uganda-dppa.yaml",
        "agt_policies_africa.uganda_dppa.escalate: Uganda DPPA s.4(e): Export o",
    ),
    ("atr-community-rules.yaml", "categories"),
    ("atr-community-rules.yaml", "suspicious_decoded_keywords"),
    ("conversation-guardian.yaml", "escalation_patterns"),
    ("conversation-guardian.yaml", "offensive_patterns"),
    ("conversation-guardian.yaml", "thresholds"),
    (
        "india-regulatory/aadhaar-pii-protection.yaml",
        "agt_policies_india.aadhaar.deny: Aadhaar Act s.29(4): no Aadhaar numbe",
    ),
    (
        "india-regulatory/certin-2022-directions.yaml",
        "agt_policies_india.certin.deny: CERT-In 2022 Directions (iv): logs mus",
    ),
    (
        "india-regulatory/certin-2022-directions.yaml",
        "agt_policies_india.certin.escalate: CERT-In 2022 Directions (i): synch",
    ),
    (
        "india-regulatory/dpdp-data-protection.yaml",
        "agt_policies_india.dpdp.deny: DPDP s.6: processing personal data requi",
    ),
    (
        "india-regulatory/dpdp-data-protection.yaml",
        "agt_policies_india.dpdp.deny: DPDP s.8(5): personal data must be proce",
    ),
    (
        "india-regulatory/rbi-data-localization.yaml",
        "agt_policies_india.rbi.deny: RBI 2018 (Storage of Payment System Data)",
    ),
    (
        "india-regulatory/rbi-data-localization.yaml",
        "agt_policies_india.rbi.deny: RBI 2018: payment data processed abroad m",
    ),
    (
        "india-regulatory/rbi-data-localization.yaml",
        "agt_policies_india.rbi.deny: RBI Master Direction KYC 2016: customer d",
    ),
    (
        "india-regulatory/sebi-governance.yaml",
        "agt_policies_india.sebi.deny: SEBI Amendment 10 Feb 2025: regulated en",
    ),
    (
        "india-regulatory/sebi-governance.yaml",
        "agt_policies_india.sebi.deny: SEBI CSCRF 2024: audit logs must be reta",
    ),
    (
        "india-regulatory/sebi-governance.yaml",
        "agt_policies_india.sebi.escalate: SEBI CSCRF 2024: periodic VAPT and c",
    ),
    (
        "lotl_prevention_policy.yaml",
        "agt.examples.lotl.denials: Potential remote code execution through a p",
    ),
    (
        "lotl_prevention_policy.yaml",
        "agt.examples.lotl.denials: Unauthorized access to sensitive system dat",
    ),
    ("mcp-security.yaml", "detection_patterns"),
    ("mcp-security.yaml", "suspicious_decoded_keywords"),
    ("pii-detection.yaml", "builtin_patterns"),
    (
        "production/enterprise.yaml",
        "agt.examples.production.enterprise.denials: Tool call budget exceeded ",
    ),
    (
        "production/financial.yaml",
        "agt.examples.production.financial.denials: Tool call budget exceeded (",
    ),
    (
        "production/healthcare.yaml",
        "agt.examples.production.healthcare.denials: Tool call budget exceeded ",
    ),
    (
        "production/minimal.yaml",
        "agt.examples.production.minimal.denials: Tool call budget exceeded (10",
    ),
    (
        "production/strict.yaml",
        "agt.examples.production.strict.denials: Tool call budget exceeded (10)",
    ),
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
        "agt_policies_uk.fca_conduct.deny: FCA market conduct: autonomous agent",
    ),
    (
        "uk-regulatory/fca-financial-conduct.yaml",
        "agt_policies_uk.fca_conduct.escalate: FCA Consumer Duty: AI-influenced",
    ),
    (
        "uk-regulatory/ico-automated-decisions.yaml",
        "agt_policies_uk.ico_adm.escalate: UK GDPR Art. 22A: solely automated s",
    ),
    (
        "uk-regulatory/ico-automated-decisions.yaml",
        "agt_policies_uk.ico_adm.escalate: UK GDPR Art. 22C(1): decision-specif",
    ),
    (
        "uk-regulatory/uk-gdpr-data-protection.yaml",
        "agt_policies_uk.uk_gdpr.deny: UK GDPR Art. 44–46: transfer to '%v' blo",
    ),
    (
        "uk-regulatory/uk-gdpr-data-protection.yaml",
        "agt_policies_uk.uk_gdpr.escalate: UK GDPR Art. 44–46: cross-border tra",
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
