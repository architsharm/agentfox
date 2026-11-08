"""Round two of the first-run walkthrough (2026-11-08): `up` names the agent the code
runs, sets up one agent system at a time, and the first run's copy says what is true.

Each project here is built in the shape an official example has (an AutoGen agent
using others as tools, a folder of independent Agents SDK scripts, a LangGraph swarm,
a pydantic-ai script, a CrewAI crew class), written fresh rather than copied, and with
names of our own, so the rules are checked on shapes and not on the examples they were
found on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()


def flat(output: str) -> str:
    return " ".join(output.split())


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(path / ".config"))
    return path


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _up(*args: str):
    return runner.invoke(app, ["up", *args, "--no-start", "--skip-machine"])


def _saved(root: Path) -> dict:
    return json.loads((root / ".agentfox" / "up.json").read_text())


def _grants_of(slug: str) -> set[str]:
    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent
    from agentfox.platform.identity import ensure_identity

    with session_scope() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == slug))
        if agent is None:
            return set()
        return {c.tool_key for c in ensure_identity(session, agent).capabilities}


# ---------------------------------------------------------------------------
# The agent the entry file runs
# ---------------------------------------------------------------------------

#: An AutoGen assistant that uses two specialists as tools, and runs with run_stream.
AUTOGEN = {
    "app.py": (
        "import asyncio\n"
        "from autogen_agentchat.agents import AssistantAgent\n"
        "from autogen_agentchat.tools import AgentTool\n"
        "from autogen_agentchat.ui import Console\n"
        "from autogen_ext.models.openai import OpenAIChatCompletionClient\n\n\n"
        "async def main():\n"
        "    client = OpenAIChatCompletionClient(model='gpt-4o')\n"
        "    poet = AssistantAgent('poet', model_client=client, description='Writes poems.')\n"
        "    critic = AssistantAgent('critic', model_client=client, description='Critiques.')\n"
        "    lead = AssistantAgent(\n"
        "        'editor', model_client=client,\n"
        "        tools=[AgentTool(poet), AgentTool(critic)],\n"
        "    )\n"
        "    await Console(lead.run_stream(task='A poem about tides'))\n\n\n"
        "asyncio.run(main())\n"
    ),
}


def test_up_names_the_autogen_agent_the_run_starts_not_the_first_one_defined(tmp_path):
    root = _write(tmp_path / "poems", AUTOGEN)
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    assert 'agentfox.auto("editor"' in (root / "app.py").read_text()
    assert _saved(root)["agent"] == "editor"
    # One system: the specialists are the editor's tools, not apps of their own.
    assert "separate agent systems" not in result.output


def test_an_agent_tool_held_in_a_variable_is_a_sub_agent(tmp_path):
    from agentfox.capabilities.discovery.repo import scan

    root = _write(
        tmp_path / "poems",
        {
            "app.py": AUTOGEN["app.py"]
            .replace("tools=[AgentTool(poet), AgentTool(critic)]", "tools=[poet_tool, critic_tool]")
            .replace(
                "    lead = AssistantAgent(",
                "    poet_tool = AgentTool(poet, return_value_as_last_message=True)\n"
                "    critic_tool = AgentTool(agent=critic)\n"
                "    lead = AssistantAgent(",
            )
        },
    )
    edges = {(e.parent, e.child, e.relation) for e in scan(root).agent_edges}
    assert edges == {("editor", "poet", "as_tool"), ("editor", "critic", "as_tool")}


def test_systems_in_the_same_file_share_the_process_and_its_grants(tmp_path):
    root = _write(
        tmp_path / "judge",
        {
            "loop.py": (
                "from agents import Agent, Runner, function_tool\n\n\n"
                "@function_tool\ndef draft_outline(topic: str) -> str:\n    return topic\n\n\n"
                "@function_tool\ndef grade(text: str) -> str:\n    return text\n\n\n"
                "drafter = Agent(name='drafter', tools=[draft_outline])\n"
                "judge = Agent(name='judge', tools=[grade])\n\n\n"
                "async def main():\n"
                "    out = await Runner.run(drafter, 'x')\n"
                "    await Runner.run(judge, out.final_output)\n"
            ),
        },
    )
    result = _up(str(root), "--yes", "--with", "python-app,tools")
    assert result.exit_code == 0, result.output
    assert "separate agent systems" not in result.output
    assert _grants_of(_saved(root)["agent"]) == {"draft_outline", "grade"}


#: pydantic-ai: two agents in one file, the second the one `run_sync` runs.
PYDANTIC_AI = {
    "quiz.py": (
        "from pydantic_ai import Agent\n\n"
        "hint_agent = Agent('openai:gpt-4o', instructions='Give hints.')\n"
        "quiz_agent = Agent('openai:gpt-4o', instructions='Ask questions.')\n\n\n"
        "@quiz_agent.tool_plain\n"
        "def score(answer: str) -> int:\n    return len(answer)\n\n\n"
        "if __name__ == '__main__':\n"
        "    print(quiz_agent.run_sync('start').output)\n"
    ),
}


def test_up_names_the_pydantic_ai_agent_run_sync_starts(tmp_path):
    root = _write(tmp_path / "quiz", PYDANTIC_AI)
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    assert 'agentfox.auto("quiz-agent"' in (root / "quiz.py").read_text()


# ---------------------------------------------------------------------------
# A folder of independent examples: one is set up, with only its own tools
# ---------------------------------------------------------------------------

EXAMPLES = {
    "alpha_router.py": (
        "import asyncio\nfrom agents import Agent, Runner, function_tool\n\n\n"
        "@function_tool\ndef read_inbox() -> str:\n    return ''\n\n\n"
        "reader = Agent(name='reader', tools=[read_inbox])\n"
        "router = Agent(name='router', handoffs=[reader])\n\n\n"
        "async def main():\n    await Runner.run(router, 'hi')\n\n\n"
        "if __name__ == '__main__':\n    asyncio.run(main())\n"
    ),
    "beta_writer.py": (
        "import asyncio\nfrom agents import Agent, Runner, function_tool\n\n\n"
        "@function_tool\ndef delete_record(rid: str) -> str:\n    return rid\n\n\n"
        "@function_tool\ndef send_payment(to: str) -> str:\n    return to\n\n\n"
        "checker = Agent(name='checker')\n"
        "writer = Agent(\n"
        "    name='writer', tools=[delete_record, send_payment], handoffs=[checker]\n"
        ")\n\n\n"
        "async def main():\n    await Runner.run(writer, 'hi')\n\n\n"
        "if __name__ == '__main__':\n    asyncio.run(main())\n"
    ),
}


def test_a_folder_of_independent_examples_sets_up_the_one_the_chosen_file_runs(tmp_path):
    root = _write(tmp_path / "patterns", EXAMPLES)
    result = _up(str(root), "--yes", "--with", "python-app,tools")
    assert result.exit_code == 0, result.output
    saved = _saved(root)
    entry = saved["entry_point"]
    text = (root / entry).read_text()
    # The agent written into the file is one that file runs.
    expected = {"alpha_router.py": "router", "beta_writer.py": "writer"}[entry]
    assert f'agentfox.auto("{expected}"' in text
    out = flat(result.output)
    assert "2 separate agent systems here" in out
    assert "agentfox up --agent" in out
    # Only its own system's tools: never the other example's.
    own = {"router": {"read_inbox"}, "writer": {"delete_record", "send_payment"}}[expected]
    assert _grants_of(expected) == own


def test_up_agent_picks_another_system_and_its_file(tmp_path):
    root = _write(tmp_path / "patterns", EXAMPLES)
    result = _up(str(root), "--yes", "--with", "python-app,tools", "--agent", "writer")
    assert result.exit_code == 0, result.output
    assert _saved(root)["entry_point"] == "beta_writer.py"
    assert 'agentfox.auto("writer"' in (root / "beta_writer.py").read_text()
    assert "agentfox" not in (root / "alpha_router.py").read_text()
    assert _grants_of("writer") == {"delete_record", "send_payment"}


def test_the_agent_name_is_shown_and_the_plan_names_it(tmp_path):
    root = _write(tmp_path / "patterns", EXAMPLES)
    out = flat(_up(str(root), "--yes", "--dry-run", "--agent", "writer").output)
    assert "agent writer" in out
    # Asked (and so changeable) when no --agent was given.
    out = flat(_up(str(root), "--yes", "--dry-run").output)
    assert "Agent name" in out


def test_the_interactive_name_question_changes_the_name(tmp_path, monkeypatch):
    from agentfox.apps.cli.wizard import command
    from agentfox.apps.cli.wizard.prompt import Scripted

    class Renaming(Scripted):
        def text(self, question, default="", *, secret=False):
            return "my-poet-desk" if question == "Agent name" else default

    root = _write(tmp_path / "poems", AUTOGEN)
    monkeypatch.setattr(command, "Scripted", Renaming)
    result = _up(str(root))
    assert result.exit_code == 0, result.output
    assert 'agentfox.auto("my-poet-desk"' in (root / "app.py").read_text()


# ---------------------------------------------------------------------------
# A swarm: the system takes its project's name, the members keep theirs
# ---------------------------------------------------------------------------

SWARM = {
    "pyproject.toml": '[project]\nname = "trip-desk"\nversion = "0.1.0"\n',
    "src/desk/graph.py": (
        "from langgraph.prebuilt import create_react_agent\n"
        "from langgraph_swarm import create_handoff_tool, create_swarm\n\n\n"
        "def find_trains(city: str) -> str:\n    '''Find trains.'''\n    return city\n\n\n"
        "def find_rooms(city: str) -> str:\n    '''Find rooms.'''\n    return city\n\n\n"
        "rail = create_react_agent('openai:gpt-4o', [find_trains, "
        "create_handoff_tool(agent_name='lodging')], name='rail')\n"
        "lodging = create_react_agent('openai:gpt-4o', [find_rooms, "
        "create_handoff_tool(agent_name='rail')], name='lodging')\n"
        "workflow = create_swarm([rail, lodging], default_active_agent='rail')\n"
        "app = workflow.compile()\n"
    ),
}


def test_a_swarm_runs_under_its_projects_name_not_its_variable(tmp_path):
    root = _write(tmp_path / "examples" / "trips", SWARM)
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    assert _saved(root)["agent"] == "trip-desk"
    assert "workflow" not in _saved(root)["agent"]


def test_init_key_map_shows_a_swarm_as_the_system_not_an_agent(tmp_path):
    from rich.console import Console

    from agentfox.capabilities.onboarding.client import _print_map
    from agentfox.capabilities.onboarding.mapper import map_repository

    root = _write(tmp_path / "trips", SWARM)
    structure = map_repository(root)["structure"]
    container = next(a for a in structure["agents"] if a["kind"] in ("team", "swarm", "graph"))
    assert container["name"] == "trip-desk" and container["system"] is True
    console = Console(record=True, width=120)
    _print_map(console, structure)
    text = console.export_text()
    assert "trip-desk  system: runs" in text
    assert "unknown model" not in text


# ---------------------------------------------------------------------------
# One naming scheme
# ---------------------------------------------------------------------------


def test_keys_split_camel_case_and_the_scan_lists_agents_by_key(tmp_path):
    from agentfox.capabilities.discovery.repo import scan

    root = _write(
        tmp_path / "crew",
        {
            "crew.py": (
                "from crewai import Agent, Crew, Task\n"
                "from crewai.project import CrewBase, agent, crew, task\n\n\n"
                "@CrewBase\nclass HarborPilotCrew:\n"
                "    @agent\n    def pilot(self) -> Agent:\n"
                "        return Agent(role='Pilot', goal='g', backstory='b')\n\n"
                "    @task\n    def steer(self) -> Task:\n"
                "        return Task(description='d', expected_output='o', agent=self.pilot())\n\n"
                "    @crew\n    def crew(self) -> Crew:\n"
                "        return Crew(agents=self.agents, tasks=self.tasks)\n"
            ),
        },
    )
    keys = {a.key for a in scan(root).agents}
    assert "harbor-pilot-crew" in keys
    out = flat(runner.invoke(app, ["scan", str(root), "--no-submit"]).output)
    assert "harbor-pilot-crew" in out


# ---------------------------------------------------------------------------
# After `up`: the scan's next step, and copy that points at what exists
# ---------------------------------------------------------------------------


def test_a_scan_after_up_says_the_next_step_not_up_again(tmp_path):
    root = _write(tmp_path / "poems", AUTOGEN)
    before = flat(runner.invoke(app, ["scan", str(root), "--no-submit"]).output)
    assert "Start watching" in before
    assert _up(str(root), "--yes").exit_code == 0
    after = flat(runner.invoke(app, ["scan", str(root), "--no-submit"]).output)
    assert "Start watching" not in after
    assert "Set up with `agentfox up` as editor" in after
    assert "agentfox findings" in after


def test_ui_pages_are_named_only_when_a_dashboard_is_set_up(tmp_path, monkeypatch):
    from agentfox.apps.cli.commands._shared import dashboard_url

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTFOX_DASHBOARD_URL", raising=False)
    assert dashboard_url() == ""
    (tmp_path / ".agentfox").mkdir()
    (tmp_path / ".agentfox" / "up.json").write_text('{"dashboard_url": "https://app.x.test/"}')
    assert dashboard_url() == "https://app.x.test"
    source = (
        Path(__file__).resolve().parents[3] / "src/agentfox/apps/cli/commands/redteam.py"
    ).read_text()
    # The only "Policies → Libraries" left is behind the dashboard check.
    assert source.count("Policies → Libraries") == 1
    assert "if dashboard_url()" in source


def test_auto_banner_is_at_most_three_lines(monkeypatch):
    from agentfox.frameworks.autoguard import AutoState, PatchResult

    state = AutoState(agent="desk", mode="policy", environment="development", policies_bound=0)
    state.patches = [PatchResult("openai", True, "")]
    state.frameworks = ["LangChain"]
    banner = state.banner()
    assert len(banner.splitlines()) <= 3
    assert "desk" in banner and "AGENTFOX_VERBOSE=1" in banner
    # The full account is still there for whoever asks.
    assert len(state.summary().splitlines()) > 3
