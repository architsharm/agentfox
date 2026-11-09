"""One agent = one registry row, whichever path registered it first.

The third launch audit followed both documented paths on one repository, `agentfox
init --key` then `agentfox up` (which records its scan, as `scan --submit` does), and
found each agent two or three times (`surprisetravelcrew`, `mono-surprisetravelcrew`,
`surprise-travel-crew`); Proposed doubled on another scan, every scan added zero-rule
`scan-<run id>-<framework>` policies, and init's agents were all "production".
"""

from __future__ import annotations

from sqlalchemy import func, select

from agentfox.capabilities.onboarding.service import register_structure
from agentfox.core.models import Agent, Policy, ScanRun
from agentfox.platform.registry.service import propose_from_scan, register_agent

STRUCTURE = {
    "sources": [],
    "systems": [],
    "tools": [],
    "agents": [
        {
            "id": "ag-1",
            "key": "surprise-travel-crew",
            "name": "SurpriseTravelCrew",
            "framework": "CrewAI",
            "handoffs": [],
        },
        {
            "id": "ag-2",
            "key": "restaurant-scout",
            "name": "restaurant_scout",
            "framework": "CrewAI",
            "handoffs": [],
        },
    ],
}

SPECS = [
    {
        "key": "surprise-travel-crew",
        "name": "SurpriseTravelCrew",
        "framework": "CrewAI",
        "tools": [],
        "top_dir": "apps",
    },
    {
        "key": "restaurant-scout",
        "name": "restaurant_scout",
        "framework": "CrewAI",
        "tools": ["search_web"],
        "top_dir": "apps",
    },
]


def _scan(session, _name: str) -> tuple[list[str], list[str]]:
    run = ScanRun(source_kind="cli", repo_full_name="mono", status="completed")
    session.add(run)
    session.flush()
    return propose_from_scan(
        session,
        run_id=run.id,
        repo_slug_base="mono",
        repo_display_name="mono",
        frameworks=["CrewAI", "AgentFox"],
        sites=[],
        author="dev@example.com",
        agents=SPECS,
        agent_edges=[{"parent": "surprise-travel-crew", "child": "restaurant-scout"}],
    )


def _count(session) -> int:
    return session.scalar(select(func.count()).select_from(Agent))


def test_init_then_scan_then_up_is_one_row_per_agent(session):
    register_structure(session, STRUCTURE, project="mono", actor="dev@example.com")
    assert {a.slug for a in session.scalars(select(Agent))} == {
        "surprise-travel-crew",
        "restaurant-scout",
    }
    _scan(session, "scn_1")
    _scan(session, "scn_2")  # a re-scan updates the proposals
    # `agentfox up` registers the agent it sets up under the scan's name.
    register_agent(
        session,
        "surprise-travel-crew",
        name="mono/SurpriseTravelCrew",
        environment="development",
        project="mono",
    )
    assert _count(session) == 2, [a.slug for a in session.scalars(select(Agent))]
    scout = session.scalar(select(Agent).where(Agent.slug == "restaurant-scout"))
    assert "search_web" in scout.declared_tools


def test_scans_propose_one_policy_per_framework_and_none_for_agentfox(session):
    _agents, first = _scan(session, "scn_1")
    _agents, second = _scan(session, "scn_2")
    assert first == ["scan-mono-crew-ai"]
    assert second == []
    assert session.scalar(select(func.count()).select_from(Policy)) == 1


def test_code_read_from_a_checkout_is_development_until_someone_says(session):
    register_structure(session, STRUCTURE, project="mono", actor="dev@example.com")
    _scan(session, "scn_1")
    assert {a.environment for a in session.scalars(select(Agent))} == {"development"}
