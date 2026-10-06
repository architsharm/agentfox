"""Ragas scorer adapter. 3 of 11 use it for retrieval evaluation.

This is a vocabulary adapter, not a capability import. Teams evaluating RAG describe
quality in Ragas terms — faithfulness, answer relevancy, context precision, context
recall — and asking them to re-learn our scorer names to adopt governance is friction
for no benefit. The names are theirs; the numbers are computed here, so an offline
install still produces them.

Where Ragas itself is installed and egress is allowed, `run_ragas` delegates to it:
their model-based implementations are better than our lexical ones, and pretending
otherwise would overstate what lexical groundedness can do. The native path exists
so the metrics are *available* offline, not so we can claim parity —
`implementation` is reported on every result for exactly that reason.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agentfox.capabilities.evaluation.scorers import (
    BaseScorer,
    ScoreContext,
    ScoreResult,
    content_tokens,
    register_scorer,
    sentences,
)

log = logging.getLogger(__name__)

#: Their names, in their order. A team reading a AgentFox report should recognise it.
RAGAS_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def ragas_available() -> bool:
    try:  # pragma: no cover - exercised only where ragas is installed
        import ragas  # noqa: F401

        return True
    except Exception:
        return False


@dataclass
class RagasSample:
    question: str
    answer: str
    contexts: list[str] = field(default_factory=list)
    ground_truth: str = ""


@dataclass
class RagasScores:
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    implementation: str = "native-lexical"

    def to_json(self) -> dict[str, Any]:
        return {
            "faithfulness": round(self.faithfulness, 4),
            "answer_relevancy": round(self.answer_relevancy, 4),
            "context_precision": round(self.context_precision, 4),
            "context_recall": round(self.context_recall, 4),
            # Named on every result: our lexical implementation is weaker than theirs
            # and a consumer of these numbers is entitled to know which produced them.
            "implementation": self.implementation,
        }


def _overlap(claim: str, corpus: str) -> float:
    claim_tokens = content_tokens(claim)
    if not claim_tokens:
        return 1.0
    corpus_tokens = content_tokens(corpus)
    return len(claim_tokens & corpus_tokens) / len(claim_tokens)


def native_scores(sample: RagasSample) -> RagasScores:
    """Lexical approximations, computed offline.

    Deliberately the same mechanics as our groundedness scorer, so a team comparing
    the two does not get two different numbers for the same underlying judgement.
    """
    context = " ".join(sample.contexts)

    supported = [s for s in sentences(sample.answer) if _overlap(s, context) >= 0.6]
    total = max(1, len(sentences(sample.answer)))
    faithfulness = len(supported) / total if sample.contexts else 0.0

    answer_relevancy = _overlap(sample.question, sample.answer) if sample.question else 0.0

    useful = [c for c in sample.contexts if _overlap(sample.answer, c) >= 0.2]
    context_precision = len(useful) / len(sample.contexts) if sample.contexts else 0.0

    context_recall = (
        _overlap(sample.ground_truth, context) if sample.ground_truth and sample.contexts else 0.0
    )

    return RagasScores(
        faithfulness=faithfulness,
        answer_relevancy=answer_relevancy,
        context_precision=context_precision,
        context_recall=context_recall,
    )


def score_sample(sample: RagasSample, *, prefer_ragas: bool = True) -> RagasScores:
    """One sample, scored in Ragas vocabulary.

    Delegates to Ragas when it is installed, because their model-based metrics are
    better than our lexical ones. The native path keeps the vocabulary available
    offline rather than claiming equivalence.
    """
    if prefer_ragas and ragas_available():  # pragma: no cover - needs ragas + a model
        try:
            return _delegate(sample)
        except Exception as exc:
            log.warning("ragas delegation failed, falling back to native: %s", exc)
    return native_scores(sample)


def _delegate(sample: RagasSample) -> RagasScores:  # pragma: no cover - needs ragas
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    dataset = Dataset.from_dict(
        {
            "question": [sample.question],
            "answer": [sample.answer],
            "contexts": [sample.contexts],
            "ground_truth": [sample.ground_truth],
        }
    )
    result = evaluate(
        dataset, metrics=[faithfulness, answer_relevancy, context_precision, context_recall]
    )
    scores = result.to_pandas().iloc[0]
    return RagasScores(
        faithfulness=float(scores.get("faithfulness", 0.0)),
        answer_relevancy=float(scores.get("answer_relevancy", 0.0)),
        context_precision=float(scores.get("context_precision", 0.0)),
        context_recall=float(scores.get("context_recall", 0.0)),
        implementation="ragas",
    )


def score_dataset(samples: list[RagasSample], *, prefer_ragas: bool = True) -> dict[str, Any]:
    """Aggregate over a dataset, reporting the per-sample floor alongside the mean.

    The mean is what Ragas reports and what teams expect. The minimum is what matters
    for governance: one unfaithful answer in a hundred is not an acceptable average,
    it is an incident waiting for a user to find it.
    """
    if not samples:
        return {"samples": 0, "metrics": {}, "implementation": "none"}
    scored = [score_sample(s, prefer_ragas=prefer_ragas) for s in samples]
    metrics: dict[str, Any] = {}
    for name in RAGAS_METRICS:
        values = [getattr(s, name) for s in scored]
        metrics[name] = {
            "mean": round(sum(values) / len(values), 4),
            "min": round(min(values), 4),
            "below_0_7": sum(1 for v in values if v < 0.7),
        }
    return {
        "samples": len(samples),
        "metrics": metrics,
        "implementation": scored[0].implementation,
        "per_sample": [s.to_json() for s in scored],
    }


# ---------------------------------------------------------------------------
# Ragas metrics as selectable scorers (not just a standalone report)
# ---------------------------------------------------------------------------


def _context_list(ctx: ScoreContext) -> list[str]:
    """Retrieved context, from wherever the harness put it — same keys the
    groundedness scorer already checks, so a case only has to supply this once."""
    for key in ("retrieved", "context", "documents", "sources"):
        value = ctx.context.get(key)
        if isinstance(value, list) and value:
            return [
                v if isinstance(v, str) else str(v.get("text") or v.get("content") or "")
                for v in value
            ]
        if isinstance(value, str) and value.strip():
            return [value]
    return []


def _ragas_sample(output: str, ctx: ScoreContext) -> RagasSample:
    return RagasSample(
        question=str(ctx.case_input.get("input") or ctx.case_input.get("question") or ""),
        answer=output,
        contexts=_context_list(ctx),
        ground_truth=str(ctx.expected.get("output") or ctx.expected.get("ground_truth") or ""),
    )


class _RagasMetricScorer(BaseScorer):
    """One selectable scorer per Ragas metric, named exactly as Ragas names it —
    a team already fluent in Ragas vocabulary shouldn't have to relearn ours.
    Falls back to the native lexical approximation where the real `ragas` package
    isn't installed; `detail.implementation` on every result says which ran."""

    metric: str = ""
    kind = "ragas"
    threshold = 0.7

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        scores = score_sample(_ragas_sample(output, ctx))
        value = getattr(scores, self.metric)
        return self._result(value, implementation=scores.implementation)


class RagasFaithfulnessScorer(_RagasMetricScorer):
    key, metric = "ragas_faithfulness", "faithfulness"


class RagasAnswerRelevancyScorer(_RagasMetricScorer):
    key, metric = "ragas_answer_relevancy", "answer_relevancy"


class RagasContextPrecisionScorer(_RagasMetricScorer):
    key, metric = "ragas_context_precision", "context_precision"


class RagasContextRecallScorer(_RagasMetricScorer):
    key, metric = "ragas_context_recall", "context_recall"


for _rs in (
    RagasFaithfulnessScorer(),
    RagasAnswerRelevancyScorer(),
    RagasContextPrecisionScorer(),
    RagasContextRecallScorer(),
):
    register_scorer(_rs)
