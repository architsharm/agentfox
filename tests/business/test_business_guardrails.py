"""Business-process guardrails.

*"Refunds under $10 auto-approve; $10–100 run a validation check; over $100 needs a
human."* That sentence is the most common form of governance a business hands an
engineering team, and the policy engine could not express it. Written as three ordinary
rules it produced two silent defects, both reproduced before this construct existed:
`lt 10` and `gt 10` leave exactly 10 uncovered, and at 500 two rules fire because the
engine takes the strongest.

The architectural point these tests protect is that security guardrails and business
guardrails compose by **different algebras** — lattice-maximum versus exactly-one-band
— and that mixing them lets a refund threshold quietly weaken a security control.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agentfox.business import (
    Ladder,
    VerifySpec,
    all_ladders,
    build_graph,
    combine,
    evaluate_ladder,
    find_conflicts,
    run_verification,
    save_ladder,
)
from agentfox.business.catalogue import BY_ID, CATALOGUE, INTENTS, inert_kinds, suggest
from agentfox.business.ladder import parse_amount
from agentfox.cli.main import app
from agentfox.core.db import session_scope

runner = CliRunner()

REFUND = {
    "key": "refund-approval",
    "owner": "finance@acme.com",
    "tool": "payments.refund",
    "field": "arguments.amount",
    "unit": "USD",
    "mode": "enforce",
    "bands": [
        {"upto": 10, "outcome": "allow", "reason": "small refunds auto-approve"},
        {"upto": 100, "outcome": "verify", "verify": {"check": "risk.refund_check"}},
        {"outcome": "escalate", "approver_role": "finance"},
    ],
}


def ladder(**overrides) -> Ladder:
    return Ladder.model_validate({**REFUND, **overrides})


def decide(amount, **overrides) -> str:
    return evaluate_ladder(ladder(**overrides), {"arguments": {"amount": amount}}).outcome


# ---------------------------------------------------------------------------
# The defects this construct removes
# ---------------------------------------------------------------------------


def test_boundaries_belong_to_exactly_one_band():
    """The original defect: `lt 10` and `gt 10` left 10 matching no rule at all, and
    the request fell through to the default with nothing in the trace."""
    assert decide(10) == "allow"
    assert decide(10.01) == "verify"
    assert decide(100) == "verify"
    assert decide(100.01) == "escalate"


def test_the_ladder_is_total_by_construction():
    """Every value lands somewhere, including ones nobody thought about."""
    for amount in (0, 0.001, 9.99, 10, 50, 100, 1e9):
        assert decide(amount) in ("allow", "verify", "escalate")


def test_a_band_may_be_weaker_than_the_one_below_it():
    """Impossible in the rule engine, where every rule is evaluated and the strongest
    wins — so a higher band could never auto-approve."""
    unusual = ladder(
        bands=[
            {"upto": 10, "outcome": "escalate"},
            {"outcome": "allow", "reason": "trusted merchant tier"},
        ]
    )
    assert evaluate_ladder(unusual, {"arguments": {"amount": 5}}).outcome == "escalate"
    assert evaluate_ladder(unusual, {"arguments": {"amount": 500}}).outcome == "allow"


def test_exactly_one_band_matches():
    decision = evaluate_ladder(ladder(), {"arguments": {"amount": 50}})
    assert decision.band_index == 1
    assert decision.matched


# ---------------------------------------------------------------------------
# Authoring mistakes are refused, not absorbed
# ---------------------------------------------------------------------------


def test_a_ladder_without_an_open_ended_final_band_is_refused():
    """Otherwise a value above the last threshold matches nothing — the silent hole
    this construct exists to remove."""
    with pytest.raises(ValueError, match="final band"):
        Ladder.model_validate({**REFUND, "bands": [{"upto": 10, "outcome": "allow"}]})


def test_descending_bands_are_refused():
    with pytest.raises(ValueError, match="ascend"):
        Ladder.model_validate(
            {
                **REFUND,
                "bands": [
                    {"upto": 100, "outcome": "allow"},
                    {"upto": 10, "outcome": "escalate"},
                    {"outcome": "block"},
                ],
            }
        )


def test_an_open_ended_band_in_the_middle_is_refused():
    with pytest.raises(ValueError, match="only the final band"):
        Ladder.model_validate(
            {
                **REFUND,
                "bands": [
                    {"outcome": "allow"},
                    {"outcome": "escalate"},
                ],
            }
        )


def test_a_verify_band_must_say_what_it_verifies():
    with pytest.raises(ValueError, match="verify"):
        Ladder.model_validate(
            {
                **REFUND,
                "bands": [
                    {"upto": 10, "outcome": "verify"},
                    {"outcome": "escalate"},
                ],
            }
        )


def test_an_unknown_unit_is_refused():
    """A bare threshold is a bug waiting to happen: one team means dollars, another
    means cents, and the ladder approves a hundred-fold larger refund."""
    with pytest.raises(ValueError, match="unit"):
        Ladder.model_validate({**REFUND, "unit": "dollars"})


# ---------------------------------------------------------------------------
# Undecidable is not the same as allowed
# ---------------------------------------------------------------------------


def test_a_missing_field_escalates_rather_than_allowing():
    """Defaulting to allow would make omitting a field the cheapest way past a
    control."""
    decision = evaluate_ladder(ladder(), {"arguments": {}})
    assert decision.outcome == "escalate"
    assert "not present" in decision.undecidable


def test_a_foreign_currency_is_refused_not_converted():
    decision = evaluate_ladder(ladder(), {"arguments": {"amount": "€75"}})
    assert decision.outcome == "escalate"
    assert "refusing to convert" in decision.undecidable


def test_a_matching_currency_symbol_is_read():
    assert decide("$75") == "verify"
    assert decide("1,250.50") == "escalate"


def test_a_negative_amount_escalates():
    """A negative refund is a charge — whatever the bands say, it is not the thing
    they were written about."""
    decision = evaluate_ladder(ladder(), {"arguments": {"amount": -5}})
    assert decision.outcome == "escalate"


def test_non_numeric_values_escalate():
    for value in ("abc", True, {"nested": 1}, [1]):
        assert evaluate_ladder(ladder(), {"arguments": {"amount": value}}).outcome == "escalate"


def test_parse_amount_reports_why_it_refused():
    value, problem = parse_amount("€75", "USD")
    assert value is None and "EUR" in problem


# ---------------------------------------------------------------------------
# The verification step
# ---------------------------------------------------------------------------


def test_a_passing_check_allows():
    spec = VerifySpec(check="risk", expect={"risk_score": {"op": "lt", "value": 0.7}})
    assert run_verification(spec, lambda c, a: {"risk_score": 0.2}).outcome == "allow"


def test_a_failing_check_escalates():
    spec = VerifySpec(check="risk", expect={"risk_score": {"op": "lt", "value": 0.7}})
    result = run_verification(spec, lambda c, a: {"risk_score": 0.9})
    assert result.outcome == "escalate" and result.ran and not result.passed


def test_a_check_that_raises_is_not_a_check_that_passed():
    """The failure being designed against is a validation step that quietly stops
    validating."""

    def broken(check, arguments):
        raise RuntimeError("risk service down")

    result = run_verification(VerifySpec(check="risk"), broken)
    assert result.outcome == "escalate"
    assert not result.ran
    assert "risk service down" in result.detail


def test_no_runner_is_also_a_failure():
    result = run_verification(VerifySpec(check="risk"), None)
    assert result.outcome == "escalate" and not result.ran


def test_an_empty_expectation_means_truthiness():
    spec = VerifySpec(check="risk")
    assert run_verification(spec, lambda c, a: True).outcome == "allow"
    assert run_verification(spec, lambda c, a: None).outcome == "escalate"


# ---------------------------------------------------------------------------
# The two algebras
# ---------------------------------------------------------------------------


def test_a_business_band_can_never_loosen_a_security_verdict():
    """Otherwise a refund threshold written by Finance becomes a way to disable an
    injection control written by Security, and neither author would ever see it."""
    approving = evaluate_ladder(ladder(), {"arguments": {"amount": 5}})
    combined = combine("block", approving)
    assert combined.verdict == "block"
    assert combined.security_dominated
    assert "cannot loosen" in combined.reason


def test_a_business_band_may_tighten():
    tightening = evaluate_ladder(ladder(), {"arguments": {"amount": 250}})
    combined = combine("allow", tightening)
    assert combined.verdict == "escalate"
    assert not combined.security_dominated


def test_an_undecidable_ladder_still_tightens():
    undecidable = evaluate_ladder(ladder(), {"arguments": {}})
    assert combine("allow", undecidable).verdict == "escalate"


def test_no_ladder_leaves_the_security_verdict_alone():
    assert combine("redact", None).verdict == "redact"


# ---------------------------------------------------------------------------
# Many authors, one graph
# ---------------------------------------------------------------------------


def test_two_teams_disagreeing_is_reported_not_silently_resolved():
    """Precedence is applied *and* named. One of the two authors believes something
    that is not happening, and needs to find out."""
    finance = ladder()
    support = ladder(
        key="support-refunds",
        owner="support@acme.com",
        bands=[
            {"upto": 500, "outcome": "allow"},
            {"outcome": "escalate"},
        ],
    )
    conflicts = find_conflicts([finance, support])
    assert conflicts
    conflict = conflicts[0]
    assert conflict.code == "contradiction"
    assert {conflict.left, conflict.right} == {"refund-approval", "support-refunds"}
    assert conflict.at_value is not None


def test_different_units_on_the_same_field_are_critical():
    """One team's 100 is another's 1.00, and no precedence rule makes that safe."""
    usd = ladder()
    cents = ladder(
        key="eu-refunds",
        unit="USD_CENTS",
        bands=[
            {"upto": 1000, "outcome": "allow"},
            {"outcome": "escalate"},
        ],
    )
    conflict = find_conflicts([usd, cents])[0]
    assert conflict.code == "unit-mismatch"
    assert conflict.severity == "critical"


def test_agreeing_ladders_produce_no_conflict():
    assert find_conflicts([ladder(), ladder(key="copy")]) == []


def test_ladders_on_different_fields_do_not_conflict():
    other = ladder(key="other", field="arguments.quantity", unit="count")
    assert find_conflicts([ladder(), other]) == []


def test_the_graph_shows_what_will_actually_run():
    nodes = build_graph(ladders=[ladder()])
    assert any(n.key == "refund-approval" for n in nodes)
    stages = [n.stage for n in nodes]
    assert stages == sorted(
        stages,
        key=lambda s: [
            "input",
            "retrieval",
            "tool_args",
            "output",
            "conversation",
            "offline",
        ].index(s),
    )


def test_the_graph_names_guardrails_that_cannot_run():
    """A control listed as configured but never reachable reads as coverage, which is
    worse than one that is visibly missing."""
    nodes = build_graph(supplied_inputs={"text on any surface"})
    inert = [n for n in nodes if n.inert_because]
    assert inert, "with almost no inputs supplied, most kinds should report as inert"
    assert any("principal" in n.inert_because for n in inert)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def test_every_kind_is_well_formed():
    for kind in CATALOGUE:
        assert kind.intent in INTENTS, kind.id
        assert kind.decides.endswith("."), f"{kind.id}: `decides` should read as a sentence"
        assert kind.stage in (
            "input",
            "retrieval",
            "tool_args",
            "output",
            "conversation",
            "offline",
        ), kind.id


def test_kind_ids_are_unique():
    assert len(BY_ID) == len(CATALOGUE)


def test_the_catalogue_names_which_kinds_are_inert_without_inputs():
    """The audit found three complete engines nobody could switch on. Naming the
    dependency makes it visible instead of discovered in production."""
    inert = {kind.id for kind in inert_kinds()}
    assert "entitlement_filter" in inert
    assert "knowledge_boundary" in inert
    assert "escalation_policy" in inert


def test_a_policy_sentence_maps_to_a_guardrail_kind():
    assert any(
        k.id == "source_authority"
        for k, _ in suggest("Agents must cite the approved source of truth")
    )
    assert any(
        k.id == "entitlement_filter"
        for k, _ in suggest("Never disclose salary data to anyone outside HR")
    )
    assert any(
        k.id == "action_analysis"
        for k, _ in suggest("No destructive queries against the production database")
    )


def test_an_unmatched_instruction_returns_nothing_rather_than_guessing():
    """A confident wrong suggestion is worse than none: it produces a control that
    looks configured and governs the wrong thing."""
    assert suggest("the office is closed on Fridays") == []


# ---------------------------------------------------------------------------
# Storage and the enforcement path
# ---------------------------------------------------------------------------


def test_a_ladder_round_trips_through_storage(isolated_db):
    with session_scope() as session:
        save_ladder(session, ladder())
    with session_scope() as session:
        loaded = all_ladders(session)
    assert len(loaded) == 1
    assert loaded[0].key == "refund-approval"
    assert len(loaded[0].bands) == 3


def test_re_authoring_bumps_the_version(isolated_db):
    """An auditor asking why a refund was approved in March needs March's thresholds."""
    from agentfox.core.models import BusinessRule

    with session_scope() as session:
        save_ladder(session, ladder())
        save_ladder(session, ladder())
    with session_scope() as session:
        assert session.query(BusinessRule).one().version == 2


