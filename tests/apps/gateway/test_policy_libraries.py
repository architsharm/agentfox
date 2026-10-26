"""Libraries on the Policies page: applied per project agent, watching first, and
blocking only through the same gate as any policy (a production-policy role and a
recorded simulation of the exact rules)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.capabilities.onboarding import service
from agentfox.core.db import session_scope
from agentfox.core.tenancy import system_scope, tenant
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
DEV = as_user("priya@example.com")  # developer: may change policy, not production policy
SLUG = "watch-agent"
#: `/api/projects` keys a project by its root agent's slug.
PROJECT = SLUG
COPY = f"agent.{SLUG}.baseline"


def _connect(client, name="Watch Agent", repo="watch"):
    """`agentfox init --key` reporting one agent from ``repo``: it arrives as a draft."""
    # The setup key's value is shown when it is made; keep it for the test's next init.
    if not hasattr(client, "setup_key"):
        client.setup_key = client.get("/api/onboarding/key", headers=ADMIN).json()["value"]
    key = client.setup_key
    structure = {
        "sources": [],
        "agents": [{"id": "ag-1", "name": name, "model": "gpt-4o-mini", "sourceIds": []}],
        "tools": [{"id": "t1", "name": f"{repo}_lookup", "agentId": "ag-1", "systemId": "s"}],
        "systems": [{"id": "s", "name": "Orders", "kind": "database"}],
    }
    r = client.post(
        "/api/onboarding/runner/connect",
        json={"structure": structure, "project": repo},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text


def _traffic(slug=SLUG):
    """An attack that went through and a reply with personal data in it."""
    from agentfox.core.models import Agent, Decision

    with session_scope() as s, system_scope("test"):
        agent = s.scalar(select(Agent).where(Agent.slug == slug))
        s.add(
            Decision(
                agent_id=agent.id,
                surface="input",
                verdict="allow",
                taint_summary_json={
                    "detections": [{"entity_type": "INJECTION.DIRECT", "score": 0.95}]
                },
            )
        )
        s.add(
            Decision(
                agent_id=agent.id,
                surface="output",
                verdict="allow",
                taint_summary_json={"detections": [{"entity_type": "PII.EMAIL", "score": 0.99}]},
            )
        )


def _mode(key):
    from agentfox.platform.policy.publish import current_mode

    with session_scope() as s, system_scope("test"):
        return current_mode(s, key)


def _lib(client, action, pack="baseline", headers=ADMIN, **body):
    body.setdefault("agents", [SLUG])
    body.setdefault("project", PROJECT)
    return client.post(f"/api/policies/libraries/{pack}/{action}", json=body, headers=headers)


# --- A: basic guardrails from the Policies page -------------------------------------


def test_basic_guardrails_from_the_library_watch_until_simulated_then_block(client):
    _connect(client)
    r = _lib(client, "apply", pack="basic")
    assert r.status_code == 200, r.text
    assert r.json()["added"] == [SLUG] and r.json()["mode"] == "observe"
    assert _mode(service.basic_key(SLUG)) == "observe"

    # The same gate as any policy: a simulation of these rules, then blocking.
    assert _lib(client, "mode", pack="basic", mode="enforce").status_code == 409
    assert _lib(client, "simulate", pack="basic").status_code == 200
    assert _lib(client, "mode", pack="basic", mode="enforce").status_code == 200
    assert _mode(service.basic_key(SLUG)) == "enforce"
    status = client.get(
        f"/api/policies/libraries/status?agents={SLUG}&project={PROJECT}", headers=ADMIN
    ).json()
    assert status["basic"]["agents"] == [SLUG] and status["basic"]["blocking"] is True


def test_a_developer_applying_basic_guardrails_gets_them_watching(client):
    _connect(client)
    r = _lib(client, "apply", pack="basic", headers=DEV)
    assert r.status_code == 200 and r.json()["mode"] == "observe"


# --- B: blocking with a library is gated like any policy ----------------------------


def test_blocking_with_a_library_needs_a_production_role_and_a_simulation(client):
    _connect(client)
    _traffic()
    assert _lib(client, "apply").json() == {"added": [SLUG], "updated": []}
    assert _mode(COPY) == "observe"

    assert _lib(client, "mode", headers=DEV, mode="enforce").status_code == 403
    refused = _lib(client, "mode", mode="enforce")
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("simulate first:")
    assert _mode(COPY) == "observe"  # nothing switched

    sim = _lib(client, "simulate")
    assert sim.status_code == 200, sim.text
    out = sim.json()
    [agent] = out["agents"]
    assert agent["agent"] == SLUG and agent["replayed"] == 2
    assert agent["blocked"] == 1 and agent["hidden"] == 1 and agent["held"] == 0
    assert out["blocked"] == 1 and agent["policies"][0]["simulation_id"]

    assert _lib(client, "mode", mode="enforce").json() == {"changed": [SLUG], "mode": "enforce"}
    assert _mode(COPY) == "enforce"
    # Back to watching: the same roles as `/api/policies/{key}/mode`, either way.
    assert _lib(client, "mode", headers=DEV, mode="observe").status_code == 403
    assert _lib(client, "mode", mode="observe").status_code == 200
    assert _mode(COPY) == "observe"


def test_a_changed_copy_needs_simulating_again(client):
    """A simulation is of exact rules: once the copy changes, blocking needs a new one."""
    from agentfox.platform.policy.model import Rule
    from agentfox.platform.policy.publish import publish_in_current_mode
    from agentfox.platform.policy.store import load_version_document

    _connect(client)
    _lib(client, "apply")
    _lib(client, "simulate")
    with session_scope() as s, system_scope("test"):
        from agentfox.capabilities.protection.libraries import _live

        doc = load_version_document(_live(s, COPY)[2])
        extra = Rule(id="mine.extra", effect="block", when={"surface": ["input"]}, reason="x")
        publish_in_current_mode(
            s, doc.model_copy(update={"rules": [*doc.rules, extra]}), actor="t", notes="edit"
        )
    assert _lib(client, "mode", mode="enforce").status_code == 409


# --- C: copies say where they came from, and catch up with the library ---------------


@pytest.fixture
def shipped_fix(monkeypatch):
    """Pretend a fix shipped to the baseline library: one rule's threshold changed."""
    from agentfox.capabilities.protection import libraries

    real = libraries._library_docs

    def apply():
        def fixed(pack_id):
            found = real(pack_id)
            if pack_id != "baseline" or found is None:
                return found
            title, docs = found
            doc = docs[0]
            rules = [
                r.model_copy(update={"description": "fixed"}) if i == 0 else r
                for i, r in enumerate(doc.rules)
            ]
            return title, [doc.model_copy(update={"rules": rules}), *docs[1:]]

        monkeypatch.setattr(libraries, "_library_docs", fixed)

    return apply


