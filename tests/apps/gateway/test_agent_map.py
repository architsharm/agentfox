"""The guardrail map: one entry per rule as this agent gets it, ready to change in place.

Each rule carries the pack a per-agent change is made against, whether the agent has
its own copy, and the grant behind each tool's permission, so the map can switch a
rule or a permission for this agent without leaving the page.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
ORCH, OTHER = "support-triage", "payments-ops"


def _map(client, slug: str = ORCH) -> dict:
    r = client.get(f"/api/agents/{slug}/map", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def _entries(m: dict, rule_id: str) -> list[dict]:
    rules = [r for s in m["stages"] for r in s["rules"]] + m["everywhere"]
    rules += [r for t in m["tools"] for r in t["rules"]]
    return [r for r in rules if r["id"] == rule_id]


def _scope(client, rule_id: str, body: dict, key: str = "baseline"):
    return client.post(f"/api/policies/{key}/rules/{rule_id}/scope", json=body, headers=ADMIN)


def test_each_rule_says_where_to_change_it(client):
    entries = _entries(_map(client), "pii.outbound_redact")
    assert entries, "the rule is on the map"
    for e in entries:
        assert e["policy"] == "baseline" and e["own"] is False and e["enabled"] is True


def test_an_agent_change_shows_as_its_own_copy(client):
    assert _scope(client, "pii.outbound_redact", {"agents": [ORCH], "effect": "block"}).is_success
    entries = _entries(_map(client), "pii.outbound_redact")
    # One entry per step, not one per copy: the agent's own wins.
    assert {e["effect"] for e in entries} == {"block"}
    e = entries[0]
    assert e["own"] and e["level"] == "agent" and e["policy"] == "baseline"
    assert e["workspace"]["effect"] == "redact"
    assert any(a["effect"] == "redact" for a in e["also"])
    # Other agents keep the workspace rule.
    assert {x["effect"] for x in _entries(_map(client, OTHER), "pii.outbound_redact")} == {"redact"}


def test_a_rule_switched_off_for_the_agent_stays_on_the_map(client):
    saved = client.post(
        "/api/policies/baseline/rules/secrets.block", json={"overridable": True}, headers=ADMIN
    ).json()
    client.post(
        "/api/policies/baseline/mode",
        json={"mode": saved["mode"], "version": saved["version"]},
        headers=ADMIN,
    )
    assert _entries(_map(client), "secrets.block")[0]["overridable"] is True
    assert _scope(client, "secrets.block", {"agents": [ORCH], "enabled": False}).is_success
    entries = _entries(_map(client), "secrets.block")
    assert entries and all(e["own"] and e["enabled"] is False for e in entries)


def test_tools_carry_their_grant(client):
    r = client.post(
        f"/api/agents/{ORCH}/access",
        json={"tool_key": "crm.*", "requires_approval": True},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/agents/{ORCH}/access",
        json={"tool_key": "crm.lookup", "constraints": {}},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    tools = {t["key"]: t for t in _map(client)["tools"]}
    # The tool's own grant wins over a pattern that also covers it.
    lookup = tools["crm.lookup"]
    assert lookup["permission"] == "allowed" and lookup["grant"]["key"] == "crm.lookup"
    assert lookup["grant"]["id"] and lookup["grant"]["max_taint"] == "user"


def test_a_custom_rule_for_another_agent_is_not_on_this_agents_map(client):
    client.post(
        "/api/custom-rules",
        json={
            "key": "only-triage",
            "name": "Only triage",
            "kind": "terms",
            "entries": ["zebra"],
            "agents": ["support-triage"],
        },
    ).raise_for_status()

    def rule_ids(slug):
        body = client.get(f"/api/agents/{slug}/map").json()
        ids = {r["id"] for st in body["stages"] for r in st["rules"]}
        ids |= {r["id"] for r in body["everywhere"]}
        ids |= {r["id"] for t in body["tools"] for r in t["rules"]}
        return ids

    assert "custom.only-triage" in rule_ids("support-triage")
    assert "custom.only-triage" not in rule_ids("payments-ops")


# --- the LLM line is a view: nothing counts twice ------------------------------------

#: One decision per surface the map shows, plus one it doesn't (`tool_call`).
SURFACES = (
    "input",
    "retrieved",
    "memory_write",
    "tool_result",
    "output",
    "reasoning",
    "tool_args",
    "tool_call",
)


def _decisions(slug: str = ORCH, surfaces=SURFACES) -> None:
    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Decision

    with session_scope() as s:
        agent = s.scalar(select(Agent).where(Agent.slug == slug))
        for surface in surfaces:
            s.add(Decision(agent_id=agent.id, surface=surface, verdict="allow"))


def _stage(m: dict, key: str) -> dict:
    return next(s for s in m["stages"] if s["key"] == key)


def test_every_decision_counts_once_across_the_stages(client):
    before = _map(client)["decisions"]
    _decisions()
    m = _map(client)
    assert m["decisions"] == before + len(SURFACES)
    assert sum(s["stats"].get("total", 0) for s in m["stages"]) == m["decisions"]
    # Reasoning is shown on the LLM line only, so it belongs there; nothing goes to input.
    assert _stage(m, "response")["stats"]["total"] == 1
    assert _stage(m, "prompt")["stats"] == {}
    # What crossed the LLM line, as a view overlapping the other stages.
    prompt, response = _stage(m, "prompt"), _stage(m, "response")
    assert prompt["derived"] and response["derived"]
    assert prompt["lineStats"]["total"] == 3  # input, retrieved, tool_result
    assert response["lineStats"]["total"] == 2  # output, reasoning
    assert not _stage(m, "input")["derived"] and "lineStats" not in _stage(m, "input")


def test_writing_memory_is_not_sent_to_the_llm(client):
    m = _map(client)
    assert "memory_write" not in _stage(m, "prompt")["surfaces"]
    assert "memory_write" in _stage(m, "context")["surfaces"]


def test_rules_on_the_llm_line_are_the_same_rules_flagged_as_shared(client):
    m = _map(client)
    response = _stage(m, "response")
    redact = next(r for r in response["rules"] if r["id"] == "pii.outbound_redact")
    assert redact["sharedWith"] == ["output"]
    assert "sharedWith" not in next(
        r for r in _stage(m, "output")["rules"] if r["id"] == "pii.outbound_redact"
    )
    # A rule on reasoning is shown nowhere else: it belongs to the LLM line.
    adopted = next(r for r in response["rules"] if r["id"] == "injection.adopted_in_reasoning")
    assert "sharedWith" not in adopted
    # Every other rule on the LLM line is a copy of one that belongs elsewhere.
    for stage in ("prompt", "response"):
        for r in _stage(m, stage)["rules"]:
            assert "sharedWith" in r or r["surfaces"] == ["reasoning"], (stage, r["id"])
    # A check on the LLM line only because it runs on the user's message says so.
    shared = _stage(m, "prompt")["detectorsSharedWith"]
    assert shared and all(shared.values())


def test_each_rule_lists_the_checks_that_can_fire_it_here(client):
    m = _map(client)
    rules = {r["id"]: r for s in m["stages"] for r in s["rules"]}
    adopted = rules["injection.adopted_in_reasoning"]
    assert adopted["surfaces"] == ["reasoning"] and adopted["finds"] == "INJECTION"
    assert "injection.heuristic" in adopted["checks"]
    every = set(adopted["checks"]) | set(adopted["checksOff"])
    assert "injection.classifier" not in every and "injection.judgment" not in every
    assert "pii.native" in rules["pii.outbound_redact"]["checks"]
    # A rule that isn't about content has none.
    for r in m["everywhere"]:
        assert r["checks"] == [] and r["checksOff"] == []


def test_the_rule_page_gets_its_checks_from_the_backend(client):
    r = client.get(
        "/api/policies/baseline/rules/injection.adopted_in_reasoning/checks",
        params={"agent": ORCH},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["finds"] == "INJECTION" and body["surfaces"] == ["reasoning"]
    keys = {c["key"]: c for c in body["checks"]}
    assert "injection.heuristic" in keys and "injection.classifier" not in keys
    assert keys["injection.heuristic"]["surfaces"] == ["reasoning"]
    assert isinstance(keys["injection.heuristic"]["on"], bool)
    missing = client.get("/api/policies/baseline/rules/no.such.rule/checks", headers=ADMIN)
    assert missing.status_code == 404


def test_models_are_the_agents_own_and_recent(client):
    import datetime as dt

    from agentfox.core.db import session_scope
    from agentfox.core.models import LineageEdge

    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=60)

    def edge(src_type: str, model: str, **kw) -> LineageEdge:
        return LineageEdge(
            src_type=src_type,
            src_id=ORCH,
            dst_type="model",
            dst_id=model,
            relation="uses_model",
            observed_count=3,
            **kw,
        )

    with session_scope() as s:
        s.add_all(
            [
                edge("agent", "gpt-new"),
                edge("agent", "gpt-old", first_observed_at=old, last_observed_at=old),
                edge("agent", "gpt-declared", declared=True, last_observed_at=old),
                edge("tool", "tool-model"),
            ]
        )
    models = _map(client)["agent"]["models"]
    assert "gpt-new" in models and "gpt-declared" in models
    assert "gpt-old" not in models and "tool-model" not in models
