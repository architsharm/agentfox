"""Safety-classifier adapters (P3-5).

Two tiers, and the split is a **licence** decision, not a quality one:

* :class:`GraniteGuardianDetector` — IBM Granite Guardian, **Apache-2.0 weights**.
  The default. Appendix A.1 calls this the cleanest licence in the classifier group,
  which is what a commercial product needs.
* :class:`RestrictedClassifierDetector` — Meta Llama Guard 3-8B (the only one of
  the three named in earlier revisions of this module that is actually wired up
  here; Prompt Guard and ShieldGemma share the same licence gate but have no
  registered adapter). The Llama Community licence is **not OSI-approved**: it
  adds an acceptable-use policy and a >700M-MAU clause. Appendix A.4 requires
  this to be opt-in, so the adapter refuses to load unless
  ``NOMETRIA_ACCEPT_RESTRICTED_MODEL_LICENSES=1`` — and, unlike every classifier
  above, it is not actually a classification model (see that class's docstring
  for why it cannot share `_TransformersClassifier`'s inference path).

Neither is installed by default. A customer must not inherit a licence obligation
by running ``docker compose up``.
"""

from __future__ import annotations

import functools

from ...config import get_settings
from ..base import BaseDetector, Detection, DetectionContext, redact_sample

#: Distinguishes "caller didn't pass this" (use the configured default) from an
#: explicit `None` (caller wants it off) — see `PromptInjectionClassifierDetector.__init__`.
_UNSET = object()


class _TransformersClassifier(BaseDetector):
    model_id: str = ""
    label_map: dict[str, str] = {}
    restricted: bool = False
    #: A model shipping custom modeling code (not a stock transformers architecture)
    #: needs this to load at all. Left False by default — executing a model repo's
    #: Python is a real trust boundary, so a subclass opts in explicitly rather than
    #: this being silently on for everyone. Only ever set for a specific, named,
    #: reputable model_id (see PromptInjectionClassifierDetector).
    trust_remote_code: bool = False

    def available(self) -> bool:
        if self.restricted and not get_settings().restricted_models_allowed:
            return False
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
            # NFR-4/NFR-9: never trigger a download at request time. Absent weights
            # mean "unavailable", not "fetch it now".
            return False

    @functools.cached_property
    def _pipeline(self):  # pragma: no cover - requires optional dependency
        import torch
        from transformers import pipeline

        # PyTorch's default intra-op thread pool sizes itself to the machine's core
        # count, which is right for one big batched job and wrong here: the
        # detector pipeline already parallelises across *detectors* with its own
        # ThreadPoolExecutor (P3-6), so every concurrent classifier call spawns
        # its own multi-threaded forward pass on top of that. The two thread pools
        # fight over the same cores — measured effect was ~22ms per call in
        # isolation ballooning past the 75ms timeout under concurrent/sustained
        # load. One torch thread per call is the standard fix for many-small-calls
        # serving, as opposed to few-large-batches.
        torch.set_num_threads(1)
        # `local_files_only` because `_weights_present()` has already confirmed
        # these are in the cache — there is nothing for the hub to tell us.
        # Without it transformers contacts huggingface.co on every load to check
        # for a newer revision, and on a host that cannot reach it that is not a
        # fast failure: measured 143.1s to warm this detector behind a blocked
        # network against 4.1s with the flag set, the difference being TCP
        # timeouts. `warm_all()` runs in the gateway's startup (see
        # `gateway.app.lifespan`), so an egress-restricted deployment — which is
        # the deployment this product is for — had its boot blocked for minutes,
        # long enough for an orchestrator's readiness probe to kill it first.
        return pipeline(
            "text-classification",
            model=self.model_id,
            top_k=None,
            trust_remote_code=self.trust_remote_code,
            local_files_only=True,
        )

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        if self.available():
            self._pipeline("")

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        scores = self._pipeline(content[:4000])
        rows = scores[0] if scores and isinstance(scores[0], list) else scores
        out: list[Detection] = []
        for row in rows or []:
            label = str(row.get("label", ""))
            score = float(row.get("score", 0.0))
            entity = self.label_map.get(label.lower())
            if not entity or score < 0.5:
                continue
            out.append(
                Detection(
                    entity_type=entity,
                    score=score,
                    end=len(content),
                    sample=redact_sample(content, keep=12),
                    owasp_id="LLM09",
                    detail={"engine": self.key, "model": self.model_id, "label": label},
                )
            )
        return out


