"""The enterprise read routes answer, for an admin and for an auditor."""

from __future__ import annotations

from tests.conftest import as_user

PATHS = (
    "/api/controls",
    "/api/frameworks",
    "/api/obligations",
    "/api/board",
    "/api/risk/register",
    "/api/evidence",
    "/api/monitors",
    "/api/authorizers",
)


def test_enterprise_reads(client):
    for path in PATHS:
        assert client.get(path, headers=as_user("admin@example.com")).status_code == 200, path


def test_auditor_can_read_compliance(client):
    for path in ("/api/controls", "/api/board"):
        assert client.get(path, headers=as_user("aisha@example.com")).status_code == 200, path


def test_version_reports_the_enterprise_edition(client):
    body = client.get("/api/version").json()
    assert body["edition"] == "enterprise"
    assert {"compliance", "evidence", "monitoring", "access_checks"} <= set(body["features"])
