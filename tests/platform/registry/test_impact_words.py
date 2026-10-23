"""`infer_impact` reads a tool's name as words and verb phrases, never substrings.

The cases are the onboarding audit's: names whose old reading was wrong because a
substring matched ("pay" in ``display``), because a noun read as a verb (``get_post``),
or because a hand-off to a person read as a money transfer.
"""

from __future__ import annotations

import pytest

from agentfox.platform.registry.impact import actions, handoff, infer_impact, tokens


@pytest.mark.parametrize(
    ("name", "impact"),
    [
        ("search_docs", "read"),
        ("create_ticket", "write"),
        ("delete_record", "irreversible"),
        ("update_seat", "write"),
        ("cancel_flight", "write"),
        ("book_new_flight", "write"),
        ("start_return", "write"),
        ("issue_compensation", "write"),
        ("add_note", "write"),
        ("notebook_search", "read"),
        ("display_seat_map", "read"),
        ("get_post", "read"),
        ("get_refund_status", "read"),
        ("get_sender", "read"),
        ("transfer_to_human", "write"),
        ("send_email", "irreversible"),
        ("tickets_close", "write"),
        ("mcp__github__create_issue", "write"),
    ],
)
def test_plain_reading(name, impact):
    assert infer_impact(name) == impact


@pytest.mark.parametrize(
    ("name", "impact"),
    [
        ("issue_refund", "irreversible"),
        ("list_and_refund", "irreversible"),
        ("fetch_and_email_report", "irreversible"),
        ("cancel_flight", "irreversible"),
        ("mcp:billing/charge_card", "irreversible"),
        # A word that sounds like money, inside another word or read, is not a payment.
        ("display_seat_map", "read"),
        ("get_payment_status", "read"),
        ("read_customer_record", "read"),
        # A chat handed to a person is not a transfer of money.
        ("transfer_to_human", "write"),
        ("transfer_funds", "irreversible"),
    ],
)
def test_cautious_reading(name, impact):
    assert infer_impact(name, cautious=True) == impact


def test_a_description_counts_only_verbs_that_cannot_be_nouns():
    assert infer_impact("lookup", {"description": "Returns the latest update"}) == "read"
    assert infer_impact("lookup", {"description": "Look up a blog post"}) == "read"
    assert infer_impact("sync", {"description": "Delete stale rows"}) == "irreversible"


def test_words_and_phrases():
    assert tokens("readCustomerRecord") == ["read", "customer", "record"]
    assert actions(tokens("get_refund_status")) == []
    assert actions(tokens("list_and_refund")) == ["refund"]
    assert actions(tokens("issue_compensation")) == ["issue"]
    assert handoff(tokens("transfer_to_human")) and handoff(tokens("escalate_to_agent"))
    assert not handoff(tokens("transfer_funds"))
