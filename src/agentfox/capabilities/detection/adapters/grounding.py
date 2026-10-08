"""Model-based grounding: is each claim in the answer supported by the context?

The built-in grounding check (`grounding/checks.py`) compares words, which is fast,
offline and fooled by paraphrase — the reason the competitor analysis calls our
groundedness "behind, not ahead". This adapter asks a natural-language-inference
model instead: for each sentence of the answer, does the retrieved context entail it?

* Model: an NLI cross-encoder via plain `transformers` (Apache-2.0
  `cross-encoder/nli-deberta-v3-small` by default, `grounding_nli_model`), loaded
  from local files only — never downloaded at request time. Models that need
  `trust_remote_code` are deliberately not supported: running code fetched with the
  weights is not a trade a governance layer should make on a customer's behalf.
* Input: the context the answer was built from, which the caller supplies
  (`evidence["chunks"]`, or `context` on `/v1/guard/output`). With none, there is no
  claim to check and it returns nothing.
* Output: one `GROUNDING.UNSUPPORTED` detection for the least-supported sentence,
  scored 1 − P(entailment). The `agent-integrity` pack's rule acts on it, and is the
  showcase for re-asking instead of refusing.

Opt-in: off until a workspace turns it on (Policies → Library → Detectors).
"""

from __future__ import annotations

import functools
import re

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    redact_sample,
)
from agentfox.core.config import get_settings

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
MAX_SENTENCES = 8
MAX_CONTEXT_CHARS = 2000


class GroundingNliDetector(BaseDetector):
    key = "grounding.nli"
    version = "1.0"
    surfaces = ("output",)
    covers_threats = ("LLM09",)  # OWASP LLM Top 10: misinformation
    # A cross-encoder pass per sentence; declared so the pipeline gives it a real
    # allowance (and its own pool) instead of the regex detectors' default.
    timeout_ms = 400
    handles_views = True

    def __init__(self, model_id: str | None = None, *, threshold: float = 0.5) -> None:
        self.model_id = model_id or get_settings().grounding_nli_model
        self.threshold = threshold

    def available(self) -> bool:
        try:
            import transformers  # noqa: F401
        except Exception:
            return False
        return self._weights_present()

    def _weights_present(self) -> bool:  # pragma: no cover - requires optional dep
        try:
            from huggingface_hub import try_to_load_from_cache

            return try_to_load_from_cache(self.model_id, "config.json") is not None
        except Exception:
            return False

    @functools.cached_property
    def _pipeline(self):  # pragma: no cover - requires optional dependency
        from transformers import pipeline

        return pipeline(
            "text-classification", model=self.model_id, top_k=None, local_files_only=True
        )

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        if self.available():
            _ = self._pipeline

    def entailment(
        self, premise: str, hypothesis: str
    ) -> float:  # pragma: no cover - optional model
        scores = self._pipeline({"text": premise, "text_pair": hypothesis})
        if scores and isinstance(scores[0], list):
            scores = scores[0]
        return next((s["score"] for s in scores if "entail" in s["label"].lower()), 0.0)

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        passages = [p for p in (context.extra or {}).get("context") or [] if p and p.strip()]
        if not passages or not content.strip():
            return []
        premise = " ".join(passages)[:MAX_CONTEXT_CHARS]
        sentences = [s for s in _SENTENCE.split(content.strip()) if len(s.split()) >= 4][
            :MAX_SENTENCES
        ]
        worst, worst_sentence = 0.0, ""
        for sentence in sentences:
            unsupported = 1.0 - self.entailment(premise, sentence)
            if unsupported > worst:
                worst, worst_sentence = unsupported, sentence
        if worst < self.threshold:
            return []
        start = content.find(worst_sentence)
        return [
            Detection(
                entity_type="GROUNDING.UNSUPPORTED",
                score=round(worst, 3),
                start=max(start, 0),
                end=max(start, 0) + len(worst_sentence),
                sample=redact_sample(worst_sentence, keep=24),
                detail={"model": self.model_id, "sentences_checked": len(sentences)},
            )
        ]
