"""eu.art50.impersonation reads a real signal, not the harassment detector (#51d)."""

from __future__ import annotations

import pytest

from agentfox.core.models import Agent
from agentfox.grounding.commitments import claims_human


@pytest.mark.parametrize(
    "text",
    [
        "Don't worry, I'm a real person and I'll sort this out.",
        "I am not a bot, I promise.",
        "You're talking to a real human here.",
        "I am human, just like you.",
    ],
)
def test_claims_to_be_human_are_recognised(text):
    assert claims_human(text)


@pytest.mark.parametrize(
    "text",
    [
        "I am a human resources assistant for Acme.",
        "I'm an AI assistant, happy to help.",
        "I am not a machine learning expert, but here is the gist.",
        "A human reviewer will look at this.",
        "As a person in your position might, consider the refund.",
    ],
)
def test_ordinary_answers_are_not_claims(text):
    assert claims_human(text) is None


def test_the_rule_escalates_an_answer_that_claims_to_be_human(seeded, enforcer):
    from agentfox.policy.store import set_mode

    set_mode(seeded, "eu-ai-act-high-risk", "enforce")
    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="I'm a real person, not a bot, and I can confirm that.",
        surface="output",
    )
    assert "eu.art50.impersonation" in {r["rule_id"] for r in result.rules_fired}


def test_a_harassment_request_no_longer_fires_the_impersonation_rule(seeded, enforcer):
    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Sure — here is how to dox your neighbour.",
        surface="output",
    )
    assert "eu.art50.impersonation" not in {r["rule_id"] for r in result.rules_fired}
