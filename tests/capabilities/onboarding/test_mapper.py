"""`agentfox init`'s map of a repository, on the shapes real agent repos are written in.

The map is discovery's scan (`discovery/repo.scan` and `discovery/agents.py`) said in
the onboarding's words, so these tests assert through `map_repository`, the adapter.
Each case is a tiny repo written to a temp folder; nothing is imported or run.

Two expectations changed when the mapper's own AST walker was replaced by discovery,
both because the old mapper was wrong:

* an agent whose model is only chosen at run time (``model=build_model(settings)``)
  has no model on the map ("unknown model"); the old mapper guessed one from any
  ``os.getenv("..._MODEL", default)`` anywhere in the repository;
* ``examples/`` is read like any other directory (the old mapper skipped it, so an
  agent kept there was never found).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agentfox.capabilities.onboarding.mapper import classify, map_repository, system_for


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
            "relations": {names[h["agentId"]]: h["relation"] for h in a["handoffs"]},
            "root": a["root"],
        }
        for a in s["agents"]
    }


AIRLINE = {
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
        triage_agent = Agent[Ctx](
            name="Triage Agent", model=MODEL, tools=[], handoffs=[],
            instructions="You help airline customers.",
        )

        triage_agent.handoffs = [faq_agent, handoff(agent=booking_agent)]
        faq_agent.handoffs.append(triage_agent)
        booking_agent.handoffs.append(triage_agent)
    """,
}


def test_openai_agents_sdk_multi_agent_with_typed_agents_and_handoffs(tmp_path):
    """Several `Agent[Ctx](...)` in one repo stay several agents, each with its own tools."""
    m = _repo(tmp_path, AIRLINE)
    agents = _agents(m)
    assert set(agents) == {"FAQ Agent", "Booking Agent", "Triage Agent"}
    assert agents["FAQ Agent"]["tools"] == ["faq_lookup"]
    assert agents["Booking Agent"]["tools"] == ["cancel_flight"]
    # An agent that lists no tools gets none, not every tool in the repo.
    assert agents["Triage Agent"]["tools"] == []
    assert all(a["model"] == "gpt-5.2" for a in agents.values())
    assert set(agents["Triage Agent"]["hands_off_to"]) == {"FAQ Agent", "Booking Agent"}
    assert agents["FAQ Agent"]["hands_off_to"] == ["Triage Agent"]
    assert agents["Triage Agent"]["relations"] == {
        "FAQ Agent": "handoff",
        "Booking Agent": "handoff",
    }
    assert {a["framework"] for a in agents.values()} == {"OpenAI Agents SDK"}
    # Everyone hands back to triage: the cycle's entry is the one that hands off most,
    # and it comes first, which is the agent a test talks to.
    assert m["structure"]["agents"][0]["name"] == "Triage Agent"
    assert [a for a, v in agents.items() if v["root"]] == ["Triage Agent"]
    assert m["agents"][0] == {
        "agentId": "ag-1",
        "module": "airline.agents",
        "attr": "triage_agent",
        "kind": "object",
        "framework": "OpenAI Agents SDK",
    }
    # Who it serves is read from its instructions; the instructions never leave.
    assert m["structure"]["sources"][0]["label"] == "Customers"
    assert "instructions" not in str(m["structure"])
    assert len(m["edges"]) == 4


def test_tools_wrapped_by_a_call_inside_a_helper_and_no_guessed_model(tmp_path):
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
    # Chosen at run time: not guessed from the config's defaults (the old mapper's bug).
    assert a["model"] == "unknown model"
    assert m["structure"]["agents"][0]["models"] == []
    tools = {t["name"]: t for t in m["structure"]["tools"]}
    assert tools["get_ticket"]["whatItDoes"].startswith("Look up one ticket")
    assert tools["add_note"]["args"] == ["ticket_id", "note"]
    # Reached by calling the factory, which takes arguments a runner has to supply.
    assert m["agents"][0]["attr"] == "build_agent" and m["agents"][0]["kind"] == "factory"


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
    alone_map = _repo(tmp_path / "alone", {"loop.py": raw})
    alone = _agents(alone_map)
    assert len(alone) == 1
    (only,) = alone.values()
    assert only["tools"] == ["get_ticket"] and only["framework"] == "OpenAI SDK"
    # Not named by its code: one agent takes the project's (the folder's) name.
    assert list(alone) == ["alone"]
    assert alone_map["agents"][0]["kind"] == "function"

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
    assert main["framework"] == "LangGraph" and main["tools"] == ["track_shipment"]


