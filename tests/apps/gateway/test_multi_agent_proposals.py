"""A scanned multi-agent system becomes one proposed agent per agent, joined by the
delegations its code declares, and the map shows that structure before any traffic.

The failure this replaces: a repository with a triage agent and three specialists came
out of a scan as one proposal per directory, all four agents' tools pooled into one,
and the hierarchy appeared on the map only after the system had run ungoverned long
enough to produce subagent spans.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from sqlalchemy import select

from agentfox.capabilities.discovery.repo import scan
from agentfox.core.models import Agent, LineageEdge, ScanRun
from agentfox.platform.registry.service import (
    assess_delegation,
    propose_from_scan,
    record_edge,
)
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")

SYSTEM = """
from agents import Agent, function_tool

@function_tool
def lookup_invoice(invoice_id: str) -> str:
    return "paid"

@function_tool
def issue_refund(invoice_id: str) -> str:
    return "ok"

billing = Agent(name="Billing", instructions="Bills.", tools=[lookup_invoice])
refunds = Agent(name="Refunds", instructions="Refunds.", tools=[issue_refund])
triage = Agent(name="Triage", instructions="Route.", handoffs=[billing, refunds])
"""


def _system_report(tmp_path: Path):
    (tmp_path / "support").mkdir()
    (tmp_path / "support" / "bots.py").write_text(textwrap.dedent(SYSTEM))
    return scan(tmp_path)


def _run(session) -> str:
    run = ScanRun(source_kind="cli", repo_full_name="acme/helpdesk", status="completed")
    session.add(run)
    session.flush()
    return run.id


def _propose(session, report):
    return propose_from_scan(
        session,
        run_id=_run(session),
        repo_slug_base="helpdesk",
        repo_display_name="acme/helpdesk",
        frameworks=report.frameworks,
        sites=[
            {"kind": s.kind, "top_dir": "support", "provider": s.provider}
            for s in report.sites
            if s.kind in ("agent_definition", "tool", "model_call")
        ],
        author="test",
        agents=[{**a.to_json(), "top_dir": a.top_dir} for a in report.agents],
        agent_edges=[e.to_json() for e in report.agent_edges],
    )


def _delegations(session) -> set[tuple[str, str, str | None, bool, int]]:
    return {
        (e.src_id, e.dst_id, e.kind, e.declared, e.observed_count)
        for e in session.scalars(select(LineageEdge).where(LineageEdge.relation == "delegates_to"))
    }


def test_one_draft_per_agent_with_its_own_tools_and_declared_edges(session, tmp_path):
    agents, _ = _propose(session, _system_report(tmp_path))

    assert sorted(agents) == ["helpdesk-billing", "helpdesk-refunds", "helpdesk-triage"]
    rows = {a.slug: a for a in session.scalars(select(Agent))}
    assert rows["helpdesk-billing"].declared_tools == ["lookup_invoice"]
    assert rows["helpdesk-refunds"].declared_tools == ["issue_refund"]
    assert rows["helpdesk-triage"].declared_tools == []
    assert all(rows[s].status == "draft" for s in agents)
    assert rows["helpdesk-triage"].name == "acme/helpdesk/Triage"
    # The directory the system lives in is not proposed a second time as a blob.
    assert "helpdesk-support" not in rows
    assert _delegations(session) == {
        ("helpdesk-triage", "helpdesk-billing", "handoff", True, 0),
        ("helpdesk-triage", "helpdesk-refunds", "handoff", True, 0),
    }


def test_rescan_updates_in_place_and_drops_a_handoff_the_code_removed(session, tmp_path):
    report = _system_report(tmp_path)
    _propose(session, report)
    # Traffic later confirms one of the two handoffs.
    record_edge(session, "agent", "helpdesk-triage", "agent", "helpdesk-billing", "delegates_to")

    report.agent_edges = [e for e in report.agent_edges if e.child != "refunds"]
    _propose(session, report)
    _propose(session, report)

    assert session.scalar(select(Agent).where(Agent.slug == "helpdesk-triage")) is not None
    assert len(list(session.scalars(select(Agent)))) == 3
    assert _delegations(session) == {
        ("helpdesk-triage", "helpdesk-billing", "handoff", True, 1),
    }


def test_rescan_never_turns_an_added_agent_back_into_a_proposal(session, tmp_path):
    report = _system_report(tmp_path)
    _propose(session, report)
    triage = session.scalar(select(Agent).where(Agent.slug == "helpdesk-triage"))
    triage.status, triage.registered = "active", True
    session.flush()

    agents, _ = _propose(session, report)

    assert "helpdesk-triage" not in agents
    assert triage.status == "active" and triage.registered is True


def test_a_single_agent_repo_keeps_the_per_directory_proposal(session, tmp_path):
    (tmp_path / "bot").mkdir()
    (tmp_path / "bot" / "main.py").write_text(
        "from agents import Agent\nsolo = Agent(name='Solo', instructions='x')\n"
    )
    report = scan(tmp_path)
    agents, _ = propose_from_scan(
        session,
        run_id=_run(session),
        repo_slug_base="solo",
        repo_display_name="solo",
        frameworks=report.frameworks,
        sites=[{"kind": "model_call", "top_dir": "bot", "provider": "openai"}],
        author="t",
        agents=[{**a.to_json(), "top_dir": a.top_dir} for a in report.agents],
        agent_edges=[],
    )
    assert agents == ["solo-bot"]


def test_handoffs_back_to_triage_are_not_a_delegation_cycle(session):
    record_edge(session, "agent", "a", "agent", "b", "delegates_to", declared=True, kind="handoff")
    record_edge(session, "agent", "b", "agent", "a", "delegates_to", declared=True, kind="handoff")
    assert assess_delegation(session) == []


# ---------------------------------------------------------------------------
# Through the API: submission, map, lineage, list and "Add all"
# ---------------------------------------------------------------------------


def _submit(client) -> None:
    response = client.post(
        "/api/discovery/submit",
        json={
            "source": "check",
            "label": "helpdesk",
            "frameworks": ["OpenAI Agents SDK"],
            "sites": [{"kind": "tool", "top_dir": "support", "provider": None}],
            "agents": [
                {
                    "key": "triage",
                    "name": "Triage",
                    "framework": "OpenAI Agents SDK",
                    "top_dir": "support",
                },
                {
                    "key": "billing",
                    "name": "Billing",
                    "framework": "OpenAI Agents SDK",
                    "top_dir": "support",
                },
                {
                    "key": "refunds",
                    "name": "Refunds",
                    "framework": "OpenAI Agents SDK",
                    "top_dir": "support",
                },
            ],
            "agent_edges": [
                {"parent": "triage", "child": "billing", "relation": "handoff"},
                {"parent": "triage", "child": "refunds", "relation": "as_tool"},
            ],
        },
        headers=ADMIN,
    )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert sorted(summary["agents_proposed"]) == [
        "helpdesk-billing",
        "helpdesk-refunds",
        "helpdesk-triage",
    ]


def test_map_shows_declared_sub_agents_and_parents_before_traffic(client):
    _submit(client)

    parent = client.get("/api/agents/helpdesk-triage/map", headers=ADMIN).json()
    subs = {s["slug"]: s for s in parent["subagents"]}
    assert subs["helpdesk-billing"] == {
        "slug": "helpdesk-billing",
        "name": "helpdesk/Billing",
        "calls": 0,
        "declared": True,
        "seen": False,
        "relation": "handoff",
    }
    assert subs["helpdesk-refunds"]["relation"] == "as_tool"
    assert parent["parents"] == []

    child = client.get("/api/agents/helpdesk-billing/map", headers=ADMIN).json()
    assert [(p["slug"], p["relation"]) for p in child["parents"]] == [
        ("helpdesk-triage", "handoff")
    ]
    assert child["subagents"] == []

    lineage = client.get("/api/agents/helpdesk-triage/lineage", headers=ADMIN).json()
    assert {(link["target"], link["declared"]) for link in lineage["links"]} >= {
        ("helpdesk-billing", True)
    }


def test_a_seen_edge_still_counts_its_calls(client, session):
    _submit(client)
    record_edge(session, "agent", "helpdesk-triage", "agent", "helpdesk-billing", "delegates_to")
    record_edge(session, "agent", "helpdesk-triage", "agent", "ad-hoc-helper", "delegates_to")
    session.commit()

    subs = {
        s["slug"]: s
        for s in client.get("/api/agents/helpdesk-triage/map", headers=ADMIN).json()["subagents"]
    }
    assert subs["helpdesk-billing"]["calls"] == 1
    assert subs["helpdesk-billing"]["declared"] and subs["helpdesk-billing"]["seen"]
    assert subs["ad-hoc-helper"] == {
        "slug": "ad-hoc-helper",
        "name": "ad-hoc-helper",
        "calls": 1,
        "declared": False,
        "seen": True,
        "relation": None,
    }


def test_agent_list_carries_children_and_add_all_approves_the_system(client):
    _submit(client)
    agents = {a["slug"]: a for a in client.get("/api/agents", headers=ADMIN).json()["agents"]}
    triage = agents["helpdesk-triage"]
    assert [c["slug"] for c in triage["children"]] == ["helpdesk-billing", "helpdesk-refunds"]

    response = client.post(f"/api/agents/{triage['id']}/approve-system", headers=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json()["approved"] == [
        "helpdesk-triage",
        "helpdesk-billing",
        "helpdesk-refunds",
    ]
    agents = {a["slug"]: a for a in client.get("/api/agents", headers=ADMIN).json()["agents"]}
    assert all(agents[s]["status"] == "active" for s in agents if s.startswith("helpdesk-"))

    again = client.post(f"/api/agents/{triage['id']}/approve-system", headers=ADMIN)
    assert again.status_code == 404


def test_a_dismissed_sub_agent_leaves_the_map(client):
    _submit(client)
    agents = {a["slug"]: a for a in client.get("/api/agents", headers=ADMIN).json()["agents"]}
    client.post(f"/api/agents/{agents['helpdesk-refunds']['id']}/reject", headers=ADMIN)

    subs = client.get("/api/agents/helpdesk-triage/map", headers=ADMIN).json()["subagents"]
    assert [s["slug"] for s in subs] == ["helpdesk-billing"]
