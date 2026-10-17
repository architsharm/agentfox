"""What a guard call can report besides the content: cost, and a tool that failed.

Through `/v1/guard/*` the gateway never sees the model call, so a run checked this
way cost $0 and a tool that threw left no trace of it. The Cost and "What breaks"
views were empty for every team integrated this way.
"""

from __future__ import annotations

import pytest

from agentfox.platform.providers.remote import estimate_cost


def test_reported_usage_is_priced_and_adds_up_across_a_run(client):
    body = {"agent": "support-triage", "trace_id": "tr_cost_test"}
    client.post("/v1/guard/input", json={**body, "content": "Where is my order?"})
    client.post(
        "/v1/guard/output",
        json={
            **body,
            "content": "It ships tomorrow.",
            "usage": {"model": "gpt-4o-mini", "input_tokens": 1000, "output_tokens": 500},
        },
    )
    trace = client.get("/api/traces/tr_cost_test").json()["trace"]
    assert trace["cost_usd"] == pytest.approx(estimate_cost("gpt-4o-mini", 1000, 500))
    assert trace["cost_usd"] > 0
    models = client.get("/api/metrics/breakdown?dim=model&range=24h").json()["rows"]
    assert "gpt-4o-mini" in [r["key"] for r in models]

    client.post(
        "/v1/guard/output",
        json={**body, "content": "Anything else?", "usage": {"cost_usd": 0.01}},
    )
    again = client.get("/api/traces/tr_cost_test").json()["trace"]
    assert again["cost_usd"] == pytest.approx(trace["cost_usd"] + 0.01)


def test_a_failed_tool_is_a_failed_step(client):
    response = client.post(
        "/v1/guard/input",
        json={
            "agent": "support-triage",
            "surface": "tool_result",
            "taint_source": "tool_result",
            "content": "An error occurred while running the tool.",
            "tool": "orders.lookup",
            "error": "TimeoutError: orders service did not answer",
        },
    ).json()
    full = client.get(f"/api/traces/{response['trace_id']}").json()
    failed = [s for s in full["spans"] if s["status"] == "error"]
    assert [s["name"] for s in failed] == ["orders.lookup"]
    assert "TimeoutError" in failed[0]["error"]

    errors = client.get("/api/metrics/errors?range=24h").json()["rows"]
    assert any(r["name"] == "orders.lookup" for r in errors)


@pytest.mark.parametrize(
    ("model", "expected_per_million_input"),
    [
        ("gpt-4o-mini-2024-07-18", 0.15),
        ("gpt-4o", 2.50),
        ("openai/gpt-4.1-mini", 0.40),
        ("claude-sonnet-4-5", 3.00),
    ],
)
def test_the_longest_matching_price_wins(model, expected_per_million_input):
    assert estimate_cost(model, 1_000_000, 0) == pytest.approx(expected_per_million_input)


def test_an_unknown_model_costs_nothing():
    assert estimate_cost("some-local-model", 1000, 1000) == 0.0


def test_the_sdk_keeps_the_rules_message_for_a_stopped_tool_call(monkeypatch):
    import httpx

    from agentfox.frameworks.sdk import AgentFox

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "verdict": "block",
                "effective_verdict": "block",
                "reason": "Seats we can assign: your rule",
                "user_message": "That seat can't be assigned online.",
            },
        )

    transport = httpx.MockTransport(handler)
    real_post = httpx.post
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kw: httpx.Client(transport=transport).post(url, **kw),
    )
    fox = AgentFox("airline-cs", base_url="http://gateway.test")
    with fox.session() as s:
        result = s.guard_tool("airline.update_seat", {"new_seat": "1A"}, raise_on_block=False)
    monkeypatch.setattr(httpx, "post", real_post)
    assert result.user_message == "That seat can't be assigned online."
