"""The first ten minutes: `scan` → `up` → run your app → `findings`, and `init && demo`.

Each test is one thing a new-user walkthrough of three official examples (a LangGraph
template, a CrewAI crew, an OpenAI Agents SDK app) found wrong on 2026-11-08. The
projects below are built here in the same shapes, not copied from the examples.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()

REPO = Path(__file__).resolve().parents[3]


def flat(output: str) -> str:
    return " ".join(output.split())


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(path / ".config"))
    return path


def _up(*args: str):
    return runner.invoke(app, ["up", *args, "--no-start"])


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


CREW = {
    "pyproject.toml": '[project]\nname = "ticket_triage"\n'
    '[project.scripts]\nticket_triage = "ticket_triage.main:run"\n',
    "src/ticket_triage/__init__.py": "",
    "src/ticket_triage/crew.py": (
        "from crewai import Agent, Crew, Task\n"
        "from crewai.project import CrewBase, agent, crew, task\n\n\n"
        "@CrewBase\n"
        "class TicketTriageCrew:\n"
        "    @agent\n"
        "    def classifier(self) -> Agent:\n"
        "        return Agent(role='Classifier', goal='classify', backstory='b')\n\n"
        "    @task\n"
        "    def classify(self) -> Task:\n"
        "        return Task(description='d', expected_output='o', agent=self.classifier())\n\n"
        "    @crew\n"
        "    def crew(self) -> Crew:\n"
        "        return Crew(agents=self.agents, tasks=self.tasks)\n"
    ),
    "src/ticket_triage/main.py": (
        "import sys\n\nfrom ticket_triage.crew import TicketTriageCrew\n\n\n"
        "def run():\n    TicketTriageCrew().crew().kickoff(inputs={'ticket': sys.argv[1]})\n"
    ),
}

AGENTS_SDK = {
    "main.py": (
        "import asyncio\n\nfrom agents import Agent, Runner, function_tool, handoff\n\n\n"
        "@function_tool\n"
        "def lookup_booking(ref: str) -> str:\n    return ref\n\n\n"
        "billing = Agent(name='Billing Agent', tools=[lookup_booking])\n"
        "support = Agent(name='Support Agent')\n"
        "triage = Agent(\n"
        "    name='Front Desk',\n"
        "    handoffs=[handoff(agent=billing), handoff(agent=support)],\n"
        ")\n"
        "billing.handoffs.append(handoff(agent=triage))\n"
        "support.handoffs.append(handoff(agent=triage))\n\n\n"
        "async def main():\n    await Runner.run(triage, input='hi')\n\n\n"
        "if __name__ == '__main__':\n    asyncio.run(main())\n"
    ),
}


# ---------------------------------------------------------------------------
# 1. `up` adds the one line, to the right file, under the scan's name
# ---------------------------------------------------------------------------


def test_up_adds_auto_to_a_src_layout_project_script(tmp_path):
    root = _write(tmp_path / "ticket-triage", CREW)
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    main = (root / "src" / "ticket_triage" / "main.py").read_text()
    assert "agentfox.auto(" in main
    assert "agentfox.auto(" not in (root / "src" / "ticket_triage" / "crew.py").read_text()
    # The name `up` registered is the one written into the call.
    saved = json.loads((root / ".agentfox" / "up.json").read_text())
    assert f'agentfox.auto("{saved["agent"]}"' in main
    assert saved["entry_point"] == "src/ticket_triage/main.py"


def test_up_adds_auto_to_an_agents_sdk_app_under_the_agent_that_starts_the_run(tmp_path):
    root = _write(tmp_path / "desk", AGENTS_SDK)
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    text = (root / "main.py").read_text()
    # Hand-offs go both ways; the root is the one that hands work to the others.
    assert 'agentfox.auto("front-desk"' in text
    assert "no Python model calls found" not in result.output


def test_an_existing_unnamed_auto_call_is_flagged(tmp_path):
    root = _write(tmp_path / "desk", AGENTS_SDK)
    main = root / "main.py"
    main.write_text("import agentfox\nagentfox.auto()\n" + main.read_text())
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    assert "already calls agentfox.auto()" in result.output
    assert 'agentfox.auto("front-desk")' in flat(result.output)


def test_the_name_question_is_not_asked_when_the_code_names_the_agent(tmp_path):
    root = _write(tmp_path / "desk", AGENTS_SDK)
    result = _up(str(root), "--yes", "--dry-run")
    assert "Name for your agent" not in result.output


# ---------------------------------------------------------------------------
# 2. Defaults that match the project
# ---------------------------------------------------------------------------


def test_a_python_agent_project_gets_no_hooks_grants_daemons_or_workflow(tmp_path, home):
    root = _write(tmp_path / "desk", AGENTS_SDK)
    (root / ".git").mkdir()
    (root / "CLAUDE.md").write_text("# notes\n")
    (root / ".github").mkdir()
    (home / ".claude.json").write_text('{"mcpServers": {"crm": {"command": "npx"}}}')
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    assert not (root / ".claude").exists()
    assert not (root / ".github" / "workflows").exists()
    assert "granted the tools" not in result.output
    assert "hook daemon" not in result.output
    saved = json.loads((root / ".agentfox" / "up.json").read_text())
    assert "coding-agents" not in saved["components"]
    assert "view" not in saved["components"]  # no background API on a local first run


def test_the_workflow_is_never_written_below_the_repository_root(tmp_path):
    repo = tmp_path / "examples"
    (repo / ".git").mkdir(parents=True)
    root = _write(repo / "crews" / "triage", CREW)
    result = _up(str(root), "--yes", "--with", "ci,python-app")
    assert result.exit_code == 0, result.output
    assert not (root / ".github").exists()
    assert not (repo / ".github").exists()
    assert "GitHub only runs workflows" in flat(result.output)


def test_the_workflow_is_written_at_the_repository_root_when_asked(tmp_path):
    root = _write(tmp_path / "triage", CREW)
    (root / ".git").mkdir()
    (root / ".github").mkdir()
    result = _up(str(root), "--yes", "--with", "ci")
    assert result.exit_code == 0, result.output
    assert (root / ".github" / "workflows" / "agentfox.yml").is_file()


def test_enterprise_items_are_left_off_the_first_run_and_named_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFOX_DISABLE_EXTENSIONS", "1")
    from agentfox.core import extensions

    extensions.reset()
    try:
        root = _write(tmp_path / "desk", AGENTS_SDK)
        result = _up(str(root), "--yes")
    finally:
        extensions.reset()
    assert result.exit_code == 0, result.output
    out = flat(result.output)
    assert "Open core." not in out
    assert out.count("AgentFox Enterprise") == 1
    assert out.index("AgentFox Enterprise") > out.index("Next")


def test_next_steps_lead_with_running_the_app_then_attack_testing_it(tmp_path):
    root = _write(tmp_path / "desk", AGENTS_SDK)
    result = _up(str(root), "--yes")
    assert result.exit_code == 0, result.output
    out = flat(result.output)
    after = out[out.index("Next") :]
    run_app = after.index("python main.py")
    redteam = after.index("agentfox test redteam front-desk")
    assert run_app < after.index("agentfox findings") < redteam
    assert redteam < after.index("agentfox declare list")


def test_up_reads_the_readme_variable_names_and_the_older_ones(monkeypatch):
    out = flat(runner.invoke(app, ["up", "--help"]).output)
    assert "AGENTFOX_URL" in out and "AGENTFOX_API_KEY" in out

    from agentfox.core.config import api_key_from_env, api_url_from_env

    monkeypatch.delenv("AGENTFOX_URL", raising=False)
    monkeypatch.setenv("AGENTFOX_API_URL", "https://old.example")
    monkeypatch.setenv("AGENTFOX_API_TOKEN", "nom_api_old")
    monkeypatch.delenv("AGENTFOX_API_KEY", raising=False)
    assert api_url_from_env() == "https://old.example"
    assert api_key_from_env() == "nom_api_old"
    monkeypatch.setenv("AGENTFOX_URL", "https://new.example")
    monkeypatch.setenv("AGENTFOX_API_KEY", "nom_api_new")
    assert api_url_from_env() == "https://new.example"
    assert api_key_from_env() == "nom_api_new"


# ---------------------------------------------------------------------------
# Hooks run by absolute path
# ---------------------------------------------------------------------------


def test_hook_commands_name_agentfox_by_absolute_path():
    from agentfox.harnesses.base import HOOK_COMMAND_RE, hook_command

    command = hook_command("claude", "dev-claude")
    executable = command.split(" hooks run ")[0].strip("'")
    assert os.path.isabs(executable.split()[0].strip("'")), command
    assert HOOK_COMMAND_RE.findall(command) == ["dev-claude"]


def test_a_hook_installed_by_the_bare_name_is_not_added_twice(tmp_path):
    from agentfox.harnesses.claude_code.install import merge

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    bare = "agentfox hooks run --harness claude --agent dev-claude"
    settings.write_text(
        json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"command": bare}]}]}})
    )
    change = merge(settings, "claude", "dev-claude", ["PreToolUse"])
    assert change.action == "unchanged"
    # A different agent whose slug starts the same is a different hook.
    assert merge(settings, "claude", "dev", ["PreToolUse"]).action == "update"


# ---------------------------------------------------------------------------
# 3. The demo keeps to its own database
# ---------------------------------------------------------------------------


def test_demo_writes_to_its_own_database_and_says_how_to_look_around_it(monkeypatch):
    from agentfox.apps.cli import demo
    from agentfox.core.config import get_settings
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Finding

    workspace = get_settings().database_url
    seen = {}

    def walkthrough():
        seen["url"] = get_settings().database_url
        with session_scope() as session:
            session.add(Finding(type="demo", severity="high", title="demo finding"))
        return {"evidence_available": False}

    monkeypatch.setattr(demo, "_walkthrough", walkthrough)
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0, result.output

    assert seen["url"].endswith("/demo.db") and seen["url"] != workspace
    assert get_settings().database_url == workspace  # put back
    with session_scope() as session:
        assert session.query(Finding).filter_by(title="demo finding").count() == 0
        assert session.query(Agent).filter_by(slug="payments-ops").count() == 0
    out = flat(result.output)
    assert "demo.db" in out and "untouched" in out
    assert f"export AGENTFOX_DATABASE_URL={seen['url']}" in out
    # No command this installation lacks.
    assert "report evidence" not in out


def test_demo_reason_lines_are_wrapped_not_cut(monkeypatch):
    from rich.console import Console

    from agentfox.apps.cli import demo

    reason = (
        "agent:payments-ops holds a grant for 'payments.transfer', so this is not a missing "
        "permission. The grant allows amount below 1000, but this call passed 25000."
    )
    result = types.SimpleNamespace(
        verdict="block",
        effective_verdict="block",
        latency_ms=1.0,
        rules_fired=[
            {"rule_id": "capability.constraint_violated", "effect": "block", "reason": reason}
        ],
        entities=[],
    )
    console = Console(width=80, record=True)
    monkeypatch.setattr(demo, "console", console)
    demo._show(result, "transfer")
    assert "passed 25000." in flat(console.export_text())


def test_report_evidence_without_enterprise_says_what_it_is():
    import typer

    from agentfox.apps.cli import layout

    stub = typer.Typer()
    settings = {"allow_extra_args": True, "ignore_unknown_options": True}
    stub.command("evidence", context_settings=settings)(layout._evidence_unavailable)
    stub.command("other")(lambda: None)
    result = runner.invoke(stub, ["evidence", "--agent", "payments-ops"])
    assert result.exit_code == 2
    assert "AgentFox Enterprise" in result.output
    assert "agentfox report verify" in result.output


# ---------------------------------------------------------------------------
# 4. Messages that were wrong
# ---------------------------------------------------------------------------


def test_doctor_keeps_the_extra_in_an_install_hint(monkeypatch):
    from agentfox.capabilities import detection

    class Classifier:
        unavailable_reason = "needs `pip install 'agentfox[classifiers]'`"

    monkeypatch.setattr(detection, "available_detectors", lambda: {})
    monkeypatch.setattr(detection, "all_detectors", lambda: {"injection.classifier": Classifier()})
    result = runner.invoke(app, ["doctor"])
    assert "agentfox[classifiers]" in flat(result.output)


def test_the_classifier_warning_is_said_once_per_installation(caplog):
    from agentfox.capabilities.detection.base import warn_unrunnable

    with caplog.at_level("WARNING"):
        first = warn_unrunnable(once=True)
    if "injection.classifier" not in first:
        pytest.skip("the classifier can run here")
    assert any("injection.classifier" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert "injection.classifier" in warn_unrunnable(once=True)
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    # A server start still says it every time.
    with caplog.at_level("WARNING"):
        warn_unrunnable()
    assert any("injection.classifier" in r.getMessage() for r in caplog.records)


def test_a_socket_left_by_a_killed_daemon_is_removed_and_a_live_one_is_not():
    from agentfox.hooks.client import remove_stale_socket

    # A short directory: a Unix socket path has a length limit.
    with tempfile.TemporaryDirectory(prefix="af") as directory:
        path = Path(directory) / "d.sock"
        live = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        live.bind(str(path))
        live.listen(1)
        try:
            assert remove_stale_socket(path) is False
            assert path.exists()
        finally:
            live.close()  # closed without unlinking: what SIGKILL leaves behind
        assert path.exists()
        assert remove_stale_socket(path) is True
        assert not path.exists()


def test_a_second_projects_up_reuses_the_api_on_the_same_database(tmp_path, monkeypatch):
    from agentfox.apps.cli.commands import root as root_commands
    from agentfox.apps.cli.wizard import components

    root_commands._record_serve(8080)
    assert root_commands.running_serve()["pid"] == os.getpid()
    monkeypatch.setattr(components, "_api_up", lambda url: True)
    project = _write(tmp_path / "second", {"main.py": "print(1)\n"})
    result = _up(str(project), "--yes", "--with", "view")
    assert result.exit_code == 0, result.output
    out = flat(result.output)
    assert "reusing the API already running" in out
    assert "its own database" not in out


def test_something_else_on_the_port_is_not_called_another_serve(tmp_path, monkeypatch):
    from agentfox.apps.cli.wizard import components

    monkeypatch.setattr(components, "_api_up", lambda url: True)
    project = _write(tmp_path / "second", {"main.py": "print(1)\n"})
    result = _up(str(project), "--yes", "--with", "view")
    out = flat(result.output)
    assert "something else answers" in out
    assert "with its own database" not in out


def test_quickscan_installs_the_published_package_unless_asked_for_main():
    script = (REPO / "scripts" / "quickscan.sh").read_text()
    assert 'PACKAGE="agentfox"' in script
    assert '--main) SOURCE="main"' in script
    assert 'pip install --quiet --disable-pip-version-check "$PACKAGE"' in script


def test_coding_agents_can_be_added_on_a_later_run(tmp_path):
    """The first run saved no harnesses (coding agents were not picked); opting in on
    the second used to crash on the saved `null`."""
    root = _write(tmp_path / "desk", AGENTS_SDK)
    (root / "CLAUDE.md").write_text("# notes\n")
    assert _up(str(root), "--yes").exit_code == 0
    result = _up(str(root), "--yes", "--with", "coding-agents")
    assert result.exit_code == 0, result.output
    command = json.loads((root / ".claude" / "settings.json").read_text())["hooks"]
    assert "hooks run --harness claude --agent front-desk-claude" in json.dumps(command)
