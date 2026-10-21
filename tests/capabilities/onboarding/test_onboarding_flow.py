"""Onboarding: map a repo, build the attack suite, grade attacks, and the API that
ties `agentfox init --key` to the dashboard."""

from __future__ import annotations

import json
from collections import defaultdict

from agentfox.capabilities.onboarding import runner, service
from agentfox.capabilities.onboarding.attacks import build_suite, counts
from agentfox.capabilities.onboarding.mapper import classify, map_repository
from tests.conftest import as_user, promote

AGENT_PY = """
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from tools import ALL_TOOLS

SYSTEM_PROMPT = "You are Maya, support for customers of a marketplace."
model = ChatOpenAI(model="gpt-4o-mini")

def build_agent(llm=None, tools=None):
    return create_agent(model=llm or model, tools=tools or ALL_TOOLS, system_prompt=SYSTEM_PROMPT)

agent = build_agent()
"""

TOOLS_PY = '''
from langchain.tools import tool

@tool
def get_order(order_id: str) -> str:
    """Look up an order: item, price and status."""

@tool
def start_return(order_id: str, reason: str) -> str:
    """Create a return request and refund for an order."""

@tool
def escalate_to_human(summary: str) -> str:
    """Hand the conversation to a human teammate, e.g. for payment issues."""

ALL_TOOLS = [get_order, start_return, escalate_to_human]
'''


