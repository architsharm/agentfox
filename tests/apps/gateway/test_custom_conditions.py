"""Value conditions end to end: authored over HTTP, evaluated on tool calls, tool
results and replies, decided by the managed `custom` pack as `custom.<key>`."""

from __future__ import annotations

from tests.apps.gateway.test_custom_rules import ADMIN, _enforce_custom, _guard


def _grant(client, *tools, slug="ops-bot"):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        session.add(Agent(slug=slug, registered=True, status="active"))
    for tool in tools:
        r = client.post(f"/api/agents/{slug}/access", json={"tool_key": tool}, headers=ADMIN)
        assert r.status_code == 201, r.text


def _tool_call(client, tool, args, agent="ops-bot"):
    return client.post(
        "/v1/guard/tool_call",
        json={
            "agent": agent,
            "tool": tool,
            "arguments": args,
            "provenance": {k: "user" for k in args},
            "intent": "help a customer",
        },
    ).json()


def _fired(result):
    return {f["rule_id"] for f in result["rules_fired"]}


def _mode(result, rule_id):
    return next(f.get("mode") for f in result["rules_fired"] if f["rule_id"] == rule_id)


def test_a_condition_on_a_tool_argument_asks_a_person_once_enforcing(client):
    _grant(client, "payments.refund", "crm.update")
    r = client.post(
        "/api/custom-rules",
        json={
            "key": "big-refunds",
            "name": "Big refunds",
            "kind": "condition",
            "condition": {
                "surface": "tool_args",
                "tool": "payments.*",
                "field": "amount",
                "operator": "gt",
                "value": 500,
            },
            "effect": "escalate",
        },
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    assert r.json()["rule"]["condition"]["operator"] == "gt"
    assert r.json()["rule"]["surfaces"] == ["tool_args"]

    # Observe: recorded as what would have happened, nothing held.
    watched = _tool_call(client, "payments.refund", {"order": "o1", "amount": 750})
    assert "custom.big-refunds" in _fired(watched)
    assert _mode(watched, "custom.big-refunds") == "observe"
    assert watched["verdict"] == "allow" and watched["effective_verdict"] == "escalate"
    small = _tool_call(client, "payments.refund", {"order": "o1", "amount": 50})
    assert "custom.big-refunds" not in _fired(small)
    other = _tool_call(client, "crm.update", {"amount": 750})
    assert "custom.big-refunds" not in _fired(other)

    _enforce_custom(client)
    held = _tool_call(client, "payments.refund", {"order": "o1", "amount": 750})
    assert held["verdict"] == "escalate"
    assert "custom.big-refunds" in _fired(held)
    assert held.get("approval_id")


def test_only_allowed_values_blocks_anything_else(client):
    _grant(client, "shipping.create")
    client.post(
        "/api/custom-rules",
        json={
            "key": "regions",
            "name": "Ship only to US or EU",
            "kind": "condition",
            "condition": {"field": "region", "operator": "not_in", "value": ["us", "eu"]},
        },
        headers=ADMIN,
    )
    _enforce_custom(client)
    blocked = _tool_call(client, "shipping.create", {"region": "apac"})
    assert blocked["verdict"] == "block" and "custom.regions" in _fired(blocked)
    allowed = _tool_call(client, "shipping.create", {"region": "EU"})
    assert "custom.regions" not in _fired(allowed) and allowed["verdict"] == "allow"


def test_a_condition_on_a_tool_result_and_on_a_reply(client):
    client.post(
        "/api/custom-rules",
        json={
            "key": "balance-leak",
            "name": "Large balances",
            "kind": "condition",
            "condition": {
                "surface": "tool_result",
                "tool": "accounts.get",
                "field": "balance",
                "operator": "gte",
                "value": 10000,
            },
        },
        headers=ADMIN,
    )
    client.post(
        "/api/custom-rules",
        json={
            "key": "quoted-amounts",
            "name": "Amounts over 1000 in replies",
            "kind": "condition",
            "condition": {
                "surface": "output",
                "measure": "number",
                "operator": "gt",
                "value": 1000,
            },
            "effect": "redact",
        },
        headers=ADMIN,
    )
    _enforce_custom(client)

    def result(tool):
        return client.post(
            "/v1/guard/input",
            json={
                "agent": "ops-bot",
                "surface": "tool_result",
                "tool": tool,
                "content": '{"id": "a1", "balance": 25000}',
            },
        ).json()

    held = result("accounts.get")
    assert "custom.balance-leak" in _fired(held) and held["verdict"] == "block"
    assert "custom.balance-leak" not in _fired(result("crm.get"))

    out = _guard(client, "Your refund of 2500 is on its way.", surface="output")
    assert "custom.quoted-amounts" in _fired(out)
    assert "2500" not in out["content"] and "on its way" in out["content"]
    assert "custom.quoted-amounts" not in _fired(_guard(client, "Refund of 20 sent.", "output"))


def test_bad_conditions_are_422_with_plain_messages(client):
    def post(condition):
        return client.post(
            "/api/custom-rules",
            json={"key": "bad", "name": "Bad", "kind": "condition", "condition": condition},
            headers=ADMIN,
        )

    r = post({"field": "amount", "operator": "bigger", "value": 1})
    assert r.status_code == 422 and "unknown operator" in r.text
    r = post({"field": "amount", "operator": "gt", "value": "lots"})
    assert r.status_code == 422 and "needs a number" in r.text
    r = post({"field": "to", "operator": "matches", "value": "(a+)+$"})
    assert r.status_code == 422
    r = post({"field": "to", "operator": "matches", "value": "x" * 400})
    assert r.status_code == 422 and "longer than" in r.text
    assert client.get("/api/custom-rules", headers=ADMIN).json()["rules"] == []


def test_try_a_condition_shows_what_it_read(client):
    rule = {
        "name": "x",
        "kind": "condition",
        "condition": {"tool": "payments.refund", "field": "amount", "operator": "gt", "value": 500},
    }
    hit = client.post(
        "/api/custom-rules/try",
        json={"rule": rule, "text": '{"amount": 750}', "tool": "payments.refund"},
        headers=ADMIN,
    ).json()
    assert hit["matched"] is True and hit["observed"] == [750]
    miss = client.post(
        "/api/custom-rules/try", json={"rule": rule, "text": '{"amount": 450}'}, headers=ADMIN
    ).json()
    assert miss["matched"] is False and miss["observed"] == [450]


def test_field_suggestions_come_from_the_tools_calls(client):
    _tool_call(client, "payments.refund", {"order": "o1", "amount": 5})
    r = client.get("/api/custom-rules/fields", params={"tool": "payments.refund"}, headers=ADMIN)
    assert r.status_code == 200
    assert {"order", "amount"} <= set(r.json()["fields"])


def test_editing_a_condition_keeps_its_rule_id(client):
    body = {
        "key": "cap",
        "name": "Cap",
        "kind": "condition",
        "condition": {"field": "amount", "operator": "gt", "value": 500},
    }
    client.post("/api/custom-rules", json=body, headers=ADMIN)
    body["condition"]["value"] = 900
    r = client.post("/api/custom-rules", json=body, headers=ADMIN)
    assert r.json()["rule"]["rule_id"] == "custom.cap"
    assert r.json()["rule"]["condition"]["value"] == 900
    [rule] = client.get("/api/custom-rules", headers=ADMIN).json()["rules"]
    assert rule["kind"] == "condition" and rule["condition"]["value"] == 900
