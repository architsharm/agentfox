"""The workspace as one file: export, plan, apply — and applying never removes."""

from __future__ import annotations

import yaml

from agentfox.capabilities import workspace
from agentfox.core.models import CustomRule
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _export(client) -> dict:
    r = client.get("/api/workspace/export", headers=ADMIN)
    assert r.status_code == 200
    return yaml.safe_load(r.json()["source"])


def _post(client, path, data, user=ADMIN):
    return client.post(
        f"/api/workspace/{path}", json={"source": yaml.safe_dump(data)}, headers=user
    )


def test_export_round_trips_with_nothing_to_change(client):
    client.post(
        "/api/custom-rules",
        json={"key": "rivals", "name": "Rivals", "kind": "terms", "entries": ["Globex"]},
        headers=ADMIN,
    )
    data = _export(client)
    assert data["kind"] == "agentfox/workspace"
    assert {p["key"] for p in data["policies"]} >= {"baseline", "custom"}
    assert [r["key"] for r in data["custom_rules"]] == ["rivals"]
    plan = _post(client, "plan", data).json()
    assert set(plan["counts"]) == {"unchanged"}


def test_a_changed_rule_is_planned_then_applied(client):
    data = _export(client)
    baseline = next(p for p in data["policies"] if p["key"] == "baseline")
    rule = next(r for r in baseline["policy"]["rules"] if r["id"] == "safety.harm")
    rule["effect"] = "escalate"
    plan = _post(client, "plan", data).json()
    assert {(i["key"], i["change"]) for i in plan["items"] if i["change"] != "unchanged"} == {
        ("baseline", "changed")
    }
    assert _post(client, "apply", data).status_code == 200
    live = client.get("/api/policies/baseline", headers=ADMIN).json()["live_compiled"]["rules"]
    assert next(r for r in live if r["id"] == "safety.harm")["effect"] == "escalate"


def test_what_the_file_leaves_out_is_left_alone(client, session):
    client.post(
        "/api/custom-rules",
        json={"key": "rivals", "name": "Rivals", "kind": "terms", "entries": ["Globex"]},
        headers=ADMIN,
    )
    data = {"kind": "agentfox/workspace", "version": 1, "policies": [], "custom_rules": []}
    plan = _post(client, "plan", data).json()
    assert plan["counts"].get("not_in_file", 0) >= 2
    _post(client, "apply", data)
    assert session.query(CustomRule).filter_by(key="rivals").count() == 1
    assert client.get("/api/policies/baseline", headers=ADMIN).status_code == 200


def test_enforcing_from_a_file_is_simulated_and_needs_the_role(client):
    data = _export(client)
    baseline = next(p for p in data["policies"] if p["key"] == "baseline")
    assert baseline["mode"] == "observe"
    baseline["mode"] = "enforce"
    assert _post(client, "plan", data).json()["enforces"] == ["baseline"]
    assert _post(client, "apply", data, as_user("priya@example.com")).status_code == 403
    r = _post(client, "apply", data)
    assert r.status_code == 200 and "baseline" in r.json()["simulations"]
    assert client.get("/api/policies/baseline", headers=ADMIN).json()["mode"] == "enforce"


def test_new_custom_rules_and_detectors_from_a_file(client, session):
    data = _export(client)
    data["custom_rules"] = [
        {"key": "acct", "name": "Account ids", "kind": "patterns", "entries": [r"ACC-\d{6}"]}
    ]
    data["detectors"] = {"code.insecure": False}
    _post(client, "apply", data)
    assert session.query(CustomRule).filter_by(key="acct").count() == 1
    assert _export(client)["detectors"] == {"code.insecure": False}


def test_bad_files_say_why(client):
    assert "kind" in _post(client, "plan", {"policies": []}).json()["detail"]
    bad = {
        "kind": "agentfox/workspace",
        "custom_rules": [{"key": "x1", "name": "x", "kind": "patterns", "entries": ["(a+)+"]}],
    }
    assert _post(client, "plan", bad).status_code == 400
    r = client.post("/api/workspace/plan", json={"source": "kind: [unclosed"}, headers=ADMIN)
    assert r.status_code == 400


def test_parse_refuses_a_newer_format():
    try:
        workspace.parse("kind: agentfox/workspace\nversion: 99\n")
    except workspace.BundleError as exc:
        assert "newer" in str(exc)
    else:
        raise AssertionError("expected BundleError")
