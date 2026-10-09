"""The two Tier-0 rows the gap analysis admits are stub-only: 0.4 and 0.7.

Both modules were real and individually tested; neither had a caller on the live
request path. `tests/runtime/test_platform_runtime.py` already proves `agent_loop` scores a
run correctly and `tests/runtime/test_availability.py` already proves `FailPolicy` and
`DegradationLedger` behave. Nothing here re-tests either algorithm. These tests are
about the *wiring* specifically — that a real request through the real FastAPI app
reaches them — which is the thing that was missing.
"""

from __future__ import annotations

import json

import pytest

from agentfox.core.config import reset_settings_cache
from agentfox.runtime.availability import (
    DATABASE,
    DETECTOR_PIPELINE,
    MODEL_PROVIDER,
    get_degradation_ledger,
    reset_degradation_ledger,
)
from tests.conftest import as_user

AGENT = {"X-AgentFox-Agent": "support-triage"}


@pytest.fixture(autouse=True)
def _clean_ledger():
    """The ledger and probe cache are process-level singletons, like the admission
    controller. Without this, one test's recorded outage is another test's mystery."""
    reset_degradation_ledger()
    yield
    reset_degradation_ledger()


def _with(session: str | None = None, **extra) -> dict[str, str]:
    headers = {**AGENT, **extra}
    if session:
        headers["X-AgentFox-Session"] = session
    return headers


def _openai_loop(pairs) -> list[dict]:
    """A conversation carrying a completed tool loop, in OpenAI wire shape."""
    messages: list[dict] = [{"role": "user", "content": "Find the customer's order."}]
    for index, (tool, arguments, observation) in enumerate(pairs):
        call_id = f"call_{index}"
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool, "arguments": json.dumps(arguments)},
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": call_id, "content": observation})
    return messages


# --- 0.4: loop governance across the proxy's tool loop ---------------------


def test_a_repeating_tool_call_loop_through_the_proxy_is_stopped(client):
    """The gap in one test: an agent re-issuing an identical call forever through the
    drop-in proxy. Every individual request looks reasonable, which is exactly why
    per-call enforcement never saw it."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": _openai_loop([("crm.lookup", {"id": 1}, "still pending")] * 4),
        },
        headers=_with("sess-repeat"),
    )
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["type"] == "agentfox_policy_violation", "reuses the policy-block shape"
    assert error["rules_fired"][0]["rule_id"] == "loop.runaway"
    assert "identical arguments" in error["message"]
    assert error["trace_id"], "a refusal without an auditable reason is not allowed (X-4)"
    assert response.headers["X-AgentFox-Verdict"] == "block"


def test_an_alternating_cycle_is_stopped_where_per_tool_counting_cannot_see_it(client):
    """A-B-A-B: neither tool repeats consecutively, so the pre-existing per-tool
    repeat counter in `_budget_state` misses it entirely."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": _openai_loop(
                [(tool, {"n": i}, i) for i, tool in enumerate(["a", "b", "a", "b", "a", "b"])]
            ),
        },
        headers=_with("sess-cycle"),
    )
    assert response.status_code == 403
    assert "repeating" in response.json()["error"]["message"]


def test_the_anthropic_shape_is_governed_too(client):
    """`tool_use`/`tool_result` content blocks, not `tool_calls` — a loop must not
    escape by being on the other supported protocol."""
    messages: list[dict] = [{"role": "user", "content": "Find it."}]
    for index in range(4):
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"t{index}",
                        "name": "crm.lookup",
                        "input": {"id": 1},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": f"t{index}", "content": "pending"}
                ],
            }
        )
    response = client.post(
        "/v1/messages",
        json={"model": "echo-1", "max_tokens": 64, "messages": messages},
        headers=_with("sess-anthropic"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["rules_fired"][0]["rule_id"] == "loop.runaway"


def test_a_stopped_loop_is_recorded_as_a_finding(client):
    """A stop that leaves no trace is indistinguishable from the agent giving up."""
    client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": _openai_loop([("crm.lookup", {"id": 1}, "pending")] * 4),
        },
        headers=_with("sess-recorded"),
    )
    findings = client.get("/api/findings", headers=as_user("admin@example.com")).json()
    rows = findings if isinstance(findings, list) else findings.get("findings", [])
    assert any(f.get("type") == "agent_loop_stopped" for f in rows), rows


