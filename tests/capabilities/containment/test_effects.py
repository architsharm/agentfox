"""F3 — effects that outlive the call.

None of these failures is a bad decision. Every individual call was authorised,
well-formed and correct; the failure is in the arrangement, and no per-call check can
see it. So the tests are written around arrangements: a retry that looks like a new
request, a sequence that cannot be unwound, a harmless update wired to a destructive
downstream.
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentfox.capabilities.containment.effects import (
    EffectLedger,
    Step,
    assess_effects,
    cascade_risk,
    compensation_plan,
    idempotency_key,
    is_external,
)

REFUND = {"order": "A-1", "amount": 50, "request_id": "r1", "timestamp": "2026-01-01"}


def codes(findings) -> set[str]:
    return {f.code for f in findings}


# --- Idempotency (F3.7) ----------------------------------------------------


def test_a_retry_with_fresh_transport_metadata_is_still_the_same_operation():
    """This is the whole mechanism.

    A retry arrives with a new request id and a new timestamp. Including those in the
    key makes every retry look new, which is the failure the key exists to prevent.
    """
    ledger = EffectLedger()
    ledger.record("payments.refund", REFUND)
    retry = dict(REFUND, request_id="r2", timestamp="2026-01-02")
    assert "duplicate-execution" in codes(ledger.check("payments.refund", retry))


def test_a_duplicate_external_effect_is_critical():
    """It cannot be cleaned up quietly — the money has moved."""
    ledger = EffectLedger()
    ledger.record("payments.refund", REFUND)
    finding = next(
        f for f in ledger.check("payments.refund", REFUND) if f.code == "duplicate-execution"
    )
    assert finding.severity == "critical"


def test_a_missing_key_is_the_finding_not_just_the_duplicate():
    """A duplicate is evidence the gap was already exploited; the missing key is the
    gap. It is reported on the first attempt, before anything has gone wrong."""
    ledger = EffectLedger()
    assert "no-idempotency-key" in codes(ledger.check("payments.refund", REFUND))


def test_a_caller_supplied_key_settles_it():
    """Only the caller knows whether two identical refunds are a retry or a customer
    charged twice."""
    ledger = EffectLedger()
    assert ledger.check("payments.refund", REFUND, key="cust-supplied") == []


def test_genuinely_different_arguments_are_not_a_duplicate():
    """The false-positive floor. Two different refunds are two refunds."""
    ledger = EffectLedger()
    ledger.record("payments.refund", REFUND, key="k1")
    other = dict(REFUND, order="A-2")
    assert "duplicate-execution" not in codes(ledger.check("payments.refund", other, key="k2"))


def test_a_read_is_not_an_effect():
    assert EffectLedger().check("db.query", {"q": "select 1"}, effectful=False) == []


def test_the_key_survives_argument_reordering_and_float_formatting():
    """Dict ordering and float formatting both vary between attempts without the
    operation changing, and either one silently defeats the key."""
    assert idempotency_key("t", {"a": 1, "b": 2.0}) == idempotency_key("t", {"b": 2, "a": 1})


def test_the_window_expires_so_the_ledger_does_not_grow_forever():
    ledger = EffectLedger(window_seconds=60)
    start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    ledger.record("payments.refund", REFUND, now=start)
    later = start + dt.timedelta(seconds=120)
    assert "duplicate-execution" not in codes(ledger.check("payments.refund", REFUND, now=later))


@pytest.mark.parametrize("tool", ["payments.refund", "email.send", "orders.ship"])
def test_externally_visible_tools_are_recognised(tool):
    assert is_external(tool)


# --- Compensation (F3.10) --------------------------------------------------


SEQUENCE = [
    Step("email.send", irreversible=True),
    Step("payments.charge", compensator="payments.refund"),
    Step("orders.create", compensator="orders.cancel"),
]


def test_compensations_run_in_reverse_order():
    """A later step may depend on an earlier one, so undoing the earlier one first can
    leave the system in a state the later compensator cannot handle."""
    plan = compensation_plan(SEQUENCE, executed=3)
    assert [s.tool for s in plan.compensations] == ["orders.create", "payments.charge"]


def test_a_step_that_cannot_be_undone_is_named_not_silently_skipped():
    plan = compensation_plan(SEQUENCE, executed=3)
    assert [s.tool for s in plan.unrecoverable] == ["email.send"]
    assert not plan.complete
    assert plan.verdict == "block"


def test_an_irreversible_step_before_a_fallible_one_is_flagged_before_anything_runs():
    """Discovering that step two cannot be undone is much cheaper before step one than
    after step three."""
    plan = compensation_plan(SEQUENCE)
    assert "irreversible-before-fallible" in codes(plan.findings)


def test_the_ordering_hint_puts_the_reversible_work_first():
    """The one structural rule that actually prevents this class of failure.

    A sequence that sends the email and then attempts the charge cannot be unwound when
    the charge fails; the same sequence in the other order can.
    """
    plan = compensation_plan(SEQUENCE)
    assert plan.ordering_hint[-1] == "email.send"


def test_only_the_steps_that_ran_are_compensated():
    plan = compensation_plan(SEQUENCE, executed=2)
    assert [s.tool for s in plan.compensations] == ["payments.charge"]


def test_a_fully_reversible_sequence_needs_no_warning():
    """The false-positive floor for compensation."""
    plan = compensation_plan(
        [
            Step("orders.create", compensator="orders.cancel"),
            Step("payments.charge", compensator="payments.refund"),
        ]
    )
    assert plan.complete
    assert plan.verdict == "allow"
    assert plan.findings == []


def test_missing_a_compensator_is_less_severe_than_being_irreversible():
    """A compensator could be written for the first and never for the second."""
    lacking = compensation_plan([Step("thing.do")], executed=1)
    gone = compensation_plan([Step("email.send", irreversible=True)], executed=1)
    assert lacking.findings[0].severity == "high"
    assert gone.findings[0].severity == "critical"


# --- Cascade (F3.9) --------------------------------------------------------


TRIGGERS = {
    "orders.update": ["events.publish"],
    "events.publish": ["email.send", "db.purge"],
    "db.purge": [],
}


def test_a_harmless_call_that_reaches_a_destructive_one_is_blocked():
    """Blast-radius analysis is statement-local. It can tell you one UPDATE touches one
    row, and has no way to know a trigger on that table publishes an event four
    subscribers act on."""
    cascade = cascade_risk("orders.update", TRIGGERS, destructive=("db.purge",))
    assert "db.purge" in cascade.reached
    assert cascade.verdict == "block"
    assert "cascade-reaches-destructive" in codes(cascade.findings)


def test_a_cascade_whose_only_destructive_tail_is_a_message_escalates():
    """A ticket update that notifies the customer is ordinary work: the message cannot
    be recalled, so a person approves it, but nothing is deleted or moved."""
    cascade = cascade_risk(
        "tickets.update",
        {"tickets.update": ["email.send"]},
        destructive=("email.send",),
        communication=("email.send",),
    )
    assert codes(cascade.findings) == {"cascade-reaches-notification"}
    assert cascade.verdict == "escalate"
    assert cascade.findings[0].severity == "high"


def test_one_destructive_tool_beside_a_message_still_blocks():
    """The split is all-or-nothing: a cascade that sends mail *and* purges a table is
    judged by the purge."""
    cascade = cascade_risk(
        "orders.update",
        TRIGGERS,
        destructive=("email.send", "db.purge"),
        communication=("email.send",),
    )
    assert codes(cascade.findings) == {"cascade-reaches-destructive"}
    assert cascade.findings[0].evidence["destructive"] == ["email.send", "db.purge"]
    assert cascade.verdict == "block"


def test_an_unclassified_irreversible_tool_counts_as_destructive():
    """Never guessed from the name: `email.send` that nobody declared as
    communication is destructive, as it was before the class existed."""
    cascade = cascade_risk(
        "tickets.update", {"tickets.update": ["email.send"]}, destructive=("email.send",)
    )
    assert codes(cascade.findings) == {"cascade-reaches-destructive"}
    assert cascade.verdict == "block"


def test_a_trigger_loop_is_caught():
    cascade = cascade_risk("a", {"a": ["b"], "b": ["a"]})
    assert cascade.cycles == [["a", "b", "a"]]
    assert cascade.verdict == "block"


def test_excessive_fan_out_is_reported():
    triggers = {"root": [f"sub{i}" for i in range(15)]}
    cascade = cascade_risk("root", triggers, fan_out_limit=10)
    assert "cascade-fan-out" in codes(cascade.findings)


def test_depth_beyond_the_limit_is_reported():
    chain = {f"t{i}": [f"t{i + 1}"] for i in range(6)}
    cascade = cascade_risk("t0", chain, depth_limit=3)
    assert "cascade-too-deep" in codes(cascade.findings)


def test_a_tool_that_sets_off_nothing_is_silent():
    """The false-positive floor for cascade."""
    cascade = cascade_risk("db.query", {"db.query": []})
    assert cascade.reached == []
    assert cascade.verdict == "allow"


def test_a_short_declared_cascade_is_allowed():
    cascade = cascade_risk("orders.update", {"orders.update": ["events.publish"]})
    assert cascade.reached == ["events.publish"]
    assert cascade.verdict == "allow"


# --- Aggregate -------------------------------------------------------------


def test_the_aggregate_takes_the_worst_of_the_three():
    ledger = EffectLedger()
    args = {"order": "A-1"}
    ledger.record("orders.update", args)
    result = assess_effects(
        "orders.update",
        args,
        ledger=ledger,
        steps=SEQUENCE,
        triggers=TRIGGERS,
        destructive=("db.purge",),
    )
    assert result.verdict == "block"
    assert {"duplicate-execution", "no-compensation", "cascade-reaches-destructive"} <= codes(
        result.findings
    )


def test_a_well_arranged_call_passes_every_gate():
    result = assess_effects(
        "orders.create",
        {"id": "A-1"},
        ledger=EffectLedger(),
        key="caller-key",
        steps=[Step("orders.create", compensator="orders.cancel")],
        triggers={"orders.create": []},
    )
    assert result.verdict == "allow"
    assert result.findings == []
