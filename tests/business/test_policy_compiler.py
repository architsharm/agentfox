"""The compiler is judged on two numbers, and both matter.

How much it compiles without asking, and whether the things it does ask about are
genuinely ambiguous. A compiler that flags everything is a transcription form with
extra steps; one that flags nothing is guessing at thresholds that move money. So
these tests come in two halves: documents that must compile clean, and documents
that must stop and ask.
"""

from __future__ import annotations

import pytest

from agentfox.business.compile import compile_document
from agentfox.business.ladder import Ladder, evaluate


def _ladder(compilation):
    return next(r for r in compilation.rules if r.kind == "threshold_ladder")


# --- The half that must compile without asking -----------------------------


def test_three_band_policy_compiles_whole():
    c = compile_document(
        "Refunds under $10 are auto-approved. Refunds between $10 and $100 must run "
        "a fraud check before proceeding, and refunds over $100 require approval "
        "from the finance team.",
        key_prefix="r",
    )
    assert not c.review, [i.question for i in c.review]
    bands = _ladder(c).definition["bands"]
    assert [b.get("upto") for b in bands] == [10.0, 100.0, None]
    assert [b["outcome"] for b in bands] == ["allow", "verify", "escalate"]
    assert bands[2]["approver_role"] == "finance"


def test_wrapped_lines_do_not_split_a_phrase():
    """A policy pasted from a PDF wraps mid-phrase, and the middle band vanished.

    'fraud\\ncheck' never matched the literal 'fraud check', so the clause carrying
    the entire middle band was dropped and the ladder silently sent everything under
    $100 straight to allow.
    """
    wrapped = compile_document(
        "Refunds under $10 are auto-approved. Refunds between $10 and $100 must run a fraud\n"
        "check before proceeding, and refunds over $100 require approval from the finance team.",
        key_prefix="r",
    )
    assert len(_ladder(wrapped).definition["bands"]) == 3


def test_scale_suffix_must_be_a_whole_word():
    """'$100 must' read the m of 'must' as 'million'.

    A hundred-dollar approval threshold became a hundred-million-dollar one — in the
    direction that approves more, and with no warning anywhere.
    """
    c = compile_document(
        "Refunds under $10 are auto-approved. Refunds between $10 and $100 must run a "
        "fraud check first, and refunds over $100 require finance approval.",
        key_prefix="r",
    )
    assert _ladder(c).definition["bands"][1]["upto"] == 100.0


@pytest.mark.parametrize(
    ("sentence", "kind", "expected"),
    [
        (
            "Agents must never disclose salary data to anyone outside HR.",
            "entitlement_filter",
            {"protected_subjects": ["salary"], "permitted_roles": ["hr"], "default": "deny"},
        ),
        (
            "The agent must only cite the approved source of truth for pricing questions.",
            "source_authority",
            {"required_tier": "system_of_record", "topic": "pricing"},
        ),
        (
            "No destructive queries may be run against the production database.",
            "action_analysis",
            {"environments": ["production"]},
        ),
        (
            "Any conversation where the customer becomes frustrated should be "
            "escalated to a human supervisor.",
            "escalation_policy",
            {"sentiment_below": 0.3, "to_role": "manager"},
        ),
        (
            "Never reveal a customer's credit card or phone number.",
            "pii_detection",
            {"entities": ["CREDIT_CARD", "PHONE_NUMBER"], "redaction": "mask"},
        ),
    ],
)
def test_non_threshold_rules_carry_real_parameters(sentence, kind, expected):
    """Naming the guardrail is not compiling it.

    An earlier version emitted {kind, from_sentence} for every one of these. It scored
    as compiled on the coverage report and enforced nothing at runtime.
    """
    c = compile_document(sentence, key_prefix="p")
    rule = next(r for r in c.rules if r.kind == kind)
    for key, value in expected.items():
        assert rule.definition[key] == value, f"{key}: {rule.definition}"
    assert set(rule.definition) - {"kind"}, "definition has no parameters"


def test_prohibitions_without_a_modal_verb_are_governance():
    """'No X may be run' carries no must/should/never and was being ignored.

    The strongest sentence in a policy is often written as a flat prohibition.
    """
    c = compile_document("No destructive queries may be run against production.")
    assert c.rules and not c.ignored


def test_boundary_ownership_is_assumed_not_asked():
    """'under $10' and 'between $10 and $100' disagree about who owns exactly 10.

    Both readings are defensible, but only one leaves no gap, so this is stated as an
    assumption rather than queued as a question.
    """
    c = compile_document(
        "Refunds under $10 auto-approve. Refunds between $10 and $100 need a fraud "
        "check. Refunds over $100 need finance approval.",
        key_prefix="r",
    )
    assert not c.review
    assert any("inclusive" in a.what for a in _ladder(c).assumptions)


def test_compiled_ladder_is_loadable_and_total():
    """The output has to survive the real validator, not just look plausible."""
    c = compile_document(
        "Refunds under $10 auto-approve, refunds between $10 and $100 require a fraud "
        "check, and refunds over $100 require finance approval.",
        key_prefix="r",
    )
    ladder = Ladder.model_validate(_ladder(c).definition)
    for amount, expected in ((5, "allow"), (50, "verify"), (5000, "escalate")):
        request = {"tool": ladder.tool, "arguments": {"amount": amount}}
        assert evaluate(ladder, request).outcome == expected, amount


def test_prose_is_not_forced_into_a_rule():
    c = compile_document("Agents should be courteous and represent the company well.")
    assert not c.rules
    assert c.unmappable


# --- The half that must stop and ask ---------------------------------------