class PromptInjectionClassifierDetector(_TransformersClassifier):
    """A model trained specifically on prompt injection, not a general safety
    classifier pressed into service for it — the same technique (and, in some
    deployments, literally the same underlying model) most competitor guardrail
    products use for this exact task, rather than `injection.heuristic`'s
    hand-written patterns.

    Uses `leolee99/PIGuard` (MIT), the over-defense-mitigated successor proposed
    in "InjecGuard: Benchmarking and Mitigating Over-defense in Prompt Injection
    Guardrail Models" (arXiv:2410.22770), swapped in after this project's own
    benchmarking (see `benchmarks/REPORT.md`) showed it beating the previous
    default (`protectai/deberta-v3-base-prompt-injection-v2`) on both axes at
    once: held-out recall on `deepset/prompt-injections` at 100% precision
    (31.7% -> 66.7%), and — more importantly — the true false-positive rate on
    `leolee99/NotInject` (339 benign prompts stuffed with injection-sounding
    vocabulary, purpose-built to catch keyword-reactive guardrails) dropping
    from 42.2% to 11.5%. Ships custom modeling code, so this is the one
    detector with `trust_remote_code = True`.
    """

    key = "injection.classifier"
    version = "1.0"
    surfaces = ("input", "retrieved", "tool_result", "output", "memory_write", "agent_message")
    label_map = {
        "injection": "INJECTION.JAILBREAK",
    }
    # A real forward pass on CPU, not a regex scan — 40ms (the pipeline default,
    # calibrated for heuristics) isn't enough headroom even once the model is warm.
    # Measured directly: solo warm latency is ~23ms, but p90 climbs to ~57ms and
    # observed max to ~85ms once `injection.similarity` runs alongside it in the
    # same request (GIL/CPU time-sharing between two concurrent torch forward
    # passes, not pool exhaustion — see REPORT.md's timeout-masking finding,
    # discovered because the previous 75ms ceiling was silently dropping a real
    # fraction of classifier detections as false "no detection" results). Raised
    # again after adding the ensemble secondary-model backstop: the common case
    # where the primary finds nothing now pays a second sequential forward pass,
    # measured at up to ~153ms end-to-end alongside similarity under load.
    timeout_ms = 250
    # PIGuard ships its own `modeling_piguard.py` in the model repo rather than
    # using a stock transformers architecture — trusted because it's the specific,
    # named, reputable model this class exists to wrap, not a general default.
    trust_remote_code = True

    # --- Ensemble backstop ------------------------------------------------
    # PIGuard's own benchmarking made it the clear primary — better recall AND
    # far fewer false positives on the primary benchmark and on NotInject (see
    # docstring above) — but it isn't uniformly better. On two OTHER
    # independent, never-tuned-against generalization datasets (SPML,
    # yanismiraoui), PIGuard's recall is markedly lower than
    # `protectai/deberta-v3-base-prompt-injection-v2`'s: 63.6%->28.4% and
    # 98.4%->75.5% respectively on the swap (`../../benchmarks/REPORT.md`).
    # Rather than pick one model and eat the other's blind spot, a second model
    # runs as a high-bar backstop — consulted only when the primary found
    # nothing, and only fires above `secondary_threshold`. That threshold
    # (0.92) is not invented here: it's llm-guard's own default for scoring
    # this exact model (`llm_guard.input_scanners.prompt_injection.PromptInjection`,
    # read directly from its source, not guessed), chosen there specifically
    # because this model is prone to over-triggering at a lower bar — which
    # matches this project's own NotInject finding for it (42.2% false-positive
    # rate at the 0.5 bar `_detect` uses for the primary model). Using the
    # secondary only as a high-confidence backstop, never as a co-equal OR,
    # is what keeps that liability from simply re-entering through the back
    # door.
    secondary_model_id: str | None = None
    secondary_threshold: float = 0.92

    def __init__(
        self, model_id: str | None = None, secondary_model_id: str | None | object = _UNSET
    ) -> None:
        settings = get_settings()
        self.model_id = model_id or settings.prompt_injection_classifier_model
        # `_UNSET` (not passed) means "use the configured default"; an explicit
        # `None` means "disable the backstop" — the two must stay distinguishable,
        # or a caller trying to turn the ensemble off silently keeps it on.
        self.secondary_model_id = (
            settings.prompt_injection_classifier_secondary_model
            if secondary_model_id is _UNSET
            else secondary_model_id
        )
        self.secondary_threshold = settings.prompt_injection_classifier_secondary_threshold

    @functools.cached_property
    def _secondary_pipeline(self):  # pragma: no cover - requires optional dependency
        if not self.secondary_model_id:
            return None
        import torch
        from transformers import pipeline

        torch.set_num_threads(1)
        # local_files_only: see `_TransformersClassifier._pipeline`.
        return pipeline(
            "text-classification",
            model=self.secondary_model_id,
            top_k=None,
            local_files_only=True,
        )

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        super().warm()
        if self.available() and self.secondary_model_id:
            pipe = self._secondary_pipeline
            if pipe is not None:
                pipe("")

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        primary = super()._detect(content, context)
        if primary or not self.secondary_model_id:
            return primary
        pipe = self._secondary_pipeline
        if pipe is None or not content:
            return primary
        scores = pipe(content[:4000])
        rows = scores[0] if scores and isinstance(scores[0], list) else scores
        for row in rows or []:
            label = str(row.get("label", ""))
            score = float(row.get("score", 0.0))
            if label.lower() != "injection" or score < self.secondary_threshold:
                continue
            return [
                Detection(
                    entity_type="INJECTION.JAILBREAK",
                    score=score,
                    end=len(content),
                    sample=redact_sample(content, keep=12),
                    owasp_id="LLM09",
                    detail={
                        "engine": self.key,
                        "model": self.secondary_model_id,
                        "label": label,
                        "role": "ensemble_secondary_backstop",
                    },
                )
            ]
        return []


