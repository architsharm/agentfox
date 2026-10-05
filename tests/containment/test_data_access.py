"""Proving a tool's query touched only the caller's rows.

Capability scoping asks whether the agent may call `db.query`. Action analysis asks
whether the statement is destructive. Both pass, cleanly, on `SELECT * FROM orders` run
by a support agent acting for one customer — nothing is destructive, the tool was
granted, the arguments are untainted, and the result is every customer's orders.

The test that matters most is not the missing WHERE. It is the one that is present and
wrong: a scope predicate bound to an id the model chose.
"""

from __future__ import annotations

import pytest

from agentfox.containment.data_access import (
    ReferenceTable,
    ScopeRule,
    analyse_access,
    connection_risk,
)

RULES = [
    ScopeRule("orders", "customer_id", "customer_id", restricted_columns=("internal_notes",)),
    ScopeRule("customers", "id", "customer_id"),
]
REFERENCE = [ReferenceTable("currencies")]
ME = {"customer_id": "C-1"}


def check(sql, principal=ME):
    return analyse_access(sql, principal=principal, rules=RULES, reference=REFERENCE)


def codes(analysis) -> set[str]:
    return {f.code for f in analysis.findings}


# --- The scope that is present and wrong -----------------------------------


def test_a_scope_bound_to_a_model_chosen_id_is_horizontal_privilege_escalation():
    """This passes every "is the query filtered" test anyone writes.

    A model asked to look up "the customer's orders" will put an id there that it read
    out of a document, a previous turn, or an injected instruction.
    """
    analysis = check("SELECT id FROM orders WHERE customer_id = 'C-4471'")
    assert "scope-bound-to-literal" in codes(analysis)
    assert analysis.verdict == "block"


def test_a_literal_that_happens_to_be_the_caller_is_still_reported():
    """Correct this time by coincidence. The runtime did not put it there, and the
    model that chose it can choose differently on the next turn."""
    analysis = check("SELECT id FROM orders WHERE customer_id = 'C-1'")
    assert "scope-literal-not-bound" in codes(analysis)
    assert not analysis.proven


def test_with_no_principal_no_literal_can_be_shown_to_be_the_caller():
    analysis = check("SELECT id FROM orders WHERE customer_id = 'C-1'", principal=None)
    assert "scope-bound-to-literal" in codes(analysis)


def test_a_scope_predicate_under_an_or_constrains_nothing():
    """It reads as scoped and returns everything."""
    analysis = check("SELECT id FROM orders WHERE customer_id = :me OR 1=1")
    assert "scope-defeated-by-or" in codes(analysis)
    assert analysis.verdict == "block"


def test_scoping_to_another_column_is_not_scoping_to_the_caller():
    analysis = check("SELECT id FROM orders WHERE customer_id = account_manager_id")
    assert "unscoped-table" in codes(analysis)


# --- The scope that is absent ----------------------------------------------


def test_an_unscoped_read_of_a_per_customer_table_is_blocked():
    analysis = check("SELECT id, total FROM orders")
    assert "unscoped-table" in codes(analysis)
    assert analysis.verdict == "block"


def test_an_unscoped_aggregate_is_named_as_running_across_every_customer():
    """A total is worse than a row: it discloses everyone at once and looks like one
    number."""
    analysis = check("SELECT SUM(total) FROM orders")
    finding = next(f for f in analysis.findings if f.code == "unscoped-table")
    assert finding.evidence["aggregate"] is True
    assert "every one of them" in finding.detail


def test_a_join_that_reaches_a_second_scoped_table_needs_its_own_predicate():
    """Scoping the table you thought about does not scope the one you joined to."""
    analysis = check(
        "SELECT o.id, c.email FROM orders o JOIN customers c ON c.id = o.customer_id "
        "WHERE o.customer_id = :me"
    )
    assert "customers" in analysis.unscoped
    assert analysis.verdict == "block"


def test_a_fully_scoped_join_passes():
    analysis = check(
        "SELECT o.id, c.email FROM orders o JOIN customers c ON c.id = o.customer_id "
        "WHERE o.customer_id = :me AND c.id = :me"
    )
    assert analysis.proven
    assert set(analysis.scoped) == {"orders", "customers"}


# --- Declarations ----------------------------------------------------------


def test_a_reference_table_needs_no_scoping():
    """The false-positive floor: currencies belong to nobody."""
    analysis = check(
        "SELECT o.id FROM orders o JOIN currencies cu ON cu.code = o.currency "
        "WHERE o.customer_id = :me"
    )
    assert analysis.proven


def test_an_undeclared_table_is_reported_rather_than_assumed_safe():
    """Treating "no rule" as "safe" is how a new table joins the schema and quietly
    becomes readable by everyone."""
    analysis = check("SELECT id FROM audit_log WHERE 1=1")
    assert "undeclared-table" in codes(analysis)
    assert "audit_log" in analysis.undeclared
    # Standard strictness (the default): reported, not refused outright.
    assert analysis.verdict == "escalate"


def test_strict_mode_promotes_an_undeclared_table_to_a_block():
    """A deployment that wants "no undeclared table is ever queried, period" opts
    into that outright, rather than the standard "a human should look" default."""
    analysis = analyse_access(
        "SELECT id FROM audit_log WHERE 1=1",
        principal=ME,
        rules=RULES,
        reference=REFERENCE,
        strictness="strict",
    )
    assert "undeclared-table" in codes(analysis)
    assert analysis.verdict == "block"


def test_a_restricted_column_is_withheld_even_on_the_callers_own_row():
    analysis = check("SELECT internal_notes FROM orders WHERE customer_id = :me")
    assert "restricted-column" in codes(analysis)


def test_select_star_is_caught_as_reaching_the_restricted_columns():
    analysis = check("SELECT * FROM orders WHERE customer_id = :me")
    assert "select-star-over-restricted" in codes(analysis)


# --- Failing closed --------------------------------------------------------


def test_an_unparseable_statement_cannot_be_proven_and_is_refused():
    """A statement we cannot read is a statement we cannot prove is scoped."""
    analysis = check("SELCT nonsense FROM ((((")
    assert not analysis.parsed
    assert analysis.verdict == "block"


def test_proven_is_a_positive_claim_not_an_absence_of_alarms():
    """An absence of evidence does not establish that the query is scoped."""
    assert not check("SELECT id FROM orders").proven
    assert check("SELECT id FROM orders WHERE customer_id = :me").proven


# --- Connection identity ---------------------------------------------------


@pytest.mark.parametrize("role", ["postgres", "root", "rds_superuser"])
def test_a_superuser_connection_removes_the_floor_under_a_mistake(role):
    """A perfect scope predicate on a superuser connection is one prompt injection away
    from irrelevant."""
    finding = connection_risk(role, environment="production")
    assert finding is not None
    assert finding.severity == "critical"


def test_a_least_privilege_role_reports_nothing():
    assert connection_risk("app_readonly") is None


def test_the_same_role_is_less_severe_outside_production():
    assert connection_risk("postgres", environment="staging").severity == "high"
