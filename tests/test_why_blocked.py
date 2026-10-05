"""Getting from a blocked response back to the reason for it.

The person this matters to did not go looking for a governance product. They met a
block as a line in a log, hours later, holding a decision id — and the product's
answer to "why" lived in the HTTP response body, which is long gone, and nowhere
else. The dashboard could show them which rules fired and which detectors ran and
left them to work out for themselves which of five detections was the one that
mattered and which of four detectors to argue with.

Two things close that. The response says where to look, and the page, when they get
there, rebuilds the sentence the response had already written.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.core.config import reset_settings_cache
from agentfox.core.models import Trace
from agentfox.detection.tuning import explain_recorded
from agentfox.prove.audit.trace import full_trace

from .conftest import INDIRECT_INJECTION, PII_TEXT, as_user


@pytest.fixture
def console(monkeypatch):
    monkeypatch.setenv("NOMETRIA_CONSOLE_URL", "https://governance.example.com/")
    reset_settings_cache()
    yield "https://governance.example.com"
    reset_settings_cache()


def _guard(client, content: str, surface: str = "input"):
    return client.post(
        f"/v1/guard/{surface}",
        json={"agent": "support-triage", "content": content},
        headers=as_user("admin@example.com"),
    )


# ---------------------------------------------------------------------------
# Saying where to look
# ---------------------------------------------------------------------------


def test_the_response_links_to_the_decision_when_the_console_is_configured(client, console):
    body = _guard(client, INDIRECT_INJECTION).json()
    assert body["explain_url"] == f"{console}/app/traces/{body['trace_id']}"


def test_no_link_is_offered_when_nobody_has_said_where_the_console_is(client):
    """Absent, not empty, and never guessed from the Host header.

    Behind a proxy the Host header is whatever the proxy sent. A link built from it
    points somewhere that does not exist, and an engineer who follows it concludes
    the dashboard is broken rather than unconfigured — strictly worse than no link.
    """
    assert "explain_url" not in _guard(client, INDIRECT_INJECTION).json()


def test_an_allowed_request_gets_the_link_too(client, console):
    """The commonest question about an allowed request is "why did you flag it and
    let it through", and that is the same page."""
    assert "explain_url" in _guard(client, "Where is my order #44812?").json()


def test_the_blocked_proxy_response_carries_the_link_in_body_and_header(client, console):
    """`curl -i` is how this is actually read, and a streamed completion's body is a
    sequence of SSE frames rather than a JSON object to read a field out of."""
    client.post(
        "/api/policies/baseline/mode",
        json={"mode": "enforce"},
        headers=as_user("admin@example.com"),
    )
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": [
                {"role": "user", "content": "Summarise."},
                {"role": "tool", "content": INDIRECT_INJECTION},
            ],
        },
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["explain_url"].startswith(console)
    assert response.headers["X-Nometria-Explain"].startswith(console)


# ---------------------------------------------------------------------------
# Answering when they get there
# ---------------------------------------------------------------------------


def test_the_trace_detail_rebuilds_the_reason_it_used_to_throw_away(client):
    from agentfox.core.db import session_scope

    live = _guard(client, INDIRECT_INJECTION).json()
    with session_scope() as s:
        trace_id = s.scalars(select(Trace)).one().id
        detail = full_trace(s, trace_id)

    recorded = detail["decisions"][0]["explanation"]
    # The same sentence the caller got, reconstructed from storage alone.
    assert recorded["summary"] == live["explanation"]["summary"]
    assert recorded["remedy"] == live["explanation"]["remedy"]
    assert recorded["rule"]["rule_id"] == live["explanation"]["rule"]["rule_id"]


def test_the_rebuilt_reason_blames_the_same_match_as_the_live_one(client):
    """The point of the reconstruction. It selects by the rule's own recorded entity
    predicate, so it cannot quietly disagree with what actually fired."""
    from agentfox.core.db import session_scope

    _guard(client, INDIRECT_INJECTION)
    with session_scope() as s:
        detail = full_trace(s, s.scalars(select(Trace)).one().id)

    decisive = [m for m in detail["decisions"][0]["explanation"]["matches"] if m["decisive"]]
    assert [m["entity_type"] for m in decisive] == ["INJECTION.INSTRUCTION_OVERRIDE"]


def test_the_dispute_names_the_detector_worth_arguing_with(client):
    from agentfox.core.db import session_scope

    _guard(client, PII_TEXT, surface="output")
    with session_scope() as s:
        detail = full_trace(s, s.scalars(select(Trace)).one().id)

    payload = detail["decisions"][0]["explanation"]["dispute"]["payload"]
    assert payload["detector_key"] == "pii.native"
    assert payload["decision_id"] == detail["decisions"][0]["id"]


def test_one_decisions_matches_are_not_attributed_to_another(client):
    """A trace holds several decisions and they are separate answers. Attributing an
    input's injection match to the output's PII block would be a confident lie."""
    from agentfox.core.db import session_scope

    first = _guard(client, INDIRECT_INJECTION).json()
    client.post(
        "/v1/guard/output",
        json={
            "agent": "support-triage",
            "content": PII_TEXT,
            "trace_id": first["trace_id"],
        },
        headers=as_user("admin@example.com"),
    )
    with session_scope() as s:
        detail = full_trace(s, first["trace_id"])

    assert len(detail["decisions"]) == 2
    by_surface = {d["surface"]: d["explanation"] for d in detail["decisions"]}
    assert "INJECTION" in by_surface["input"]["summary"]
    assert "INJECTION" not in by_surface["output"]["summary"]


def test_a_rule_that_fired_on_no_detection_still_says_something():
    """A tool, capability or taint rule matches no entity at all. An empty panel is
    not an explanation; saying which rule fired and that it was not a detector is."""
    recorded = explain_recorded(
        {
            "id": "dec_x",
            "surface": "tool_args",
            "verdict": "block",
            "rules_fired": [
                {"rule_id": "capability.denied", "effect": "block", "reason": "not granted"}
            ],
            "detector_run_ids": [],
        },
        [],
    )
    assert "capability.denied" in recorded["summary"]
    assert "other than a detector match" in recorded["summary"]


def test_a_decision_with_nothing_recorded_produces_no_claim():
    """Rather than a confident sentence about nothing."""
    recorded = explain_recorded(
        {"id": "dec_y", "surface": "input", "verdict": "allow", "rules_fired": []}, []
    )
    assert recorded["summary"] == ""
    assert recorded["matches"] == []
