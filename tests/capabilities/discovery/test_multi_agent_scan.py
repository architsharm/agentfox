"""Multi-agent structure read from code: one entry per agent, its own tools, and which
agent hands work to which.

Each fixture below is the shape the framework's own documentation and examples use, so
a passing test means the scanner reads code people actually write, not a toy dialect.
The negative tests matter as much: a local class called ``Agent`` is not an agent, and
an unresolvable reference is left out rather than guessed, because a wrong edge widens
what an "apply to sub-agents" policy reaches.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

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
# OpenAI Agents SDK
# ---------------------------------------------------------------------------


def test_openai_agents_handoffs_tools_and_as_tool(tmp_path):
    _write(
        tmp_path,
        "support/tools.py",
        """
        from agents import function_tool

        @function_tool
        def lookup_invoice(invoice_id: str) -> str:
            return "paid"

        @function_tool(name_override="issue_refund")
        def refund(invoice_id: str) -> str:
            return "ok"
        """,
    )
    _write(
        tmp_path,
        "support/agents.py",
        """
        from agents import Agent, handoff
        from .tools import lookup_invoice, refund

        billing_agent = Agent(
            name="Billing agent",
            instructions="Answer billing questions.",
            tools=[lookup_invoice],
        )
        refund_agent = Agent(name="Refund agent", instructions="Refunds.", tools=[refund])
        translator = Agent(name="Translator", instructions="Translate.")

        triage_agent = Agent(
            name="Triage agent",
            instructions="Route the customer.",
            handoffs=[billing_agent, handoff(refund_agent)],
            tools=[translator.as_tool(tool_name="translate", tool_description="Translate")],
        )
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert set(agents) == {"billing-agent", "refund-agent", "translator", "triage-agent"}
    assert agents["billing-agent"]["tools"] == ["lookup_invoice"]
    assert agents["refund-agent"]["tools"] == ["issue_refund"]
    assert agents["triage-agent"]["tools"] == []  # an agent used as a tool is an edge
    assert agents["triage-agent"]["framework"] == "OpenAI Agents SDK"
    assert agents["triage-agent"]["file"] == "support/agents.py"
    assert _edges(report) == {
        ("triage-agent", "billing-agent", "handoff"),
        ("triage-agent", "refund-agent", "handoff"),
        ("triage-agent", "translator", "as_tool"),
    }
    assert "OpenAI Agents SDK" in report.frameworks
    assert report.multi_agent


def test_cross_file_reference_resolves_by_module_level_name(tmp_path):
    _write(
        tmp_path,
        "app/billing.py",
        """
        from agents import Agent
        billing_agent = Agent(name="Billing", instructions="Bill.")
        """,
    )
    _write(
        tmp_path,
        "app/triage.py",
        """
        from agents import Agent
        from app.billing import billing_agent
        triage = Agent(name="Triage", instructions="Route.", handoffs=[billing_agent])
        """,
    )
    assert _edges(scan(tmp_path)) == {("triage", "billing", "handoff")}


def test_a_local_agent_class_is_not_an_agent(tmp_path):
    _write(
        tmp_path,
        "agents/__init__.py",
        """
        class Agent:
            def __init__(self, name):
                self.name = name
        """,
    )
    _write(
        tmp_path,
        "main.py",
        """
        from agents import Agent
        from mylib import Agent as Other
        a = Agent("worker")
        b = Other(name="x", tools=[])
        """,
    )
    assert scan(tmp_path).agents == []


def test_unresolvable_handoff_is_left_out(tmp_path):
    _write(
        tmp_path,
        "bot.py",
        """
        from agents import Agent
        a = Agent(name="A", instructions="x", handoffs=[make_agent_somehow()])
        b = Agent(name="B", instructions="y")
        """,
    )
    report = scan(tmp_path)
    assert set(_agents(report)) == {"a", "b"}
    assert report.agent_edges == []


# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------


