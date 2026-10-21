"""`classify_tool` on the names the onboarding audit found misread.

* "issue" is a verb at the head of a name (``issue_compensation`` pays out) and a noun
  after a read (``get_issue`` reads what someone wrote);
* a change whose name or description says it pays out moves money (``start_return``,
  ``list_and_refund``); a chat handed to a person (``transfer_to_human``) does not;
* a cancellation or a booking acts irreversibly;
* "email" acts in ``fetch_and_email_report`` and is read in ``read_email``.
"""

from __future__ import annotations

import pytest

from agentfox.capabilities.discovery.exposure import EXFIL, PRIVATE, UNTRUSTED, classify_tool


@pytest.mark.parametrize(
    ("name", "description", "flags", "action"),
    [
        ("issue_compensation", "", {EXFIL}, "move money"),
        ("issue_refund", "", {EXFIL}, "move money"),
        ("list_and_refund", "", {EXFIL}, "move money"),
        (
            "start_return",
            "Create a return request and refund for an order.",
            {EXFIL},
            "move money",
        ),
        ("cancel_flight", "", {EXFIL}, "act on {data}"),
        ("book_new_flight", "", {EXFIL}, "act on {data}"),
        ("fetch_and_email_report", "", {UNTRUSTED, EXFIL}, "send {data} out"),
        ("transfer_to_human", "", set(), None),
        ("notebook_search", "", set(), None),
        ("get_membership_status", "", set(), None),
        ("get_refund_status", "", set(), None),
        ("update_seat", "", set(), None),
    ],
)
def test_audited_names(name, description, flags, action):
    caps = classify_tool(name, description)
    assert caps.flags == flags
    assert caps.action == action


def test_issue_is_read_after_a_read_verb():
    assert {PRIVATE, UNTRUSTED} >= classify_tool("get_issue").flags
    assert UNTRUSTED in classify_tool("list_issues").flags
    assert UNTRUSTED not in classify_tool("issue_compensation").flags


def test_a_money_description_needs_a_change_not_a_read():
    """Mentioning refunds in a read's description is not paying one."""
    assert classify_tool("check_return_eligibility", "Can it be returned for a refund?").flags == (
        set()
    )
