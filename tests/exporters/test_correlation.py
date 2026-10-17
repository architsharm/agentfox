"""I-4 / I-6 — LangSmith and Langfuse correlation.

The failure being removed: two systems that both describe the same request and
cannot be joined, so an incident costs twenty minutes of timestamp arithmetic.
"""

from __future__ import annotations

import pytest

from agentfox.core.models import Trace
from agentfox.exporters.correlation import (
    LANGFUSE,
    LANGSMITH,
    OTEL,
    ExternalRef,
    deep_link,
    link_trace,
    links_for,
    refs_from_headers,
    resolve_external,
)
from tests.conftest import as_user

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


# ---------------------------------------------------------------------------
# Reading the join key off the request
# ---------------------------------------------------------------------------


def test_traceparent_is_the_zero_configuration_path():
    """A team already running an OTel SDK gets correlation with no header setup and
    no vendor lock — which is the only version of this anyone actually adopts."""
    refs = refs_from_headers({"traceparent": TRACEPARENT})
    assert [r.system for r in refs] == [OTEL]
    assert refs[0].external_trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert refs[0].external_run_id == "00f067aa0ba902b7"


def test_malformed_traceparent_is_ignored_rather_than_stored():
    assert refs_from_headers({"traceparent": "garbage"}) == []
    assert refs_from_headers({"traceparent": "00-tooshort-00f067aa0ba902b7-01"}) == []


def test_header_names_are_matched_case_insensitively():
    """Vendor SDKs and proxies disagree on spelling; a join key missed because of a
    capital letter is a join key we do not have."""
    refs = refs_from_headers({"Langfuse-Trace-Id": "lf-1", "X-LangSmith-Trace-Id": "ls-1"})
    assert {r.system for r in refs} == {LANGFUSE, LANGSMITH}


def test_run_ids_are_attached_to_the_right_system():
    refs = refs_from_headers(
        {
            "langsmith-trace-id": "ls-1",
            "langsmith-run-id": "ls-run",
            "langfuse-trace-id": "lf-1",
            "langfuse-observation-id": "lf-obs",
        }
    )
    by_system = {r.system: r for r in refs}
    assert by_system[LANGSMITH].external_run_id == "ls-run"
    assert by_system[LANGFUSE].external_run_id == "lf-obs"


def test_no_correlation_headers_is_the_normal_case_not_an_error():
    assert refs_from_headers({"content-type": "application/json"}) == []
    assert refs_from_headers({}) == []
    assert refs_from_headers(None) == []


# ---------------------------------------------------------------------------
# Deep links
# ---------------------------------------------------------------------------


def test_deep_links_are_built_for_known_hosts():
    assert deep_link(LANGFUSE, "lf-1") == "https://cloud.langfuse.com/trace/lf-1"
    assert "/r/ls-1" in deep_link(LANGSMITH, "ls-1")


def test_no_link_is_better_than_a_link_that_404s(monkeypatch):
    """Self-hosted Langfuse lives on a customer domain. Guessing the SaaS URL produces
    a link that does not resolve, which is worse than admitting we cannot build one."""
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "langfuse_host", "")
    assert deep_link(LANGFUSE, "lf-1") is None
    assert deep_link(OTEL, "abc") is None


# ---------------------------------------------------------------------------
# Storage and both directions of lookup
# ---------------------------------------------------------------------------


def _trace(session) -> Trace:
    trace = Trace(agent_slug="support-triage", verdict="allow")
    session.add(trace)
    session.flush()
    return trace


def test_linking_is_idempotent(seeded):
    trace = _trace(seeded)
    ref = ExternalRef(LANGFUSE, "lf-1")
    link_trace(seeded, trace.id, [ref])
    link_trace(seeded, trace.id, [ref])
    assert len(links_for(seeded, trace.id)) == 1


def test_a_later_run_id_backfills_an_existing_link(seeded):
    trace = _trace(seeded)
    link_trace(seeded, trace.id, [ExternalRef(LANGFUSE, "lf-1")])
    link_trace(seeded, trace.id, [ExternalRef(LANGFUSE, "lf-1", "lf-obs")])
    links = links_for(seeded, trace.id)
    assert len(links) == 1 and links[0].external_run_id == "lf-obs"


def test_unknown_systems_are_refused(seeded):
    trace = _trace(seeded)
    assert link_trace(seeded, trace.id, [ExternalRef("wandb", "w-1")]) == []


