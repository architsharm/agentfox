"""Which file starts the agent: where `agentfox up` offers to add `agentfox.auto()`.

Found by a walkthrough of three official examples, on all of which `up` offered only
"Don't edit my code": a LangGraph template (src/<pkg>/graph.py, loaded by
langgraph.json), a CrewAI crew (src/<pkg>/main.py, a [project.scripts] entry) and an
OpenAI Agents SDK app (main.py running `Runner.run`). The layouts below are those
shapes and others, written out here rather than copied from the examples.
"""

from __future__ import annotations

from pathlib import Path

from agentfox.capabilities.onboarding.project_files import entry_points


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _rel(root: Path) -> list[str]:
    return [str(p.relative_to(root)) for p in entry_points(root)]


def test_a_project_script_under_src_is_found(tmp_path):
    root = _write(
        tmp_path,
        {
            "pyproject.toml": (
                '[project]\nname = "x"\n[project.scripts]\nrun-it = "billing_bot.main:run"\n'
            ),
            "src/billing_bot/__init__.py": "",
            "src/billing_bot/crew.py": "class Crew: ...\n",
            "src/billing_bot/main.py": "from billing_bot.crew import Crew\n\n"
            "def run():\n    Crew().crew().kickoff(inputs={})\n",
        },
    )
    assert _rel(root)[0] == "src/billing_bot/main.py"


def test_a_poetry_script_names_the_module_too(tmp_path):
    root = _write(
        tmp_path,
        {
            "pyproject.toml": '[tool.poetry.scripts]\nbot = "helpdesk.cli:main"\n',
            "helpdesk/__init__.py": "",
            "helpdesk/cli.py": "def main():\n    pass\n",
            "helpdesk/util.py": "x = 1\n",
        },
    )
    assert _rel(root) == ["helpdesk/cli.py"]


def test_the_graph_langgraph_json_loads_is_found(tmp_path):
    root = _write(
        tmp_path,
        {
            "langgraph.json": '{"graphs": {"agent": "./src/research/graph.py:graph"}}',
            "src/research/graph.py": "from langgraph.graph import StateGraph\n"
            "graph = StateGraph(dict).compile()\n",
            "src/research/prompts.py": "SYSTEM = 'hi'\n",
        },
    )
    assert _rel(root) == ["src/research/graph.py"]


def test_a_file_that_runs_an_agents_sdk_agent_is_a_candidate(tmp_path):
    root = _write(
        tmp_path,
        {
            "app.py": "from agents import Agent, Runner\n"
            "triage = Agent(name='Triage')\n\n"
            "async def main():\n    await Runner.run(triage, 'hi')\n",
            "helpers.py": "def fmt(x):\n    return x\n",
        },
    )
    assert _rel(root) == ["app.py"]


def test_a_package_main_module_is_found_deep_in_the_tree(tmp_path):
    root = _write(
        tmp_path,
        {
            "services/agents/router/__main__.py": "from .graph import app\n\n"
            "if __name__ == '__main__':\n    app.invoke({})\n",
            "services/agents/router/graph.py": "app = None\n",
        },
    )
    assert _rel(root)[0] == "services/agents/router/__main__.py"


def test_the_file_that_runs_beats_the_file_that_defines(tmp_path):
    root = _write(
        tmp_path,
        {
            "agent.py": "from openai import OpenAI\nclient = OpenAI()\n",
            "serve.py": "from agent import client\n\nif __name__ == '__main__':\n    pass\n",
        },
    )
    ranked = entry_points(root, model_call_files={"agent.py": 3})
    assert [p.name for p in ranked] == ["serve.py", "agent.py"]


def test_tests_docs_and_virtualenvs_are_never_candidates(tmp_path):
    runs = "if __name__ == '__main__':\n    pass\n"
    root = _write(
        tmp_path,
        {
            "tests/test_main.py": runs,
            "tests/main.py": runs,
            "docs/main.py": runs,
            ".venv/lib/site.py": runs,
            "node_modules/x/main.py": runs,
            "main.py": runs,
        },
    )
    assert _rel(root) == ["main.py"]


def test_nothing_that_starts_anything_is_no_candidate(tmp_path):
    root = _write(tmp_path, {"lib.py": "def f():\n    return 1\n"})
    assert entry_points(root) == []
