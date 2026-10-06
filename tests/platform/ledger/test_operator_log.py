"""The governance layer, governed.

Every control in this system watches the agent. Nothing watched the operator, and the
operator is the one who can turn the controls off. `apply_suppression` silences a
detector — an unaudited version means the audit log can be defeated by switching off
the thing that would have written to it.

The first test is the one that keeps this true over time: it is structural, so a new
privileged surface added without an audit call fails here rather than being discovered
during an incident.
"""

from __future__ import annotations

import pytest

from agentfox.capabilities.business.ladder import Ladder
from agentfox.capabilities.business.store import save_ladder, set_mode
from agentfox.platform.ledger.operator_log import (
    PRIVILEGED,
    ReasonRequired,
    operator_history,
    record,
    unaudited,
)

LADDER = {
    "key": "refunds",
    "tool": "payments.refund",
    "field": "arguments.amount",
    "unit": "USD",
    "bands": [{"upto": 10, "outcome": "allow"}, {"outcome": "escalate"}],
}


# --- The structural guarantee ----------------------------------------------


def test_every_declared_privileged_operation_records():
    """A new operator surface written without an audit call fails here.

    This mirrors the import-time assertion that keeps mapped classes tenant-scoped —
    same reasoning, one layer up. Source inspection rather than runtime interception,
    because the failure being guarded against is a surface nobody has exercised yet.
    """
    assert unaudited() == []


def test_the_registry_explains_why_each_entry_is_privileged():
    """An entry nobody can justify is an entry that gets removed to make a test pass."""
    for entry in PRIVILEGED:
        assert entry.why, entry.target
        assert entry.action.startswith("operator.")


def test_the_suppression_pair_is_both_recorded():
    """Suppressing and restoring have to be reconstructable as a pair, or an
    investigation cannot say which detector was unwatched and for how long."""
    actions = {e.action for e in PRIVILEGED}
    assert {"operator.guardrail.suppressed", "operator.guardrail.unsuppressed"} <= actions


# --- The recorder ----------------------------------------------------------


def test_a_blank_reason_is_refused_rather_than_defaulted(seeded):
    """A field that can be left blank is blank exactly when it matters."""
    with pytest.raises(ReasonRequired):
        record(seeded, "operator.business_rule.changed", actor="ops", reason="   ")


def test_operator_actions_must_be_namespaced(seeded):
    with pytest.raises(ValueError, match="namespaced"):
        record(seeded, "guardrail.suppressed", actor="ops", reason="because")


def test_an_operator_entry_lands_in_the_same_chain_as_the_decisions(seeded):
    """A separate operator log is a log someone can be given permission to clear.

    In the shared chain, removing an operator action breaks the digest over every
    decision recorded after it.
    """
    entry = record(
        seeded,
        "operator.guardrail.suppressed",
        actor="ops@example.com",
        reason="false positives on invoice numbers",
        subject_type="detector",
        subject_id="pii.us_ssn",
    )
    assert entry.actor_type == "operator"
    assert entry.digest and entry.prev_digest
    assert entry.payload_json["reason"] == "false positives on invoice numbers"


# --- The wired surfaces ----------------------------------------------------


def test_changing_a_business_rule_records_the_bands_it_replaced(seeded):
    """ "The threshold was changed" answers nothing an investigation asks."""
    save_ladder(seeded, Ladder.model_validate(LADDER), actor="ops", reason="initial")

    loosened = dict(LADDER, bands=[{"upto": 5000, "outcome": "allow"}, {"outcome": "escalate"}])
    save_ladder(
        seeded,
        Ladder.model_validate(loosened),
        actor="ops",
        reason="finance asked for a higher auto-approve ceiling",
    )

    history = operator_history(seeded)
    change = next(h for h in history if h["action"] == "operator.business_rule.changed")
    assert change["before"]["bands"][0]["upto"] == 10
    assert change["after"]["bands"][0]["upto"] == 5000
    assert "finance asked" in change["reason"]


def test_moving_a_rule_to_enforce_is_recorded_separately_from_its_definition(seeded):
    """The same rule with the opposite effect.

    "Was this rule live in March?" is a question about the mode, not the bands.
    """
    save_ladder(seeded, Ladder.model_validate(LADDER), actor="ops", reason="initial")
    set_mode(seeded, "refunds", "enforce", actor="ops", reason="observation period over")

    entry = next(
        h for h in operator_history(seeded) if h["action"] == "operator.business_rule.mode_changed"
    )
    assert entry["before"]["mode"] == "observe"
    assert entry["after"]["mode"] == "enforce"


def test_issuing_a_credential_never_records_the_credential(seeded):
    """The entry identifies which token without being a second place it exists.

    Identification is by token id, not by any part of the key: capture-time redaction
    scrubs the key prefix, which is right, and recording a field that always reads
    `<redacted>` would only look like evidence.
    """
    from sqlalchemy import select

    from agentfox.core.models import User
    from agentfox.gateway.auth import issue_token

    user = seeded.scalars(select(User)).first()
    if user is None:
        pytest.skip("no seeded user in this fixture")

    token, raw = issue_token(seeded, user, name="ci", actor="ops", reason="CI pipeline")
    entry = next(h for h in operator_history(seeded) if h["action"] == "operator.credential.issued")
    assert entry["subject"] == f"api_token:{token.id}"
    assert raw not in str(entry), "the raw token must never reach the log"
    assert token.key_prefix not in str(entry), "nor any part of the key"


def test_history_reads_newest_first_and_carries_the_reason(seeded):
    record(seeded, "operator.business_rule.changed", actor="a", reason="first")
    record(seeded, "operator.business_rule.changed", actor="b", reason="second")
    history = operator_history(seeded)
    assert history[0]["reason"] == "second"
    assert history[0]["actor"] == "b"


def test_agent_decisions_are_not_returned_as_operator_actions(seeded):
    """The false-positive floor: the shared chain has to stay filterable."""
    from agentfox.platform.ledger import chain

    chain.append(seeded, "decision.recorded", actor_type="agent", actor_id="agent-1")
    record(seeded, "operator.business_rule.changed", actor="ops", reason="a change")
    assert [h["action"] for h in operator_history(seeded)] == ["operator.business_rule.changed"]
