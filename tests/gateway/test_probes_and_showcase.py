"""The probe-target API (consent recorded, security-only writes) and the public showcase."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.core.config import get_settings
from agentfox.core.models import Finding, ProbeTarget, RedTeamCampaign
from agentfox.core.tenancy import bind_session
from agentfox.evaluation import live_probes, showcase
from agentfox.gateway.routes import probes as probe_routes
from tests.conftest import as_user

SECURITY = as_user("marcus@example.com")
DEVELOPER = as_user("priya@example.com")
CRON = "/api/internal/jobs/run"


@pytest.fixture(autouse=True)
def _fresh_showcase_cache():
    showcase.reset_cache()
    yield
    showcase.reset_cache()


def _create(client, headers=SECURITY, **body):
    payload = {"agent": "support-triage", "adapter": "http", "url": "https://agent.example/p"}
    payload.update(body)
    return client.post("/api/probes/targets", json=payload, headers=headers)


def test_registering_needs_a_security_role_and_starts_disabled(client):
    assert _create(client, headers=DEVELOPER).status_code == 403
    response = _create(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["enabled"] is False and body["opted_in_by"] is None
    assert body["warning"] == live_probes.OPT_IN_WARNING


def test_opt_in_records_the_caller_and_needs_the_warning(client):
    target_id = _create(client).json()["id"]
    url = f"/api/probes/targets/{target_id}/opt-in"
    bad = client.post(url, json={"acknowledgement": "yes"}, headers=SECURITY)
    assert bad.status_code == 422
    warning = client.get("/api/probes/warning", headers=SECURITY).json()["warning"]
    ok = client.post(url, json={"acknowledgement": warning}, headers=SECURITY)
    assert ok.status_code == 200, ok.text
    assert ok.json()["enabled"] is True
    assert ok.json()["opted_in_by"] == "marcus@example.com"

    off = client.post(f"/api/probes/targets/{target_id}/opt-out", headers=SECURITY)
    assert off.json()["enabled"] is False


def test_running_a_target_that_is_not_opted_in_is_refused(client):
    target_id = _create(client).json()["id"]
    response = client.post(f"/api/probes/targets/{target_id}/run", headers=SECURITY)
    assert response.status_code == 409
    assert "not opted in" in response.json()["detail"]


def test_a_non_http_url_is_rejected(client):
    assert _create(client, url="file:///etc/passwd").status_code == 422


def test_changing_the_url_over_the_api_clears_the_opt_in(client):
    target_id = _create(client).json()["id"]
    client.post(
        f"/api/probes/targets/{target_id}/opt-in",
        json={"acknowledgement": live_probes.OPT_IN_WARNING},
        headers=SECURITY,
    )
    patched = client.patch(
        f"/api/probes/targets/{target_id}",
        json={"url": "https://new.example/p", "max_probes_per_run": 999},
        headers=SECURITY,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["enabled"] is False and body["registered_host"] == "new.example"
    assert body["max_probes_per_run"] == live_probes.MAX_PROBES_PER_RUN_CAP


def test_an_in_process_target_runs_over_the_api_and_is_rate_limited(client):
    created = _create(client, adapter="in_process", url=None, model="echo-1").json()
    client.post(
        f"/api/probes/targets/{created['id']}/opt-in",
        json={"acknowledgement": live_probes.OPT_IN_WARNING},
        headers=SECURITY,
    )
    run = client.post(f"/api/probes/targets/{created['id']}/run", headers=SECURITY)
    assert run.status_code == 200, run.text
    assert run.json()["attacks_attempted"] == 9
    again = client.post(f"/api/probes/targets/{created['id']}/run", headers=SECURITY)
    assert again.status_code == 429
    listed = client.get(f"/api/probes/targets/{created['id']}/campaigns", headers=SECURITY)
    assert [c["id"] for c in listed.json()["campaigns"]] == [run.json()["campaign_id"]]


# ---------------------------------------------------------------------------
# public showcase
# ---------------------------------------------------------------------------


def test_the_showcase_is_off_unless_enabled(client):
    response = client.get("/api/public/showcase")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "last_updated": None}


@pytest.fixture
def showcase_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "showcase_enabled", True)
    monkeypatch.setattr(get_settings(), "cron_secret", "cron-test")
    monkeypatch.delenv("CRON_SECRET", raising=False)


def test_the_cron_builds_the_showcase_and_probes_it(client, showcase_on):
    response = client.post(CRON, headers={"Authorization": "Bearer cron-test"})
    assert response.status_code == 200, response.text
    assert response.json()["showcase"]["target_created"] is True

    body = client.get("/api/public/showcase").json()
    assert body["enabled"] is True
    assert body["agent"]["slug"] == "support-triage"
    assert body["target"]["model"] == "echo-1" and body["target"]["scoring"] == "gateway_verdict"
    totals = body["totals"]
    assert totals["runs"] == 1 and totals["attacks_attempted"] == 9
    assert totals["contained"] + totals["escaped"] == 9
    # Every attack is contained and neither benign control is over-blocked. A probe that
    # starts escaping is a detector regression the public page would show.
    assert (totals["contained"], totals["escaped"], totals["over_blocked"]) == (9, 0, 0), [
        (r["key"], r["status"]) for r in body["latest"]["results"]
    ]
    # Honest numbers: whatever escaped is an open finding, and both say the same thing.
    assert body["findings"]["open"] == totals["escaped"]
    assert body["latest"]["run"]["escaped"] == totals["escaped"]
    # Read back from the database in a fresh session, not from the run's own objects.
    assert body["latest"]["run"]["findings_opened"] == totals["escaped"]
    assert body["last_updated"] is not None
    keys = {r["key"] for r in body["latest"]["results"]}
    assert "injection.direct_override" in keys

    # Nothing in the public payload is probe text, a reply, or a canary.
    text = str(body)
    assert "Ignore all previous instructions" not in text
    assert "AFX-" not in text and "probe.invalid" not in text

    # A second cron run the same hour is idempotent: no second world, no second target.
    again = client.post(CRON, headers={"Authorization": "Bearer cron-test"}).json()
    assert again["showcase"]["seeded"] is False and again["showcase"]["target_created"] is False


def test_the_showcase_reads_only_its_own_tenant(client, showcase_on, session):
    from agentfox.prove.findings import raise_finding

    client.post(CRON, headers={"Authorization": "Bearer cron-test"})
    # A live-probe finding and campaign in a *customer* tenant must never show up.
    raise_finding(
        session,
        type=live_probes.FINDING_TYPE,
        title="customer finding",
        subject_id="customer-agent",
        evidence={"probe": "injection.direct_override"},
    )
    session.add(
        RedTeamCampaign(
            name="customer",
            runner="live",
            status="completed",
            target_json={"source": "live_probe"},
            summary_json={"attacks_attempted": 100, "escaped": 100},
        )
    )
    session.commit()
    showcase.reset_cache()
    body = client.get("/api/public/showcase").json()
    assert body["totals"]["attacks_attempted"] == 9
    assert "customer finding" not in str(body)

    bind_session(session, get_settings().showcase_org_id)
    assert session.scalar(select(ProbeTarget)).opted_in_by.startswith("agentfox-showcase")


def test_the_showcase_is_cached_and_rate_limited(client, showcase_on, monkeypatch):
    client.post(CRON, headers={"Authorization": "Bearer cron-test"})
    first = client.get("/api/public/showcase")
    assert "max-age=60" in first.headers["cache-control"]
    calls = []
    monkeypatch.setattr(showcase, "build_summary", lambda s: calls.append(1) or {})
    assert client.get("/api/public/showcase").json() == first.json()
    assert calls == []  # served from cache

    monkeypatch.setattr(probe_routes, "showcase_limiter", probe_routes.RateLimiter(2, 60))
    statuses = [client.get("/api/public/showcase").status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


def test_a_showcase_regression_shows_up_and_closes(client, showcase_on, session):
    """Flip the showcase policy to observe (as a bad deploy might): attacks that were
    blocked now reach the model, the public numbers say so, and findings open."""
    from agentfox.policy import set_mode

    client.post(CRON, headers={"Authorization": "Bearer cron-test"})
    bind_session(session, get_settings().showcase_org_id)
    before = session.scalar(select(RedTeamCampaign)).summary_json["escaped"]
    target = session.scalar(select(ProbeTarget))
    set_mode(session, "baseline", "observe")
    campaign = live_probes.run_target(session, target, sleep=lambda s: None)
    session.commit()
    assert campaign.summary_json["escaped"] > before
    assert campaign.summary_json["posture"]["direction"] == "weaker"
    regressions = [
        f
        for f in session.scalars(select(Finding).where(Finding.type == live_probes.FINDING_TYPE))
        if f.evidence_json.get("regression")
    ]
    assert regressions
    showcase.reset_cache()
    assert (
        client.get("/api/public/showcase").json()["findings"]["open"]
        == campaign.summary_json["escaped"]
    )
