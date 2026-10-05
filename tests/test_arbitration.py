"""Which source answers, and when to stop and ask.

Provenance ranks retrieved documents and conflict detection notices when two chunks
disagree — both after the fact, on text already fetched. Neither governs the decision
that determines everything downstream: which system the agent went to first.

The tests below are built around the case every product in this space gets wrong. Two
sources answer, the values differ, and the system picks one. Picking is the mistake.
"""

from __future__ import annotations

from agentfox.grounding.arbitration import (
    Reading,
    SourceAuthority,
    arbitrate,
    confirmation_for_ambiguous_source,
    materially_differ,
)

SOURCES = [
    SourceAuthority("ledger", "system_of_record", ("balance",), max_age_seconds=60),
    SourceAuthority("crm", "approved", ("balance",)),
    SourceAuthority("warehouse", "unverified", ("balance",), max_age_seconds=3600),
]


def codes(result) -> set[str]:
    return {f.code for f in result.findings}


# --- Using a lesser source -------------------------------------------------


def test_answering_from_a_lesser_source_while_the_ledger_was_reachable_is_blocked():
    """The number is twelve hours old, the answer is grounded, cited and wrong."""
    result = arbitrate("balance", [Reading("warehouse", 4000, 100)], sources=SOURCES)
    assert "authoritative-source-bypassed" in codes(result)
    assert result.verdict == "block"


def test_the_system_of_record_answering_is_silent():
    """The false-positive floor."""
    result = arbitrate("balance", [Reading("ledger", 4000)], sources=SOURCES)
    assert result.verdict == "allow"
    assert result.chosen == "ledger"


def test_a_source_past_its_freshness_limit_is_reported():
    result = arbitrate("balance", [Reading("ledger", 4000, 900)], sources=SOURCES)
    assert "stale-reading" in codes(result)


def test_a_source_with_no_declared_standing_cannot_be_weighed():
    result = arbitrate(
        "balance", [Reading("ledger", 4000), Reading("scratchpad", 4000)], sources=SOURCES
    )
    assert "undeclared-source" in codes(result)


# --- Disagreement, and the confirmation step -------------------------------


def test_a_material_disagreement_asks_rather_than_picks():
    """This is the whole argument. A disagreement between two systems is information,
    not a ranking problem."""
    result = arbitrate("balance", [Reading("ledger", 4000), Reading("crm", 4310)], sources=SOURCES)
    assert result.verdict == "confirm"
    assert result.confirmation is not None
    assert "ledger: 4000" in result.confirmation.options
    assert "crm: 4310" in result.confirmation.options


def test_the_confirmation_carries_its_reason_so_it_can_be_replayed():
    """A confirmation nobody can reconstruct afterwards is a pause, not a control."""
    result = arbitrate("balance", [Reading("ledger", 4000), Reading("crm", 4310)], sources=SOURCES)
    payload = result.confirmation.to_json()
    assert payload["because"]
    assert payload["topic"] == "balance"


def test_confirmation_can_be_downgraded_but_never_to_allow():
    """A setting that made the disagreement disappear would be a setting for producing
    confident wrong answers."""
    result = arbitrate(
        "balance",
        [Reading("ledger", 4000), Reading("crm", 4310)],
        sources=SOURCES,
        require_confirmation=False,
    )
    assert result.confirmation is None
    assert result.verdict == "block"


def test_a_rounding_difference_is_not_a_disagreement():
    """Reporting a penny on four thousand pounds would train people to dismiss the pair
    that matters."""
    result = arbitrate(
        "balance", [Reading("ledger", 4000.00), Reading("crm", 4000.01)], sources=SOURCES
    )
    assert result.verdict == "allow"


def test_agreement_between_sources_needs_no_question():
    result = arbitrate("balance", [Reading("ledger", 4000), Reading("crm", 4000)], sources=SOURCES)
    assert result.confirmation is None
    assert result.verdict == "allow"


def test_material_difference_is_relative_not_absolute():
    assert not materially_differ(4000.00, 4000.01)
    assert materially_differ(1.00, 1.50)


def test_a_text_difference_counts_as_disagreement():
    """Two systems of record differing on what the record says is a genuine conflict,
    and this deliberately does not try to decide it is only a paraphrase."""
    assert materially_differ("active", "suspended")
    assert not materially_differ("Active", "  active ")


# --- Asking before the call ------------------------------------------------


def test_a_tie_at_the_top_tier_is_asked_before_anything_is_queried():
    """The cheapest place to resolve this is in front of the tool call, not after two
    of them have returned different numbers."""
    tied = [
        SourceAuthority("ledger_eu", "system_of_record", ("balance",)),
        SourceAuthority("ledger_us", "system_of_record", ("balance",)),
    ]
    step = confirmation_for_ambiguous_source("balance", tied)
    assert step is not None
    assert step.options == ["ledger_eu", "ledger_us"]


def test_one_clear_winner_is_not_asked_about():
    """Asking anyway is how a confirmation step becomes a dialog people click through."""
    assert confirmation_for_ambiguous_source("balance", SOURCES) is None


def test_a_topic_no_source_covers_raises_nothing():
    assert confirmation_for_ambiguous_source("weather", SOURCES) is None