def _repo(tmp_path):
    (tmp_path / "agent.py").write_text(AGENT_PY)
    (tmp_path / "tools.py").write_text(TOOLS_PY)
    (tmp_path / "chat.py").write_text("from agent import agent\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "shop-agent"\n')
    return tmp_path


def test_maps_agent_model_tools_and_systems(tmp_path):
    mapped = map_repository(_repo(tmp_path))
    s = mapped["structure"]
    assert [a["name"] for a in s["agents"]] == ["shop-agent"]
    assert s["agents"][0]["model"] == "gpt-4o-mini"
    risks = {t["name"]: t["risk"] for t in s["tools"]}
    assert risks == {
        "get_order": "read_only",
        "start_return": "high",
        "escalate_to_human": "outside",
    }
    assert {x["name"] for x in s["systems"]} == {"Orders", "Payments", "Helpdesk"}
    assert s["sources"][0]["label"] == "Customers"
    # Discovery's framework names; `agent = build_agent()` is the live object to run.
    assert mapped["agents"] == [
        {
            "agentId": "ag-1",
            "module": "agent",
            "attr": "agent",
            "kind": "object",
            "framework": "LangGraph",
        }
    ]


def test_names_decide_before_docstrings():
    # "escalate ... payment issues" talks to people; it doesn't move money.
    assert classify("escalate_to_human", "Use for payment issues")[0] == "outside"
    assert (
        classify("check_return_eligibility", "Can it be returned for a refund?")[0] == "read_only"
    )
    assert classify("delete_user", "")[0] == "high"


def test_suite_is_140_split_like_the_brief(tmp_path):
    suite = build_suite(map_repository(_repo(tmp_path))["structure"])
    assert len(suite) == 140
    assert counts(suite) == {
        "unsafe_tool_use": 40,
        "prompt_injection": 40,
        "data_leak": 30,
        "jailbreak": 30,
    }
    assert all(a.forbidden == ["start_return"] for a in suite if a.type == "unsafe_tool_use")


class _Msg:
    def __init__(self, content):
        self.content = content


class _GullibleAgent:
    """Does whatever the message says: refunds when asked, repeats what tools return."""

    def __init__(self, tools):
        self.tools = tools

    def invoke(self, payload, config=None):
        text = payload["messages"][0]["content"]
        record = json.loads(self.tools["get_order"](order_id="BZ-2207"))
        if "refund" in text.lower() or "return" in text.lower():
            self.tools["start_return"](order_id="BZ-2207", reason="asked")
        return {"messages": [_Msg(f"Sure! The buyer is {record.get('customer_email', '')}.")]}


def _run(structure, guards, kinds):
    tools = {
        t["name"]: runner._dispatch(t["name"], lambda **kw: "real") for t in structure["tools"]
    }
    suite = [a for a in build_suite(structure) if a.id in kinds]
    out = []
    runner.run_suite(
        _GullibleAgent(tools),
        suite,
        structure,
        guards,
        out.append,
        agent_name="shop-agent",
        concurrency=2,
    )
    return {r["id"]: r for r in out}


def test_before_attacks_get_through_and_guardrails_stop_them(tmp_path):
    structure = map_repository(_repo(tmp_path))["structure"]
    ids = {"unsafe_tool_use-001", "data_leak-001"}
    before = _run(structure, [], ids)
    assert before["unsafe_tool_use-001"]["gotThrough"]
    assert "start_return" in before["unsafe_tool_use-001"]["toolCall"]
    assert before["data_leak-001"]["gotThrough"]

    after = _run(structure, ["refund-approval", "prompt-attacks", "hide-personal-data"], ids)
    held = after["unsafe_tool_use-001"]
    assert not held["gotThrough"]
    assert held["calls"][-1] == {
        "tool": "start_return",
        "executed": False,
        "held": "Money-moving actions need a person to approve them.",
    }
    assert not after["data_leak-001"]["gotThrough"]  # the email was hidden from the reply


def test_real_tools_run_outside_a_test():
    call = runner._dispatch("start_return", lambda **kw: "really refunded")
    assert call(order_id="x") == "really refunded"


def test_run_aggregates_and_explains_a_broken_model():
    structure = {
        "tools": [{"name": "start_return", "risk": "high"}],
        "agents": [{"id": "a", "name": "x"}],
        "systems": [],
    }
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    run = service.new_run("before", structure, now)
    run["startedAt"] = now.isoformat()
    ok = {
        "id": "unsafe_tool_use-001",
        "type": "unsafe_tool_use",
        "gotThrough": True,
        "sentence": "x refunded",
        "severity": 3,
    }
    run = service.add_results(run, [ok, ok], done=False, error=None, now=now)
    shown = service.to_test_run(run, runner_connected=True, now=now)
    assert (
        shown["gotThrough"] == 1
        and shown["byType"][0]["done"] == 1
        and shown["status"] == "running"
    )

    broken = service.new_run("before", structure, now)
    errs = [
        {"id": f"jailbreak-{i:03d}", "type": "jailbreak", "error": "429 insufficient_quota"}
        for i in range(5)
    ]
    broken = service.add_results(broken, errs, done=True, error=None, now=now)
    assert broken["status"] == "failed"
    assert "out of credits" in broken["error"]


def test_api_end_to_end(client):
    me = as_user("admin@example.com")
    key = client.get("/api/onboarding/key", headers=me).json()["value"]
    assert key.startswith("afi_")
    # Shown in full once; after that only its prefix.
    again = client.get("/api/onboarding/key", headers=me).json()
    assert again["value"] is None and key.startswith(again["prefix"])

    assert (
        client.post(
            "/api/onboarding/runner/poll", headers={"Authorization": "Bearer afi_wrong"}
        ).status_code
        == 401
    )
    runner_auth = {"Authorization": f"Bearer {key}"}
    structure = {
        "sources": [{"id": "src-1", "label": "Customers"}],
        "agents": [
            {"id": "ag-1", "name": "shop-agent", "model": "gpt-4o-mini", "sourceIds": ["src-1"]}
        ],
        "tools": [
            {
                "id": "t1",
                "name": "start_return",
                "agentId": "ag-1",
                "risk": "high",
                "whatItDoes": "Refunds.",
                "systemId": "sys-payments",
            }
        ],
        "systems": [{"id": "sys-payments", "name": "Payments", "kind": "payments"}],
    }
    assert (
        client.post(
            "/api/onboarding/runner/connect", json={"structure": structure}, headers=runner_auth
        ).status_code
        == 200
    )
    live = client.get("/api/onboarding/structure", headers=me).json()
    assert (
        live["connected"]
        and live["runnerConnected"]
        and live["structure"]["agents"][0]["name"] == "shop-agent"
    )

    run = client.post("/api/onboarding/tests", json={"phase": "before"}, headers=me).json()
    assert run["total"] == 140 and run["status"] == "running"
    job = client.post("/api/onboarding/runner/poll", headers=runner_auth).json()["job"]
    assert job["runId"] == run["id"] and job["guardrails"] == []

    result = {
        "id": "unsafe_tool_use-001",
        "type": "unsafe_tool_use",
        "gotThrough": True,
        "sentence": "shop-agent refunded",
        "attack": "a",
        "toolCall": "start_return({})",
        "owasp": [],
        "severity": 3,
    }
    client.post(
        f"/api/onboarding/runner/runs/{run['id']}/results",
        json={"results": [result], "done": True},
        headers=runner_auth,
    )
    done = client.get(f"/api/onboarding/tests/{run['id']}", headers=me).json()
    assert (
        done["status"] == "done"
        and done["gotThrough"] == 1
        and done["worst"]["toolCall"] == "start_return({})"
    )

    guards = client.get("/api/onboarding/guardrails", headers=me).json()
    assert [g["id"] for g in guards] == ["refund-approval", "prompt-attacks", "hide-personal-data"]
    client.post(
        "/api/onboarding/guardrails", json=[{"id": "refund-approval", "enabled": False}], headers=me
    )
    after = client.post("/api/onboarding/tests", json={"phase": "after"}, headers=me).json()
    job = client.post("/api/onboarding/runner/poll", headers=runner_auth).json()["job"]
    assert job["runId"] == after["id"] and job["guardrails"] == [
        "prompt-attacks",
        "hide-personal-data",
    ]

    client.patch(
        "/api/onboarding/state",
        json={"currentStep": "test", "completedSteps": ["connect"], "skipped": True},
        headers=me,
    )
    assert client.get("/api/onboarding/state", headers=me).json()["currentStep"] == "test"
    client.delete("/api/onboarding/state", headers=me)
    assert client.get("/api/onboarding/state", headers=me).json()["currentStep"] == "connect"
    assert (
        client.post("/api/onboarding/runner/poll", headers=runner_auth).json()["needStructure"]
        is True
    )


def test_user_can_add_to_the_map_and_tests_use_it(client):
    me = as_user("admin@example.com")
    structure = {
        "sources": [{"id": "src-1", "label": "Customers"}],
        "agents": [{"id": "ag-1", "name": "shop-agent", "model": "gpt-4o", "sourceIds": ["src-1"]}],
        "tools": [
            {
                "id": "t-user-1",
                "name": "payouts.send",
                "agentId": "ag-1",
                "risk": "high",
                "whatItDoes": "Sends a payout.",
                "systemId": "sys-bank",
                "addedByUser": True,
            }
        ],
        "systems": [{"id": "sys-bank", "name": "Bank", "kind": "payments"}],
    }
    saved = client.put("/api/onboarding/structure", json={"structure": structure}, headers=me)
    assert saved.status_code == 200
    live = client.get("/api/onboarding/structure", headers=me).json()["structure"]
    assert live["tools"][0]["addedByUser"] is True
    guards = client.get("/api/onboarding/guardrails", headers=me).json()
    assert guards[0]["id"] == "refund-approval" and "payouts.send" in guards[0]["appliesTo"]
    assert (
        client.post("/api/onboarding/tests", json={"phase": "before"}, headers=me).json()["total"]
        == 140
    )


def test_connect_registers_agents_and_tools_under_projects(client):
    me = as_user("admin@example.com")
    key = client.get("/api/onboarding/key", headers=me).json()["value"]
    structure = {
        "sources": [{"id": "src-1", "label": "Customers"}],
        "agents": [
            {"id": "ag-1", "name": "Shop Agent", "model": "gpt-4o-mini", "sourceIds": ["src-1"]}
        ],
        "tools": [
            {
                "id": "t1",
                "name": "start_return",
                "agentId": "ag-1",
                "risk": "high",
                "whatItDoes": "Refunds.",
                "systemId": "sys-pay",
            },
            {
                "id": "t2",
                "name": "get_order",
                "agentId": "ag-1",
                "risk": "read_only",
                "whatItDoes": "Reads.",
                "systemId": "sys-db",
            },
        ],
        "systems": [
            {"id": "sys-pay", "name": "Payments", "kind": "payments"},
            {"id": "sys-db", "name": "Orders", "kind": "database"},
        ],
    }
    ok = client.post(
        "/api/onboarding/runner/connect",
        json={"structure": structure},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert ok.status_code == 200
    slug = client.get("/api/onboarding/structure", headers=me).json()["structure"]["agents"][0][
        "slug"
    ]
    assert slug == "shop-agent"
    agent = client.get(f"/api/agents/{slug}", headers=me)
    assert agent.status_code == 200
    tools = {t["key"]: t["impact"] for t in client.get("/api/tools", headers=me).json()["tools"]}
    assert tools["start_return"] == "irreversible" and tools["get_order"] == "read"


def test_connect_groups_agents_into_a_project_with_its_map(client):
    """One init run is one project; its map runs input -> agent -> tools -> resources."""
    me = as_user("admin@example.com")
    key = client.get("/api/onboarding/key", headers=me).json()["value"]
    structure = {
        "sources": [{"id": "src-1", "label": "Customers", "detail": "chat"}],
        "agents": [
            {"id": "ag-1", "name": "Shop Agent", "model": "gpt-4o-mini", "sourceIds": ["src-1"]},
            {"id": "ag-2", "name": "Refund Agent", "model": "gpt-4o", "sourceIds": []},
        ],
        "tools": [
            {"id": "t1", "name": "get_order", "agentId": "ag-1", "systemId": "sys-db"},
            {"id": "t2", "name": "start_return", "agentId": "ag-2", "systemId": "sys-pay"},
        ],
        "systems": [
            {"id": "sys-db", "name": "Orders", "kind": "database"},
            {"id": "sys-pay", "name": "Payments", "kind": "payments"},
        ],
    }
    client.post(
        "/api/onboarding/runner/connect",
        json={"structure": structure, "project": "bazaar"},
        headers={"Authorization": f"Bearer {key}"},
    )

    # A project is a system: two agents that hand nothing to each other are two, both
    # mapped from the `bazaar` repository, which still names them both.
    projects = {
        p["project"]: (p["agents"], p["repos"])
        for p in client.get("/api/projects", headers=me).json()["projects"]
    }
    assert projects["shop-agent"] == (1, ["bazaar"])
    assert projects["refund-agent"] == (1, ["bazaar"])

    m = client.get("/api/projects/bazaar/map", headers=me).json()
    assert sorted(a["slug"] for a in m["agents"]) == ["refund-agent", "shop-agent"]
    shop = next(a for a in m["agents"] if a["slug"] == "shop-agent")
    assert shop["models"] == ["gpt-4o-mini"] and shop["tools"] == ["get_order"]
    assert m["inputs"] == [{"label": "Customers", "detail": "chat", "agents": ["shop-agent"]}]
    touched = {r["name"]: (r["kind"], r["tools"]) for r in m["resources"]}
    assert touched == {
        "Orders": ("database", ["get_order"]),
        "Payments": ("payments", ["start_return"]),
    }
    assert client.get("/api/agents/shop-agent", headers=me).json()["project"] == "bazaar"


def test_an_agent_without_a_project_is_its_own_never_a_pile_of_all(client):
    """There is no catch-all project: each agent outside a mapped repo stands alone."""
    me = as_user("admin@example.com")
    for slug in ("solo-a", "solo-b"):
        client.post("/api/agents", json={"slug": slug, "name": slug}, headers=me)
    projects = {
        p["project"]: p["agents"]
        for p in client.get("/api/projects", headers=me).json()["projects"]
    }
    assert projects["solo-a"] == 1 and projects["solo-b"] == 1
    assert "default" not in projects
    m = client.get("/api/projects/solo-a/map", headers=me).json()
    assert [a["slug"] for a in m["agents"]] == ["solo-a"]


def _connect_watch(client):
    me = as_user("admin@example.com")
    key = client.get("/api/onboarding/key", headers=me).json()["value"]
    structure = {
        "sources": [],
        "agents": [{"id": "ag-1", "name": "Watch Agent", "model": "gpt-4o-mini", "sourceIds": []}],
        "tools": [{"id": "t1", "name": "get_order", "agentId": "ag-1", "systemId": "s"}],
        "systems": [{"id": "s", "name": "Orders", "kind": "database"}],
    }
    runner = {"Authorization": f"Bearer {key}"}
    send = lambda: client.post(  # noqa: E731
        "/api/onboarding/runner/connect",
        json={"structure": structure, "project": "watch"},
        headers=runner,
    )
    assert send().status_code == 200
    return me, runner, send


def _finish(client, runner, run_id):
    r = client.post(
        f"/api/onboarding/runner/runs/{run_id}/results",
        json={
            "results": [{"id": "a1", "type": "prompt_injection", "gotThrough": True}],
            "done": True,
        },
        headers=runner,
    )
    assert r.status_code == 200


def test_connecting_tests_the_project_as_it_is_with_no_guardrails(client):
    """A new project is proposed with no guardrails and no tool grants (a person adds
    the agents and grants their tools), and is tested at once."""
    me, runner, send = _connect_watch(client)

    m = client.get("/api/agents/watch-agent/map", headers=me).json()
    assert not [r for s in m["stages"] for r in s["rules"] if r["id"].startswith("basic.")]
    assert {t["key"]: t["permission"] for t in m["tools"]}["get_order"] == "not_granted"

    tests = client.get("/api/onboarding/projects/watch/tests", headers=me).json()
    assert tests["first"]["status"] == "running"  # queued for the runner
    assert tests["withBasic"] is None and tests["basicOn"] is False
    assert tests["connectedProject"] == "watch"

    # The runner picks it up with no guardrails applied.
    job = client.post("/api/onboarding/runner/poll", headers=runner).json()["job"]
    assert job["runId"] == tests["first"]["id"] and job["guardrails"] == []

    # Connecting again doesn't queue a second first test.
    _finish(client, runner, job["runId"])
    assert send().status_code == 200
    assert client.post("/api/onboarding/runner/poll", headers=runner).json()["job"] is None


def test_basic_guardrails_cover_what_users_send_and_get_back_then_the_test_runs_again(client):
    me, runner, _send = _connect_watch(client)
    first = client.post("/api/onboarding/runner/poll", headers=runner).json()["job"]
    _finish(client, runner, first["runId"])

    r = client.post("/api/onboarding/projects/watch/basic-guardrails", headers=me)
    assert r.status_code == 200 and r.json()["added"] == ["watch-agent"]
    # Once only.
    again = client.post("/api/onboarding/projects/watch/basic-guardrails", headers=me)
    assert again.json()["added"] == []

    m = client.get("/api/agents/watch-agent/map", headers=me).json()
    on = defaultdict(set)
    modes = set()
    for stage in m["stages"]:
        for rule in stage["rules"]:
            if rule["id"].startswith("basic."):
                on[stage["key"]].add(rule["id"])
                modes.add(rule["mode"])
    # What users send and what goes back to them; nothing on tools. Watching until
    # they are simulated and promoted, like any policy.
    assert on["input"] == {"basic.input.attacks"}
    assert on["output"] == {"basic.reply.personal_data", "basic.reply.secrets"}
    assert not on["tool_call"] and not on["tool_result"]
    assert modes == {"observe"}

    tests = client.get("/api/onboarding/projects/watch/tests", headers=me).json()
    assert tests["basicOn"] is True and tests["first"]["status"] == "done"
    assert tests["basicEnforcing"] is False
    promote(client, service.basic_key("watch-agent"))
    tests = client.get("/api/onboarding/projects/watch/tests", headers=me).json()
    assert tests["basicEnforcing"] is True

    started = client.post("/api/onboarding/projects/watch/tests", headers=me)
    assert started.status_code == 200 and started.json()["phase"] == "after"
    # One at a time.
    assert client.post("/api/onboarding/projects/watch/tests", headers=me).status_code == 409
    job = client.post("/api/onboarding/runner/poll", headers=runner).json()["job"]
    assert job["guardrails"] == service.BASIC_TEST_GUARDS
    _finish(client, runner, job["runId"])
    tests = client.get("/api/onboarding/projects/watch/tests", headers=me).json()
    assert tests["withBasic"]["status"] == "done"
    # The first test stays as it was, for the before/after.
    assert tests["first"]["id"] == first["runId"]


def test_a_project_chooses_its_attack_sets_from_the_library(client):
    me, runner, _send = _connect_watch(client)
    first = client.post("/api/onboarding/runner/poll", headers=runner).json()["job"]
    # A new project runs the four default sets.
    assert first["sets"] == ["unsafe_tool_use", "prompt_injection", "data_leak", "jailbreak"]
    _finish(client, runner, first["runId"])

    tests = client.get("/api/onboarding/projects/watch/tests", headers=me).json()
    library = {x["key"]: x for x in tests["library"]}
    assert {"encoding", "multilingual", "authority", "bulk_action"} <= set(library)
    assert all(x["attacks"] > 0 for x in library.values())

    url = "/api/onboarding/projects/watch/tests/sets"
    assert client.put(url, json={"sets": []}, headers=me).status_code == 400
    r = client.put(url, json={"sets": ["encoding", "jailbreak", "nonsense"]}, headers=me)
    assert r.json()["sets"] == ["jailbreak", "encoding"]

    started = client.post("/api/onboarding/projects/watch/tests", headers=me).json()
    assert [t["type"] for t in started["byType"]] == ["jailbreak", "encoding"]
    assert started["total"] == library["jailbreak"]["attacks"] + library["encoding"]["attacks"]
    job = client.post("/api/onboarding/runner/poll", headers=runner).json()["job"]
    assert job["sets"] == ["jailbreak", "encoding"]


def test_library_sets_are_graded_like_the_rest():
    from agentfox.capabilities.onboarding.attacks import LIBRARY, build_suite

    structure = {
        "tools": [
            {"name": "get_order", "risk": "read_only"},
            {"name": "issue_refund", "risk": "high"},
        ]
    }
    suite = build_suite(structure, list(LIBRARY))
    for kind in ("encoding", "multilingual", "authority", "bulk_action"):
        mine = [a for a in suite if a.type == kind]
        assert mine, kind
        # Each one is graded mechanically: the action tool must not run.
        assert all(a.forbidden == ["issue_refund"] for a in mine), kind
        assert len({a.id for a in mine}) == len(mine)


def test_only_the_connected_project_can_be_tested(client):
    me, _runner, _send = _connect_watch(client)
    r = client.post("/api/onboarding/projects/elsewhere/tests", headers=me)
    assert r.status_code == 409 and "agentfox init" in r.json()["detail"]


# --- the setup key ---------------------------------------------------------------


def test_the_setup_key_is_made_on_first_ask_and_the_same_after(client):
    me = as_user("admin@example.com")
    first = client.get("/api/onboarding/key", headers=me)
    assert first.status_code == 200
    key = first.json()["value"]
    assert key.startswith("afi_") and len(key) > 30
    assert first.json()["createdNow"] is True

    again = client.get("/api/onboarding/key", headers=me).json()
    assert again["value"] is None and again["createdNow"] is False
    assert key.startswith(again["prefix"])


def test_every_user_gets_their_own_setup_key(client):
    a = client.get("/api/onboarding/key", headers=as_user("admin@example.com")).json()["value"]
    b = client.get("/api/onboarding/key", headers=as_user("priya@example.com")).json()["value"]
    assert a != b


def test_starting_setup_over_keeps_the_key(client):
    """A running `agentfox init` holds the key; resetting setup must not strand it."""
    me = as_user("admin@example.com")
    first = client.get("/api/onboarding/key", headers=me).json()
    assert client.delete("/api/onboarding/state", headers=me).status_code == 200
    again = client.get("/api/onboarding/key", headers=me).json()
    assert again["createdNow"] is False and again["prefix"] == first["prefix"]
    r = client.post(
        "/api/onboarding/runner/poll", headers={"Authorization": f"Bearer {first['value']}"}
    )
    assert r.status_code == 200


def test_the_key_is_what_lets_init_report_in(client):
    me = as_user("admin@example.com")
    key = client.get("/api/onboarding/key", headers=me).json()["value"]
    structure = {
        "sources": [],
        "agents": [{"id": "a", "name": "Key Agent", "model": "gpt-4o"}],
        "tools": [],
        "systems": [],
    }

    ok = client.post(
        "/api/onboarding/runner/connect",
        json={"structure": structure},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert ok.status_code == 200
    # It landed in this user's setup, with the time it arrived.
    live = client.get("/api/onboarding/structure", headers=me).json()
    assert live["connected"] is True and live["connectedAt"]

    for bad in ("afi_not-a-real-key", "nom_api_wrong-kind-of-token", ""):
        refused = client.post(
            "/api/onboarding/runner/connect",
            json={"structure": structure},
            headers={"Authorization": f"Bearer {bad}"},
        )
        assert refused.status_code == 401, bad


# --- disconnecting a project -------------------------------------------------------


def test_removing_a_project_lets_it_connect_again_as_new(client):
    """Remove, then run init again: the same repo comes back as a brand-new project."""
    me = as_user("admin@example.com")
    key = client.get("/api/onboarding/key", headers=me).json()["value"]
    structure = {
        "sources": [{"id": "src-1", "label": "Customers", "detail": "chat"}],
        "agents": [
            {
                "id": "ag-1",
                "name": "Shop Bot",
                "model": "gpt-4o",
                "sourceIds": ["src-1"],
                "handsOffTo": ["ag-2"],
            },
            {"id": "ag-2", "name": "Refund Bot", "model": "gpt-4o", "sourceIds": []},
        ],
        "tools": [
            {"id": "t1", "name": "shop_lookup", "agentId": "ag-1", "systemId": "s"},
            {"id": "t2", "name": "shop_refund", "agentId": "ag-2", "systemId": "s"},
        ],
        "systems": [{"id": "s", "name": "Orders", "kind": "database"}],
    }

    def connect():
        r = client.post(
            "/api/onboarding/runner/connect",
            json={"structure": structure, "project": "shop"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert r.status_code == 200
        return client.get("/api/onboarding/structure", headers=me).json()["structure"]["agents"]

    connect()
    assert client.get("/api/onboarding/projects/shop/tests", headers=me).json()["first"]
    client.post("/api/onboarding/projects/shop/basic-guardrails", headers=me)
    # The agents are live.
    before = client.get("/api/projects/shop/map", headers=me).json()
    assert before["agents"][1]["hands_off_to"] == ["refund-bot"] or before["agents"][0][
        "hands_off_to"
    ] == ["refund-bot"]

    removed = client.delete("/api/projects/shop", headers=me)
    assert removed.status_code == 200
    assert sorted(removed.json()["removed"]) == ["refund-bot", "shop-bot"]

    # Gone from the dashboard, and the setup card no longer remembers it.
    assert not {"shop", "shop-bot", "refund-bot"} & {
        p["project"] for p in client.get("/api/projects", headers=me).json()["projects"]
    }
    assert client.get("/api/onboarding/structure", headers=me).json()["connected"] is False
    m = client.get("/api/agents/shop-bot/map", headers=me).json()
    assert not [r for s in m["stages"] for r in s["rules"] if r["id"].startswith("basic.")]
    assert {t["permission"] for t in m["tools"]} <= {"not_granted"}
    assert client.get("/api/onboarding/projects/shop/tests", headers=me).json()["first"] is None
    assert client.delete("/api/projects/shop", headers=me).status_code == 404

    # Connect again: treated like a new project.
    connect()
    # One system: Shop Bot hands work to Refund Bot.
    assert {
        p["project"]: (p["agents"], p["repos"])
        for p in client.get("/api/projects", headers=me).json()["projects"]
    }["shop-bot"] == (2, ["shop"])
    m = client.get("/api/agents/shop-bot/map", headers=me).json()
    assert not [r for s in m["stages"] for r in s["rules"] if r["id"].startswith("basic.")]
    # Tested afresh, and proposed again: nothing granted until a person does.
    assert client.get("/api/onboarding/projects/shop/tests", headers=me).json()["first"]
    assert client.get("/api/agents/shop-bot", headers=me).json()["status"] == "draft"
    assert {t["key"]: t["permission"] for t in m["tools"]}["shop_lookup"] == "not_granted"
