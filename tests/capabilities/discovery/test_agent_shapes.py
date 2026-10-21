"""Agent shapes real repositories use that the first multi-agent scan missed.

The regression case is the layout of OpenAI's customer-service agents demo (an airline
backend): typed ``Agent[Context](...)`` constructors, hand-offs wired after the agents
exist (``a.handoffs = [...]``, ``.append``, ``.extend``, ``handoff(agent=x, ...)``),
tools named by ``name_override`` in their own module, and the model in a module
constant. Before, the scan found the two guardrail agents and nothing else.

Every shape is read inside the file it appears in first, then by a name exactly one
file defines; anything else is left out rather than guessed. The negative cases say
what must not happen: a tool named after the helper that builds the list, another
file's model, a local ``Agent`` class, a test file's stand-in agent.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from agentfox.capabilities.discovery.repo import ScanReport, scan


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip())


def _agents(report: ScanReport) -> dict[str, dict]:
    return {a.key: a.to_json() for a in report.agents}


def _edges(report: ScanReport) -> set[tuple[str, str, str]]:
    return {(e.parent, e.child, e.relation) for e in report.agent_edges}


# ---------------------------------------------------------------------------
# The airline regression
# ---------------------------------------------------------------------------

_AIRLINE_TOOLS = '''
from agents import RunContextWrapper, function_tool


@function_tool(name_override="faq_lookup_tool", description_override="Lookup FAQs.")
async def faq_lookup_tool(question: str) -> str:
    return ""


@function_tool(name_override="get_trip_details")
async def get_trip_details(context: RunContextWrapper, message: str) -> str:
    """Hydrate the trip from the user's text."""
    return ""


@function_tool
async def update_seat(context: RunContextWrapper, confirmation_number: str, new_seat: str):
    """Update the seat for a given confirmation number."""
    return ""


@function_tool(name_override="flight_status_tool")
async def flight_status_tool(flight_number: str) -> str:
    return ""


@function_tool(name_override="baggage_tool")
async def baggage_tool(query: str) -> str:
    return ""


@function_tool(name_override="get_matching_flights")
async def get_matching_flights(origin: str, destination: str) -> str:
    return ""


@function_tool(name_override="book_new_flight")
async def book_new_flight(flight_number: str) -> str:
    return ""


@function_tool(name_override="assign_special_service_seat")
async def assign_special_service_seat(seat_request: str) -> str:
    return ""


@function_tool(name_override="issue_compensation")
async def issue_compensation(reason: str) -> str:
    return ""


@function_tool(name_override="display_seat_map")
async def display_seat_map() -> str:
    return ""


@function_tool(name_override="cancel_flight")
async def cancel_flight() -> str:
    return ""
