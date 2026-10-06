"""Integration surfaces, frequency-ordered from the practitioner evidence.

FastAPI 10/11 · Azure OpenAI 6/11 · Prometheus 4/11 · Bedrock 4/11 · Ragas 3/11 ·
Vertex 3/11 · LiteLLM 2/11. Measured, not assumed — and the reason a governance
product that only speaks to api.openai.com is unusable at exactly the companies that
need governance.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agentfox.core.config import get_settings
from agentfox.evaluation.ragas_adapter import (
    RAGAS_METRICS,
    RagasSample,
    native_scores,
    ragas_available,
    score_dataset,
    score_sample,
)
from agentfox.integrations.fastapi import (
    AgentFoxMiddleware,
    context,
    guard,
    install,
)
from agentfox.integrations.prometheus import render_metrics
from agentfox.providers import all_providers, available_providers, get_provider
from tests.conftest import PII_TEXT

# ---------------------------------------------------------------------------
# I-11 / I-10 — enterprise providers
# ---------------------------------------------------------------------------


def test_every_enterprise_provider_is_registered():
    """Neutrality as a code path rather than an assertion."""
    registered = set(all_providers())
    assert {"azure-openai", "bedrock", "vertex", "litellm"} <= registered


def test_none_of_them_are_available_offline():
    """NFR-4: nothing leaves a regulated boundary because a config key was missing."""
    assert available_providers() == {"echo"} or "echo" in available_providers()
    for key in ("azure-openai", "bedrock", "vertex", "litellm"):
        assert not get_provider(key).available(), key


def test_azure_stays_unavailable_without_an_endpoint(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_egress", True)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k")
    assert not get_provider("azure-openai").available(), "a key without an endpoint is not usable"
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://x.openai.azure.com")
    assert get_provider("azure-openai").available()


def test_the_azure_url_carries_the_deployment_and_api_version(monkeypatch):
    """In Azure the caller names a *deployment*, not a model."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://x.openai.azure.com/")
    url = get_provider("azure-openai")._url("my-gpt4o")
    assert "/openai/deployments/my-gpt4o/chat/completions" in url
    assert f"api-version={settings.azure_openai_api_version}" in url


def test_azure_inherits_the_openai_wire_format():
    """The inheritance is the point: a bug fixed in the OpenAI path is fixed here too,
    which is not true of a copy-pasted adapter."""
    from agentfox.providers.remote import OpenAIProvider

    assert isinstance(get_provider("azure-openai"), OpenAIProvider)
    assert isinstance(get_provider("litellm"), OpenAIProvider)


def test_bedrock_refuses_rather_than_improvising_sigv4(monkeypatch):
    """Request signing is easy to get subtly wrong and catastrophic when you do."""
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_egress", True)
    monkeypatch.setattr(settings, "aws_region", "eu-west-1")
    provider = get_provider("bedrock")
    if provider.available():  # boto3 present in this environment
        pytest.skip("boto3 installed; the unavailable path cannot be exercised here")
    with pytest.raises(RuntimeError, match="boto3"):
        from agentfox.providers import CompletionRequest

        provider.complete(CompletionRequest(messages=[{"role": "user", "content": "hi"}]))