def test_a_normal_multi_step_loop_under_the_limit_is_not_stopped(client):
    """The false-positive floor, and the one that decides whether this ships: an
    agent doing several different useful things is an agent working."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": _openai_loop([(f"tool.{i}", {"i": i}, f"result {i}") for i in range(6)]),
        },
        headers=_with("sess-progress"),
    )
    assert response.status_code == 200
    assert response.headers["X-AgentFox-Verdict"] == "allow"


def test_the_same_tool_with_different_arguments_is_progress_not_a_loop(client):
    """Paging through results calls one tool repeatedly and is not a runaway."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": _openai_loop([("search", {"page": i}, f"page {i}") for i in range(5)]),
        },
        headers=_with("sess-paging"),
    )
    assert response.status_code == 200


def test_a_request_with_no_session_is_unaffected(client):
    """No correlation key means no attribution, and guessing one would let a run be
    scored against traffic that is not its own. The default has to be untouched."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": _openai_loop([("crm.lookup", {"id": 1}, "pending")] * 6),
        },
        headers=AGENT,
    )
    assert response.status_code == 200


def test_an_ordinary_single_turn_chat_is_untouched(client):
    """No tool calls at all — the overwhelmingly common request shape."""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hello"}]},
        headers=_with("sess-plain"),
    )
    assert response.status_code == 200


def test_the_configured_limit_is_what_decides(client, monkeypatch):
    """The budget is `AGENTFOX_LOOP_*`, not a constant compiled into the route."""
    monkeypatch.setenv("AGENTFOX_LOOP_MAX_REPEATS", "99")
    reset_settings_cache()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": _openai_loop([("crm.lookup", {"id": 1}, "pending")] * 4),
        },
        headers=_with("sess-budget"),
    )
    assert response.status_code == 200, "raising the repeat budget must raise the limit"


def test_a_malformed_tool_call_never_breaks_the_caller(client):
    """A body that is not a recognisable tool loop must not manufacture one, and must
    not 500 either."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": "not-a-list"},
                {"role": "assistant", "tool_calls": [{"nonsense": True}]},
            ],
        },
        headers=_with("sess-malformed"),
    )
    assert response.status_code == 200


# --- 0.7: service-level degradation ----------------------------------------


def _break_detector_pipeline(monkeypatch) -> None:
    """A real probe firing on real configuration: every enabled detector missing
    means the pipeline as a whole has nothing to run."""
    monkeypatch.delenv("AGENTFOX_ENABLED_DETECTORS", raising=False)
    monkeypatch.setenv("AGENTFOX_ENABLED_DETECTORS", '["nope.does_not_exist"]')
    reset_settings_cache()
    reset_degradation_ledger()


def test_a_degraded_dependency_fails_open_and_is_recorded(client, monkeypatch):
    """Fail-open is legitimate — but the request must be recorded, and the caller
    must be told, or a control that is down is indistinguishable from one that works.
    """
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "open")
    _break_detector_pipeline(monkeypatch)

    response = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert response.status_code == 200, "fail open keeps the customer's agent working"
    assert response.headers["X-AgentFox-Degraded"] == DETECTOR_PIPELINE
    assert get_degradation_ledger().history(DETECTOR_PIPELINE), "the record is the point"


def test_a_degraded_dependency_fails_closed_when_declared_closed(client, monkeypatch):
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "closed")
    _break_detector_pipeline(monkeypatch)

    response = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["type"] == "agentfox_service_degraded"
    assert error["service"] == DETECTOR_PIPELINE
    assert error["fail_mode"] == "closed"
    assert "fail-closed" in error["message"]


