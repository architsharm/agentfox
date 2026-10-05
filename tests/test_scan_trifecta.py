"""The zero-config scan's first finding: the lethal trifecta.

A fresh user pointed `agentfox quickscan` / `agentfox check` at a support bot that
declares its tools as OpenAI function schemas and loads two MCP servers. The scan
found zero tools, called the servers "I-2 rug pull", and said nothing about the one
thing a security owner would care about: the bot reads customer records, reads web
pages anyone can write, and can send email. These tests pin each part of the fix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfox.cli.main import app
from agentfox.discovery import scan
from agentfox.exposure import (
    EXFIL,
    PRIVATE,
    UNTRUSTED,
    McpServerDecl,
    classify_mcp_server,
    classify_tool,
    parse_mcp_config,
    server_hygiene,
)

runner = CliRunner()


def flat(output: str) -> str:
    # Panel borders sit between the words of a wrapped sentence; drop them.
    return " ".join(output.replace("│", " ").split())


def _json(output: str):
    lines = [line for line in output.splitlines() if not line.startswith("INFO")]
    return json.loads("\n".join(lines))


SUPPORT_BOT = """
from openai import OpenAI

client = OpenAI()

TOOLS = [
    {"type": "function", "function": {"name": "read_customer_record",
     "description": "Look up a customer by id.", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "fetch_url",
     "description": "Fetch a web page.", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "send_email",
     "description": "Send an email.", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "issue_refund",
     "description": "Refund an order.", "parameters": {"type": "object"}}},
]


def answer(question):
    return client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": question}], tools=TOOLS
    )
