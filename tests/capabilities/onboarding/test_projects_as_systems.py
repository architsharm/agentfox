"""Projects are systems: a root agent and everything it hands work to.

The same thing whether a repository scan proposed the system or `agentfox init`
reported it; ``agents.project`` (the repository init mapped an agent from) is only
provenance. Two repositories each with a "Triage Agent" are two agents, and
disconnecting one never touches the other.
"""

from __future__ import annotations

from sqlalchemy import select

from agentfox.capabilities.onboarding import service
from agentfox.core.db import session_scope
from agentfox.core.models import Agent, LineageEdge
from agentfox.core.tenancy import system_scope
from agentfox.platform.registry.projects import systems_of
from agentfox.platform.registry.service import lineage, record_edge
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


# --- the grouping itself -----------------------------------------------------------


def test_a_root_is_what_nothing_hands_work_to_and_a_cycle_enters_at_its_hub():
    nodes = ["triage", "faq", "booking", "seat", "guard", "solo"]
    edges = [
        ("triage", "faq", "handoff"),
        ("triage", "booking", "handoff"),
        ("triage", "seat", "handoff"),
        ("faq", "triage", "handoff"),
        ("booking", "triage", "handoff"),
        ("booking", "seat", "handoff"),
        ("seat", "triage", "handoff"),
    ]
    systems = systems_of(nodes, edges)
    assert [s["root"] for s in systems] == ["guard", "solo", "triage"]
    guard, solo, triage = systems
    # Agents with no edges are a project each.
    assert solo["members"] == [{"slug": "solo", "depth": 0, "relation": None, "parent": None}]
    assert [m["slug"] for m in guard["members"]] == ["guard"]
    # Every specialist hands back to triage: triage hands off to the most, so it leads.
    assert triage["members"][0]["slug"] == "triage"
    assert {m["slug"]: m["depth"] for m in triage["members"]} == {
        "triage": 0,
        "booking": 1,
        "faq": 1,
        "seat": 1,
    }
    assert systems_of(list(reversed(nodes)), list(reversed(edges))) == systems

    # Something outside the cycle that hands work into it is the entry instead.
    entered = systems_of(nodes, [*edges, ("guard", "faq", "as_tool")])
    assert [s["root"] for s in entered] == ["guard", "solo"]
    assert [(m["slug"], m["depth"]) for m in entered[0]["members"]] == [
        ("guard", 0),
        ("faq", 1),
        ("triage", 2),
        ("booking", 3),
        ("seat", 3),
    ]
    assert entered[0]["members"][1]["relation"] == "as_tool"


def test_ties_in_a_cycle_are_broken_by_name():
    systems = systems_of(["b", "a"], [("a", "b", "handoff"), ("b", "a", "handoff")])
    assert [s["root"] for s in systems] == ["a"]
    assert systems[0]["members"][1] == {
        "slug": "b",
        "depth": 1,
        "relation": "handoff",
        "parent": "a",
    }


# --- through the API -----------------------------------------------------------------


def _key(client) -> str:
    return client.get("/api/onboarding/key", headers=ADMIN).json()["value"]


