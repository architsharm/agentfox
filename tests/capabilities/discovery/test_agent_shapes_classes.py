"""Agent shapes the third launch audit found the scan missing, from small snippets.

* a LangGraph agent a class builds (``self.tools = [...]``, then
  ``create_react_agent(self.model, tools=self.tools)``): its tools, model and name;
* the Agents SDK's ``writer.clone(tools=[a.as_tool(...)])``: the agents it calls;
* a hierarchical CrewAI crew's ``manager_llm``;
* an agent built on the repository's own ``Agent`` class, in a package named like a
  framework (``agents``, ``a2a_mcp``): labelled by what it talks to, not the package;
* ``Tool`` subclasses that name themselves, and an MCP server the repository serves.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from agentfox.capabilities.discovery.repo import ScanReport, scan


def _scan(root: Path, files: dict[str, str]) -> ScanReport:
    for rel, source in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip())
    return scan(root)


def _agents(report: ScanReport) -> dict[str, dict]:
    return {a.key: a.to_json() for a in report.agents}


def _edges(report: ScanReport) -> set[tuple[str, str, str]]:
    return {(e.parent, e.child, e.relation) for e in report.agent_edges}


def test_a_langgraph_agent_built_in_a_class_has_its_tools_model_and_name(tmp_path):
    report = _scan(
        tmp_path,
        {
            "svc/agent.py": '''
            from langchain_core.tools import tool
            from langchain_openai import ChatOpenAI
            from langgraph.prebuilt import create_react_agent

            @tool
            def lookup_rate(base: str) -> str:
                """Look up a rate."""
                return ""

            class PriceAgent:
                def __init__(self):
                    self.model = ChatOpenAI(model="gpt-4o-mini")
                    self.tools = [lookup_rate]
                    self.graph = create_react_agent(self.model, tools=self.tools)

                def ask(self, q):
                    return self.graph.invoke({"messages": [q]})
            '''
        },
    )
    agents = _agents(report)
    assert list(agents) == ["price-agent"]
    agent = agents["price-agent"]
    assert agent["name"] == "PriceAgent"
    assert agent["tools"] == ["lookup_rate"]
    assert agent["model"] == "gpt-4o-mini"
    assert report.unassigned_tools == []


def test_an_agents_sdk_clone_handed_agents_as_tools_calls_them(tmp_path):
    report = _scan(
        tmp_path,
        {
            "app/team.py": """
            from agents import Agent

            checker = Agent(name="CheckerAgent", instructions="check", model="gpt-4o")
            writer = Agent(name="WriterAgent", instructions="write")
            """,
            "app/run.py": """
            from agents import Runner
            from app.team import checker, writer

            def build():
                return writer.clone(tools=[checker.as_tool(tool_name="check_it")])
            """,
        },
    )
    assert ("writer-agent", "checker-agent", "as_tool") in _edges(report)


def test_a_hierarchical_crew_runs_on_its_manager_llm(tmp_path):
    report = _scan(
        tmp_path,
        {
            "crew/crew.py": """
            from crewai import Agent, Crew, Process, Task
            from crewai.project import CrewBase, agent, crew, task
            from langchain_openai import ChatOpenAI

            @CrewBase
            class PartyCrew:
                @agent
                def caterer(self) -> Agent:
                    return Agent(config=self.agents_config["caterer"])

                @agent
                def florist(self) -> Agent:
                    return Agent(config=self.agents_config["florist"])

                @crew
                def crew(self) -> Crew:
                    return Crew(agents=self.agents, tasks=self.tasks,
                                process=Process.hierarchical,
                                manager_llm=ChatOpenAI(model="gpt-4o"))
            """
        },
    )
    agents = _agents(report)
    assert agents["party-crew"]["model"] == "gpt-4o"
    assert {("party-crew", "caterer", "delegates"), ("party-crew", "florist", "delegates")} <= (
        _edges(report)
    )


_LOCAL_AGENT = {
    "bot/core/agent.py": """
    import anthropic

    class Agent:
        def __init__(self, name, system, tools):
            self.client = anthropic.Anthropic()
            self.name, self.tools = name, tools

        def run(self, msg):
            return self.client.messages.create(
                model="claude-x", max_tokens=10, messages=[], tools=[t.spec() for t in self.tools]
            )
    """,
    "bot/core/__init__.py": "",
    "bot/tools/base.py": """
    class Tool:
        name: str
        description: str
    """,
    "bot/tools/files.py": '''
    from .base import Tool

    class FileWriteTool(Tool):
        """Write a file to disk."""

        def __init__(self):
            super().__init__(name="file_write", description="Write a file")

        async def execute(self, path, content): ...

    class ShellTool(Tool):
        name = "run_shell"
        description = "Run a shell command"

        async def execute(self, command): ...
    ''',
    "bot/servers/calc.py": """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("calculator")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        return a + b
    """,
    "agents/__init__.py": "",
    "agents/agent.py": """
    from bot.core.agent import Agent as Base

    class Agent(Base):
        pass
    """,
    "main.py": """
    from agents.agent import Agent
    from bot.tools.files import FileWriteTool, ShellTool

    assistant = Agent(name="file-assistant", system="help", tools=[FileWriteTool(), ShellTool()])
    """,
}


def test_an_agent_on_the_repos_own_agent_class_is_not_the_agents_sdk(tmp_path):
    report = _scan(tmp_path, _LOCAL_AGENT)
    agents = _agents(report)
    assert agents["file-assistant"]["framework"] != "OpenAI Agents SDK"
    assert "OpenAI Agents SDK" not in report.frameworks
    assert not agents["file-assistant"]["default_model"]


def test_tool_classes_are_named_by_the_name_they_give_themselves(tmp_path):
    report = _scan(tmp_path, _LOCAL_AGENT)
    assert _agents(report)["file-assistant"]["tools"] == ["file_write", "run_shell"]
    reach = {s.name for s in report.tools}
    assert {"file_write", "run_shell", "add"} <= reach


def test_an_mcp_server_the_repo_serves_counts_as_an_mcp_server(tmp_path):
    report = _scan(tmp_path, _LOCAL_AGENT)
    assert [s.name for s in report.mcp_servers] == ["calculator"]


def test_the_agents_sdk_is_still_the_agents_sdk_beside_a_file_named_agents(tmp_path):
    report = _scan(
        tmp_path,
        {
            "app/agents.py": """
            from agents import Agent

            helper = Agent(name="HelperAgent", instructions="help", model="gpt-4o")
            """
        },
    )
    assert _agents(report)["helper-agent"]["framework"] == "OpenAI Agents SDK"


def test_a_class_agent_on_a_local_base_is_labelled_by_the_protocol_it_uses(tmp_path):
    report = _scan(
        tmp_path,
        {
            "a2a_kit/__init__.py": "",
            "a2a_kit/base_agent.py": """
            class BaseAgent:
                def __init__(self, agent_name, description):
                    self.agent_name = agent_name
            """,
            "orchestrator/agent.py": """
            import httpx
            from a2a.client import A2AClient
            from a2a_kit.base_agent import BaseAgent

            class OrchestratorAgent(BaseAgent):
                async def stream(self, query):
                    client = A2AClient(httpx.AsyncClient(), url="http://localhost:1")
                    return await client.send_message(query)
            """,
        },
    )
    assert _agents(report)["orchestrator-agent"]["framework"] == "A2A"
    assert "a2a_kit" not in report.frameworks


_LLAMA_STATE = '''
from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent
from llama_index.core.workflow import Context
from llama_index.tools.tavily_research import TavilyToolSpec


async def record_notes(ctx: Context, notes: str, notes_title: str) -> str:
    """Record notes on a given topic."""
    state = await ctx.store.get("state")
    state["research_notes"][notes_title] = notes
    await ctx.store.set("state", state)
    return "Notes recorded."


async def write_report(ctx: Context, report_content: str) -> str:
    """Write a report on a given topic."""
    state = await ctx.store.get("state")
    state["report_content"] = report_content
    await ctx.store.set("state", state)
    return "Report written."


async def review_report(ctx: Context, review: str) -> str:
    """Review a report and provide feedback."""
    state = await ctx.store.get("state")
    state["review"] = review
    await ctx.store.set("state", state)
    return "Report reviewed."


research = FunctionAgent(name="ResearchAgent", description="r", system_prompt="s",
                         tools=[record_notes])
write = FunctionAgent(name="WriteAgent", description="w", system_prompt="s",
                      tools=[write_report])
review = FunctionAgent(name="ReviewAgent", description="v", system_prompt="s",
                       tools=[review_report])
workflow = AgentWorkflow(agents=[research, write, review], root_agent="ResearchAgent")
'''


def test_tools_that_only_touch_the_run_state_are_no_trifecta(tmp_path):
    """Three LlamaIndex tools that only read and write `ctx.store` read as private
    data, untrusted input and a way out by their names: a critical that was not one."""
    report = _scan(tmp_path, {"workflow.py": _LLAMA_STATE})
    assert not report.trifectas
    tools = {s.name: s for s in report.tools}
    assert {"record_notes", "write_report", "review_report"} <= set(tools)
    assert all(not tools[n].capabilities for n in ("record_notes", "write_report"))


_TRIFECTA_SYSTEM = '''
from agents import Agent, function_tool


@function_tool
def read_customer_records(customer_id: str) -> str:
    """Read the customer's private records from the CRM database."""
    return ""