def test_a_copy_records_its_source_and_is_updated_when_the_library_changes(client, shipped_fix):
    from agentfox.core.models import Policy, PolicyVersion

    _connect(client)
    _lib(client, "apply")
    with session_scope() as s, system_scope("test"):
        policy = s.scalar(select(Policy).where(Policy.key == COPY))
        notes = s.scalars(select(PolicyVersion.notes).where(PolicyVersion.policy_id == policy.id))
        assert any("[from baseline baseline " in n for n in notes)

    def status():
        return client.get(f"/api/policies/libraries/status?agents={SLUG}", headers=ADMIN).json()[
            "baseline"
        ]

    assert status()["outdated"] is False and status()["outdatedAgents"] == []
    # Blocking, then a fix ships.
    _lib(client, "simulate")
    _lib(client, "mode", mode="enforce")
    shipped_fix()
    assert status()["outdated"] is True and status()["outdatedAgents"] == [SLUG]

    again = _lib(client, "apply")
    assert again.json() == {"added": [], "updated": [SLUG]}
    assert status()["outdated"] is False
    # Updated in the mode it was in (the new version simulated on the way in).
    assert _mode(COPY) == "enforce" and status()["blocking"] is True
    assert _lib(client, "apply").json() == {"added": [], "updated": []}


def test_a_copy_edited_by_hand_is_not_outdated_until_the_library_changes(client):
    from agentfox.platform.policy.model import Rule
    from agentfox.platform.policy.publish import publish_in_current_mode
    from agentfox.platform.policy.store import load_version_document

    _connect(client)
    _lib(client, "apply")
    with session_scope() as s, system_scope("test"):
        from agentfox.capabilities.protection.libraries import _live

        doc = load_version_document(_live(s, COPY)[2])
        extra = Rule(id="mine.extra", effect="block", when={"surface": ["input"]}, reason="x")
        publish_in_current_mode(
            s, doc.model_copy(update={"rules": [*doc.rules, extra]}), actor="t", notes="edit"
        )
    st = client.get(f"/api/policies/libraries/status?agents={SLUG}", headers=ADMIN).json()
    assert st["baseline"]["outdated"] is False


# --- D: disconnecting keeps library copies restorable --------------------------------