"""

MCP_CONFIG = {
    "mcpServers": {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
        },
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
    }
}


@pytest.fixture
def support_bot(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bot.py").write_text(SUPPORT_BOT)
    (repo / ".mcp.json").write_text(json.dumps(MCP_CONFIG))
    return repo


# ---------------------------------------------------------------------------
# 1. tools declared as schemas are tools
# ---------------------------------------------------------------------------


def test_openai_function_schemas_in_a_list_variable_are_tools(support_bot):
    names = {s.name for s in scan(support_bot).tools}
    assert names == {"read_customer_record", "fetch_url", "send_email", "issue_refund"}


def test_inline_tools_kwarg_and_responses_api_shape_are_tools(tmp_path):
    (tmp_path / "a.py").write_text(
        "client.chat.completions.create(model='m', messages=[], tools=[\n"
        "    {'type': 'function', 'function': {'name': 'lookup_order', 'parameters': {}}}])\n"
        "client.responses.create(model='m', input='x', tools=[\n"
        "    {'type': 'function', 'name': 'delete_account', 'parameters': {}}])\n"
    )
    names = {s.name for s in scan(tmp_path).tools}
    assert names == {"lookup_order", "delete_account"}


def test_anthropic_tool_dicts_are_tools(tmp_path):
    (tmp_path / "a.py").write_text(
        "tools = [{'name': 'get_weather', 'description': 'Weather.',\n"
        "          'input_schema': {'type': 'object'}}]\n"
        "client.messages.create(model='claude', max_tokens=10, messages=[], tools=tools)\n"
    )
    tools = scan(tmp_path).tools
    assert [t.name for t in tools] == ["get_weather"]
    assert "Anthropic" in tools[0].detail
    # A tool whose name says nothing risky gets no flag rather than a guessed one.
    assert tools[0].capabilities == []


def test_decorated_tools_and_constructed_tools_still_count(tmp_path):
    (tmp_path / "a.py").write_text(
        "from langchain.tools import tool, Tool\n"
        "@tool\n"
        "def send_slack_message(text: str):\n"
        "    '''Post to Slack.'''\n"
        "Tool(name='web_search', func=print, description='Search the web')\n"
    )
    names = {s.name for s in scan(tmp_path).tools}
    assert names == {"send_slack_message", "web_search"}


def test_a_dict_that_merely_has_a_name_is_not_a_tool(tmp_path):
    (tmp_path / "a.py").write_text(
        "user = {'name': 'ada', 'email': 'a@example.com'}\ncfg = {'type': 'function', 'value': 3}\n"
    )
    assert scan(tmp_path).tools == []


def test_the_same_schema_twice_in_a_file_is_one_tool(tmp_path):
    schema = "{'type': 'function', 'function': {'name': 'send_email', 'parameters': {}}}"
    (tmp_path / "a.py").write_text(f"A = [{schema}]\nB = [{schema}]\n")
    assert len(scan(tmp_path).tools) == 1


# ---------------------------------------------------------------------------
# 2. capability classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "flags"),
    [
        ("read_customer_record", {PRIVATE}),
        ("fetch_url", {UNTRUSTED}),
        ("web_search", {UNTRUSTED}),
        ("send_email", {EXFIL}),
        ("issue_refund", {EXFIL}),
        ("delete_file", {EXFIL}),
        ("run_shell_command", {EXFIL}),
        # Reading a mailbox is both private and attacker-authored.
        ("read_email", {PRIVATE, UNTRUSTED}),
        ("get_weather", set()),
        # Token match, not substring: "sender" is not "send".
        ("get_sender", set()),
        # Creating a ticket reads nothing in.
        ("create_ticket", set()),
        # AgentDojo's irreversible pattern is honoured.
        ("send_money", {EXFIL}),
    ],
)
def test_tool_classification(name, flags):
    assert classify_tool(name).flags == flags


@pytest.mark.parametrize(
    ("name", "args", "flags"),
    [
        ("fetch", ["mcp-server-fetch"], {UNTRUSTED, EXFIL}),
        ("files", ["-y", "@modelcontextprotocol/server-filesystem", "."], {PRIVATE, EXFIL}),
        ("gmail", [], {PRIVATE, UNTRUSTED, EXFIL}),
        ("slack", [], {PRIVATE, UNTRUSTED, EXFIL}),
        ("github", [], {PRIVATE, UNTRUSTED, EXFIL}),
        ("puppeteer", [], {UNTRUSTED, EXFIL}),
    ],
)
def test_known_mcp_servers_are_classified(name, args, flags):
    caps = classify_mcp_server(McpServerDecl(name=name, config=".mcp.json", args=args))
    assert caps.known
    assert caps.flags == flags


def test_an_unknown_mcp_server_is_unknown_not_safe():
    caps = classify_mcp_server(
        McpServerDecl(name="acme-internal", config=".mcp.json", command="node", args=["s.js"])
    )
    assert caps.known is False
    assert caps.flags == set()


# ---------------------------------------------------------------------------
# 3. the trifecta finding
# ---------------------------------------------------------------------------


def test_the_support_bot_is_a_lethal_trifecta_in_plain_english(support_bot):
    report = scan(support_bot)
    code = next(t for t in report.trifectas if t.file == "bot.py")
    assert code.severity == "critical"
    assert code.detail.startswith("bot.py: can read customer records (read_customer_record)")
    assert "reads untrusted web pages (fetch_url)" in code.detail
    assert "can send email (send_email)" in code.detail
    assert "An instruction hidden in a web page could send customer data out." in code.detail
    assert "agentfox permit grant" in code.evidence["fix"]
    assert 'agentfox.auto(mode="observe")' in code.evidence["fix"]
    assert code.evidence["exfiltration"][0] == "send_email"


def test_mcp_servers_in_one_config_form_their_own_trifecta(support_bot):
    report = scan(support_bot)
    mcp = next(t for t in report.trifectas if t.file == ".mcp.json")
    assert "(filesystem)" in mcp.detail and "(fetch)" in mcp.detail


def test_the_trifecta_is_the_first_site_and_ranks_first(support_bot):
    report = scan(support_bot)
    assert report.sites[0].kind == "lethal_trifecta"
    assert report.ranked()[0].kind == "lethal_trifecta"


def test_two_legs_are_not_a_trifecta(tmp_path):
    (tmp_path / "a.py").write_text(
        "T = [{'name': 'read_customer_record', 'input_schema': {}},\n"
        "     {'name': 'send_email', 'input_schema': {}}]\n"
    )
    assert scan(tmp_path).trifectas == []


def test_tools_spread_across_one_package_are_grouped(tmp_path):
    pkg = tmp_path / "support"
    pkg.mkdir()
    (pkg / "read.py").write_text("R = {'name': 'read_customer_record', 'input_schema': {}}\n")
    (pkg / "web.py").write_text("W = {'name': 'fetch_url', 'input_schema': {}}\n")
    (pkg / "out.py").write_text("O = {'name': 'send_email', 'input_schema': {}}\n")
    # A different package's tools do not complete this one's trifecta.
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "x.py").write_text("X = {'name': 'fetch_url', 'input_schema': {}}\n")
    trifectas = scan(tmp_path).trifectas
    assert [t.file for t in trifectas] == ["support/"]


def test_json_carries_the_trifecta_and_counts(support_bot):
    payload = scan(support_bot).to_json()
    assert payload["tools"] == 4
    assert payload["mcp_servers"] == 2
    assert len(payload["lethal_trifectas"]) == 2
    tool = next(s for s in payload["sites"] if s.get("name") == "send_email")
    assert tool["capabilities"] == ["exfiltration"]


def test_submission_payload_carries_the_trifecta_without_its_text(support_bot):
    payload = scan(support_bot).to_submission_payload(source="check")
    kinds = [s["kind"] for s in payload["sites"]]
    assert "lethal_trifecta" in kinds
    assert "read_customer_record" not in repr(payload)


def test_a_submitted_trifecta_proposes_a_high_risk_agent(client):
    from .conftest import as_user

    response = client.post(
        "/api/discovery/submit",
        json={
            "source": "check",
            "label": "supportrepo",
            "sites": [
                {"kind": "model_call", "top_dir": "bot.py", "provider": "openai"},
                {"kind": "lethal_trifecta", "top_dir": "bot.py", "provider": None},
                {"kind": "model_call", "top_dir": "batch", "provider": "openai"},
                # An MCP-config trifecta raises nothing it has no agent to raise.
                {"kind": "lethal_trifecta", "top_dir": ".mcp.json", "provider": "mcp"},
            ],
        },
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200, response.text
    proposed = response.json()["summary"]["agents_proposed"]
    assert sorted(proposed) == ["supportrepo-batch", "supportrepo-bot-py"]
    agents = client.get("/api/agents", headers=as_user("admin@example.com")).json()["agents"]
    tiers = {a["slug"]: a["risk_tier"] for a in agents if a["slug"].startswith("supportrepo")}
    assert tiers == {"supportrepo-bot-py": "high", "supportrepo-batch": "limited"}


# ---------------------------------------------------------------------------
# 4. what check and quickscan print
# ---------------------------------------------------------------------------


def test_check_leads_with_the_trifecta(support_bot):
    result = runner.invoke(app, ["check", str(support_bot), "--no-submit"])
    assert result.exit_code == 0, result.output
    output = flat(result.output)
    assert output.index("lethal trifecta") < output.index("Scanned")
    assert "An instruction hidden in a web page could send customer data out." in output
    assert "4 tools · 2 MCP servers (filesystem, fetch)" in output


def test_check_output_has_no_internal_codes(support_bot):
    (support_bot / "db.py").write_text('cursor.execute(f"SELECT * FROM t WHERE id={x}")\n')
    output = runner.invoke(app, ["check", str(support_bot), "--no-submit"]).output
    for code in ("I-2", "P9", "P1-5", "NOM-", "F3.8", "Pillar"):
        assert code not in output, code


def test_quickscan_shows_tools_servers_and_the_trifecta(support_bot):
    result = runner.invoke(app, ["quickscan", str(support_bot), "--skip-sessions", "--no-submit"])
    assert result.exit_code == 0, result.output
    output = flat(result.output)
    assert output.index("lethal trifecta") < output.index("Committed")
    assert "4 tools · 2 MCP servers (filesystem, fetch)" in output
    for code in ("I-2", "P9", "P1-5", "NOM-"):
        assert code not in output


def test_a_clean_repo_shows_no_trifecta(tmp_path):
    (tmp_path / "a.py").write_text("print('hello')\n")
    output = flat(runner.invoke(app, ["check", str(tmp_path), "--no-submit"]).output)
    assert "trifecta" not in output
    assert "0 tools · 0 MCP servers" in output


# ---------------------------------------------------------------------------
# 5. scan mcp needs no registration step
# ---------------------------------------------------------------------------


def test_scan_mcp_reads_the_repo_config_with_no_setup(support_bot, monkeypatch):
    monkeypatch.chdir(support_bot)
    result = runner.invoke(app, ["scan", "mcp", "fetch"])
    assert result.exit_code == 0, result.output
    output = flat(result.output)
    assert "reads untrusted web pages" in output
    assert "no version pinned" in output
    assert "tools: not listed" in output
    assert "unknown MCP server" not in output


def test_scan_mcp_registers_the_declared_servers(support_bot, monkeypatch):
    from sqlalchemy import select

    from agentfox.db import session_scope
    from agentfox.models import McpServer

    monkeypatch.chdir(support_bot)
    assert runner.invoke(app, ["scan", "mcp"]).exit_code == 0
    with session_scope() as session:
        names = {s.name for s in session.scalars(select(McpServer))}
    assert {"filesystem", "fetch"} <= names


def test_scan_mcp_without_a_name_reports_the_config_trifecta(support_bot, monkeypatch):
    monkeypatch.chdir(support_bot)
    result = runner.invoke(app, ["scan", "mcp", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert payload["lethal_trifecta"]
    assert {s["server"] for s in payload["servers"]} == {"filesystem", "fetch"}


def test_scan_mcp_explicit_config_and_tool_file(tmp_path, monkeypatch):
    elsewhere = tmp_path / "cfg"
    elsewhere.mkdir()
    config = elsewhere / "claude_desktop_config.json"
    config.write_text(
        json.dumps({"mcpServers": {"web": {"command": "uvx", "args": ["mcp-server-fetch==1.2"]}}})
    )
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps([{"name": "fetch", "description": "Fetch a URL."}]))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["scan", "mcp", "web", "--config", str(config), "--file", str(tools), "--json"]
    )
    assert result.exit_code == 0, result.output
    entry = _json(result.output)["servers"][0]
    assert entry["pinned_version"] == "1.2"
    assert entry["tools"] == 1
    assert entry["tool_capabilities"] == [{"name": "fetch", "capabilities": ["untrusted_input"]}]
    assert not any(i["type"] == "unpinned_server" for i in entry["config_issues"])


def test_scan_mcp_with_a_tool_file_registers_an_undeclared_server(tmp_path, monkeypatch):
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps([{"name": "lookup", "description": "Look something up."}]))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan", "mcp", "brand-new", "--file", str(tools)])
    assert result.exit_code == 0, result.output
    assert "1 tools" in flat(result.output)


def test_scan_mcp_names_what_it_looked_for_when_nothing_is_declared(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan", "mcp", "fetch"])
    assert result.exit_code == 2
    output = flat(result.output)
    assert "no MCP server named 'fetch'" in output
    assert "--config" in output


def test_scan_mcp_never_starts_a_server(support_bot, monkeypatch):
    """No process, no network, unless someone explicitly asks for it."""
    import subprocess

    def refuse(*args, **kwargs):
        raise AssertionError(f"scan mcp tried to run {args!r}")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.chdir(support_bot)
    assert runner.invoke(app, ["scan", "mcp"]).exit_code == 0


def test_config_hygiene_without_a_tool_list():
    remote = McpServerDecl(name="r", config="x", url="http://mcp.example.com/sse")
    assert {i["type"] for i in server_hygiene(remote)} == {
        "plaintext_remote",
        "remote_without_auth",
    }
    leaky = McpServerDecl(
        name="gh",
        config="x",
        command="npx",
        args=["@modelcontextprotocol/server-github@1.0.0"],
        env={"GITHUB_TOKEN": "ghp_" + "a" * 30},
    )
    assert [i["type"] for i in server_hygiene(leaky)] == ["secret_in_config"]
    broad = McpServerDecl(
        name="fs", config="x", command="npx", args=["@scope/server-filesystem@2.0.0", "/"]
    )
    assert [i["type"] for i in server_hygiene(broad)] == ["broad_filesystem_access"]


def test_claude_json_projects_and_cursor_configs_are_read(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"gmail": {"command": "npx", "args": ["gmail-mcp"]}}})
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps({"projects": {"/x": {"mcpServers": {"slack": {"url": "https://s/mcp"}}}}})
    )
    names = {s.name for s in scan(tmp_path).mcp_servers}
    assert names == {"gmail", "slack"}
    decls = parse_mcp_config(tmp_path / ".claude.json", root=tmp_path)
    assert decls[0].transport == "http"
