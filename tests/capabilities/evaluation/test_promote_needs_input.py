"""A test made from a run asks what the run's user asked (wow3 prove B3).

Promoting a run reported to an account (``auto()`` with a key checks through
``/v1/guard/*``) made a case whose prompt was ``trace.intent``, which those runs don't
have, and which then passed at 100% on "No user input". The guard path now keeps the
user's message and the reply (masked, as the run preview is), and a run with no input
is refused with a sentence saying why.
"""

from __future__ import annotations

from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import EvalCase, Trace
from tests.conftest import as_user

ME = as_user("priya@example.com")


def _suite(client):
    client.post("/api/eval/suites", json={"key": "regress", "name": "Regress"}, headers=ME)


def test_a_run_reported_through_the_guard_becomes_a_real_case(client):
    _suite(client)
    asked = client.post(
        "/v1/guard/input",
        json={
            "agent": "support-triage",
            "content": "Where is order 4410? My email is jane.doe@example.com",
        },
    ).json()
    trace_id = asked["trace_id"]
    client.post(
        "/v1/guard/output",
        json={"agent": "support-triage", "content": "It shipped on Monday.", "trace_id": trace_id},
    ).raise_for_status()

    r = client.post(f"/api/eval/suites/regress/cases/from-trace?trace_id={trace_id}", headers=ME)
    assert r.status_code == 201, r.text
    with session_scope() as s:
        case = s.scalar(select(EvalCase).where(EvalCase.source_trace_id == trace_id))
        prompt = case.input_json["prompt"]
        assert "Where is order 4410?" in prompt
        assert "jane.doe@example.com" not in prompt  # masked before it was kept
        assert case.context_json["observed_output"] == "It shipped on Monday."


def test_runs_reported_through_the_guard_can_be_scored_online(client):
    """`test online` said "sampled 0 of 12 … not scored": no output was recorded."""
    from agentfox.capabilities.evaluation.runner import sample_production

    for i in range(3):
        t = client.post(
            "/v1/guard/input", json={"agent": "support-triage", "content": f"Question {i}?"}
        ).json()["trace_id"]
        client.post(
            "/v1/guard/output",
            json={"agent": "support-triage", "content": f"Answer {i}.", "trace_id": t},
        ).raise_for_status()
    with session_scope() as s:
        run = sample_production(s, "support-triage", rate=1.0)
        assert run is not None
        assert run.summary_json["skipped_no_output"] == 0, run.summary_json
        assert run.summary_json["sampled"] >= 3, run.summary_json


def test_a_run_with_no_input_is_refused_with_why(client):
    _suite(client)
    with session_scope() as s:
        trace = Trace(agent_slug="support-triage")
        s.add(trace)
        s.flush()
        trace_id = trace.id
    r = client.post(f"/api/eval/suites/regress/cases/from-trace?trace_id={trace_id}", headers=ME)
    assert r.status_code == 422
    assert "no recorded user input" in r.json()["detail"]
    with session_scope() as s:
        assert s.scalar(select(EvalCase).where(EvalCase.source_trace_id == trace_id)) is None