def test_disconnect_snapshots_library_copies_and_restore_keeps_the_gate(client):
    from agentfox.core.models import Agent

    _connect(client)
    _lib(client, "apply")
    _lib(client, "simulate")
    _lib(client, "mode", mode="enforce")

    assert client.delete(f"/api/projects/{PROJECT}", headers=ADMIN).status_code == 200
    with session_scope() as s, system_scope("test"):
        snap = s.scalar(select(Agent).where(Agent.slug == SLUG)).guardrails_snapshot
    assert snap[COPY]["mode"] == "enforce" and snap[COPY]["version"]
    assert _mode(COPY) == "observe"

    _connect(client)
    # A developer gets it back watching: blocking again needs a production role.
    r = client.post(f"/api/agents/{SLUG}/restore-guardrails", headers=DEV)
    assert r.status_code == 200
    assert r.json()["restored"][COPY] == {
        "version": snap[COPY]["version"],
        "mode": "observe",
        "was": "enforce",
    }
    st = client.get(f"/api/policies/libraries/status?agents={SLUG}", headers=ADMIN).json()
    assert st["baseline"]["agents"] == [SLUG]


def test_restore_by_an_admin_blocks_again_with_the_simulated_version(client):
    _connect(client)
    _lib(client, "apply")
    _lib(client, "simulate")
    _lib(client, "mode", mode="enforce")
    client.delete(f"/api/projects/{PROJECT}", headers=ADMIN)
    _connect(client)
    r = client.post(f"/api/agents/{SLUG}/restore-guardrails", headers=ADMIN)
    assert r.json()["restored"][COPY]["mode"] == "enforce"
    assert _mode(COPY) == "enforce"


# --- E: drafts from `agentfox init --key`, and the project's agents ------------------


def test_a_fresh_projects_draft_agents_take_libraries_and_show_as_drafts(client):
    _connect(client)
    assert client.get(f"/api/agents/{SLUG}", headers=ADMIN).json()["status"] == "draft"
    [project] = [
        p
        for p in client.get("/api/projects", headers=ADMIN).json()["projects"]
        if p["project"] == PROJECT
    ]
    # The Policies page reads the project's agents from its map: the same members.
    m = client.get(f"/api/projects/{PROJECT}/map", headers=ADMIN).json()
    assert [a["slug"] for a in m["agents"]] == project["slugs"] == [SLUG]

    assert _lib(client, "apply").status_code == 200
    applied = client.get("/api/policies/applied", headers=ADMIN).json()
    assert {a["slug"]: a["draft"] for a in applied["agentList"]}[SLUG] is True
    row = next(r for r in applied["rules"] if r["id"] == "injection.direct")
    mine = [a for a in row["agents"] if a["slug"] == SLUG]
    assert mine and mine[0]["draft"] is True
    assert "Baseline runtime guardrails" in row["libraries"]


def test_a_project_spanning_repos_applies_to_every_member(client):
    """A project is a system: its root and every agent it hands work to, from any repo."""
    from agentfox.platform.registry.service import record_edge

    _connect(client)
    _connect(client, name="Billing Agent", repo="billing")
    with session_scope() as s, system_scope("test"):
        record_edge(
            s,
            "agent",
            SLUG,
            "agent",
            "billing-agent",
            "delegates_to",
            declared=True,
            kind="as_tool",
        )
    r = _lib(client, "apply", agents=[])
    assert r.status_code == 200 and sorted(r.json()["added"]) == ["billing-agent", SLUG]


# --- F: tenancy, shipped libraries only, the stated project's agents -----------------


def test_only_a_shipped_library_can_be_named(client):
    _connect(client)
    for pack in ("custom", f"agent.{SLUG}", "no-such-pack", "baseline/../custom"):
        for action, extra in (("apply", {}), ("simulate", {}), ("mode", {"mode": "observe"})):
            r = _lib(client, action, pack=pack, **extra)
            assert r.status_code == 404, (pack, action, r.text)


def test_agents_must_be_of_the_stated_project_and_the_callers_workspace(client):
    from agentfox.core.models import Agent, User

    _connect(client)
    _connect(client, name="Other Agent", repo="elsewhere")
    assert _lib(client, "apply", agents=["other-agent"]).status_code == 400
    assert _lib(client, "apply", project="no-such-project").status_code == 404
    assert _lib(client, "apply", agents=["nobody"], project=None).status_code == 404

    with tenant("org_globex"), session_scope() as s:
        s.add(Agent(slug="globex-bot", name="globex-bot", environment="production"))
        s.add(User(email="admin@globex.example", name="G", role="admin", active=True))
    them = as_user("admin@globex.example")
    # Another workspace's agent is unknown here, and this one's is unknown there.
    assert _lib(client, "apply", agents=["globex-bot"], project=None).status_code == 404
    assert _lib(client, "apply", headers=them, project=None).status_code == 404
    assert _lib(client, "mode", headers=them, project=None, mode="observe").status_code == 404
    theirs = client.get("/api/policies/applied", headers=them).json()
    assert SLUG not in {a["slug"] for a in theirs["agentList"]}
