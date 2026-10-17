"""One agent's quality: every wrong-result signal already recorded for it, in one read."""

from __future__ import annotations

import datetime as dt

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
URL = "/api/metrics/quality?range=24h&agent=quality-bot"


def _seed() -> None:
    from agentfox.core.db import session_scope
    from agentfox.core.models import (
        Agent,
        Decision,
        EvalRun,
        Finding,
        GuardrailFeedback,
        Span,
        Trace,
    )

    now = dt.datetime.now(dt.UTC)
    with session_scope() as session:
        agent = Agent(slug="quality-bot", registered=True, status="active")
        other = Agent(slug="other-bot", registered=True, status="active")
        session.add_all([agent, other])
        session.flush()

        def run(hours_ago: int, rules: list[dict], verdict: str = "allow", error: str = ""):
            t = Trace(
                agent_slug="quality-bot",
                agent_id=agent.id,
                verdict=verdict,
                started_at=now - dt.timedelta(hours=hours_ago),
            )
            session.add(t)
            session.flush()
            if error:
                session.add(
                    Span(trace_id=t.id, kind="tool", name="crm.lookup", status="error", error=error)
                )
            d = Decision(
                trace_id=t.id,
                agent_id=agent.id,
                surface="output",
                verdict=verdict,
                mode="observe",
                rules_fired_json=rules,
            )
            session.add(d)
            session.flush()
            return d

        run(1, [{"rule_id": "grounding.unsupported", "effect": "block", "mode": "observe"}])
        run(2, [{"rule_id": "answerability.out_of_scope", "effect": "abstain"}], verdict="abstain")
        run(3, [{"rule_id": "pii.outbound_redact", "effect": "redact"}], verdict="redact")
        d = run(4, [], error="timeout")
        session.add(
            GuardrailFeedback(
                decision_id=d.id, agent_id=agent.id, label="false_negative", actor="a@example.com"
            )
        )
        session.add(
            EvalRun(
                suite_id="s1",
                target_json={"agent": "quality-bot"},
                mode="online",
                status="completed",
                summary_json={
                    "cases": 4,
                    "scorers": {
                        "groundedness": {"pass_rate": 0.5},
                        "task_completion": {"pass_rate": 1.0},
                    },
                },
            )
        )
        session.add(EvalRun(suite_id="s1", target_json={"agent": "other-bot"}, mode="online"))
        session.add(
            Finding(
                type="fabricated_citation",
                severity="high",
                title="Cited a page that does not exist",
                subject_type="agent",
                subject_id=agent.id,
                status="open",
                fingerprint="fp-quality-1",
            )
        )
        session.add(
            Finding(
                type="shadow_agent",
                severity="high",
                title="not a quality issue",
                subject_type="agent",
                subject_id=agent.id,
                status="open",
                fingerprint="fp-quality-2",
            )
        )


def test_quality_collects_every_signal_for_the_agent(client):
    _seed()
    r = client.get(URL, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requests"] == 4

    wrong = body["wrong_answers"]
    assert {x["rule_id"] for x in wrong["rules"]} == {
        "grounding.unsupported",
        "answerability.out_of_scope",
    }
    assert wrong["total"] == 2 and wrong["requests"] == 2 and wrong["rate"] == 0.5
    assert wrong["abstained"] == 1
    assert sum(body["trend"]["wrong_answers"]) == 2
    assert sum(body["trend"]["requests"]) == 4

    assert body["failed_steps"]["total"] == 1
    assert body["failed_steps"]["rows"][0]["name"] == "crm.lookup"
    assert sum(body["trend"]["failed_steps"]) == 1

    [run] = body["evals"]["runs"]
    assert run["pass_rate"] == 0.75 and run["scorers"]["groundedness"] == 0.5

    assert body["feedback"]["labels"]["false_negative"] == 1
    assert [f["type"] for f in body["findings"]] == ["fabricated_citation"]
    assert set(body["handoffs"]) == {"handoffs", "qualified", "missed", "false_resolutions"}


def test_an_agent_with_no_traffic_reads_as_empty_not_an_error(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        session.add(Agent(slug="quiet-bot", registered=True, status="active"))
    body = client.get("/api/metrics/quality?agent=quiet-bot", headers=ADMIN).json()
    assert body["requests"] == 0
    assert body["wrong_answers"]["rate"] is None and body["failed_steps"]["rate"] is None
    assert body["evals"]["runs"] == [] and body["findings"] == []


def test_unknown_agent_is_404(client):
    assert client.get("/api/metrics/quality?agent=nobody", headers=ADMIN).status_code == 404
