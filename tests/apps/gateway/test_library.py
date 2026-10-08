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
