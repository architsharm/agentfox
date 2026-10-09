"""The industry and regional packs: rule tables translated from Rego policies.

The source policies ship OPA unit tests; `fixtures/translated_policy_tests.json` holds
their inputs and expected outcomes (converted once, see its `_notice`), and they run
here against the translated tables. The rest pins the wiring: every table rule has a
policy rule, the check raises the risks on the right surfaces, and a raised risk reaches
a verdict through the policy engine, in observe.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from agentfox.platform import checks as checks_registry
from agentfox.platform import packs
from agentfox.platform.checks import CheckContext
from agentfox.platform.packs.rule_table import TableRule, decision, match
from agentfox.platform.policy import PolicyDocument, PolicyInput
from agentfox.platform.policy.engine import NativePolicyEngine

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "translated_policy_tests.json").read_text()
)
PACK_IDS = [
    "industry/enterprise",
    "industry/financial",
    "industry/healthcare",
    "industry/minimal",
    "industry/strict",
    "regional/africa",
    "regional/india",
    "regional/uk",
]
OUTCOME_OF = {"block": "deny", "escalate": "escalate", "allow": "audit"}


def _module(pack_id: str):
    path = packs.builtin_pack(pack_id).root / "checks" / "rules.py"
    name = "translated_rules_" + pack_id.replace("/", "_").replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Importing registers the check; the registry is process-wide and other tests pin
    # exactly which checks it holds, so take it out again.
    checks_registry.unregister("pack." + pack_id.replace("/", "."))
    return module


MODULES = {pack_id: _module(pack_id) for pack_id in PACK_IDS}


def _policies(pack_id: str) -> dict[str, PolicyDocument]:
    pack = packs.builtin_pack(pack_id)
    docs = [PolicyDocument.from_yaml(p.read_text()) for p in pack.files("policies")]
    return {doc.key: doc for doc in docs}


def _full_table(pack_id: str, key: str) -> list[TableRule]:
    """The table plus the rules that are plain `tool:` conditions in the policy."""
    rules = list(MODULES[pack_id].TABLES[key])
    for rule in _policies(pack_id)[key].rules:
        if rule.when.tool:
            when = (("action_in", (rule.when.tool,)),)
            rules.append(TableRule(rule.id, OUTCOME_OF[rule.effect], rule.reason, when))
    return rules


def _ctx(surface: str, content: str = "", tool: str | None = None, arguments=None, evidence=None):
    return CheckContext(
        session=None,
        settings=None,
        agent=None,
        surface=surface,
        content=content,
        tool_key=tool,
        arguments=arguments,
        evidence=evidence,
    )


def _codes(pack_id: str, ctx: CheckContext) -> set[str]:
    module = MODULES[pack_id]
    check_fn = next(v for k, v in vars(module).items() if k.startswith("rules_"))
    return {risk["code"] for risk in (check_fn(ctx) or {}).get("risks", [])}


# ---------------------------------------------------------------------------
# the source policies' own tests
# ---------------------------------------------------------------------------


def test_the_converted_upstream_tests_are_all_here():
    assert len(FIXTURES["cases"]) >= 230
    assert "MIT License" in FIXTURES["_notice"]


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=[c["source"] for c in FIXTURES["cases"]])
def test_upstream_policy_test(case):
    given = case["input"]
    matched = match(
        _full_table(case["pack"], case["policy"]),
        action=str(given.get("action", "")),
        params=given.get("params") or {},
        text=given.get("output", ""),
        context=given.get("context") or {},
    )
    expect = case["expect"]
    if "decision" in expect:
        assert decision(matched) == expect["decision"], [r.code for r in matched]
    else:
        hits = [r.code for r in matched if r.outcome == expect["outcome"]]
        assert bool(hits) == expect["matches"], [r.code for r in matched]


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_every_table_rule_has_a_policy_rule_and_every_policy_starts_in_observe(pack_id):
    policies = _policies(pack_id)
    assert set(MODULES[pack_id].TABLES) == set(policies)
    for key, doc in policies.items():
        assert doc.mode == "observe" and doc.default_effect == "allow"
        risk_rules = {r.when.action_risk for r in doc.rules if r.when.action_risk}
        assert risk_rules == {rule.code for rule in MODULES[pack_id].TABLES[key]}
        for rule in doc.rules:
            assert rule.id.startswith(f"{key}.")
            assert bool(rule.when.action_risk) != bool(rule.when.tool)
    manifest = packs.builtin_pack(pack_id).manifest
    assert manifest.maturity == "incubating"


def test_no_translated_risk_is_critical():
    # Critical action risks are hard-blocked whatever the mode; these packs start in observe.
    for module in MODULES.values():
        for rule in module.RULES:
            assert rule.outcome in ("deny", "escalate", "audit")


def test_a_raised_risk_reaches_a_verdict_in_observe():
    ctx = _ctx("output", "Your Aadhaar number is 234567890123.")
    codes = _codes("regional/india", ctx)
    assert "india-aadhaar.unmasked-12-digit-aadhaar-output" in codes
    doc = _policies("regional/india")["india-aadhaar"]
    event = PolicyInput(
        surface="output",
        action={"risks": [{"code": c, "severity": "high"} for c in codes]},
    )
    result = NativePolicyEngine().evaluate(doc, event)
    assert result.effective_verdict == "block"
    assert result.verdict == "allow"  # observe: recorded, not applied


def test_text_rules_run_on_messages_and_tool_rules_on_tool_calls():
    breach = "Let's not report it — hide the breach for now."
    assert "uk-gdpr.block-breach-suppression" in _codes("regional/uk", _ctx("output", breach))
    # the same words as a tool argument are not message text in the source policies
    args = {"note": breach}
    assert not any(
        c == "uk-gdpr.block-breach-suppression"
        for c in _codes("regional/uk", _ctx("tool_args", "", "x", args))
    )
    transfer = _ctx("tool_args", "", "export_data", {"destination_country": "JP"})
    assert "uk-gdpr.block-transfer-without-adequacy-platform-set" in _codes("regional/uk", transfer)
    adequate = _ctx("tool_args", "", "export_data", {"destination_country": "FR"})
    assert "uk-gdpr.block-transfer-without-adequacy-platform-set" not in _codes(
        "regional/uk", adequate
    )
    assert _codes("regional/uk", _ctx("retrieved", breach)) == set()


def test_context_comes_from_the_callers_evidence():
    call = _ctx(
        "tool_args", "", "pos_payment", {}, evidence={"context": {"location_verified": True}}
    )
    unverified = _ctx("tool_args", "", "pos_payment", {})
    rule = [r.code for r in MODULES["regional/africa"].TABLES["nigeria-pos-geofencing"]][0]
    assert rule in _codes("regional/africa", unverified)
    assert rule not in _codes("regional/africa", call)


# ---------------------------------------------------------------------------
# packs whose sources ship no tests: examples from each rule's own pattern
# ---------------------------------------------------------------------------

POSITIVE = [
    (
        "industry/enterprise",
        _ctx("output", "SSN on file: 123-45-6789"),
        "industry-enterprise.ssn-pattern-detected-output",
    ),
    (
        "industry/enterprise",
        _ctx("tool_args", "", "crm.note", {"text": "ssn 123-45-6789"}),
        "industry-enterprise.ssn-pattern-detected-output",
    ),
    (
        "industry/financial",
        _ctx("output", "card 4111 1111 1111 1111"),
        "industry-financial.credit-card-number-detected",
    ),
    (
        "industry/financial",
        _ctx("tool_args", "", "payment_refund", {}),
        "industry-financial.financial-transactions-require-compliance-approval",
    ),
    (
        "industry/healthcare",
        _ctx("output", "Patient MRN: 00123456"),
        "industry-healthcare.medical-record-number-detected",
    ),
    (
        "industry/healthcare",
        _ctx("tool_args", "", "delete_chart", {}),
        "industry-healthcare.deletion-prohibited-healthcare",
    ),
    (
        "industry/strict",
        _ctx("input", "my api_key=sk_live_abcdefgh123"),
        "industry-strict.credential-pattern-detected-output",
    ),
    (
        "regional/india",
        _ctx("output", "Directions say we should not; suppress the incident instead"),
        "india-cert-in.6-hour-reporting-cannot-suppress-delay",
    ),
    (
        "regional/india",
        _ctx("tool_args", "", "rotate_logs", {"log_retention_days": 90}),
        "india-cert-in.180-day-india-log-retention",
    ),
    (
        "regional/india",
        _ctx("tool_args", "", "store_pii", {"encrypted": True}),
        "india-dpdp.consent-required-before-processing-personal-data",
    ),
    (
        "regional/india",
        _ctx("tool_args", "", "save", {"data_class": "card_data", "storage_region": "US"}),
        "india-rbi.payment-system-data-stored-only-india",
    ),
    (
        "regional/india",
        _ctx("tool_args", "", "execute_trade", {}),
        "india-sebi.re-solely-responsible-ai-ml-output",
    ),
]

NEGATIVE = [
    (
        "industry/enterprise",
        _ctx("output", "Order 123-456 shipped."),
        "industry-enterprise.ssn-pattern-detected-output",
    ),
    (
        "industry/healthcare",
        _ctx("output", "MRN pending"),
        "industry-healthcare.medical-record-number-detected",
    ),
    (
        "regional/india",
        _ctx("tool_args", "", "rotate_logs", {"log_retention_days": 365}),
        "india-cert-in.180-day-india-log-retention",
    ),
    (
        "regional/india",
        _ctx("tool_args", "", "store_pii", {"consent_logged": True, "encrypted": True}),
        "india-dpdp.consent-required-before-processing-personal-data",
    ),
    (
        "regional/india",
        _ctx("tool_args", "", "save", {"data_class": "card_data", "storage_region": "IN"}),
        "india-rbi.payment-system-data-stored-only-india",
    ),
    (
        "regional/india",
        _ctx("output", "Aadhaar ending 9012 verified."),
        "india-aadhaar.unmasked-12-digit-aadhaar-output",
    ),
]


@pytest.mark.parametrize(("pack_id", "ctx", "code"), POSITIVE, ids=[p[2] for p in POSITIVE])
def test_rule_catches_its_example(pack_id, ctx, code):
    assert code in _codes(pack_id, ctx)


@pytest.mark.parametrize(("pack_id", "ctx", "code"), NEGATIVE, ids=[n[2] for n in NEGATIVE])
def test_rule_passes_the_near_miss(pack_id, ctx, code):
    assert code not in _codes(pack_id, ctx)


def test_single_tool_rules_are_plain_policy_conditions():
    doc = _policies("industry/enterprise")["industry-enterprise"]
    event = PolicyInput(surface="tool_args", tool_key="ssh_connect")
    result = NativePolicyEngine().evaluate(doc, event)
    assert [r.rule_id for r in result.rules_fired] == ["industry-enterprise.ssh-not-permitted"]
    assert result.effective_verdict == "block"
