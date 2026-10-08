"""Applying an import: one custom-pack version, packs watching, detectors only if installed."""

from __future__ import annotations

from agentfox.core.models import CustomRule, Policy
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
SOURCE = """
guard = Guard().use_many(
    CompetitorCheck(["Globex"], on_fail="exception"),
    BanList(banned_words=["darn"], on_fail="reask"),
    DetectPII(["EMAIL_ADDRESS"], on_fail="fix"),
    ValidLength(1, 10),
)
"""


def test_plan_saves_nothing(client, session):
    r = client.post("/api/import/guardrails-ai/plan", json={"source": SOURCE}, headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["summary"] == {"custom_rule": 2, "detector": 0, "pack": 1, "skipped": 1}
    assert session.query(CustomRule).count() == 0


def test_apply_imports_rules_and_packs(client, session):
    r = client.post("/api/import/guardrails-ai", json={"source": SOURCE}, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["rules"]) == ["gr-ban-list", "gr-competitor-check"]
    assert body["custom_policy"]["mode"] == "observe"
    assert "baseline" in body["packs"]
    custom = client.get("/api/policies/custom", headers=ADMIN).json()
    rules = {r["id"]: r for r in custom["live_compiled"]["rules"]}
    assert rules["custom.gr-ban-list"]["on_block"] == "reask"
    assert session.query(Policy).filter_by(key="baseline").count() == 1


def test_unticked_items_are_left_out(client):
    plan = client.post(
        "/api/import/guardrails-ai/plan", json={"source": SOURCE}, headers=ADMIN
    ).json()
    skip = [i for i, item in enumerate(plan["items"]) if item["kind"] == "pack"]
    body = client.post(
        "/api/import/guardrails-ai", json={"source": SOURCE, "skip": skip}, headers=ADMIN
    ).json()
    assert body["packs"] == {}


def test_unknown_tool_and_unreadable_input(client):
    assert (
        client.post("/api/import/other/plan", json={"source": "x"}, headers=ADMIN).status_code
        == 404
    )
    assert (
        client.post(
            "/api/import/guardrails-ai", json={"source": "x = ("}, headers=ADMIN
        ).status_code
        == 400
    )


def test_a_viewer_cannot_import(client):
    r = client.post(
        "/api/import/guardrails-ai/plan",
        json={"source": SOURCE},
        headers=as_user("viewer@example.com"),
    )
    assert r.status_code in (401, 403)
