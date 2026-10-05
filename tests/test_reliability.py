"""P15 — circuit breaker, fallback ladder, budgets.

Evidence: 5 of 11 senior engineers built this by hand. It sits at the same
interception point as enforcement, which is why it lives in the same request path
rather than in a separate gateway.
"""

from __future__ import annotations

import time

import pytest

from agentfox.runtime.enforcement import ProviderUnavailable
from agentfox.core.models import Budget, Finding
from agentfox.providers import CompletionRequest, CompletionResponse, register_provider
from agentfox.runtime.reliability import (
    BREAKER,
    CLOSED,
    HALF_OPEN,
    OPEN,
    CircuitBreaker,
    FallbackLadder,
    charge,
    check_budget,
)


@pytest.fixture(autouse=True)
def _clean_breaker():
    BREAKER.reset()
    yield
    BREAKER.reset()


# ---------------------------------------------------------------------------
# Circuit breaker (P15-1)
# ---------------------------------------------------------------------------


def test_breaker_opens_after_the_threshold():
    breaker = CircuitBreaker(failure_threshold=3)
    for _ in range(2):
        breaker.record_failure("openai")
    assert breaker.state_of("openai") == CLOSED, "must not trip early"
    breaker.record_failure("openai")
    assert breaker.state_of("openai") == OPEN
    assert not breaker.allows("openai")


def test_open_breaker_fails_fast():
    """The point: a provider incident must not become our own outage by making every
    request wait out a timeout (NFR-2)."""
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure("openai")
    started = time.perf_counter()
    allowed = breaker.allows("openai")
    assert not allowed
    assert (time.perf_counter() - started) < 0.01


def test_breaker_probes_before_fully_reopening():
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=0.01, half_open_successes=2)
    breaker.record_failure("openai")
    time.sleep(0.02)
    assert breaker.state_of("openai") == HALF_OPEN
    assert breaker.allows("openai"), "half-open must permit a probe"
    breaker.record_success("openai")
    assert breaker.state_of("openai") == HALF_OPEN, "one success is not recovery"
    breaker.record_success("openai")
    assert breaker.state_of("openai") == CLOSED


def test_a_failed_probe_reopens_immediately():
    """One bad recovery must not re-flood a still-degraded provider."""
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=0.01)
    breaker.record_failure("openai")
    time.sleep(0.02)
    assert breaker.state_of("openai") == HALF_OPEN
    breaker.record_failure("openai")
    assert breaker.state_of("openai") == OPEN


def test_breaker_is_per_provider():
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure("openai:gpt-4o")
    assert not breaker.allows("openai:gpt-4o")
    assert breaker.allows("anthropic:claude-sonnet-4"), "one provider must not trip another"


# ---------------------------------------------------------------------------
# Fallback ladder (P15-2)
# ---------------------------------------------------------------------------


def test_ladder_parses_provider_model_pairs():
    ladder = FallbackLadder.parse(["openai:gpt-4o", "echo:echo-1"])
    assert [(r.provider, r.model) for r in ladder.rungs] == [
        ("openai", "gpt-4o"),
        ("echo", "echo-1"),
    ]


def test_fallback_serves_from_the_next_rung_when_the_first_fails(seeded, enforcer, monkeypatch):
    class BrokenProvider:
        key = "broken"

        def available(self):
            return True

        def supports_native_streaming(self):
            return False

        def complete(self, request):
            raise RuntimeError("provider is down")

        def stream(self, request):
            raise RuntimeError("provider is down")

        def judge(self, output, rubric, model="default"):
            return {"score": 0.0}

    register_provider(BrokenProvider())
    monkeypatch.setattr(enforcer.settings, "fallback_chain", ["echo:echo-1"])

    response, provider, record = enforcer.call_provider(
        CompletionRequest(messages=[{"role": "user", "content": "hi"}]),
        provider="broken",
        model="broken-1",
    )
    assert isinstance(response, CompletionResponse)
    assert record.degraded, "serving from a lower rung is a degradation, and must be recorded"
    assert record.served_by == "echo:echo-1"
    assert record.attempts[0].ok is False


def test_exhausting_the_ladder_raises_rather_than_returning_nothing(seeded, enforcer, monkeypatch):
    class AlwaysBroken:
        key = "alwaysbroken"

        def available(self):
            return True

        def supports_native_streaming(self):
            return False

        def complete(self, request):
            raise RuntimeError("down")

        def stream(self, request):
            raise RuntimeError("down")

        def judge(self, output, rubric, model="default"):
            return {"score": 0.0}

    register_provider(AlwaysBroken())
    monkeypatch.setattr(enforcer.settings, "fallback_chain", [])
    with pytest.raises(ProviderUnavailable):
        enforcer.call_provider(
            CompletionRequest(messages=[{"role": "user", "content": "hi"}]),
            provider="alwaysbroken",
            model="x",
        )


