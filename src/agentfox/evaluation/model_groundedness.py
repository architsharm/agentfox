"""P4-3 — model-based groundedness, alongside the lexical scorer.

`silent_failure.py::groundedness` is deliberately lexical — numeric agreement plus
token overlap, cheap enough to run inline. Its own docstring names exactly what that
buys and what it costs: "this is grounding, not entailment: it will not catch a
fabricated claim phrased entirely in the context's own words and numbers." A claim
that reuses the context's vocabulary while changing what it asserts scores as fully
supported, because token overlap cannot see the substitution.

This is the second opinion that gap was always going to need, and it is built the
same way every other model call in this codebase already is: through
`ModelProvider.judge()` — the exact mechanism `evaluation/scorers.py::LlmJudgeScorer`
already uses for rubric-based judging, not a new prompt-and-parse scheme invented for
this one scorer. The rubric is the retrieved context plus an instruction to judge
strictly against it; everything about *how* that gets scored (provider selection,
model pinning for reproducibility, the deterministic offline fallback) is
`LlmJudgeScorer`'s own established contract, reused rather than duplicated.

Offline, the pinned judge is `echo:deterministic`, same as `LlmJudgeScorer` — honest
about what that is (rubric-keyword coverage, `providers/echo.py::judge`'s own words:
"not a substitute for a model judge"), not a claim of model-level judgment. A team
that wants the real thing configures a real provider, exactly as they already do for
`llm_judge` and for Ragas's model-based path in `ragas_adapter.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from agentfox.providers import get_provider
from agentfox.evaluation.scorers import BaseScorer, ScoreContext, ScoreResult, register_scorer
from agentfox.evaluation.silent_failure import groundedness

log = logging.getLogger(__name__)

_RUBRIC_TEMPLATE = (
    "Score, from 0.0 to 1.0, how well the output is supported by the reference "
    "context below. 1.0 means every factual claim, number and named entity in the "
    "output is verifiable against the context; 0.0 means the output introduces "
    "facts the context does not state. Judge strictly against the context given — "
    "outside knowledge, even if true, does not count as support.\n\n"
    "Reference context:\n{context}"
)


def _context_text(ctx: ScoreContext) -> str:
    """Retrieved context for grounding, from wherever the harness put it — the same
    keys `silent_failure.py`'s lexical scorer reads, reimplemented locally rather
    than importing that module's private helper (the same choice
    `ragas_adapter.py::_context_list` already made for the identical question)."""
    for key in ("retrieved", "context", "documents", "sources"):
        value = ctx.context.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            parts = [
                v if isinstance(v, str) else str(v.get("text") or v.get("content") or "")
                for v in value
            ]
            joined = "\n".join(p for p in parts if p)
            if joined.strip():
                return joined
    return ""


def model_groundedness(
    output: str, context_text: str, *, judge_model: str = "echo:deterministic"
) -> dict[str, Any]:
    """The judge verdict, with a lexical fallback if the call itself fails.

    A scoring signal that can crash an eval run is worse than a weaker one, so a
    provider error falls back to the lexical scorer rather than propagating —
    `implementation`/`judge_model` on the result says which one actually ran, the
    same disclosure `ragas_adapter.py` makes when its own delegation fails.
    """
    if not context_text.strip():
        # Nothing to be grounded against, and nothing a judge could check either —
        # the lexical scorer's own reading of an empty context ("not a failure").
        return {
            "score": 1.0,
            "rationale": "no retrieved context; nothing to judge",
            "judge_model": judge_model,
        }

    provider_key, _, model = judge_model.partition(":")
    try:
        provider = get_provider(provider_key)
        verdict = provider.judge(
            output=output,
            rubric=_RUBRIC_TEMPLATE.format(context=context_text[:6000]),
            model=model or "default",
        )
        return {
            "score": float(verdict["score"]),
            "rationale": verdict.get("rationale", ""),
            "judge_model": judge_model,
        }
    except Exception as exc:  # a judge call must not be able to fail the eval run
        log.warning("model groundedness judge call failed, falling back to lexical: %s", exc)
        report = groundedness(output, context_text)
        return {
            "score": report.score,
            "rationale": f"judge call failed ({exc}); fell back to lexical scoring",
            "judge_model": "native-lexical",
            "unsupported_claims": report.unsupported[:10],
        }


class ModelGroundednessScorer(BaseScorer):
    """Selectable alongside `groundedness` (`silent_failure.py`), not a replacement
    for it — an eval suite can run both and see where they disagree, which is itself
    a signal: the lexical scorer full-marking something the judge flags is exactly
    the paraphrased-fabrication case neither one alone is enough to catch."""

    key, kind, threshold = "model_groundedness", "groundedness", 0.7

    def __init__(self, judge_model: str = "echo:deterministic") -> None:
        self.judge_model = judge_model

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        result = model_groundedness(output, _context_text(ctx), judge_model=self.judge_model)
        return self._result(result["score"], **{k: v for k, v in result.items() if k != "score"})


register_scorer(ModelGroundednessScorer())

__all__ = ["model_groundedness", "ModelGroundednessScorer"]
