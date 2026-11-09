"""Which agent a governed call is credited to (audit 2026-11-08, A1).

After an OpenAI Agents SDK hand-off the FAQ agent's own `faq_lookup_tool` was
credited to the triage agent `auto()` names: listed as "Blocked: tools the agent
wasn't given", with a high issue "triage-agent tried to faq_lookup_tool without
permission", while the tool ran. The call belongs to the agent running it, and a call
nothing stopped is never recorded as blocked.

No framework is needed here: the SDK's current-agent span, a CrewAI agent and a
LangGraph namespace are stood in for. The real Agents SDK run is in
`test_autoguard_responses_real_sdk`.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from agentfox.core.db import session_scope
from agentfox.core.models import Decision, Finding
from agentfox.frameworks.autoguard import auto, off
from agentfox.frameworks.autoguard import delegation as d

from .test_autoguard_tool_calls import _openai_response, _openai_tool_call

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "faq_lookup_tool",
            "description": "Lookup frequently asked questions.",
            "parameters": {"type": "object", "properties": {"question": {"type": "string"}}},
        },
    }
]


@pytest.fixture(autouse=True)
def _clean():
    d.stop()
    yield
    d.stop()


def test_without_a_framework_agent_the_call_is_the_named_agents():
    assert d.agent_for("triage-agent") == "triage-agent"


def test_the_entry_agent_keeps_autos_name_and_a_handed_to_agent_its_own():
    d.DELEGATION_TOOLS["transfer_to_faq_agent"] = ("FAQ Agent", "handoff")
    with d.active("Triage Agent"):
        assert d.agent_for("support-app") == "support-app"  # the entry agent
    with d.active("FAQ Agent"):
        assert d.agent_for("support-app") == "faq-agent"
    # FAQ hands back: the entry agent is still credited to the name auto() was given.
    d.DELEGATION_TOOLS["transfer_to_triage_agent"] = ("Triage Agent", "handoff")
    with d.active("Triage Agent"):
        assert d.agent_for("support-app") == "support-app"
    assert d.agent_for("support-app") == "support-app"  # outside any agent


def test_an_agent_slugged_like_autos_name_is_that_agent():
    d.DELEGATION_TOOLS["transfer_to_triage_agent"] = ("Triage Agent", "handoff")
    with d.active("Triage Agent"):
        assert d.agent_for("triage-agent") == "triage-agent"


def test_each_member_of_a_crew_is_credited_by_its_role():
    researcher = types.SimpleNamespace(role="Researcher")
    writer = types.SimpleNamespace(role="Writer")
    crew = types.SimpleNamespace(agents=[researcher, writer])
    researcher.crew = writer.crew = crew
    with d.active(d.crew_member(writer)):
        assert d.agent_for("support-crew") == "writer"
    solo = types.SimpleNamespace(role="Assistant", crew=types.SimpleNamespace(agents=[None]))
    with d.active(d.crew_member(solo)):
        assert d.agent_for("my-bot") == "my-bot"


def _fake_sdk_span(monkeypatch, name: str) -> None:
    """`agents.tracing.get_current_span()` returning an agent span for `name`."""

    class AgentSpanData:
        def __init__(self, name: str) -> None:
            self.name = name

    span = types.SimpleNamespace(span_data=AgentSpanData(name))
    tracing = types.ModuleType("agents.tracing")
    tracing.get_current_span = lambda: span
    package = types.ModuleType("agents")
    package.tracing = tracing
    monkeypatch.setitem(sys.modules, "agents", package)
    monkeypatch.setitem(sys.modules, "agents.tracing", tracing)


def test_an_agents_sdk_model_call_runs_as_the_sdks_current_agent(monkeypatch):
    _fake_sdk_span(monkeypatch, "FAQ Agent")
    d.DELEGATION_TOOLS["transfer_to_faq_agent"] = ("FAQ Agent", "handoff")
    seen: list[str] = []

    async def get_response(*_args, **_kwargs):
        seen.append(d.agent_for("triage-agent"))
        return "response"

    async def stream_response(*_args, **_kwargs):
        seen.append(d.agent_for("triage-agent"))
        yield "chunk"

    async def run() -> None:
        assert await d._scoped(get_response)() == "response"
        assert [c async for c in d._scoped(stream_response)()] == ["chunk"]

    asyncio.run(run())
    assert seen == ["faq-agent", "faq-agent"]
    assert d.running_agent() is None, "the running agent does not outlive the call"


def test_a_langgraph_member_is_read_from_the_graph_namespace():
    config_module = pytest.importorskip("langchain_core.runnables.config")
    var = config_module.var_child_runnable_config
    token = var.set({"metadata": {"langgraph_checkpoint_ns": "faq_agent:1|agent:2"}})
    try:
        assert d.agent_for("supervisor") == "supervisor", "no hand-off yet: one agent"
        d.DELEGATION_TOOLS["transfer_to_faq_agent"] = ("faq_agent", "handoff")
        assert d.agent_for("supervisor") == "faq-agent"
    finally:
        var.reset(token)


def test_a_handed_to_agents_own_tool_is_its_own_and_allowed(fake_openai):
    """The customer_service example after the hand-off: the FAQ agent holds its own
    tool, the triage agent holds nothing. The call is the FAQ agent's, allowed, with
    no issue raised against the triage agent."""
    from agentfox.platform.identity.service import ensure_identity, grant_capability
    from agentfox.platform.registry.service import register_agent

    with session_scope() as session:
        faq = register_agent(session, "faq-agent", name="FAQ Agent")
        grant_capability(session, ensure_identity(session, faq), "faq_lookup_tool")
        register_agent(session, "triage-agent", name="Triage Agent")
    client, script, _calls = fake_openai
    script.append(
        _openai_response(_openai_tool_call("c1", "faq_lookup_tool", {"question": "bags?"}))
    )
    governed = auto(agent="triage-agent", quiet=True)
    d.DELEGATION_TOOLS["transfer_to_faq_agent"] = ("FAQ Agent", "handoff")
    with d.active("FAQ Agent"):
        client().create(
            model="gpt-4o", messages=[{"role": "user", "content": "bags?"}], tools=TOOLS
        )
    assert governed.calls_blocked == 0 and governed.would_have_blocked == 0
    with session_scope() as session:
        from agentfox.core.models import Agent

        decision = session.query(Decision).filter_by(surface="tool_args").one()
        assert decision.verdict == "allow"
        assert session.get(Agent, decision.agent_id).slug == "faq-agent"
        titles = [f.title for f in session.query(Finding).all()]
        assert not [t for t in titles if "triage-agent" in t], titles
    off()


def test_a_call_only_watched_is_listed_as_would_block_not_blocked(fake_openai):
    """The no-grants carve-out: the call runs, so the run lists as allowed with a
    would-be block, never Blocked."""
    from agentfox.platform.ledger.trace import search_traces

    client, script, _calls = fake_openai
    script.append(
        _openai_response(_openai_tool_call("c1", "faq_lookup_tool", {"question": "bags?"}))
    )
    governed = auto(agent="triage-agent", quiet=True)
    client().create(model="gpt-4o", messages=[{"role": "user", "content": "bags?"}], tools=TOOLS)
    assert governed.calls_blocked == 0 and governed.would_have_blocked == 1
    with session_scope() as session:
        rows = [r for r in search_traces(session) if "faq_lookup_tool" in r["tools"]]
        assert rows and all(r["verdict"] == "allow" for r in rows), rows
        assert rows[0]["would_verdict"] == "block"