def test_langgraph_supervisor_delegates_to_react_agents(tmp_path):
    _write(
        tmp_path,
        "team/graph.py",
        """
        from langchain_core.tools import tool
        from langgraph.prebuilt import create_react_agent
        from langgraph_supervisor import create_supervisor

        @tool
        def web_search(query: str) -> str:
            '''Search the web.'''
            return ""

        def add(a: int, b: int) -> int:
            return a + b

        research_agent = create_react_agent(model, tools=[web_search], name="research_expert")
        math_agent = create_react_agent(model, [add], name="math_expert")

        workflow = create_supervisor([research_agent, math_agent], model=model)
        app = workflow.compile()
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert agents["research-expert"]["tools"] == ["web_search"]
    assert agents["math-expert"]["tools"] == ["add"]
    assert agents["supervisor"]["kind"] == "supervisor"
    assert _edges(report) == {
        ("supervisor", "research-expert", "delegates"),
        ("supervisor", "math-expert", "delegates"),
    }


def test_langgraph_state_graph_supervisor_routes_to_worker_nodes(tmp_path):
    _write(
        tmp_path,
        "graph.py",
        """
        from typing import Literal
        from langgraph.graph import StateGraph, START, END
        from langgraph.prebuilt import create_react_agent
        from langgraph.types import Command

        researcher = create_react_agent(llm, tools=[tavily], name="researcher")

        def research_node(state) -> Command[Literal["supervisor"]]:
            result = researcher.invoke(state)
            return Command(update={"messages": result["messages"]}, goto="supervisor")

        def coder_node(state):
            response = llm.bind_tools([python_repl]).invoke(state["messages"])
            return {"messages": [response]}

        def supervisor_node(state) -> Command[Literal["researcher", "coder", "__end__"]]:
            choice = llm.with_structured_output(Router).invoke(state["messages"])
            return Command(goto=choice["next"])

        builder = StateGraph(State)
        builder.add_node("supervisor", supervisor_node)
        builder.add_node("researcher", research_node)
        builder.add_node("coder", coder_node)
        builder.add_edge(START, "supervisor")
        builder.add_edge("coder", "supervisor")
        graph = builder.compile(name="research_team")
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert agents["research-team"]["kind"] == "graph"
    assert agents["supervisor"]["kind"] == "supervisor"
    assert agents["coder"]["tools"] == ["python_repl"]
    assert agents["researcher"]["tools"] == ["tavily"]
    assert _edges(report) == {
        ("research-team", "supervisor", "member"),
        ("supervisor", "researcher", "delegates"),
        ("supervisor", "coder", "delegates"),
    }


def test_langgraph_conditional_edges_and_a_plain_pipeline(tmp_path):
    _write(
        tmp_path,
        "pipeline.py",
        """
        from langgraph.graph import StateGraph, END
        from langgraph.prebuilt import create_react_agent

        planner = create_react_agent(llm, tools=[plan_tool], name="planner")
        writer = create_react_agent(llm, tools=[write_tool], name="writer")
        editor = create_react_agent(llm, tools=[], name="editor")

        def route(state):
            if state["done"]:
                return END
            return "editor"

        g = StateGraph(State)
        g.add_node("planner", planner)
        g.add_node("writer", writer)
        g.add_node("editor", editor)
        g.add_node("format", format_output)
        g.add_edge("planner", "writer")
        g.add_conditional_edges("writer", route)
        g.add_edge("editor", "format")
        app = g.compile()
        """,
    )
    report = scan(tmp_path)
    # `format` is a plain function: a step, not an agent.
    assert "format" not in _agents(report)
    assert _edges(report) == {
        ("g", "planner", "member"),
        ("planner", "writer", "handoff"),
        ("writer", "editor", "delegates"),
    }


def test_langgraph_swarm_handoff_tools(tmp_path):
    _write(
        tmp_path,
        "swarm.py",
        """
        from langgraph.prebuilt import create_react_agent
        from langgraph_swarm import create_handoff_tool, create_swarm

        alice = create_react_agent(
            model, [add, create_handoff_tool(agent_name="Bob")], name="Alice"
        )
        bob = create_react_agent(
            model, [create_handoff_tool(agent_name="Alice")], name="Bob"
        )
        workflow = create_swarm([alice, bob], default_active_agent="Alice")
        """,
    )
    report = scan(tmp_path)
    assert _agents(report)["alice"]["tools"] == ["add"]
    assert _edges(report) >= {("alice", "bob", "handoff"), ("bob", "alice", "handoff")}
    assert ("workflow", "alice", "member") in _edges(report)


# ---------------------------------------------------------------------------
# CrewAI
# ---------------------------------------------------------------------------


def test_crewai_crew_members_and_delegation(tmp_path):
    _write(
        tmp_path,
        "crew/main.py",
        """
        from crewai import Agent, Crew, Process, Task
        from crewai_tools import SerperDevTool

        search_tool = SerperDevTool()

        researcher = Agent(
            role="Senior Research Analyst",
            goal="Find things",
            backstory="...",
            tools=[search_tool, SerperDevTool()],
            allow_delegation=True,
        )
        writer = Agent(role="Writer", goal="Write", backstory="...", allow_delegation=False)

        crew = Crew(agents=[researcher, writer], tasks=[t1, t2], process=Process.sequential)
        crew.kickoff()
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert agents["senior-research-analyst"]["tools"] == ["search_tool", "SerperDevTool"]
    assert agents["crew"]["kind"] == "crew"
    assert _edges(report) == {
        ("crew", "senior-research-analyst", "member"),
        ("crew", "writer", "member"),
        ("senior-research-analyst", "writer", "delegates"),
    }


def test_crewai_manager_agent_delegates_to_members(tmp_path):
    _write(
        tmp_path,
        "crew.py",
        """
        from crewai import Agent, Crew, Process

        manager = Agent(role="Project Manager", goal="g", backstory="b", allow_delegation=True)
        dev = Agent(role="Developer", goal="g", backstory="b")
        qa = Agent(role="QA", goal="g", backstory="b")
        team = Crew(agents=[dev, qa], tasks=[], manager_agent=manager, process=Process.hierarchical)
        """,
    )
    assert _edges(scan(tmp_path)) == {
        ("team", "project-manager", "member"),
        ("project-manager", "developer", "delegates"),
        ("project-manager", "qa", "delegates"),
    }


def test_crewai_crewbase_class_layout(tmp_path):
    _write(
        tmp_path,
        "src/research_crew/crew.py",
        """
        from crewai import Agent, Crew, Process, Task
        from crewai.project import CrewBase, agent, crew, task
        from crewai_tools import SerperDevTool

        @CrewBase
        class ResearchCrew:
            @agent
            def researcher(self) -> Agent:
                return Agent(config=self.agents_config["researcher"], tools=[SerperDevTool()])

            @agent
            def reporting_analyst(self) -> Agent:
                return Agent(config=self.agents_config["reporting_analyst"])

            @crew
            def crew(self) -> Crew:
                return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential)
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert agents["researcher"]["tools"] == ["SerperDevTool"]
    assert agents["researchcrew"]["kind"] == "crew"
    assert _edges(report) == {
        ("researchcrew", "researcher", "member"),
        ("researchcrew", "reporting-analyst", "member"),
    }


# ---------------------------------------------------------------------------
# AutoGen
# ---------------------------------------------------------------------------


def test_autogen_agentchat_team_and_tools(tmp_path):
    _write(
        tmp_path,
        "team.py",
        """
        from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
        from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat

        async def get_weather(city: str) -> str:
            return "sunny"

        weather = AssistantAgent("weather_agent", model_client=client, tools=[get_weather])
        critic = AssistantAgent(name="critic", model_client=client)
        user = UserProxyAgent("user")

        team = RoundRobinGroupChat([weather, critic], termination_condition=stop)
        selector = SelectorGroupChat(participants=[weather, critic, user], model_client=client)
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert agents["weather-agent"]["tools"] == ["get_weather"]
    assert "AutoGen" in report.frameworks
    assert _edges(report) == {
        ("team", "weather-agent", "member"),
        ("team", "critic", "member"),
        ("selector", "weather-agent", "delegates"),
        ("selector", "critic", "delegates"),
        ("selector", "user", "delegates"),
    }


def test_autogen_swarm_handoffs_by_name(tmp_path):
    _write(
        tmp_path,
        "swarm.py",
        """
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.teams import Swarm

        travel = AssistantAgent(
            "travel_agent", model_client=c, handoffs=["flights_refunder", "user"]
        )
        flights = AssistantAgent(
            "flights_refunder", model_client=c, handoffs=["travel_agent"], tools=[refund_flight]
        )
        team = Swarm([travel, flights])
        """,
    )
    edges = _edges(scan(tmp_path))
    assert ("travel-agent", "flights-refunder", "handoff") in edges
    assert ("flights-refunder", "travel-agent", "handoff") in edges


def test_ag2_group_chat_manager_runs_the_chat(tmp_path):
    _write(
        tmp_path,
        "chat.py",
        """
        import autogen

        coder = autogen.AssistantAgent(name="Coder", llm_config=cfg)
        pm = autogen.AssistantAgent(name="Product_manager", llm_config=cfg)
        groupchat = autogen.GroupChat(agents=[coder, pm], messages=[], max_round=12)
        manager = autogen.GroupChatManager(groupchat=groupchat, name="chat_manager", llm_config=cfg)
        """,
    )
    report = scan(tmp_path)
    assert "groupchat" not in _agents(report)
    assert _edges(report) == {
        ("chat-manager", "coder", "delegates"),
        ("chat-manager", "product-manager", "delegates"),
    }


# ---------------------------------------------------------------------------
# Google ADK
# ---------------------------------------------------------------------------


def test_google_adk_sub_agents_and_agent_tool(tmp_path):
    _write(
        tmp_path,
        "adk/agent.py",
        """
        from google.adk.agents import Agent, SequentialAgent
        from google.adk.tools.agent_tool import AgentTool

        greeter = Agent(name="greeter", model="gemini-2.0-flash", tools=[say_hello])
        searcher = Agent(name="searcher", model="gemini-2.0-flash")
        root_agent = Agent(
            name="coordinator",
            model="gemini-2.0-flash",
            sub_agents=[greeter],
            tools=[AgentTool(agent=searcher), get_time],
        )
        pipeline = SequentialAgent(name="pipeline", sub_agents=[root_agent])
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert agents["coordinator"]["tools"] == ["get_time"]
    assert "Google ADK" in report.frameworks
    assert _edges(report) == {
        ("coordinator", "greeter", "delegates"),
        ("coordinator", "searcher", "as_tool"),
        ("pipeline", "coordinator", "member"),
    }


# ---------------------------------------------------------------------------
# TypeScript — OpenAI Agents SDK
# ---------------------------------------------------------------------------


def test_openai_agents_typescript(tmp_path):
    _write(
        tmp_path,
        "src/agents.ts",
        """
        import { Agent, tool, handoff } from '@openai/agents';
        import { z } from 'zod';

        const getWeather = tool({
          name: 'get_weather',
          description: 'Weather for a city',
          parameters: z.object({ city: z.string() }),
          execute: async ({ city }) => `sunny in ${city}`,
        });

        const weatherAgent = new Agent({ name: 'Weather', instructions: 'W', tools: [getWeather] });
        const summarizer = new Agent({ name: 'Summarizer', instructions: 'Summarize, short.' });
        export const triage = Agent.create({
          name: 'Triage',
          instructions: 'Route, then answer.',
          handoffs: [weatherAgent],
          tools: [summarizer.asTool({ toolName: 'summarize' })],
        });
        """,
    )
    report = scan(tmp_path)
    agents = _agents(report)
    assert agents["weather"]["tools"] == ["get_weather"]
    assert _edges(report) == {
        ("triage", "weather", "handoff"),
        ("triage", "summarizer", "as_tool"),
    }


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


def test_json_and_submission_payload_carry_the_structure(tmp_path):
    _write(
        tmp_path,
        "bots/team.py",
        """
        from agents import Agent, function_tool

        @function_tool
        def secret_internal_tool() -> str:
            return ""

        b = Agent(name="B", instructions="b", tools=[secret_internal_tool])
        a = Agent(name="A", instructions="a", handoffs=[b])
        """,
    )
    report = scan(tmp_path)
    data = report.to_json()
    assert {a["key"] for a in data["agents"]} == {"a", "b"}
    assert data["agent_edges"] == [{"parent": "a", "child": "b", "relation": "handoff"}]
    # Existing keys are untouched.
    assert data["agent_definitions"] == 0 and "sites" in data

    payload = report.to_submission_payload(source="check")
    assert payload["agents"] == [
        {
            "key": "b",
            "name": "B",
            "framework": "OpenAI Agents SDK",
            "kind": "agent",
            "top_dir": "bots",
        },
        {
            "key": "a",
            "name": "A",
            "framework": "OpenAI Agents SDK",
            "kind": "agent",
            "top_dir": "bots",
        },
    ]
    assert payload["agent_edges"] == [{"parent": "a", "child": "b", "relation": "handoff"}]
    # No file paths, lines or tool names leave the machine.
    dumped = repr(payload["agents"]) + repr(payload["agent_edges"])
    assert "team.py" not in dumped and "secret_internal_tool" not in dumped


def test_single_agent_repo_sends_no_structure(tmp_path):
    _write(
        tmp_path,
        "bot.py",
        """
        from agents import Agent
        solo = Agent(name="Solo", instructions="x")
        """,
    )
    report = scan(tmp_path)
    assert len(report.agents) == 1 and not report.multi_agent
    payload = report.to_submission_payload(source="check")
    assert payload["agents"] == [] and payload["agent_edges"] == []


def test_terminal_summary_names_who_hands_work_to_whom(tmp_path):
    _write(
        tmp_path,
        "bots.py",
        """
        from agents import Agent
        b = Agent(name="Billing", instructions="b")
        r = Agent(name="Refunds", instructions="r")
        t = Agent(name="Triage", instructions="t", handoffs=[b, r])
        """,
    )
    assert scan(tmp_path).agent_summary() == [
        "3 agents, 2 handoff(s) between them",
        "triage hands off to billing, refunds",
    ]
