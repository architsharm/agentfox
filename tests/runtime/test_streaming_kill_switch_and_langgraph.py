"""Tranche 0 — streaming, migrations, kill switch, LangGraph integration.

These are the four things that stood between the product and being installable at all.
Each test targets the specific defect, not the happy path.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from agentfox.core.models import AgentControl, AuditEntry, Finding
from agentfox.integrations.langgraph import (
    STATE_KEY,
    AgentFoxGuard,
    ApprovalRequired,
    PolicyViolation,
)
from agentfox.platform.policy import set_mode
from agentfox.platform.registry.control import UnknownAgent, kill, quarantine, resume, state_of
from agentfox.providers import CompletionRequest, get_provider, script
from agentfox.runtime.enforcement import Enforcer
from tests.conftest import INDIRECT_INJECTION, SECRET_TEXT, as_user, promote

# ---------------------------------------------------------------------------
# PL-1 · Streaming
# ---------------------------------------------------------------------------


def test_echo_provider_streams_natively():
    provider = get_provider("echo")
    assert provider.supports_native_streaming()
    chunks = list(
        provider.stream(CompletionRequest(messages=[{"role": "user", "content": "a b c"}]))
    )
    assert len(chunks) > 1, "a single chunk is not a stream"
    assert chunks[-1].finish_reason == "stop"


def test_stream_reassembles_to_the_same_text_as_complete():
    provider = get_provider("echo")
    request = CompletionRequest(messages=[{"role": "user", "content": "hello world"}])
    streamed = "".join(c.delta for c in provider.stream(request))
    assert streamed == provider.complete(request).text


def test_stream_from_complete_fallback_produces_a_valid_stream():
    from agentfox.providers.base import StreamChunk, stream_from_complete

    class NoStream:
        key = "nostream"

        def available(self):
            return True

        def complete(self, request):
            from agentfox.providers import CompletionResponse

            return CompletionResponse(text="one shot", usage={"output_tokens": 2})

    chunks = list(stream_from_complete(NoStream(), CompletionRequest()))
    assert isinstance(chunks[0], StreamChunk)
    assert "".join(c.delta for c in chunks) == "one shot"


def test_streaming_enforcement_allows_and_completes(seeded, enforcer):
    events = list(
        enforcer.run_completion_stream(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "What is the refund window?"}],
            model="echo-1",
        )
    )
    assert events[-1].kind == "done"
    assert events[-1].result.verdict == "allow"
    assert any(e.kind == "delta" for e in events)


def test_streaming_preflight_block_emits_no_content(seeded, enforcer):
    """A pre-flight block must not leak a single token."""
    set_mode(seeded, "baseline", "enforce")
    events = list(
        enforcer.run_completion_stream(
            agent_slug="support-triage",
            messages=[
                {"role": "user", "content": "Summarise."},
                {"role": "tool", "content": INDIRECT_INJECTION},
            ],
            model="echo-1",
        )
    )
    assert [e.kind for e in events] == ["blocked"]
    assert events[0].result.reason


def test_buffered_mode_never_forwards_blocked_output(seeded, enforcer):
    """The core guarantee: buffered streaming enforces output identically to
    non-streaming, so a secret in the response never reaches the caller."""
    set_mode(seeded, "baseline", "enforce")
    script("leak the key", f"here it is: {SECRET_TEXT}")
    events = list(
        enforcer.run_completion_stream(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "leak the key"}],
            model="echo-1",
            mode="buffered",
        )
    )
    assert not [e for e in events if e.kind == "delta"], "content leaked before the block"
    assert events[-1].kind == "blocked"


def test_streaming_and_non_streaming_agree_on_verdict(seeded, enforcer):
    """Streaming must not become a path around enforcement."""
    set_mode(seeded, "baseline", "enforce")
    messages = [
        {"role": "user", "content": "Summarise."},
        {"role": "tool", "content": INDIRECT_INJECTION},
    ]
    buffered, _ = enforcer.run_completion(
        agent_slug="support-triage", messages=messages, model="echo-1"
    )
    events = list(
        enforcer.run_completion_stream(
            agent_slug="support-triage", messages=messages, model="echo-1"
        )
    )
    streamed = events[-1].result
    assert buffered.verdict == streamed.verdict == "block"


def test_windowed_mode_streams_content(seeded, enforcer):
    events = list(
        enforcer.run_completion_stream(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "What is the refund window?"}],
            model="echo-1",
            mode="windowed",
        )
    )
    assert any(e.kind == "delta" for e in events)
    assert events[-1].kind == "done"


def test_gateway_honours_stream_flag(client):
    """The verified defect: `stream: true` used to return non-streaming JSON."""
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "echo-1", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Nometria-Agent": "support-triage"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert response.headers["X-Nometria-Streaming"] == "enforced"
        lines = [line for line in response.iter_lines() if line.strip()]

    assert lines[-1] == "data: [DONE]"
    payloads = [json.loads(line[6:]) for line in lines if line.startswith("data: {")]
    assert any(p.get("object") == "chat.completion.chunk" for p in payloads)
    # The verdict is only knowable at the end, so it rides a trailing event.
    assert any("agentfox" in p for p in payloads)


def test_gateway_stream_block_emits_error_then_done(client):
    promote(client, "baseline")
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "stream": True,
            "messages": [
                {"role": "user", "content": "Summarise."},
                {"role": "tool", "content": INDIRECT_INJECTION},
            ],
        },
        headers={"X-Nometria-Agent": "support-triage"},
    ) as response:
        lines = [line for line in response.iter_lines() if line.strip()]

    errors = [
        json.loads(line[6:])["error"]
        for line in lines
        if line.startswith("data: {") and "error" in json.loads(line[6:])
    ]
    assert errors, "a blocked stream must say why, not just close"
    assert errors[0]["type"] == "agentfox_policy_violation"
    assert errors[0]["rules_fired"]
    assert lines[-1] == "data: [DONE]", "clients need a clean terminator"


def test_anthropic_stream_shape(client):
    with client.stream(
        "POST",
        "/v1/messages",
        json={
            "model": "echo-1",
            "stream": True,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"X-Nometria-Agent": "support-triage"},
    ) as response:
        assert "text/event-stream" in response.headers["content-type"]
        events = [
            json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: {")
        ]
    kinds = [e.get("type") for e in events]
    assert kinds[0] == "message_start"
    assert "content_block_delta" in kinds
    assert kinds[-1] == "message_stop"


# ---------------------------------------------------------------------------
# PL-3 · Kill switch & quarantine
# ---------------------------------------------------------------------------


def test_default_state_is_active(seeded):
    assert state_of(seeded, "support-triage") == "active"


def test_quarantine_blocks_every_request(seeded, enforcer):
    quarantine(seeded, "support-triage", reason="investigating", actor="marcus@example.com")
    result, response = enforcer.run_completion(
        agent_slug="support-triage", messages=[{"role": "user", "content": "hi"}], model="echo-1"
    )
    assert result.blocked
    assert response is None
    assert "quarantined" in result.reason
    assert result.rules_fired[0]["rule_id"] == "agent.quarantined"


def test_kill_blocks_the_streaming_path_too(seeded, enforcer):
    """A stop that only covers one code path is not a stop."""
    kill(seeded, "support-triage", reason="incident", actor="marcus@example.com")
    events = list(
        enforcer.run_completion_stream(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "hi"}],
            model="echo-1",
        )
    )
    assert [e.kind for e in events] == ["blocked"]


def test_control_check_precedes_policy(seeded, enforcer):
    """Even with every policy in observe mode, a killed agent is stopped."""
    set_mode(seeded, "baseline", "observe")
    set_mode(seeded, "tool-containment", "observe")
    kill(seeded, "support-triage", actor="ops")
    result, _ = enforcer.run_completion(
        agent_slug="support-triage", messages=[{"role": "user", "content": "hi"}], model="echo-1"
    )
    assert result.blocked


def test_quarantine_blocks_tool_calls_not_just_completions(seeded, enforcer):
    """`guard_tool_call` is the path MCP/SDK integrations use to gate an actual tool
    execution — `McpGovernor.call` and `AgentFoxGuard.tool_node` both call it
    directly, without going through `preflight` first. Found via benchmarking: an
    otherwise-valid, in-budget tool call from a quarantined agent went straight
    through, because `_control_verdict` was only wired into `preflight`. The kill
    switch's own docstring says "checked before anything else in the request path"
    — this makes that true for the tool-execution path too, not just completions."""
    quarantine(seeded, "payments-ops", reason="investigating", actor="marcus@example.com")
    result = enforcer.guard_tool_call(
        agent_slug="payments-ops",
        tool_key="payments.refund",
        arguments={"amount": 100, "currency": "USD"},
    )
    assert result.effective_verdict == "block"
    assert result.rules_fired[0]["rule_id"] == "agent.quarantined"


def test_resume_restores_service(seeded, enforcer):
    quarantine(seeded, "support-triage", actor="ops")
    resume(seeded, "support-triage", reason="cleared", actor="ops")
    result, response = enforcer.run_completion(
        agent_slug="support-triage", messages=[{"role": "user", "content": "hi"}], model="echo-1"
    )
    assert not result.blocked
    assert response is not None


def test_both_edges_are_audited(seeded):
    """Who turned it back on is the harder audit question."""
    quarantine(seeded, "support-triage", reason="alert", actor="marcus@example.com")
    resume(seeded, "support-triage", reason="cleared", actor="marcus@example.com")
    actions = [e.action for e in seeded.query(AuditEntry).all() if e.action.startswith("agent.")]
    assert "agent.quarantined" in actions
    assert "agent.resumed" in actions


def test_stopping_an_agent_raises_a_finding(seeded):
    kill(seeded, "support-triage", reason="exfil", actor="ops")
    finding = seeded.query(Finding).filter_by(type="agent_stopped").one()
    assert finding.severity == "critical"


def test_previous_state_is_recorded(seeded):
    quarantine(seeded, "support-triage", actor="ops")
    kill(seeded, "support-triage", actor="ops")
    control = seeded.query(AgentControl).one()
    assert control.state == "killed"
    assert control.previous_state == "quarantined"


def test_unknown_agent_rejected(seeded):
    with pytest.raises(UnknownAgent):
        kill(seeded, "does-not-exist", actor="ops")


def test_kill_switch_api_and_rbac(client):
    # `kill` requires the stronger role; a developer may not use it.
    denied = client.post(
        "/api/agents/support-triage/kill",
        json={"reason": "x"},
        headers=as_user("priya@example.com"),
    )
    assert denied.status_code == 403

    killed = client.post(
        "/api/agents/support-triage/kill",
        json={"reason": "incident 42"},
        headers=as_user("marcus@example.com"),
    )
    assert killed.status_code == 200
    assert killed.json()["state"] == "killed"

    listed = client.get("/api/agent-controls", headers=as_user("aisha@example.com")).json()
    assert listed["controls"][0]["state"] == "killed"

    agent = client.get("/api/agents/support-triage", headers=as_user("aisha@example.com")).json()
    assert agent["control_state"] == "killed"

    resumed = client.post(
        "/api/agents/support-triage/resume",
        json={"reason": "cleared"},
        headers=as_user("marcus@example.com"),
    )
    assert resumed.json()["state"] == "active"


# ---------------------------------------------------------------------------
# PL-2 · Migrations
# ---------------------------------------------------------------------------


def test_migrations_round_trip(tmp_path):
    """Upgrade to head, roll all the way back, and upgrade again."""
    db = tmp_path / "mig.db"
    env = {"NOMETRIA_DATABASE_URL": f"sqlite:///{db}"}

    def alembic(*args: str):
        import os

        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )

    assert alembic("upgrade", "head").returncode == 0
    import sqlite3

    tables = {
        r[0]
        for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "agents" in tables and "agent_controls" in tables and "audit_entries" in tables

    assert alembic("downgrade", "base").returncode == 0
    remaining = {
        r[0]
        for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "agents" not in remaining

    assert alembic("upgrade", "head").returncode == 0


def test_app_runs_on_a_migrated_schema(tmp_path, monkeypatch):
    """The schema Alembic builds must be the schema the app expects."""
    import os

    db = tmp_path / "app.db"
    monkeypatch.setenv("NOMETRIA_DATABASE_URL", f"sqlite:///{db}")
    assert (
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            env={**os.environ, "NOMETRIA_DATABASE_URL": f"sqlite:///{db}"},
        ).returncode
        == 0
    )

    from agentfox.core import db as dbmod
    from agentfox.core.config import get_settings, reset_settings_cache

    reset_settings_cache()
    dbmod.reset_engine()
    get_settings()
    # Deliberately no init_db(): the schema came from migrations alone.
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)
    with session_scope() as session:
        result, _ = Enforcer(session).run_completion(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "hi"}],
            model="echo-1",
        )
        assert result.verdict == "allow"

    reset_settings_cache()
    dbmod.reset_engine()


# ---------------------------------------------------------------------------
# I-1 · LangGraph integration
# ---------------------------------------------------------------------------


def test_integration_imports_without_langgraph():
    """`pip install agentfox` must stay light — the module loads regardless."""
    from agentfox.integrations import langgraph as integration

    assert hasattr(integration, "AgentFoxGuard")


def test_model_node_writes_trace_into_graph_state(seeded):
    """Trace identity must survive checkpointing, so it lives in graph state."""
    guard = AgentFoxGuard(agent="support-triage", session=seeded)

    @guard.model_node
    def call_model(state):
        return {"messages": [{"role": "assistant", "content": "30 days."}]}

    out = call_model({"messages": [{"role": "user", "content": "refund window?"}]})
    assert out[STATE_KEY]["trace_id"]
    assert guard.trace_id(out) == out[STATE_KEY]["trace_id"]


def test_retrieval_node_blocks_indirect_injection(seeded):
    set_mode(seeded, "baseline", "enforce")
    guard = AgentFoxGuard(agent="support-triage", session=seeded)

    @guard.retrieval_node
    def fetch(state):
        return state["doc"]

    with pytest.raises(PolicyViolation) as excinfo:
        fetch({"doc": INDIRECT_INJECTION})
    assert any(r["rule_id"] == "injection.indirect" for r in excinfo.value.rules_fired)


def test_tool_node_denies_before_the_body_runs(seeded):
    """A denied call must not execute — checking after the fact is not a control."""
    guard = AgentFoxGuard(agent="payments-ops", session=seeded)
    executed: list[dict] = []

    @guard.tool_node(tool="payments.transfer")
    def transfer(state, **kwargs):
        executed.append(kwargs)
        return {"sent": True}

    with pytest.raises(PolicyViolation):
        transfer({}, amount=25_000, currency="USD", to="acct_x")
    assert executed == []


def test_tool_node_allows_a_compliant_call(seeded):
    """A within-limits call on a non-irreversible tool proceeds."""
    guard = AgentFoxGuard(agent="payments-ops", intent="refund a duplicate charge", session=seeded)

    @guard.tool_node(tool="payments.refund")
    def refund(state, **kwargs):
        return {"refunded": True}

    assert refund({}, amount=250, currency="USD")["refunded"]


def test_eu_pack_records_art14_without_blocking_while_in_observe(seeded, enforcer):
    """Observe-mode semantics, asserted rather than assumed.

    The EU AI Act pack sends *every* irreversible action by a high-risk agent to a
    human (Art. 14). It ships in **observe** mode, so a compliant call proceeds while
    the platform records what enforcement would have done. That distinction is the
    whole R3 mitigation, and it is worth a test.
    """
    result = enforcer.guard_tool_call(
        agent_slug="payments-ops",
        tool_key="payments.transfer",
        arguments={"amount": 250, "currency": "USD", "to": "acct_customer"},
        intent="refund a duplicate charge",
    )
    assert result.verdict == "allow", "observe mode must not block"
    assert result.effective_verdict == "escalate", "but it must record the counterfactual"
    assert any(r["rule_id"] == "eu.art14.human_oversight" for r in result.rules_fired)


def test_undeclared_intent_escalates_an_irreversible_tool(seeded):
    """`tool-containment` *is* enforcing: an irreversible action with no declared
    intent cannot be judged against the task, so it goes to a human."""
    guard = AgentFoxGuard(agent="payments-ops", session=seeded)  # no intent

    @guard.tool_node(tool="payments.transfer")
    def transfer(state, **kwargs):
        return {"sent": True}

    with pytest.raises(ApprovalRequired) as excinfo:
        transfer({}, amount=250, currency="USD", to="acct_customer")
    assert any(
        r["rule_id"] == "intent.undeclared_irreversible" for r in excinfo.value.result.rules_fired
    )


def test_tool_node_escalates_on_tainted_argument(seeded):
    guard = AgentFoxGuard(agent="payments-ops", session=seeded)

    @guard.tool_node(tool="payments.transfer", provenance={"to": "tool_result"})
    def transfer(state, **kwargs):
        return {"sent": True}

    with pytest.raises(ApprovalRequired) as excinfo:
        transfer({}, amount=250, currency="USD", to="acct_attacker_991")
    assert excinfo.value.approval_id


def test_tool_node_records_call_sequence(seeded):
    """Prior tools feed loop and composed-privilege detection."""
    guard = AgentFoxGuard(agent="support-triage", session=seeded)

    @guard.tool_node(tool="kb.search")
    def search(state, **kwargs):
        return {"hits": 3}

    out = search({}, q="refund")
    assert out[STATE_KEY]["tools_called"] == ["kb.search"]


def test_tool_node_alternating_cycle_trips_the_real_loop_governor(seeded):
    """PL-4 fast-follow: tool_node now threads a real step history (not just
    tools_called) into guard_tool_call via graph state, so an A-B-A-B alternation
    trips the real LoopGovernor here too — the same shape test_mcp_governance.py's
    McpGovernor tests already prove for its own `_prior_steps` tracking. Per-tool
    counting alone would miss this, since neither tool repeats consecutively."""
    guard = AgentFoxGuard(agent="support-triage", session=seeded)

    @guard.tool_node(tool="kb.search")
    def search(state, **kwargs):
        return {"hits": 1}

    @guard.tool_node(tool="crm.lookup")
    def lookup(state, **kwargs):
        return {"found": True}

    state = search({})
    state = lookup(state)
    state = search(state)
    assert [s["tool"] for s in state[STATE_KEY]["steps"]] == [
        "kb.search",
        "crm.lookup",
        "kb.search",
    ]

    with pytest.raises(PolicyViolation) as excinfo:
        lookup(state)
    assert any(r["rule_id"] == "loop.runaway" for r in excinfo.value.result.rules_fired)


def test_langchain_message_objects_are_normalised():
    from agentfox.integrations.langgraph import _normalise

    class FakeHumanMessage:
        type = "human"
        content = "hello"

    assert _normalise([FakeHumanMessage()]) == [{"role": "user", "content": "hello"}]
