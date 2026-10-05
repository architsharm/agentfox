"""F6 — commitment, disclosure and liability.

Low frequency, high severity, and the first instance is a lawsuit rather than a bug
report. Air Canada was held to a refund policy its chatbot invented; that is the shape
of every failure here — fluent, on-topic, grounded in the conversation, and creating an
obligation nobody authorised.

Each section pairs the binding form with the near-identical non-binding one, because
the whole difficulty is that they differ by hedging alone.
"""

from __future__ import annotations

import pytest

from agentfox.grounding.commitments import (
    FOUR_FIFTHS,
    MIN_GROUP_SIZE,
    adverse_action_risk,
    assess_liability,
    check_disclosure,
    detect_commitments,
    disclosure_required,
    fairness_probe,
)


def kinds(commitments) -> set[str]:
    return {c.kind for c in commitments}


# --- Binding commitments (F6.1) --------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("I guarantee you will receive a full replacement.", "promise"),
        ("Your refund has been approved.", "decision"),
        ("We'll credit your account by Friday.", "undertaking"),
        ("You're entitled to a full refund under our policy.", "entitlement"),
        ("Your total will be $49.99 including delivery.", "quote"),
    ],
)
def test_each_way_of_binding_the_company_is_caught(text, kind):
    assert kind in kinds(detect_commitments(text))


@pytest.mark.parametrize(
    "text",
    [
        "Refunds are usually approved within two days.",
        "I can't guarantee a refund; it's subject to review by the claims team.",
        "We aim to credit your account within a week.",
        "The price is approximately $50, but I'd confirm with the sales team.",
        "You may be eligible for a refund if approved.",
        "Thanks for getting in touch — let me look into that for you.",
    ],
)
def test_the_hedged_twin_of_every_commitment_is_not_one(text):
    """This is the whole difficulty: the binding and non-binding forms differ by
    hedging alone, and a check that cannot tell them apart is unusable."""
    assert detect_commitments(text) == []


def test_a_disclaimer_in_one_sentence_does_not_soften_a_promise_in_another():
    """Hedging is evaluated per sentence.

    Treating the whole message as one context is how a real commitment hides behind
    boilerplate it has nothing to do with.
    """
    text = (
        "Please note that all outcomes are generally subject to review. "
        "Your refund has been approved and we'll credit your account today."
    )
    assert detect_commitments(text)


def test_an_authorised_commitment_is_not_a_finding():
    """The agent genuinely held the authority to approve this."""
    assert detect_commitments("Your refund has been approved.", authorised=True) == []


def test_ordinary_helpful_prose_binds_nothing():
    """The false-positive floor. An agent that cannot say anything reassuring is an
    agent nobody deploys."""
    assert (
        detect_commitments(
            "I'm sorry to hear about the delay. Let me check the status of your order and "
            "explain what the usual process looks like from here."
        )
        == []
    )


# --- AI disclosure (F6.3) --------------------------------------------------


def test_a_human_on_a_conversational_channel_is_owed_a_disclosure():
    """EU AI Act Article 50 has applied since August 2026."""
    assert check_disclosure("Hi! How can I help?", channel="chat").breach


def test_saying_so_satisfies_it():
    assert not check_disclosure("Hi, I'm an AI assistant — how can I help?", channel="chat").breach


def test_disclosure_is_per_conversation_not_per_message():
    assert not check_disclosure("Sure, one moment.", already_disclosed=True).breach


@pytest.mark.parametrize(
    ("channel", "counterparty"),
    [("batch", "service"), ("internal", "service"), ("chat", "service")],
)
def test_no_human_means_no_obligation(channel, counterparty):
    assert not disclosure_required(channel=channel, counterparty=counterparty).required


def test_obviousness_must_be_declared_rather_than_inferred():
    """The Article 50 exemption is for cases obvious from context.

    A default that silently assumes obviousness is a default that never discloses, so
    somebody has to set it.
    """
    assert disclosure_required(channel="chat").required
    assert not disclosure_required(channel="chat", exempt=True).required


# --- Adverse action (F6.4) -------------------------------------------------


