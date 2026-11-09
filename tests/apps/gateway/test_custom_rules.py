"""Custom rules end to end: authored over HTTP, matched by the detector, decided by
the managed `custom` pack, shown to the end user."""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _guard(client, content, surface="input", agent="support-bot"):
    path = "/v1/guard/output" if surface == "output" else "/v1/guard/input"
    return client.post(path, json={"agent": agent, "content": content, "surface": surface}).json()


def _enforce_custom(client):
    """Simulate and promote the custom pack, as the dashboard's Start enforcing does."""
    pack = client.get("/api/policies/custom", headers=ADMIN).json()
    client.post(
        "/api/policies/simulate", json={"body": pack["live_body"], "persist": True}, headers=ADMIN
    )
    r = client.post(
        "/api/policies/custom/mode",
        json={"mode": "enforce", "version": pack["bound_version"]},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text


def test_a_word_list_is_watched_then_enforced_with_its_message(client):
    r = client.post(
        "/api/custom-rules",
        json={
            "key": "competitors",
            "name": "Competitor names",
            "kind": "terms",
            "entries": ["Globex", "Initech"],
            "message": "I can only talk about our own products.",
        },
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    assert r.json()["policy"]["mode"] == "observe"

    watched = _guard(client, "Is Globex cheaper than you?")
    assert watched["verdict"] == "allow" and watched["effective_verdict"] == "block"
    assert "custom.competitors" in {f["rule_id"] for f in watched["rules_fired"]}
    assert _guard(client, "What are your opening hours?")["effective_verdict"] == "allow"

    _enforce_custom(client)
    blocked = _guard(client, "Is Globex cheaper than you?")
    assert blocked["verdict"] == "block"
    assert blocked["user_message"] == "I can only talk about our own products."


def test_a_masking_pattern_rewrites_only_what_it_matched(client):
    client.post(
        "/api/custom-rules",
        json={
            "key": "case-ids",
            "name": "Internal case IDs",
            "kind": "patterns",
            "entries": [r"CASE-\d{6}"],
            "effect": "redact",
            "surfaces": ["output"],
        },
        headers=ADMIN,
    )
    _enforce_custom(client)
    out = _guard(client, "Your ticket is CASE-123456, thanks.", surface="output")
    assert out["verdict"] in ("redact", "mask")
    assert "CASE-123456" not in out["content"] and "thanks" in out["content"]


def test_allowed_topics_flag_off_topic_questions_only(client):
    client.post(
        "/api/custom-rules",
        json={
            "key": "billing-only",
            "name": "Billing questions only",
            "kind": "topic",
            "polarity": "allow",
            "description": "billing invoices payments refunds subscription charges",
            "examples": ["Why was I charged twice?", "How do I update my card for payments?"],
            "effect": "escalate",
        },
        headers=ADMIN,
    )
    on = _guard(client, "I was charged twice on my last invoice, can I get a refund?")
    off = _guard(client, "Write me a poem about the ocean and the moon tonight")
    assert "custom.billing-only" not in {f["rule_id"] for f in on["rules_fired"]}
    assert "custom.billing-only" in {f["rule_id"] for f in off["rules_fired"]}
    # Too short to be about anything: not judged.
    assert "custom.billing-only" not in {
        f["rule_id"] for f in _guard(client, "thanks!")["rules_fired"]
    }


def test_try_matches_without_saving(client):
    r = client.post(
        "/api/custom-rules/try",
        json={"rule": {"name": "x", "kind": "terms", "entries": ["acme"]}, "text": "Acme's prices"},
        headers=ADMIN,
    )
    assert r.json()["matched"] is True
    assert client.get("/api/custom-rules", headers=ADMIN).json()["rules"] == []


def test_dangerous_patterns_are_refused(client):
    r = client.post(
        "/api/custom-rules",
        json={"key": "bad", "name": "bad", "kind": "patterns", "entries": ["(a+)+$"]},
        headers=ADMIN,
    )
    assert r.status_code == 422


def test_deleting_removes_the_rule_from_the_pack(client):
    client.post(
        "/api/custom-rules",
        json={"key": "tmp", "name": "Tmp", "kind": "terms", "entries": ["zzz"]},
        headers=ADMIN,
    )
    assert client.delete("/api/custom-rules/tmp", headers=ADMIN).status_code == 200
    pack = client.get("/api/policies/custom", headers=ADMIN).json()
    assert "custom.tmp" not in pack["live_body"]
    assert "custom.tmp" not in {f["rule_id"] for f in _guard(client, "zzz")["rules_fired"]}


def test_a_tuned_action_survives_editing_the_word_list(client):
    client.post(
        "/api/custom-rules",
        json={"key": "names", "name": "Names", "kind": "terms", "entries": ["foo"]},
        headers=ADMIN,
    )
    patched = client.post(
        "/api/policies/custom/rules/custom.names", json={"effect": "escalate"}, headers=ADMIN
    ).json()
    client.post(
        "/api/policies/custom/mode",
        json={"mode": "observe", "version": patched["version"]},
        headers=ADMIN,
    )
    client.post(
        "/api/custom-rules",
        json={"key": "names", "name": "Names", "kind": "terms", "entries": ["foo", "bar"]},
        headers=ADMIN,
    )
    fired = {f["rule_id"]: f for f in _guard(client, "bar")["rules_fired"]}
    assert fired["custom.names"]["effect"] == "escalate"


def test_adding_a_rule_to_an_enforcing_pack_is_simulated_first(client):
    client.post(
        "/api/custom-rules",
        json={"key": "one", "name": "One", "kind": "terms", "entries": ["alpha"]},
        headers=ADMIN,
    )
    _enforce_custom(client)
    r = client.post(
        "/api/custom-rules",
        json={"key": "two", "name": "Two", "kind": "terms", "entries": ["beta"]},
        headers=ADMIN,
    )
    assert r.json()["policy"]["mode"] == "enforce"
    assert r.json()["policy"]["simulation"] is not None
    # The form promises a new rule starts by watching, even with Your rules blocking.
    assert r.json()["mode"] == "observe"
    watched = _guard(client, "beta")
    assert watched["verdict"] == "allow" and watched["effective_verdict"] == "block"
    fired = {f["rule_id"]: f for f in watched["rules_fired"]}
    assert fired["custom.two"]["mode"] == "observe"
    # The rule that was already there still blocks.
    assert _guard(client, "alpha")["verdict"] == "block"

    # Start blocking just this rule: a new version, simulated, then made live.
    v = client.post("/api/policies/custom/rules/custom.two", json={"watch": False}, headers=ADMIN)
    assert v.status_code == 201, v.text
    sim = client.post(
        "/api/policies/simulate", json={"body": v.json()["body"], "persist": True}, headers=ADMIN
    )
    assert sim.status_code == 200, sim.text
    r = client.post(
        "/api/policies/custom/mode",
        json={"mode": "enforce", "version": v.json()["version"]},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert _guard(client, "beta")["verdict"] == "block"

    # Editing its words later does not send it back to watching.
    client.post(
        "/api/custom-rules",
        json={"key": "two", "name": "Two", "kind": "terms", "entries": ["beta", "gamma"]},
        headers=ADMIN,
    )
    assert _guard(client, "gamma")["verdict"] == "block"


def test_detectors_switch_per_workspace_but_the_safety_net_stays(client):
    assert (
        client.post(
            "/api/detectors/schema.json", json={"enabled": False}, headers=ADMIN
        ).status_code
        == 200
    )
    detectors = {
        d["key"]: d for d in client.get("/api/detectors", headers=ADMIN).json()["detectors"]
    }
    assert detectors["schema.json"]["enabled"] is False
    assert (
        client.post(
            "/api/detectors/injection.heuristic", json={"enabled": False}, headers=ADMIN
        ).status_code
        == 400
    )
    assert (
        client.post("/api/detectors/nope", json={"enabled": True}, headers=ADMIN).status_code == 404
    )


def test_a_validator_rule_is_listed_tried_saved_and_enforced(client):
    listed = client.get("/api/validators", headers=ADMIN).json()["validators"]
    ban = next(v for v in listed if v["name"] == "ban_list")
    assert ban["available"] and "banned_words" in ban["params_schema"]["required"]

    rule = {
        "key": "fuzzy-competitors",
        "name": "Competitors, however spelled",
        "kind": "validator",
        "validator": {"name": "ban_list", "params": {"banned_words": ["Globex"]}},
        "surfaces": ["input"],
    }
    tried = client.post(
        "/api/custom-rules/try",
        json={"rule": rule, "text": "is G l o b e x cheaper?", "surface": "input"},
        headers=ADMIN,
    ).json()
    assert tried["matched"] and tried["matches"][0]["reason"]

    bad = client.post(
        "/api/custom-rules",
        json={**rule, "validator": {"name": "ban_list", "params": {}}},
        headers=ADMIN,
    )
    assert bad.status_code == 422

    r = client.post(
        "/api/custom-rules", json={**rule, "message": "Let's talk about us."}, headers=ADMIN
    )
    assert r.status_code == 201, r.text
    saved = r.json()["rule"]
    assert saved["validator"] == {
        "name": "ban_list",
        "params": {"banned_words": ["Globex"], "max_l_dist": 1},
    }

    _enforce_custom(client)
    blocked = _guard(client, "Is Gl0bex cheaper than you?")
    assert blocked["verdict"] == "block", blocked
    assert blocked["user_message"] == "Let's talk about us."
    assert _guard(client, "What are your opening hours?")["verdict"] == "allow"


def test_try_applies_a_rule_scoped_to_agents_as_it_runs_for_them(client):
    rule = {"name": "x", "kind": "terms", "entries": ["acme"], "agents": ["support-agent"]}
    r = client.post(
        "/api/custom-rules/try", json={"rule": rule, "text": "Acme's prices"}, headers=ADMIN
    )
    assert r.json()["matched"] is True


def test_a_check_that_cannot_run_here_is_not_saved_and_degrades_if_already_saved(
    client, monkeypatch
):
    from agentfox.capabilities.detection.validators import get_validator

    rule = {
        "key": "competitors",
        "name": "Competitors",
        "kind": "validator",
        "validator": {"name": "ban_list", "params": {"banned_words": ["Globex"]}},
        "surfaces": ["input"],
    }
    # Saved while the check could run; then the server lost what it needs.
    assert client.post("/api/custom-rules", json=rule, headers=ADMIN).status_code == 201
    cls = type(get_validator("ban_list"))
    monkeypatch.setattr(cls, "available", lambda self: False)
    monkeypatch.setattr(cls, "unavailable_reason", lambda self: "needs nothing-here")

    r = client.post("/api/custom-rules", json={**rule, "key": "again"}, headers=ADMIN)
    assert r.status_code == 400 and "needs nothing-here" in r.json()["detail"]

    out = _guard(client, "Is Globex cheaper?")
    assert "custom.validators" in out["degraded"], out


def test_a_rules_history_says_what_changed_and_restoring_puts_the_words_back(client):
    def save(entries):
        r = client.post(
            "/api/custom-rules",
            json={"key": "rivals", "name": "Rivals", "kind": "terms", "entries": entries},
            headers=ADMIN,
        )
        assert r.status_code == 201, r.text

    save(["Globex", "Initech"])
    save(["Globex", "Hooli"])
    versions = client.get("/api/custom-rules/rivals/history", headers=ADMIN).json()["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["live"] and not versions[1]["live"]
    assert versions[0]["change"] == "Added “Hooli”; removed “Initech”"
    assert versions[1]["change"] == "Created"

    r = client.post("/api/custom-rules/rivals/versions/1/restore", headers=ADMIN)
    assert r.status_code == 201, r.text
    assert r.json()["rule"]["entries"] == ["Globex", "Initech"]
    assert _guard(client, "Ask Initech")["effective_verdict"] == "block"
    assert _guard(client, "Ask Hooli")["effective_verdict"] == "allow"
    latest = client.get("/api/custom-rules/rivals/history", headers=ADMIN).json()["versions"][0]
    assert latest["change"] == "Restored version 1: added “Initech”; removed “Hooli”"
    again = client.post("/api/custom-rules/rivals/versions/3/restore", headers=ADMIN)
    assert again.status_code == 409


def test_a_sequence_rule_can_be_tried_on_a_made_up_run(client):
    rule = {
        "name": "No email after CRM",
        "kind": "sequence",
        "sequence": {
            "after": "crm.*",
            "then": "email.send",
            "unless_path": "to",
            "unless_matches": r"@acme\.com$",
        },
    }

    def tried(text):
        r = client.post("/api/custom-rules/try", json={"rule": rule, "text": text}, headers=ADMIN)
        assert r.status_code == 200, r.text
        return r.json()

    hit = tried('crm.lookup -> email.send {"to": "x@gmail.com"}')
    assert hit["matched"] and hit["matches"][0]["reason"] == "email.send after crm.lookup"
    assert not tried('crm.lookup -> email.send {"to": "ops@acme.com"}')["matched"]
    assert not tried("email.send, crm.lookup")["matched"]
