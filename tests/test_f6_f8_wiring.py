"""F6 and F8, on the live enforcement path.

`docs/failure-modes.md` recorded eleven modes as `◐-unwired`: real, individually
unit-tested detectors that nothing in the request path ever called. `tests/
test_commitments.py` and `tests/test_context_integrity.py` already prove the detectors
work — and proved exactly nothing about production, because they call the functions
directly. That is the gap this file exists to close, so every test here goes through
`Enforcer.evaluate()` or `guard_memory_write()` and asserts on what a real request
produced: a persisted `Finding`, an entry in `result.taint`, a verdict.

Three things are asserted throughout, because wiring a detector on badly is worse than
leaving it off:

* it fires on the real path (the audit's claim, falsified);
* it stays quiet on ordinary traffic and when the caller declared nothing (the
  false-positive floor — a gate that fires on normal requests gets switched off);
* it does not block by default, and blocking is reachable only by writing a policy.
"""

from __future__ import annotations

import json
import pathlib
import time

import pytest

from agentfox.runtime import enforcement
from agentfox.runtime.enforcement import Enforcer
from agentfox.core.models import Agent, Finding
from agentfox.policy import PolicyDocument, save_policy


@pytest.fixture
def agent(seeded) -> Agent:
    return seeded.query(Agent).filter_by(slug="support-triage").one()


def findings_of(session, kind: str) -> list[Finding]:
    return session.query(Finding).filter_by(type=kind).all()


def codes(session, kind: str) -> set[str]:
    return {(f.evidence_json or {}).get("code") for f in findings_of(session, kind)}


ORDINARY = "Your order shipped on Tuesday and should arrive by Friday."

CLEAN_PROSE = (
    "Refunds under $10 are auto-approved. Refunds between $10 and $100 must run a "
    "fraud check before proceeding. Refunds over $100 require approval from the "
    "finance team, and the approval is recorded against the original transaction."
)


# --- F6.1 binding commitments ---------------------------------------------


def test_a_binding_commitment_is_found_on_the_real_output_path(seeded, enforcer, agent):
    """The Air Canada shape: fluent, on-topic, and creating an obligation nobody
    authorised. Before this wiring, a production request got zero benefit from the
    detector that catches it."""
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Your refund has been approved and we'll credit your account by Friday.",
        surface="output",
    )
    assert [c["kind"] for c in result.taint["commitments"]] == ["decision"]
    assert len(findings_of(seeded, "binding_commitment")) == 1
    assert "commitment.decision" in [r["code"] for r in result.taint["action"]["risks"]]


def test_a_hedged_near_miss_is_not_a_commitment(seeded, enforcer, agent):
    """The whole difficulty of F6.1 is that the binding and non-binding forms differ by
    hedging alone."""
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Refunds are usually approved within two days.",
        surface="output",
    )
    assert "commitments" not in result.taint
    assert findings_of(seeded, "binding_commitment") == []


def test_an_authorised_commitment_is_recorded_without_becoming_a_finding(seeded, enforcer, agent):
    """An approval the agent was entitled to grant is still recorded — someone has to be
    able to show what was promised — but it is not a breach."""
    enforcer.evidence = {"authorised": True}
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Your refund has been approved.",
        surface="output",
    )
    assert findings_of(seeded, "binding_commitment") == []
    assert "commitments" not in result.taint


# --- F6.2 register / unlicensed advice ------------------------------------


def test_an_unlicensed_dosage_instruction_is_caught(seeded, enforcer, agent):
    """In medicine the line is not accuracy but instruction."""
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Take 400mg of ibuprofen every six hours with food.",
        surface="output",
    )
    assert "dosage-instruction" in codes(seeded, "register_breach")
    assert result.taint["register"]["domain"] == "medical"


def test_a_licensed_operator_silences_the_register_finding(seeded, enforcer, agent):
    """Standing is declared, never inferred: an operator that employs clinicians
    licenses `medical` and the instruction findings stop firing."""
    enforcer.evidence = {"licensed_domains": ("medical",)}
    enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Take 400mg of ibuprofen every six hours with food.",
        surface="output",
    )
    assert findings_of(seeded, "register_breach") == []


def test_ordinary_support_prose_is_not_a_register_breach(seeded, enforcer, agent):
    enforcer.evaluate(agent=agent, identity=None, content=ORDINARY, surface="output")
    assert findings_of(seeded, "register_breach") == []


# --- F6.3 AI disclosure ----------------------------------------------------


def test_missing_ai_disclosure_is_caught_when_a_counterparty_is_declared(seeded, enforcer, agent):
    enforcer.evidence = {"channel": "chat", "counterparty": "human"}
    result = enforcer.evaluate(agent=agent, identity=None, content=ORDINARY, surface="output")
    assert result.taint["ai_disclosure"]["breach"] is True
    assert len(findings_of(seeded, "ai_disclosure_missing")) == 1


