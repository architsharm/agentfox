"""`agentfox test redteam` says what live traffic gets, and only for a real agent.

A CLI walk-through found it reporting "100% blocked" while every policy only watched,
and filing a finding for an agent that doesn't exist."""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_an_unknown_agent_is_refused_with_the_ones_that_exist(seeded):
    seeded.commit()
    result = runner.invoke(app, ["test", "redteam", "no-such-agent-xyz", "--allow-escapes"])
    assert result.exit_code == 2
    out = _flat(result.output)
    assert "No agent 'no-such-agent-xyz'" in out and "support-triage" in out


def test_blocks_by_watching_rules_are_said_as_such(seeded):
    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import set_mode

    for policy in seeded.query(Policy).all():
        set_mode(seeded, policy.key, "observe")
    seeded.commit()
    out = _flat(runner.invoke(app, ["test", "redteam", "support-triage", "--allow-escapes"]).output)
    assert "only by rules that watch" in out
    assert "would stop" in out  # the column of attacks only watching rules caught
