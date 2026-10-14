"""`agentfox up`: the guided setup, end to end and per part.

CliRunner's stdin is not a terminal, so `up` answers every question with its
recommended (or saved) answer, which is exactly what `--yes` does. The interactive
prompts are tested on their own below.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.apps.cli.wizard import targets
from agentfox.apps.cli.wizard.backend import BackendError, Remote
from agentfox.apps.cli.wizard.components import insert_auto
from agentfox.apps.cli.wizard.prompt import Choice, Interactive

runner = CliRunner()

AGENT_PY = '''"""Support bot."""
from __future__ import annotations

from openai import OpenAI

client = OpenAI()

tools = [
    {"type": "function", "function": {"name": "lookup_order", "description": "Find an order"}},
    {"type": "function", "function": {"name": "refund_payment", "description": "Refund it"}},
]


def answer(q):
    return client.chat.completions.create(model="gpt-4o", messages=[], tools=tools)


if __name__ == "__main__":
    answer("hi")
'''


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch) -> Path:
    """A home directory of our own: `up` reads the AI tools set up on this machine."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(path / ".config"))
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "support-bot"
    root.mkdir()
    (root / ".git").mkdir()  # enough for the .gitignore handling; no remote
    (root / "main.py").write_text(AGENT_PY)
    (root / "CLAUDE.md").write_text("# notes\n")
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {"command": "npx", "args": ["server-github"]}}})
    )
    return root


def _up(*args: str) -> object:
    return runner.invoke(app, ["up", *args, "--no-start"])


# ---------------------------------------------------------------------------
# Local, end to end
# ---------------------------------------------------------------------------


def test_up_sets_up_a_project_locally(project):
    result = _up(str(project), "--yes")
    assert result.exit_code == 0, result.output

    # Coding agent: Claude Code hooks for <project>-claude.
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    assert "support-bot-claude" in json.dumps(settings)
    # Python agent: one line, before the client import.
    text = (project / "main.py").read_text()
    assert 'agentfox.auto("support-bot", mode="observe")' in text
    assert text.index("agentfox.auto(") < text.index("from openai import")
    # Answers saved for the next run.
    saved = json.loads((project / ".agentfox" / "up.json").read_text())
    assert saved["target"] == "local"
    assert {"coding-agents", "python-app", "tools", "mcp"} <= set(saved["components"])
    assert saved["mode"] == "observe"

    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import McpServer, Policy, Tool
    from agentfox.platform.policy import current_binding
    from agentfox.platform.registry.service import impact_source_of

    with session_scope() as session:
        tools = {t.key: t for t in session.scalars(select(Tool))}
        assert tools["refund_payment"].impact == "irreversible"
        assert impact_source_of(tools["refund_payment"]) == "inferred"
        assert tools["lookup_order"].impact == "read"
        assert session.scalar(select(McpServer).where(McpServer.name == "github")) is not None
        # Watch first: nothing blocks, tool containment included.
        for policy in session.scalars(select(Policy)):
            binding, _ = current_binding(session, policy.id)
            if binding is not None:
                assert binding.mode == "observe", policy.key


def test_running_up_again_changes_nothing_new(project):
    assert _up(str(project), "--yes").exit_code == 0
    before = (project / "main.py").read_text()
    result = _up(str(project), "--yes")
    assert result.exit_code == 0, result.output
    assert (project / "main.py").read_text() == before
    assert "already calls agentfox.auto()" in result.output
    assert "already installed" in result.output


def test_a_declared_tool_is_never_overwritten_by_a_guess(project):
    from agentfox.core.db import init_db, session_scope
    from agentfox.platform.registry.service import upsert_tool

    init_db()
    with session_scope() as session:
        upsert_tool(session, "lookup_order", impact="write")
    assert _up(str(project), "--yes").exit_code == 0

    from sqlalchemy import select

    from agentfox.core.models import Tool

    with session_scope() as session:
        tool = session.scalar(select(Tool).where(Tool.key == "lookup_order"))
        assert tool.impact == "write"


