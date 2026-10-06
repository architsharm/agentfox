"""What the product can see of a request it governed through `/v1/guard`.

The gateway has two integration shapes and they are not equally served. One proxies
the model call (`/v1/chat/completions`, the SDK's `agentfox.auto()`); the other
guards content in place (`/v1/guard/input`, `/v1/guard/output`) and is the lower
friction of the two — no re-routing of every model call through a new hop, which is
exactly why a security team adopting this reaches for it first.

Almost the entire read side of the product keys off `Trace`: the Traces page lists
them, `/api/onboarding` decides from them whether anything is connected at all, an
agent's last-seen comes from them, and control effectiveness is computed from the
telemetry hanging off them. `guard_tool_call`, `guard_memory_write` and
`guard_agent_message` all started one. `guard_content`, the most used of the four,
did not.

The result was not a missing page. It was a product that governed thousands of
requests and then said *"Nothing is sending traffic yet"* on its front screen, with
the findings from those very requests counted in the header directly above the
message. These tests are about that contradiction, from both ends.
"""

from __future__ import annotations

from sqlalchemy import select

from agentfox.core.models import Agent, Decision, Trace
from tests.conftest import INDIRECT_INJECTION, PII_TEXT, as_user, promote


def _guard(client, content: str, surface: str = "input", **extra):
    return client.post(
        f"/v1/guard/{surface}",
        json={"agent": "support-triage", "content": content, **extra},
        headers=as_user("admin@example.com"),
    )


def test_guarding_content_records_a_trace(client):
    """The one-line version of every other test in this file."""
    from agentfox.core.db import session_scope

    assert _guard(client, "Where is my order #44812?").status_code == 200
    with session_scope() as s:
        traces = list(s.scalars(select(Trace)))
    assert len(traces) == 1
    assert traces[0].agent_slug == "support-triage"


def test_the_trace_is_attached_to_the_agent_so_it_has_a_last_seen(client):
    """An agent registry whose rows all read "last seen —" is an inventory, not a
    registry. The resolve happens before the trace starts for exactly this reason."""
    from agentfox.core.db import session_scope

    _guard(client, "Can you reset my password?")
    with session_scope() as s:
        trace = s.scalars(select(Trace)).one()
        agent = s.scalar(select(Agent).where(Agent.slug == "support-triage"))
    assert agent is not None
    assert trace.agent_id == agent.id
    assert agent.last_seen_at is not None


def test_the_trace_carries_the_verdict_not_the_default(client):
    """`Trace.verdict` defaults to allow, so a blocked request recorded as a trace
    nobody raised the verdict on is worse than no trace: it is a clean record of a
    request that was not clean.

    Enforcing first, deliberately. In observe mode the applied verdict *is* allow and
    the trace is right to say so — the counterfactual lives on the decision. Asserting
    against observe mode would have pinned the wrong behaviour as correct.
    """
    from agentfox.core.db import session_scope

    promote(client, "baseline")
    _guard(client, INDIRECT_INJECTION)
    with session_scope() as s:
        trace = s.scalars(select(Trace)).one()
    assert trace.verdict != "allow"
    assert trace.ended_at is not None


def test_in_observe_mode_the_trace_says_allow_because_nothing_was_blocked(client):
    """The other half, so neither reading can regress unnoticed."""
    from agentfox.core.db import session_scope

    _guard(client, INDIRECT_INJECTION)
    with session_scope() as s:
        trace = s.scalars(select(Trace)).one()
        decision = s.scalars(select(Decision)).one()
    assert trace.verdict == "allow"
    assert decision.mode == "observe"
    assert decision.rules_fired_json, "observe still records what would have happened"


def test_a_second_guard_on_the_same_trace_cannot_erase_the_first_verdict(client):
    """Guarding the input and then the output is one request, so it is one trace —
    and a clean output must not overwrite a blocked input. `end_trace` is called with
    the verdict already on the trace for this reason."""
    from agentfox.core.db import session_scope

    promote(client, "baseline")
    first = _guard(client, INDIRECT_INJECTION)
    trace_id = first.json()["trace_id"]
    assert trace_id, "a caller cannot correlate two calls it was never given an id for"

    second = _guard(client, "Your order ships Tuesday.", surface="output", trace_id=trace_id)
    assert second.status_code == 200, second.text

    with session_scope() as s:
        traces = list(s.scalars(select(Trace)))
        decisions = list(s.scalars(select(Decision)))
    assert len(traces) == 1, "one request, passed through twice, is one trace"
    assert traces[0].verdict != "allow", "the clean output must not erase the blocked input"
    assert len(decisions) == 2


def test_the_front_page_stops_saying_nothing_is_connected(client):
    """The contradiction that motivated all of this, asserted end to end."""
    before = client.get("/api/onboarding", headers=as_user("admin@example.com")).json()
    assert before["connected"] is False, "fixture must start disconnected or this proves nothing"

    _guard(client, PII_TEXT, surface="output")

    after = client.get("/api/onboarding", headers=as_user("admin@example.com")).json()
    assert after["connected"] is True
    assert after["counts"]["traces"] >= 1
    assert after["counts"]["decisions"] >= 1


def test_the_traces_list_shows_it(client):
    """Where a platform engineer goes to answer "what did you do to my request"."""
    _guard(client, INDIRECT_INJECTION)
    body = client.get("/api/traces", headers=as_user("admin@example.com")).json()
    rows = body.get("traces", body) if isinstance(body, dict) else body
    assert len(rows) >= 1


def test_an_unregistered_agent_is_observed_rather_than_turned_away(client):
    """P1-6 — the inline path serves shadow traffic so it is seen. Resolving in the
    route is what makes that true here and not only on the proxy path."""
    from agentfox.core.db import session_scope

    response = client.post(
        "/v1/guard/input",
        json={"agent": "undeclared-side-project", "content": "hello"},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200
    with session_scope() as s:
        agent = s.scalar(select(Agent).where(Agent.slug == "undeclared-side-project"))
    assert agent is not None, "shadow traffic must show up in the registry, not vanish"


def test_the_red_team_runner_still_leaves_no_trace(seeded, enforcer):
    """A simulated attack is not something the agent did.

    `trace` is optional on `check_content` for this one caller, and it matters: red
    team runs would otherwise inflate every traffic count in the product and put
    attacks the agent never received on its own timeline.
    """
    from sqlalchemy import func

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    enforcer.check_content(agent_slug=agent.slug, content=INDIRECT_INJECTION, surface="input")
    assert seeded.scalar(select(func.count()).select_from(Trace)) == 0


def test_a_redact_verdict_returns_the_rewritten_text(client):
    """A guard endpoint that says "redact" and hands back nothing leaves every caller
    to mask the content themselves from spans (#17). The rewrite is in `content`."""
    client.post(
        "/api/policies/baseline/mode",
        json={"mode": "enforce"},
        headers=as_user("admin@example.com"),
    )
    text = "Reach Jane at jane.doe@example.com today."
    body = _guard(client, text, surface="output").json()
    assert body["verdict"] == "redact", body
    assert body["content"] is not None
    assert "jane.doe@example.com" not in body["content"]
    assert body["content"] == "Reach Jane at [REDACTED:PII.EMAIL] today."


def test_an_allowed_request_has_no_rewritten_content(client):
    body = _guard(client, "Where is my order #44812?").json()
    assert body["verdict"] == "allow"
    assert body["content"] is None