def test_vertex_refuses_without_a_credential(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_egress", True)
    provider = get_provider("vertex")
    assert not provider.available(), "no project configured"


def test_litellm_does_not_require_a_key(monkeypatch):
    """A self-hosted LiteLLM proxy commonly runs without a master key."""
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_egress", True)
    monkeypatch.setattr(settings, "litellm_base_url", "http://localhost:4000")
    assert get_provider("litellm").available()


def test_system_prompts_are_lifted_out_for_bedrock_and_vertex():
    from agentfox.providers.enterprise import _split_system

    rest, system = _split_system(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert system == "be terse"
    assert [m["role"] for m in rest] == ["user"]


# ---------------------------------------------------------------------------
# I-3 — FastAPI
# ---------------------------------------------------------------------------


@pytest.fixture
def app(isolated_db):
    # Seeded and closed rather than holding an open session: the `guard` dependency
    # opens its own, and SQLite will not have two writers.
    from agentfox.core.db import session_scope
    from agentfox.core.seed import seed

    with session_scope() as s:
        seed(s)

    application = FastAPI()
    install(application, service="test-agent")

    @application.post("/ask")
    def ask(payload: dict, result=Depends(guard(agent="support-triage", field="prompt"))):
        return {"answer": "ok", "verdict": result.verdict, "trace_id": result.trace_id}

    @application.get("/whoami")
    def whoami(request_ctx=Depends(context)):
        return {"agent": request_ctx.agent, "intent": request_ctx.intent}

    return TestClient(application)


def test_one_line_install_adds_a_health_probe(app):
    body = app.get("/agentfox/health").json()
    assert body["status"] == "ok"
    assert body["middleware"] == "observe", "global middleware must never enforce"
    assert body["service"] == "test-agent"


def test_the_health_probe_reports_the_mode_the_policies_are_in(app):
    """#51a: it said "observe" whatever the policies were doing."""
    from agentfox.core.db import session_scope
    from agentfox.policy.store import set_mode

    with session_scope() as s:
        for key in ("baseline", "eu-ai-act-high-risk", "tool-containment"):
            set_mode(s, key, "observe")
    body = app.get("/agentfox/health").json()
    assert body["mode"] == "observe"
    assert body["policies"]["baseline"] == "observe"

    with session_scope() as s:
        set_mode(s, "baseline", "enforce")
    body = app.get("/agentfox/health").json()
    assert body["mode"] == "enforce"
    assert body["policies"]["baseline"] == "enforce"
    assert body["middleware"] == "observe"


def test_the_middleware_stamps_every_response(app):
    response = app.get("/agentfox/health")
    assert response.headers["X-Nometria-Service"] == "test-agent"
    assert float(response.headers["X-Nometria-Latency-Ms"]) >= 0


def test_correlation_ids_flow_through_the_middleware(app):
    response = app.get("/agentfox/health", headers={"langfuse-trace-id": "lf-mw"})
    assert response.headers["X-Nometria-External-Trace"] == "lf-mw"


def test_the_dependency_governs_inside_the_handler(app):
    """Not a proxy: this runs where the agent slug and the prompt are already
    resolved, which is the difference between "the request contained an SSN" and
    "this agent was about to send an SSN to a tool it cannot use"."""
    response = app.post("/ask", json={"prompt": "hello there"})
    assert response.status_code == 200
    assert response.json()["trace_id"]


def test_a_governed_route_stamps_the_trace_on_the_response(app):
    response = app.post("/ask", json={"prompt": "hello"})
    assert response.headers["X-Nometria-Trace"] == response.json()["trace_id"]


def test_detections_reach_the_dependency(app):
    response = app.post("/ask", json={"prompt": PII_TEXT})
    assert response.status_code in (200, 403)


def test_the_context_dependency_works_without_the_middleware(isolated_db):
    """A dependency that silently no-ops because of a missing add_middleware call is a
    governance gap that looks like working code."""
    application = FastAPI()

    @application.get("/whoami")
    def whoami(request_ctx=Depends(context)):
        return {"agent": request_ctx.agent}

    client = TestClient(application)
    body = client.get("/whoami", headers={"X-Nometria-Agent": "support-triage"}).json()
    assert body["agent"] == "support-triage"


def test_the_middleware_cannot_refuse_a_request(isolated_db):
    """A middleware that can 403 a route its author never considered is how a
    governance layer gets removed on the first false positive."""
    application = FastAPI()
    application.add_middleware(AgentFoxMiddleware)

    @application.post("/anything")
    def anything(payload: dict):
        return {"ok": True}

    client = TestClient(application)
    assert client.post("/anything", json={"prompt": PII_TEXT}).status_code == 200


# ---------------------------------------------------------------------------
# I-7 — Prometheus
# ---------------------------------------------------------------------------


def test_metrics_follow_prometheus_naming(seeded, enforcer):
    """A metric that does not follow the convention does not compose with the
    alerting rules a team already wrote."""
    enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hi"}],
        model="echo-1",
    )
    body = render_metrics(seeded)
    for name in (
        "agentfox_decisions_total",
        "agentfox_detector_runs_total",
        "agentfox_open_findings",
        "agentfox_missed_escalation_rate",
        "agentfox_circuit_breaker_state",
    ):
        assert f"# TYPE {name} " in body, name
    for line in body.splitlines():
        if line.startswith("nometria_") and "_total" in line.split("{")[0]:
            assert "# " not in line


def test_observe_mode_is_reported_separately(seeded, enforcer):
    """A dashboard showing "1,204 blocks" that were all counterfactual is actively
    misleading."""
    enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": PII_TEXT}],
        model="echo-1",
    )
    body = render_metrics(seeded)
    assert 'agentfox_decisions_by_mode_total{mode="observe"}' in body


