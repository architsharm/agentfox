"""A project's setup banner: what it still needs, computed from its data."""

from __future__ import annotations

from agentfox.core.models import Agent
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
AGENT = "support-triage"


def _setup(client, slug=AGENT):
    r = client.get(f"/api/agents/{slug}/setup", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_quiet_project_waits_for_traffic_first(client):
    body = _setup(client)
    assert body["traces"] == 0
    assert body["next"] == "traffic"


def test_traffic_moves_it_on(client):
    client.post("/v1/guard/input", json={"agent": AGENT, "content": "hello"})
    body = _setup(client)
    assert body["traces"] >= 1
    assert body["next"] != "traffic"
    # Watching packs are listed so the banner can say what turning blocking on switches.
    if body["next"] == "enforce":
        assert body["watching"]


def test_a_proposed_project_is_added_first(client, session):
    session.add(Agent(slug="scan-found", name="Scan found", status="draft"))
    session.commit()
    assert _setup(client, "scan-found")["next"] == "add"
