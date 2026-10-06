"""The CLI's visible shape: thirteen verbs in six panels, and nothing else.

`agentfox --help` lists thirteen verbs (see `src/agentfox/apps/cli/layout.py`). The
pre-consolidation top-level names were removed; only the two protocol endpoints that
installed configs call, `hooks run` and `mcp serve`, still resolve at their old paths.
"""

from __future__ import annotations

import json

import click
import pytest
import typer.main
from typer.testing import CliRunner

from agentfox.apps.cli import layout
from agentfox.apps.cli.main import app

runner = CliRunner()
ROOT = typer.main.get_command(app)

# The pre-consolidation top-level names, every one removed. A name coming back here
# means a second way to reach a command, which is what the consolidation removed.
REMOVED_TOP_LEVEL = (
    "check",
    "quickscan",
    "quickstart",
    "version",
    "seed",
    "analyse-action",
    "eval",
    "audit",
    "evidence",
    "compliance",
    "redteam",
    "tools",
    "access",
    "db",
    "auth",
    "boundary",
    "sources",
    "escalation",
    "entitlement",
    "guardrails",
    "capability",
    "approvals",
    "proposals",
    "users",
)

# Written into installed coding-agent hook configs and MCP client configs.
KEPT_PROTOCOL_ENDPOINTS = ("hooks run", "mcp serve")

# Where each removed name's commands live now.
NEW_PATHS = (
    "scan repo",
    "scan sessions",
    "init",
    "admin version",
    "admin seed",
    "test action",
    "test run",
    "test gate",
    "test baseline",
    "test suites",
    "test online",
    "report drift",
    "report verify",
    "admin checkpoint",
    "report evidence",
    "report status",
    "report signoff",
    "admin catalog sync",
    "test redteam",
    "test probes",
    "declare tool",
    "declare triggers",
    "declare list",
    "declare scope",
    "declare reference",
    "admin db upgrade",
    "admin auth issue",
    "declare boundary",
    "test boundary",
    "declare source",
    "declare import-sources",
    "declare escalation",
    "report escalations",
    "declare principal",
    "permit user",
    "report entitlement",
    "policy rules apply",
    "test rule",
    "permit grant",
    "permit approvals",
    "policy proposals list",
    "admin users",
    "admin hooks run",
    "admin hooks daemon",
    "admin hooks install",
    "serve mcp",
    "admin mcp tools",
)


def _resolve(path: str) -> click.Command | None:
    cmd: click.Command = ROOT
    for word in path.split():
        if not isinstance(cmd, click.Group):
            return None
        cmd = cmd.get_command(click.Context(cmd), word)
        if cmd is None:
            return None
    return cmd


def _walk(group: click.Group, prefix: tuple[str, ...] = ()):
    for name, cmd in group.commands.items():
        yield prefix + (name,), cmd
        if isinstance(cmd, click.Group):
            yield from _walk(cmd, prefix + (name,))


@pytest.mark.parametrize("name", REMOVED_TOP_LEVEL)
def test_removed_top_level_names_are_gone(name):
    assert _resolve(name) is None, f"`agentfox {name}` should no longer resolve"


@pytest.mark.parametrize("path", KEPT_PROTOCOL_ENDPOINTS)
def test_protocol_endpoints_still_resolve_at_their_old_paths(path):
    command = _resolve(path)
    assert command is not None, f"`agentfox {path}` is called by installed configs"
    assert ROOT.commands[path.split()[0]].hidden


@pytest.mark.parametrize("path", ["hooks install", "hooks daemon", "hooks status", "mcp tools"])
def test_only_the_protocol_endpoints_survive_under_their_old_groups(path):
    assert _resolve(path) is None


@pytest.mark.parametrize("path", NEW_PATHS)
def test_every_new_path_resolves(path):
    assert _resolve(path) is not None, f"`agentfox {path}` does not resolve"


def test_the_only_hidden_top_level_entries_are_the_protocol_endpoints():
    hidden = sorted(name for name, cmd in ROOT.commands.items() if cmd.hidden)
    assert hidden == sorted({path.split()[0] for path in KEPT_PROTOCOL_ENDPOINTS})


def test_visible_top_level_is_thirteen_or_fewer():
    listed = ROOT.list_commands(click.Context(ROOT))
    visible = [name for name in listed if not ROOT.commands[name].hidden]
    assert len(visible) <= 13, visible
    assert visible == [name for name, _ in layout.VISIBLE if name in visible]
    assert set(visible) == {name for name, _ in layout.VISIBLE}


