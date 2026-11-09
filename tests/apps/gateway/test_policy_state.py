"""Policy state the dashboard shows: restoring a version, what a simulation credits a
pack with, and which project opens by default (UI audit 2026-11-08, B4/B11/B13)."""

from __future__ import annotations

import datetime as dt

from agentfox.platform.policy.simulate import SimulationDiff
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def test_an_earlier_pack_version_can_be_restored(client):
    """Undoing a Tune: the old rules go live again as a new version, same mode."""
    before = client.get("/api/policies/baseline", headers=ADMIN).json()
    live = before["bound_version"]
    patched = client.post(
        "/api/policies/baseline/rules/safety.harm", json={"effect": "escalate"}, headers=ADMIN
    ).json()
    client.post(
        "/api/policies/baseline/mode",
        json={"mode": before["mode"] or "observe", "version": patched["version"]},
        headers=ADMIN,
    )
    assert (
        client.post(
            f"/api/policies/baseline/versions/{patched['version']}/restore", headers=ADMIN
        ).status_code
        == 409
    )
    restored = client.post(f"/api/policies/baseline/versions/{live}/restore", headers=ADMIN)
    assert restored.status_code == 201, restored.text
    out = restored.json()
    assert out["restored"] == live and out["version"] == patched["version"] + 1
    after = client.get("/api/policies/baseline", headers=ADMIN).json()
    assert after["bound_version"] == out["version"]
    assert "escalate" not in after["live_body"].split("safety.harm")[1].split("- id:")[0]
    assert (
        client.post("/api/policies/baseline/versions/999/restore", headers=ADMIN).status_code == 404
    )


def test_restoring_a_blocking_pack_needs_the_production_role(client):
    from tests.conftest import promote

    promote(client, "baseline")
    patched = client.post(
        "/api/policies/baseline/rules/safety.harm", json={"effect": "escalate"}, headers=ADMIN
    ).json()
    r = client.post(
        f"/api/policies/baseline/versions/{patched['version']}/restore",
        headers=as_user("priya@example.com"),
    )
    assert r.status_code == 403, r.text


def test_a_simulation_credits_a_pack_only_with_its_own_stops():
    """B4: a watching words rule's own catches were reported as "0 would have been
    stopped" (newly_blocked); another pack's catches must not count either."""
    diff = SimulationDiff()
    diff.would_stop = [
        {"decision_id": "d1", "trace_id": "t1", "own": "block"},
        {"decision_id": "d2", "trace_id": "t1", "own": "block"},
        {"decision_id": "d3", "trace_id": "t2", "own": "allow"},  # another pack's
    ]
    out = diff.to_json()
    assert out["counts"]["newly_blocked"] == 0
    assert out["counts"]["own_would_stop"] == 2
    assert out["runs_own_would_stop"] == 1
    assert out["runs_would_stop"] == 2


def test_projects_say_when_they_last_had_traffic(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, utcnow

    with session_scope() as s:
        agent = s.query(Agent).filter(Agent.slug == "payments-ops").one()
        agent.last_seen_at = utcnow() + dt.timedelta(minutes=5)
    projects = client.get("/api/projects", headers=ADMIN).json()["projects"]
    mine = next(p for p in projects if "payments-ops" in p["slugs"])
    assert mine["last_seen_at"]
    newest = max((p for p in projects if p["last_seen_at"]), key=lambda p: p["last_seen_at"])
    assert newest is mine
