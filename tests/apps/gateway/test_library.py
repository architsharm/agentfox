"""The policy library over HTTP: packs, compiling written policy, business rules."""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def test_packs_list_shipped_packs_with_install_state(client):
    packs = client.get("/api/library/packs", headers=ADMIN).json()["packs"]
    ids = {p["id"] for p in packs}
    assert "coding-agent" in ids
    baseline = next(p for p in packs if any(x["key"] == "baseline" for x in p["policies"]))
    assert baseline["policies"][0]["rules"] > 0


def test_installing_a_pack_saves_its_policies_watching(client):
    r = client.post("/api/library/packs/coding-agent/install", headers=ADMIN)
    assert r.status_code == 200, r.text
    added = r.json()["added"]
    pack = next(
        p
        for p in client.get("/api/library/packs", headers=ADMIN).json()["packs"]
        if p["id"] == "coding-agent"
    )
    assert pack["installed"] is True
    for policy in pack["policies"]:
        if policy["key"] in added:
            assert policy["mode"] == "observe"
    # Installing again adds nothing.
    assert (
        client.post("/api/library/packs/coding-agent/install", headers=ADMIN).json()["added"] == []
    )


LADDER_TEXT = (
    "Refunds up to $100 can be issued automatically. "
    "Refunds between $100 and $1000 require approval from a finance manager."
)


def test_compile_returns_rules_and_saves_nothing(client):
    out = client.post("/api/business/compile", json={"text": LADDER_TEXT}, headers=ADMIN).json()
    assert out["rules"], out
    assert client.get("/api/business/rules", headers=ADMIN).json()["rules"] == []


def test_compile_asks_instead_of_guessing(client):
    out = client.post(
        "/api/business/compile", json={"text": "Refunds over $500 need a manager."}, headers=ADMIN
    ).json()
    assert out["review"] and out["review"][0]["question"]


def test_a_compiled_ladder_saves_watching_and_can_be_enforced(client):
    compiled = client.post(
        "/api/business/compile", json={"text": LADDER_TEXT}, headers=ADMIN
    ).json()
    ladder = next(r for r in compiled["rules"] if r["kind"] == "threshold_ladder")
    saved = client.post(
        "/api/business/rules", json={"definition": ladder["definition"]}, headers=ADMIN
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["mode"] == "observe"
    key = saved.json()["key"]
    enforced = client.post(
        f"/api/business/rules/{key}/mode", json={"mode": "enforce"}, headers=ADMIN
    )
    assert enforced.json()["mode"] == "enforce"


def test_unknown_pack_is_404(client):
    assert client.post("/api/library/packs/nope/install", headers=ADMIN).status_code == 404


def test_a_limit_on_an_argument_the_tool_never_takes_is_flagged(client):
    client.post(
        "/v1/guard/tool_call",
        json={
            "agent": "support-triage",
            "tool": "airline.issue_compensation",
            "arguments": {"reason": "delay"},
            "provenance": {},
        },
    )
    out = client.post(
        "/api/business/compile",
        json={"text": "airline.issue_compensation above $200 requires approval from a supervisor."},
        headers=as_user("admin@example.com"),
    ).json()
    [rule] = out["rules"]
    assert any("takes no `amount`" in w for w in rule.get("warnings", []))


def _ladder(key="refund-cap", upto=100.0):
    return {
        "key": key,
        "name": "Refund cap",
        "tool": "payments.refund",
        "field": "arguments.amount",
        "unit": "USD",
        "bands": [
            {"upto": upto, "outcome": "allow"},
            {"outcome": "escalate", "approver_role": "manager"},
        ],
    }


def test_a_business_rule_can_be_edited_in_place_and_deleted(client):
    assert (
        client.post(
            "/api/business/rules", json={"definition": _ladder()}, headers=ADMIN
        ).status_code
        == 201
    )
    edited = client.put(
        "/api/business/rules/refund-cap", json={"definition": _ladder(upto=250.0)}, headers=ADMIN
    )
    assert edited.status_code == 200, edited.text
    rule = client.get("/api/business/rules/refund-cap", headers=ADMIN).json()
    assert rule["definition"]["bands"][0]["upto"] == 250.0 and rule["mode"] == "observe"
    assert client.delete("/api/business/rules/refund-cap", headers=ADMIN).status_code == 200
    assert client.get("/api/business/rules/refund-cap", headers=ADMIN).status_code == 404


def test_editing_an_enforcing_rule_needs_the_production_role(client):
    client.post("/api/business/rules", json={"definition": _ladder()}, headers=ADMIN)
    client.post("/api/business/rules/refund-cap/mode", json={"mode": "enforce"}, headers=ADMIN)
    r = client.put(
        "/api/business/rules/refund-cap",
        json={"definition": _ladder(upto=999.0)},
        headers=as_user("priya@example.com"),
    )
    assert r.status_code == 403
    assert client.get("/api/business/rules/refund-cap", headers=ADMIN).json()["mode"] == "enforce"
