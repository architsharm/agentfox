"""SDK `check()` on an agent nobody registered (#51c, X6).

`/v1/guard/input` registers an unknown slug as a shadow agent; `check()` looked the
slug up without registering it, so the agent stayed invisible and every finding the
check raised was filed under `agent:None`.
"""

from __future__ import annotations

from agentfox.core.models import Agent, Finding
from tests.conftest import INDIRECT_INJECTION


def test_check_registers_an_unknown_agent_as_shadow_and_files_findings_under_it(seeded):
    from agentfox.frameworks.sdk import AgentFox

    fox = AgentFox(agent="never-registered-bot", session=seeded)
    fox.check(INDIRECT_INJECTION)

    agent = seeded.query(Agent).filter_by(slug="never-registered-bot").one()
    assert agent.registered is False
    assert agent.status == "shadow"
    agent_findings = seeded.query(Finding).filter(Finding.subject_type == "agent").all()
    assert agent_findings
    assert all(f.subject_id is not None for f in agent_findings)
    assert any(f.subject_id == agent.id for f in agent_findings)


def test_a_dry_run_check_does_not_create_an_agent(seeded):
    from agentfox.runtime.enforcement import Enforcer

    Enforcer(seeded).check_content(
        agent_slug="dry-run-bot", content=INDIRECT_INJECTION, persist=False
    )
    assert seeded.query(Agent).filter_by(slug="dry-run-bot").count() == 0