def test_a_definition_that_no_longer_validates_is_skipped_not_fatal(isolated_db):
    """One malformed rule written months ago must not take the enforcement path down
    for every other rule that is fine."""
    from agentfox.core.models import BusinessRule

    with session_scope() as session:
        save_ladder(session, ladder())
        session.add(
            BusinessRule(
                key="broken",
                kind="threshold_ladder",
                definition_json={"key": "broken", "bands": []},
            )
        )
    with session_scope() as session:
        loaded = all_ladders(session)
    assert [lad.key for lad in loaded] == ["refund-approval"]


def test_the_ladder_governs_a_real_tool_call(isolated_db):
    """The whole point: not another engine nobody can reach."""
    from agentfox.core.models import Agent
    from agentfox.fixtures.seed import seed
    from agentfox.identity import ensure_identity, grant_capability
    from agentfox.runtime.enforcement import Enforcer

    with session_scope() as session:
        seed(session)
        save_ladder(session, ladder())
        agent = session.query(Agent).filter_by(slug="payments-ops").one()
        grant_capability(session, ensure_identity(session, agent), "payments.refund")

    outcomes = {}
    with session_scope() as session:
        enforcer = Enforcer(session)
        for amount in (5, 50, 250):
            result = enforcer.guard_tool_call(
                agent_slug="payments-ops",
                tool_key="payments.refund",
                arguments={"amount": amount},
            )
            outcomes[amount] = (result.taint.get("business") or {}).get("outcome")
    assert outcomes == {5: "allow", 50: "verify", 250: "escalate"}


