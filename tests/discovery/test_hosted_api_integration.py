"""The second onboarding path — connect a hosted API endpoint plus its OpenAPI spec,
instead of handing over GitHub repo access. Same draft-then-review guarantee as the
repo-scan path: nothing created here is live until a human approves it.
"""

from __future__ import annotations

from agentfox.discovery.openapi import scan_spec
from tests.conftest import as_user

PETSTORE_SPEC = {
    "info": {"title": "Pet Store API"},
    "paths": {
        "/pets": {
            "get": {"summary": "List pets"},
            "post": {"summary": "Create a pet"},
        },
        "/pets/{id}": {
            "delete": {"summary": "Remove a pet"},
            "parameters": [{"name": "id"}],  # not a method — must be ignored
        },
    },
}


# ---------------------------------------------------------------------------
# scan_spec — pure parsing, no network
# ---------------------------------------------------------------------------


def test_scan_spec_turns_operations_into_tool_sites():
    report = scan_spec(PETSTORE_SPEC, source_label="petstore.example.com")
    assert report.files_scanned == 1
    assert report.frameworks == ["hosted_api"]
    assert len(report.sites) == 3
    assert all(s.kind == "tool" and s.provider == "hosted_api" for s in report.sites)
    assert any("DELETE /pets/{id}" in s.detail for s in report.sites)


def test_scan_spec_ignores_non_method_keys_under_a_path():
    report = scan_spec(PETSTORE_SPEC)
    # "parameters" under /pets/{id} is not an HTTP method and must not become a site.
    assert not any("PARAMETERS" in s.detail.upper() for s in report.sites)


def test_scan_spec_with_no_paths_reports_the_gap_rather_than_crashing():
    report = scan_spec({"info": {"title": "Empty"}})
    assert report.sites == []
    assert report.errors


# ---------------------------------------------------------------------------
# The route — draft agent + proposed policy, inert until approved
# ---------------------------------------------------------------------------


def test_scanning_a_hosted_api_proposes_a_draft_agent_and_policy(client, monkeypatch):
    import agentfox.gateway.routes.integrations as integrations

    monkeypatch.setattr(integrations, "fetch_spec", lambda url: PETSTORE_SPEC)

    response = client.post(
        "/api/integrations/hosted-api/scan",
        json={
            "endpoint_url": "https://petstore.example.com/v1",
            "docs_url": "https://petstore.example.com/docs",
            "openapi_spec_url": "https://petstore.example.com/openapi.json",
            "purpose": "Internal pet-store backend",
        },
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["agents_proposed"] == [body["agent"]]
    assert body["summary"]["policies_proposed"], "operations were found, so a policy is proposed"

    agents = client.get("/api/agents", headers=as_user("admin@example.com")).json()["agents"]
    agent = next(a for a in agents if a["slug"] == body["agent"])
    assert agent["status"] == "draft"
    assert agent["registered"] is False


def test_scanning_with_no_spec_still_registers_the_endpoint_for_review(client, monkeypatch):
    """No OpenAPI document to enumerate is not a reason to refuse the connection —
    the reviewer still gets an agent to look at, just with nothing pre-populated."""
    response = client.post(
        "/api/integrations/hosted-api/scan",
        json={"endpoint_url": "https://internal-llm.example.com", "purpose": "internal LLM"},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["policies_proposed"] == []
    assert body["summary"]["agents_proposed"] == [body["agent"]]


def test_a_bad_spec_url_fails_the_scan_without_creating_a_draft_agent(client, monkeypatch):
    import agentfox.gateway.routes.integrations as integrations
    from agentfox.discovery.openapi import SpecFetchError

    def _boom(url):
        raise SpecFetchError("could not fetch the OpenAPI spec: connection refused")

    monkeypatch.setattr(integrations, "fetch_spec", _boom)

    response = client.post(
        "/api/integrations/hosted-api/scan",
        json={
            "endpoint_url": "https://petstore.example.com/v1",
            "openapi_spec_url": "https://petstore.example.com/openapi.json",
        },
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 422
    agents = client.get("/api/agents", headers=as_user("admin@example.com")).json()["agents"]
    assert not any(a["slug"] == "petstore-example-com" for a in agents)


def test_approving_a_hosted_api_draft_makes_it_active(client, monkeypatch):
    import agentfox.gateway.routes.integrations as integrations

    monkeypatch.setattr(integrations, "fetch_spec", lambda url: PETSTORE_SPEC)
    scan = client.post(
        "/api/integrations/hosted-api/scan",
        json={
            "endpoint_url": "https://petstore.example.com/v1",
            "openapi_spec_url": "https://petstore.example.com/openapi.json",
        },
        headers=as_user("admin@example.com"),
    ).json()

    agents = client.get("/api/agents", headers=as_user("admin@example.com")).json()["agents"]
    agent_id = next(a["id"] for a in agents if a["slug"] == scan["agent"])

    approved = client.post(
        f"/api/agents/{agent_id}/approve", headers=as_user("admin@example.com")
    ).json()
    assert approved["status"] == "active"