def test_a_message_that_identifies_itself_satisfies_the_obligation(seeded, enforcer, agent):
    enforcer.evidence = {"channel": "chat", "counterparty": "human"}
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="I'm an AI assistant. Your order shipped on Tuesday.",
        surface="output",
    )
    assert result.taint["ai_disclosure"]["breach"] is False
    assert findings_of(seeded, "ai_disclosure_missing") == []


def test_disclosure_is_never_inferred_when_the_caller_declared_nothing(seeded, enforcer, agent):
    """The obligation resolves to *breach* for any message on a human channel. Correct
    as an obligation, catastrophic as a default — inferred, it would report a breach on
    essentially every response this product has ever governed."""
    enforcer.evidence = {}
    result = enforcer.evaluate(agent=agent, identity=None, content=ORDINARY, surface="output")
    assert "ai_disclosure" not in result.taint
    assert findings_of(seeded, "ai_disclosure_missing") == []


def test_a_non_human_counterparty_owes_no_disclosure(seeded, enforcer, agent):
    enforcer.evidence = {"channel": "batch", "counterparty": "service"}
    enforcer.evaluate(agent=agent, identity=None, content=ORDINARY, surface="output")
    assert findings_of(seeded, "ai_disclosure_missing") == []


# --- F6.4 adverse action ---------------------------------------------------


def test_an_adverse_decision_with_no_reason_is_caught(seeded, enforcer, agent):
    enforcer.evidence = {"decision": {"outcome": "denied", "reasons": [], "domain": "credit"}}
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Unfortunately your application was not successful.",
        surface="output",
    )
    assert result.taint["adverse_action"]["statutory"] is True
    assert len(findings_of(seeded, "adverse_action")) == 1


def test_boilerplate_is_treated_as_no_reason(seeded, enforcer, agent):
    """ "Does not meet our criteria" satisfies a field and tells the applicant nothing
    they could act on, which is what the statute exists to prevent."""
    enforcer.evidence = {
        "decision": {
            "outcome": "declined",
            "reasons": ["does not meet our criteria"],
            "domain": "lending",
        }
    }
    enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Your application was declined.",
        surface="output",
    )
    assert len(findings_of(seeded, "adverse_action")) == 1


def test_a_substantive_reason_that_was_actually_communicated_is_compliant(seeded, enforcer, agent):
    enforcer.evidence = {
        "decision": {
            "outcome": "declined",
            "reasons": ["insufficient verified income history"],
            "domain": "lending",
        }
    }
    enforcer.evaluate(
        agent=agent,
        identity=None,
        content=(
            "Your application was declined because your verified income history was "
            "insufficient for the requested amount."
        ),
        surface="output",
    )
    assert findings_of(seeded, "adverse_action") == []


def test_adverse_action_is_not_checked_without_a_decision_record(seeded, enforcer, agent):
    """Checked against the record rather than the prose, because a message can read as
    an explanation while the record behind it is empty."""
    enforcer.evidence = {}
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Unfortunately your application was denied.",
        surface="output",
    )
    assert "adverse_action" not in result.taint
    assert findings_of(seeded, "adverse_action") == []


# --- F6.5 fairness: deliberately NOT wired --------------------------------


def test_fairness_probe_is_deliberately_not_on_the_per_request_path(enforcer, agent):
    """It is an aggregate over a decision population — selection rates by group with a
    30-observation floor. One request cannot exhibit disparate impact, and calling it
    per-request could only ever return `underpowered` while implying a check had run."""
    result = enforcer.evaluate(agent=agent, identity=None, content=ORDINARY, surface="output")
    assert "fairness" not in result.taint
    body = pathlib.Path(enforcement.__file__).read_text()
    assert "fairness_probe(" not in body


# --- F8 context integrity: retrieved / tool_result ------------------------


def test_mojibake_in_retrieved_content_is_caught_automatically(seeded, enforcer, agent):
    """Previously reachable only via the opt-in `POST /provenance/context-check` route;
    a normal request got none of it."""
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="The vendorâ€™s cafÃ© charge was Â£5.00 on the third of the month.",
        surface="retrieved",
        taint_source="retrieved",
    )
    assert "mojibake" in codes(seeded, "context_integrity")
    assert result.taint["context"]["verdict"] in ("abstain", "block")


def test_clean_retrieved_prose_produces_nothing(seeded, enforcer, agent):
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content=CLEAN_PROSE,
        surface="retrieved",
        taint_source="retrieved",
    )
    assert "context" not in result.taint
    assert findings_of(seeded, "context_integrity") == []