def test_a_decline_with_no_reason_is_a_breach():
    action = adverse_action_risk("declined", reasons=[], domain="lending")
    assert not action.compliant
    assert action.verdict == "block", "statutory domains block rather than escalate"


def test_boilerplate_is_treated_as_no_reason():
    """It satisfies a field and tells the applicant nothing they can act on, which is
    precisely what the statute exists to prevent."""
    action = adverse_action_risk(
        "declined", reasons=["does not meet our criteria"], domain="lending"
    )
    assert not action.compliant
    assert "boilerplate" in action.findings[0]


def test_a_reason_that_was_never_communicated_is_caught():
    """A message can read as an explanation while the real basis was never given."""
    action = adverse_action_risk(
        "declined",
        reasons=["credit utilisation above ninety percent"],
        domain="lending",
        text="Unfortunately we cannot proceed with your application at this time.",
    )
    assert not action.compliant
    assert "actual basis" in action.findings[-1]


def test_a_specific_reason_that_was_communicated_passes():
    """The false-positive floor for adverse action."""
    action = adverse_action_risk(
        "declined",
        reasons=["debt-to-income ratio above 45 percent"],
        domain="lending",
        text="Your application was declined because your debt-to-income ratio is above "
        "our limit of 45 percent.",
    )
    assert action.compliant
    assert action.verdict == "allow"


def test_a_positive_outcome_carries_no_reason_obligation():
    assert adverse_action_risk("approved", reasons=[], domain="lending").compliant


def test_an_unregulated_domain_escalates_rather_than_blocks():
    action = adverse_action_risk("declined", reasons=[], domain="loyalty points")
    assert not action.compliant
    assert action.verdict == "escalate"


# --- Fairness (F6.5) -------------------------------------------------------


def test_a_disparity_below_four_fifths_is_reported():
    result = fairness_probe({"a": (80, 100), "b": (40, 100)})
    assert result.investigate
    assert result.ratio == pytest.approx(0.5)
    assert result.disadvantaged == ["b"]


def test_the_finding_is_grounds_to_investigate_not_a_verdict():
    """A selection-rate ratio below 0.8 has been the enforcement trigger since 1978.

    It is not proof of discrimination, and a tool that reports it as one will be
    disbelieved the first time a legitimate factor explains it.
    """
    explanation = fairness_probe({"a": (80, 100), "b": (40, 100)}).explain()
    assert "not a finding of discrimination" in explanation


def test_a_small_sample_says_nothing_rather_than_raising_an_alarm():
    """A disparity computed on ten applicants is noise, and alarms nobody can act on
    train people to dismiss the ones they could."""
    result = fairness_probe({"a": (8, 10), "b": (4, 10)})
    assert not result.investigate
    assert set(result.underpowered) == {"a", "b"}


def test_raw_decision_records_are_accepted_as_well_as_counts():
    records = (
        [{"group": "a", "selected": True} for _ in range(80)]
        + [{"group": "a", "selected": False} for _ in range(20)]
        + [{"group": "b", "selected": True} for _ in range(40)]
        + [{"group": "b", "selected": False} for _ in range(60)]
    )
    assert fairness_probe(records).ratio == pytest.approx(0.5)


def test_comparable_rates_do_not_trigger():
    """The false-positive floor for fairness."""
    result = fairness_probe({"a": (80, 100), "b": (75, 100)})
    assert not result.investigate
    assert result.ratio > FOUR_FIFTHS


def test_a_single_group_cannot_be_compared_to_anything():
    assert not fairness_probe({"a": (80, MIN_GROUP_SIZE + 1)}).investigate


# --- Aggregate -------------------------------------------------------------


def test_a_commitment_dominates_a_disclosure_breach():
    """Both are wrong; only one of them creates an obligation."""
    result = assess_liability("Your refund has been approved.", channel="chat")
    assert result.verdict == "block"
    assert result.disclosure.breach


def test_a_clean_message_passes_every_gate():
    result = assess_liability(
        "I'm an AI assistant. Refunds are usually processed within two days, and I've "
        "passed your request to the claims team.",
        channel="chat",
    )
    assert result.verdict == "allow"
    assert result.commitments == []
    assert not result.disclosure.breach
