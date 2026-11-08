"""`agentfox init --key` polish (audit 2026-11-08, A15 and A20).

* The "Missing something?" list of every recognised shape printed under a map that
  had found what it was looking for; it now prints only when nothing (or no tool) was
  found, and a found map gets one line pointing to the docs.
* The key was only accepted on the command line, so it showed in `ps` and the shell
  history; with ``--server`` and no ``--key``, ``AGENTFOX_API_KEY`` is used.
"""

from __future__ import annotations

from rich.console import Console
from typer.testing import CliRunner

from agentfox.capabilities.onboarding import client as init_client

AGENT_WITH_TOOL = (
    "from agents import Agent, function_tool\n\n"
    "@function_tool\ndef faq_lookup_tool(question: str) -> str:\n    return 'ok'\n\n"
    "faq = Agent(name='FAQ Agent', instructions='Answer.', tools=[faq_lookup_tool])\n"
)


class _Api:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def post(self, path: str, body: dict) -> dict:
        self.posts.append(path)
        return {"registered": []}


def _report(root) -> str:
    console = Console(record=True, width=200)
    init_client.report(_Api(), console, root, "http://gw", "afi_old")
    return console.export_text()


def test_a_found_agent_gets_one_line_not_the_whole_list(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "main.py").write_text(AGENT_WITH_TOOL)
    out = _report(tmp_path)
    assert "FAQ Agent" in out
    assert "Missing something?" not in out
    assert "Missing an agent or tool?" in out
    assert "useagentfox.com/docs/discover" in out


def test_nothing_found_prints_what_mapping_recognises(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "notes.txt").write_text("no code here\n")
    out = _report(tmp_path)
    assert "Missing something?" in out
    assert "OpenAI Agents SDK" in out


def _invoke(monkeypatch, args: list[str], env: dict[str, str]) -> list[tuple]:
    from agentfox.apps.cli.main import app

    seen: list[tuple] = []
    monkeypatch.setattr(init_client, "connect", lambda *a, **k: seen.append(a))
    monkeypatch.delenv("AGENTFOX_SERVER", raising=False)
    monkeypatch.delenv("AGENTFOX_API_KEY", raising=False)
    result = CliRunner().invoke(app, ["init", *args], env=env)
    assert result.exit_code == 0, result.output
    return seen


def test_init_with_a_server_reads_the_key_from_the_environment(monkeypatch, tmp_path):
    seen = _invoke(
        monkeypatch,
        ["--server", "https://gw.example", "--path", str(tmp_path)],
        {"AGENTFOX_API_KEY": "nom_api_from_env"},
    )
    assert seen and seen[0][:2] == ("nom_api_from_env", "https://gw.example")


def test_an_explicit_key_wins_over_the_environment(monkeypatch, tmp_path):
    seen = _invoke(
        monkeypatch,
        ["--key", "nom_api_flag", "--server", "https://gw", "--path", str(tmp_path)],
        {"AGENTFOX_API_KEY": "nom_api_from_env"},
    )
    assert seen[0][0] == "nom_api_flag"


def test_a_plain_init_sets_up_this_machine_even_with_a_key_exported(
    monkeypatch, tmp_path, isolated_db
):
    seen = _invoke(monkeypatch, ["--path", str(tmp_path)], {"AGENTFOX_API_KEY": "nom_api_x"})
    assert seen == []
    assert (tmp_path / "agentfox.toml").exists()
