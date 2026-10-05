"""P7 — answerability and abstention (F1).

The distinction that makes this a different control from everything in the
competitive set: Cleanlab, Vectara, RAGAS, Galileo and Patronus all score an answer
*after* it exists. By then the number has been invented, and a confident wrong number
scored at 0.4 is still a confident wrong number in front of a user.

The counter-metric is load-bearing throughout. An over-refusing agent is uninstalled
faster than a hallucinating one, so every test here that adds a refusal is paired with
one that proves we do not refuse what we could answer.
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentfox.grounding.answerability import (
    AGGREGATE,
    FACT,
    OPINION,
    OUT_OF_COVERAGE,
    OUT_OF_DOMAIN,
    OUT_OF_SCOPE_ENTITY,
    PREDICTION,
    PROCEDURE,
    UNKNOWABLE,
    classify_answerability,
    completeness_signal,
    declare_boundary,
    detect_over_refusal,
    get_boundary,
    is_refusal,
    question_type,
    verify_boundary,
)
from agentfox.core.models import Agent, Finding

from .conftest import as_user


@pytest.fixture
def agent(seeded) -> Agent:
    return seeded.query(Agent).filter_by(slug="support-triage").one()


@pytest.fixture
def boundary(seeded, agent):
    return declare_boundary(
        seeded,
        agent_id=agent.id,
        systems_of_record=["CRM", "order-db"],
        coverage_months=24,
        answerable_types=[FACT, AGGREGATE, PROCEDURE],
        out_of_scope_topics=["payroll", "hr records"],
        mode="enforce",
    )


# ---------------------------------------------------------------------------
# Question classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("what was revenue in 2024?", FACT),
        ("what is the status of order ABC-12345?", FACT),
        ("how many orders shipped last month?", AGGREGATE),
        ("what will Q4 2027 revenue be?", PREDICTION),
        ("revenue is expected to grow next year, by how much?", PREDICTION),
        ("should I invest in this fund?", OPINION),
        ("how do I reset my password?", PROCEDURE),
    ],
)
def test_questions_are_classified_deterministically(text, expected):
    assert question_type(text) == expected


def test_a_forecast_that_is_also_an_aggregate_is_a_forecast():
    """F1.4 — treating "what will total revenue be next year" as an aggregate returns
    a projection in the same register as a record, which is the failure itself."""
    assert question_type("what will total revenue be next year?") == PREDICTION


@pytest.mark.parametrize(
    "text",
    [
        "What if we doubled headcount, would that shorten the roadmap?",
        "What if the vendor changes pricing, might that affect renewal?",
        "How might the new tariff impact next quarter's margins?",
        "How might a competitor launch change our pricing strategy?",
    ],
)
def test_hypothetical_conditional_shapes_are_predictions(text):
    """benchmarks/answerability/README.md — the KUQ round-2 fix: "what if ...
    would/might/could" and "how might ... impact/shape/change" are a structurally
    distinct forecast shape the original five markers didn't cover."""
    assert question_type(text) == PREDICTION


def test_do_you_believe_is_an_opinion_marker():
    """benchmarks/answerability/README.md — "do you think" was already covered;
    "do you believe" (KUQ's controversial-category phrasing, e.g. "Do you believe
    Joe Biden is too old to be president") was not."""
    assert question_type("Do you believe remote work is better for productivity?") == OPINION


def test_a_forecast_shaped_question_naming_only_past_years_is_a_resolved_fact():
    """A question is grammatically forecast-shaped ("what was X projected to be by
    2018") but names only a year that has already happened relative to `now` — that's
    asking to recall a documented outcome, not soliciting a new prediction."""
    text = "What disease was projected to be eradicated worldwide by 2018, thanks to vaccines?"
    assert question_type(text, now=dt.date(2026, 1, 1)) == FACT


def test_a_forecast_naming_a_still_future_year_stays_a_prediction():
    """The same mechanism must not fire when any named year is still ahead of `now` —
    one open year is enough to keep the question a real, unresolved forecast."""
    text = "Which religion will have the most followers by the year 2050 if trends continue?"
    assert question_type(text, now=dt.date(2026, 1, 1)) == PREDICTION


def test_a_forecast_naming_no_year_at_all_is_unaffected_by_the_resolved_check():
    """No year mentioned leaves the question genuinely open — the resolved-prediction
    check only downgrades when it has positive evidence the question is already
    settled, never by default."""
    text = "What, ultimately, will the sun become?"
    assert question_type(text, now=dt.date(2026, 1, 1)) == PREDICTION


# ---------------------------------------------------------------------------
# F1.1 — the unknowable question
# ---------------------------------------------------------------------------


def test_a_forecast_is_refused_before_the_model_is_reached(seeded, boundary):
    verdict = classify_answerability("what will Q4 2027 revenue be?", boundary)
    assert not verdict.answerable
    assert verdict.abstention_kind == UNKNOWABLE
    assert verdict.should_abstain


