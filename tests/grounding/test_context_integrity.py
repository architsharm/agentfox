"""P14 — the gates on the middle of the pipe.

Every one of these failures is invisible from the far end of the pipeline. The model
answers fluently from a destroyed context, groundedness confirms the answer matches
that context, and nothing anywhere reports a problem. So the tests are written the way
the failures actually arrive: a real mojibake string, a real mid-sentence split, a real
budget that cannot hold the citation.

The last test in each section is the one that matters most — the false-positive floor.
A gate that fires on ordinary text gets switched off in week two.
"""

from __future__ import annotations

import pytest

from agentfox.grounding.context_integrity import (
    DEGRADED,
    REJECT,
    Assembly,
    assemble_context,
    assess_context,
    chunk_quality,
    document_quality,
    estimate_tokens,
    evaluate_retrieval,
    memory_binding_breach,
    retrieval_drift,
    retrieval_metrics,
    worst,
)

CLEAN = (
    "Refunds under $10 are auto-approved. Refunds between $10 and $100 must run a "
    "fraud check before proceeding. Refunds over $100 require approval from the "
    "finance team, and the approval is recorded against the original transaction."
)


def codes(findings) -> set[str]:
    return {f.code for f in findings}


# --- Corrupt ingestion (L2.14) and encoding failure (L2.9) -----------------


def test_mojibake_is_refused_before_it_becomes_authoritative():
    """UTF-8 read as latin-1 is the quietest corruption there is.

    The text stays readable, so nobody notices, and every term the retriever matches on
    is now spelled differently from the query.
    """
    quality = document_quality("The vendorâ€™s cafÃ© charge was Â£5.00.", source_key="s1")
    assert "mojibake" in codes(quality.findings)


def test_a_binary_read_as_text_is_rejected():
    quality = document_quality("\x00\x01\x02 garbage \x07\x08" * 40)
    assert not quality.usable
    assert "control-characters" in codes(quality.findings)


def test_lost_spaces_are_caught_even_though_the_text_looks_fine():
    """A PDF extractor that drops the space glyph produces text a human can still read
    and a retriever cannot match a single term in."""
    quality = document_quality(
        "Thecustomerrequestedarefundoftwohundreddollarsonthethirdofmarch. " + CLEAN
    )
    assert "lost-word-boundaries" in codes(quality.findings)


def test_unknown_characters_are_reported():
    quality = document_quality("The name is ��� and the amount is [UNK].")
    assert "unknown-characters" in codes(quality.findings)


def test_an_empty_extraction_is_not_an_empty_success():
    quality = document_quality("   \n  ")
    assert not quality.usable
    assert quality.score == 0.0


def test_clean_prose_produces_no_document_findings():
    """The false-positive floor. Ordinary English, ordinary punctuation, no findings."""
    assert document_quality(CLEAN).findings == []
    assert document_quality(CLEAN).score == 1.0


@pytest.mark.parametrize(
    "text",
    [
        "Der Kunde hat eine Rückerstattung über 200 € angefordert.",
        "Le client a demandé un remboursement de 200 € le troisième jour.",
        "Клиент запросил возврат средств в размере двухсот долларов.",
        "顧客は三月三日に二百ドルの払い戻しを要求しました。",
    ],
)
def test_non_latin_text_is_not_mistaken_for_corruption(text):
    """The check that catches encoding damage must not fire on languages.

    An earlier confusable-folding bug in this codebase destroyed Russian text by
    treating a script it did not expect as an attack; the same mistake here would
    reject every non-English document in the corpus.
    """
    assert document_quality(text).findings == []


# --- Chunk coherence (L2.8) ------------------------------------------------


def test_a_sentence_split_across_chunks_is_caught():
    """Neither half answers the question the whole sentence answered.

    Retrieval returns the fragment, groundedness confirms the answer matches the
    fragment, and the exception the other half carried is simply gone.
    """
    findings = chunk_quality(
        [
            "Refunds are approved automatically unless the amount",
            "exceeds $100, in which case the finance team signs off.",
        ]
    )
    assert {"split-sentence-end", "split-sentence-start"} <= codes(findings)
    assert worst(findings) == "abstain"


def test_a_boundary_inside_a_code_block_is_caught():
    findings = chunk_quality(
        [
            "Run the migration with this command, which is safe to repeat:\n"
            "```bash\nalembic upgrade head",
            "```\nThen restart the workers so they pick up the new schema version.",
        ]
    )
    assert "split-code-fence" in codes(findings)


def test_a_bare_heading_reports_once_not_three_times():
    """A heading is not a broken sentence.

    Checking it as one produced an orphan finding, a split-sentence finding and a
    heading finding for a chunk with a single, different problem.
    """
    findings = chunk_quality(["## Section 4. Refund limits"])
    assert codes(findings) == {"heading-without-body"}


def test_well_formed_chunks_produce_nothing():
    """The false-positive floor for chunking."""
    assert (
        chunk_quality(
            [
                "Refunds under $10 are auto-approved by the system without review.",
                "Refunds over $100 require approval from the finance team before proceeding.",
            ]
        )
        == []
    )


# --- Truncation (L2.10) and position (L2.11) -------------------------------


def test_dropping_cited_evidence_is_a_different_failure_from_dropping_the_tail():
    """The model is being asked to support a claim from evidence it cannot see."""
    chunks = [{"text": "x" * 400} for _ in range(8)]
    result = assemble_context(chunks, budget_tokens=120, required=[7])
    assert result.kept == [7], "a required chunk must be seated before the ranking"

    starved = assemble_context(chunks, budget_tokens=50, required=[7])
    finding = next(f for f in starved.findings if f.code == "required-evidence-truncated")
    assert finding.severity == REJECT
    assert finding.verdict == "block"