class GraniteGuardianDetector(_TransformersClassifier):
    """IBM Granite Guardian — Apache-2.0. The default classifier."""

    key = "safety.granite"
    version = "1.0"
    surfaces = ("input", "output", "retrieved", "tool_result")
    label_map = {
        "yes": "SAFETY.HARM",
        "harmful": "SAFETY.HARM",
        "risky": "SAFETY.HARM",
        "jailbreak": "INJECTION.JAILBREAK",
        "unsafe": "SAFETY.HARM",
    }

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or get_settings().granite_guardian_model


class RestrictedClassifierDetector(_TransformersClassifier):
    """Llama Guard 3-8B. Opt-in, licence-gated.

    Unlike every other detector in this module, Llama Guard is not a
    classification model — it is a causal LM fine-tuned to *generate* the word
    "safe" or "unsafe\\nS<n>" in response to a chat-formatted prompt built from
    its own tokenizer's chat template (the taxonomy the template embeds is baked
    into the tokenizer config, not passed by the caller). Running it through
    `_TransformersClassifier`'s `pipeline("text-classification", ...)` — right
    for Granite Guardian and the two prompt-injection models, which really are
    fine-tuned classification heads — does not error for this model, but it
    silently attaches a freshly, randomly-initialized classification head on top
    of the pretrained base model (`config.json` declares `LlamaForCausalLM`, no
    classification head) and scores everything against untrained noise. That
    failure mode produces no error and no obviously-wrong output, so it would
    ship undetected. `_detect` below instead follows Meta's own documented usage
    (`apply_chat_template` + `generate`, checking whether the completion starts
    with "unsafe"), overriding the classification-pipeline machinery entirely
    while still reusing `available()`/`_weights_present()` from the base class.
    """

    key = "safety.restricted"
    version = "1.0"
    restricted = True
    surfaces = ("input", "output", "retrieved", "tool_result")
    #: Generation has no natural per-call confidence score the way a softmax
    #: over a trained classification head does — "unsafe" is a binary verdict,
    #: reported at the same fixed confidence schema.py's structural violations
    #: use for the same reason (see `_TransformersClassifier._detect` for the
    #: contrasting case where a real softmax score is available).
    _verdict_score = 1.0
    max_new_tokens = 20

    def __init__(self, model_id: str = "meta-llama/Llama-Guard-3-8B") -> None:
        self.model_id = model_id

    @functools.cached_property
    def _generator(self):  # pragma: no cover - requires optional dependency + gated weights
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(1)  # see _TransformersClassifier._pipeline for why
        # local_files_only: see `_TransformersClassifier._pipeline`.
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_id, torch_dtype=torch.bfloat16, local_files_only=True
        )
        model.eval()
        return tokenizer, model

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        if self.available():
            self._detect("hello", DetectionContext())

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        import torch

        tokenizer, model = self._generator
        # Llama Guard classifies whichever turn is *last* in the chat it's given,
        # against a different half of its taxonomy depending on that turn's role.
        # "output" is the only surface here that is itself a model completion;
        # everything else (input/retrieved/tool_result) is content arriving at
        # the model, which maps onto Llama Guard's "user" role.
        role = "assistant" if context.surface == "output" else "user"
        chat = [{"role": role, "content": content[:4000]}]
        input_ids = tokenizer.apply_chat_template(chat, return_tensors="pt")
        with torch.no_grad():
            generated = model.generate(
                input_ids=input_ids, max_new_tokens=self.max_new_tokens, pad_token_id=0
            )
        completion = tokenizer.decode(
            generated[0][input_ids.shape[-1] :], skip_special_tokens=True
        ).strip()

        if not completion.lower().startswith("unsafe"):
            return []
        # The category line ("S1".."S14" in the 3.x taxonomy) is passed through
        # verbatim rather than mapped to a specific entity type: Llama Guard's
        # categories are content-harm categories (violence, weapons, CSAE, etc.),
        # not a jailbreak/injection-specific taxonomy the way this project's other
        # detectors are, so a blanket SAFETY.HARM is the honest label rather than
        # guessing which category number should read as something more specific.
        category = completion.splitlines()[1].strip() if "\n" in completion else ""
        return [
            Detection(
                entity_type="SAFETY.HARM",
                score=self._verdict_score,
                end=len(content),
                sample=redact_sample(content, keep=12),
                owasp_id="LLM09",
                detail={"engine": self.key, "model": self.model_id, "category": category},
            )
        ]

    def license_notice(self) -> str:
        return (
            f"{self.model_id} is distributed under a non-OSI licence with usage "
            "restrictions (acceptable-use policy; Llama adds a >700M-MAU clause). "
            "Enabled only because NOMETRIA_ACCEPT_RESTRICTED_MODEL_LICENSES=1. "
            "Legal review required before commercial deployment — see Appendix A.4."
        )
