"""The CLI's visible shape, and the promise that no old command path broke.

`agentfox --help` used to list thirty-four top-level entries. It now lists thirteen
in six panels (see `src/agentfox/cli/layout.py`). Every name that existed before the
consolidation is still registered — hidden, not removed — because old names live in
CI scripts, docs people copied, and agent configs (`hooks run`, `mcp serve`).
"""

from __future__ import annotations

import json

import click
import pytest
import typer.main
from typer.testing import CliRunner

from agentfox.cli import layout
from agentfox.cli.main import app

runner = CliRunner()
ROOT = typer.main.get_command(app)

# Every command path that existed before the consolidation (typer 0.19 / click 8,
# 118 paths: 97 runnable commands and 21 groups). Do not edit this list to make a
# test pass: a path missing here is a user's script breaking.
PRE_CONSOLIDATION_PATHS = (
    "init",
    "check",
    "doctor",
    "findings",
    "quickstart",
    "quickscan",
    "version",
    "seed",
    "demo",
    "serve",
    "analyse-action",
    "agents",
    "agents list",
    "agents discover",
    "agents lineage",
    "agents quarantine",
    "agents kill",
    "agents resume",
    "agents controls",
    "policy",
    "policy packs",
    "policy list",
    "policy lint",
    "policy effective",
    "policy simulate",
    "policy enforce",
    "policy observe",
    "policy validate",
    "eval",
    "eval suites",
    "eval run",
    "eval gate",
    "eval baseline",
    "eval drift",
    "eval online",
    "audit",
    "audit verify",
    "audit checkpoint",
    "evidence",
    "evidence export",
    "compliance",
    "compliance sync",
    "compliance compute",
    "compliance status",
    "compliance validate",
    "compliance review-packet",
    "compliance review",
    "compliance frameworks",
    "compliance risk",
    "compliance obligations",
    "compliance board",
    "redteam",
    "redteam run",
    "redteam probes",
    "scan",
    "scan skills",
    "scan mcp",
    "tools",
    "tools declare",
    "tools list",
    "tools set-triggers",
    "access",
    "access declare-scope",
    "access declare-reference",
    "db",
    "db upgrade",
    "db downgrade",
    "db current",
    "hooks",
    "hooks daemon",
    "hooks run",
    "hooks install",
    "hooks status",
    "auth",
    "auth issue",
    "auth tokens",
    "auth revoke",
    "auth status",
    "boundary",
    "boundary set",
    "boundary check",
    "sources",
    "sources add",
    "sources import",
    "sources list",
    "escalation",
    "escalation set",
    "escalation scan",
    "entitlement",
    "entitlement principal",
    "entitlement grant",
    "entitlement report",
    "guardrails",
    "guardrails apply",
    "guardrails show",
    "guardrails check",
    "guardrails test",
    "guardrails catalogue",
    "guardrails explain",
    "guardrails suggest",
    "guardrails graph",
    "guardrails compile",
    "mcp",
    "mcp serve",
    "mcp tools",
    "capability",
    "capability grant",
    "capability list",
    "capability revoke",
    "proposals",
    "proposals list",
    "proposals show",
    "proposals approve",
    "proposals reject",
    "proposals apply",
    "proposals rollback",
    "proposals verify",
    "proposals from-labels",
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


def test_the_snapshot_is_the_size_the_audit_counted():
    assert len(PRE_CONSOLIDATION_PATHS) == 118
    assert len(set(PRE_CONSOLIDATION_PATHS)) == 118


@pytest.mark.parametrize("path", PRE_CONSOLIDATION_PATHS)
def test_every_old_command_path_still_resolves(path):
    assert _resolve(path) is not None, f"`agentfox {path}` no longer resolves"


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
    old = runner.invoke(app, ["check", str(tmp_path), "--json"])
    new = runner.invoke(app, ["scan", str(tmp_path), "--json"])
    assert new.exit_code == old.exit_code == 0
    assert json.loads(new.output)["files_scanned"] == json.loads(old.output)["files_scanned"]
    failing = runner.invoke(app, ["scan", str(tmp_path), "--fail", "--json"])
    assert (
        failing.exit_code
        == runner.invoke(app, ["check", str(tmp_path), "--fail", "--json"]).exit_code
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
    assert (
        runner.invoke(app, ["report", "status"]).output
        == runner.invoke(app, ["compliance", "status"]).output
    )


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
    ("old", "new"),
    [
        (["eval", "suites"], ["test", "suites"]),
        (["redteam", "probes"], ["test", "probes"]),
        (["compliance", "frameworks"], ["report", "frameworks"]),
        (["capability", "list"], ["permit", "list"]),
        (["guardrails", "catalogue", "--json"], ["policy", "catalogue", "--json"]),
        (["guardrails", "catalogue", "--json"], ["policy", "rules", "catalogue", "--json"]),
        (["proposals", "list"], ["policy", "proposals", "list"]),
        (["sources", "list", "--json"], ["declare", "list", "sources", "--json"]),
        (["tools", "list", "--json"], ["declare", "list", "tools", "--json"]),
        (["db", "current"], ["admin", "db", "current"]),
        (["auth", "status"], ["admin", "auth", "status"]),
        (["mcp", "tools"], ["admin", "mcp", "tools"]),
    ],
)
def test_new_name_runs_the_same_command(isolated_db, old, new):
    before = runner.invoke(app, old)
    after = runner.invoke(app, new)
    assert after.exit_code == before.exit_code, after.output
    assert after.output == before.output


# ---------------------------------------------------------------------------
# Rename hints
# ---------------------------------------------------------------------------


def test_old_names_hint_on_a_terminal_only(isolated_db, monkeypatch):
    monkeypatch.setattr(layout, "_stderr_is_tty", lambda: True)
    result = CliRunner().invoke(app, ["eval", "suites"])
    assert "is now `agentfox test" in result.stderr
    assert "is now" not in result.stdout

    monkeypatch.setattr(layout, "_stderr_is_tty", lambda: False)
    result = CliRunner().invoke(app, ["eval", "suites"])
    assert "is now" not in result.output


@pytest.mark.parametrize("endpoint", [["hooks", "run", "--help"], ["mcp", "serve", "--help"]])
def test_protocol_endpoints_never_hint(monkeypatch, endpoint):
    """`hooks run` and `mcp serve` are written into agent configs and speak a protocol."""
    monkeypatch.setattr(layout, "_stderr_is_tty", lambda: True)
    result = CliRunner().invoke(app, endpoint)
    assert result.exit_code == 0
    assert "is now" not in result.output
