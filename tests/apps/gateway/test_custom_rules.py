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
    assert _guard(client, "beta")["verdict"] == "block"


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
