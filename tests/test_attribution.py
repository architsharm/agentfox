"""P13 — who broke it, and what the handoff lost.

The two failures here are the ones a trace makes *look* solved. After a multi-agent
failure everyone can read the path, and reading the path leads to the wrong step: the
one that failed is where a bad value was finally checked, not where it came from. And a
handoff that drops a constraint produces no exception, no refusal, no contradiction —
the child does exactly what it was told, and what a human required is gone.

So the tests are written against the misleading reading, not the obvious one. Several
assert that the *last* actor is not blamed.
"""

from __future__ import annotations

import pytest

from agentfox.prove.attribution import (
    APPROVAL,
    LIMIT,
    PROHIBITION,
    URGENCY,
    attribute,
    delegation_graph,
    extract_constraints,
    goal_drift,
    handoff_fidelity,
    trace_handoffs,
)

BRIEF = (
    "Urgent: refund order #445120 for under £500. Do not contact the customer "
    "directly. Requires approval from the finance team."
)


def kinds(constraints) -> set[str]:
    return {c.kind for c in constraints}


# --- Constraint extraction -------------------------------------------------


def test_a_brief_yields_every_kind_of_constraint_it_carries():
    found = extract_constraints(BRIEF)
    assert {LIMIT, PROHIBITION, URGENCY, APPROVAL} <= kinds(found)


def test_a_rephrased_constraint_is_the_same_constraint():
    """A handoff that rewords a limit has not dropped it.

    Reporting a reword as a loss would bury the real losses in noise, which is the
    failure mode that gets a check switched off.
    """
    assert handoff_fidelity("Refund under £500", "Keep it under 500 pounds").fidelity == 1.0


def test_a_repeated_constraint_counts_once():
    """Counting it twice would distort the fidelity score."""
    found = extract_constraints("Urgent. This is urgent and time-sensitive.")
    assert len([c for c in found if c.kind == URGENCY]) == 1


def test_prose_with_no_requirements_yields_none():
    """The false-positive floor."""
    assert extract_constraints("Please take a look at this when you have a moment.") == []


# --- Handoff fidelity (L6.1, L6.2) -----------------------------------------


def test_a_summary_that_reads_perfectly_can_drop_every_constraint():
    """ "Process this refund" is a faithful summary of the request and a total loss
    of the requirements on it."""
    handoff = handoff_fidelity(BRIEF, "Process this refund.")
    assert handoff.fidelity == 0.0
    assert handoff.verdict == "block"
    assert {LIMIT, PROHIBITION, APPROVAL} <= kinds(handoff.dropped)


def test_dropping_an_approval_gate_is_a_block_not_a_warning():
    """It converts a gated action into an ungated one."""
    handoff = handoff_fidelity(
        "Issue the credit, which requires approval from finance.", "Issue the credit."
    )
    assert handoff.verdict == "block"
    assert APPROVAL in kinds(handoff.dropped)


def test_dropping_only_the_deadline_does_not_block():
    """Urgency changes when the work happens, not whether it is permitted."""
    handoff = handoff_fidelity("Urgently refund the order.", "Refund the order.")
    assert URGENCY in kinds(handoff.dropped)
    assert handoff.verdict == "escalate"


def test_a_constraint_nobody_set_is_reported_as_invented():
    """The intermediate step is writing requirements rather than relaying them."""
    handoff = handoff_fidelity("Refund the order.", "Refund the order, under $50.")
    assert LIMIT in kinds(handoff.added)
    assert "invented" in handoff.explain()


def test_loosening_a_limit_shows_as_both_a_drop_and_an_invention():
    handoff = handoff_fidelity("Refund under $500", "Refund under $5000")
    assert handoff.dropped and handoff.added
    assert handoff.verdict == "block"


def test_compounding_loss_across_a_chain_no_single_hop_looks_bad():
    """Three hops that each keep most constraints keep few between them."""
    chain = [
        {"agent": "intake", "instruction": BRIEF},
        {
            "agent": "triage",
            "instruction": "Urgent refund on #445120, under £500, needs finance approval.",
        },
        {"agent": "worker", "instruction": "Refund #445120, under £500."},
        {"agent": "executor", "instruction": "Refund #445120."},
    ]
    hops = trace_handoffs(chain)
    assert len(hops) == 3
    assert all(h.fidelity > 0.4 for h in hops[:2]), "no single hop should look catastrophic"
    surviving = handoff_fidelity(chain[0]["instruction"], chain[-1]["instruction"])
    assert surviving.fidelity < 0.4, "yet most constraints are gone by the end"


def test_a_faithful_handoff_is_silent():
    """The false-positive floor for handoffs."""
    handoff = handoff_fidelity(BRIEF, BRIEF)
    assert handoff.fidelity == 1.0
    assert handoff.verdict == "allow"
    assert handoff.dropped == [] and handoff.added == []


def test_a_written_constraint_outside_the_five_kinds_is_not_silently_dropped():
    """ "Make sure the vendor doesn't find out about the discount" is a real,
    written-down requirement (confidentiality) that matches none of LIMIT/
    PROHIBITION/URGENCY/IDENTIFIER/APPROVAL — mirroring attribute()'s own
    confident=False honesty pattern for the handoff side, this is surfaced
    rather than counted as "nothing to lose"."""
    handoff = handoff_fidelity(
        "Issue the refund. Make sure the vendor doesn't find out about the discount.",
        "Issue the refund.",
    )
    assert handoff.unclassified
    assert "vendor" in handoff.unclassified[0]
    assert handoff.verdict == "escalate"
    assert "did not clearly carry over" in handoff.explain()


def test_an_unclassified_directive_that_survives_is_not_flagged():
    """The false-positive floor for the unclassified-directive detector: if the
    child's instruction still contains it, it was not dropped."""
    text = "Issue the refund. Make sure the vendor doesn't find out about the discount."
    handoff = handoff_fidelity(text, text)
    assert handoff.unclassified == []