def test_the_refusal_says_what_is_missing_not_just_no(seeded, boundary):
    """ "I don't know" sends the user away; naming the boundary sends them to the right
    system."""
    verdict = classify_answerability("what will sales be next quarter?", boundary)
    assert "CRM" in verdict.response
    assert "projection" in verdict.response


def test_a_gateway_completion_abstains_without_calling_the_model(seeded, enforcer, boundary):
    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "what will our revenue be next year?"}],
        model="echo-1",
    )
    assert result.verdict == "abstain"
    assert response is None
    assert result.content, "an abstention must still answer the user"
    assert result.rules_fired[0]["rule_id"] == f"answerability.{UNKNOWABLE}"


def test_the_abstention_is_recorded_in_the_audit_chain(seeded, enforcer, boundary):
    from agentfox.core.models import AuditEntry

    enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "predict next quarter's churn"}],
        model="echo-1",
    )
    assert seeded.query(AuditEntry).filter_by(action=f"answerability.{UNKNOWABLE}").count() == 1


# ---------------------------------------------------------------------------
# F1.2 — the coverage window
# ---------------------------------------------------------------------------


def test_a_question_before_the_coverage_window_is_refused(seeded, boundary):
    verdict = classify_answerability("what was revenue in 2019?", boundary)
    assert verdict.abstention_kind == OUT_OF_COVERAGE
    assert "2019" in verdict.response


def test_relative_dates_are_resolved_against_the_window(seeded, boundary):
    verdict = classify_answerability("what did we bill five years ago?", boundary)
    assert verdict.abstention_kind == OUT_OF_COVERAGE


def test_a_question_inside_the_window_is_answered(seeded, boundary):
    this_year = dt.date.today().year
    assert classify_answerability(f"what was revenue in {this_year}?", boundary).answerable


def test_an_undated_question_is_not_refused(seeded, boundary):
    """Refusing every question without a date would be over-refusal in its purest
    form — most real questions carry no explicit date at all."""
    assert classify_answerability("how many open orders are there?", boundary).answerable


def test_an_absolute_coverage_start_wins_over_a_rolling_window(seeded, agent):
    boundary = declare_boundary(
        seeded,
        agent_id=agent.id,
        coverage_months=120,
        coverage_start=dt.date(2023, 1, 1),
        answerable_types=[FACT],
        mode="enforce",
    )
    assert not classify_answerability("what happened in 2020?", boundary).answerable


# ---------------------------------------------------------------------------
# F1.3 — the entity not in scope
# ---------------------------------------------------------------------------


def test_an_unknown_identifier_is_refused_rather_than_invented(seeded, boundary):
    verdict = classify_answerability(
        "what is the status of order ZZZ-99999?", boundary, known_entities=["ABC-12345"]
    )
    assert verdict.abstention_kind == OUT_OF_SCOPE_ENTITY
    assert "ZZZ-99999" in verdict.response


def test_a_known_identifier_passes(seeded, boundary):
    assert classify_answerability(
        "what is the status of order ABC-12345?", boundary, known_entities=["ABC-12345"]
    ).answerable


def test_entity_scope_is_silent_when_the_caller_supplies_nothing(seeded, boundary):
    """Guessing at entity membership from the prompt would refuse on typos and
    nicknames, which is the adoption-killing failure again."""
    assert classify_answerability("status of order ZZZ-99999?", boundary).answerable


# ---------------------------------------------------------------------------
# Topic scope
# ---------------------------------------------------------------------------


def test_a_declared_out_of_scope_topic_is_refused(seeded, boundary):
    verdict = classify_answerability("what is our payroll policy?", boundary)
    assert verdict.abstention_kind == OUT_OF_DOMAIN
    assert "payroll" in verdict.response


def test_an_unsupported_question_type_names_what_is_supported(seeded, boundary):
    verdict = classify_answerability("should I switch suppliers?", boundary)
    assert verdict.abstention_kind is not None
    assert "fact" in verdict.response


# ---------------------------------------------------------------------------
# Observe-first
# ---------------------------------------------------------------------------


def test_observe_mode_records_the_counterfactual_without_refusing(seeded, agent, enforcer):
    """The only responsible way to ship a control whose false positives are refusals:
    show the team what enforcement would have refused, first."""
    declare_boundary(
        seeded,
        agent_id=agent.id,
        systems_of_record=["CRM"],
        answerable_types=[FACT],
        mode="observe",
    )
    verdict = classify_answerability(
        "what will revenue be next year?", get_boundary(seeded, agent.id)
    )
    assert not verdict.answerable
    assert not verdict.should_abstain

    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "what will revenue be next year?"}],
        model="echo-1",
    )
    assert response is not None, "observe mode must not withhold the answer"


def test_an_agent_with_no_boundary_is_unaffected(seeded, enforcer):
    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "what will revenue be next year?"}],
        model="echo-1",
    )
    assert response is not None


# ---------------------------------------------------------------------------
# F1.5 — over-refusal, the counter-metric
# ---------------------------------------------------------------------------


