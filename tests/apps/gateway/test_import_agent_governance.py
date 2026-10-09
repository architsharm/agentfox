"""Importing an agent-governance policy over the API: plan saves nothing, apply observes."""

from __future__ import annotations

from agentfox.core.models import CustomRule, Policy
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
RULES = """
apiVersion: governance.toolkit/v1
name: support-bot
default_action: allow
rules:
  - name: no-refunds
    condition: "tool_name == 'issue_refund'"
    action: deny
  - name: injection
    condition: "message contains 'ignore previous'"
    action: deny
    stage: pre_input
  - name: owner-only
    condition: "user.id == resource.owner"
    action: deny
"""
MANIFEST = """
agent_control_specification_version: 0.4.0-alpha.1
metadata: {name: payments}
policies:
  main: {type: rego, bundle: rego, query: data.payments.result}
intervention_points:
  pre_tool_call: {policy_target: $.tool_call.args, policy: {id: main}}
"""
REGO = """package payments
import rego.v1
denials contains "No wires" if {
    input.action == "wire_transfer"
}
allows contains "reads" if {
    regex.match(`^read_`, input.action)
}
result := {"decision": "deny", "reason": "Default deny"} if {
    count(denials) == 0
    count(allows) == 0
}
"""
URL = "/api/import/agent-governance"


def test_plan_reports_every_rule_and_saves_nothing(client, session):
    r = client.post(f"{URL}/plan", json={"source": RULES}, headers=ADMIN)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["format"] == "rules"
    assert plan["summary"] == {"translated": 1, "translated_with_note": 1, "untranslatable": 1}
    assert plan["unmatched_pass"] is True
    assert plan["lint"]["passed"] is True
    owner = next(i for i in plan["items"] if i["source"] == "owner-only")
    assert "compares two fields" in owner["reason"]
    assert session.query(Policy).filter_by(key="imported-support-bot").count() == 0
    assert session.query(CustomRule).count() == 0


def test_apply_saves_in_observe_with_patterns(client, session):
    r = client.post(URL, json={"source": RULES}, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    [saved] = body["policies"]
    assert saved["key"] == "imported-support-bot"
    assert saved["mode"] == "observe"
    assert len(body["patterns"]) == 1
    assert [i["source"] for i in body["untranslatable"]] == ["owner-only"]
    policy = client.get("/api/policies/imported-support-bot", headers=ADMIN).json()
    rule_ids = {rule["id"] for rule in policy["live_compiled"]["rules"]}
    assert rule_ids == {"no-refunds", "injection"}
    assert session.query(CustomRule).filter_by(key=body["patterns"][0]).count() == 1


def test_unticked_rules_are_left_out(client):
    plan = client.post(f"{URL}/plan", json={"source": RULES}, headers=ADMIN).json()
    skip = [i for i, item in enumerate(plan["items"]) if item["source"] == "injection"]
    body = client.post(URL, json={"source": RULES, "skip": skip}, headers=ADMIN).json()
    assert body["patterns"] == []
    assert [i["source"] for i in body["left_out"]] == ["injection"]
    policy = client.get("/api/policies/imported-support-bot", headers=ADMIN).json()
    assert [rule["id"] for rule in policy["live_compiled"]["rules"]] == ["no-refunds"]


def test_manifest_with_bundle(client):
    r = client.post(
        f"{URL}/plan", json={"source": MANIFEST, "files": {"main.rego": REGO}}, headers=ADMIN
    )
    plan = r.json()
    assert plan["format"] == "manifest" and plan["errors"] == []
    assert plan["unmatched_pass"] is False
    body = client.post(
        URL, json={"source": MANIFEST, "files": {"main.rego": REGO}}, headers=ADMIN
    ).json()
    rules = client.get("/api/policies/imported-payments", headers=ADMIN).json()
    ids = {rule["id"] for rule in rules["live_compiled"]["rules"]}
    assert "default-deny" in ids and body["policies"][0]["mode"] == "observe"


def test_manifest_schema_errors_come_back_in_the_plan(client):
    bad = "agent_control_specification_version: 0.4.0-alpha.1\nsurprise: 1\n"
    plan = client.post(f"{URL}/plan", json={"source": bad}, headers=ADMIN).json()
    assert plan["schema_errors"]
    assert client.post(URL, json={"source": bad}, headers=ADMIN).status_code == 400


def test_nothing_translatable_is_refused(client):
    source = "name: t\ndefault_action: allow\nrules:\n  - name: x\n    condition: 'a == b'\n"
    assert client.post(URL, json={"source": source}, headers=ADMIN).status_code == 400


def test_reimport_keeps_an_enforcing_policy_enforcing(client, session):
    from agentfox.platform.policy import set_mode

    client.post(URL, json={"source": RULES}, headers=ADMIN)
    set_mode(session, "imported-support-bot", "enforce")
    session.commit()
    changed = RULES.replace("issue_refund", "issue_credit")
    saved = client.post(URL, json={"source": changed}, headers=ADMIN).json()["policies"][0]
    assert saved["mode"] == "enforce"
    assert saved["version"] == 2 and saved["live_version"] == 1


def test_unknown_user_cannot_import(client):
    stranger = as_user("stranger@example.com")
    r = client.post(f"{URL}/plan", json={"source": RULES}, headers=stranger)
    assert r.status_code in (401, 403)
