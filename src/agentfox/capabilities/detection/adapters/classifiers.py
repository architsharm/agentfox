"""Safety-classifier adapters.

Two tiers, and the split is a **licence** decision, not a quality one:

* :class:`GraniteGuardianDetector` — IBM Granite Guardian, **Apache-2.0 weights**.
  The default. A causal LM read for its "Yes"/"No" answer, not a classifier. It is
  the cleanest licence in the classifier group, which is what a
  commercial product needs.
* :class:`RestrictedClassifierDetector` — Meta Llama Guard 3-8B (Prompt Guard and
  ShieldGemma share the same licence gate but have no registered adapter). The
  Llama Community licence is **not OSI-approved**: it adds an acceptable-use policy
  and a >700M-MAU clause, so it has to be opt-in, and the adapter refuses to load unless
  ``AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1`` — and, unlike every classifier
  above, it is not actually a classification model (see that class's docstring
  for why it cannot share `_TransformersClassifier`'s inference path).

Neither is installed by default. A customer must not inherit a licence obligation
by running ``docker compose up``.
"""

from __future__ import annotations

from typing import Any

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    redact_sample,
)
from agentfox.capabilities.detection.loading import (
    inference_lock,
    load_once,
    model_device,
    to_model_device,
)
from agentfox.capabilities.detection.validators.base import module_present
from agentfox.core.config import get_settings

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
        # Decided once per process: `available()` runs on every request, and an
        # import attempt for a library that is not installed walks the whole import
        # path each time (see `module_present`). The weights check stays live, so a
        # `detectors pull` takes effect without a restart.
        if not module_present("transformers"):
            return False
        return self._weights_present()

    @property
    def unavailable_reason(self) -> str:
        """What is missing and the command that fixes it, for `doctor`, the
        dashboard's detector catalogue and the startup log. A property, as on the
        other adapters (`/api/detectors` reads it as a value)."""
        if self.restricted and not get_settings().restricted_models_allowed:
            return "restricted licence not accepted (AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1)"
        if not module_present("transformers"):
            return "needs `pip install 'agentfox[classifiers]'`"
        if not self._weights_present():
            return f"model not downloaded: run `agentfox admin detectors pull {self.key}`"
        return ""

    def _weights_present(self) -> bool:  # pragma: no cover - requires optional dep
        try:
            from huggingface_hub import try_to_load_from_cache

            return try_to_load_from_cache(self.model_id, "config.json") is not None
        except Exception:
            # Never trigger a download at request time. Absent weights
            # mean "unavailable", not "fetch it now".
            return False

    @load_once
    def _pipeline(self):  # pragma: no cover - requires optional dependency
        import torch
        from transformers import pipeline

        # PyTorch's default intra-op thread pool sizes itself to the machine's core
        # count, which is right for one big batched job and wrong here: the
        # detector pipeline already parallelises across *detectors* with its own
        # ThreadPoolExecutor, so every concurrent classifier call spawns
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
            device=model_device(),
        )

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        if self.available():
            pipe = self._pipeline
            with inference_lock(pipe):
                pipe("")

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        rows = _scored(self._pipeline, content)
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

    @load_once
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
            device=model_device(),
        )

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        super().warm()
        if self.available() and self.secondary_model_id:
            pipe = self._secondary_pipeline
            if pipe is not None:
                with inference_lock(pipe):
                    pipe("")

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        primary = super()._detect(content, context)
        if primary or not self.secondary_model_id:
            return primary
        pipe = self._secondary_pipeline
        if pipe is None or not content:
            return primary
        rows = _scored(pipe, content)
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
                        # Recorded, never blocked on: an enforcing policy does not see
                        # it (`PolicyInput.for_mode`). PIGuard alone false-positives
                        # 11.5% of NotInject; with this backstop it is 41%.
                        "advisory": True,
                    },
                )
            ]
        return []


#: Tokens per window a classifier scores. Text this short or shorter is scored whole;
#: longer text is scored in overlapping windows over all of it, in one batched pass.
#: The models here declare no maximum length, so 4,000 characters went in as one
#: sequence of about 650 tokens: slower (super-linear) and past the length they were
#: trained on, where a long benign document scored as a jailbreak.
WINDOW_TOKENS = 256
WINDOW_OVERLAP = 32


def _scored(pipe: Any, content: str) -> list[dict[str, Any]]:
    """Label scores for ``content``: the highest per label across its windows."""
    text = content[:4000]
    windows = [text]
    tokenizer = getattr(pipe, "tokenizer", None)
    if tokenizer is not None:
        try:
            ids = tokenizer(text, add_special_tokens=False)["input_ids"]
        except Exception:  # pragma: no cover - a tokenizer that cannot count: score whole
            ids = []
        if len(ids) > WINDOW_TOKENS:
            # Overlapping windows over the whole text, so an injection in the middle of
            # a long document is read too, each within the length the model handles.
            step = WINDOW_TOKENS - WINDOW_OVERLAP
            starts = list(range(0, len(ids) - WINDOW_OVERLAP, step))
            windows = [tokenizer.decode(ids[i : i + WINDOW_TOKENS]) for i in starts]
    with inference_lock(pipe):
        scores = pipe(windows if len(windows) > 1 else windows[0])
    if len(windows) == 1:
        return scores[0] if scores and isinstance(scores[0], list) else list(scores or [])
    best: dict[str, dict[str, Any]] = {}
    for rows in scores:
        for row in rows if isinstance(rows, list) else [rows]:
            label = str(row.get("label", ""))
            if label not in best or float(row.get("score", 0.0)) > float(best[label]["score"]):
                best[label] = row
    return list(best.values())