def test_the_decision_records_which_rule_decided(isolated_db):
    from agentfox.core.models import Agent
    from agentfox.fixtures.seed import seed
    from agentfox.identity import ensure_identity, grant_capability
    from agentfox.runtime.enforcement import Enforcer

    with session_scope() as session:
        seed(session)
        save_ladder(session, ladder())
        agent = session.query(Agent).filter_by(slug="payments-ops").one()
        grant_capability(session, ensure_identity(session, agent), "payments.refund")

    with session_scope() as session:
        result = Enforcer(session).guard_tool_call(
            agent_slug="payments-ops",
            tool_key="payments.refund",
            arguments={"amount": 250},
        )
    fired = [r["rule_id"] for r in result.rules_fired]
    assert "business.refund-approval" in fired


def test_ladders_do_not_run_on_surfaces_with_no_number_to_band(isolated_db):
    from agentfox.core.models import Agent
    from agentfox.fixtures.seed import seed
    from agentfox.runtime.enforcement import Enforcer

    with session_scope() as session:
        seed(session)
        save_ladder(session, ladder())
        agent = session.query(Agent).filter_by(slug="payments-ops").one()

    with session_scope() as session:
        agent = session.query(Agent).filter_by(slug="payments-ops").one()
        result = Enforcer(session).evaluate(
            agent=agent, identity=None, content="some output", surface="output"
        )
    assert not result.taint.get("business")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write(tmp_path, name, payload):
    import yaml

    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload))
    return path


