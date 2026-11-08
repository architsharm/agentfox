"""`agentfox up` registers each agent once, and leaves policy modes as it set them.

A first-run re-audit found every agent registered twice: the scan's draft
(``lg-supervisor-supervisor``, production, listed as SHADOW) next to `up`'s own agent
(development, no framework, no declared tools, so `agentfox test redteam` fell back to
generic probes). And `agentfox init` run after `up` put tool-containment back to
enforce.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.core.db import session_scope
from agentfox.core.models import Agent, LineageEdge, Policy
from tests.apps.cli.test_up import _up, home, project  # noqa: F401 - fixtures

runner = CliRunner()

SYSTEM = """
from agents import Agent, Runner, function_tool

@function_tool
def lookup_invoice(invoice_id: str) -> str:
    return "paid"

@function_tool
def issue_refund(invoice_id: str) -> str:
    return "ok"

billing = Agent(name="Billing", instructions="Bills.", tools=[lookup_invoice])
refunds = Agent(name="Refunds", instructions="Refunds.", tools=[issue_refund])
triage = Agent(name="Triage", instructions="Route.", handoffs=[billing, refunds])

if __name__ == "__main__":
    Runner.run_sync(triage, "hi")
"""

SOLO = """
from agents import Agent, Runner, function_tool

@function_tool
def customer_balance(customer_id: int) -> str:
    return "100"

support_agent = Agent(name="Support", instructions="Help.", tools=[customer_balance])

if __name__ == "__main__":
    Runner.run_sync(support_agent, "hi")
"""


def _repo(tmp_path: Path, name: str, code: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / ".git").mkdir()
    (root / "app.py").write_text(textwrap.dedent(code))
    return root


def _agents() -> dict[str, Agent]:
    with session_scope() as session:
        rows = list(session.scalars(select(Agent)))
        for row in rows:
            session.expunge(row)
    return {a.slug: a for a in rows}


@pytest.mark.usefixtures("home")
def test_up_registers_each_agent_of_a_system_once(tmp_path):
    root = _repo(tmp_path, "helpdesk", SYSTEM)
    result = _up(str(root), "--yes", "--with", "python-app,tools,scan-report")
    assert result.exit_code == 0, result.output
    agents = _agents()
    live = [a for a in agents.values() if a.status != "draft"]
    assert [a.slug for a in live] == ["triage"]
    triage = agents["triage"]
    # The scan's proposal for the same code landed on it: one row, carrying what the
    # scan read, in development (it runs here).
    assert triage.name == "helpdesk/Triage" and triage.framework
    assert triage.environment == "development" and triage.project == "helpdesk"
    assert {"lookup_invoice", "issue_refund"} <= set(triage.declared_tools)
    assert not [a for a in agents.values() if a.name == triage.name and a.slug != "triage"]
    # The sub-agents stay proposals, for this machine too.
    assert {a.slug for a in agents.values() if a.status == "draft"} == {"billing", "refunds"}
    assert {a.environment for a in agents.values()} == {"development"}
    with session_scope() as session:
        edges = {
            (e.src_id, e.dst_id)
            for e in session.scalars(select(LineageEdge).where(LineageEdge.declared.is_(True)))
        }
    assert {("triage", "billing"), ("triage", "refunds")} <= edges


@pytest.mark.usefixtures("home")
def test_a_single_agent_repo_is_not_also_proposed_as_its_directory(tmp_path):
    root = _repo(tmp_path, "pai-bank", SOLO)
    assert _up(str(root), "--yes", "--with", "python-app,tools,scan-report").exit_code == 0
    agents = _agents()
    assert list(agents) == ["support"], agents
    assert agents["support"].declared_tools == ["customer_balance"]


@pytest.mark.usefixtures("home")
def test_up_folds_the_duplicate_an_earlier_run_left(tmp_path):
    """A database from before: `up`'s agent and the scan's prefixed draft of it."""
    from agentfox.platform.registry.service import propose_draft, record_edge, register_agent

    root = _repo(tmp_path, "helpdesk", SYSTEM)
    with session_scope() as session:
        register_agent(session, "triage", name="triage", environment="development")
        propose_draft(
            session,
            slug="helpdesk-triage",
            name="helpdesk/Triage",
            framework="OpenAI Agents SDK",
            declared_tools=["lookup_invoice"],
        )
        propose_draft(session, slug="helpdesk-billing", name="helpdesk/Billing")
        record_edge(
            session,
            "agent",
            "helpdesk-triage",
            "agent",
            "helpdesk-billing",
            "delegates_to",
            declared=True,
        )
    assert _up(str(root), "--yes", "--with", "python-app,tools").exit_code == 0
    agents = _agents()
    assert agents["helpdesk-triage"].status == "rejected"  # dismissed, folded in
    assert agents["triage"].framework == "OpenAI Agents SDK"
    assert "lookup_invoice" in agents["triage"].declared_tools
    with session_scope() as session:
        edges = {(e.src_id, e.dst_id) for e in session.scalars(select(LineageEdge))}
    assert ("triage", "helpdesk-billing") in edges
    listed = runner.invoke(app, ["agents", "list"], env={"COLUMNS": "200"})
    assert "helpdesk-triage" not in listed.output and "1 dismissed" in listed.output
    assert "SHADOW" not in listed.output and "draft" in listed.output


@pytest.mark.usefixtures("home")
def test_redteam_attacks_ups_agent_through_its_own_tools(tmp_path):
    root = _repo(tmp_path, "helpdesk", SYSTEM)
    assert _up(str(root), "--yes", "--with", "python-app,tools").exit_code == 0
    out = runner.invoke(app, ["test", "redteam", "triage", "--allow-escapes"])
    text = " ".join(out.output.split())
    assert "probes written from its" in text
    assert "built-in generic probes" not in text


def test_init_after_up_keeps_the_modes_up_set(project):  # noqa: F811
    assert _up(str(project), "--yes").exit_code == 0  # watch first: everything observes
    result = runner.invoke(app, ["init", "--path", str(project)])
    assert result.exit_code == 0, result.output
    from agentfox.platform.policy import current_binding

    with session_scope() as session:
        policy = session.scalar(select(Policy).where(Policy.key == "tool-containment"))
        assert current_binding(session, policy.id)[0].mode == "observe"
    assert "tool-containment observe" in " ".join(result.output.split())
    # "(kept)" marks only a pack someone switched to blocking; both watch here.