def test_reverse_lookup_accepts_either_id(seeded):
    """An engineer copying an id out of a Langfuse UI does not know or care whether
    they grabbed the trace or the observation."""
    trace = _trace(seeded)
    link_trace(seeded, trace.id, [ExternalRef(LANGFUSE, "lf-1", "lf-obs")])
    assert resolve_external(seeded, LANGFUSE, "lf-1")[0].trace_id == trace.id
    assert resolve_external(seeded, LANGFUSE, "lf-obs")[0].trace_id == trace.id
    assert resolve_external(seeded, LANGSMITH, "lf-1") == [], "systems must not cross-match"


# ---------------------------------------------------------------------------
# The enforcement path
# ---------------------------------------------------------------------------


def test_a_governed_completion_records_the_link(seeded, enforcer):
    result, _ = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hello"}],
        model="echo-1",
        correlation={"langfuse-trace-id": "lf-42", "traceparent": TRACEPARENT},
    )
    links = {link.system: link for link in links_for(seeded, result.trace_id)}
    assert links[LANGFUSE].external_trace_id == "lf-42"
    assert links[OTEL].external_trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_a_blocked_request_is_still_correlated(seeded, enforcer):
    """The blocked ones are precisely the requests someone will come looking for."""
    from agentfox.core.models import Agent, Budget

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    seeded.query(Budget).filter_by(scope_id=agent.id).one().max_calls = 0
    seeded.flush()

    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hello"}],
        model="echo-1",
        correlation={"langfuse-trace-id": "lf-blocked"},
    )
    assert result.blocked and response is None
    assert links_for(seeded, result.trace_id)[0].external_trace_id == "lf-blocked"


def test_correlation_never_fails_the_request(seeded, enforcer, monkeypatch):
    """Correlation is a convenience for whoever debugs this later. It must not be able
    to take down the path it is describing."""
    import agentfox.exporters.correlation as correlation

    def explode(*args, **kwargs):
        raise RuntimeError("link store unavailable")

    monkeypatch.setattr(correlation, "link_trace", explode)
    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hello"}],
        model="echo-1",
        correlation={"langfuse-trace-id": "lf-1"},
    )
    assert response is not None and not result.blocked


def test_push_is_off_without_egress(seeded, enforcer):
    """NFR-4: nothing leaves the customer boundary by default, including a verdict."""
    from agentfox.exporters.correlation import push_verdict

    trace = _trace(seeded)
    link_trace(seeded, trace.id, [ExternalRef(LANGSMITH, "ls-1")])
    assert push_verdict(seeded, trace.id, verdict="block") == []


def test_push_failure_is_recorded_not_raised(seeded, monkeypatch):
    """An observability vendor having an outage must not become our outage."""
    from agentfox.core.config import get_settings
    from agentfox.exporters.correlation import push_verdict

    settings = get_settings()
    monkeypatch.setattr(settings, "allow_egress", True)
    monkeypatch.setattr(settings, "correlation_push", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "test-key")

    import httpx

    def explode(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "patch", explode)

    trace = _trace(seeded)
    link_trace(seeded, trace.id, [ExternalRef(LANGSMITH, "ls-1", "ls-run")])
    results = push_verdict(seeded, trace.id, verdict="block")
    assert len(results) == 1 and results[0].ok is False
    assert "no route to host" in results[0].detail


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


@pytest.fixture
def governed(client):
    response = client.post(
        "/v1/chat/completions",
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hello"}]},
        headers={"X-AgentFox-Agent": "support-triage", "langfuse-trace-id": "lf-api"},
    )
    assert response.status_code == 200
    return response.headers["X-AgentFox-Trace"]


def test_gateway_captures_headers_from_the_live_proxy(client, governed):
    body = client.get(f"/api/traces/{governed}", headers=as_user("admin@example.com")).json()
    assert body["links"][0]["external_trace_id"] == "lf-api"
    assert body["links"][0]["url"] == "https://cloud.langfuse.com/trace/lf-api"


def test_reverse_lookup_over_the_api(client, governed):
    response = client.get(
        "/api/traces/resolve",
        params={"system": "langfuse", "external_id": "lf-api"},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200
    match = response.json()["matches"][0]
    assert match["trace_id"] == governed
    assert match["agent"] == "support-triage"
    assert match["detail"] == f"/api/traces/{governed}"


def test_resolve_route_is_not_shadowed_by_the_trace_detail_route(client):
    """`/traces/{trace_id}` is declared after this one on purpose — FastAPI matches in
    declaration order and would otherwise treat "resolve" as a trace id."""
    response = client.get(
        "/api/traces/resolve",
        params={"system": "langfuse", "external_id": "nothing-here"},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 404
    assert "correlates" in response.json()["detail"]


def test_trace_detail_carries_links_so_the_dashboard_gets_them_free(client, governed):
    detail = client.get(f"/api/traces/{governed}", headers=as_user("admin@example.com")).json()
    assert detail["links"][0]["system"] == "langfuse"
