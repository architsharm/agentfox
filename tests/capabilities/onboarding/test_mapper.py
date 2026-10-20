"""`agentfox init`'s map of a repository, on the shapes real agent repos are written in.

Each case is a tiny repo written to a temp folder; the mapper only reads it.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from agentfox.capabilities.onboarding.mapper import classify, map_repository


def _repo(tmp_path: Path, files: dict[str, str]) -> dict:
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dedent(body))
    return map_repository(tmp_path)


def _agents(m: dict) -> dict[str, dict]:
    s = m["structure"]
    names = {a["id"]: a["name"] for a in s["agents"]}
    return {
        a["name"]: {
            "model": a["model"],
            "framework": a["framework"],
            "tools": [t["name"] for t in s["tools"] if t["agentId"] == a["id"]],
            "hands_off_to": [names[x] for x in a["handsOffTo"]],
        }
        for a in s["agents"]
    }


def test_openai_agents_sdk_multi_agent_with_typed_agents_and_handoffs(tmp_path):
    """Several `Agent[Ctx](...)` in one repo stay several agents, each with its own tools."""
    m = _repo(
        tmp_path,
        {
            "airline/tools.py": '''
                from agents import function_tool

                @function_tool(name_override="faq_lookup", description_override="Look up an FAQ.")
                async def faq_lookup_tool(question: str) -> str:
                    return ""

                @function_tool
                async def cancel_flight(confirmation: str) -> str:
                    """Cancel a booked flight."""
                    return ""
            ''',
            "airline/agents.py": """
                from agents import Agent, handoff
                from .tools import faq_lookup_tool, cancel_flight

                MODEL = "gpt-5.2"

                faq_agent = Agent[Ctx](name="FAQ Agent", model=MODEL, tools=[faq_lookup_tool])
                booking_agent = Agent[Ctx](name="Booking Agent", model=MODEL, tools=[cancel_flight])
                triage_agent = Agent[Ctx](name="Triage Agent", model=MODEL, tools=[], handoffs=[])

                triage_agent.handoffs = [faq_agent, handoff(agent=booking_agent)]
                faq_agent.handoffs.append(triage_agent)
            """,
        },
    )
    agents = _agents(m)
    assert set(agents) == {"FAQ Agent", "Booking Agent", "Triage Agent"}
    assert agents["FAQ Agent"]["tools"] == ["faq_lookup"]
    assert agents["Booking Agent"]["tools"] == ["cancel_flight"]
    # An agent that lists no tools gets none, not every tool in the repo.
    assert agents["Triage Agent"]["tools"] == []
    assert all(a["model"] == "gpt-5.2" for a in agents.values())
    assert agents["Triage Agent"]["hands_off_to"] == ["FAQ Agent", "Booking Agent"]
    assert agents["FAQ Agent"]["hands_off_to"] == ["Triage Agent"]
    assert {a["framework"] for a in agents.values()} == {"openai-agents"}


def test_tools_wrapped_by_a_call_inside_a_helper_and_a_model_from_config(tmp_path):
    """`tools=build_tools()` returning `function_tool(fn)` / `function_tool(...)(fn)`."""
    m = _repo(
        tmp_path,
        {
            "helpdesk/config.py": """
                import os
                LOCAL = os.getenv("OLLAMA_MODEL", "llama3.1")
                HOSTED = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            """,
            "helpdesk/tools.py": '''
                def get_ticket(ticket_id: str) -> str:
                    """Look up one ticket."""

                def add_note(ticket_id: str, note: str) -> str:
                    """Add a note to a ticket."""
            ''',
            "helpdesk/sdk_agent.py": """
                from agents import Agent, function_tool
                from helpdesk import tools

                AGENT_NAME = "Helpdesk Agent"

                def build_tools():
                    return [
                        function_tool(tools.get_ticket),
                        function_tool(needs_approval=True)(tools.add_note),
                    ]

                def build_agent(settings):
                    return Agent(name=AGENT_NAME, model=build_model(settings), tools=build_tools())
            """,
        },
    )
    agents = _agents(m)
    assert list(agents) == ["Helpdesk Agent"]
    a = agents["Helpdesk Agent"]
    assert a["tools"] == ["get_ticket", "add_note"]
    # Chosen at run time; of the config's defaults, the OpenAI one for an OpenAI agent.
    assert a["model"] == "gpt-4o-mini"
    tools = {t["name"]: t for t in m["structure"]["tools"]}
    assert tools["get_ticket"]["whatItDoes"].startswith("Look up one ticket")
    assert tools["add_note"]["args"] == ["ticket_id", "note"]


def test_a_raw_function_calling_loop_is_an_agent_only_when_nothing_else_is(tmp_path):
    raw = """
        from openai import OpenAI
        client = OpenAI()
        TOOL_SCHEMAS: list[dict] = [
            {"type": "function", "function": {
                "name": "get_ticket",
                "description": "Look up a ticket.",
                "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}},
            }},
        ]
        def run(messages):
            return client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, tools=TOOL_SCHEMAS
            )
        def again(messages):
            return client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, tools=TOOL_SCHEMAS
            )
    """
    alone = _agents(_repo(tmp_path / "alone", {"loop.py": raw}))
    assert len(alone) == 1
    (only,) = alone.values()
    assert only["tools"] == ["get_ticket"] and only["framework"] == "openai"

    beside = _agents(
        _repo(
            tmp_path / "beside",
            {
                "demo.py": raw,
                "agent.py": """
                    from langchain.agents import create_agent
                    from langchain_core.tools import tool

                    @tool
                    def track_shipment(order_id: str) -> str:
                        \"\"\"Track an order.\"\"\"

                    ALL_TOOLS = [track_shipment]

                    def build_agent(llm=None, tools=None):
                        return create_agent(model=llm or "gpt-4o-mini", tools=tools or ALL_TOOLS)

                    agent = build_agent()
                """,
            },
        )
    )
    # The script beside a real agent is not a second agent; `tools or ALL_TOOLS` is read.
    assert len(beside) == 1
    (main,) = beside.values()
    assert main["framework"] == "langchain" and main["tools"] == ["track_shipment"]


def test_risk_from_the_tool_name():
    assert classify("issue_compensation", "")[0] == "high"
    assert classify("book_new_flight", "")[0] == "high"
    assert classify("add_note", "")[0] == "high"
    assert classify("get_ticket", "")[0] == "read_only"
    assert classify("escalate_to_human", "")[0] == "outside"


def test_test_code_is_not_the_agent(tmp_path):
    """Mocks and tests build stand-in tools; they are not reported as the agent's."""
    m = _repo(
        tmp_path,
        {
            "agent.py": """
                from langchain.agents import create_agent
                from langchain_core.tools import tool

                @tool
                def get_order(order_id: str) -> str:
                    \"\"\"Look up an order.\"\"\"

                agent = create_agent(model="gpt-4o-mini", tools=[get_order])
            """,
            "testing/mocks.py": """
                from langchain_core.tools import StructuredTool

                def mock_tool(name):
                    def fake(**kwargs):
                        return {}
                    return StructuredTool.from_function(fake, name=name)
            """,
            "test_agent.py": """
                from langchain_core.tools import tool

                @tool
                def stub(x: str) -> str:
                    \"\"\"A stub.\"\"\"
            """,
        },
    )
    assert [t["name"] for t in m["structure"]["tools"]] == ["get_order"]
    assert m["unassigned_tools"] == []
    assert m["unreadable"] == []