def test_the_cli_authors_and_shows_a_rule(isolated_db, tmp_path):
    path = _write(tmp_path, "refund.yaml", REFUND)
    applied = runner.invoke(app, ["guardrails", "apply", str(path)])
    assert applied.exit_code == 0, applied.output
    flat = " ".join(runner.invoke(app, ["guardrails", "show"]).output.split())
    assert "refund-approval" in flat
    assert "allow" in flat and "verify" in flat


def test_the_cli_refuses_an_invalid_ladder(isolated_db, tmp_path):
    path = _write(tmp_path, "bad.yaml", {**REFUND, "bands": [{"upto": 10, "outcome": "allow"}]})
    result = runner.invoke(app, ["guardrails", "apply", str(path)])
    assert result.exit_code == 1
    assert "not a valid ladder" in " ".join(result.output.split())


def test_the_cli_exits_non_zero_on_a_conflict(isolated_db, tmp_path):
    runner.invoke(app, ["guardrails", "apply", str(_write(tmp_path, "a.yaml", REFUND))])
    runner.invoke(
        app,
        [
            "guardrails",
            "apply",
            str(
                _write(
                    tmp_path,
                    "b.yaml",
                    {
                        **REFUND,
                        "key": "support-refunds",
                        "owner": "support@acme.com",
                        "bands": [{"upto": 500, "outcome": "allow"}, {"outcome": "escalate"}],
                    },
                )
            ),
        ],
    )
    result = runner.invoke(app, ["guardrails", "check"])
    assert result.exit_code == 1
    assert "conflict" in " ".join(result.output.split())


def test_the_cli_explains_a_guardrail_kind(isolated_db):
    flat = " ".join(
        runner.invoke(app, ["guardrails", "explain", "threshold_ladder"]).output.split()
    )
    assert "bands" in flat
    assert "outcome" in flat


def test_explaining_an_unknown_kind_lists_the_real_ones(isolated_db):
    result = runner.invoke(app, ["guardrails", "explain", "made_up"])
    assert result.exit_code == 1
    assert "threshold_ladder" in " ".join(result.output.split())
