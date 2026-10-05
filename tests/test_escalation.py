"""P11 — escalation governance. 31.1% of all catalogued failures.

Everyone ships the mechanism to escalate. The claim here is narrower and, as far as
the research went, unclaimed: **detecting that it should have escalated and didn't**.
Escalation is the one control whose failure is invisible from inside the system — a
conversation where the agent kept going instead of handing off looks perfectly
ordinary in the telemetry, and the user simply leaves.
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentfox.core.db import session_scope
from agentfox.containment.escalation import (
    DEFAULT_CONDITIONS,
    REQUIRED_CONTEXT,
    _loop_without_handoff,
    assess,
    breached_handoffs,
    build_context,
    detect_false_resolution,
    detect_missed_escalation,
    escalation_report,
    explicit_handoff_request,
    get_policy,
    handoff_completeness,
    is_abstention,
    raise_handoff,
    record_turn,
    sentiment_signal,
    set_policy,
    topic_signal,
    turn_depth_risk,
)
from agentfox.core.models import Agent, ConversationTurn, Finding, Handoff, utcnow

from .conftest import as_user


@pytest.fixture
def agent_id(seeded) -> str:
    return seeded.query(Agent).filter_by(slug="support-triage").one().id


def _conversation(seeded, agent_id, turns, session_id="sess-1"):
    for user_text, agent_text, extra in turns:
        record_turn(
            seeded,
            session_id=session_id,
            agent_id=agent_id,
            user_text=user_text,
            agent_text=agent_text,
            **extra,
        )
    return list(seeded.query(ConversationTurn).filter_by(session_id=session_id).all())


# ---------------------------------------------------------------------------
# Signals (F5.7)
# ---------------------------------------------------------------------------


def test_frustration_accumulates_across_markers():
    weak = sentiment_signal("this still isn't working")
    strong = sentiment_signal("This is ridiculous, third time I have asked!!!")
    assert strong["score"] < weak["score"] <= 0


def test_distress_and_legal_threats_are_flags_not_scores():
    """Averaging "I'm going to call my lawyer" into a satisfaction number is how a
    system misses the one message that mattered."""
    legal = sentiment_signal("I am going to call my lawyer about this")
    assert legal["flags"] == ["legal_threat"]
    harm = sentiment_signal("I want to hurt myself")
    assert harm["flags"] == ["self_harm"]


def test_an_explicit_request_is_recognised_in_its_common_forms():
    for text in (
        "can I speak to a human please",
        "transfer me to an agent",
        "I want a real person",
        "get me a manager",
        "please escalate this",
    ):
        assert explicit_handoff_request(text), text


def test_ordinary_messages_are_not_treated_as_requests():
    """A policy that fires on everything trains humans to ignore the queue."""
    for text in ("what are your opening hours", "thanks, that helped", "can you check my order"):
        assert not explicit_handoff_request(text), text


def test_abstention_is_detected_in_its_usual_phrasings():
    assert is_abstention("I don't have access to that information")
    assert is_abstention("That's outside my scope")
    assert not is_abstention("Your balance is £42.10")


def test_regulated_topics_are_recognised():
    assert "medical" in topic_signal("what dosage of that medication should I take")
    assert "financial_advice" in topic_signal("which fund should I invest in")
    assert topic_signal("what are your opening hours") == []


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def test_an_ordinary_conversation_does_not_qualify(seeded, agent_id):
    turns = _conversation(
        seeded,
        agent_id,
        [
            ("what are your opening hours?", "We're open 9-5 weekdays.", {}),
            ("thanks", "Happy to help.", {}),
        ],
    )
    assert not assess(turns).should_escalate


def test_an_explicit_request_qualifies_on_its_own(seeded, agent_id):
    turns = _conversation(
        seeded, agent_id, [("let me speak to a human", "I can help with that.", {})]
    )
    assessment = assess(turns)
    assert assessment.should_escalate
    assert assessment.triggers[0].condition == "explicit_request"


def test_repeated_abstention_qualifies(seeded, agent_id):
    """Declining is not the same as escalating. The user gets nothing either way."""
    turns = _conversation(
        seeded,
        agent_id,
        [
            ("where is my refund?", "I don't have access to that information.", {}),
            ("can you check again?", "I can't help with that.", {}),
        ],
    )
    conditions = {t.condition for t in assess(turns).triggers}
    assert "repeated_abstention" in conditions


def test_a_user_restating_the_same_question_counts_as_failure(seeded, agent_id):
    turns = _conversation(
        seeded,
        agent_id,
        [
            ("my order 123 never arrived", "Let me look into that.", {}),
            ("my order 123 still never arrived", "Let me look into that.", {}),
            ("my order 123 has still never arrived", "Let me look into that.", {}),
        ],
    )
    assert any(t.condition == "repeated_failure" for t in assess(turns).triggers)


def test_turn_depth_qualifies_on_its_own(seeded, agent_id):
    turns = _conversation(
        seeded, agent_id, [(f"question {i}", f"answer {i}", {}) for i in range(9)]
    )
    assert any(t.condition == "turn_depth" for t in assess(turns).triggers)
    risk = turn_depth_risk(turns)
    assert risk["exceeded"] and risk["depth"] == 9


def test_self_harm_is_the_only_critical_trigger(seeded, agent_id):
    turns = _conversation(seeded, agent_id, [("I want to hurt myself", "I'm sorry.", {})])
    trigger = next(t for t in assess(turns).triggers if t.condition.startswith("flag:"))
    assert trigger.severity == "critical"


def test_conditions_are_configurable_per_agent(seeded, agent_id):
    set_policy(seeded, agent_id=agent_id, conditions={"turn_depth": 3})
    turns = _conversation(
        seeded, agent_id, [(f"q{i}", f"a{i}", {}) for i in range(3)], session_id="s-cfg"
    )
    policy = get_policy(seeded, agent_id)
    assert policy.conditions_json["turn_depth"] == 3
    assert any(t.condition == "turn_depth" for t in assess(turns, policy).triggers)


def test_an_agent_policy_wins_over_the_global_default(seeded, agent_id):
    set_policy(seeded, agent_id=None, conditions={"turn_depth": 20})
    set_policy(seeded, agent_id=agent_id, conditions={"turn_depth": 4})
    assert get_policy(seeded, agent_id).conditions_json["turn_depth"] == 4
    assert get_policy(seeded, "agt_other").conditions_json["turn_depth"] == 20


def test_assessment_is_pure_so_it_can_be_simulated_before_it_is_enabled(seeded, agent_id):
    """A detector that cannot be run against yesterday's traffic cannot be tuned
    before it is turned on."""
    turns = _conversation(seeded, agent_id, [("escalate this", "ok", {})])
    before = seeded.query(Finding).count()
    assess(turns)
    assess(turns)
    assert seeded.query(Finding).count() == before


# ---------------------------------------------------------------------------
# The control: missed escalation (P11-2, F5.1)
# ---------------------------------------------------------------------------


def test_a_qualifying_conversation_that_never_escalated_is_detected(seeded, agent_id):
    _conversation(
        seeded,
        agent_id,
        [
            ("I need to speak to a human", "I can help you here.", {}),
            ("no, a person please", "Let me try again.", {}),
        ],
        session_id="missed-1",
    )
    # agent_slug scopes this to support-triage — the seed demo carries a real,
    # already-escalated qualifying conversation on payments-ops that would
    # otherwise inflate "qualified" here.
    result = detect_missed_escalation(seeded, raise_findings=False, agent_slug="support-triage")
    assert [m["session_id"] for m in result["missed"]] == ["missed-1"]
    assert result["qualified"] == 1
    assert result["missed_rate"] == 1.0


def test_a_conversation_that_did_escalate_is_not_flagged(seeded, agent_id):
    _conversation(
        seeded,
        agent_id,
        [("let me talk to a person", "Connecting you now.", {"escalated": True})],
        session_id="ok-1",
    )
    assert detect_missed_escalation(seeded, raise_findings=False)["missed"] == []


def test_an_existing_handoff_counts_as_escalation(seeded, agent_id):
    _conversation(seeded, agent_id, [("escalate please", "One moment.", {})], session_id="hand-1")
    raise_handoff(
        seeded,
        agent_id=agent_id,
        session_id="hand-1",
        trace_id=None,
        triggers=[],
        context=build_context(
            list(seeded.query(ConversationTurn).filter_by(session_id="hand-1").all())
        ),
    )
    assert detect_missed_escalation(seeded, raise_findings=False)["missed"] == []


def test_detection_raises_a_finding_and_a_retroactive_handoff(seeded, agent_id):
    """Recording that a person was left waiting and then leaving them waiting is an
    audit artefact, not a control."""
    _conversation(
        seeded, agent_id, [("I want a manager", "I can assist.", {})], session_id="retro-1"
    )
    detect_missed_escalation(seeded)
    finding = seeded.query(Finding).filter_by(type="missed_escalation").one()
    assert finding.severity == "high"
    handoff = seeded.query(Handoff).filter_by(session_id="retro-1").one()
    assert handoff.detected_retroactively is True
    assert handoff.due_at is not None


def test_scanning_twice_does_not_duplicate(seeded, agent_id):
    _conversation(seeded, agent_id, [("escalate", "ok", {})], session_id="dupe-1")
    detect_missed_escalation(seeded)
    detect_missed_escalation(seeded)
    assert seeded.query(Handoff).filter_by(session_id="dupe-1").count() == 1


def test_the_read_only_endpoint_does_not_act(seeded, agent_id):
    before = seeded.query(Handoff).count()  # the seed demo carries one real hand-off
    _conversation(seeded, agent_id, [("escalate", "ok", {})], session_id="ro-1")
    detect_missed_escalation(seeded, raise_findings=False)
    assert seeded.query(Finding).filter_by(type="missed_escalation").count() == 0
    assert seeded.query(Handoff).count() == before


def test_the_missed_rate_is_measured_against_qualifying_conversations(seeded, agent_id):
    """PRD §10.1 targets < 5% of *qualifying* conversations, not of all traffic —
    dividing by total would flatter the number."""
    _conversation(seeded, agent_id, [("escalate", "ok", {})], session_id="q-1")
    _conversation(seeded, agent_id, [("escalate", "ok", {"escalated": True})], session_id="q-2")
    _conversation(seeded, agent_id, [("hours?", "9-5", {})], session_id="q-3")
    # agent_slug scopes this to support-triage — see the note above.
    result = detect_missed_escalation(seeded, raise_findings=False, agent_slug="support-triage")
    assert result["conversations"] == 3
    assert result["qualified"] == 2
    assert result["missed_rate"] == 0.5


# ---------------------------------------------------------------------------
# Hand-off quality (F5.2) and SLA (F5.6)
# ---------------------------------------------------------------------------


def test_an_incomplete_handoff_is_its_own_failure(seeded, agent_id):
    """The escalation happened *and* the human cannot act on it."""
    handoff = raise_handoff(
        seeded,
        agent_id=agent_id,
        session_id="ctx-1",
        trace_id=None,
        triggers=[],
        context={"user_request": "refund please"},
    )
    assert handoff.completeness < 1.0
    finding = seeded.query(Finding).filter_by(type="incomplete_handoff").one()
    assert "conversation_summary" in finding.evidence_json["missing"]


def test_a_context_package_built_from_the_conversation_is_complete(seeded, agent_id):
    turns = _conversation(
        seeded,
        agent_id,
        [("my refund is late", "Let me check.", {}), ("still nothing", "I can't help.", {})],
        session_id="ctx-2",
    )
    report = handoff_completeness(build_context(turns, "agent could not resolve"))
    assert report["complete"], report["missing"]
    assert set(report["present"]) == set(REQUIRED_CONTEXT)


def test_an_unacknowledged_handoff_breaches_its_sla(seeded, agent_id):
    """An escalation raised into a queue nobody watches is the same outcome as no
    escalation — and worse in one respect: the system believes it did its job."""
    handoff = raise_handoff(
        seeded,
        agent_id=agent_id,
        session_id="sla-1",
        trace_id=None,
        triggers=[],
        context={},
    )
    handoff.due_at = utcnow() - dt.timedelta(minutes=1)
    seeded.flush()

    breached = breached_handoffs(seeded)
    assert [h.id for h in breached] == [handoff.id]
    assert handoff.status == "breached"
    assert seeded.query(Finding).filter_by(type="handoff_sla_breach").count() == 1


def test_an_acknowledged_handoff_does_not_breach(seeded, agent_id):
    handoff = raise_handoff(
        seeded, agent_id=agent_id, session_id="sla-2", trace_id=None, triggers=[], context={}
    )
    handoff.status = "acknowledged"
    handoff.due_at = utcnow() - dt.timedelta(hours=1)
    seeded.flush()
    assert breached_handoffs(seeded) == []


# ---------------------------------------------------------------------------
# F5.3 loop-instead-of-escalate, F5.5 false resolution
# ---------------------------------------------------------------------------


def test_a_broken_loop_with_no_handoff_is_still_a_failure(seeded, agent_id):
    """Breaking the loop stops the agent burning budget. It does nothing for the user,
    who is still on the other end with an unsolved problem."""
    _conversation(
        seeded,
        agent_id,
        [
            ("reset my password", "Try the reset link.", {}),
            ("reset my password", "Try the reset link.", {}),
            ("reset my password", "Try the reset link.", {}),
        ],
        session_id="loop-1",
    )
    assert _loop_without_handoff(seeded, "loop-1")


def test_a_loop_that_was_handed_off_is_not_flagged(seeded, agent_id):
    _conversation(
        seeded,
        agent_id,
        [("same question", "same answer", {}), ("same question", "same answer", {})],
        session_id="loop-2",
    )
    raise_handoff(
        seeded, agent_id=agent_id, session_id="loop-2", trace_id=None, triggers=[], context={}
    )
    assert not _loop_without_handoff(seeded, "loop-2")


def test_a_resolution_claim_the_user_contradicts_is_detected(seeded, agent_id):
    _conversation(
        seeded,
        agent_id,
        [
            ("my card was declined", "I've resolved that for you.", {}),
            ("it's still declined", "Let me check again.", {}),
        ],
        session_id="false-1",
    )
    found = detect_false_resolution(seeded, raise_findings=False)
    assert found[0]["session_id"] == "false-1"
    assert "continued" in found[0]["contradictions"][0]


def test_claiming_resolution_while_declining_is_detected(seeded, agent_id):
    """ "Anything else I can help with?" after declining to help is the shape."""
    _conversation(
        seeded,
        agent_id,
        [
            (
                "where is my order",
                "I don't have access to that data. Anything else I can help with?",
                {},
            )
        ],
        session_id="false-2",
    )
    found = detect_false_resolution(seeded, raise_findings=False)
    assert any("declined" in c for c in found[0]["contradictions"])


def test_a_genuine_resolution_is_not_flagged(seeded, agent_id):
    _conversation(
        seeded,
        agent_id,
        [("what are your hours", "We're open 9-5. I've sorted that for you.", {})],
        session_id="true-1",
    )
    assert detect_false_resolution(seeded, raise_findings=False) == []


# ---------------------------------------------------------------------------
# Report and API
# ---------------------------------------------------------------------------


def test_the_report_carries_the_headline_metric(seeded, agent_id):
    _conversation(seeded, agent_id, [("get me a human", "I can help.", {})], session_id="rep-1")
    # agent_slug scopes this to support-triage — see the note above.
    report = escalation_report(seeded, agent_slug="support-triage")
    assert report["qualified_for_escalation"] == 1
    assert report["missed_escalations"] == 1
    assert report["missed_rate"] == 1.0


def test_the_escalation_api(client):
    headers = as_user("marcus@example.com")
    assert (
        client.put(
            "/api/escalation/policy",
            json={"agent": "support-triage", "conditions": {"turn_depth": 4}, "mode": "enforce"},
            headers=headers,
        ).status_code
        == 201
    )

    for text in ("I need a human", "still need a human"):
        assert (
            client.post(
                "/api/escalation/turns",
                json={
                    "session_id": "api-1",
                    "agent": "support-triage",
                    "user_text": text,
                    "agent_text": "I can help here.",
                },
                headers=headers,
            ).status_code
            == 201
        )

    missed = client.get("/api/escalation/missed", headers=headers).json()
    assert missed["missed"][0]["session_id"] == "api-1"

    conversation = client.get("/api/escalation/conversations/api-1", headers=headers).json()
    assert conversation["assessment"]["missed"] is True

    scanned = client.post("/api/escalation/scan", headers=headers).json()
    assert len(scanned["missed"]) == 1
    handoffs = client.get("/api/escalation/handoffs", headers=headers).json()["handoffs"]
    assert handoffs[0]["detected_retroactively"] is True

    acked = client.post(
        f"/api/escalation/handoffs/{handoffs[0]['id']}/acknowledge", headers=headers
    ).json()
    assert acked["status"] == "acknowledged"

    # The queue and the report both need to answer "just this agent" — a mixed
    # queue with no filter is exactly what a team with more than one agent hits.
    # hr-screening (not payments-ops) is the clean "other agent" here — the seed
    # demo carries a real hand-off for payments-ops to make NOM-RTG-10 computable.
    filtered = client.get("/api/escalation/handoffs?agent=support-triage", headers=headers).json()[
        "handoffs"
    ]
    assert filtered and all(h["agent_slug"] == "support-triage" for h in filtered)
    other = client.get("/api/escalation/handoffs?agent=hr-screening", headers=headers).json()[
        "handoffs"
    ]
    assert not other

    report = client.get("/api/escalation/report?agent=support-triage", headers=headers).json()
    assert report["handoffs"] == len(filtered)
    empty_report = client.get("/api/escalation/report?agent=hr-screening", headers=headers).json()
    assert empty_report["handoffs"] == 0


def test_gateway_completions_record_a_conversation_turn(client):
    """Before this, only the SDK's `agentfox.auto()` monkeypatch called record_turn
    — a team integrating via this HTTP gateway directly got zero escalation tracking
    however long they ran it. Exercised end to end through the actual route."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": [{"role": "user", "content": "I want to speak to a manager"}],
        },
        headers={"X-Nometria-Agent": "support-triage", "X-Nometria-Session": "gw-turn-1"},
    )
    assert response.status_code == 200
    with session_scope() as session:
        turn = session.query(ConversationTurn).filter_by(session_id="gw-turn-1").one()
    assert turn.user_text == "I want to speak to a manager"
    assert turn.signals_json.get("explicit_request") is True


def test_policy_writes_require_the_policy_role(client):
    response = client.put(
        "/api/escalation/policy",
        json={"agent": "support-triage", "conditions": {}},
        headers=as_user("aisha@example.com"),
    )
    assert response.status_code == 403


def test_the_default_conditions_are_conservative():
    """An escalation policy that fires on everything trains humans to ignore the
    queue, which is worse than not having one."""
    assert DEFAULT_CONDITIONS["repeated_failure"] >= 2
    assert DEFAULT_CONDITIONS["turn_depth"] >= 6
    assert DEFAULT_CONDITIONS["sentiment_below"] <= -0.5