@function_tool
def fetch_web_page(url: str) -> str:
    """Fetch any web page from the internet."""
    return ""


@function_tool
def send_email(to: str, body: str) -> str:
    """Send an email to any address."""
    return ""


MailerAgent = Agent(name="MailerAgent", instructions="m",
                    tools=[read_customer_records, fetch_web_page, send_email])
FrontDesk = Agent(name="FrontDesk", instructions="route", handoffs=[MailerAgent])
'''


def test_contain_it_names_the_agent_auto_reports_as(tmp_path):
    """The fix named the draft (`writeagent`), not the agent `up` registers and
    `auto()` reports as: the root of the system, under the one slug every path uses."""
    report = _scan(tmp_path, {"desk.py": _TRIFECTA_SYSTEM})
    (trifecta,) = report.trifectas
    assert "agentfox permit grant front-desk send_email" in trifecta.evidence["fix"]


def test_agentfox_itself_is_not_a_framework_the_app_is_built_on(tmp_path):
    report = _scan(
        tmp_path,
        {
            "main.py": """
            import agentfox
            from openai import OpenAI

            agentfox.auto("helper")
            OpenAI().chat.completions.create(model="gpt-4o", messages=[])
            """
        },
    )
    assert "AgentFox" not in report.frameworks
    assert report.model_calls and all(s.governed for s in report.model_calls)