def test_dry_run_changes_nothing(project):
    result = _up(str(project), "--yes", "--dry-run")
    assert result.exit_code == 0, result.output
    assert "Plan" in result.output
    assert not (project / ".claude").exists()
    assert "agentfox.auto" not in (project / "main.py").read_text()
    assert not (project / ".agentfox").exists()


def test_with_and_without_choose_the_components(project):
    result = _up(str(project), "--yes", "--with", "tools,python-app", "--without", "python-app")
    assert result.exit_code == 0, result.output
    saved = json.loads((project / ".agentfox" / "up.json").read_text())
    assert saved["components"] == ["tools"]
    assert "agentfox.auto" not in (project / "main.py").read_text()


def test_an_unknown_component_is_refused(project):
    result = _up(str(project), "--yes", "--with", "everything")
    assert result.exit_code == 2
    assert "unknown" in result.output


def test_shipped_defaults_keep_tool_containment_enforcing(project):
    result = _up(str(project), "--yes", "--mode", "defaults", "--with", "tools")
    assert result.exit_code == 0, result.output

    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import Policy
    from agentfox.platform.policy import current_binding

    with session_scope() as session:
        policy = session.scalar(select(Policy).where(Policy.key == "tool-containment"))
        binding, _ = current_binding(session, policy.id)
        assert binding.mode == "enforce"


def test_enterprise_components_say_why_they_are_unavailable(project, monkeypatch):
    monkeypatch.setenv("AGENTFOX_DISABLE_EXTENSIONS", "1")
    from agentfox.core import extensions

    extensions.reset()
    try:
        result = _up(str(project), "--yes", "--with", "monitoring")
    finally:
        extensions.reset()
    assert result.exit_code == 0, result.output
    assert "monitoring unavailable" in result.output
    assert "AgentFox Enterprise" in result.output


# ---------------------------------------------------------------------------
# Cloud (and a connected self-hosted server): a remote control plane
# ---------------------------------------------------------------------------


class FakeControlPlane:
    """Just enough of the gateway's API for `up` to talk to."""

    def __init__(self, *, enterprise: bool = True) -> None:
        self.tools: dict[str, str] = {"lookup_order": "write"}
        self.modes = {"baseline": "observe", "tool-containment": "enforce"}
        self.calls: list[tuple[str, str]] = []
        self.enterprise = enterprise

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if request.headers.get("authorization") != "Bearer nom_api_good":
            return httpx.Response(401, json={"detail": "bad token"})
        if path == "/api/me":
            return httpx.Response(
                200,
                json={"email": "me@acme.test", "role": "owner", "workspace": "acme", "id": "u1"},
            )
        if path == "/api/version":
            features = ["compliance", "evidence", "monitoring"] if self.enterprise else []
            return httpx.Response(
                200,
                json={
                    "edition": "enterprise" if self.enterprise else "open-source",
                    "features": features,
                    "code_version": "0.4.0",
                },
            )
        if path == "/api/tools" and method == "GET":
            return httpx.Response(200, json={"tools": [{"key": k} for k in self.tools]})
        if path == "/api/tools":
            body = json.loads(request.content)
            self.tools[body["key"]] = body["impact"]
            return httpx.Response(201, json=body)
        if path == "/api/policies":
            return httpx.Response(
                200, json={"policies": [{"key": k, "mode": m} for k, m in self.modes.items()]}
            )
        if path.startswith("/api/policies/") and path.endswith("/mode"):
            key = path.split("/")[3]
            self.modes[key] = json.loads(request.content)["mode"]
            return httpx.Response(200, json={})
        if path in ("/api/agents", "/api/mcp-servers", "/api/monitors"):
            return httpx.Response(201, json={"id": "x"})
        if path == "/api/discovery/submit":
            return httpx.Response(
                200, json={"summary": {"agents_proposed": ["a"], "policies_proposed": []}}
            )
        return httpx.Response(404, json={"detail": "not here"})


@pytest.fixture
def cloud(monkeypatch):
    plane = FakeControlPlane()
    client = httpx.Client(transport=httpx.MockTransport(plane.handle))
    monkeypatch.setattr(targets, "Remote", lambda url, token: Remote(url, token, client=client))
    return plane


