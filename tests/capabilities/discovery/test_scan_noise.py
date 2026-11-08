"""Findings that are not findings, found on a first run on 2026-11-08: skills shipped
inside installed packages, every agent run site at severity high, a constant
parameterised query read as "SQL built from a string", and a remote MCP server that
signs in with OAuth graded like an open one. Shapes written here, not copied."""

from __future__ import annotations

from pathlib import Path

from agentfox.capabilities.discovery.exposure import McpServerDecl, _decl, server_hygiene
from agentfox.capabilities.discovery.repo import scan
from agentfox.capabilities.discovery.skills import scan_skills_dir

SKILL = "---\nname: {name}\ndescription: Does {name}.\n---\nDo {name}.\n"


def _skill(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(SKILL.format(name=name))


# --- skills ---------------------------------------------------------------------


def test_skills_inside_virtualenvs_and_installed_packages_are_not_the_projects(tmp_path):
    _skill(tmp_path / ".claude" / "skills" / "release", "release")
    _skill(tmp_path / "skills" / "triage", "triage")
    _skill(tmp_path / ".venv" / "lib" / "python3.13" / "site-packages" / "lib_a", "vendored-a")
    _skill(tmp_path / "node_modules" / "pkg" / "skills" / "x", "vendored-b")
    # A virtualenv under a name of its own, known by its pyvenv.cfg.
    (tmp_path / "py-env").mkdir()
    (tmp_path / "py-env" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    _skill(tmp_path / "py-env" / "share" / "skills" / "y", "vendored-c")
    # And a site-packages outside any venv (a --target install).
    _skill(tmp_path / "vendor" / "site-packages" / "z", "vendored-d")

    names = sorted(r["skill"] for r in scan_skills_dir(tmp_path))
    assert names == ["release", "triage"]


# --- run sites ------------------------------------------------------------------


def test_a_run_site_is_information_and_a_direct_model_call_stays_high(tmp_path):
    (tmp_path / "runner.py").write_text(
        "from agents import Agent, Runner\n\n"
        "helper = Agent(name='helper')\n\n\n"
        "async def go():\n    return await Runner.run(helper, 'hi')\n"
    )
    (tmp_path / "direct.py").write_text(
        "from openai import OpenAI\n\n"
        "def ask():\n"
        "    return OpenAI().chat.completions.create(model='gpt-4o', messages=[])\n"
    )
    (tmp_path / "typed.py").write_text(
        "from pydantic_ai import Agent\n\n"
        "clerk = Agent('openai:gpt-4o')\n"
        "print(clerk.run_sync('hi'))\n"
    )
    report = scan(tmp_path)
    by_file = {}
    for site in report.model_calls:
        by_file.setdefault(site.file, set()).add(site.severity)
    assert by_file["runner.py"] == {"info"}
    assert by_file["direct.py"] == {"high"}
    assert by_file.get("typed.py", {"info"}) == {"info"}
    # Still counted: a run site is ungoverned until auto() covers it.
    assert any(s.file == "runner.py" for s in report.ungoverned)


# --- SQL ------------------------------------------------------------------------


def test_constant_parameterised_queries_are_not_sql_built_from_a_string(tmp_path):
    (tmp_path / "store.py").write_text(
        "def load(cur, uid, name, col):\n"
        "    cur.execute('SELECT * FROM users WHERE id = ?', (uid,))\n"  # 2: safe
        '    cur.execute("UPDATE users SET name = %s WHERE id = %s", (name, uid))\n'  # 3: safe
        "    cur.execute('DELETE FROM t WHERE k = :k', {'k': uid})\n"  # 4: safe
        '    cur.execute(f"SELECT * FROM users WHERE id = {uid}")\n'  # 5: built
        "    cur.execute(\"SELECT * FROM users WHERE name = '%s'\" % name)\n"  # 6: built
        '    cur.execute("SELECT " + col + " FROM users")\n'  # 7: built
        '    cur.execute("SELECT {} FROM users".format(col))\n'  # 8: built
    )
    lines = sorted(s.line for s in scan(tmp_path).sites if s.kind == "sql_build")
    assert lines == [5, 6, 7, 8]


# --- MCP ------------------------------------------------------------------------


def _remote_without_auth(decl: McpServerDecl) -> dict | None:
    return next((i for i in server_hygiene(decl) if i["type"] == "remote_without_auth"), None)


def test_a_remote_mcp_server_that_signs_in_with_oauth_is_information():
    https = _remote_without_auth(McpServerDecl(name="d", config="x", url="https://mcp.d.test/mcp"))
    assert https is not None and https["severity"] == "info"
    assert "OAuth" in https["detail"]

    declared = _decl("e", {"url": "https://mcp.e.test", "oauth": {"clientId": "abc"}}, "x")
    assert declared.oauth
    issue = _remote_without_auth(declared)
    assert issue is not None and issue["severity"] == "info"

    # A token from the environment (Codex) is auth too.
    assert _decl("f", {"url": "https://f.test", "bearer_token_env_var": "F_TOKEN"}, "x").oauth

    # Plain http with nothing: still something to look at.
    plain = _remote_without_auth(McpServerDecl(name="g", config="x", url="http://mcp.g.test"))
    assert plain is not None and plain["severity"] == "medium"