def test_refusal_language_is_recognised():
    assert is_refusal("I don't have access to that information")
    assert is_refusal("Data not available")
    assert not is_refusal("Your order shipped on Tuesday")


def test_refusing_an_answerable_question_is_a_finding_against_us(seeded, agent, boundary):
    verdict = classify_answerability("how many open orders are there?", boundary)
    assert verdict.answerable
    record = detect_over_refusal(
        seeded,
        answer="I'm unable to help with that.",
        verdict=verdict,
        agent_id=agent.id,
    )
    assert record is not None
    assert seeded.query(Finding).filter_by(type="over_refusal").count() == 1


def test_a_justified_refusal_is_not_counted(seeded, agent, boundary):
    verdict = classify_answerability("what will revenue be next year?", boundary)
    assert (
        detect_over_refusal(
            seeded, answer="Data not available.", verdict=verdict, agent_id=agent.id
        )
        is None
    )


def test_over_refusal_never_blocks(seeded, enforcer, agent):
    """This side of the control produces findings only. Blocking a refusal would mean
    forcing an answer, which is worse than either failure."""
    declare_boundary(
        seeded, agent_id=agent.id, answerable_types=[FACT, AGGREGATE, PROCEDURE], mode="enforce"
    )
    result, response = enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "how many open orders are there?"}],
        model="echo-1",
    )
    assert not result.blocked


# ---------------------------------------------------------------------------
# F1.4 post-flight, F1.6 completeness
# ---------------------------------------------------------------------------


def test_a_record_only_agent_that_answers_with_a_forecast_is_flagged(seeded, boundary):
    verdict = classify_answerability("what was revenue in 2024?", boundary)
    breaches = verify_boundary("Revenue was £4m and will grow to £6m next year.", verdict, boundary)
    assert [b["breach"] for b in breaches] == ["prediction_in_answer"]


def test_a_record_answer_produces_no_breach(seeded, boundary):
    verdict = classify_answerability("what was revenue in 2024?", boundary)
    assert verify_boundary("Revenue was £4m.", verdict, boundary) == []


def test_a_partial_answer_presented_as_complete_is_flagged():
    signal = completeness_signal("Here are the results.", retrieved=3, available=50)
    assert signal["misleading"] is True
    assert "3 of 50" in signal["suggested_caveat"]


def test_declaring_the_partiality_clears_it():
    """The failure is answering as if exhaustive, not being partial."""
    signal = completeness_signal("Based on the 3 documents I found, ...", retrieved=3, available=50)
    assert signal["misleading"] is False


def test_completeness_says_so_when_the_counts_are_unknown():
    assert completeness_signal("Here are the results.")["known"] is False


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_the_answerability_api(client):
    headers = as_user("marcus@example.com")
    created = client.put(
        "/api/answerability/boundary",
        json={
            "agent": "support-triage",
            "systems_of_record": ["CRM"],
            "coverage_months": 24,
            "answerable_types": ["fact", "aggregate"],
            "out_of_scope_topics": ["payroll"],
            "mode": "enforce",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    refused = client.post(
        "/api/answerability/check",
        json={"agent": "support-triage", "question": "what will revenue be next year?"},
        headers=headers,
    ).json()
    assert refused["answerable"] is False and refused["should_abstain"] is True

    allowed = client.post(
        "/api/answerability/check",
        json={"agent": "support-triage", "question": "how many orders are open?"},
        headers=headers,
    ).json()
    assert allowed["answerable"] is True

    one = client.get("/api/answerability/boundaries?agent=support-triage", headers=headers).json()
    assert [b["agent"] for b in one["boundaries"]] == ["support-triage"]
    none = client.get("/api/answerability/boundaries?agent=payments-ops", headers=headers).json()
    assert none["boundaries"] == []
    assert (
        client.get("/api/answerability/boundaries?agent=nope", headers=headers).status_code == 404
    )

    report = client.get("/api/answerability/report", headers=headers).json()
    assert report["boundaries_declared"] == 1 and report["enforcing"] == 1
    assert "payments-ops" in report["agents_without_boundary"]


def test_the_check_endpoint_changes_nothing(client):
    """A dry-run that leaves findings behind is not a dry run."""
    headers = as_user("marcus@example.com")
    client.put(
        "/api/answerability/boundary",
        json={"agent": "support-triage", "answerable_types": ["fact"], "mode": "enforce"},
        headers=headers,
    )
    before = client.get("/api/findings", headers=headers).json()["findings"]
    client.post(
        "/api/answerability/check",
        json={"agent": "support-triage", "question": "what will revenue be?"},
        headers=headers,
    )
    after = client.get("/api/findings", headers=headers).json()["findings"]
    assert len(after) == len(before)


def test_an_unknown_question_type_is_rejected(client):
    response = client.put(
        "/api/answerability/boundary",
        json={"agent": "support-triage", "answerable_types": ["vibes"]},
        headers=as_user("marcus@example.com"),
    )
    assert response.status_code == 400
    assert "vibes" in response.json()["detail"]