def test_no_fallback_configured_means_fail_rather_than_substitute(seeded, enforcer):
    """Empty ladder is a deliberate default: silently serving from a different model
    than the agent was evaluated against invalidates the baseline."""
    assert enforcer.settings.fallback_chain == []


# ---------------------------------------------------------------------------
# Budgets (P15-3, P15-5)
# ---------------------------------------------------------------------------


def test_budget_within_limits_is_not_exceeded(seeded):
    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    assert not check_budget(seeded, "agent", agent.id).exceeded


def test_budget_exceeded_on_calls(seeded):
    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    budget = seeded.query(Budget).filter_by(scope_id=agent.id).one()
    budget.max_calls = 2
    budget.calls = 2
    seeded.flush()

    verdict = check_budget(seeded, "agent", agent.id)
    assert verdict.exceeded
    assert verdict.dimensions == ["calls"]
    assert "2/2" in verdict.reason


def test_budget_blocks_before_the_model_call(seeded, enforcer):
    """A hard cap checked after the spend is not a cap."""
    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    budget = seeded.query(Budget).filter_by(scope_id=agent.id).one()
    budget.max_cost_usd = 0.0
    budget.cost_usd = 1.0
    seeded.flush()

    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hi"}],
        model="echo-1",
    )
    assert result.blocked
    assert response is None
    assert result.rules_fired[0]["rule_id"] == "budget.exhausted"


def test_budget_breach_raises_a_finding_and_an_audit_entry(seeded, enforcer):
    """A breach is a governed event, not an HTTP 429 in a load-balancer log."""
    from agentfox.core.models import Agent, AuditEntry

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    budget = seeded.query(Budget).filter_by(scope_id=agent.id).one()
    budget.max_calls = 0
    seeded.flush()

    enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hi"}],
        model="echo-1",
    )
    assert seeded.query(Finding).filter_by(type="budget_exhausted").count() == 1
    assert seeded.query(AuditEntry).filter_by(action="budget.exhausted").count() == 1


def test_budget_findings_are_deduplicated_per_window(seeded, enforcer):
    """An exhausted agent must not generate a finding per request."""
    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    budget = seeded.query(Budget).filter_by(scope_id=agent.id).one()
    budget.max_calls = 0
    seeded.flush()

    for _ in range(3):
        enforcer.run_completion(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "hi"}],
            model="echo-1",
        )
    assert seeded.query(Finding).filter_by(type="budget_exhausted").count() == 1


def test_budget_blocks_the_streaming_path_too(seeded, enforcer):
    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    budget = seeded.query(Budget).filter_by(scope_id=agent.id).one()
    budget.max_calls = 0
    seeded.flush()

    events = list(
        enforcer.run_completion_stream(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "hi"}],
            model="echo-1",
        )
    )
    assert [e.kind for e in events] == ["blocked"]


def test_charge_accumulates_and_the_window_rolls(seeded):
    import datetime as dt

    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    charge(seeded, "agent", agent.id, calls=1, tokens=100, cost_usd=0.5)
    budget = seeded.query(Budget).filter_by(scope_id=agent.id).one()
    assert budget.calls == 1 and budget.tokens == 100

    budget.window_started_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    seeded.flush()
    charge(seeded, "agent", agent.id, calls=1)
    assert budget.calls == 1, "counters reset when the window rolls"
    assert budget.tokens == 0


def test_normal_traffic_records_which_provider_served_it(seeded, enforcer):
    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hi"}],
        model="echo-1",
    )
    assert response is not None
    degradation = result.taint.get("degradation") or {}
    if degradation:
        assert degradation["served_by"] == "echo:echo-1"
        assert degradation["degraded"] is False


# ---------------------------------------------------------------------------
# Operator surface (P15-4)
# ---------------------------------------------------------------------------


def test_reliability_endpoint_exposes_breaker_and_budget_state(client):
    from tests.conftest import as_user

    BREAKER.record_failure("openai:gpt-4o")
    response = client.get("/api/reliability", headers=as_user("admin@example.com"))
    assert response.status_code == 200
    body = response.json()
    assert "openai:gpt-4o" in body["circuit_breakers"]
    assert body["fallback_chain"] == []
    assert any(b["agent"] == "support-triage" for b in body["budgets"])