def test_an_ordinary_json_tool_result_is_not_flagged_as_a_bad_document(seeded, enforcer, agent):
    """The false-positive floor, and the reason `tool_result` is narrowed to corruption
    codes: a serialised structure is mostly punctuation and digits, so the prose-shape
    heuristic `low-text-density` fires on every healthy JSON payload. Measured directly
    on this payload before the narrowing was added."""
    payload = json.dumps(
        {
            "orders": [
                {"id": f"ORD-{i}", "total": round(19.99 + i, 2), "qty": i % 5} for i in range(30)
            ]
        }
    )
    assert len(payload) > 200
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content=payload,
        surface="tool_result",
        taint_source="tool_result",
    )
    assert "context" not in result.taint
    assert findings_of(seeded, "context_integrity") == []


def test_real_corruption_is_still_caught_on_a_tool_result(seeded, enforcer, agent):
    """Narrowing `tool_result` to the corruption codes must not switch the surface off."""
    enforcer.evaluate(
        agent=agent,
        identity=None,
        content='{"customer": "���", "note": "[UNK] charge"}',
        surface="tool_result",
        taint_source="tool_result",
    )
    assert "unknown-characters" in codes(seeded, "context_integrity")


def test_split_chunks_are_caught_when_the_retriever_supplies_them(seeded, enforcer, agent):
    """A sentence cut in half indexes as two fragments, neither of which answers the
    question the whole sentence answered — invisible downstream."""
    enforcer.evidence = {
        "chunks": [
            {"text": "Refunds over $100 require approval from the finance team, and"},
            {"text": "the approval is recorded against the original transaction."},
        ]
    }
    enforcer.evaluate(
        agent=agent,
        identity=None,
        content=CLEAN_PROSE,
        surface="retrieved",
        taint_source="retrieved",
    )
    found = codes(seeded, "context_integrity")
    assert {"split-sentence-end", "split-sentence-start"} & found


def test_retrieval_drift_runs_only_against_a_supplied_baseline(seeded, enforcer, agent):
    """Regression is only visible against a baseline, which is why the check takes one
    rather than a threshold."""
    enforcer.evidence = {
        "retrieval": {"ndcg": 0.61, "recall": 0.62, "precision": 0.60},
        "baseline": {"ndcg": 0.86, "recall": 0.84, "precision": 0.80},
    }
    enforcer.evaluate(
        agent=agent,
        identity=None,
        content=CLEAN_PROSE,
        surface="retrieved",
        taint_source="retrieved",
    )
    assert "retrieval-regression" in codes(seeded, "context_integrity")


def test_no_drift_check_without_a_baseline(seeded, enforcer, agent):
    enforcer.evidence = {"retrieval": {"ndcg": 0.61}}
    enforcer.evaluate(
        agent=agent,
        identity=None,
        content=CLEAN_PROSE,
        surface="retrieved",
        taint_source="retrieved",
    )
    assert "retrieval-regression" not in codes(seeded, "context_integrity")


# --- F8.5 memory binding ---------------------------------------------------


def test_cross_subject_memory_is_caught_on_the_live_memory_write_path(seeded, enforcer):
    """Tenant isolation cannot catch this: a shared assistant legitimately holds memory
    for thousands of end users in one org, and the boundary is the *subject*."""
    enforcer.evidence = {"principal": "alice"}
    enforcer.guard_memory_write(
        agent_slug="support-triage",
        content="Prefers email contact.",
        subject="bob",
    )
    assert "cross-subject-memory" in codes(seeded, "context_integrity")


def test_memory_written_about_the_reader_is_fine(seeded, enforcer):
    enforcer.evidence = {"principal": "alice"}
    enforcer.guard_memory_write(
        agent_slug="support-triage",
        content="Prefers email contact.",
        subject="alice",
    )
    assert findings_of(seeded, "context_integrity") == []


def test_an_unbound_memory_entry_is_reported_rather_than_assumed_safe(seeded, enforcer):
    """An entry with no subject was written by someone, about someone, and nothing
    records who."""
    enforcer.evidence = {"principal": "alice"}
    enforcer.guard_memory_write(agent_slug="support-triage", content="Prefers email contact.")
    assert "unbound-memory" in codes(seeded, "context_integrity")


def test_memory_binding_stays_quiet_without_a_declared_principal(seeded, enforcer):
    """Nothing to compare against, so nothing is claimed."""
    enforcer.evidence = {}
    enforcer.guard_memory_write(
        agent_slug="support-triage", content="Prefers email contact.", subject="bob"
    )
    assert findings_of(seeded, "context_integrity") == []


# --- F8.4 assembly stays the caller's step --------------------------------


