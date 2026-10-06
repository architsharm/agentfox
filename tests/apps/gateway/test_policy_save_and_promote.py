"""#64 — saving a policy never changes what is in force; promotion does.

The editor's "Save new version" bound the YAML's own `mode`: saving `mode: enforce`
enforced at once with no simulation, and saving the observe starter over an
enforcing policy demoted it. The simulate-before-promote gate lived only in the
browser.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
OBSERVE_V1 = "key: editor-test\nmode: observe\nrules: []\n"
ENFORCE_V2 = (
    "key: editor-test\nmode: enforce\n"
    "rules:\n  - id: x\n    when: {surface: [input]}\n    effect: block\n"
)


def _row(client) -> dict:
    rows = client.get("/api/policies", headers=ADMIN).json()["policies"]
    return next(p for p in rows if p["key"] == "editor-test")


def test_saving_mode_enforce_does_not_enforce(client):
    assert client.post("/api/policies", json={"body": OBSERVE_V1}, headers=ADMIN).status_code == 201
    saved = client.post("/api/policies", json={"body": ENFORCE_V2}, headers=ADMIN).json()
    assert saved["version"] == 2
    assert saved["live_version"] == 1 and saved["mode"] == "observe" and saved["pending"]
    row = _row(client)
    assert row["mode"] == "observe" and row["bound_version"] == 1


def test_saving_the_observe_starter_does_not_demote_an_enforcing_policy(client):
    client.post("/api/policies", json={"body": OBSERVE_V1}, headers=ADMIN)
    client.post("/api/policies/simulate", json={"body": OBSERVE_V1}, headers=ADMIN)
    assert (
        client.post(
            "/api/policies/editor-test/mode", json={"mode": "enforce"}, headers=ADMIN
        ).status_code
        == 200
    )
    client.post(
        "/api/policies",
        json={"body": OBSERVE_V1.replace("rules: []", "name: edited\nrules: []")},
        headers=ADMIN,
    )
    assert _row(client)["mode"] == "enforce"


def test_enforce_requires_a_simulation_of_the_promoted_version(client):
    client.post("/api/policies", json={"body": OBSERVE_V1}, headers=ADMIN)
    client.post("/api/policies", json={"body": ENFORCE_V2}, headers=ADMIN)

    refused = client.post(
        "/api/policies/editor-test/mode", json={"mode": "enforce", "version": 2}, headers=ADMIN
    )
    assert refused.status_code == 409
    assert "has not been simulated" in refused.json()["detail"]
    assert _row(client)["mode"] == "observe"

    # Simulating different rules does not count.
    client.post("/api/policies/simulate", json={"body": OBSERVE_V1}, headers=ADMIN)
    assert (
        client.post(
            "/api/policies/editor-test/mode", json={"mode": "enforce", "version": 2}, headers=ADMIN
        ).status_code
        == 409
    )

    client.post("/api/policies/simulate", json={"body": ENFORCE_V2}, headers=ADMIN)
    promoted = client.post(
        "/api/policies/editor-test/mode", json={"mode": "enforce", "version": 2}, headers=ADMIN
    )
    assert promoted.status_code == 200, promoted.text
    row = _row(client)
    assert row["mode"] == "enforce" and row["bound_version"] == 2


def test_save_refuses_to_bind_enforce(client):
    response = client.post(
        "/api/policies", json={"body": ENFORCE_V2, "mode": "enforce"}, headers=ADMIN
    )
    assert response.status_code == 409
    assert "promote" in response.json()["detail"]


def test_demoting_never_needs_a_simulation(client):
    client.post("/api/policies", json={"body": OBSERVE_V1}, headers=ADMIN)
    response = client.post(
        "/api/policies/editor-test/mode", json={"mode": "observe"}, headers=ADMIN
    )
    assert response.status_code == 200