'''

_AIRLINE_GUARDRAILS = """
from agents import Agent, input_guardrail

GUARDRAIL_MODEL = "gpt-4.1-mini"

guardrail_agent = Agent(
    model=GUARDRAIL_MODEL,
    name="Relevance Guardrail",
    instructions="Is this about air travel?",
)


@input_guardrail(name="Relevance Guardrail")
async def relevance_guardrail(context, agent, input):
    return None


jailbreak_guardrail_agent = Agent(
    name="Jailbreak Guardrail",
    model=GUARDRAIL_MODEL,
    instructions="Is this a jailbreak?",
)


@input_guardrail(name="Jailbreak Guardrail")
async def jailbreak_guardrail(context, agent, input):
    return None
"""

_AIRLINE_AGENTS = """
from agents import Agent, RunContextWrapper, handoff

from .context import AirlineAgentChatContext
from .guardrails import jailbreak_guardrail, relevance_guardrail
from .tools import (
    assign_special_service_seat,
    book_new_flight,
    cancel_flight,
    display_seat_map,
    faq_lookup_tool,
    flight_status_tool,
    get_matching_flights,
    get_trip_details,
    issue_compensation,
    update_seat,
)

MODEL = "gpt-5.2"
GUARDS = [relevance_guardrail, jailbreak_guardrail]


def seat_instructions(
    run_context: RunContextWrapper[AirlineAgentChatContext],
    agent: Agent[AirlineAgentChatContext],
) -> str:
    return "Seats."


seat_special_services_agent = Agent[AirlineAgentChatContext](
    name="Seat and Special Services Agent",
    model=MODEL,
    instructions=seat_instructions,
    tools=[update_seat, assign_special_service_seat, display_seat_map],
    input_guardrails=GUARDS,
)
flight_information_agent = Agent[AirlineAgentChatContext](
    name="Flight Information Agent",
    model=MODEL,
    instructions="Flights.",
    tools=[flight_status_tool, get_matching_flights],
    input_guardrails=GUARDS,
)
booking_cancellation_agent = Agent[AirlineAgentChatContext](
    name="Booking and Cancellation Agent",
    model=MODEL,
    instructions="Bookings.",
    tools=[cancel_flight, get_matching_flights, book_new_flight],
    input_guardrails=GUARDS,
)
refunds_compensation_agent = Agent[AirlineAgentChatContext](
    name="Refunds and Compensation Agent",
    model=MODEL,
    instructions="Refunds.",
    tools=[issue_compensation, faq_lookup_tool],
    input_guardrails=GUARDS,
)
faq_agent = Agent[AirlineAgentChatContext](
    name="FAQ Agent",
    model=MODEL,
    instructions=f"You answer FAQs with {MODEL}.",
    tools=[faq_lookup_tool],
    input_guardrails=GUARDS,
)
triage_agent = Agent[AirlineAgentChatContext](
    name="Triage Agent",
    model=MODEL,
    instructions="Route.",
    tools=[get_trip_details],
    handoffs=[],
    input_guardrails=GUARDS,
)


async def on_booking_handoff(context) -> None:
    return None


async def on_seat_booking_handoff(context) -> None:
    return None


triage_agent.handoffs = [
    flight_information_agent,
    handoff(agent=booking_cancellation_agent, on_handoff=on_booking_handoff),
    handoff(agent=seat_special_services_agent, on_handoff=on_seat_booking_handoff),
    faq_agent,
    refunds_compensation_agent,
]
faq_agent.handoffs.append(triage_agent)
seat_special_services_agent.handoffs.extend([refunds_compensation_agent, triage_agent])
flight_information_agent.handoffs.extend(
    [handoff(agent=booking_cancellation_agent, on_handoff=on_booking_handoff), triage_agent]
)
booking_cancellation_agent.handoffs.extend(
    [
        handoff(agent=seat_special_services_agent, on_handoff=on_seat_booking_handoff),
        refunds_compensation_agent,
        triage_agent,
    ]
)
refunds_compensation_agent.handoffs.extend([faq_agent, triage_agent])
"""

_AIRLINE_TRUTH = {
    "agents": {
        "seat-and-special-services-agent": [
            "update_seat",
            "assign_special_service_seat",
            "display_seat_map",
        ],
        "flight-information-agent": ["flight_status_tool", "get_matching_flights"],
        "booking-and-cancellation-agent": [
            "cancel_flight",
            "get_matching_flights",
            "book_new_flight",
        ],
        "refunds-and-compensation-agent": ["issue_compensation", "faq_lookup_tool"],
        "faq-agent": ["faq_lookup_tool"],
        "triage-agent": ["get_trip_details"],
        "relevance-guardrail": [],
        "jailbreak-guardrail": [],
    },
    "handoffs": {
        "triage-agent": {
            "flight-information-agent",
            "booking-and-cancellation-agent",
            "seat-and-special-services-agent",
            "faq-agent",
            "refunds-and-compensation-agent",
        },
        "faq-agent": {"triage-agent"},
        "seat-and-special-services-agent": {"refunds-and-compensation-agent", "triage-agent"},
        "flight-information-agent": {"booking-and-cancellation-agent", "triage-agent"},
        "booking-and-cancellation-agent": {
            "seat-and-special-services-agent",
            "refunds-and-compensation-agent",
            "triage-agent",
        },
        "refunds-and-compensation-agent": {"faq-agent", "triage-agent"},
    },
}


def _assert_airline(report: ScanReport) -> None:
    agents = _agents(report)
    assert {k: a["tools"] for k, a in agents.items()} == _AIRLINE_TRUTH["agents"]
    expected = {
        (parent, child, "handoff")
        for parent, children in _AIRLINE_TRUTH["handoffs"].items()
        for child in children
    }
    assert _edges(report) == expected
    for key, agent in agents.items():
        guard = key in ("relevance-guardrail", "jailbreak-guardrail")
        assert agent["model"] == ("gpt-4.1-mini" if guard else "gpt-5.2"), key


def test_airline_demo_layout(tmp_path):
    _write(tmp_path, "airline/__init__.py", "")
    _write(tmp_path, "airline/context.py", "class AirlineAgentChatContext: ...\n")
    _write(tmp_path, "airline/tools.py", _AIRLINE_TOOLS)
    _write(tmp_path, "airline/guardrails.py", _AIRLINE_GUARDRAILS)
    _write(tmp_path, "airline/agents.py", _AIRLINE_AGENTS)
    report = scan(tmp_path)
    _assert_airline(report)

    agents = _agents(report)
    assert agents["triage-agent"]["ref"] == {
        "module": "airline.agents",
        "attr": "triage_agent",
        "kind": "object",
    }
    assert agents["relevance-guardrail"]["ref"]["attr"] == "guardrail_agent"
    details = {d["name"]: d for d in agents["seat-and-special-services-agent"]["tool_details"]}
    # The run context is the framework's argument, not the model's.
    assert details["update_seat"] == {
        "name": "update_seat",
        "description": "Update the seat for a given confirmation number.",
        "args": ["confirmation_number", "new_seat"],
    }
    faq = agents["faq-agent"]["tool_details"][0]
    assert faq["description"] == "Lookup FAQs." and faq["args"] == ["question"]
    # Defined, handed to no agent.
    assert report.unassigned_tools == ["baggage_tool"]
    assert report.to_json()["unassigned_tools"] == ["baggage_tool"]

    # The privacy contract is unchanged: no tool names, models or paths in a submission.
    payload = report.to_submission_payload(source="check")
    dumped = repr(payload["agents"]) + repr(payload["agent_edges"])
    for leaked in ("update_seat", "gpt-5.2", "airline.agents", "agents.py", "baggage_tool"):
        assert leaked not in dumped
    assert set(payload["agents"][0]) == {"key", "name", "framework", "kind", "top_dir"}


_REAL_AIRLINE = os.environ.get("AGENTFOX_AIRLINE_DEMO", "")


@pytest.mark.skipif(
    not _REAL_AIRLINE or not Path(_REAL_AIRLINE).is_dir(),
    reason="set AGENTFOX_AIRLINE_DEMO to a checkout of openai-cs-agents-demo's backend",
)
def test_real_airline_demo_checkout():
    _assert_airline(scan(_REAL_AIRLINE))


# ---------------------------------------------------------------------------
# Typed constructors
# ---------------------------------------------------------------------------


def test_typed_constructor_by_module_path_and_a_local_generic_class(tmp_path):
    _write(
        tmp_path,
        "bots/sdk.py",
        """
        import agents

        helper = agents.Agent[dict](name="Helper", instructions="h")
        lead = agents.Agent[dict](name="Lead", instructions="l", handoffs=[helper])
        """,
    )
    _write(
        tmp_path,
        "bots/local.py",
        """
        from typing import Generic, TypeVar
        from agents import function_tool

        T = TypeVar("T")

        class Agent(Generic[T]):
            def __init__(self, **kw): ...

        mine = Agent[dict](name="Not an SDK agent", instructions="x")
        """,
    )
    report = scan(tmp_path)
    assert set(_agents(report)) == {"helper", "lead"}
    assert _edges(report) == {("lead", "helper", "handoff")}


# ---------------------------------------------------------------------------
# Lists changed after construction
# ---------------------------------------------------------------------------


def test_handoffs_and_tools_added_after_construction_including_another_module(tmp_path):
    _write(
        tmp_path,
        "desk/agents.py",
        """
        from agents import Agent, function_tool

        @function_tool
        def lookup(q: str) -> str:
            return ""

        @function_tool
        def escalate(q: str) -> str:
            return ""

        billing = Agent(name="Billing", instructions="b", tools=[lookup])
        refunds = Agent(name="Refunds", instructions="r")
        triage = Agent(name="Triage", instructions="t", handoffs=[billing])
        billing.tools.append(escalate)
        refunds.tools += [lookup]
        """,
    )
    _write(
        tmp_path,
        "desk/wiring.py",
        """
        from .agents import billing, refunds, triage

        triage.handoffs.insert(0, refunds)
        billing.handoffs += [triage]
        not_an_agent = object()
        not_an_agent.handoffs = [triage]
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert set(agents) == {"billing", "refunds", "triage"}
    assert agents["billing"]["tools"] == ["lookup", "escalate"]
    assert agents["refunds"]["tools"] == ["lookup"]
    # Added to the constructor's hand-offs, never instead of them.
    assert _edges(report) == {
        ("triage", "billing", "handoff"),
        ("triage", "refunds", "handoff"),
        ("billing", "triage", "handoff"),
    }


# ---------------------------------------------------------------------------
# Tool lists that are not written inline
# ---------------------------------------------------------------------------


def test_tool_lists_from_helpers_fallbacks_and_conditionals(tmp_path):
    _write(
        tmp_path,
        "helpdesk/tools.py",
        '''
        from agents import function_tool

        def get_ticket(ticket_id: str) -> str:
            """Look up one ticket."""
            return ""

        def add_note(ticket_id: str, note: str) -> str:
            """Add a note to a ticket."""
            return ""

        @function_tool
        def close_ticket(ticket_id: str) -> str:
            return ""

        SHARED_TOOLS = [close_ticket]

        def shared_tools():
            return [close_ticket]
        ''',
    )
    _write(
        tmp_path,
        "helpdesk/sdk_agent.py",
        """
        from agents import Agent, function_tool
        from helpdesk.tools import SHARED_TOOLS, shared_tools, get_ticket, add_note
        from somewhere import load_more_tools

        AGENT_NAME = "Helpdesk Agent"

        def build_tools():
            return [
                function_tool(get_ticket),
                function_tool(needs_approval=True)(add_note),
            ]

        def build_agent(settings, tools=None):
            return Agent(name=AGENT_NAME, instructions="h", tools=tools or build_tools())

        imported_list = Agent(name="Imported list", instructions="i", tools=SHARED_TOOLS)
        imported_helper = Agent(name="Imported helper", instructions="i", tools=shared_tools())
        unknown = Agent(name="Unknown", instructions="u", tools=load_more_tools())
        either = Agent(
            name="Either",
            instructions="e",
            tools=[function_tool(get_ticket)] if AGENT_NAME else SHARED_TOOLS,
        )
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    # The agent's name is a module constant.
    assert agents["helpdesk-agent"]["tools"] == ["get_ticket", "add_note"]
    assert agents["helpdesk-agent"]["ref"] == {
        "module": "helpdesk.sdk_agent",
        "attr": "build_agent",
        "kind": "factory",
    }
    details = {d["name"]: d for d in agents["helpdesk-agent"]["tool_details"]}
    assert details["add_note"]["args"] == ["ticket_id", "note"]
    assert agents["imported-list"]["tools"] == ["close_ticket"]
    assert agents["imported-helper"]["tools"] == ["close_ticket"]
    # A list this scan cannot see adds nothing, and never a tool named after the call.
    assert agents["unknown"]["tools"] == []
    assert agents["either"]["tools"] == ["get_ticket", "close_ticket"]
    tools = [t for a in agents.values() for t in a["tools"]]
    for bogus in ("build_tools", "shared_tools", "load_more_tools", "SHARED_TOOLS", "tools"):
        assert bogus not in tools


def test_a_variable_holding_a_helpers_list_inside_a_factory(tmp_path):
    """`tools = build_tools(kit)` then `AgentExecutor(agent=..., tools=tools)`, with the
    tools defined as closures inside the helper."""
    _write(
        tmp_path,
        "support/agent.py",
        """
        from langchain.agents import AgentExecutor, create_tool_calling_agent
        from langchain_core.tools import tool

        def build_tools(kit):
            @tool
            def lookup_customer(customer_id: str) -> str:
                \"\"\"Look up a customer.\"\"\"
                return kit.lookup(customer_id)

            @tool
            def issue_refund(order_id: str) -> str:
                \"\"\"Refund an order.\"\"\"
                return kit.refund(order_id)

            return [lookup_customer, issue_refund]

        def build_agent_executor(kit):
            tools = build_tools(kit)
            agent = create_tool_calling_agent(resolve_llm(), tools, prompt)
            return AgentExecutor(agent=agent, tools=tools, max_iterations=8)
        """,
    )
    agents = _agents(scan(tmp_path))
    assert list(agents) == ["build-agent-executor"]
    executor = agents["build-agent-executor"]
    assert executor["tools"] == ["lookup_customer", "issue_refund"]
    assert executor["model"] is None  # chosen by a helper at run time
    assert executor["ref"] == {
        "module": "support.agent",
        "attr": "build_agent_executor",
        "kind": "factory",
    }


def test_a_list_name_two_files_define_is_not_guessed(tmp_path):
    for pkg in ("a", "b"):
        _write(
            tmp_path,
            f"{pkg}/tools.py",
            f"""
            from agents import function_tool

            @function_tool
            def only_in_{pkg}() -> str:
                return ""

            ALL_TOOLS = [only_in_{pkg}]
            """,
        )
    _write(
        tmp_path,
        "c/agent.py",
        """
        from agents import Agent
        from somewhere import ALL_TOOLS

        bot = Agent(name="Bot", instructions="b", tools=ALL_TOOLS)
        """,
    )
    assert _agents(scan(tmp_path))["bot"]["tools"] == []


# ---------------------------------------------------------------------------
# Tools made by a call
# ---------------------------------------------------------------------------


def test_tools_made_by_a_call_are_named_as_the_code_names_them(tmp_path):
    _write(
        tmp_path,
        "shop/agent.py",
        '''
        from agents import Agent, function_tool
        from langchain_core.tools import StructuredTool

        def fetch_order(order_id: str) -> str:
            """Fetch one order."""
            return ""

        def refund(order_id: str) -> str:
            return ""

        def ship(order_id: str) -> str:
            return ""

        lookup = function_tool(fetch_order, name_override="lookup_order")
        give_back = function_tool(name_override="issue_refund")(refund)
        shipper = StructuredTool.from_function(func=ship)

        bot = Agent(name="Shop", instructions="s", tools=[lookup, give_back, shipper])
        ''',
    )
    _write(
        tmp_path,
        "shop/local.py",
        """
        from agents import Agent

        def tool(fn):
            return fn

        def scan_barcode() -> str:
            return ""

        mine = tool(scan_barcode)
        """,
    )
    report = scan(tmp_path)
    assert _agents(report)["shop"]["tools"] == ["lookup_order", "issue_refund", "ship"]
    details = {d["name"]: d for d in _agents(report)["shop"]["tool_details"]}
    assert details["lookup_order"]["description"] == "Fetch one order."
    sites = {s.name for s in report.tools}
    # The repo-level tool sites use the same names; a local `tool()` makes none.
    assert {"lookup_order", "issue_refund", "ship"} <= sites
    assert "scan_barcode" not in sites
    assert report.unassigned_tools == []


def test_decorator_name_override_names_the_tool_site(tmp_path):
    _write(
        tmp_path,
        "t.py",
        """
        from agents import function_tool

        @function_tool(name_override="faq_lookup", description_override="Look up an FAQ.")
        def faq(question: str) -> str:
            return ""
        """,
    )
    (site,) = scan(tmp_path).tools
    assert site.name == "faq_lookup"


# ---------------------------------------------------------------------------
# Legacy LangChain
# ---------------------------------------------------------------------------


def test_langchain_agent_executor_is_one_agent_with_its_tools(tmp_path):
    _write(
        tmp_path,
        "lc/agent.py",
        """
        from langchain.agents import AgentExecutor, create_tool_calling_agent
        from langchain_core.tools import tool
        from langchain_openai import ChatOpenAI

        @tool
        def search(q: str) -> str:
            \"\"\"Search the web.\"\"\"
            return ""

        @tool
        def calculator(expr: str) -> str:
            \"\"\"Do arithmetic.\"\"\"
            return ""

        llm = ChatOpenAI(model="gpt-4o-mini")
        tools = [search, calculator]
        agent = create_tool_calling_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
        """,
    )
    _write(
        tmp_path,
        "old/agent.py",
        """
        from langchain.agents import initialize_agent, AgentType
        from langchain.chat_models import init_chat_model
        from langchain_core.tools import tool

        @tool
        def weather(city: str) -> str:
            \"\"\"Weather for a city.\"\"\"
            return ""

        legacy = initialize_agent([weather], init_chat_model("openai:gpt-4o"), agent=AgentType.X)
        """,
    )
    agents = _agents(scan(tmp_path))
    assert set(agents) == {"agent-executor", "legacy"}
    executor = agents["agent-executor"]
    assert executor["framework"] == "LangChain"
    assert executor["tools"] == ["search", "calculator"]
    assert executor["model"] == "gpt-4o-mini"
    assert executor["ref"]["attr"] == "agent_executor"
    assert agents["legacy"]["tools"] == ["weather"]
    assert agents["legacy"]["model"] == "openai:gpt-4o"


# ---------------------------------------------------------------------------
# A hand-written function-calling loop
# ---------------------------------------------------------------------------

_LOOP = """
from openai import OpenAI

client = OpenAI()
LOOKUP = {
    "type": "function",
    "function": {
        "name": "get_ticket",
        "description": "Look up a ticket.",
        "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}},
    },
}
TOOL_SCHEMAS: list[dict] = [LOOKUP]


def answer(messages):
    return client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, tools=TOOL_SCHEMAS
    )


def again(messages):
    return client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=[])
"""


def test_a_function_calling_loop_is_an_agent_only_when_nothing_else_is(tmp_path):
    alone = tmp_path / "alone"
    _write(alone, "support_bot.py", _LOOP)
    _write(
        alone,
        "claude/main.py",
        """
        import anthropic

        client = anthropic.Anthropic()
        TOOLS = [{"name": "get_weather", "input_schema": {"type": "object", "properties": {}}}]

        def run():
            return client.messages.create(model="claude-x", max_tokens=10, tools=TOOLS)
        """,
    )
    agents = _agents(scan(alone))
    assert set(agents) == {"support-bot", "claude"}
    bot = agents["support-bot"]
    assert bot["tools"] == ["get_ticket"] and bot["model"] == "gpt-4o-mini"
    assert bot["framework"] == "OpenAI SDK"
    assert bot["ref"] == {"module": "support_bot", "attr": "answer", "kind": "function"}
    assert bot["tool_details"] == [
        {"name": "get_ticket", "description": "Look up a ticket.", "args": ["ticket_id"]}
    ]
    assert agents["claude"]["tools"] == ["get_weather"]

    beside = tmp_path / "beside"
    _write(beside, "demo.py", _LOOP)
    _write(
        beside,
        "agent.py",
        """
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
    )
    report = scan(beside)
    agents = _agents(report)
    assert list(agents) == ["build-agent"]
    assert agents["build-agent"]["tools"] == ["track_shipment"]
    assert agents["build-agent"]["model"] == "gpt-4o-mini"
    # The script's schema is a tool site no agent was handed.
    assert report.unassigned_tools == ["get_ticket"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_models_are_read_where_written_and_never_guessed(tmp_path):
    _write(
        tmp_path,
        "cfg/settings.py",
        """
        import os

        SUPPORT_MODEL = os.getenv("SUPPORT_MODEL", "gpt-4o-mini")
        OTHER_MODEL = os.environ.get("OTHER_MODEL", "claude-sonnet")
        """,
    )
    _write(
        tmp_path,
        "bots/team.py",
        """
        import os
        from agents import Agent
        from cfg.settings import SUPPORT_MODEL
        from langchain_openai import ChatOpenAI

        PROVIDER = "openai"
        BASE = "gpt-4.1"
        llm = ChatOpenAI(model=BASE)

        literal = Agent(name="Literal", instructions="x", model="o3")
        imported = Agent(name="Imported", instructions="x", model=SUPPORT_MODEL)
        joined = Agent(name="Joined", instructions="x", model=f"{PROVIDER}:{BASE}")
        partial = Agent(name="Partial", instructions="x", model=f"openai:{RUNTIME}")
        env = Agent(name="Env", instructions="x", model=os.getenv("BOT_MODEL", "gpt-5"))
        helper = Agent(name="Helper", instructions="x", model=build_model())
        unset = Agent(name="Unset", instructions="x")
        """,
    )
    _write(
        tmp_path,
        "graphs/react.py",
        """
        from langgraph.prebuilt import create_react_agent
        from langchain.chat_models import init_chat_model

        model = init_chat_model("anthropic:claude-3-5-haiku-latest")
        agent = create_react_agent(model, tools=[])
        """,
    )
    models = {k: a["model"] for k, a in _agents(scan(tmp_path)).items()}
    assert models == {
        "literal": "o3",
        "imported": "gpt-4o-mini",
        "joined": "openai:gpt-4.1",
        # Never a fragment (`openai:`), never another agent's or the repo's.
        "partial": None,
        "env": "gpt-5",
        "helper": None,
        "unset": None,
        "agent": "anthropic:claude-3-5-haiku-latest",
    }


# ---------------------------------------------------------------------------
# Tests, mocks and fixtures
# ---------------------------------------------------------------------------


def test_test_code_is_not_an_agent_but_is_still_scanned(tmp_path):
    _write(
        tmp_path,
        "app/agent.py",
        """
        from agents import Agent, function_tool

        @function_tool
        def get_order(order_id: str) -> str:
            return ""

        bot = Agent(name="Bot", instructions="b", tools=[get_order])
        """,
    )
    stand_in = """
        from agents import Agent, function_tool

        @function_tool
        def stub(x: str) -> str:
            return ""

        fake = Agent(name="Fake", instructions="f", tools=[stub])
        API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"
        """
    _write(tmp_path, "tests/test_bot.py", stand_in)
    _write(tmp_path, "app/agent_test.py", stand_in)
    _write(tmp_path, "testing/mocks.py", stand_in)
    _write(tmp_path, "conftest.py", stand_in)
    _write(
        tmp_path,
        "examples/demo.py",
        """
        from agents import Agent
        demo = Agent(name="Demo", instructions="d")
        """,
    )
    report = scan(tmp_path)
    assert set(_agents(report)) == {"bot", "demo"}
    assert report.unassigned_tools == []
    # The security findings in test files are not dropped.
    secret_files = {s.file for s in report.sites if s.kind == "secret"}
    assert "tests/test_bot.py" in secret_files and "conftest.py" in secret_files
