"""What a new user's first `agentfox scan` got wrong, on public agent repositories.

A walkthrough on 2026-11-08 pointed the scan at LangGraph's repository, the LangGraph
ReAct template, the Agents SDK's examples and crewAI-examples, and found results a
security engineer would distrust on sight:

* "2039 of 8 model call sites are ungoverned": every `StateGraph(...)` and every
  `re.compile` in a file importing LangGraph was counted into the numerator only;
* the ReAct template's real model call (`load_chat_model(...).bind_tools(...)
  .ainvoke(...)`) was missed while `StateGraph(...)` / `builder.compile()` were listed;
* three Agents SDK agents, then "No model calls found";
* "ReAct Agent · 1 tool" above "can reach: 0 tools";
* "can read user datas", `permit grant <agent>`, and a trifecta built from tools of
  separate scripts in one directory;
* the repository root reporting the agents and tools its tests define.

Each fixture is the general shape, written fresh here; none is copied from those repos.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.capabilities.discovery.exposure import PRIVATE, UNTRUSTED, classify_tool
from agentfox.capabilities.discovery.repo import is_excluded_path, scan
from agentfox.capabilities.onboarding.mapper import map_repository

runner = CliRunner()


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip())


def flat(output: str) -> str:
    return " ".join(output.replace("│", " ").split())


# ---------------------------------------------------------------------------
# Model calls: definitions are not calls; runs are
# ---------------------------------------------------------------------------


def test_graph_definitions_and_regexes_are_not_model_calls(tmp_path):
    _write(
        tmp_path,
        "app/graph.py",
        """
        import re
        from langgraph.graph import StateGraph

        PATTERN = re.compile(r"\\d+")
        builder = StateGraph(dict)
        graph = builder.compile()
        """,
    )
    report = scan(tmp_path)
    assert report.model_calls == []
    assert [s.detail for s in report.agent_definitions] == ["StateGraph(...)"]
    assert report.agent_definitions[0].severity == "info"
    assert report.ungoverned == []


def test_ungoverned_never_exceeds_the_calls_it_is_a_share_of(tmp_path):
    for n in range(5):
        _write(
            tmp_path,
            f"g{n}.py",
            """
            from langgraph.graph import StateGraph
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(model="gpt-4o")
            builder = StateGraph(dict)

            def node(state):
                return {"messages": [llm.invoke(state["messages"])]}
            """,
        )
    report = scan(tmp_path)
    assert len(report.ungoverned) <= len(report.model_calls) == 5


def test_a_chat_model_bound_to_tools_is_a_model_call(tmp_path):
    """The ReAct template's shape: the model comes from a helper, so only the
    `.bind_tools(...)` says it is one; the call passes its messages positionally."""
    _write(
        tmp_path,
        "agent/graph.py",
        """
        from langgraph.graph import StateGraph
        from agent.utils import load_chat_model
        from agent.tools import TOOLS

        async def call_model(state, runtime):
            model = load_chat_model(runtime.context.model).bind_tools(TOOLS)
            response = await model.ainvoke([{"role": "system", "content": "x"}])
            return {"messages": [response]}

        builder = StateGraph(dict)
        builder.add_node(call_model)
        graph = builder.compile(name="ReAct Agent")
        """,
    )
    report = scan(tmp_path)
    assert [(s.line, s.provider) for s in report.model_calls] == [(7, "langchain")]


def test_a_prompt_template_invoke_is_still_not_a_model_call(tmp_path):
    _write(
        tmp_path,
        "chain.py",
        """
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([("system", "x")])
        text = prompt.invoke({"q": "hi"})
        """,
    )
    assert scan(tmp_path).model_calls == []


def test_running_a_compiled_graph_is_a_model_call(tmp_path):
    _write(
        tmp_path,
        "run.py",
        """
        from langgraph.graph import StateGraph
        from langgraph.prebuilt import create_react_agent

        builder = StateGraph(dict)
        graph = builder.compile()
        agent = create_react_agent("openai:gpt-4o", tools=[])
        graph.invoke({"messages": []})
        agent.stream({"messages": []})
        """,
    )
    calls = scan(tmp_path).model_calls
    assert [(s.line, s.provider) for s in calls] == [(7, "langgraph"), (8, "langgraph")]
    assert all("runs the graph" in s.detail for s in calls)


def test_an_agents_sdk_run_is_a_model_call_only_with_the_sdk_imported(tmp_path):
    _write(
        tmp_path,
        "main.py",
        """
        from agents import Agent, Runner

        triage = Agent(name="Triage", instructions="Route the request.")

        async def main():
            await Runner.run(triage, "hi")
            Runner.run_sync(triage, "hi")
        """,
    )
    _write(tmp_path, "other/runner.py", "class Runner: ...\nRunner.run(1, 2)\n")
    report = scan(tmp_path)
    assert [(s.file, s.provider) for s in report.model_calls] == [
        ("main.py", "openai-agents"),
        ("main.py", "openai-agents"),
    ]
    # Agents and a call that runs them: not "No model calls found".
    assert "No model calls found" not in report.next_step()


def test_a_crew_kickoff_is_a_model_call(tmp_path):
    _write(
        tmp_path,
        "crew/main.py",
        """
        from crewai import Agent, Crew, Task

        writer = Agent(role="Writer", goal="Write", backstory="b")
        crew = Crew(agents=[writer], tasks=[Task(description="d", agent=writer)])
        result = crew.kickoff(inputs={"topic": "x"})
        """,
    )
    report = scan(tmp_path)
    assert [s.provider for s in report.model_calls] == ["crewai"]
    assert [s.detail for s in report.agent_definitions] == ["Crew(...)"]


def test_a_typescript_agents_sdk_run_is_a_model_call(tmp_path):
    _write(
        tmp_path,
        "index.ts",
        """
        import { Agent, run } from "@openai/agents";
        const agent = new Agent({ name: "Helper", instructions: "Help." });
        const result = await run(agent, "hi");
        """,
    )
    _write(tmp_path, "other.ts", "function run(x: number) { return x; }\nrun(1);\n")
    calls = scan(tmp_path).model_calls
    assert [(s.file, s.provider) for s in calls] == [("index.ts", "openai-agents")]


def test_agents_found_but_never_run_do_not_read_as_no_model_calls(tmp_path):
    _write(
        tmp_path,
        "app.py",
        """
        from agents import Agent

        helper = Agent(name="Helper", instructions="Help.")
        """,
    )
    report = scan(tmp_path)
    assert report.agents and not report.model_calls
    step = report.next_step()
    assert "No model calls found" not in step and "Found 1 agent(s)" in step


# ---------------------------------------------------------------------------
# Tools handed over as plain functions
# ---------------------------------------------------------------------------


def test_a_plain_function_in_a_tool_list_is_a_tool_the_agent_can_reach(tmp_path):
    _write(
        tmp_path,
        "agent/tools.py",
        """
        def search(query: str) -> dict:
            \"\"\"Search for general web results.\"\"\"
            return {}

        TOOLS = [search]
        """,
    )
    _write(
        tmp_path,
        "agent/graph.py",
        """
        from langgraph.graph import StateGraph
        from langgraph.prebuilt import ToolNode
        from langchain.chat_models import init_chat_model
        from agent.tools import TOOLS

        def call_model(state):
            model = init_chat_model("gpt-4o").bind_tools(TOOLS)
            return {"messages": [model.invoke(state["messages"])]}

        builder = StateGraph(dict)
        builder.add_node(call_model)
        builder.add_node("tools", ToolNode(TOOLS))
        graph = builder.compile(name="ReAct Agent")
        """,
    )
    report = scan(tmp_path)
    (agent,) = report.agents
    assert agent.tools == ["search"]
    # The count on the agent line and the "can reach" line agree, and `up` (which
    # declares `report.tools`) declares it.
    assert [(s.name, s.file) for s in report.tools] == [("search", "agent/tools.py")]
    assert UNTRUSTED in report.tools[0].capabilities


def test_a_tool_that_opens_any_path_it_is_given_reads_private_data(tmp_path):
    _write(
        tmp_path,
        "tools.py",
        """
        from crewai.tools import tool

        @tool("markdown_validation_tool")
        def markdown_validation_tool(file_path: str) -> str:
            \"\"\"Review a markdown file for syntax errors.\"\"\"
            return open(file_path).read()
        """,
    )
    (site,) = scan(tmp_path).tools
    assert site.capabilities == [PRIVATE]
    assert "any file path" in site.detail


def test_path_arguments_do_not_make_every_tool_a_private_read():
    assert classify_tool("save_report", "Save the report.", ["path", "text"]).flags == set()
    assert classify_tool("get_weather", "Weather for a city.", ["city"]).flags == set()
    assert PRIVATE in classify_tool("summarize", "Summarize a document.", ["file_path"]).flags
    # Without the argument names, a description that says it takes a file path.
    assert PRIVATE in classify_tool("lint", "Takes the path to the markdown file.").flags


# ---------------------------------------------------------------------------
# A model the code does not set
# ---------------------------------------------------------------------------


def test_an_agent_without_a_model_runs_the_framework_default(tmp_path):
    _write(
        tmp_path,
        "main.py",
        """
        from agents import Agent

        def build_model(settings):
            return settings.model

        plain = Agent(name="Plain", instructions="Help.")
        chosen = Agent(name="Chosen", instructions="Help.", model="gpt-4o")
        runtime = Agent(name="Runtime", instructions="Help.", model=build_model(None))
        """,
    )
    report = scan(tmp_path)
    agents = {a.name: a for a in report.agents}
    assert agents["Plain"].model is None and agents["Plain"].default_model is True
    assert agents["Chosen"].model == "gpt-4o" and agents["Chosen"].default_model is False
    # Chosen at run time is unknown, not the framework default.
    assert agents["Runtime"].model is None and agents["Runtime"].default_model is False
    assert agents["Plain"].to_json()["default_model"] is True

    mapped = {a["name"]: a for a in map_repository(tmp_path)["structure"]["agents"]}
    assert mapped["Plain"]["model"] == "OpenAI Agents SDK default"
    assert mapped["Plain"]["models"] == []  # no model id to declare
    assert mapped["Runtime"]["model"] == "unknown model"

    out = flat(runner.invoke(app, ["scan", str(tmp_path), "--no-submit"]).output)
    assert "plain OpenAI Agents SDK · default model" in out  # listed by key


# ---------------------------------------------------------------------------
# Wording, and which tools make one trifecta
# ---------------------------------------------------------------------------


def test_private_data_phrases_read_as_english():
    assert classify_tool("get_user_data").phrases[PRIVATE] == "can read user data"
    assert classify_tool("get_contact_info").phrases[PRIVATE] == "can read contact info"
    assert classify_tool("inspect_secret").phrases[PRIVATE] == "can read secrets"
    assert classify_tool("read_customer_record").phrases[PRIVATE] == "can read customer records"


TOOLS = """
from agents import Agent, function_tool

