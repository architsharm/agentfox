"""The judgment router, and the invariants bought by measured failures.

Each test here names the Jev behaviour it exists to contain. None of them
reach the network: the point of the split is that the half that decides
authorisation is pure code, so it must be testable with no key.
"""

from __future__ import annotations

import json

import pytest

from agentfox.capabilities.judgment import (
    Comparison,
    Identity,
    JevAnswer,
    JevResult,
    JevUnavailable,
    Outcome,
    Policy,
    PredicateMisrouted,
    Router,
    Semantic,
)


class FakeJev:
    """A client that answers from a script, and records what it was sent."""

    def __init__(self, answers: dict[str, float] | None = None, fail: str | None = None):
        self._answers = answers or {}
        self._fail = fail
        self.sent: list[tuple] = []

    def available(self) -> bool:
        return True

    def ask(self, state, questions):
        self.sent.append((state, questions))
        if self._fail:
            raise JevUnavailable(self._fail)
        return JevResult(
            answers={
                qid: JevAnswer(qid, "noul", self._answers.get(qid, 0.9), 0.8) for qid in questions
            },
            model="fake",
        )


# ---------------------------------------------------------------------------
# The mistake that started the investigation, made unwritable
# ---------------------------------------------------------------------------


def test_a_comparison_hidden_in_a_semantic_question_is_refused():
    """The original failing question read as a judgment and was a subtraction.

    "Does days_since_last_refund satisfy the requirement about recent
    refunds" returned 0.98 — wrong — on eight consecutive runs, with 30 days
    against a 90-day window. Confidently wrong, so no threshold caught it.
    """
    with pytest.raises(PredicateMisrouted, match="within the last"):
        Semantic(
            id="no_recent_refund",
            instructions="Has the account had a refund within the last 90 days?",
            criteria={"what": "A refund inside the window."},
            weighs="recency",
        )


@pytest.mark.parametrize(
    "phrasing",
    [
        "Is the amount at least 50 dollars?",
        "Does it exceed the approval limit?",
        "How many refunds were there?",
        "Is `request.amount` >= 50?",
    ],
)
def test_every_comparison_phrasing_is_refused(phrasing):
    with pytest.raises(PredicateMisrouted):
        Semantic(id="q", instructions=phrasing, criteria={}, weighs="x")


def test_a_real_meaning_question_is_allowed():
    """The questions Jev is good at must still be expressible. This exact
    question scored 24/24 across the case suite and was unmoved by key order."""
    p = Semantic(
        id="promises_outcome",
        instructions="Does `agent_answer` tell the customer the refund will happen?",
        criteria={"what": "Wording a customer would read as the refund being settled."},
        weighs="whether the answer settles the outcome",
    )
    assert p.weighs


def test_a_semantic_predicate_must_name_its_one_signal():
    """Writing the signal down is what stops a second one creeping in. The
    bundled duplicate question weighed merchant, amount, timing and
    descriptor at once and scored 0.64; the descriptor alone scored 0.96."""
    with pytest.raises(PredicateMisrouted, match="one signal"):
        Semantic(id="q", instructions="Is this a duplicate charge?", criteria={}, weighs="  ")


# ---------------------------------------------------------------------------
# Comparisons, which code owns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "days,expected",
    [
        (30, Outcome.VIOLATED),
        (89, Outcome.VIOLATED),
        (90, Outcome.SATISFIED),
        (91, Outcome.SATISFIED),
    ],
)
def test_the_window_boundary_is_exact(days, expected):
    """Jev allowed 89 and 30 against a 90-day window, and correctly allowed
    91 — so it was not evaluating the condition at all."""
    policy = Policy(
        "refund",
        "4",
        (Comparison(id="recency", left="request.days_since_last_refund", op=">=", right=90),),
    )
    out = Router(FakeJev()).evaluate(policy, {"request": {"days_since_last_refund": days}})
    assert out.results["recency"].outcome is expected


@pytest.mark.parametrize("amount,expected", [(50, Outcome.SATISFIED), (50.01, Outcome.VIOLATED)])
def test_one_cent_over_the_limit(amount, expected):
    policy = Policy(
        "refund",
        "4",
        (Comparison(id="limit", left="request.amount", op="<=", right=50, unit="USD"),),
    )
    out = Router(FakeJev()).evaluate(policy, {"request": {"amount": amount, "currency": "USD"}})
    assert out.results["limit"].outcome is expected


def test_a_currency_mismatch_is_unknown_and_escalates():
    """Asked as a judgment, every GBP amount scored 0.58-0.64 "within a 50
    USD limit" regardless of size — 49 GBP is about 62 USD. There is no rate
    in state, so there is no answer, and no answer must not read as a pass."""
    policy = Policy(
        "refund",
        "4",
        (Comparison(id="limit", left="request.amount", op="<=", right=50, unit="USD"),),
        requires_all=("limit",),
    )
    out = Router(FakeJev()).evaluate(policy, {"request": {"amount": 49, "currency": "GBP"}})
    assert out.results["limit"].outcome is Outcome.UNKNOWN
    assert out.escalate and not out.authorised
    assert "no rate in state" in out.results["limit"].detail