def test_up_connects_to_cloud_and_keeps_the_key_out_of_git(project, cloud):
    result = _up(
        str(project),
        "--yes",
        "--target",
        "cloud",
        "--api-url",
        "https://gw.acme.test",
        "--api-token",
        "nom_api_good",
    )
    assert result.exit_code == 0, result.output
    assert "connected to" in result.output and "me@acme.test" in result.output

    env = project / ".agentfox" / "agentfox.env"
    assert "AGENTFOX_API_TOKEN=nom_api_good" in env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert ".agentfox/agentfox.env" in (project / ".gitignore").read_text()
    saved = (project / ".agentfox" / "up.json").read_text()
    assert "nom_api_good" not in saved  # answers are not secrets

    # auto() records locally, so it is not offered against a remote control plane…
    assert "agentfox.auto" not in (project / "main.py").read_text()
    # …the gateway is, and the tool found in code was declared there, the
    # existing declaration left alone.
    assert "OPENAI_BASE_URL=https://gw.acme.test/v1" in env.read_text()
    assert cloud.tools == {"lookup_order": "write", "refund_payment": "irreversible"}
    assert cloud.modes["tool-containment"] == "observe"
    assert ("POST", "/api/discovery/submit") in cloud.calls


def test_a_refused_key_stops_before_anything_changes(project, cloud):
    result = _up(
        str(project),
        "--yes",
        "--target",
        "cloud",
        "--api-url",
        "https://gw.acme.test",
        "--api-token",
        "nom_api_bad",
    )
    assert result.exit_code == 1
    assert "refused the token" in result.output
    assert not (project / ".agentfox").exists()


def test_remote_backend_reports_a_missing_enterprise_feature():
    plane = FakeControlPlane(enterprise=False)
    backend = Remote(
        "https://gw",
        "nom_api_good",
        client=httpx.Client(transport=httpx.MockTransport(plane.handle)),
    )
    assert not backend.edition().enterprise
    plane_404 = Remote(
        "https://gw",
        "nom_api_good",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
    )
    with pytest.raises(BackendError, match="Enterprise"):
        plane_404.add_monitor("github_repo", "acme/bot", name="")


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------


def test_insert_auto_goes_after_the_docstring_and_future_imports(tmp_path):
    path = tmp_path / "app.py"
    path.write_text('"""Doc."""\nfrom __future__ import annotations\n\nimport os\n')
    assert insert_auto(path, "import agentfox\n\nagentfox.auto()\n")
    assert path.read_text() == (
        '"""Doc."""\nfrom __future__ import annotations\n\n'
        "import agentfox\n\nagentfox.auto()\n\nimport os\n"
    )
    assert not insert_auto(path, "import agentfox\n\nagentfox.auto()\n")


def test_insert_auto_into_a_bare_script(tmp_path):
    path = tmp_path / "run.py"
    path.write_text("import os\n")
    assert insert_auto(path, "import agentfox\n")
    assert path.read_text() == "import agentfox\n\nimport os\n"


class Typed(Interactive):
    """The interactive prompter, fed from a list instead of a keyboard."""

    def __init__(self, replies: list[str]) -> None:
        super().__init__(Console(file=open("/dev/null", "w")))  # noqa: SIM115
        self.replies = replies

    def _ask(self, prompt: str, *, secret: bool = False) -> str:
        return self.replies.pop(0)


CHOICES = [Choice("a", "Alpha"), Choice("b", "Beta"), Choice("c", "Gamma", disabled="no")]


def test_multiselect_toggles_by_number_and_skips_disabled():
    assert Typed(["2", "3", ""]).multiselect("?", CHOICES, ["a"]) == ["a", "b"]
    assert Typed(["n", "1", ""]).multiselect("?", CHOICES, ["a", "b"]) == ["a"]
    assert Typed(["a", ""]).multiselect("?", CHOICES, []) == ["a", "b"]


