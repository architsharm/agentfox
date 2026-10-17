"""Validators: local models.

Ported from the Guardrails AI hub validators that run a model on this machine (a
Hugging Face classifier, a zero-shot NLI model, a sentence-embedding model, GLiNER,
Presidio, COMET). Each class names its source in ``upstream``; the logic was rewritten
against our interface, without the ``guardrails`` package. Where upstream called a
hosted endpoint (Llama Guard, ShieldGemma) the port runs the same model locally.

The rules are the ones `adapters/classifiers.py` set for every model-backed check:

* Weights are read from the local cache only (``local_files_only``). ``available()`` is
  "the libraries import *and* the weights are already on disk"; absent weights mean
  unavailable, never "fetch it now". `agentfox admin detectors pull validator.<name>`
  downloads them on purpose.
* One torch thread per forward pass — the detector pipeline already parallelises
  across detectors (see `_TransformersClassifier._pipeline`).
* A model loads once per process, whichever validator asks first, under a lock.
* Models under a licence with usage restrictions (Llama, Gemma, CC-BY-NC) refuse to
  load unless ``AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1``, as
  `RestrictedClassifierDetector` does.

Upstream split text into sentences with nltk; :func:`split_sentences` is a small
stdlib splitter with the same intent, and reports real character offsets.
"""

from __future__ import annotations

import functools
import math
import os
import re
import statistics
import threading
from collections.abc import Callable, Sequence
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentfox.capabilities.detection.validators import register_validator
from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    Validator,
    span_finding,
)

Method = Literal["sentence", "full"]

# --------------------------------------------------------------------------- text


_ABBREVIATIONS = frozenset(
    "mr mrs ms dr prof sr jr st vs etc e.g i.e eg ie inc ltd co corp no fig al approx "
    "a.m p.m dept est jan feb mar apr jun jul aug sep sept oct nov dec u.s u.k".split()
)
#: Sentence-final punctuation (with any closing quote or bracket) before whitespace,
#: or a blank line.
_BOUNDARY = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s|$)|\n[ \t]*\n")
_LAST_WORD = re.compile(r"(\S+)$")