def test_a_required_chunk_is_seated_before_lower_ranked_ones():
    """Filling the budget in rank order drops the one passage the answer needs
    because two lower-ranked chunks happened to come first."""
    chunks = [{"text": "y" * 300} for _ in range(5)]
    result = assemble_context(chunks, budget_tokens=200, required=[4])
    assert 4 in result.kept


def test_long_contexts_are_reordered_so_the_best_evidence_is_not_in_the_middle():
    chunks = [{"text": f"passage {i}. " * 5} for i in range(6)]
    result = assemble_context(chunks, budget_tokens=10_000)
    assert result.dropped == []
    assert result.order != result.kept
    assert result.order[0] == 0, "the top-ranked passage belongs at the front"
    assert result.order[-1] == 1, "the second belongs at the other edge"
    assert sorted(result.order) == result.kept, "reordering must not lose a chunk"


def test_a_context_that_fits_reports_no_truncation():
    """The false-positive floor for assembly."""
    result = assemble_context([{"text": "short passage."} for _ in range(3)], budget_tokens=5_000)
    assert result.dropped == []
    assert result.findings == []


def test_token_estimate_is_conservative():
    """Under-estimating cost drops evidence silently, so the estimate must not be
    cheaper than a real tokeniser would be."""
    assert estimate_tokens("hello world") >= 3
    assert estimate_tokens("") == 0


# --- Retrieval drift (L2.13) -----------------------------------------------


def test_ndcg_falls_when_the_right_passage_slides_down_the_ranking():
    """Recall cannot see this failure and it is the failure that matters.

    A passage at rank 9 is past where a truncated context reaches, but recall@10 counts
    it exactly the same as rank 1.
    """
    good = retrieval_metrics(["target", "a", "b", "c"], {"target"})
    bad = retrieval_metrics(["a", "b", "c", "target"], {"target"})
    assert good["recall"] == bad["recall"] == 1.0
    assert good["ndcg"] > bad["ndcg"]


def test_an_embedding_change_that_regresses_retrieval_is_reported():
    baseline = evaluate_retrieval([(["t", "a", "b"], {"t"}), (["t", "c", "d"], {"t"})])
    current = evaluate_retrieval([(["a", "b", "t"], {"t"}), (["c", "d", "t"], {"t"})])
    finding = retrieval_drift(current, baseline)
    assert finding is not None
    assert finding.code == "retrieval-regression"
    assert finding.severity in (DEGRADED, REJECT)


def test_an_unchanged_pipeline_reports_no_drift():
    """The false-positive floor for drift."""
    metrics = evaluate_retrieval([(["t", "a"], {"t"})])
    assert retrieval_drift(metrics, metrics) is None


def test_noise_below_the_tolerance_is_not_a_regression():
    assert retrieval_drift({"ndcg": 0.88}, {"ndcg": 0.90}, tolerance=0.05) is None


# --- Memory binding (L2.12) ------------------------------------------------


def test_memory_about_one_end_user_never_surfaces_for_another():
    """Tenant isolation cannot catch this and is not meant to.

    A shared assistant holds memory for thousands of end users inside one org; the
    boundary that matters is the subject the memory is about.
    """
    findings = memory_binding_breach([{"key": "pref", "subject": "bob"}], principal="alice")
    assert codes(findings) == {"cross-subject-memory"}
    assert findings[0].verdict == "block"


def test_memory_with_no_subject_is_reported_rather_than_allowed():
    """It was written by someone, about someone, and nothing records who."""
    findings = memory_binding_breach([{"key": "note"}], principal="alice")
    assert "unbound-memory" in codes(findings)


def test_shared_memory_is_allowed_through():
    assert memory_binding_breach([{"key": "policy", "shared": True}], principal="alice") == []


def test_the_end_users_own_memory_is_not_flagged():
    """The false-positive floor for memory."""
    assert (
        memory_binding_breach(
            [{"key": "pref", "subject": "alice", "session": "s1"}],
            principal="alice",
            session_id="s1",
        )
        == []
    )


# --- Aggregate -------------------------------------------------------------


def test_a_gate_with_no_input_does_not_pass_it_silently():
    """Every input beyond the chunks is optional, and a gate that did not run must not
    read as a gate that passed."""
    result = assess_context(["A complete and well-formed passage about refunds."])
    assert result.findings == []
    assert result.assembly is None, "no budget was given, so no assembly was computed"


def test_the_aggregate_reports_the_worst_verdict_it_found():
    result = assess_context(
        ["Refunds are approved unless the amount", "exceeds $100 and finance signs off."],
        documents={"s1": "The vendorâ€™s charge was Â£5."},
        memory=[{"key": "k", "subject": "bob"}],
        principal="alice",
    )
    assert result.verdict == "block"
    assert {"mojibake", "cross-subject-memory"} <= codes(result.findings)
    assert result.to_json()["verdict"] == "block"


def test_a_clean_pipeline_end_to_end_is_silent():
    result = assess_context(
        [
            "Refunds under $10 are auto-approved by the system without review.",
            "Refunds over $100 require approval from the finance team before proceeding.",
        ],
        budget_tokens=5_000,
        documents={"policy": CLEAN},
        memory=[{"key": "pref", "subject": "alice"}],
        principal="alice",
    )
    assert result.findings == []
    assert result.verdict == "allow"
    assert isinstance(result.assembly, Assembly)