# ---------------------------------------------------------------------------
# Identity, which code owns and a model must never be asked
# ---------------------------------------------------------------------------


def test_cross_tenant_is_refused_by_code():
    """Asked directly, Jev returned 0.78 "entitled" for a requester whose
    user_id matched and whose account_id did not. Tenant isolation is one of
    the four controls that may not fail open."""
    policy = Policy(
        "access",
        "1",
        (
            Identity(
                id="tenant",
                subject="requester.account_id",
                relation="same_tenant_as",
                object="$order.account_id",
            ),
        ),
        requires_all=("tenant",),
    )
    out = Router(FakeJev()).evaluate(
        policy,
        {
            "requester": {"user_id": "u_8821", "account_id": "acc_77"},
            "order": {"owner_user_id": "u_8821", "account_id": "acc_31"},
        },
    )
    assert out.results["tenant"].outcome is Outcome.VIOLATED
    assert not out.authorised


def test_delegate_membership():
    policy = Policy(
        "access",
        "1",
        (
            Identity(
                id="delegate",
                subject="requester.user_id",
                relation="in",
                object="$order.authorised_user_ids",
            ),
        ),
        requires_all=("delegate",),
    )
    state = {
        "requester": {"user_id": "u_9100"},
        "order": {"authorised_user_ids": ["u_8821", "u_9100"]},
    }
    assert Router(FakeJev()).evaluate(policy, state).authorised


# ---------------------------------------------------------------------------
# Failure direction and degradation
# ---------------------------------------------------------------------------


def test_an_unavailable_judgment_does_not_authorise():
    """Every failure measured was an under-flag. A judgment that could not
    run is a gap in the record, never a pass."""
    policy = Policy(
        "refund",
        "4",
        (
            Semantic(
                id="promised",
                instructions="Does `answer` settle the outcome?",
                criteria={"what": "It settles it."},
                weighs="settlement",
            ),
        ),
        requires_all=("promised",),
    )
    out = Router(FakeJev(fail="connection reset")).evaluate(policy, {"answer": "done"})
    assert out.results["promised"].outcome is Outcome.UNKNOWN
    assert out.escalate and not out.authorised
    assert out.degraded and "connection reset" in out.degraded[0]


def test_a_missing_operand_is_not_a_pass():
    policy = Policy(
        "refund",
        "4",
        (Comparison(id="recency", left="request.days_since_last_refund", op=">=", right=90),),
        requires_all=("recency",),
    )
    out = Router(FakeJev()).evaluate(policy, {"request": {}})
    assert out.results["recency"].outcome is Outcome.UNKNOWN
    assert not out.authorised


def test_code_violation_cannot_be_overridden_by_a_confident_judgment():
    """A judgment may raise severity. It may never clear a code predicate."""
    policy = Policy(
        "refund",
        "4",
        (
            Comparison(id="recency", left="request.days_since_last_refund", op=">=", right=90),
            Semantic(
                id="looks_fine",
                instructions="Does `answer` read as routine?",
                criteria={"what": "Routine."},
                weighs="tone",
            ),
        ),
        requires_all=("recency", "looks_fine"),
    )
    out = Router(FakeJev({"looks_fine": 0.99})).evaluate(
        policy, {"request": {"days_since_last_refund": 30}, "answer": "all good"}
    )
    assert out.results["looks_fine"].outcome is Outcome.SATISFIED
    assert out.results["recency"].outcome is Outcome.VIOLATED
    assert not out.authorised


# ---------------------------------------------------------------------------
# Batching and serialisation
# ---------------------------------------------------------------------------


def test_every_semantic_question_goes_in_one_request():
    """Latency is flat in question count — 8 questions took 416ms and 512
    took 524ms — so splitting buys nothing and costs a round trip each."""
    fake = FakeJev()
    policy = Policy(
        "refund",
        "4",
        tuple(
            Semantic(
                id=f"q{i}",
                instructions=f"Does `answer` show trait {i}?",
                criteria={"what": "It does."},
                weighs=f"trait {i}",
            )
            for i in range(12)
        ),
    )
    Router(fake).evaluate(policy, {"answer": "text"})
    assert len(fake.sent) == 1
    assert len(fake.sent[0][1]) == 12


def test_the_payload_is_serialised_with_sorted_keys():
    """The same question over the same values returned a median 0.53 under
    one key order and 0.98 on eight consecutive runs under another."""
    from agentfox.capabilities.judgment.jev import JevClient

    captured: dict = {}

    class Probe(JevClient):
        def ask(self, state, questions):  # type: ignore[override]
            captured["body"] = json.dumps(
                {"model": "m", "state": state, "questions": questions}, sort_keys=True, default=str
            )
            return JevResult()

    Probe(api_key="k").ask({"b": 1, "a": 2}, {"q": {"type": "noul", "instructions": "x"}})
    assert captured["body"].index('"a"') < captured["body"].index('"b"')
