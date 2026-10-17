"""Guarantees the proposal flow must keep even under concurrency.

Two things live outside application code on purpose. Duplicate open proposals are refused
by a partial unique index, because a check-then-insert in Python loses races. The rule that
undoing a tightening needs a person is a contract rule, not a condition buried in one function.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentfox.capabilities.improvement import contract
from agentfox.core import models


def test_index_predicate_lists_exactly_the_open_statuses():
    statuses = set(re.findall(r"'([a-z_]+)'", models.PROPOSAL_OPEN_FINGERPRINT))
    assert statuses == set(contract.OPEN)


def _proposal(status: str, org: str = "org_a") -> models.ChangeProposal:
    return models.ChangeProposal(org_id=org, kind="k", fingerprint="fp-1", status=status)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_database_refuses_a_second_open_proposal_for_the_same_problem(session):
    session.add(_proposal("proposed"))
    session.flush()
    session.add(_proposal("proven"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_closed_proposals_and_other_tenants_do_not_collide(session):
    session.add_all(
        [
            _proposal("rejected"),
            _proposal("rolled_back"),
            _proposal("verified"),
            _proposal("proposed"),
            _proposal("proposed", org="org_b"),
        ]
    )
    session.flush()


@pytest.mark.parametrize(
    ("direction", "allowed"),
    [("tightens", False), ("loosens", True), ("neutral", True), ("sideways", False)],
)
def test_undoing_a_tightening_is_a_decision_for_a_person(direction, allowed):
    assert contract.may_rollback_automatically(direction=direction) is allowed