@function_tool
def get_user_data(user_id: str) -> str:
    \"\"\"Look up a user.\"\"\"

@function_tool
def fetch_web_page(url: str) -> str:
    \"\"\"Fetch a web page.\"\"\"

@function_tool
def send_email(to: str, body: str) -> str:
    \"\"\"Send an email.\"\"\"
"""
READER = (
    'reader = Agent(name="Reader", instructions="Read.", tools=[get_user_data, fetch_web_page])\n'
)
MAILER = 'mailer = Agent(name="Mailer", instructions="Mail.", tools=[send_email])\n'


def test_separate_scripts_in_one_directory_are_not_one_trifecta(tmp_path):
    _write(tmp_path, "examples/basic/reader.py", TOOLS + READER)
    _write(tmp_path, "examples/basic/mailer.py", TOOLS + MAILER)
    assert scan(tmp_path).trifectas == []


def test_one_agent_holding_all_three_legs_is_a_trifecta_naming_it(tmp_path):
    _write(
        tmp_path,
        "examples/basic/both.py",
        TOOLS + READER.replace("fetch_web_page]", "fetch_web_page, send_email]"),
    )
    _write(tmp_path, "examples/basic/other.py", TOOLS + MAILER)
    report = scan(tmp_path)
    (finding,) = report.trifectas
    assert finding.detail.startswith("Reader (examples/basic/both.py): can read user data")
    fix = finding.evidence["fix"]
    assert "agentfox permit grant reader send_email" in fix and "<agent>" not in fix


def test_agents_that_hand_off_to_each_other_share_a_trifecta(tmp_path):
    """A handoff passes the conversation, so what one agent read the other can send."""
    _write(tmp_path, "bot.py", TOOLS + READER + MAILER.replace("])", "], handoffs=[reader])"))
    report = scan(tmp_path)
    (finding,) = report.trifectas
    assert "permit grant mailer send_email" in finding.evidence["fix"]


def test_tools_no_agent_holds_still_group_by_directory(tmp_path):
    """The old grouping, kept for code whose agent the scan cannot see."""
    _write(
        tmp_path,
        "svc/tools.py",
        """
        from langchain_core.tools import tool

        @tool
        def read_customer_record(cid: str) -> str:
            \"\"\"Look up a customer.\"\"\"

        @tool
        def fetch_url(url: str) -> str:
            \"\"\"Fetch a web page.\"\"\"
        """,
    )
    _write(
        tmp_path,
        "svc/out.py",
        """
        from langchain_core.tools import tool

        @tool
        def send_email(to: str) -> str:
            \"\"\"Send an email.\"\"\"
        """,
    )
    (finding,) = scan(tmp_path).trifectas
    assert finding.file == "svc/"
    # No agent to name: the placeholder is spelled as one, and said to be one.
    assert "permit grant AGENT send_email" in finding.evidence["fix"]


# ---------------------------------------------------------------------------
# Tests, docs and benchmarks
# ---------------------------------------------------------------------------


def test_tests_docs_and_benchmarks_are_left_out_by_default(tmp_path):
    agent = (
        "from agents import Agent, Runner\n"
        'a = Agent(name="{0}", instructions="x")\n'
        'Runner.run_sync(a, "hi")\n'
    )
    _write(tmp_path, "app/main.py", agent.format("App"))
    _write(tmp_path, "tests/test_app.py", agent.format("Fake"))
    _write(tmp_path, "docs/scripts/translate.py", agent.format("Docs"))
    _write(tmp_path, "libs/x/bench/run.py", agent.format("Bench"))
    _write(tmp_path, "tests/conftest.py", 'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"\n')

    report = scan(tmp_path)
    assert [a.name for a in report.agents] == ["App"]
    assert [s.file for s in report.model_calls] == ["app/main.py"]
    assert report.excluded_files == 4
    # A key committed in a test is still committed.
    assert [s.file for s in report.sites if s.kind == "secret"] == ["tests/conftest.py"]

    everything = scan(tmp_path, include_tests=True)
    assert len(everything.model_calls) == 4 and everything.excluded_files == 0

    out = flat(runner.invoke(app, ["scan", str(tmp_path), "--no-submit"]).output)
    assert "left out 4 test, docs or benchmark files" in out


def test_what_counts_as_excluded():
    assert is_excluded_path("tests/test_x.py")
    assert is_excluded_path("docs/scripts/build.py")
    assert is_excluded_path("integration_tests/openai/test_x.py")
    assert is_excluded_path("libs/langgraph/bench/run.py")
    assert not is_excluded_path("examples/basic/hello.py")
    assert not is_excluded_path("src/app/docs_agent.py")


def test_many_agents_across_examples_are_listed_by_directory(tmp_path):
    for group in ("basic", "handoffs", "memory", "voice"):
        for n in range(4):
            _write(
                tmp_path,
                f"examples/{group}/ex{n}.py",
                f'from agents import Agent\na = Agent(name="{group}-{n}", instructions="x")\n',
            )
    out = flat(runner.invoke(app, ["scan", str(tmp_path), "--no-submit"]).output)
    assert "Found 16 agents" in out
    assert "examples/basic/ 4 agents" in out and "examples/memory/ 4 agents" in out


def test_running_any_agent_the_scan_found_is_a_model_call(tmp_path):
    """Framework-agnostic: a run-shaped method on a variable the agent pass found an
    agent in, in its own file or imported from the one file that defines it."""
    _write(
        tmp_path,
        "bot/agent.py",
        """
        from pydantic_ai import Agent

        def lookup(order_id: str) -> str:
            return ""

        support = Agent("openai:gpt-4o", tools=[lookup], instructions="Help.")

        def main():
            return support.run_sync("where is my order?")
        """,
    )
    _write(
        tmp_path,
        "bot/server.py",
        """
        from bot.agent import support

        async def handle(text):
            jobs.run()  # not an agent
            return await support.run(text)
        """,
    )
    calls = sorted((s.file, s.line, s.provider) for s in scan(tmp_path).model_calls)
    assert calls == [("bot/agent.py", 9, "pydantic-ai"), ("bot/server.py", 5, "pydantic-ai")]