def _connect(client, key: str, project: str, agents: list[dict], tools: list[dict]) -> list:
    structure = {
        "sources": [{"id": "src-1", "label": "Customers", "detail": "chat, chat.py"}],
        "agents": agents,
        "tools": tools,
        "systems": [
            {"id": "sys-pay", "name": "Payments", "kind": "payments"},
            {"id": "sys-db", "name": "Orders", "kind": "database"},
        ],
    }
    r = client.post(
        "/api/onboarding/runner/connect",
        json={"structure": structure, "project": project},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text
    return client.get("/api/onboarding/structure", headers=ADMIN).json()["structure"]["agents"]


def _repo_a(client, key):
    return _connect(
        client,
        key,
        "repo-a",
        [
            {
                "id": "ag-1",
                "name": "Triage Agent",
                "model": "gpt-4o",
                "sourceIds": ["src-1"],
                "handsOffTo": ["ag-2"],
                "handoffs": [{"agentId": "ag-2", "relation": "handoff"}],
            },
            {"id": "ag-2", "name": "Billing Agent", "model": "gpt-4o", "sourceIds": []},
        ],
        [
            {"id": "t1", "name": "get_order", "agentId": "ag-1", "systemId": "sys-db"},
            {
                "id": "t2",
                "name": "issue_refund",
                "agentId": "ag-2",
                "risk": "high",
                "systemId": "sys-pay",
            },
        ],
    )


def _repo_b(client, key):
    return _connect(
        client,
        key,
        "repo-b",
        [{"id": "ag-1", "name": "Triage Agent", "model": "gpt-4o-mini", "sourceIds": ["src-1"]}],
        [{"id": "t1", "name": "lookup_faq", "agentId": "ag-1", "systemId": "sys-db"}],
    )


def _projects(client) -> dict[str, dict]:
    return {p["project"]: p for p in client.get("/api/projects", headers=ADMIN).json()["projects"]}


def test_two_repos_with_a_triage_agent_are_two_agents_and_disconnecting_one_spares_the_other(
    client,
):
    key = _key(client)
    a = {x["name"]: x["slug"] for x in _repo_a(client, key)}
    assert a == {"Triage Agent": "triage-agent", "Billing Agent": "billing-agent"}
    # repo-a's agents go live, with their basic guardrails.
    assert client.post("/api/projects/repo-a/approve", headers=ADMIN).status_code == 200
    on = client.post("/api/onboarding/projects/repo-a/basic-guardrails", headers=ADMIN)
    assert sorted(on.json()["added"]) == ["billing-agent", "triage-agent"]

    b = {x["name"]: x["slug"] for x in _repo_b(client, key)}
    # repo-a's Triage Agent is never repo-b's: repo-b's gets a name of its own.
    assert b == {"Triage Agent": "repo-b-triage-agent"}
    projects = _projects(client)
    assert projects["triage-agent"]["slugs"] == ["triage-agent", "billing-agent"]
    assert projects["triage-agent"]["repos"] == ["repo-a"]
    assert projects["repo-b-triage-agent"]["repos"] == ["repo-b"]

    gone = client.delete("/api/projects/repo-b", headers=ADMIN)
    assert gone.status_code == 200 and gone.json()["removed"] == ["repo-b-triage-agent"]

    # repo-a is exactly as it was: live, guarded, its hand-off and input still drawn.
    with session_scope() as s, system_scope("test"):
        for slug in ("triage-agent", "billing-agent"):
            agent = s.scalar(select(Agent).where(Agent.slug == slug))
            assert agent.status == "active" and agent.project == "repo-a"
            assert service.basic_mode(s, slug) is not None
            assert agent.guardrails_snapshot is None
    m = client.get("/api/projects/repo-a/map", headers=ADMIN).json()
    triage = next(x for x in m["agents"] if x["slug"] == "triage-agent")
    assert triage["hands_off_to"] == ["billing-agent"]
    assert m["inputs"] == [
        {"label": "Customers", "detail": "chat, chat.py", "agents": ["triage-agent"]}
    ]
    assert "repo-b-triage-agent" not in _projects(client)


def test_a_project_is_its_systems_closure_across_repositories(client):
    key = _key(client)
    _repo_a(client, key)
    _repo_b(client, key)
    # repo-b's triage hands work to repo-a's billing agent (traffic saw it).
    with session_scope() as s, system_scope("test"):
        record_edge(s, "agent", "repo-b-triage-agent", "agent", "billing-agent", "delegates_to")

    projects = _projects(client)
    assert projects["repo-b-triage-agent"]["slugs"] == ["repo-b-triage-agent", "billing-agent"]
    assert projects["repo-b-triage-agent"]["repos"] == ["repo-a", "repo-b"]
    member = projects["repo-b-triage-agent"]["members"][1]
    assert (member["slug"], member["depth"], member["repo"]) == ("billing-agent", 1, "repo-a")

    # The root's map draws the sub-agent from the other repository.
    m = client.get("/api/projects/repo-b-triage-agent/map", headers=ADMIN).json()
    assert [x["slug"] for x in m["agents"]] == ["repo-b-triage-agent", "billing-agent"]
    assert m["agents"][0]["hands_off_to"] == ["billing-agent"]
    # A repository's name still opens the systems its agents are in, parents included.
    legacy = client.get("/api/projects/repo-a/map", headers=ADMIN).json()
    assert {x["slug"] for x in legacy["agents"]} == {
        "triage-agent",
        "billing-agent",
        "repo-b-triage-agent",
    }
    assert set(legacy["roots"]) == {"triage-agent", "repo-b-triage-agent"}
    assert client.get("/api/projects/no-such-thing/map", headers=ADMIN).status_code == 404
    # Acting on the repository reaches its own agents, not a parent in another one.
    added = client.post("/api/projects/repo-a/approve", headers=ADMIN).json()["approved"]
    assert added == ["billing-agent", "triage-agent"]
    assert client.get("/api/agents/repo-b-triage-agent", headers=ADMIN).json()["status"] == "draft"

    # Disconnecting repo-b removes its own agent only; the hand-off into repo-a stays
    # (it is in traffic, and it is repo-a's agent too).
    gone = client.delete("/api/projects/repo-b-triage-agent", headers=ADMIN).json()
    assert gone["removed"] == ["repo-b-triage-agent"]
    with session_scope() as s, system_scope("test"):
        edge = s.scalar(
            select(LineageEdge).where(
                LineageEdge.src_id == "repo-b-triage-agent",
                LineageEdge.dst_id == "billing-agent",
            )
        )
        assert edge is not None
        assert s.scalar(select(Agent).where(Agent.slug == "billing-agent")).status == "active"


def test_a_declared_hand_off_into_another_project_survives_a_disconnect(client):
    key = _key(client)
    _repo_a(client, key)
    _repo_b(client, key)
    with session_scope() as s, system_scope("test"):
        record_edge(
            s,
            "agent",
            "repo-b-triage-agent",
            "agent",
            "billing-agent",
            "delegates_to",
            declared=True,
            kind="as_tool",
        )
    client.delete("/api/projects/repo-b", headers=ADMIN)
    with session_scope() as s, system_scope("test"):
        kept = s.scalar(
            select(LineageEdge).where(
                LineageEdge.src_id == "repo-b-triage-agent",
                LineageEdge.dst_id == "billing-agent",
            )
        )
        assert kept is not None and kept.declared and kept.kind == "as_tool"
        # Its own input edge went with it.
        assert (
            s.scalar(
                select(LineageEdge).where(
                    LineageEdge.relation == "talks_to",
                    LineageEdge.dst_id == "repo-b-triage-agent",
                )
            )
            is None
        )


def test_disconnected_agents_leave_the_agent_list_and_can_get_their_guardrails_back(client):
    key = _key(client)
    _repo_a(client, key)
    client.post("/api/projects/repo-a/approve", headers=ADMIN)
    client.post("/api/onboarding/projects/repo-a/basic-guardrails", headers=ADMIN)
    with session_scope() as s, system_scope("test"):
        before = service.basic_mode(s, "triage-agent")
    assert before is not None

    # Nothing to restore yet.
    assert (
        client.post("/api/agents/triage-agent/restore-guardrails", headers=ADMIN).status_code == 404
    )
    out = client.delete("/api/projects/triage-agent", headers=ADMIN).json()
    assert sorted(out["removed"]) == ["billing-agent", "triage-agent"]
    assert out["restorable"] == ["billing-agent", "triage-agent"]

    slugs = {a["slug"] for a in client.get("/api/agents", headers=ADMIN).json()["agents"]}
    assert not {"triage-agent", "billing-agent"} & slugs
    everyone = client.get("/api/agents?include_removed=true", headers=ADMIN).json()["agents"]
    assert {a["slug"]: a["status"] for a in everyone}["triage-agent"] == "removed"
    with session_scope() as s, system_scope("test"):
        assert service.basic_mode(s, "triage-agent") is None
        snap = s.scalar(select(Agent).where(Agent.slug == "triage-agent")).guardrails_snapshot
        assert snap[service.basic_key("triage-agent")]["mode"] == before
    # Still disconnected: connect it again first.
    assert (
        client.post("/api/agents/triage-agent/restore-guardrails", headers=ADMIN).status_code == 409
    )

    again = {a["slug"]: a for a in _repo_a(client, key)}
    assert again["triage-agent"]["restorable"] is True
    assert client.get("/api/agents/triage-agent", headers=ADMIN).json()["status"] == "draft"
    m = client.get("/api/projects/triage-agent/map", headers=ADMIN).json()
    assert next(x for x in m["agents"] if x["slug"] == "triage-agent")["restorable"] is True

    r = client.post("/api/agents/triage-agent/restore-guardrails", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["restored"][service.basic_key("triage-agent")]["mode"] in ("observe", "enforce")
    with session_scope() as s, system_scope("test"):
        assert service.basic_mode(s, "triage-agent") is not None
        assert (
            s.scalar(select(Agent).where(Agent.slug == "triage-agent")).guardrails_snapshot is None
        )
    # Used once.
    assert (
        client.post("/api/agents/triage-agent/restore-guardrails", headers=ADMIN).status_code == 404
    )


def test_what_init_declares_is_kept_in_attrs_and_inputs_are_no_blast_radius(client):
    key = _key(client)
    _repo_a(client, key)
    with session_scope() as s, system_scope("test"):
        talks = s.scalar(
            select(LineageEdge).where(
                LineageEdge.relation == "talks_to", LineageEdge.dst_id == "triage-agent"
            )
        )
        assert talks.kind is None and talks.attrs == {"detail": "chat, chat.py"}
        touches = s.scalar(
            select(LineageEdge).where(
                LineageEdge.relation == "touches", LineageEdge.src_id == "issue_refund"
            )
        )
        assert touches.kind is None and touches.attrs == {"resource_kind": "payments"}
        handoff = s.scalar(
            select(LineageEdge).where(
                LineageEdge.relation == "delegates_to", LineageEdge.src_id == "triage-agent"
            )
        )
        assert handoff.kind == "handoff"
        radius = lineage(s, "triage-agent")
        assert "Customers" not in {n["id"] for n in radius["nodes"]}
        assert "talks_to" not in {link["relation"] for link in radius["links"]}
    m = client.get("/api/projects/repo-a/map", headers=ADMIN).json()
    assert {r["name"]: r["kind"] for r in m["resources"]} == {
        "Orders": "database",
        "Payments": "payments",
    }


def test_risk_on_the_map_becomes_a_registry_impact_that_never_replaces_a_declared_one(client):
    kinds = {"sys-pay": "payments", "sys-db": "database"}
    assert (
        service.impact_for({"name": "issue_refund", "risk": "high", "systemId": "sys-pay"}, kinds)
        == "irreversible"
    )
    assert service.impact_for({"name": "update_seat", "risk": "high"}, kinds) == "high_impact"
    assert service.impact_for({"name": "send_email", "risk": "outside"}, kinds) == "irreversible"
    assert service.impact_for({"name": "get_order", "risk": "read_only"}, kinds) == "read"
    assert (
        service.impact_for({"name": "x", "risk": "read_only", "impact": "write"}, kinds) == "write"
    )

    # A tool someone declared keeps its impact when init maps it again.
    client.post(
        "/api/tools",
        json={"key": "get_order", "name": "get_order", "impact": "high_impact"},
        headers=ADMIN,
    )
    _repo_a(client, _key(client))
    tools = {t["key"]: t["impact"] for t in client.get("/api/tools", headers=ADMIN).json()["tools"]}
    assert tools["get_order"] == "high_impact"
    assert tools["issue_refund"] == "irreversible"