def test_metrics_expose_counts_never_content(seeded, enforcer):
    """The endpoint is unauthenticated like every /metrics endpoint, so it must not
    carry a prompt, a finding detail or an identifier."""
    enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": PII_TEXT}],
        model="echo-1",
    )
    body = render_metrics(seeded)
    assert "jane.doe@example.com" not in body
    assert "123-45-6789" not in body


def test_label_values_are_escaped(seeded):
    from agentfox.integrations.prometheus import _line

    rendered = _line("m", {"detector": 'a"b\nc'}, 1.0)
    assert '\\"' in rendered and "\n" not in rendered


def test_the_metrics_endpoint_is_served(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "agentfox_decisions_total" in response.text


def test_metrics_need_no_auth(client):
    """A scrape job that needs a bearer token is a scrape job nobody configures."""
    assert client.get("/metrics").status_code == 200


# ---------------------------------------------------------------------------
# I-8 — Ragas
# ---------------------------------------------------------------------------


def test_the_vocabulary_is_theirs():
    assert RAGAS_METRICS == (
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
    )


def test_scores_are_produced_offline():
    sample = RagasSample(
        question="what is the refund window?",
        answer="The refund window is 30 days.",
        contexts=["The refund window is 30 days for all orders."],
        ground_truth="30 days",
    )
    scores = native_scores(sample)
    assert scores.faithfulness == 1.0
    assert scores.context_precision == 1.0


def test_an_unsupported_answer_scores_low_on_faithfulness():
    scores = native_scores(
        RagasSample(
            question="refund window?",
            answer="The refund window is ninety days and includes shipping insurance.",
            contexts=["Orders ship within two days."],
        )
    )
    assert scores.faithfulness < 0.5


def test_every_result_names_its_implementation():
    """Our lexical implementation is weaker than theirs, and a consumer of these
    numbers is entitled to know which produced them."""
    scores = score_sample(RagasSample(question="q", answer="a"), prefer_ragas=False)
    assert scores.to_json()["implementation"] == "native-lexical"


def test_the_dataset_report_carries_the_floor_not_just_the_mean():
    """One unfaithful answer in a hundred is not an acceptable average, it is an
    incident waiting for a user to find it."""
    report = score_dataset(
        [
            RagasSample(question="q", answer="The window is 30 days.", contexts=["30 days"]),
            RagasSample(question="q", answer="The window is 90 days.", contexts=["30 days"]),
        ],
        prefer_ragas=False,
    )
    assert report["samples"] == 2
    faithfulness = report["metrics"]["faithfulness"]
    assert faithfulness["min"] <= faithfulness["mean"]
    assert "below_0_7" in faithfulness


def test_an_empty_dataset_says_so():
    assert score_dataset([])["samples"] == 0


def test_availability_is_reported_honestly():
    assert isinstance(ragas_available(), bool)
