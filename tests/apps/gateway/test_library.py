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


def test_compile_for_an_agent_governs_its_own_tool(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        session.add(
            Agent(
                slug="support-agent",
                registered=True,
                status="active",
                declared_tools=["issue_refund", "lookup_order", "send_email"],
            )
        )
    out = client.post(
        "/api/business/compile",
        json={"text": "Refunds over $50 need approval from a manager.", "agent": "support-agent"},
        headers=ADMIN,
    ).json()
    ladder = next(r for r in out["rules"] if r["kind"] == "threshold_ladder")
    assert ladder["definition"]["tool"] == "issue_refund"


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
    # The same gate as a library: simulated first, then enforced.
    refused = client.post(
        f"/api/business/rules/{key}/mode", json={"mode": "enforce"}, headers=ADMIN
    )
    assert refused.status_code == 409 and "simulated" in refused.json()["detail"]
    assert client.post(f"/api/business/rules/{key}/simulate", headers=ADMIN).status_code == 200
    enforced = client.post(
        f"/api/business/rules/{key}/mode", json={"mode": "enforce"}, headers=ADMIN
    )
    assert enforced.json()["mode"] == "enforce"


def test_a_business_rule_says_which_agent_it_is_scoped_to(client):
    """The approval-limit form offers "this agent" or "every agent"; the rule says
    which it got, so the screens can show it."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        session.add(Agent(slug="pay-bot", registered=True, status="active"))
    ladder = next(
        r
        for r in client.post(
            "/api/business/compile", json={"text": LADDER_TEXT}, headers=ADMIN
        ).json()["rules"]
        if r["kind"] == "threshold_ladder"
    )
    one = client.post(
        "/api/business/rules",
        json={"definition": {**ladder["definition"], "key": "one"}, "agent": "pay-bot"},
        headers=ADMIN,
    ).json()
    every = client.post(
        "/api/business/rules",
        json={"definition": {**ladder["definition"], "key": "every"}},
        headers=ADMIN,
    ).json()
    assert one["agent"] == "pay-bot" and every["agent"] is None
    listed = {
        r["key"]: r["agent"]
        for r in client.get("/api/business/rules", headers=ADMIN).json()["rules"]
    }
    assert listed == {"one": "pay-bot", "every": None}


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
    _enforce(client, "refund-cap")
    r = client.put(
        "/api/business/rules/refund-cap",
        json={"definition": _ladder(upto=999.0)},
        headers=as_user("priya@example.com"),
    )
    assert r.status_code == 403
    assert client.get("/api/business/rules/refund-cap", headers=ADMIN).json()["mode"] == "enforce"


def _enforce(client, key):
    assert client.post(f"/api/business/rules/{key}/simulate", headers=ADMIN).status_code == 200
    r = client.post(f"/api/business/rules/{key}/mode", json={"mode": "enforce"}, headers=ADMIN)
    assert r.status_code == 200, r.text


def _transfer(client, amount, **extra):
    return client.post(
        "/v1/guard/tool_call",
        json={
            "agent": "support-triage",
            "tool": "payments.refund",
            "arguments": {"amount": amount, "currency": "USD"},
            "intent": "Refund the customer's duplicate charge",
            **extra,
        },
    ).json()


def test_start_blocking_a_business_rule_replays_recent_calls_first(client):
    """B6: the simulation says what the rule would have held; a changed rule needs a new one."""
    for amount in (40, 400):
        _transfer(client, amount)
    client.post("/api/business/rules", json={"definition": _ladder()}, headers=ADMIN)
    sim = client.post("/api/business/rules/refund-cap/simulate", headers=ADMIN).json()
    assert sim["replayed"] >= 2
    # Only the call over the limit: held by the rule now, or already stopped by another.
    counts = sim["counts"]
    assert counts["would_stop"] + counts["already_stopped"] == 1
    assert all(r["value"] > 100 for r in sim["would_stop"])
    # Editing the bands makes the simulation stale: enforcing asks for a new one.
    client.put(
        "/api/business/rules/refund-cap", json={"definition": _ladder(upto=500.0)}, headers=ADMIN
    )
    stale = client.post(
        "/api/business/rules/refund-cap/mode", json={"mode": "enforce"}, headers=ADMIN
    )
    assert stale.status_code == 409
    # Going back to watching never needs one.
    _enforce(client, "refund-cap")
    back = client.post(
        "/api/business/rules/refund-cap/mode", json={"mode": "observe"}, headers=ADMIN
    )
    assert back.json()["mode"] == "observe"


def test_a_business_rule_is_one_more_applied_rule(client):
    """B2: Applied rules and the effective policy list it, in its own mode, in Your rules."""
    client.post("/api/business/rules", json={"definition": _ladder()}, headers=ADMIN)
    applied = client.get("/api/policies/applied", headers=ADMIN).json()
    row = next(r for r in applied["rules"] if r["id"] == "business.refund-cap")
    assert row["mode"] == "observe" and row["effect"] == "escalate"
    assert row["libraries"] == ["Your rules"] and row["all"]
    effective = client.get("/api/policies/effective?agent=support-triage", headers=ADMIN).json()
    rule = next(r for r in effective["rules"] if r["rule_id"] == "business.refund-cap")
    assert rule["enforcement"] == "observe" and rule["level"] == "business"
    _enforce(client, "refund-cap")
    applied = client.get("/api/policies/applied", headers=ADMIN).json()
    assert (
        next(r for r in applied["rules"] if r["id"] == "business.refund-cap")["mode"] == "enforce"
    )


def test_the_effective_policy_defaults_to_the_agents_environment(client):
    """B16: the runtime resolves an agent in its own environment, not the caller's."""
    out = client.get("/api/policies/effective?agent=support-triage", headers=ADMIN).json()
    assert out["environment"] == "production"
    out = client.get(
        "/api/policies/effective?agent=support-triage&environment=staging", headers=ADMIN
    ).json()
    assert out["environment"] == "staging"


def test_an_earlier_business_rule_version_can_be_restored(client):
    """B13: Restore puts the old bands back as a new version, in the rule's mode."""
    client.post("/api/business/rules", json={"definition": _ladder()}, headers=ADMIN)
    client.put(
        "/api/business/rules/refund-cap", json={"definition": _ladder(upto=250.0)}, headers=ADMIN
    )
    versions = client.get("/api/business/rules/refund-cap/history", headers=ADMIN).json()[
        "versions"
    ]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["live"] and not versions[1]["live"]
    assert (
        client.post("/api/business/rules/refund-cap/versions/2/restore", headers=ADMIN).status_code
        == 409
    )
    restored = client.post("/api/business/rules/refund-cap/versions/1/restore", headers=ADMIN)
    assert restored.status_code == 201, restored.text
    assert restored.json()["version"] == 3
    rule = client.get("/api/business/rules/refund-cap", headers=ADMIN).json()
    assert rule["definition"]["bands"][0]["upto"] == 100.0 and rule["mode"] == "observe"
