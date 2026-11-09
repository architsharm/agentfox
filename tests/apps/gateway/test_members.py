"""Settings → Members: list the workspace, add a teammate with a role and a sign-in
key shown once, change a role or deactivate. Changing members is owner/admin only."""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
DEV = as_user("priya@example.com")


def test_an_owner_adds_a_teammate_who_signs_in_with_the_key(client):
    listed = client.get("/api/members", headers=DEV).json()
    assert "owner" in listed["roles"] and listed["members"]

    added = client.post(
        "/api/members", json={"email": "new.person@example.com", "role": "auditor"}, headers=ADMIN
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["member"]["role"] == "auditor" and body["signInKey"].startswith("nom_api_")
    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['signInKey']}"})
    assert me.status_code == 200 and me.json()["email"] == "new.person@example.com"

    again = client.post("/api/members", json={"email": "new.person@example.com"}, headers=ADMIN)
    assert again.status_code == 409
    bad = client.post("/api/members", json={"email": "x@example.com", "role": "god"}, headers=ADMIN)
    assert bad.status_code == 422

    member_id = body["member"]["id"]
    changed = client.patch(f"/api/members/{member_id}", json={"role": "developer"}, headers=ADMIN)
    assert changed.status_code == 200 and changed.json()["role"] == "developer"
    off = client.patch(f"/api/members/{member_id}", json={"active": False}, headers=ADMIN)
    assert off.json()["active"] is False
    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['signInKey']}"})
    assert me.status_code == 401


def test_only_owners_and_admins_change_members_and_nobody_changes_themselves(client):
    assert client.post("/api/members", json={"email": "a@example.com"}, headers=DEV).status_code == 403
    me = client.get("/api/me", headers=ADMIN).json()
    assert client.patch(f"/api/members/{me['id']}", json={"role": "auditor"}, headers=ADMIN).status_code == 409