def test_examples_are_read_like_any_other_directory(tmp_path):
    """The old mapper skipped `examples/`; an agent kept there is still an agent."""
    m = _repo(
        tmp_path,
        {
            "examples/support/agent.py": """
                from agents import Agent, function_tool

                @function_tool
                def lookup_order(order_id: str) -> str:
                    \"\"\"Look up an order.\"\"\"

                support = Agent(name="Support", model="gpt-4o", tools=[lookup_order])
            """,
        },
    )
    assert list(_agents(m)) == ["Support"]


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


def test_coverage_says_what_was_read_and_what_was_not(tmp_path):
    """The CLI's "Recognised ... Missing something?" comes from the scan's own coverage."""
    m = _repo(
        tmp_path / "repo",
        {
            "agent.py": """
                from agents import Agent, function_tool

                @function_tool
                def get_order(order_id: str) -> str:
                    \"\"\"Look up an order.\"\"\"

                @function_tool
                def unused_export(x: str) -> str:
                    \"\"\"Export everything.\"\"\"

                shop = Agent(name="Shop", model="gpt-4o", tools=[get_order])
            """,
            "broken.py": "def broken(:\n",
            "service/Main.java": "class Main {}\n",
        },
    )
    assert m["read"] == 2
    assert m["unreadable"] == ["broken.py"]
    assert m["unassigned_tools"] == ["unused_export"]
    assert m["skipped"] == {".java": 1}
    assert m["frameworks"] == ["OpenAI Agents SDK"]


def test_as_tool_and_supervisor_relations_are_kept(tmp_path):
    m = _repo(
        tmp_path,
        {
            "team.py": """
                from agents import Agent

                researcher = Agent(name="Researcher", instructions="Research.")
                writer = Agent(
                    name="Writer",
                    instructions="Write.",
                    tools=[researcher.as_tool(tool_name="research", tool_description="r")],
                )
            """,
        },
    )
    agents = _agents(m)
    assert agents["Writer"]["relations"] == {"Researcher": "as_tool"}
    assert agents["Writer"]["root"] and not agents["Researcher"]["root"]


# --- risk and systems, from discovery's classifiers --------------------------------


@pytest.mark.parametrize(
    ("name", "doc", "risk"),
    [
        ("issue_compensation", "", "high"),
        ("book_new_flight", "", "high"),
        ("add_note", "", "high"),
        ("get_ticket", "", "read_only"),
        ("escalate_to_human", "", "outside"),
        ("start_return", "Create a return request and refund for an order.", "high"),
        ("update_seat", "", "high"),
        ("cancel_flight", "", "high"),
        ("transfer_to_human", "", "outside"),
        ("notebook_search", "", "read_only"),
        ("list_and_refund", "", "high"),
        ("fetch_and_email_report", "", "outside"),
        ("send_email", "", "outside"),
        ("delete_user", "", "high"),
        ("export_all_customers", "", "high"),
        ("display_seat_map", "", "read_only"),
        ("get_membership_status", "", "read_only"),
        ("check_return_eligibility", "Can it be returned for a refund?", "read_only"),
    ],
)
def test_risk_is_the_classifiers_answer(name, doc, risk):
    assert classify(name, doc)[0] == risk


def test_what_moves_money_and_what_only_hands_over():
    assert classify("issue_compensation")[1] == "moves money"
    assert classify("list_and_refund")[1] == "moves money"
    # A chat handed to a person moves no money.
    assert classify("transfer_to_human")[1] == "hands the conversation to a person"


@pytest.mark.parametrize(
    ("name", "doc", "system"),
    [
        ("issue_compensation", "", "Payments"),
        ("start_return", "Create a return request and refund for an order.", "Payments"),
        ("transfer_to_human", "", "Helpdesk"),
        ("escalate_to_human", "", "Helpdesk"),
        ("get_order", "", "Orders"),
        ("track_shipment", "", "Shipping carrier"),
        ("send_email", "", "Email"),
        # Whole words: "ship" is in neither name.
        ("get_membership_status", "", "Customer records"),
        ("lookup_relationship_manager", "", "Internal service"),
        # A tool that only mentions refunds reads; it touches no payments.
        ("check_return_eligibility", "Can it be returned for a refund?", "Internal service"),
    ],
)
def test_the_system_a_tool_touches(name, doc, system):
    risk = classify(name, doc)[0]
    assert system_for(name, doc, risk)[0] == system
