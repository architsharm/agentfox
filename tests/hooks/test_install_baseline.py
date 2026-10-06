"""`agentfox admin hooks install --write` leaves a coding agent that can work (#84).

Before, the hook refused everything straight after setup: the agent was a production
shadow with no grants, so `ls`, Read and Edit all hit capability default-deny and every
shell command also tripped `action.production_irreversible`.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agentfox.cli.main import app
from agentfox.hooks.daemon import HookDaemon
from agentfox.hooks.protocol import PROTOCOL_VERSION

runner = CliRunner()


def _install(tmp_path, *extra):
    assert runner.invoke(app, ["init", "--path", str(tmp_path)]).exit_code == 0
    result = runner.invoke(
        app,
        ["admin", "hooks", "install", "--agent", "coder", "--path", str(tmp_path), "--write"]
        + list(extra),
    )
    assert result.exit_code == 0, result.output
    return result


def _call(tool: str, arguments: dict) -> dict:
    daemon = HookDaemon.__new__(HookDaemon)  # handle() needs no socket
    return daemon.handle(
        {
            "protocolVersion": PROTOCOL_VERSION,
            "type": "hook",
            "agent": "coder",
            "tool": tool,
            "arguments": arguments,
        }
    )


def _agent():
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        agent = session.query(Agent).filter_by(slug="coder").one()
        return agent.environment, agent.registered, agent.status


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("Bash", {"command": "ls -la"}),
        ("Bash", {"command": "git status"}),
        ("Read", {"file_path": "README.md"}),
        ("Edit", {"file_path": "app.py", "old_string": "a", "new_string": "b"}),
        ("Grep", {"pattern": "TODO"}),
    ],
)
def test_ordinary_work_is_allowed_right_after_install(tmp_path, tool, arguments):
    _install(tmp_path)
    verdict = _call(tool, arguments)
    assert verdict["verdict"] == "allow", verdict
    assert "capability.denied" not in verdict["rules"]


def test_a_destructive_command_is_still_refused(tmp_path):
    _install(tmp_path)
    verdict = _call("Bash", {"command": "rm -rf /"})
    assert verdict["verdict"] == "block"
    assert "shell.destructive" in verdict["rules"]
    assert "action.production_irreversible" not in verdict["rules"]


def test_the_agent_is_registered_in_development(tmp_path):
    result = _install(tmp_path)
    assert _agent() == ("development", True, "active")
    assert "granted" in result.output


def test_a_shadow_agent_seen_before_install_is_registered_in_development(tmp_path):
    assert runner.invoke(app, ["init", "--path", str(tmp_path)]).exit_code == 0
    _call("Read", {"file_path": "README.md"})  # the hook ran before install
    assert _agent()[1:] == (False, "shadow")
    result = runner.invoke(
        app, ["admin", "hooks", "install", "--agent", "coder", "--path", str(tmp_path), "--write"]
    )
    assert result.exit_code == 0, result.output
    assert _agent() == ("development", True, "active")
    assert _call("Read", {"file_path": "README.md"})["verdict"] == "allow"


def test_an_explicit_environment_is_kept(tmp_path):
    _install(tmp_path, "--env", "production")
    assert _agent()[0] == "production"


def test_no_grant_leaves_default_deny_in_place(tmp_path):
    _install(tmp_path, "--no-grant")
    assert "capability.denied" in _call("Read", {"file_path": "README.md"})["rules"]


def test_reinstalling_does_not_duplicate_grants(tmp_path):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Capability

    _install(tmp_path)
    runner.invoke(
        app, ["admin", "hooks", "install", "--agent", "coder", "--path", str(tmp_path), "--write"]
    )
    with session_scope() as session:
        keys = [c.tool_key for c in session.query(Capability).filter_by(granted_by="hooks install")]
    assert len(keys) == len(set(keys))