def test_help_lists_the_panels_in_order_and_hides_old_names():
    output = runner.invoke(app, ["--help"]).output
    positions = [
        output.index(f"─ {panel} ")
        for panel in ("Start", "See", "Watch", "Contain", "Prove", "Operate")
    ]
    assert positions == sorted(positions)
    for old in ("quickscan", "compliance", "guardrails", "capability", "entitlement"):
        assert f" {old} " not in output, old


def test_every_visible_leaf_has_help_text():
    for path, cmd in _walk(ROOT):
        if cmd.hidden or any(_resolve(" ".join(path[:i])).hidden for i in range(1, len(path))):
            continue
        assert (cmd.help or cmd.short_help or "").strip(), " ".join(path)


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("agentfox ")


# ---------------------------------------------------------------------------
# Default-command groups: scan, serve, report
# ---------------------------------------------------------------------------


def test_bare_scan_is_the_repo_scan_with_its_flags(isolated_db, tmp_path):
    (tmp_path / "app.py").write_text("import openai\nopenai.OpenAI().chat.completions.create()\n")
    old = runner.invoke(app, ["scan", "repo", str(tmp_path), "--json"])
    new = runner.invoke(app, ["scan", str(tmp_path), "--json"])
    assert new.exit_code == old.exit_code == 0
    assert json.loads(new.output)["files_scanned"] == json.loads(old.output)["files_scanned"]
    failing = runner.invoke(app, ["scan", str(tmp_path), "--fail", "--json"])
    assert (
        failing.exit_code
        == runner.invoke(app, ["scan", "repo", str(tmp_path), "--fail", "--json"]).exit_code
    )


def test_scan_still_reaches_its_subcommands():
    assert "Check an MCP server" in runner.invoke(app, ["scan", "mcp", "--help"]).output
    assert runner.invoke(app, ["scan", "skills", "--help"]).exit_code == 0
    assert "Sweep for shadow agents" in runner.invoke(app, ["scan", "runtime", "--help"]).output


def test_scan_sessions_routes_to_the_quickscan(isolated_db, tmp_path):
    result = runner.invoke(
        app, ["scan", "--sessions", str(tmp_path), "--skip-sessions", "--no-submit", "--json"]
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert {"repo", "sessions", "live_demo"} <= set(body)


def test_serve_keeps_its_options_and_gains_mcp():
    assert "--port" in runner.invoke(app, ["serve", "api", "--help"]).output
    assert runner.invoke(app, ["serve", "mcp", "--help"]).exit_code == 0


def test_serve_with_options_forwards_to_the_api_command(monkeypatch):
    import uvicorn

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.update(k))
    result = runner.invoke(app, ["serve", "--port", "9123"])
    assert result.exit_code == 0, result.output
    assert calls["port"] == 9123


def test_bare_report_is_the_one_page_summary(isolated_db):
    summary = runner.invoke(app, ["report", "summary"])
    bare = runner.invoke(app, ["report"])
    assert bare.exit_code == summary.exit_code == 0
    assert bare.output.startswith("# AgentFox summary")
    assert runner.invoke(app, ["report", "status"]).exit_code == 0


# ---------------------------------------------------------------------------
# Renames that carry behaviour
# ---------------------------------------------------------------------------


def test_agents_list_stopped_is_agents_controls(isolated_db):
    old = runner.invoke(app, ["agents", "controls"])
    new = runner.invoke(app, ["agents", "list", "--stopped"])
    assert new.exit_code == old.exit_code == 0
    assert new.output == old.output


def test_declare_list_shows_both_kinds(isolated_db):
    result = runner.invoke(app, ["declare", "list"])
    assert result.exit_code == 0, result.output
    assert "tools" in result.output and "sources" in result.output
    as_json = runner.invoke(app, ["declare", "list", "sources", "--json"])
    assert as_json.exit_code == 0, as_json.output
    json.loads(as_json.output)
    assert runner.invoke(app, ["declare", "list", "--json"]).exit_code != 0


@pytest.mark.parametrize(
    "args",
    [["hooks", "run", "--help"], ["mcp", "serve", "--help"]],
)
def test_protocol_endpoints_run(args):
    """`hooks run` and `mcp serve` are written into agent configs and speak a protocol."""
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output


def test_protocol_endpoint_is_the_same_command_as_its_new_path():
    for old_path, new_path in (("hooks run", "admin hooks run"), ("mcp serve", "serve mcp")):
        old, new = _resolve(old_path), _resolve(new_path)
        assert old.callback.__qualname__ == new.callback.__qualname__
        assert old.callback.__module__ == new.callback.__module__
        assert [p.name for p in old.params] == [p.name for p in new.params]
