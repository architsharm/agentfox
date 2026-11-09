"""One agent, one name, one registry row, in a repository holding several apps.

The third launch audit ran `up`, `up --agent <another app's agent>`, `scan --submit`
and `init` on one monorepo and found: `up --agent X` kept the first run's entry file
(another app's, so its traffic would be credited to X); the CamelCase name the code
gives an agent became `financialplanneragent` in the registry but
`financial-planner-agent` in `auto()`; and every path added its own copy.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import Agent
from tests.apps.cli.test_up import _up, home  # noqa: F401 - fixtures

PLANNER = """
from agents import Agent, Runner, function_tool

@function_tool
def search_filings(q: str) -> str:
    return ""

PlannerAgent = Agent(name="FinancialPlannerAgent", instructions="Plan.", tools=[search_filings])

if __name__ == "__main__":
    Runner.run_sync(PlannerAgent, "hi")
"""

TRIP = """
from crewai import Agent, Crew, Task

scout = Agent(role="venue_scout", goal="find venues", backstory="b")
trip_crew = Crew(agents=[scout], tasks=[Task(description="d", expected_output="e", agent=scout)])

if __name__ == "__main__":
    trip_crew.kickoff()
"""


def _mono(tmp_path: Path) -> Path:
    root = tmp_path / "mono"
    for rel, code in {"apps/research/main.py": PLANNER, "apps/trip/main.py": TRIP}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(code))
    (root / ".git").mkdir()
    return root


def _rows() -> list[Agent]:
    with session_scope() as session:
        rows = list(session.scalars(select(Agent)))
        for row in rows:
            session.expunge(row)
    return rows


@pytest.mark.usefixtures("home")
def test_up_agent_edits_that_agents_own_app_not_the_saved_one(tmp_path):
    root = _mono(tmp_path)
    first = _up(str(root), "--yes", "--with", "python-app", "--agent", "venue-scout")
    assert first.exit_code == 0, first.output
    assert "agentfox.auto(" in (root / "apps/trip/main.py").read_text()

    second = _up(str(root), "--yes", "--with", "python-app", "--agent", "financial-planner-agent")
    assert second.exit_code == 0, second.output
    research = (root / "apps/research/main.py").read_text()
    assert 'agentfox.auto("financial-planner-agent"' in research
    assert "financial-planner-agent" not in (root / "apps/trip/main.py").read_text()


@pytest.mark.usefixtures("home")
def test_a_camel_case_agent_has_one_key_whatever_the_path(tmp_path):
    from agentfox.platform.registry.service import observe_agent, slugify

    assert slugify("FinancialPlannerAgent") == "financial-planner-agent"
    root = _mono(tmp_path)
    result = _up(
        str(root), "--yes", "--with", "python-app,scan-report", "--agent", "financial-planner-agent"
    )
    assert result.exit_code == 0, result.output
    # auto("FinancialPlannerAgent") at runtime lands on the same row.
    with session_scope() as session:
        agent, shadow = observe_agent(session, "FinancialPlannerAgent")
        assert (agent.slug, shadow) == ("financial-planner-agent", False)
    planners = [a for a in _rows() if "planner" in a.slug]
    assert [a.slug for a in planners] == ["financial-planner-agent"]


def test_an_agent_registered_under_the_old_key_is_found_by_its_name(tmp_path, monkeypatch):
    """A database from before the keys were unified keeps its agent."""
    from agentfox.platform.registry.service import find_agent, observe_agent, register_agent

    monkeypatch.setenv("AGENTFOX_DATABASE_URL", f"sqlite:///{tmp_path / 'af.db'}")
    from agentfox.core.db import init_db

    init_db()
    with session_scope() as session:
        old = Agent(slug="financialplanneragent", name="FinancialPlannerAgent", status="active")
        session.add(old)
        session.flush()
        assert find_agent(session, "FinancialPlannerAgent").slug == "financialplanneragent"
        agent, shadow = observe_agent(session, "FinancialPlannerAgent")
        assert (agent.slug, shadow) == ("financialplanneragent", False)
        again = register_agent(session, "FinancialPlannerAgent", name="FinancialPlannerAgent")
        assert again.slug == "financialplanneragent"
        assert len(list(session.scalars(select(Agent)))) == 1


ADK = """
from google.adk.agents import LlmAgent

def lookup_fund(name: str) -> str:
    return ""

root_agent = LlmAgent(name="fund_advisor", model="gemini-2.5-pro", instruction="advise",
                      tools=[lookup_fund])
"""


@pytest.mark.usefixtures("home")
def test_up_says_auto_does_not_govern_an_adk_agents_model_calls(tmp_path):
    root = tmp_path / "advisor"
    (root / "app").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "app" / "agent.py").write_text(textwrap.dedent(ADK))
    result = _up(str(root), "--yes", "--with", "python-app")
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "NOT governed by auto()" in out
    assert "google-genai" in out
    assert "records every call" not in out
