"""A library's contents, for the library drawer and page: its rules as they ship, and
what its last simulation on the project's agents found."""

from __future__ import annotations

from tests.apps.gateway.test_policy_libraries import ADMIN, SLUG, _connect, _lib, _traffic


def _contents(client, pack, agents=SLUG):
    return client.get(f"/api/library/packs/{pack}/contents?agents={agents}", headers=ADMIN)


def test_a_library_lists_its_rules_before_it_is_applied(client):
    r = _contents(client, "tool-containment")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["id"] == "tool-containment" and out["scoped"] is True
    assert out["rules"] and all(row["effect"] and row["id"] for row in out["rules"])
    assert out["simulation"] is None


def test_the_basic_guardrails_and_a_policy_key_resolve_to_their_library(client):
    basic = _contents(client, "basic").json()
    assert basic["title"] == "Basic guardrails" and len(basic["rules"]) == 4
    assert {s for row in basic["rules"] for s in row["surfaces"]} <= {"input", "output", "tool_result", "retrieved"}
    # A shipped policy's key opens the library that ships it.
    by_policy = _contents(client, "eu-ai-act-high-risk").json()
    assert by_policy["id"] == "eu-ai-act"


def test_a_ladder_library_applies_to_every_agent(client):
    out = _contents(client, "payments/refunds").json()
    assert out["scoped"] is False
    [ladder] = out["rules"]
    assert ladder["effect"] == "escalate" and ladder["installed"] is False
    assert "up to 10 USD: allow" in ladder["detail"]


def test_an_unknown_library_is_not_found(client):
    for pack in ("no-such-pack", "custom", f"agent.{SLUG}.baseline"):
        assert _contents(client, pack).status_code == 404, pack


def test_the_last_simulation_is_reported_for_these_agents_only(client):
    _connect(client)
    _traffic()
    assert _lib(client, "apply").status_code == 200
    assert _lib(client, "simulate").status_code == 200
    sim = _contents(client, "baseline").json()["simulation"]
    assert sim["replayed"] == 2 and sim["blocked"] == 1 and sim["hidden"] == 1
    assert sim["held"] == 0 and sim["since_days"] == 30 and sim["at"]
    assert _contents(client, "baseline", agents="someone-else").json()["simulation"] is None