def _strip(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_sentences(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each sentence in `text`, without surrounding whitespace.

    Splits after ``.``, ``!`` or ``?`` followed by whitespace, and at blank lines; not
    after a common abbreviation ("Dr.", "e.g.") or a single initial ("J. Smith").
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        if m.group().rstrip("\"'”’)]") == ".":
            word = _LAST_WORD.search(text[start : m.start()])
            token = word.group(1).lower().lstrip("(\"'") if word else ""
            if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
                continue
        s, e = _strip(text, start, m.end())
        if e > s:
            spans.append((s, e))
        start = m.end()
    s, e = _strip(text, start, len(text))
    if e > s:
        spans.append((s, e))
    return spans


def _units(text: str, method: str) -> list[tuple[int, int]]:
    """What a ``validation_method`` checks: each sentence, or the whole text."""
    if method == "sentence":
        return split_sentences(text)
    s, e = _strip(text, 0, len(text))
    return [(s, e)] if e > s else []


def _whole(text: str, start: int, end: int) -> tuple[int, int]:
    """A span covering the whole text is reported as ``0, 0`` (the whole text)."""
    s, e = _strip(text, 0, len(text))
    return (0, 0) if (start, end) == (s, e) else (start, end)


def _finding(text: str, start: int, end: int, reason: str, score: float, **detail: Any):
    start, end = _whole(text, start, end)
    f = span_finding(text, start, end, reason, **detail) if end > start else Finding(reason)
    f.detail = dict(detail)
    f.score = max(0.0, min(1.0, float(score)))
    return f


# ------------------------------------------------------------------------ loading

_LOCK = threading.Lock()
_LOADED: dict[tuple[str, ...], Any] = {}


class ModelNotDownloaded(RuntimeError):
    """A model named in a validator's settings is not in the local cache."""


def _load(key: tuple[str, ...], build: Callable[[], Any]) -> Any:
    """Build something slow once per process, whoever asks first."""
    try:
        return _LOADED[key]
    except KeyError:
        pass
    with _LOCK:
        if key not in _LOADED:
            _LOADED[key] = build()
        return _LOADED[key]


def _cached_file(repo_id: str, filename: str = "config.json") -> str | None:
    """Path of `filename` from `repo_id` in the Hugging Face cache, or None.

    Never downloads: this is what ``available()`` asks (see `classifiers.py`).
    """
    try:
        from huggingface_hub import try_to_load_from_cache

        path = try_to_load_from_cache(repo_id, filename)
    except Exception:
        return None
    return path if isinstance(path, str) else None


def _restricted_allowed() -> bool:
    from agentfox.core.config import get_settings

    return bool(get_settings().restricted_models_allowed)


def _torch_one_thread() -> None:  # pragma: no cover - requires torch
    import torch

    # See `_TransformersClassifier._pipeline`: one thread per call, many calls.
    torch.set_num_threads(1)


def text_classifier(model_id: str) -> Any:  # pragma: no cover - requires weights
    """A ``text-classification`` pipeline returning every label's score."""

    def build() -> Any:
        from transformers import (
            AutoConfig,
            AutoModelForSequenceClassification,
            AutoTokenizer,
            PretrainedConfig,
            pipeline,
        )

        _torch_one_thread()
        raw, _ = PretrainedConfig.get_config_dict(model_id, local_files_only=True)
        labels = raw.get("id2label") or {}
        if any(not isinstance(v, str) for v in labels.values()):
            # Some hub configs name labels with integers ({"0": 0, "1": 1}), which
            # transformers 5 rejects outright. Read them as strings.
            raw["id2label"] = {int(k): str(v) for k, v in labels.items()}
            raw["label2id"] = {str(v): int(k) for k, v in labels.items()}
            config = AutoConfig.for_model(**raw)
            model = AutoModelForSequenceClassification.from_pretrained(
                model_id, config=config, local_files_only=True
            )
            tokenizer = AutoTokenizer.from_pretrained(
                model_id, config=config, local_files_only=True
            )
            return pipeline("text-classification", model=model, tokenizer=tokenizer, top_k=None)
        return pipeline("text-classification", model=model_id, top_k=None, local_files_only=True)

    return _load(("text-classification", model_id), build)


def zero_shot(model_id: str) -> Any:  # pragma: no cover - requires weights
    def build() -> Any:
        from transformers import pipeline

        _torch_one_thread()
        return pipeline("zero-shot-classification", model=model_id, local_files_only=True)

    return _load(("zero-shot-classification", model_id), build)


def classify(pipe: Any, texts: Sequence[str], **kwargs: Any) -> list[dict[str, float]]:
    """``{label: score}`` for each text, from a ``top_k=None`` pipeline."""
    if not texts:
        return []
    out = pipe(list(texts), truncation=True, **kwargs)
    rows: list[dict[str, float]] = []
    for item in out:
        item = item if isinstance(item, list) else [item]
        rows.append({str(r["label"]): float(r["score"]) for r in item})
    return rows


def _top(row: dict[str, float]) -> tuple[str, float]:
    label = max(row, key=row.__getitem__)
    return label, row[label]


def embedder(model_id: str) -> Any:
    """The shared local sentence embedder (`adapters/embeddings.py`)."""
    from agentfox.capabilities.detection.adapters.embeddings import local_embedder

    return local_embedder(model_id)


def _require_embedder(model_id: str) -> Any:
    emb = embedder(model_id)
    if not emb.available():
        raise ModelNotDownloaded(
            f"embedding model {model_id} is not downloaded; it is never fetched during a request"
        )
    return emb


@functools.lru_cache(maxsize=64)
def _embed_cached(model_id: str, texts: tuple[str, ...]) -> Any:  # pragma: no cover
    return embedder(model_id).embed(list(texts))


# --------------------------------------------------------------------------- base


class _ModelValidator(Validator):
    """A validator backed by a local model. Unavailable until its weights are here."""

    kind = "model"
    requires = ("transformers", "torch")
    timeout_ms = 400
    #: Refuses to load without ``AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1``.
    restricted: ClassVar[bool] = False
    #: Licence of the model weights (``license`` is the ported logic's).
    model_license: ClassVar[str] = ""
    #: A file whose presence in the Hugging Face cache means the model is here.
    weights_file: ClassVar[str] = "config.json"

    def _required_models(self) -> tuple[str, ...]:
        """The models without which it cannot run (others may be optional)."""
        return self.models

    def _weights_present(self) -> bool:
        return all(_cached_file(m, self.weights_file) for m in self._required_models())

    def available(self) -> bool:
        if self.restricted and not _restricted_allowed():
            return False
        return super().available() and self._weights_present()

    def unavailable_reason(self) -> str:
        if self.restricted and not _restricted_allowed():
            return (
                f"{', '.join(self.models)} is distributed under {self.model_license}, a "
                "licence with usage restrictions, so it is off unless "
                "AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1. Legal review required "
                "before commercial use."
            )
        deps = super().unavailable_reason()
        if deps:
            return deps
        if not self._weights_present():
            missing = [m for m in self._required_models() if not _cached_file(m, self.weights_file)]
            return (
                f"model {', '.join(missing)} is not downloaded. Run `agentfox admin "
                f"detectors pull validator.{self.name}` where the gateway runs; it is "
                "never fetched during a request."
            )
        return ""

    def warm(self) -> None:  # pragma: no cover - requires weights
        if self.available():
            self._warm()

    def _warm(self) -> None:  # pragma: no cover - requires weights
        """Load the model and run it once, off the request path."""

    def describe(self) -> dict[str, Any]:
        out = super().describe()
        out["model_license"] = self.model_license
        out["restricted"] = self.restricted
        return out


class _SentenceClassifier(_ModelValidator):
    """A text classifier run per sentence (or over the whole text), as upstream did.

    Subclasses say which units fail and why in :meth:`_judge`.
    """

    def _pipe(self) -> Any:  # pragma: no cover - requires weights
        return text_classifier(self.models[0])

    def _classify(self, texts: Sequence[str]) -> list[dict[str, float]]:
        return classify(self._pipe(), texts)

    def _warm(self) -> None:  # pragma: no cover - requires weights
        self._classify(["warm up"])

    def _judge(self, row: dict[str, float], params: Any) -> tuple[str, float] | None:
        """``(reason, score)`` if this unit fails, else None."""
        raise NotImplementedError

    def check(self, text: str, params: Any, ctx: CheckContext) -> list[Finding]:
        units = _units(text, getattr(params, "validation_method", "full"))
        rows = self._classify([text[s:e] for s, e in units])
        out: list[Finding] = []
        for (s, e), row in zip(units, rows, strict=True):
            verdict = self._judge(row, params)
            if verdict:
                reason, score = verdict
                out.append(_finding(text, s, e, reason, score, model=self.models[0]))
        return out


# ----------------------------------------------------------------- injection


def _rescale(x: float, a: float = 1.0, b: float = 1.0) -> float:
    """Upstream's logistic squash of a 0..1 score."""
    return 1.0 / (1.0 + a * math.exp(-b * x))


class DetectJailbreakParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Unset: 0.5 on the classifier's own probability, or upstream's 0.81 on its
    #: rescaled ensemble when `known_attacks` is on. Lower is more sensitive.
    threshold: float | None = Field(None, ge=0.0, le=1.0)
    #: Also compare against our attack corpus (upstream compared against a list it
    #: downloads at install time). Off by default so this check stays independent
    #: of `injection.similarity`, which already does that comparison.
    known_attacks: bool = False


@register_validator
class DetectJailbreak(_ModelValidator):
    """Upstream's `DetectJailbreak` takes the max of three rescaled scores: a RoBERTa
    jailbreak classifier, cosine similarity to a list of known attacks, and a
    "prompt saturation" model. Ported: the classifier, and the known-attack match.

    * The known-attack list (`resources.KNOWN_ATTACKS`) is fetched by upstream at
      install time and is not in its source; the match runs against our bundled
      attack corpus (`data/injection_corpus.json`) with upstream's embedding model
      and scale factors. It is optional: without the embedding model the classifier
      runs alone.
    * The saturation model (`GuardrailsAI/prompt-saturation-attack-detector`) needs
      upstream's custom architecture and its card states a "Restrictive" licence;
      not ported.

    Note what upstream's scale factors imply: the classifier's rescaled score tops
    out at 1/(1+3e^-2.5) = 0.802, under the 0.81 default, so at the default it is the
    known-attack match that fails a prompt; the classifier fails one only below 0.80.
    """

    name = "detect_jailbreak"
    label = "Jailbreak (classifier)"
    description = (
        "A RoBERTa jailbreak classifier plus similarity to known attack prompts, "
        "scored as upstream's ensemble does."
    )
    entity_type = "INJECTION.JAILBREAK"
    surfaces = ("input", "retrieved", "tool_result", "agent_message")
    Params = DetectJailbreakParams
    models = ("zhx123/ftrobertallm", "sentence-transformers/all-MiniLM-L6-v2")
    model_license = "MIT (classifier); Apache-2.0 (embeddings)"
    upstream = "guardrails-ai/detect_jailbreak"
    owasp_id = "LLM01"
    atlas_id = "AML.T0054"
    timeout_ms = 400
    detector = True

    TEXT_SCALE: ClassVar[tuple[float, float]] = (3.0, 2.5)
    KNOWN_SCALE: ClassVar[tuple[float, float]] = (0.5, 2.0)

    def _required_models(self) -> tuple[str, ...]:
        return self.models[:1]

    def _unsafe_probability(self, text: str) -> float:
        row = classify(text_classifier(self.models[0]), [text], max_length=512)[0]
        label, score = _top(row)
        # Upstream remaps so 0 is safe and 1 is unsafe, from the top label only.
        unsafe = label in ("1", "LABEL_1")
        return 0.5 + score * 0.5 if unsafe else 0.5 - score * 0.5

    def _classifier_score(self, text: str) -> float:
        return _rescale(self._unsafe_probability(text), *self.TEXT_SCALE)

    def _known_attack_score(self, text: str) -> tuple[float, float] | None:
        """(rescaled score, raw cosine) against the attack corpus, or None if off."""
        emb = embedder(self.models[1])
        if not emb.available():
            return None
        attacks = self._attack_embeddings()
        if attacks is None:
            return None
        query = emb.embed([text])[0]
        best = float((attacks @ query).max())
        return _rescale(best, *self.KNOWN_SCALE), best

    def _attack_embeddings(self) -> Any:  # pragma: no cover - requires weights
        def build() -> Any:
            from agentfox.capabilities.detection.adapters.embeddings import _load_corpus

            attacks, _ = _load_corpus()
            return embedder(self.models[1]).embed(attacks)

        try:
            return _load(("jailbreak-known-attacks", self.models[1]), build)
        except FileNotFoundError:
            return None

    def _warm(self) -> None:  # pragma: no cover - requires weights
        self._unsafe_probability("warm up")

    def check(self, text: str, params: DetectJailbreakParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        if not params.known_attacks:
            # The classifier alone, on its own probability. Upstream's rescaling caps
            # it at 0.802, under its 0.81 default, so on upstream's scale the
            # classifier could never fail a prompt by itself.
            p = self._unsafe_probability(text)
            if p < (params.threshold if params.threshold is not None else 0.5):
                return []
            return [_finding(text, 0, 0, f"likely jailbreak ({p:.2f})", p, classifier=p)]
        clf = self._classifier_score(text)
        known = self._known_attack_score(text)
        score = max(clf, known[0] if known else 0.0)
        if score <= (params.threshold if params.threshold is not None else 0.81):
            return []
        detail: dict[str, Any] = {"classifier_score": round(clf, 4)}
        if known:
            detail["known_attack_score"] = round(known[0], 4)
            detail["known_attack_similarity"] = round(known[1], 4)
        return [_finding(text, 0, 0, f"likely jailbreak (score {score:.2f})", score, **detail)]


class ManyShotParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A text-classification model in the local cache whose LABEL_1 means
    #: "this line is an instruction". Upstream took an inference endpoint URL.
    model: str = Field(min_length=3, max_length=200, pattern=r"^[\w.\-]+/[\w.\-]+$")
    #: Instruction lines at which the text counts as a many-shot jailbreak.
    num_few_shot_examples: int = Field(64, ge=1, le=10_000)


@register_validator
class ManyShotJailbreak(_ModelValidator):
    """Upstream (`guardrails/detect_many_shot_jailbreak`) sent every line to a hosted
    Hugging Face inference endpoint the user supplied and counted the lines it called
    instructions. It named no model, so neither does this port: the setting names a
    local text-classification model (LABEL_1 = instruction) already in the cache."""

    name = "many_shot_jailbreak"
    label = "Many-shot jailbreak"
    description = (
        "Counts the lines a local classifier calls instructions; many of them in one "
        "prompt is the shape of a many-shot jailbreak."
    )
    entity_type = "INJECTION.MANY_SHOT"
    surfaces = ("input", "retrieved", "tool_result")
    Params = ManyShotParams
    upstream = "guardrails-ai/jailbreak"
    owasp_id = "LLM01"
    timeout_ms = 600

    MAX_CHARS: ClassVar[int] = 14_500

    def check(self, text: str, params: ManyShotParams, ctx: CheckContext) -> list[Finding]:
        if len(text) >= self.MAX_CHARS:
            return [
                _finding(
                    text,
                    0,
                    0,
                    f"prompt of {len(text)} characters is over the supported {self.MAX_CHARS}",
                    1.0,
                )
            ]
        if not _cached_file(params.model):
            raise ModelNotDownloaded(f"model {params.model} is not downloaded")
        lines = [ln for ln in text.split("\n") if ln.strip()]
        if len(lines) < params.num_few_shot_examples:
            return []
        rows = classify(text_classifier(params.model), lines)
        count = sum(1 for row in rows if _top(row)[0] in ("LABEL_1", "1"))
        if count < params.num_few_shot_examples:
            return []
        return [
            _finding(
                text,
                0,
                0,
                f"{count} instruction lines (many-shot jailbreak)",
                1.0,
                instruction_lines=count,
            )
        ]


# ------------------------------------------------------------------- toxicity


class ToxicParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(0.5, ge=0.0, le=1.0)
    validation_method: Method = "sentence"


_DETOXIFY_CHECKPOINT = "unbiased-albert-c8519128.ckpt"
_DETOXIFY_BACKBONE = "albert-base-v2"


@register_validator
class ToxicLanguage(_ModelValidator):
    """Detoxify's ``unbiased-small`` model, as upstream: a sentence fails when any of
    seven labels scores over the threshold.

    Needs the ``detoxify`` package. Its checkpoint is not on the Hugging Face hub:
    Detoxify downloads it from its GitHub release into torch's hub cache the first
    time it is constructed, so ``pull`` cannot fetch it; run
    ``python -c "from detoxify import Detoxify; Detoxify('unbiased-small')"`` once.
    """

    name = "toxic_language"
    label = "Toxic language"
    description = (
        "Detoxify's unbiased model, per sentence: toxicity, severe toxicity, obscenity, "
        "threats, insults, identity attacks and sexually explicit language."
    )
    entity_type = "SAFETY.TOXIC"
    surfaces = ("input", "output")
    Params = ToxicParams
    requires = ("detoxify", "torch", "transformers")
    model_license = "Apache-2.0"
    upstream = "guardrails-ai/toxic_language"
    detector = True

    LABELS: ClassVar[tuple[str, ...]] = (
        "toxicity",
        "severe_toxicity",
        "obscene",
        "threat",
        "insult",
        "identity_attack",
        "sexual_explicit",
    )

    @staticmethod
    def _checkpoint() -> str | None:
        try:
            import torch

            path = os.path.join(torch.hub.get_dir(), "checkpoints", _DETOXIFY_CHECKPOINT)
        except Exception:
            return None
        return path if os.path.exists(path) else None

    def _weights_present(self) -> bool:
        return bool(self._checkpoint() and _cached_file(_DETOXIFY_BACKBONE))

    def unavailable_reason(self) -> str:
        reason = super().unavailable_reason()
        if reason.startswith("model "):
            return (
                f"Detoxify's checkpoint ({_DETOXIFY_CHECKPOINT}) or its {_DETOXIFY_BACKBONE} "
                'tokenizer is not downloaded. Run `python -c "from detoxify import '
                "Detoxify; Detoxify('unbiased-small')\"` once where the gateway runs; it "
                "is never fetched during a request."
            )
        return reason

    def _model(self) -> Any:  # pragma: no cover - requires detoxify
        def build() -> Any:
            from detoxify import Detoxify

            _torch_one_thread()
            config_file = _cached_file(_DETOXIFY_BACKBONE)
            return Detoxify(
                "unbiased-small",
                checkpoint=self._checkpoint(),
                device="cpu",
                # The cached snapshot, so transformers never asks the hub.
                huggingface_config_path=os.path.dirname(config_file) if config_file else None,
            )

        return _load(("detoxify", "unbiased-small"), build)

    def _predict(self, texts: list[str]) -> list[dict[str, float]]:
        if not texts:
            return []
        raw = self._model().predict(texts)
        return [
            {label: float(raw[label][i]) for label in self.LABELS if label in raw}
            for i in range(len(texts))
        ]

    def _warm(self) -> None:  # pragma: no cover - requires detoxify
        self._predict(["warm up"])

    def check(self, text: str, params: ToxicParams, ctx: CheckContext) -> list[Finding]:
        units = _units(text, params.validation_method)
        rows = self._predict([text[s:e] for s, e in units])
        out: list[Finding] = []
        for (s, e), row in zip(units, rows, strict=True):
            hits = [label for label in self.LABELS if row.get(label, 0.0) > params.threshold]
            if hits:
                out.append(
                    _finding(
                        text,
                        s,
                        e,
                        f"Toxic language detected: {', '.join(hits)}",
                        max(row[h] for h in hits),
                        labels=hits,
                    )
                )
        return out


@register_validator
class BertToxic(_SentenceClassifier):
    """Upstream `bert_toxic` posted each sentence to a chat server on 127.0.0.1:10000
    and read a "poison score" back; it shipped no model. This port runs a BERT
    toxicity classifier locally instead (`unitary/toxic-bert`, the model behind
    Detoxify's ``original``), with upstream's threshold and per-sentence method."""

    name = "bert_toxic"
    label = "Toxic language (BERT)"
    description = (
        "A BERT toxicity classifier, per sentence: toxic, severe toxic, obscene, "
        "threat, insult, identity hate."
    )
    entity_type = "SAFETY.TOXIC"
    surfaces = ("input", "output")
    Params = ToxicParams
    models = ("unitary/toxic-bert",)
    model_license = "Apache-2.0"
    upstream = "guardrails-ai/bert_toxic"
    # Offered as an every-request check: on ToxicChat it found 7x what
    # safety.lexicon finds at a 1.2% false-positive rate (benchmarks/validators/).
    detector = True

    def _classify(self, texts: Sequence[str]) -> list[dict[str, float]]:
        # Multi-label: each label is its own sigmoid, not a softmax over all six.
        return classify(self._pipe(), texts, function_to_apply="sigmoid")

    def _judge(self, row: dict[str, float], params: ToxicParams) -> tuple[str, float] | None:
        hits = sorted(label for label, score in row.items() if score > params.threshold)
        if not hits:
            return None
        return f"Toxic language detected: {', '.join(hits)}", max(row[h] for h in hits)


class NSFWParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(0.8, ge=0.0, le=1.0)
    validation_method: Method = "sentence"


@register_validator
class NSFWText(_SentenceClassifier):
    name = "nsfw_text"
    label = "NSFW text"
    description = "A DistilBERT classifier for not-safe-for-work text, per sentence."
    entity_type = "SAFETY.NSFW"
    surfaces = ("input", "output")
    Params = NSFWParams
    models = ("michellejieli/NSFW_text_classifier",)
    model_license = "unspecified on the model card"
    upstream = "guardrails-ai/nsfw_text"
    # Not offered as an every-request check: on ToxicChat it flagged 20.6% of benign
    # prompts (benchmarks/validators/README.md). Still available as a rule.

    def _judge(self, row: dict[str, float], params: NSFWParams) -> tuple[str, float] | None:
        score = row.get("NSFW", 0.0)
        return ("NSFW content detected", score) if score > params.threshold else None


class BiasParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Higher allows more. Upstream's default.
    threshold: float = Field(0.9, ge=0.0, le=1.0)


@register_validator
class BiasCheck(_ModelValidator):
    """`d4data/bias-detection-model` publishes TensorFlow weights only
    (``tf_model.h5``), so like upstream this loads it with ``framework="tf"``. That
    needs ``tensorflow`` and a transformers release that still loads TensorFlow
    models (4.x; transformers 5 removed TensorFlow support)."""

    name = "bias_check"
    label = "Bias"
    description = (
        "A DistilBERT classifier for biased statements about age, gender, ethnicity, "
        "religion and similar."
    )
    entity_type = "SAFETY.BIAS"
    surfaces = ("input", "output")
    Params = BiasParams
    requires = ("transformers", "tensorflow")
    models = ("d4data/bias-detection-model",)
    model_license = "unspecified on the model card"
    upstream = "guardrails-ai/bias_check"
    detector = True

    @staticmethod
    @functools.cache
    def _tf_supported() -> bool:
        # Cached: it imports transformers, and `available()` runs on every request.
        try:
            import transformers

            return hasattr(transformers, "TFAutoModelForSequenceClassification")
        except Exception:
            return False

    def available(self) -> bool:
        return super().available() and self._tf_supported()

    def unavailable_reason(self) -> str:
        reason = super().unavailable_reason()
        if not reason and not self._tf_supported():
            return (
                f"{self.models[0]} ships TensorFlow weights only, and the installed "
                "transformers cannot load TensorFlow models (removed in transformers 5)."
            )
        return reason

    def _pipe(self) -> Any:  # pragma: no cover - requires tensorflow
        def build() -> Any:
            from transformers import pipeline

            return pipeline(
                "text-classification",
                model=self.models[0],
                tokenizer=self.models[0],
                framework="tf",
                top_k=None,
                local_files_only=True,
            )

        return _load(("text-classification-tf", self.models[0]), build)

    def _warm(self) -> None:  # pragma: no cover - requires tensorflow
        classify(self._pipe(), ["warm up"])

    def check(self, text: str, params: BiasParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        # Upstream scores the whole passage (it splits into sentences only to fix).
        row = classify(self._pipe(), [text])[0]
        score = row.get("Biased", 0.0)
        if score <= params.threshold:
            return []
        return [_finding(text, 0, 0, "potentially biased", score, model=self.models[0])]


class GibberishParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Confidence the text is clean needed to pass.
    threshold: float = Field(0.5, ge=0.0, le=1.0)
    validation_method: Method = "sentence"


@register_validator
class GibberishText(_SentenceClassifier):
    name = "gibberish_text"
    label = "Gibberish"
    description = (
        "A classifier for word salad, noise and mild gibberish, per sentence. A "
        "sentence passes only when it is confidently clean."
    )
    entity_type = "FORMAT.GIBBERISH"
    surfaces = ("output",)
    Params = GibberishParams
    models = ("madhurjindal/autonlp-Gibberish-Detector-492513457",)
    model_license = "MIT"
    upstream = "guardrails-ai/gibberish_text"
    detector = True
    scan_views = False

    def _judge(self, row: dict[str, float], params: GibberishParams) -> tuple[str, float] | None:
        label, score = _top(row)
        if label == "clean" and score > params.threshold:
            return None
        return f"gibberish ({label})", 1.0 - row.get("clean", 0.0)


class FinancialToneParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone: Literal["positive", "negative", "neutral"] = "neutral"
    threshold: float = Field(0.8, ge=0.0, le=1.0)


@register_validator
class FinancialTone(_ModelValidator):
    name = "financial_tone"
    label = "Financial tone"
    description = (
        "FinBERT-tone reads the text as positive, negative or neutral; it fails unless "
        "it is confidently the tone you set."
    )
    entity_type = "BRAND.FINANCIAL_TONE"
    surfaces = ("output",)
    Params = FinancialToneParams
    models = ("yiyanghkust/finbert-tone",)
    model_license = "unspecified on the model card"
    upstream = "guardrails-ai/financial_tone"
    scan_views = False

    def _warm(self) -> None:  # pragma: no cover - requires weights
        classify(text_classifier(self.models[0]), ["warm up"])

    def check(self, text: str, params: FinancialToneParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        row = classify(text_classifier(self.models[0]), [text])[0]
        label, score = _top(row)
        if label.lower() == params.tone and score > params.threshold:
            return []
        wanted = next((v for k, v in row.items() if k.lower() == params.tone), 0.0)
        return [
            _finding(
                text,
                0,
                0,
                f"tone reads {label.lower()} ({score:.2f}), not {params.tone}",
                1.0 - wanted,
                predicted=label.lower(),
            )
        ]


class ProfanityParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The package's own decision is a probability over 0.5.
    threshold: float = Field(0.5, ge=0.0, le=1.0)


@register_validator
class ProfanityFree(Validator):
    """`alt-profanity-check`: a linear SVM over a bag of words, bundled in the
    package (no download). Upstream fails on ``predict() == 1``, which is the
    calibrated probability over 0.5."""

    name = "profanity_free"
    label = "Profanity"
    description = "A small bundled classifier (alt-profanity-check) for profane language."
    entity_type = "SAFETY.PROFANITY"
    surfaces = ("input", "output")
    kind = "model"
    Params = ProfanityParams
    requires = ("profanity_check",)
    upstream = "guardrails-ai/profanity_free"
    timeout_ms = 100
    detector = True

    def warm(self) -> None:  # pragma: no cover - requires profanity_check
        if self.available():
            self._prob("warm up")

    @staticmethod
    def _prob(text: str) -> float:  # pragma: no cover - requires profanity_check
        from profanity_check import predict_prob

        return float(predict_prob([text])[0])

    def check(self, text: str, params: ProfanityParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        score = self._prob(text)
        if score <= params.threshold:
            return []
        return [_finding(text, 0, 0, "This text contains profanity.", score)]


# --------------------------------------------------------------------- topics

_TOPIC_HYPOTHESIS = "This example has to do with topic {}."


class _ZeroShotTopics(_ModelValidator):
    """Upstream's zero-shot leg: BART-MNLI, one hypothesis per topic, multi-label.
    Upstream also asked an OpenAI model when unsure; that leg is not ported here
    (the judgment tier owns any LLM call)."""

    models = ("facebook/bart-large-mnli",)
    model_license = "MIT"
    # One NLI forward pass per topic on a 400M-parameter model.
    timeout_ms = 600

    def _scores(self, text: str, topics: Sequence[str]) -> dict[str, float]:
        result = zero_shot(self.models[0])(
            text,
            candidate_labels=list(topics),
            hypothesis_template=_TOPIC_HYPOTHESIS,
            multi_label=True,
        )
        return {str(t): float(s) for t, s in zip(result["labels"], result["scores"], strict=True)}

    def _warm(self) -> None:  # pragma: no cover - requires weights
        self._scores("warm up", ["weather"])

    @staticmethod
    def _topic_span(text: str, topic: str) -> tuple[int, int]:
        i = text.lower().find(topic.lower())
        return (i, i + len(topic)) if i >= 0 else (0, 0)


def _clean_topics(topics: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in topics if t.strip()))


class RestrictToTopicParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid_topics: list[str] = Field(default_factory=list, max_length=50)
    invalid_topics: list[str] = Field(default_factory=list, max_length=50)
    #: Zero-shot score a topic needs to count as present.
    threshold: float = Field(0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _topics(self) -> RestrictToTopicParams:
        self.valid_topics = _clean_topics(self.valid_topics)
        self.invalid_topics = _clean_topics(self.invalid_topics)
        if not (self.valid_topics or self.invalid_topics):
            raise ValueError("give at least one valid or invalid topic")
        both = set(self.valid_topics) & set(self.invalid_topics)
        if both:
            raise ValueError(f"a topic cannot be both valid and invalid: {sorted(both)}")
        return self


@register_validator
class RestrictToTopic(_ZeroShotTopics):
    name = "restrict_to_topic"
    label = "Restrict to topic"
    description = (
        "A zero-shot classifier checks the text is about at least one allowed topic "
        "and none of the forbidden ones."
    )
    entity_type = "TOPIC.OUT_OF_SCOPE"
    surfaces = ("input", "output")
    Params = RestrictToTopicParams
    upstream = "guardrails-ai/restricttotopic"

    def check(self, text: str, params: RestrictToTopicParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        scores = self._scores(text, params.valid_topics + params.invalid_topics)
        found = {t for t, s in scores.items() if s > params.threshold}
        out = [
            _finding(
                text,
                *self._topic_span(text, topic),
                f"Text contains invalid topic: {topic}",
                scores[topic],
                topic=topic,
            )
            for topic in params.invalid_topics
            if topic in found
        ]
        if out:
            return out
        if params.valid_topics and not found & set(params.valid_topics):
            best = max((scores.get(t, 0.0) for t in params.valid_topics), default=0.0)
            return [_finding(text, 0, 0, "No valid topic was found.", 1.0 - best)]
        return []


#: Upstream's documented default list (trauma triggers).
DEFAULT_SENSITIVE_TOPICS = (
    "holiday or anniversary of the trauma or loss",
    "certain sounds, sights, smells, or tastes related to the trauma",
    "loud voices or yelling",
    "loud noises",
    "arguments",
    "being ridiculed or judged",
    "being alone",
    "getting rejected",
    "being ignored",
    "breakup of a relationship",
    "violence in the news",
    "sexual harassment or unwanted touching",
    "physical illness or injury",
)


class SensitiveTopicsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensitive_topics: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_TOPICS), min_length=1, max_length=50
    )
    threshold: float = Field(0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _topics(self) -> SensitiveTopicsParams:
        self.sensitive_topics = _clean_topics(self.sensitive_topics)
        if not self.sensitive_topics:
            raise ValueError("give at least one sensitive topic")
        return self


@register_validator
class SensitiveTopics(_ZeroShotTopics):
    """Upstream's signature defaulted ``sensitive_topics`` to ``[]`` (so its
    documented trauma-trigger list never applied without passing ``None``); here
    the documented list is the default."""

    name = "sensitive_topics"
    label = "Sensitive topics"
    description = "A zero-shot classifier flags text about any topic on a sensitive list."
    entity_type = "TOPIC.SENSITIVE"
    surfaces = ("input", "output")
    Params = SensitiveTopicsParams
    upstream = "guardrails-ai/sensitive_topics"

    def check(self, text: str, params: SensitiveTopicsParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        scores = self._scores(text, params.sensitive_topics)
        return [
            _finding(
                text,
                *self._topic_span(text, topic),
                f"Sensitive topic: {topic}",
                scores[topic],
                topic=topic,
            )
            for topic in params.sensitive_topics
            if scores.get(topic, 0.0) > params.threshold
        ]


# ------------------------------------------------------------------ grounding
#
# Upstream used the `sentence-transformers` package. These models are a BERT encoder
# plus mean pooling, which `adapters/embeddings.LocalEmbedder` does with plain
# transformers, so the cosine similarities are the same without the extra package.

_MINILM = "sentence-transformers/all-MiniLM-L6-v2"
_PARAPHRASE_MINILM = "sentence-transformers/paraphrase-MiniLM-L6-v2"
_MODEL_ID = r"^[\w.\-]+/[\w.\-]+$"


class _EmbeddingValidator(_ModelValidator):
    model_license = "Apache-2.0"
    timeout_ms = 300
    scan_views = False

    def _warm(self) -> None:  # pragma: no cover - requires weights
        embedder(self.models[0]).embed(["warm up"])


class SimilarToDocumentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: str = Field(min_length=1, max_length=20_000)
    #: Minimum cosine similarity to pass.
    threshold: float = Field(0.7, ge=-1.0, le=1.0)
    model: str = Field(_MINILM, pattern=_MODEL_ID)


@register_validator
class SimilarToDocument(_EmbeddingValidator):
    name = "similar_to_document"
    label = "Similar to document"
    description = "Fails when the text's embedding is not close enough to a given document."
    entity_type = "GROUNDING.DISSIMILAR"
    surfaces = ("output",)
    Params = SimilarToDocumentParams
    models = (_MINILM,)
    upstream = "guardrails-ai/similar_to_document"

    def check(self, text: str, params: SimilarToDocumentParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        _require_embedder(params.model)
        doc = _embed_cached(params.model, (params.document,))[0]
        value = embedder(params.model).embed([text])[0]
        similarity = float(doc @ value)
        if similarity >= params.threshold:
            return []
        return [
            _finding(
                text,
                0,
                0,
                f"not similar enough to the document ({similarity:.2f} < {params.threshold})",
                1.0,
                similarity=round(similarity, 4),
            )
        ]


def chunk_text(text: str, strategy: str, size: int, overlap: int) -> list[str]:
    """Upstream's `get_chunks_from_text`: windows of `size` atoms, `overlap` shared."""
    if strategy == "sentence":
        atoms = [text[s:e] for s, e in split_sentences(text)]
        joiner = " "
    elif strategy == "word":
        atoms = text.split()
        joiner = " "
    else:
        atoms = list(text)
        joiner = ""
    step = max(1, size - overlap)
    return [joiner.join(atoms[i : i + size]) for i in range(0, len(atoms), step)]


class ProvenanceEmbeddingsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Source texts. Without them, the request's retrieved sources are used.
    sources: list[str] | None = Field(None, max_length=200)
    #: Cosine *distance* at or over which a sentence is unsupported.
    threshold: float = Field(0.8, ge=0.0, le=2.0)
    validation_method: Method = "sentence"
    chunk_strategy: Literal["sentence", "word", "char"] = "sentence"
    chunk_size: int = Field(5, ge=1, le=1000)
    chunk_overlap: int = Field(2, ge=0, le=999)

    @model_validator(mode="after")
    def _overlap(self) -> ProvenanceEmbeddingsParams:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


def _sources(params_sources: list[str] | None, ctx: CheckContext) -> list[str]:
    if params_sources:
        return [s for s in params_sources if s.strip()]
    raw = ctx.extra.get("sources")
    if isinstance(raw, str):
        raw = [raw]
    return [s for s in raw or [] if isinstance(s, str) and s.strip()]


@register_validator
class ProvenanceEmbeddings(_EmbeddingValidator):
    """Upstream's default path: chunk the sources, embed with
    ``paraphrase-MiniLM-L6-v2``, and call a sentence unsupported when its nearest
    chunk is at cosine distance ``threshold`` or more. (Upstream's ``full`` method
    fails only over the threshold; kept.) A caller-supplied query or embedding
    function is not portable to a settings form and is not ported; ``token``
    chunking needed tiktoken and is not offered."""

    name = "provenance_embeddings"
    label = "Provenance (embeddings)"
    description = (
        "Each sentence must be close, in embedding space, to some passage of the source texts."
    )
    entity_type = "GROUNDING.UNSUPPORTED"
    surfaces = ("output",)
    Params = ProvenanceEmbeddingsParams
    models = (_PARAPHRASE_MINILM,)
    upstream = "guardrails-ai/provenance_embeddings"
    owasp_id = "LLM09"

    def check(
        self, text: str, params: ProvenanceEmbeddingsParams, ctx: CheckContext
    ) -> list[Finding]:
        sources = _sources(params.sources, ctx)
        units = _units(text, params.validation_method)
        if not sources or not units:
            return []
        model = self.models[0]
        _require_embedder(model)
        chunks = tuple(
            c
            for src in sources
            for c in chunk_text(src, params.chunk_strategy, params.chunk_size, params.chunk_overlap)
            if c.strip()
        )
        if not chunks:
            return []
        chunk_vecs = _embed_cached(model, chunks)
        vecs = embedder(model).embed([text[s:e] for s, e in units])
        distances = [1.0 - float((chunk_vecs @ v).max()) for v in vecs]
        out: list[Finding] = []
        for (s, e), dist in zip(units, distances, strict=True):
            if params.validation_method == "sentence":
                unsupported = dist >= params.threshold
            else:
                unsupported = dist > params.threshold
            if unsupported:
                out.append(
                    _finding(
                        text,
                        s,
                        e,
                        "not supported by the provided sources",
                        1.0,
                        distance=round(dist, 4),
                    )
                )
        return out


class SimilarToPreviousValuesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prev_values: list[str] | list[float] = Field(min_length=1, max_length=500)
    #: For numbers: how many standard deviations from the mean are allowed.
    standard_deviations: int = Field(3, ge=0, le=100)
    #: For text: minimum average cosine similarity to the previous values.
    threshold: float = Field(0.8, ge=-1.0, le=1.0)


@register_validator
class SimilarToPreviousValues(_EmbeddingValidator):
    name = "similar_to_previous_values"
    label = "Similar to previous values"
    description = (
        "Numbers must fall within k standard deviations of earlier values; text must "
        "be semantically close, on average, to earlier values."
    )
    entity_type = "GROUNDING.OUTLIER"
    surfaces = ("output", "tool_args", "tool_result")
    Params = SimilarToPreviousValuesParams
    models = (_PARAPHRASE_MINILM,)
    upstream = "guardrails-ai/similar_to_previous_values"

    def check(
        self, text: str, params: SimilarToPreviousValuesParams, ctx: CheckContext
    ) -> list[Finding]:
        prev = params.prev_values
        if all(isinstance(p, float) for p in prev):
            return self._numeric(text, [float(p) for p in prev], params.standard_deviations)
        if not text.strip():
            return []
        model = self.models[0]
        _require_embedder(model)
        prev_vecs = _embed_cached(model, tuple(str(p) for p in prev))
        value = embedder(model).embed([text])[0]
        avg = float((prev_vecs @ value).mean())
        if avg >= params.threshold:
            return []
        return [
            _finding(
                text,
                0,
                0,
                f"not semantically similar to previous values ({avg:.2f} < {params.threshold})",
                1.0,
                similarity=round(avg, 4),
            )
        ]

    @staticmethod
    def _numeric(text: str, prev: list[float], k: int) -> list[Finding]:
        try:
            value = float(text.strip())
        except ValueError:
            return [_finding(text, 0, 0, "previous values are numbers; this is not", 1.0)]
        mean = statistics.fmean(prev)
        std = statistics.pstdev(prev)  # numpy's np.std, as upstream
        if mean - k * std <= value <= mean + k * std:
            return []
        return [
            _finding(
                text,
                0,
                0,
                f"{value} lies outside the expected range {mean:g} +/- {k * std:g}",
                1.0,
                mean=mean,
                std=std,
            )
        ]


# ------------------------------------------------------------------------ PII


def _presidio_ready() -> bool:
    from agentfox.capabilities.detection.adapters.presidio import PresidioPiiDetector

    return PresidioPiiDetector._model_present()


def _presidio_reason() -> str:
    from agentfox.capabilities.detection.adapters.presidio import PresidioPiiDetector

    return PresidioPiiDetector().unavailable_reason


def _presidio_analyze(text: str, entities: list[str]) -> list[Any]:  # pragma: no cover
    from agentfox.capabilities.detection.adapters.presidio import _analyzer

    return list(_analyzer().analyze(text=text, entities=entities, language="en"))


def _dedupe(spans: list[tuple[int, int, str, float]]) -> list[tuple[int, int, str, float]]:
    """Drop a span inside a higher-scoring one (Presidio's `remove_duplicates`)."""
    kept: list[tuple[int, int, str, float]] = []
    for span in sorted(spans, key=lambda r: (-r[3], r[0])):
        if any(k[0] <= span[0] and span[1] <= k[1] for k in kept):
            continue
        kept.append(span)
    return sorted(kept, key=lambda r: (r[0], r[1]))


PII_ENTITIES_MAP: dict[str, tuple[str, ...]] = {
    "pii": (
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "DOMAIN_NAME",
        "IP_ADDRESS",
        "DATE_TIME",
        "LOCATION",
        "PERSON",
        "URL",
    ),
    "spi": (
        "CREDIT_CARD",
        "CRYPTO",
        "IBAN_CODE",
        "NRP",
        "MEDICAL_LICENSE",
        "US_BANK_NUMBER",
        "US_DRIVER_LICENSE",
        "US_ITIN",
        "US_PASSPORT",
        "US_SSN",
    ),
}

_ENTITY_NAME = r"^[A-Z][A-Z0-9_]{1,40}$"


def _entity_list(value: str | list[str]) -> list[str]:
    return list(PII_ENTITIES_MAP[value]) if isinstance(value, str) else list(value)


class DetectPIIParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ``pii``, ``spi``, or a list of Presidio entity names.
    pii_entities: Literal["pii", "spi"] | list[str] = "pii"

    @model_validator(mode="after")
    def _names(self) -> DetectPIIParams:
        if isinstance(self.pii_entities, list):
            if not self.pii_entities:
                raise ValueError("give at least one entity")
            bad = [e for e in self.pii_entities if not re.match(_ENTITY_NAME, e)]
            if bad:
                raise ValueError(f"not Presidio entity names: {bad}")
        return self


@register_validator
class DetectPII(Validator):
    """Presidio, as upstream ran it. Overlaps our `pii.presidio` detector, which maps
    entities into our PII taxonomy and drops Presidio's noisiest recognisers by
    default; this keeps upstream's ``pii``/``spi`` groups for rules ported from
    Guardrails, and reports every hit as ``PII.PRESIDIO``."""

    name = "detect_pii"
    label = "PII (Presidio)"
    description = "Microsoft Presidio, with Guardrails' 'pii' and 'spi' entity groups."
    entity_type = "PII.PRESIDIO"
    surfaces = ("input", "output", "tool_args", "tool_result", "retrieved")
    kind = "model"
    Params = DetectPIIParams
    requires = ("presidio_analyzer",)
    upstream = "guardrails-ai/detect_pii"
    owasp_id = "LLM02"
    atlas_id = "AML.T0057"
    timeout_ms = 300

    def available(self) -> bool:
        return super().available() and _presidio_ready()

    def unavailable_reason(self) -> str:
        return "" if self.available() else _presidio_reason()

    def warm(self) -> None:  # pragma: no cover - requires presidio
        if self.available():
            _presidio_analyze("warm up", ["PERSON"])

    def check(self, text: str, params: DetectPIIParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        results = _presidio_analyze(text, _entity_list(params.pii_entities))
        spans = _dedupe([(r.start, r.end, r.entity_type, float(r.score)) for r in results])
        return [
            _finding(text, s, e, f"PII detected: {ent}", score, presidio_entity=ent)
            for s, e, ent, score in spans
        ]


class GlinerPIIParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[str] = Field(
        default_factory=lambda: [
            "date",
            "time",
            "city",
            "state",
            "country",
            "zip code",
            "location",
            "name",
            "person",
            "phone number",
            "driver license",
        ],
        min_length=1,
        max_length=50,
    )
    #: GLiNER's own default span threshold.
    threshold: float = Field(0.5, ge=0.0, le=1.0)


def _gliner(model_id: str) -> Any:  # pragma: no cover - requires gliner
    def build() -> Any:
        from gliner import GLiNER

        _torch_one_thread()
        return GLiNER.from_pretrained(model_id, local_files_only=True)

    return _load(("gliner", model_id), build)


@register_validator
class GlinerPII(_ModelValidator):
    """GLiNER finds spans of whatever entity labels you name. Note GLiNER also loads
    its backbone's tokenizer (DeBERTa-v3) from the hub cache; pull it with the model."""

    name = "gliner_pii"
    label = "PII (GLiNER)"
    description = "GLiNER zero-shot entity recognition for the PII labels you name."
    entity_type = "PII.GLINER"
    surfaces = ("input", "output", "tool_args", "tool_result", "retrieved")
    Params = GlinerPIIParams
    requires = ("gliner", "torch")
    models = ("urchade/gliner_medium-v2.1",)
    model_license = "Apache-2.0"
    weights_file = "gliner_config.json"
    upstream = "guardrails-ai/gliner_pii"
    owasp_id = "LLM02"
    timeout_ms = 500

    def _predict(self, text: str, labels: list[str], threshold: float) -> list[dict[str, Any]]:
        return list(_gliner(self.models[0]).predict_entities(text, labels, threshold=threshold))

    def _warm(self) -> None:  # pragma: no cover - requires gliner
        self._predict("warm up", ["person"], 0.5)

    def check(self, text: str, params: GlinerPIIParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        return [
            _finding(
                text,
                int(p["start"]),
                int(p["end"]),
                f"PII: {p['label']}",
                float(p.get("score", 1.0)),
                label=p["label"],
            )
            for p in self._predict(text, params.entities, params.threshold)
        ]


#: Which Presidio entities GLiNER answers for (spaCy's NER is weakest there), and
#: the labels it is asked for. Upstream's mapping lives in a `constants.py` that is
#: not in its published source; this one is ours.
PRESIDIO_TO_GLINER: dict[str, tuple[str, ...]] = {
    "PERSON": ("person", "name"),
    "LOCATION": ("location", "address", "city", "country"),
    "DATE_TIME": ("date", "time", "date of birth"),
    "NRP": ("nationality", "religion", "political group"),
}


class GuardrailsPIIParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ``pii``, ``spi``, or a list of Presidio entity names.
    entities: Literal["pii", "spi"] | list[str]
    #: Score GLiNER's entities need. Presidio's pattern entities keep any score.
    threshold: float = Field(0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _names(self) -> GuardrailsPIIParams:
        if isinstance(self.entities, list):
            if not self.entities:
                raise ValueError("give at least one entity")
            bad = [e for e in self.entities if not re.match(_ENTITY_NAME, e)]
            if bad:
                raise ValueError(f"not Presidio entity names: {bad}")
        return self


@register_validator
class GuardrailsPII(_ModelValidator):
    """Presidio for pattern entities (cards, SSNs, IBANs) and GLiNER (small) for the
    named-entity ones, as upstream combined them."""

    name = "guardrails_pii"
    label = "PII (Presidio + GLiNER)"
    description = "Presidio's pattern recognisers plus GLiNER for names, places, dates."
    entity_type = "PII.GUARDRAILS"
    surfaces = ("input", "output", "tool_args", "tool_result", "retrieved")
    Params = GuardrailsPIIParams
    requires = ("gliner", "presidio_analyzer", "torch")
    models = ("urchade/gliner_small-v2.1",)
    model_license = "Apache-2.0"
    weights_file = "gliner_config.json"
    upstream = "guardrails-ai/guardrails_pii"
    owasp_id = "LLM02"
    atlas_id = "AML.T0057"
    timeout_ms = 500

    def available(self) -> bool:
        return super().available() and _presidio_ready()

    def unavailable_reason(self) -> str:
        reason = super().unavailable_reason()
        if not reason and not _presidio_ready():
            return _presidio_reason()
        return reason

    def _gliner_spans(
        self, text: str, entities: list[str], threshold: float
    ) -> list[tuple[int, int, str, float]]:
        label_to_entity = {
            label: ent for ent in entities for label in PRESIDIO_TO_GLINER.get(ent, ())
        }
        if not label_to_entity:
            return []
        found = _gliner(self.models[0]).predict_entities(
            text, list(label_to_entity), threshold=threshold
        )
        return [
            (int(p["start"]), int(p["end"]), label_to_entity[p["label"]], float(p["score"]))
            for p in found
            if p["label"] in label_to_entity
        ]

    def _warm(self) -> None:  # pragma: no cover - requires gliner
        self._gliner_spans("warm up", ["PERSON"], 0.5)
        _presidio_analyze("warm up", ["EMAIL_ADDRESS"])

    def check(self, text: str, params: GuardrailsPIIParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        entities = _entity_list(params.entities)
        pattern = [e for e in entities if e not in PRESIDIO_TO_GLINER]
        spans = self._gliner_spans(text, entities, params.threshold)
        if pattern:
            spans += [
                (r.start, r.end, r.entity_type, float(r.score))
                for r in _presidio_analyze(text, pattern)
            ]
        return [
            _finding(text, s, e, f"PII detected: {ent}", score, entity=ent)
            for s, e, ent, score in _dedupe(spans)
        ]


# ------------------------------------------------------------------ translation


class TranslationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The text that was translated. Without it, the request's prompt is used.
    source: str | None = Field(None, max_length=20_000)
    #: Minimum COMET-Kiwi quality score.
    threshold: float = Field(0.75, ge=0.0, le=1.0)


@register_validator
class HighQualityTranslation(_ModelValidator):
    """Reference-free COMET (`Unbabel/wmt22-cometkiwi-da`) scores a translation
    against its source. The model is gated on the hub and licensed CC-BY-NC-SA-4.0
    (non-commercial), so it sits behind the restricted-licence switch."""

    name = "high_quality_translation"
    label = "Translation quality"
    description = "COMET-Kiwi scores the translation against its source text."
    entity_type = "QUALITY.LOW_TRANSLATION_QUALITY"
    surfaces = ("output",)
    Params = TranslationParams
    requires = ("comet",)
    models = ("Unbabel/wmt22-cometkiwi-da",)
    model_license = "CC-BY-NC-SA-4.0"
    weights_file = "checkpoints/model.ckpt"
    restricted = True
    upstream = "guardrails-ai/high_quality_translation_validator"
    timeout_ms = 600
    scan_views = False

    def _model(self) -> Any:  # pragma: no cover - requires comet
        def build() -> Any:
            from comet import load_from_checkpoint

            _torch_one_thread()
            return load_from_checkpoint(_cached_file(self.models[0], self.weights_file))

        return _load(("comet", self.models[0]), build)

    def _score(self, source: str, translation: str) -> float:  # pragma: no cover
        out = self._model().predict(
            [{"src": source, "mt": translation}],
            batch_size=1,
            gpus=0,
            accelerator="cpu",
            progress_bar=False,
        )
        return float(out.scores[0])

    def _warm(self) -> None:  # pragma: no cover - requires comet
        self._score("Bonjour.", "Hello.")

    def check(self, text: str, params: TranslationParams, ctx: CheckContext) -> list[Finding]:
        source = params.source or ctx.extra.get("prompt")
        if not text.strip() or not isinstance(source, str) or not source.strip():
            return []
        quality = self._score(source, text)
        if quality >= params.threshold:
            return []
        return [
            _finding(
                text,
                0,
                0,
                f"low quality translation ({quality:.2f} < {params.threshold})",
                1.0,
                quality=round(quality, 4),
            )
        ]


# ------------------------------------------------------- safety LLM classifiers


LLAMA_GUARD_POLICIES: dict[str, str] = {
    "O1": "POLICY__NO_VIOLENCE_HATE",
    "O2": "POLICY__NO_SEXUAL_CONTENT",
    "O3": "POLICY__NO_CRIMINAL_PLANNING",
    "O4": "POLICY__NO_GUNS_AND_ILLEGAL_WEAPONS",
    "O5": "POLICY__NO_ILLEGAL_DRUGS",
    "O6": "POLICY__NO_ENOURAGE_SELF_HARM",
}


class LlamaGuardParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Categories that fail the text. None: all six.
    policies: list[Literal["O1", "O2", "O3", "O4", "O5", "O6"]] | None = None


@register_validator
class LlamaGuard7B(_ModelValidator):
    """Upstream sent the text to Guardrails' hosted Llama Guard endpoint; this runs
    `meta-llama/LlamaGuard-7b` here, as Meta documents it: the tokenizer's chat
    template (which carries the O1–O6 taxonomy), ``generate``, and "unsafe\\nO<n>".
    As upstream, the text is the user turn, and ``policies`` limits which violated
    category fails it. A 7B model: plan for a GPU, or a long budget on CPU."""

    name = "llamaguard_7b"
    label = "Llama Guard 7B"
    description = "Meta's Llama Guard classifies the text as safe or unsafe by category."
    entity_type = "SAFETY.LLAMA_GUARD"
    surfaces = ("input", "output")
    Params = LlamaGuardParams
    models = ("meta-llama/LlamaGuard-7b",)
    model_license = "Llama 2 Community License"
    restricted = True
    upstream = "guardrails-ai/llamaguard-7b"
    timeout_ms = 5000
    requires_budget_ms = 6000

    def _generator(self) -> Any:  # pragma: no cover - requires gated weights
        def build() -> Any:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            _torch_one_thread()
            tokenizer = AutoTokenizer.from_pretrained(self.models[0], local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(
                self.models[0], dtype=torch.bfloat16, local_files_only=True
            )
            model.eval()
            return tokenizer, model

        return _load(("causal-lm", self.models[0]), build)

    def _verdict(self, text: str) -> str:  # pragma: no cover - requires gated weights
        import torch

        tokenizer, model = self._generator()
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": text[:4000]}], return_tensors="pt", return_dict=True
        )
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=20, pad_token_id=0)
        prompt_len = inputs["input_ids"].shape[-1]
        return tokenizer.decode(out[0][prompt_len:], skip_special_tokens=True).strip()

    def _warm(self) -> None:  # pragma: no cover - requires gated weights
        self._verdict("hello")

    def check(self, text: str, params: LlamaGuardParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        completion = self._verdict(text)
        if not completion.lower().startswith("unsafe"):
            return []
        lines = completion.splitlines()
        categories = [c.strip() for c in lines[1].split(",")] if len(lines) > 1 else []
        if params.policies is not None and not set(categories) & set(params.policies):
            return []
        policy = next(
            (LLAMA_GUARD_POLICIES[c] for c in categories if c in LLAMA_GUARD_POLICIES), None
        )
        return [
            _finding(
                text,
                0,
                0,
                f"unsafe content ({policy or 'uncategorised'})",
                1.0,
                categories=categories,
                policy=policy,
            )
        ]


#: ShieldGemma's policies, written in the form its model card prescribes.
SHIELDGEMMA_GUIDELINES: dict[str, str] = {
    "NO_DANGEROUS_CONTENT": (
        '"No Dangerous Content": The prompt shall not contain or seek generation of '
        "content that harms oneself and/or others (e.g., accessing or building firearms "
        "and explosive devices, promotion of terrorism, instructions for suicide)."
    ),
    "NO_HARASSMENT": (
        '"No Harassment": The prompt shall not contain or seek generation of content '
        "that is malicious, intimidating, bullying, or abusive content targeting another "
        "individual (e.g., physical threats, denial of tragic events, disparaging "
        "victims of violence)."
    ),
    "NO_HATE_SPEECH": (
        '"No Hate Speech": The prompt shall not contain or seek generation of content '
        "that targets identity and/or protected attributes (e.g., racial slurs, "
        "promotion of discrimination, calls to violence against protected groups) or "
        "dehumanizes, belittles or vilifies on the basis of race, ethnicity, religion, "
        "disability, age, nationality, veteran status, sexual orientation, gender, "
        "gender identity, caste, or any other protected status."
    ),
    "NO_SEXUAL_CONTENT": (
        '"No Sexually Explicit Information": The prompt shall not contain or seek '
        "generation of content that contains references to sexual acts or other lewd "
        "content (e.g., sexually graphic descriptions, content aimed at causing "
        "arousal). Medical or scientific terms related to human anatomy or sex "
        "education are permitted."
    ),
}


class ShieldGemmaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Policies to check, each scored separately (the model is trained on one at a
    #: time). None: all four.
    policies: (
        list[
            Literal["NO_DANGEROUS_CONTENT", "NO_HARASSMENT", "NO_HATE_SPEECH", "NO_SEXUAL_CONTENT"]
        ]
        | None
    ) = Field(None, min_length=1)
    #: Probability of "Yes, it violates" that fails the text. Upstream left the
    #: default to its hosted endpoint; 0.5 is the model card's decision point.
    threshold: float = Field(0.5, ge=0.0, le=1.0)


@register_validator
class ShieldGemma2B(_ModelValidator):
    """Upstream sent the text to Guardrails' hosted ShieldGemma endpoint; this runs
    `google/shieldgemma-2b` here, as Google documents it: the chat template with a
    ``guideline``, then P("Yes") from the next-token logits."""

    name = "shieldgemma_2b"
    label = "ShieldGemma 2B"
    description = (
        "Google's ShieldGemma scores the text against dangerous content, harassment, "
        "hate speech and sexual content policies."
    )
    entity_type = "SAFETY.SHIELD_GEMMA"
    surfaces = ("input", "output")
    Params = ShieldGemmaParams
    models = ("google/shieldgemma-2b",)
    model_license = "Gemma Terms of Use"
    restricted = True
    upstream = "guardrails-ai/shieldgemma-2b"
    timeout_ms = 2000
    requires_budget_ms = 3000

    def _model(self) -> Any:  # pragma: no cover - requires gated weights
        def build() -> Any:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            _torch_one_thread()
            tokenizer = AutoTokenizer.from_pretrained(self.models[0], local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(
                self.models[0], dtype=torch.bfloat16, local_files_only=True
            )
            model.eval()
            return tokenizer, model

        return _load(("causal-lm", self.models[0]), build)

    def _p_violation(self, text: str, policy: str) -> float:  # pragma: no cover
        import torch

        tokenizer, model = self._model()
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": text[:4000]}],
            guideline=SHIELDGEMMA_GUIDELINES[policy],
            return_tensors="pt",
            return_dict=True,
        )
        with torch.no_grad():
            logits = model(**inputs).logits
        vocab = tokenizer.get_vocab()
        yes_no = logits[0, -1, [vocab["Yes"], vocab["No"]]].float()
        return float(torch.softmax(yes_no, dim=0)[0])

    def _warm(self) -> None:  # pragma: no cover - requires gated weights
        self._p_violation("hello", "NO_HARASSMENT")

    def check(self, text: str, params: ShieldGemmaParams, ctx: CheckContext) -> list[Finding]:
        if not text.strip():
            return []
        out: list[Finding] = []
        for policy in params.policies or list(SHIELDGEMMA_GUIDELINES):
            score = self._p_violation(text, policy)
            if score > params.threshold:
                out.append(_finding(text, 0, 0, f"violates {policy}", score, policy=policy))
        return out
