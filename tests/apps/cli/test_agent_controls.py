"""Stopped-agent views show current stops, not the history of resumed agents."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.core.db import session_scope
from agentfox.platform.registry.control import all_controls, kill, quarantine, resume
from agentfox.platform.registry.service import register_agent

runner = CliRunner()


@pytest.mark.parametrize("command", [["agents", "controls"], ["agents", "list", "--stopped"]])
def test_resumed_agents_are_not_stopped(command, isolated_db):
    with session_scope() as session:
        register_agent(session, "resumed-agent")
        quarantine(session, "resumed-agent", reason="investigate", actor="test")
        resume(session, "resumed-agent", reason="cleared", actor="test")
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert "all agents active" in result.output
    assert "resumed-agent" not in result.output
    # Filtering the CLI must not delete the retained control record.
    with session_scope() as session:
        assert [(r["agent"], r["state"]) for r in all_controls(session)] == [
            ("resumed-agent", "active")
        ]


@pytest.mark.parametrize("command", [["agents", "controls"], ["agents", "list", "--stopped"]])
def test_only_currently_stopped_agents_and_reasons_are_listed(command, isolated_db):
    with session_scope() as session:
        for slug in ("resumed-agent", "paused-agent", "killed-agent", "untouched-agent"):
            register_agent(session, slug)
        quarantine(session, "resumed-agent", reason="old reason", actor="test")
        resume(session, "resumed-agent", actor="test")
        quarantine(session, "paused-agent", reason="review needed", actor="operator")
        kill(session, "killed-agent", reason="stop now", actor="operator")
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert "paused-agent" in result.output and "quarantined" in result.output
    assert "killed-agent" in result.output and "killed" in result.output
    assert "review needed" in result.output and "stop now" in result.output
    assert "operator" in result.output
    assert "resumed-agent" not in result.output
    assert "untouched-agent" not in result.output
    assert "all agents active" not in result.output