class GraniteGuardianDetector(_TransformersClassifier):
    """IBM Granite Guardian — Apache-2.0. The default classifier.

    Granite Guardian is a causal LM (``GraniteForCausalLM``), not a classification
    model: given its chat template and a risk name, it answers "Yes" (the content
    carries that risk) or "No" as its next token. It used to run through
    `_TransformersClassifier`'s ``pipeline("text-classification")``, which, for a model
    with no classification head, scores against a randomly initialised one (older
    transformers) or fails outright (current transformers, which crashed the
    gateway's startup in `warm()`). This reads the model's own answer instead: one
    forward pass, and the probability of "Yes" against "No" for the next token,
    which is IBM's documented scoring.

    Only the "harm" risk is checked. Measured on this model, the "jailbreak" risk
    scored "Summarise this article for me." at 0.95; prompt injection is
    `injection.heuristic`'s and `injection.classifier`'s job.

    It is slow on CPU: a forward pass of a 2B model measured about 8 s on one thread
    and 3 s on four (float32), against a 40 ms default per-detector timeout and a
    300 ms request budget. Enabled without a GPU, it reports as degraded on every
    call rather than checking anything. That is a deployment decision, not one this
    class can make.
    """

    key = "safety.granite"
    version = "2.0"
    surfaces = ("input", "output", "retrieved", "tool_result")
    #: The risk name Granite Guardian's chat template takes, and what it reports.
    risks = {"harm": "SAFETY.HARM"}
    threshold = 0.5

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or get_settings().granite_guardian_model

    @load_once
    def _guardian(self):  # pragma: no cover - requires optional dependency + weights
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(1)  # see _TransformersClassifier._pipeline for why
        # local_files_only: see `_TransformersClassifier._pipeline`. float32, because
        # bfloat16 is emulated on most CPUs: measured 26 s per pass against 8 s.
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_id, torch_dtype=torch.float32, local_files_only=True
        )
        model.to(model_device()).eval()
        yes = tokenizer.encode("Yes", add_special_tokens=False)[0]
        no = tokenizer.encode("No", add_special_tokens=False)[0]
        return tokenizer, model, yes, no

    def chat(self, content: str, surface: str) -> list[dict[str, str]]:
        """The conversation Granite Guardian judges. A model's output is judged as an
        assistant turn; its template refuses an assistant turn with no user turn
        before it, so that one is empty. Everything else arrives at the model, as a
        user turn."""
        if surface == "output":
            return [{"role": "user", "content": ""}, {"role": "assistant", "content": content}]
        return [{"role": "user", "content": content}]

    def risk_probability(self, chat: list[dict[str, str]], risk: str) -> float:
        """P("Yes") against P("No") for the model's next token: how sure it is the
        last turn carries ``risk``."""
        import torch

        tokenizer, model, yes, no = self._guardian
        ids = tokenizer.apply_chat_template(
            chat,
            guardian_config={"risk_name": risk},
            add_generation_prompt=True,
            return_tensors="pt",
        )
        if not isinstance(ids, torch.Tensor):  # a BatchEncoding in newer transformers
            ids = ids["input_ids"]
        ids = to_model_device(ids, model)
        with inference_lock(model), torch.no_grad():
            logits = model(input_ids=ids).logits[0, -1].float()
        return float(torch.softmax(logits[[yes, no]], dim=0)[0])

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        # Not an empty string: that is zero tokens, which the model cannot run.
        if self.available():
            self._detect("hello", DetectionContext())

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        chat = self.chat(content[:4000], context.surface)
        out: list[Detection] = []
        for risk, entity in self.risks.items():
            score = self.risk_probability(chat, risk)
            if score < self.threshold:
                continue
            out.append(
                Detection(
                    entity_type=entity,
                    score=score,
                    end=len(content),
                    sample=redact_sample(content, keep=12),
                    owasp_id="LLM09",
                    detail={"engine": self.key, "model": self.model_id, "risk": risk},
                )
            )
        return out


class RestrictedClassifierDetector(_TransformersClassifier):
    """Llama Guard 3-8B. Opt-in, licence-gated.

    Unlike every other detector in this module, Llama Guard is not a
    classification model — it is a causal LM fine-tuned to *generate* the word
    "safe" or "unsafe\\nS<n>" in response to a chat-formatted prompt built from
    its own tokenizer's chat template (the taxonomy the template embeds is baked
    into the tokenizer config, not passed by the caller). Running it through
    `_TransformersClassifier`'s `pipeline("text-classification", ...)` — right
    for the two prompt-injection models, which really are fine-tuned
    classification heads, and wrong for Granite Guardian too (see
    `GraniteGuardianDetector`) — does not error for this model, but it
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

    @load_once
    def _generator(self):  # pragma: no cover - requires optional dependency + gated weights
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(1)  # see _TransformersClassifier._pipeline for why
        # local_files_only: see `_TransformersClassifier._pipeline`.
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_id, torch_dtype=torch.bfloat16, local_files_only=True
        )
        model.to(model_device()).eval()
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
        if not isinstance(input_ids, torch.Tensor):  # a BatchEncoding in newer transformers
            input_ids = input_ids["input_ids"]
        input_ids = to_model_device(input_ids, model)
        with inference_lock(model), torch.no_grad():
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
            "Enabled only because AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1. "
            "Legal review required before commercial deployment — see Appendix A.4."
        )
