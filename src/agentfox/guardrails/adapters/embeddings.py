"""Local vector-similarity detector (P3-1 companion).

The other two injection signals catch different things: `injection.heuristic`
matches phrasing it was told to look for; `injection.classifier` recognizes what
its training data looked like. This one recognizes *proximity to known attacks* —
embed the incoming text, compare it against a corpus of known attack and benign
examples by cosine similarity, and flag it when it sits close to an attack anchor
and meaningfully closer to that than to any benign one.

The corpus (`../data/injection_corpus.json`) is synthetic — authored from a
taxonomy of known injection/jailbreak intents, not derived from real user data or
from any benchmark dataset this detector is evaluated against (kept independent so
evaluation stays honest). It grows by editing that file and re-embedding; unlike
the classifier, there's no retraining step.

Everything happens locally: the embedding model runs on this machine, the corpus is
a bundled file, and the only network activity ever is the one-time model weights
download (same opt-in gate as the classifier — see `PromptInjectionClassifierDetector`).
No text is ever sent anywhere for this detector to work.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from ...config import get_settings
from ..base import BaseDetector, Detection, DetectionContext, redact_sample

_CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "injection_corpus.json"


def _load_corpus() -> tuple[list[str], list[str]]:
    data = json.loads(_CORPUS_PATH.read_text())
    return (
        [row["text"] for row in data["attack"]],
        [row["text"] for row in data["benign"]],
    )


class EmbeddingSimilarityDetector(BaseDetector):
    """Cosine-similarity match against a local corpus of known attack/benign
    examples — apache-2.0 `sentence-transformers/all-MiniLM-L6-v2`, ~22M params,
    loaded via plain `transformers` (mean-pooled last hidden state) rather than the
    `sentence-transformers` package, so it shares the `classifiers` extra's
    dependencies instead of adding a new one."""

    key = "injection.similarity"
    version = "1.0"
    surfaces = ("input", "retrieved", "tool_result", "output", "memory_write", "agent_message")
    # A real forward pass plus a corpus-sized matrix multiply — same reasoning as
    # injection.classifier's timeout_ms, including the measured 150ms figure.
    timeout_ms = 150

    def __init__(
        self,
        model_id: str | None = None,
        *,
        attack_threshold: float | None = None,
        benign_margin: float | None = None,
    ) -> None:
        settings = get_settings()
        self.model_id = model_id or settings.embedding_similarity_model
        # Explicit arguments still win (tests, benchmarks); otherwise the configured cut-off.
        self.attack_threshold = (
            settings.embedding_similarity_attack_threshold
            if attack_threshold is None
            else attack_threshold
        )
        self.benign_margin = (
            settings.embedding_similarity_benign_margin if benign_margin is None else benign_margin
        )

    def available(self) -> bool:
        try:
            import transformers  # noqa: F401
        except Exception:
            return False
        if not _CORPUS_PATH.exists():
            return False
        return self._weights_present()

    def _weights_present(self) -> bool:  # pragma: no cover - requires optional dep
        try:
            from huggingface_hub import try_to_load_from_cache

            return try_to_load_from_cache(self.model_id, "config.json") is not None
        except Exception:
            # NFR-4/NFR-9: never trigger a download at request time.
            return False

    @functools.cached_property
    def _model(self):  # pragma: no cover - requires optional dependency
        import torch
        from transformers import AutoModel, AutoTokenizer

        torch.set_num_threads(1)  # see injection.classifier's _pipeline for why
        # local_files_only: see `injection.classifier`'s `_pipeline`.
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
        model = AutoModel.from_pretrained(self.model_id, local_files_only=True)
        model.eval()
        return tokenizer, model

    def _embed(self, texts: list[str]):  # pragma: no cover - requires optional dependency
        import torch

        tokenizer, model = self._model
        encoded = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        with torch.no_grad():
            out = model(**encoded)
        mask = encoded["attention_mask"].unsqueeze(-1).float()
        summed = (out.last_hidden_state * mask).sum(1)
        counts = mask.sum(1).clamp(min=1e-9)
        mean_pooled = summed / counts
        return torch.nn.functional.normalize(mean_pooled, p=2, dim=1)

    @functools.cached_property
    def _corpus_embeddings(self):  # pragma: no cover - requires optional dependency
        attack_texts, benign_texts = _load_corpus()
        return attack_texts, self._embed(attack_texts), benign_texts, self._embed(benign_texts)

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        if self.available():
            self._corpus_embeddings

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        attack_texts, attack_embeddings, _benign_texts, benign_embeddings = self._corpus_embeddings
        query = self._embed([content])[0]

        attack_sims = attack_embeddings @ query
        benign_sims = benign_embeddings @ query
        best_attack_idx = int(attack_sims.argmax())
        best_attack_score = float(attack_sims[best_attack_idx])
        best_benign_score = float(benign_sims.max()) if len(benign_sims) else -1.0

        if best_attack_score < self.attack_threshold:
            return []
        if best_attack_score - best_benign_score < self.benign_margin:
            return []

        return [
            Detection(
                entity_type="INJECTION.SEMANTIC_SIMILARITY",
                score=best_attack_score,
                end=len(content),
                sample=redact_sample(content, keep=12),
                owasp_id="LLM01",
                detail={
                    "engine": self.key,
                    "model": self.model_id,
                    "nearest_attack": redact_sample(attack_texts[best_attack_idx], keep=20),
                    "attack_similarity": round(best_attack_score, 4),
                    "benign_similarity": round(best_benign_score, 4),
                },
            )
        ]
