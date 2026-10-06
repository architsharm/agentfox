"""#33 — `policy simulate` replays a candidate alongside what else was in force.

It evaluated the candidate alone, so every block another pack made showed up as
"newly allowed"; it printed only the newly blocked; and `--agent` matched through
traces, dropping every decision recorded without one.
"""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.cli.main import app
from agentfox.platform.policy import PolicyDocument, save_policy, simulate
from agentfox.registry.service import register_agent
from agentfox.runtime.enforcement import Enforcer

PACK_A = """
key: pack-a
mode: enforce
rules:
  - id: a.block
    when: {surface: [input]}
    effect: block
    reason: pack a blocks input
"""

CANDIDATE_B = """
key: pack-b
mode: observe
rules:
  - id: b.escalate
    when: {surface: [output]}
    effect: escalate
"""


def _record(session):
    agent = register_agent(session, "sim-bot")
    save_policy(session, PolicyDocument.from_yaml(PACK_A), bind_mode="enforce")
    result = Enforcer(session).evaluate(
        agent=agent, identity=None, content="hello", surface="input"
    )  # no trace: a bare evaluate, as the SDK's check() records
    assert result.verdict == "block"
    session.flush()


def test_another_packs_block_is_not_reported_as_newly_allowed(session):
    _record(session)
    diff = simulate(session, PolicyDocument.from_yaml(CANDIDATE_B))
    assert diff.replayed == 1
    assert diff.newly_allowed == []
    assert diff.unchanged == 1


def test_a_new_version_that_drops_a_rule_is_newly_allowed(session):
    _record(session)
    loosened = PACK_A.replace("effect: block", "effect: allow")
    diff = simulate(session, PolicyDocument.from_yaml(loosened))
    assert [r["was"] for r in diff.newly_allowed] == ["block"]
    assert [r["now"] for r in diff.newly_allowed] == ["allow"]


def test_agent_filter_keeps_decisions_recorded_without_a_trace(session):
    _record(session)
    diff = simulate(session, PolicyDocument.from_yaml(CANDIDATE_B), agent_slug="sim-bot")
    assert diff.replayed == 1
    assert (
        simulate(session, PolicyDocument.from_yaml(CANDIDATE_B), agent_slug="other").replayed == 0
    )


def test_cli_lists_newly_allowed_and_escalated_decisions(session, tmp_path):
    _record(session)
    session.commit()
    path = tmp_path / "loosened.yaml"
    path.write_text(PACK_A.replace("effect: block", "effect: allow"))
    out = CliRunner().invoke(app, ["policy", "simulate", "--file", str(path)]).output
    assert "would allow" in out
    assert "sim-bot" in out
