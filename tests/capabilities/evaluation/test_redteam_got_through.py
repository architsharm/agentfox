"""`agentfox test redteam` on the agent `agentfox up` registers.

Two first-run findings: on an agent `up` set up it always fell back to the generic
probes ("AgentFox knows none of this agent's tools … Run agentfox init") because `up`
granted tools without declaring them; and it said "recall 100% … 0 got through" next
to "Verdict: 11 of 18 attacks get through today", then exited 0 while its help said it
exits 1 when an attack got through.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.capabilities.evaluation.redteam import (
    AGENT_TOOLS,
    agent_tool_probes,
    no_tool_probes_reason,
)


def _granted_agent(session, *tools: str):
    from agentfox.platform.identity import ensure_identity
    from agentfox.platform.identity.service import grant_capability
    from agentfox.platform.registry.service import register_agent, upsert_tool

    agent = register_agent(session, slug="granted-agent", name="Granted")
    identity = ensure_identity(session, agent)
    for key in tools:
        if "*" not in key:
            upsert_tool(session, key, name=key, impact="irreversible", actor="test")
        grant_capability(session, identity, key, granted_by="test")
    session.flush()


def test_an_agent_with_only_grants_is_attacked_through_them(seeded):
    _granted_agent(seeded, "update_seat", "mcp__github__*")
    probes, _ = agent_tool_probes(seeded, "granted-agent", ["unsafe_tool_use"])
    assert probes and all((p.target_class or "").startswith(AGENT_TOOLS) for p in probes)
    assert any(p.tool_key == "update_seat" for p in probes)
    assert not any("mcp__github" in (p.tool_key or "") for p in probes)


def test_why_no_own_tool_probes_were_written(seeded):
    from agentfox.platform.registry.service import register_agent

    register_agent(seeded, slug="bare-agent", name="Bare")
    seeded.flush()
    assert "declares no tools and holds no tool grants" in no_tool_probes_reason(
        seeded, "bare-agent"
    )
    assert "capability grant bare-agent" in no_tool_probes_reason(seeded, "bare-agent")
    _granted_agent(seeded, "mcp__github__*")
    assert "only as wildcards (mcp__github__*)" in no_tool_probes_reason(seeded, "granted-agent")


def _observe_everything(session):
    from agentfox.core.models import Policy
    from agentfox.platform.policy.store import set_mode

    for policy in session.query(Policy).all():
        set_mode(session, policy.key, "observe")


def test_got_through_means_the_same_in_every_line_and_the_exit_code(seeded):
    _granted_agent(seeded, "update_seat")
    _observe_everything(seeded)
    seeded.commit()
    args = ["test", "redteam", "granted-agent", "--sets", "unsafe_tool_use"]
    out = CliRunner().invoke(app, args, env={"COLUMNS": "200"})
    text = " ".join(out.output.split())
    recall = int(re.search(r"\d+ blocked, (\d+) got through", text).group(1))
    verdict = int(re.search(r"Verdict: (\d+) of \d+ attacks get through", text).group(1))
    # Everything only watches: what a rule would block still gets through today.
    assert recall == verdict > 0
    assert f"{recall} attack(s) got through — exit 1" in text
    assert out.exit_code == 1, out.output
    allowed = CliRunner().invoke(app, [*args, "--allow-escapes"])
    assert allowed.exit_code == 0, allowed.output


def test_an_attack_only_a_watching_rule_catches_fails_the_run(seeded):
    """The reported case: every catch by a watching rule, "0 got through", exit 0."""
    from agentfox.platform.registry.service import register_agent

    register_agent(seeded, slug="bare-agent", name="Bare")
    _observe_everything(seeded)
    seeded.commit()
    out = CliRunner().invoke(app, ["test", "redteam", "bare-agent"], env={"COLUMNS": "200"})
    text = " ".join(out.output.split())
    watched = int(re.search(r"\((\d+) of them caught by rules that only watch\)", text).group(1))
    through = int(re.search(r"\d+ blocked, (\d+) got through", text).group(1))
    assert through >= watched > 0
    assert f"Verdict: {through} of" in text
    assert f"{watched} of them stop once the rules that watch them block" in text
    assert out.exit_code == 1, out.output


def test_the_help_says_what_got_through_means():
    out = CliRunner().invoke(app, ["test", "redteam", "--help"], env={"COLUMNS": "200"})
    text = " ".join(out.output.split())
    assert "watching (observe-mode) rule catches gets through" in text
    assert "--allow-escapes" in text