def test_assemble_context_is_exposed_but_never_faked_inside_evaluate(enforcer, agent):
    """It needs the ranked chunks and the real token budget, and it repairs as well as
    reports. Manufacturing an assembly step inside `evaluate()` would measure a fit this
    code had just invented."""
    # A budget too small to seat the required chunk at all. (At a budget that *can*
    # hold it the module seats it first and reports plain `context-truncated` — the
    # required passage is protected, which is the behaviour its own tests pin.)
    assembly = Enforcer.assemble_context(
        [{"text": "x" * 400} for _ in range(10)], budget_tokens=50, required=[7]
    )
    assert "required-evidence-truncated" in {f.code for f in assembly.findings}

    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content=CLEAN_PROSE,
        surface="retrieved",
        taint_source="retrieved",
    )
    assert "assembly" not in result.taint


# --- The safety rule: observe-first ---------------------------------------


@pytest.mark.parametrize(
    ("content", "surface", "evidence"),
    [
        ("Your refund has been approved.", "output", {}),
        ("Take 400mg of ibuprofen every six hours.", "output", {}),
        (ORDINARY, "output", {"channel": "chat", "counterparty": "human"}),
        (
            "Your application was denied.",
            "output",
            {"decision": {"outcome": "denied", "reasons": [], "domain": "credit"}},
        ),
        ("The vendorâ€™s cafÃ© charge was Â£5.00.", "retrieved", {}),
    ],
)
def test_none_of_these_block_by_default(enforcer, agent, content, surface, evidence):
    """The product's whole stance is observe-first. Every one of these records a finding
    and returns an allow; none of them is a new hard-coded block."""
    enforcer.evidence = dict(evidence)
    result = enforcer.evaluate(agent=agent, identity=None, content=content, surface=surface)
    assert not result.blocked
    assert result.verdict == "allow"


def test_nothing_here_joins_the_hard_blocked_critical_risk_list(enforcer, agent):
    """`action["critical"]` is hard-blocked by the action-assurance branch. A register
    finding can be `critical` in its own vocabulary; it must not land there."""
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Take 400mg of ibuprofen every six hours.",
        surface="output",
    )
    assert result.taint["action"].get("critical", []) == []
    ours = ("commitment.", "register.", "context.", "adverse_action.", "disclosure.")
    assert all(
        r["severity"] != "critical"
        for r in result.taint["action"]["risks"]
        if r["code"].startswith(ours)
    )


COMMITMENT_POLICY = """
key: f6-commitments
name: Unauthorised commitments are refused
version: 1
mode: enforce
default_effect: allow
fail_mode: open
scope:
  agents: ["*"]
rules:
  - id: commitment.binding
    description: The answer created an obligation nobody authorised.
    when:
      surface: [output]
      action_risk: "commitment.*"
    effect: block
    severity: high
    reason: "The response commits the company to something it was not authorised to promise."
    controls: [NOM-RTG-11]
"""


def test_a_policy_author_can_turn_a_commitment_into_a_block(seeded, enforcer, agent):
    """This is what makes the observe-first default honest rather than toothless: the
    finding is expressible through the existing `action_risk` condition, so an operator
    who wants commitments blocked writes one rule — no code change, no new channel."""
    save_policy(seeded, PolicyDocument.from_yaml(COMMITMENT_POLICY), bind_mode="enforce")
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Your refund has been approved and we'll credit your account by Friday.",
        surface="output",
    )
    assert result.blocked
    assert "commitment.binding" in [r["rule_id"] for r in result.rules_fired]


def test_the_same_policy_leaves_ordinary_answers_alone(seeded, enforcer, agent):
    save_policy(seeded, PolicyDocument.from_yaml(COMMITMENT_POLICY), bind_mode="enforce")
    result = enforcer.evaluate(agent=agent, identity=None, content=ORDINARY, surface="output")
    assert not result.blocked


# --- Latency ---------------------------------------------------------------


def test_the_added_work_is_bounded_on_oversized_content(enforcer):
    """These checks are deterministic and local, but they are linear in what they read:
    unbounded, a 405KB retrieved payload costs ~170ms against a 300ms budget. The scan
    is capped instead."""
    huge = CLEAN_PROSE * 2_000
    assert len(huge) > 400_000
    enforcer.evidence = {"chunks": [{"text": CLEAN_PROSE} for _ in range(500)]}

    started = time.perf_counter()
    for _ in range(5):
        enforcer._commitment_checks(None, "output", huge, None)
        enforcer._context_checks("retrieved", huge, None)
    elapsed_ms = ((time.perf_counter() - started) / 5) * 1000
    assert elapsed_ms < 60, f"F6+F8 cost {elapsed_ms:.1f}ms on a 400KB payload"


def test_the_cap_is_a_documented_limit_not_a_silent_one(enforcer, agent):
    """A commitment buried past the scan cap is a case this honestly does not cover.
    Asserting it keeps the limitation visible instead of letting a future reader assume
    full coverage."""
    buried = ("filler sentence. " * 3_000) + "Your refund has been approved."
    assert len(buried) > 32_000
    result = enforcer.evaluate(agent=agent, identity=None, content=buried, surface="output")
    assert "commitments" not in result.taint
