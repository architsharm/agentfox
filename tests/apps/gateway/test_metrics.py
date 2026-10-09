"""The dashboard aggregates count what is in the window, split the way they say."""

from __future__ import annotations

import datetime as dt

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _seed() -> None:
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Decision, Span, Trace

    now = dt.datetime.now(dt.UTC)
    with session_scope() as session:
        agent = Agent(slug="metrics-bot", registered=True, status="active")
        session.add(agent)
        session.flush()
        rows = [
            ("allow", 1, None),
            ("allow", 2, "boom"),
            ("block", 3, None),
            ("escalate", 4, None),
            ("redact", 5, None),
        ]
        for verdict, hours_ago, error in rows:
            t = Trace(
                agent_slug="metrics-bot",
                agent_id=agent.id,
                verdict=verdict,
                model="m-1",
                cost_usd=0.5,
                started_at=now - dt.timedelta(hours=hours_ago),
            )
            session.add(t)
            session.flush()
            if error:
                session.add(
                    Span(trace_id=t.id, kind="tool", name="crm.lookup", status="error", error=error)
                )
            session.add(
                Decision(
                    trace_id=t.id,
                    agent_id=agent.id,
                    surface="tool_call",
                    tool_key="crm.lookup",
                    verdict=verdict,
                    mode="enforce" if verdict == "block" else "observe",
                    latency_ms=float(hours_ago),
                    rules_fired_json=[{"rule_id": "pii.outbound_redact", "effect": "redact"}]
                    if verdict == "redact"
                    else [],
                )
            )
        # Outside the 24h window: counted as the previous period, not this one.
        session.add(
            Trace(
                agent_slug="metrics-bot", verdict="block", started_at=now - dt.timedelta(hours=30)
            )
        )


def test_summary_counts_outcomes_errors_and_previous_period(client):
    _seed()
    body = client.get("/api/metrics/summary?range=24h&agent=metrics-bot", headers=ADMIN).json()
    totals = body["totals"]
    assert totals["requests"] == 5
    assert (totals["allowed"], totals["blocked"], totals["held"], totals["masked"]) == (2, 1, 1, 1)
    assert totals["errors"] == 1
    assert totals["cost_usd"] == 2.5
    assert body["previous"]["requests"] == 1
    assert len(body["buckets"]) == 24
    assert sum(b["blocked"] for b in body["buckets"]) == 1


def test_breakdown_by_tool_counts_decisions(client):
    _seed()
    body = client.get(
        "/api/metrics/breakdown?dim=tool&range=24h&agent=metrics-bot", headers=ADMIN
    ).json()
    assert body["rows"][0]["key"] == "crm.lookup"
    assert body["rows"][0]["requests"] == 5


def test_rules_separate_enforced_from_watched(client):
    _seed()
    body = client.get("/api/metrics/rules?range=24h&agent=metrics-bot", headers=ADMIN).json()
    rule = next(r for r in body["rules"] if r["rule_id"] == "pii.outbound_redact")
    assert rule["fires"] == 1
    assert rule["watched"] == 1 and rule["enforced"] == 0
    assert rule["agents"] == {"metrics-bot": 1}


def test_errors_group_failed_steps(client):
    _seed()
    body = client.get("/api/metrics/errors?range=24h&agent=metrics-bot", headers=ADMIN).json()
    assert body["rows"][0]["name"] == "crm.lookup"
    assert body["rows"][0]["count"] == 1


def test_unknown_range_is_rejected(client):
    assert client.get("/api/metrics/summary?range=1y", headers=ADMIN).status_code == 422


def test_trace_search_filters_by_rule_verdicts_and_errors(client):
    _seed()
    by_rule = client.get("/api/traces?rule=pii.outbound_redact", headers=ADMIN).json()["traces"]
    assert [t["verdict"] for t in by_rule] == ["redact"]
    assert by_rule[0]["rules"] == ["pii.outbound_redact"]
    assert by_rule[0]["tools"] == ["crm.lookup"]

    held_or_blocked = client.get(
        "/api/traces?agent=metrics-bot&verdict=block,escalate", headers=ADMIN
    ).json()
    assert sorted(t["verdict"] for t in held_or_blocked["traces"]) == ["block", "block", "escalate"]

    failed = client.get("/api/traces?agent=metrics-bot&errors=true", headers=ADMIN).json()["traces"]
    assert len(failed) == 1


def test_playground_runs_are_excluded_unless_asked_for(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Trace

    _seed()
    with session_scope() as session:
        session.add(Trace(agent_slug="metrics-bot", verdict="block", environment="playground"))
    body = client.get("/api/metrics/summary?range=24h&agent=metrics-bot", headers=ADMIN).json()
    assert body["totals"]["requests"] == 5
    listed = client.get("/api/traces?agent=metrics-bot", headers=ADMIN).json()["traces"]
    assert all(t["environment"] != "playground" for t in listed)
    played = client.get(
        "/api/traces?agent=metrics-bot&environment=playground", headers=ADMIN
    ).json()["traces"]
    assert len(played) == 1


def test_activity_names_the_smallest_range_with_traffic(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Trace

    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=20)
    with session_scope() as session:
        session.add(Trace(agent_slug="old-bot", verdict="allow", started_at=old))
        session.add(
            Trace(agent_slug="old-bot", verdict="allow", started_at=old, environment="playground")
        )
    out = client.get("/api/metrics/activity?agent=old-bot", headers=ADMIN).json()
    assert out["range"] == "30d" and out["last_request_at"].startswith(old.date().isoformat())
    assert client.get("/api/metrics/activity?agent=nobody", headers=ADMIN).json() == {
        "last_request_at": None,
        "range": "7d",
    }


def test_a_run_with_no_checks_says_so(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Trace

    with session_scope() as session:
        session.add(Trace(agent_slug="otel-bot", verdict="allow"))
    rows = client.get("/api/traces?agent=otel-bot", headers=ADMIN).json()["traces"]
    assert rows and rows[0]["checks"] == 0


def test_a_run_says_what_was_asked_with_personal_data_masked(client):
    client.post(
        "/v1/guard/input",
        json={"agent": "summary-bot", "content": "Refund order 7 to jane.doe@example.com please"},
    )
    client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": [
                {"role": "system", "content": "be nice"},
                {"role": "user", "content": "Where is my parcel?"},
            ],
        },
        headers={"X-AgentFox-Agent": "summary-bot"},
    )
    rows = client.get("/api/traces?agent=summary-bot", headers=ADMIN).json()["traces"]
    summaries = {r["summary"] for r in rows}
    assert "Where is my parcel?" in summaries
    masked = next(s for s in summaries if s and s.startswith("Refund"))
    assert "jane.doe@example.com" not in masked and "REDACTED" in masked
