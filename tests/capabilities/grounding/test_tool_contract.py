"""Did the tool answer the question that was asked?

Nothing between the request and the result checked that they matched. The agent asks
for order A-1182, the tool returns A-1183, and every downstream control is satisfied —
the call was authorised, the response is well-formed, and the answer is perfectly
grounded in it. Groundedness is measured against the retrieved context, so an answer
faithfully describing the wrong record scores 1.0, which makes it more dangerous than
an ungrounded one.
"""

from __future__ import annotations

from agentfox.capabilities.grounding.tool_contract import (
    answers_request,
    identifiers,
    requested_fields,
)


def codes(check) -> set[str]:
    return {f.code for f in check.findings}


# --- Wrong subject ---------------------------------------------------------


def test_the_result_being_about_a_different_record_is_the_worst_case():
    """The agent then tells one customer another customer's balance in good faith."""
    check = answers_request(
        "What is the status of order A-1182?",
        {"order": "A-1183", "status": "shipped"},
    )
    assert "subject-mismatch" in codes(check)
    assert check.verdict == "block"


def test_a_result_carrying_no_identifier_at_all_is_unverifiable_not_wrong():
    """A different severity, because it may well be right — there is just no way to
    tell, and saying so is more useful than guessing either way."""
    check = answers_request("What is the status of order A-1182?", {"status": "shipped"})
    finding = next(f for f in check.findings if f.code == "subject-unverifiable")
    assert finding.severity == "medium"


def test_the_matching_record_passes():
    """The false-positive floor."""
    check = answers_request(
        "What is the status of order A-1182?",
        {"order": "A-1182", "status": "shipped"},
    )
    assert check.satisfied
    assert check.verdict == "allow"


def test_identifiers_are_recognised_by_shape_not_by_a_list_of_formats():
    """Every schema invents its own."""
    found = identifiers("order A-1182, ticket #44712, and bob@example.com")
    assert found == {"a-1182", "#44712", "bob@example.com"}


# --- Silent failure --------------------------------------------------------


def test_an_error_inside_a_successful_response_is_caught():
    """The transport succeeded; the call did not. An agent reads the payload, not the
    status."""
    check = answers_request(
        "What is the balance for order A-1182?",
        {"order": "A-1182", "error": "upstream timeout"},
    )
    assert "error-in-successful-response" in codes(check)
    assert check.verdict == "block"


def test_an_error_string_buried_in_a_nested_payload_is_found():
    check = answers_request(
        "Status of A-1182?", {"order": "A-1182", "data": {"detail": "503 unavailable"}}
    )
    assert "error-in-successful-response" in codes(check)


def test_an_empty_result_for_a_question_that_assumes_a_record_is_reported():
    check = answers_request("What is the status of order A-1182?", {"rows": []})
    assert "empty-result-for-a-question-that-presupposes-rows" in codes(check)


def test_an_empty_result_for_an_existence_question_is_a_valid_answer():
    """Nothing in the payload distinguishes these two, so the caller says which it is."""
    check = answers_request(
        "Does A-1182 have any open tickets?", {"rows": []}, presupposes_rows=False
    )
    assert check.satisfied


# --- Over-fetch ------------------------------------------------------------


def test_a_lookup_by_id_that_returns_five_hundred_rows_is_reported():
    """Whether or not the surplus reaches the user, it is now in the context window
    where a later turn can disclose it."""
    check = answers_request(
        "What is the status of order A-1182?",
        {"rows": [{"order": "A-1182", "status": "shipped"} for _ in range(500)]},
    )
    finding = next(f for f in check.findings if f.code == "over-fetch")
    assert finding.severity == "high"


def test_a_declared_expected_count_overrides_the_inference():
    check = answers_request(
        "List the items on order A-1182",
        {"rows": [{"order": "A-1182", "status": "x"} for _ in range(8)]},
        expect_rows=10,
    )
    assert "over-fetch" not in codes(check)


# --- Missing fields --------------------------------------------------------


def test_a_field_the_request_asked_for_and_the_result_lacks_is_reported():
    """The agent will answer about the rest and the omission will not appear anywhere
    in the answer."""
    check = answers_request(
        "Give me the balance and due date for A-1182",
        {"order": "A-1182", "balance": 30},
    )
    assert "missing-requested-field" in codes(check)


def test_field_checks_are_suppressed_once_the_call_has_already_failed():
    """A second finding about the same event. A check that reports twice is a check
    people learn to skim."""
    check = answers_request(
        "Give me the balance and due date for A-1182",
        {"order": "A-1182", "error": "timeout"},
    )
    assert codes(check) == {"error-in-successful-response"}


def test_requested_fields_are_read_from_the_request_text():
    assert requested_fields("give me the balance and the due date") == {"balance", "due date"}


def test_a_result_carrying_everything_asked_for_is_silent():
    check = answers_request(
        "Give me the balance and due date for A-1182",
        {"order": "A-1182", "balance": 30, "due_date": "2026-09-01"},
    )
    assert check.satisfied