def test_fail_open_converts_to_closed_once_it_covers_too_much_traffic(client, monkeypatch):
    """Bounded, not indefinite. A control open across a whole window is not degraded,
    it is absent, and the system should stop pretending otherwise."""
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "open")
    _break_detector_pipeline(monkeypatch)

    first = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert first.status_code == 200
    later = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert later.status_code == 503, "past its share of the window, open becomes closed"
    assert later.json()["error"]["escalated"] is True


def test_a_degraded_control_is_visible_to_an_operator_on_the_api(client, monkeypatch):
    """Without reading logs. `/api/health` still reports status ok — the process is
    up — but a fail-open system reports success while checking nothing, so the 200
    alone cannot distinguish a working control from an absent one."""
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "open")
    _break_detector_pipeline(monkeypatch)

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["governance_healthy"] is False
    assert DETECTOR_PIPELINE in health["degradation"]["unavailable"]

    reliability = client.get("/api/reliability", headers=as_user("admin@example.com")).json()
    assert reliability["fail_mode"] == "open"
    assert DETECTOR_PIPELINE in reliability["degradation"]["unavailable"]


def test_a_healthy_deployment_reports_every_service_up(client):
    """The false-positive floor for 0.7: the default deployment must not report
    itself degraded, or the signal is worthless."""
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["governance_healthy"] is True
    assert health["degradation"]["unavailable"] == {}
    assert set(health["degradation"]["services"]) >= {
        DETECTOR_PIPELINE,
        DATABASE,
        MODEL_PROVIDER,
    }


def test_reading_the_status_view_does_not_change_it(client, monkeypatch):
    """An earlier version recorded what it probed, so opening the dashboard pushed a
    fail-open control towards its budget. A status view that changes the system by
    being read is worse than none."""
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "open")
    _break_detector_pipeline(monkeypatch)

    for _ in range(5):
        client.get("/api/health")
    assert get_degradation_ledger().history(DETECTOR_PIPELINE) == []

    served = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert served.status_code == 200, "five dashboard reads must not have spent the budget"


def test_the_ledger_failing_never_raises_into_the_caller(client, monkeypatch):
    """The whole argument for permitting fail-open is that it is recorded. A recorder
    that takes the request down with it has turned a degradation into an outage."""
    import agentfox.runtime.availability as availability

    def explode(*args, **kwargs):
        raise RuntimeError("the ledger itself is broken")

    monkeypatch.setattr(availability, "get_degradation_ledger", explode)
    monkeypatch.setattr(availability, "probe_services", explode)

    response = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert response.status_code == 200

    health = client.get("/api/health")
    assert health.status_code == 200, "a status view must not 500 either"


def test_a_probe_that_throws_is_evidence_not_a_500(client, monkeypatch):
    """An unreachable database raises out of the probe rather than returning a
    string. That is a degradation, not a bug to propagate."""
    import agentfox.runtime.availability as availability

    def explode() -> str:
        raise RuntimeError("connection refused")

    monkeypatch.setitem(availability._PROBES, DATABASE, explode)
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "closed")
    reset_settings_cache()
    reset_degradation_ledger()

    response = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert response.status_code == 503
    assert response.json()["error"]["service"] == DATABASE
    assert "connection refused" in response.json()["error"]["detail"]


def test_the_control_plane_is_not_locked_out_by_the_outage(client, monkeypatch):
    """An operator diagnosing a degradation must be able to reach the endpoint that
    describes it — the same reasoning that scopes the admission gate to `/v1/*`."""
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "closed")
    _break_detector_pipeline(monkeypatch)

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/reliability", headers=as_user("admin@example.com")).status_code == 200


def test_a_provider_outage_does_not_stop_guard_checks(client, monkeypatch):
    """Guard routes never call the model. Teams that call their provider themselves
    still get their traffic checked when the gateway's own provider is down."""
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "closed")
    monkeypatch.setenv("AGENTFOX_DEFAULT_PROVIDER", "openai")
    monkeypatch.setenv("AGENTFOX_ALLOW_EGRESS", "false")
    reset_settings_cache()
    reset_degradation_ledger()

    guard = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
    assert guard.status_code == 200
    proxied = client.post(
        "/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert proxied.status_code == 503
    assert proxied.json()["error"]["service"] == "model_provider"
