"""Forms that used to create records nobody could account for or remove.

Before: an empty form placed a workspace-wide hold with no reason, pausing every
purge with nothing to account for it.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def test_a_hold_without_a_reason_is_refused(client):
    for reason in ("", "   "):
        r = client.post("/api/legal-holds", json={"scope": {}, "reason": reason}, headers=ADMIN)
        assert r.status_code == 422, r.text
    ok = client.post("/api/legal-holds", json={"scope": {}, "reason": "case 4471"}, headers=ADMIN)
    assert ok.status_code == 201, ok.text


def test_a_hold_can_be_released_once(client):
    hold = client.post(
        "/api/legal-holds", json={"scope": {}, "reason": "case 4471"}, headers=ADMIN
    ).json()
    # Releasing lets the purge delete what the hold kept, so it needs a reason too.
    for body in ({}, {"reason": "  "}):
        r = client.post(f"/api/legal-holds/{hold['id']}/release", json=body, headers=ADMIN)
        assert r.status_code == 400, r.text
    r = client.post(
        f"/api/legal-holds/{hold['id']}/release", json={"reason": "case closed"}, headers=ADMIN
    )
    assert r.status_code == 200, r.text and r.json()["released_at"]
    assert client.post(f"/api/legal-holds/{hold['id']}/release", headers=ADMIN).status_code == 409
    entries = client.get(
        "/api/audit/entries", params={"action": "legal_hold.released"}, headers=ADMIN
    ).json()["entries"]
    assert entries[0]["payload"]["reason"] == "case closed"
    # The same actor type as a retention change: the audit log names one kind of person.
    assert entries[0]["actor_type"] == "operator"
    assert client.post("/api/legal-holds/nope/release", headers=ADMIN).status_code == 404


def test_a_source_needs_a_key(client):
    # An empty key was accepted, made a source no page could address, and could not
    # be deleted: delete names the source by its key.
    for key in ("", "  "):
        r = client.put("/api/sources", json={"key": key}, headers=ADMIN)
        assert r.status_code == 422, r.text