def test_multiselect_shows_which_options_are_ticked():
    import io

    buffer = io.StringIO()
    prompter = Typed([""])
    prompter.console = Console(file=buffer, width=100)
    prompter.multiselect("?", CHOICES, ["a"])
    lines = buffer.getvalue().splitlines()
    assert any("[x]" in line and "Alpha" in line for line in lines)
    assert any("[ ]" in line and "Beta" in line for line in lines)


def test_select_takes_the_default_on_enter_and_rejects_disabled():
    assert Typed([""]).select("?", CHOICES, "b") == "b"
    assert Typed(["3", "9", "alpha"]).select("?", CHOICES, "b") == "a"


def test_confirm_and_text():
    assert Typed([""]).confirm("?", default=False) is False
    assert Typed(["y"]).confirm("?", default=False) is True
    assert Typed([""]).text("?", "keep") == "keep"
    assert Typed(["new"]).text("?", "keep") == "new"


# ---------------------------------------------------------------------------
# Self-hosted
# ---------------------------------------------------------------------------


def test_up_connects_to_a_running_self_hosted_server(project, cloud):
    result = _up(
        str(project),
        "--yes",
        "--target",
        "self-hosted",
        "--api-url",
        "http://agentfox.internal:8080",
        "--api-token",
        "nom_api_good",
    )
    assert result.exit_code == 0, result.output
    saved = json.loads((project / ".agentfox" / "up.json").read_text())
    assert saved["target"] == "self-hosted"
    assert saved["api_url"] == "http://agentfox.internal:8080"


def test_the_compose_stack_gets_its_own_secrets_once(project):
    compose = targets.write_compose(project)
    env = compose.parent / ".env"
    first = env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "AGENTFOX_AUDIT_SIGNING_KEY=" in first
    assert "ghcr.io/architsharm/agentfox/gateway" in compose.read_text()
    # Regenerating the secrets would orphan the database and the audit chain.
    targets.write_compose(project)
    assert env.read_text() == first
    assert ".agentfox/selfhost/.env" in (project / ".gitignore").read_text()


def test_starting_a_stack_without_docker_says_what_to_do(project, monkeypatch):
    monkeypatch.setattr("agentfox.apps.cli.wizard.detect._on_path", lambda binary: False)
    result = _up(str(project), "--yes", "--target", "self-hosted")
    assert result.exit_code == 1
    assert "--api-url and --api-token" in result.output
    assert not (project / ".agentfox" / "selfhost").exists()


# ---------------------------------------------------------------------------
# What landed with `agentfox scan machine` and the GitHub Action
# ---------------------------------------------------------------------------


def test_the_scan_step_includes_this_machine_and_the_repos_skills(project, home):
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text(
        '[mcp_servers.fs]\ncommand = "npx"\nargs = ["@modelcontextprotocol/server-filesystem"]\n'
    )
    skill = project / "skills" / "deploy"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: deploy\ndescription: Deploys.\n---\nDeploy it.\n")

    result = _up(str(project), "--yes", "--dry-run")
    assert result.exit_code == 0, result.output
    assert "this machine" in result.output and "Codex" in result.output
    assert "skills" in result.output
    # Codex is configured on this machine, so its hooks are offered too.
    assert "Codex CLI" in result.output.split("coding agents", 1)[1].splitlines()[0]


def test_skip_machine_leaves_the_home_directory_alone(project, home):
    (home / ".claude.json").write_text('{"mcpServers": {"x": {"command": "x"}}}')
    result = _up(str(project), "--yes", "--dry-run", "--skip-machine")
    assert result.exit_code == 0, result.output
    assert "this machine" not in result.output


def test_up_adds_the_github_action_once(project):
    from agentfox.apps.cli.wizard.components import WORKFLOW_PATH

    (project / ".github").mkdir()
    assert _up(str(project), "--yes", "--with", "ci").exit_code == 0
    workflow = (project / WORKFLOW_PATH).read_text()
    assert "uses: architsharm/agentfox@main" in workflow
    (project / WORKFLOW_PATH).write_text("# mine\n")
    result = _up(str(project), "--yes", "--with", "ci")
    assert "already exists" in result.output
    assert (project / WORKFLOW_PATH).read_text() == "# mine\n"
