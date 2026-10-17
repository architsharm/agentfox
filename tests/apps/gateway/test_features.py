"""Features: the workspace sets each switch, a project inherits it until it changes it.

A project can always be stricter than the workspace. It can be looser only where the
workspace lets projects change that protection, and setting it back to the
workspace's value is the same as inheriting.
"""

from __future__ import annotations

from agentfox.capabilities.detection.detector_settings import enabled_for
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
AGENT = "support-triage"
OTHER = "payments-ops"


def _by_key(body, kind):
    return {f["key"]: f for f in body[kind]}


def _agent(client, slug=AGENT):
    return client.get(f"/api/agents/{slug}/features", headers=ADMIN)


def _set(client, key, **body):
    return client.post(f"/api/features/protections/{key}", json=body, headers=ADMIN)


def test_a_project_inherits_the_workspace_until_it_changes_something(client):
    workspace = _by_key(client.get("/api/features", headers=ADMIN).json(), "protections")
    project = _by_key(_agent(client).json(), "protections")
    for key, ws in workspace.items():
        assert project[key]["project"] is None
        assert project[key]["workspace"] == ws["workspace"]
        assert project[key]["effective"] == ws["workspace"]


def test_a_project_can_be_stricter_without_asking(client):
    r = _set(client, "attacks", agent=AGENT, level="high")
    assert r.status_code == 200, r.text
    mine = _by_key(r.json(), "protections")["attacks"]
    assert mine["project"] == "high" and mine["effective"] == "high"
    # Nobody else changed.
    assert _by_key(_agent(client, OTHER).json(), "protections")["attacks"]["project"] is None


def test_lowering_needs_the_workspace_to_allow_it(client):
    ws = _by_key(client.get("/api/features", headers=ADMIN).json(), "protections")["harmful"]
    assert ws["workspace"] != "off" and not ws["open_to_projects"]
    refused = _set(client, "harmful", agent=AGENT, level="off")
    assert refused.status_code == 409
    assert "does not let projects" in refused.json()["detail"]

    assert _set(client, "harmful", open_to_projects=True).status_code == 200
    r = _set(client, "harmful", agent=AGENT, level="off")
    assert r.status_code == 200, r.text
    mine = _by_key(r.json(), "protections")["harmful"]
    assert mine["project"] == "off" and mine["effective"] == "off"
    assert _by_key(_agent(client, OTHER).json(), "protections")["harmful"]["effective"] != "off"


def test_going_back_to_the_workspace_removes_the_projects_copy(client):
    _set(client, "attacks", agent=AGENT, level="high")
    r = client.delete(f"/api/agents/{AGENT}/features/protections/attacks", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert _by_key(r.json(), "protections")["attacks"]["project"] is None


def test_a_workspace_change_reaches_every_project_that_inherits(client):
    r = _set(client, "harmful", level="off")
    assert r.status_code == 200, r.text
    assert _by_key(r.json(), "protections")["harmful"]["workspace"] == "off"
    for slug in (AGENT, OTHER):
        assert _by_key(_agent(client, slug).json(), "protections")["harmful"]["effective"] == "off"


def test_a_check_can_be_switched_for_one_project_either_way(client, session):
    checks = _by_key(_agent(client).json(), "checks")
    assert checks["safety.lexicon"]["workspace"] and checks["safety.lexicon"]["project"] is None

    r = client.post(
        "/api/features/checks/safety.lexicon",
        json={"enabled": False, "agent": AGENT},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    mine = _by_key(r.json(), "checks")["safety.lexicon"]
    assert mine["project"] is False and mine["effective"] is False
    # The runtime reads the same choice: off for this project, on for the rest.
    assert "safety.lexicon" not in enabled_for(session, AGENT)
    assert "safety.lexicon" in enabled_for(session, OTHER)

    back = client.delete(f"/api/agents/{AGENT}/features/checks/safety.lexicon", headers=ADMIN)
    assert _by_key(back.json(), "checks")["safety.lexicon"]["project"] is None
    assert "safety.lexicon" in enabled_for(session, AGENT)


def test_the_safety_net_cannot_be_switched_off_for_a_project(client):
    r = client.post(
        "/api/features/checks/injection.heuristic",
        json={"enabled": False, "agent": AGENT},
        headers=ADMIN,
    )
    assert r.status_code == 400
