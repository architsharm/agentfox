"""Agents found by shape, not by a framework the scanner was told about.

Each fixture is a shape any framework may use: an imported constructor given tools and
an instruction, an agent class, a decorator that registers a tool on an agent, a
LangGraph graph whose nodes call a model, a TypeScript agent factory. None names a
specific project. The negatives matter as much: a data class about an agent, a task
and a helper that takes tools are not agents, and a variable that holds a list is
never reported as a tool named after it.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from agentfox.capabilities.discovery.repo import scan


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip())


def _by_name(report):
    return {a.name: a for a in report.agents}


def test_an_imported_constructor_given_tools_and_instructions_is_an_agent(tmp_path):
    _write(
        tmp_path,
        "bot.py",
        """
        from someframework import Agent, Task

        def lookup(order_id: str) -> str:
            "Look an order up."
            return order_id

        support = Agent(name="Support", instructions="Help customers.", tools=[lookup])
        job = Task(description="Answer the ticket", tools=[lookup])
        """,
    )
    agents = _by_name(scan(tmp_path))
    assert set(agents) == {"Support"}  # the Task takes tools too, and is not an agent
    support = agents["Support"]
    assert support.tools == ["lookup"]
    assert (support.framework, support.confidence) == ("someframework", "medium")
    assert "agent-shaped call" in support.evidence


def test_a_data_class_or_helper_about_an_agent_is_not_one(tmp_path):
    _write(
        tmp_path,
        "cfg.py",
        """
        from someframework import AgentConfig, count_tokens

        cfg = AgentConfig(name="x", model="m", tools=[])
        n = count_tokens(model="m", tools=[], messages=[])
        """,
    )
    assert scan(tmp_path).agents == []


def test_tools_registered_by_decorator_belong_to_that_agent(tmp_path):
    _write(
        tmp_path,
        "bank.py",
        """
        from someframework import Agent

        support_agent = Agent("openai:gpt-4o", system_prompt="Bank support.")

        @support_agent.tool
        def balance(ctx, account: str) -> float:
            return 0.0
        """,
    )
    [agent] = scan(tmp_path).agents
    assert agent.tools == ["balance"]


def test_a_subclass_of_an_agent_base_is_a_low_confidence_agent(tmp_path):
    _write(
        tmp_path,
        "roles.py",
        """
        from someframework.roles import Role

        def write_spec(text: str) -> str:
            return text

        class BaseAgentMixin(Role):
            pass

        class Architect(Role):
            def __init__(self):
                self.set_actions([write_spec])
        """,
    )
    [agent] = scan(tmp_path).agents
    assert (agent.name, agent.confidence, agent.tools) == ("Architect", "low", ["write_spec"])


def test_a_variable_holding_a_tool_list_is_never_a_tool(tmp_path):
    _write(
        tmp_path,
        "graph.py",
        """
        from someframework import Agent

        def make(tools):
            return Agent(name="Worker", instructions="Work.", tools=tools)
        """,
    )
    [agent] = scan(tmp_path).agents
    assert agent.tools == []


def test_a_langgraph_graph_of_model_calls_is_one_workflow_agent(tmp_path):
    _write(
        tmp_path,
        "flow.py",
        """
        from langchain_openai import ChatOpenAI
        from langgraph.graph import StateGraph

        llm = ChatOpenAI(model="gpt-4o")

        def plan(state):
            return {"plan": llm.invoke(state["q"]).content}

        def write(state):
            return {"answer": llm.invoke(state["plan"]).content}

        builder = StateGraph(dict)
        builder.add_node("plan", plan)
        builder.add_node("write", write)
        builder.add_edge("plan", "write")
        graph = builder.compile(name="report-writer")
        """,
    )
    [agent] = scan(tmp_path).agents
    assert (agent.name, agent.kind, agent.confidence) == ("report-writer", "agent", "medium")
    assert "workflow" in agent.evidence


def test_tools_bound_at_module_level_reach_the_node_that_uses_them(tmp_path):
    _write(
        tmp_path,
        "assistant.py",
        """
        from langchain_core.tools import tool
        from langchain_openai import ChatOpenAI
        from langgraph.graph import StateGraph
        from langgraph.prebuilt import ToolNode

        @tool
        def send_email(to: str, body: str) -> str:
            "Send an email."
            return "sent"

        llm_with_tools = ChatOpenAI(model="gpt-4o").bind_tools([send_email])

        def llm_call(state):
            return {"messages": [llm_with_tools.invoke(state["messages"])]}

        graph = (
            StateGraph(dict)
            .add_node("llm_call", llm_call)
            .add_node("tools", ToolNode([send_email]))
            .add_edge("llm_call", "tools")
            .compile()
        )
        """,
    )
    agents = scan(tmp_path).agents
    # One agent, not the graph and its single node counted twice; tools found through
    # the module-level binding and through a fluent StateGraph chain.
    assert len(agents) == 1
    assert agents[0].tools == ["send_email"]


def test_typescript_agents_by_shape(tmp_path):
    _write(
        tmp_path,
        "src/agents.ts",
        """
        import { createReactAgent } from "@langchain/langgraph/prebuilt";
        import { streamText, tool } from "ai";

        const lookup = tool({ description: "Look up", parameters: {} });
        export const helper = createReactAgent({ llm, tools: [lookup], name: "helper" });

        export async function POST(req) {
          return streamText({ model, messages, tools: { getWeather, createDocument } });
        }
        """,
    )
    agents = _by_name(scan(tmp_path))
    assert agents["helper"].tools == ["lookup"]
    assert agents["helper"].framework == "LangGraph"
    vercel = next(a for a in agents.values() if a.name != "helper")
    assert sorted(vercel.tools) == ["createDocument", "getWeather"]


def test_an_app_that_only_calls_a_model_is_reported_at_low_confidence(tmp_path):
    _write(
        tmp_path,
        "search/rank.py",
        """
        from openai import OpenAI

        client = OpenAI()

        def rank(q):
            msgs = [{"role": "user", "content": q}]
            return client.chat.completions.create(model="gpt-4o", messages=msgs)
        """,
    )
    assert scan(tmp_path).agents == []  # a discovery submission proposes nothing
    [agent] = scan(tmp_path, llm_apps=True).agents  # `agentfox init` says what it saw
    assert (agent.name, agent.confidence) == ("search", "low")
    assert "no agent structure" in agent.evidence


def test_gitignored_and_generated_code_is_not_read(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _write(tmp_path, ".gitignore", "build/\n")
    _write(
        tmp_path,
        "build/gen.py",
        """
        from someframework import Agent
        a = Agent(name="Generated", instructions="x", tools=[])
        """,
    )
    _write(
        tmp_path,
        "app.py",
        """
        from someframework import Agent
        a = Agent(name="Real", instructions="x", tools=[])
        """,
    )
    (tmp_path / "bundle.js").write_text("x" * 1_100_000)
    report = scan(tmp_path)
    assert [a.name for a in report.agents] == ["Real"]
    assert report.skipped_suffixes.get("(generated or minified)") == 1
