"""An agent's Settings say where its traffic comes from, not only where it was registered.

`agentfox init` registers a new agent as development; `auto()` reports its calls as
production. The agent's page said "Environment development" for an agent whose every
run was production.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
SLUG = "env-bot"


def test_agent_carries_the_environment_its_latest_traffic_came_from(client):
    r = client.post("/api/agents", json={"slug": SLUG, "environment": "development"}, headers=ADMIN)
    assert r.status_code == 201, r.text
    before = client.get(f"/api/agents/{SLUG}", headers=ADMIN).json()
    assert before["environment"] == "development"
    assert before["traffic_environment"] is None  # no traffic yet: nothing to say

    client.post("/v1/guard/input", json={"agent": SLUG, "content": "hello"})
    after = client.get(f"/api/agents/{SLUG}", headers=ADMIN).json()
    # What discovery stored is unchanged; the traffic's environment is beside it.
    assert after["environment"] == "development"
    assert after["traffic_environment"] == "production"
    # The agent's page reads it from its posture.
    posture = client.get(f"/api/agents/{SLUG}/posture", headers=ADMIN).json()
    assert posture["agent"]["traffic_environment"] == "production"

    client.post(
        "/v1/guard/input", json={"agent": SLUG, "content": "again", "environment": "staging"}
    )
    latest = client.get(f"/api/agents/{SLUG}", headers=ADMIN).json()
    assert latest["traffic_environment"] == "staging"