def test_mixed_currencies_are_a_question_not_a_conversion():
    c = compile_document(
        "Refunds under $10 auto-approve. Refunds over €100 require finance approval.",
        key_prefix="r",
    )
    assert not c.rules
    assert any("currency" in i.question.lower() for i in c.review)


def test_a_bare_number_asks_for_its_unit():
    c = compile_document(
        "Refunds under 10 auto-approve. Refunds over 100 require finance approval.",
        key_prefix="r",
    )
    assert any("unit" in i.question.lower() for i in c.review)


def test_an_unmapped_role_is_a_one_word_question():
    c = compile_document(
        "Refunds under $10 auto-approve. Refunds over $100 require approval from management.",
        key_prefix="r",
    )
    item = next(i for i in c.review if "management" in i.question)
    assert item.options
    assert item.source


def test_approval_with_no_threshold_is_flagged_as_unconditional():
    c = compile_document("All refunds require approval from the finance team.")
    assert any("every call" in i.question for i in c.review)


def test_a_recognised_guardrail_with_no_settings_asks_rather_than_emitting_a_stub():
    """A kind whose parameters cannot be read from the prose must not compile.

    This is the regression that matters most: the failure it replaces was silent.
    """
    c = compile_document("The agent must respect the configured spend budget.")
    assert not any(r.kind == "spend_budget" for r in c.rules)
    assert c.review or c.unmappable


def test_every_review_item_is_answerable_on_its_own():
    """A question a reviewer cannot answer without reading the whole document is a
    question that will sit in the queue."""
    c = compile_document(
        "Refunds under $10 auto-approve. Refunds over €100 require approval from "
        "management. All wire transfers require approval.",
        key_prefix="r",
    )
    assert c.review
    for item in c.review:
        assert item.question.endswith("?")
        assert item.source, item.question
        assert item.why, item.question


def test_auto_rate_counts_only_rules_that_enforce():
    c = compile_document(
        "Refunds under $10 auto-approve. Refunds between $10 and $100 need a fraud "
        "check. Refunds over $100 need finance approval. Agents must never disclose "
        "salary data to anyone outside HR. Agents should be courteous.",
        key_prefix="r",
    )
    assert c.auto_rate >= 0.75
    for rule in c.rules:
        assert set(rule.definition) - {"kind"}, f"{rule.key} enforces nothing"


# --- A document the compiler was not tuned against -------------------------
#
# Every number above was measured on one policy, and tuning against a single sample
# is how a compiler ends up fitting its own test. This one is a different domain in a
# different currency with different phrasing, and it is the reason the three bugs
# below were found at all.

HELD_OUT = """Vendor Payments and Data Handling Policy

Section 1. Payment authorisation.
Purchase orders below £500 may proceed without approval. Purchase orders from £500
to £5,000 must be validated against the approved vendor list. Anything in excess of
£5,000 needs sign-off from the legal team.

Section 2. Handling of personal information.
The assistant must never share an employee's home address or date of birth with an
external party. Personally identifiable information appearing in any reply must be
masked before it is returned.

Section 3. Retrieval.
When answering questions about vendor contracts the assistant may only rely on the
contract system of record, and the record must be no older than 24 hours.
The assistant must not answer questions about periods earlier than the last 36 months.

Section 4. Conduct.
Escalate to a human agent after 3 failed attempts to resolve the customer's issue.
No bulk deletes are permitted against the vendor database.
Aggregate figures must not be reported when fewer than 5 employees contribute.
The assistant should always strive to be helpful and professional.
"""


@pytest.fixture
def held_out():
    return compile_document(HELD_OUT, key_prefix="v")


def test_no_governance_sentence_is_ever_lost(held_out):
    """The failure this replaces was silent and total.

    Several sentences fed one ladder; the ladder stopped to ask which tool it governed;
    the question carried only the first sentence, and the rest were counted in no
    bucket at all. Two rules governing five-thousand-pound payments left no trace in
    the output, and the auto-compile rate went *up* as a result.
    """
    assert held_out.unaccounted() == []


def test_counts_are_not_swallowed_by_a_money_ladder(held_out):
    """'after 3 failed attempts' and 'fewer than 5 employees' are thresholds too.

    Both parsed as bands and were merged into the nearest currency ladder, which is
    how a retry limit became a payment tier.
    """
    kinds = {r.kind: r.definition for r in held_out.rules}
    assert kinds["escalation_policy"]["repeated_failure"] == 3
    assert kinds["aggregation_floor"]["k"] == 5
    assert kinds["knowledge_boundary"]["coverage_months"] == 36
    ladders = [r for r in held_out.rules if r.kind == "threshold_ladder"]
    for ladder in ladders:
        assert ladder.definition["unit"] == "GBP"


def test_the_kind_that_fits_beats_the_kind_that_scores(held_out):
    """ "PII in any reply must be masked" scores highest as an output contract.

    An output contract has nothing to extract from that sentence, so the compiler took
    the best-scoring kind, found no parameters, and raised a question — about a
    sentence the PII detector two places down reads exactly.
    """
    pii = [r for r in held_out.rules if r.kind == "pii_detection"]
    assert any("EMAIL_ADDRESS" in r.definition["entities"] for r in pii)
    assert not any("output contract" in i.question.lower() for i in held_out.review)


def test_a_question_names_its_subject(held_out):
    """ "Which tool does this govern?" cannot be answered without the document."""
    item = next(i for i in held_out.review if "tool" in i.question.lower())
    assert "purchase order" in item.question.lower()


def test_held_out_document_mostly_compiles(held_out):
    """The rate on unseen text, which is the only rate worth quoting.

    It is lower than on the tuned document and should be: the guard here is against
    regression, not a claim that prose is a solved problem.
    """
    assert held_out.auto_rate >= 0.6
    assert len(held_out.rules) >= 7