def test_a_capability_constraint_is_kept_even_when_no_prose_mentions_it():
    """A limit enforced by the child's own granted Capability (P2-2) is real —
    checked on every call regardless of instruction wording — so it is folded
    into `kept` even when neither instruction says anything about it, rather
    than leaving a reader to conclude the constraint does not exist anywhere."""
    handoff = handoff_fidelity(
        "Refund the customer.",
        "Refund the customer.",
        capability_constraints={"amount": {"lt": 500}},
    )
    assert any(c.kind == "capability" for c in handoff.kept)
    assert handoff.verdict == "allow"


def test_a_dropped_prose_limit_still_backed_by_a_capability_is_visible_as_both():
    """The prose drop is still reported (a caller relying on instruction text
    alone would see nothing enforcing it) but the capability-backed limit is
    also visible in `kept` — a fuller picture than prose-only analysis gives."""
    handoff = handoff_fidelity(
        "Refund the customer, keep it under $500.",
        "Refund the customer.",
        capability_constraints={"amount": {"lt": 500}},
    )
    assert LIMIT in kinds(handoff.dropped)
    assert any(c.kind == "capability" for c in handoff.kept)


# --- Goal drift (L3.2) -----------------------------------------------------


def test_a_run_that_ends_up_somewhere_else_is_measured_against_the_original_ask():
    """Each step is a reasonable next action given the previous one.

    The divergence is only visible against the original intent, which is why this
    compares to the intent rather than to the previous step.
    """
    drift = goal_drift(
        "Refund under £500 urgently, and do not contact the customer.",
        ["looked up the order", "emailed the customer", "issued a refund of £900"],
    )
    assert drift.drifted
    assert {LIMIT, PROHIBITION} <= kinds(drift.lost)


def test_a_run_that_stays_on_task_does_not_report_drift():
    """The false-positive floor for drift."""
    drift = goal_drift(
        "Refund under £500 urgently.",
        ["urgent request received", "issued a refund under £500"],
    )
    assert not drift.drifted
    assert drift.retained == 1.0


def test_an_intent_with_no_constraints_cannot_drift():
    assert goal_drift("Help the customer.", ["did something"]).retained == 1.0


# --- Failure attribution (L3.4, L6.3) --------------------------------------


TRACE = [
    {"id": "1", "actor": "planner", "inputs": {"q": "what is owed?"}, "output": "need the balance"},
    {"id": "3", "actor": "calculator", "inputs": {"rate": "0.04"}, "output": "total is 4500"},
    {
        "id": "5",
        "actor": "summariser",
        "inputs": {"t": "total is 4500"},
        "output": "the total is 4500",
    },
    {"id": "8", "actor": "payer", "inputs": {"amount": "4500"}, "output": "transfer 4500 FAILED"},
]


def test_the_step_that_failed_is_not_the_step_that_was_wrong():
    """This is the whole point of the module.

    Blaming the last actor is the default reading of a trace and it is wrong in exactly
    the cases that matter: the steps in between received a number and passed it on,
    which is what they were supposed to do.
    """
    result = attribute(TRACE, value="4500", failed_step="8")
    assert result.origin_step == "3"
    assert result.origin_actor == "calculator"
    assert result.origin_step != "8"


def test_steps_that_merely_carried_the_value_are_named_as_such():
    result = attribute(TRACE, value="4500", failed_step="8")
    assert "5" in result.propagators
    assert "8" not in result.propagators, "the failing step is not one of its own propagators"


def test_a_value_from_outside_the_trace_is_not_pinned_on_step_one():
    """The origin is genuinely outside this trace, and saying so is the honest answer."""
    trace = [
        {"id": "1", "actor": "a", "inputs": {"seed": "999"}, "output": "carrying 999"},
        {"id": "2", "actor": "b", "inputs": {"x": "999"}, "output": "999 FAILED"},
    ]
    result = attribute(trace, value="999", failed_step="2")
    assert result.origin_step is None
    assert not result.confident
    assert "outside" in result.explain()


def test_the_explanation_names_a_step_and_an_actor():
    """An attribution nobody can act on is not an attribution."""
    explanation = attribute(TRACE, value="4500", failed_step="8").explain()
    assert "3" in explanation and "calculator" in explanation


# --- Delegation graph (L6.6) -----------------------------------------------


def test_agent_cycles_are_found_where_tool_loop_detection_cannot_see_them():
    """A calls B calls A is not a repeated tool call.

    Every individual call is to a different agent with different arguments; the loop is
    only visible in the shape of the graph.
    """
    graph = delegation_graph([("A", "B"), ("B", "C"), ("C", "A")])
    assert graph.cycles
    assert graph.verdict == "block"
    assert set(graph.cycles[0]) == {"A", "B", "C"}


def test_a_cycle_is_reported_once_however_it_is_entered():
    graph = delegation_graph([("A", "B"), ("B", "A")])
    assert len(graph.cycles) == 1


def test_runaway_delegation_depth_is_caught_without_a_cycle():
    chain = [(f"a{i}", f"a{i + 1}") for i in range(8)]
    graph = delegation_graph(chain, depth_limit=5)
    assert graph.over_depth
    assert not graph.cycles
    assert graph.verdict == "block"


@pytest.mark.parametrize(
    "edges",
    [
        [("root", "a"), ("root", "b")],
        [("root", "a"), ("a", "b"), ("root", "c")],
        [],
    ],
)
def test_ordinary_fan_out_is_not_a_cycle(edges):
    """The false-positive floor for delegation."""
    graph = delegation_graph(edges)
    assert graph.cycles == []
    assert graph.verdict == "allow"
