"""Guardrails AI Hub validators, one detector each (P3-1 / P3-9).

`adapters/rails.py` already wrapped Guardrails AI, but as a single detector with
an empty validator list: nothing was configured by default, and when something
did fire, every failure — a jailbreak, a leaked secret, malformed SQL —
flattened into one `SCHEMA.VIOLATION`. That is the wrong shape twice over. It
cannot be tuned, because precision and latency are recorded per detector key and
there was only one key. And it cannot be governed, because our policies match on
entity prefixes (`entity_prefix: INJECTION`), so a jailbreak arriving as
`SCHEMA.VIOLATION` matched no rule anybody had written.

So each validator is its own detector here, with its own key, its own measured
precision and latency, its own suppressions, and — the part that matters — an
entity type from *our* taxonomy. Installing `guardrails-ai-detect-jailbreak` and
enabling `rails.hub.detect_jailbreak` makes the baseline policy's existing
INJECTION rule fire on it. No new rule, no new policy version.

That is the trade this adapter exists to make. Guardrails AI has sixty-five
validators and no notion of latency budget, per-detector telemetry, or control
status; we have those and a much smaller library. Wrapping theirs at the
granularity of one validator per detector is what lets both halves count.

**Nothing here is available by default, and that is deliberate.** Hub validators
carry their own licences, independent of the Apache-2.0 core (Appendix A.1), and
several download model weights on first use. A detector appears as available
only once someone has installed that specific package on purpose, and still has
to be named in `enabled_detectors` before it runs.

The validator class is *discovered*, not hard-coded. Guardrails is mid-migration
from `guardrails.hub` to standalone `guardrails_ai.<slug>` packages (their own
README puts the cutoff at 2026-08-25), and a hard-coded class name that drifts
fails silently — the import raises, `available()` returns False, and the
detector sits in the UI reading "not installed" forever with nobody able to tell
that from the truth. Importing the module and finding the Validator subclass in
it survives a rename and both import paths.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from typing import Any

from ..base import BaseDetector, Detection, DetectionContext, redact_sample

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HubValidator:
    """One Guardrails Hub validator, mapped onto our taxonomy.

    `slug` is the module name under `guardrails_ai.` and the tail of the pip
    package (`guardrails-ai-<slug-with-dashes>`). `entity_type` is what a
    detection is reported as, chosen so existing policy rules match it.
    """

    slug: str
    label: str
    entity_type: str
    surfaces: tuple[str, ...]
    owasp_id: str | None = None
    atlas_id: str | None = None
    #: Real model forward passes need more than the default per-detector budget.
    timeout_ms: int | None = None
    note: str = ""


#: The validators worth mapping, out of the sixty-five on the hub.
#:
#: Chosen on one rule: it has to answer a question this product already asks. A
#: validator that measures reading level or sentence redundancy is a fine thing
#: and tells an operator nothing about whether an agent should have been stopped,
#: so it is not here. Entity types reuse the prefixes our shipped policies
#: already match on — INJECTION, PII, SECRET, SAFETY, SCHEMA — rather than
#: inventing a parallel vocabulary that no rule would fire on.
CATALOGUE: tuple[HubValidator, ...] = (
    # --- Injection and jailbreak → INJECTION.*, matched by baseline's rules ---
    HubValidator(
        "detect_jailbreak", "Detect Jailbreak", "INJECTION.JAILBREAK",
        ("input", "retrieved", "tool_result", "agent_message"),
        owasp_id="LLM01", atlas_id="AML.T0054", timeout_ms=400,
        note="Model-backed. Downloads weights on first use.",
    ),
    HubValidator(
        "detect_prompt_injection", "Detect Prompt Injection", "INJECTION.CLASSIFIER",
        ("input", "retrieved", "tool_result", "memory_write", "agent_message"),
        owasp_id="LLM01", atlas_id="AML.T0051", timeout_ms=400,
        note="Model-backed. Downloads weights on first use.",
    ),
    HubValidator(
        "unusual_prompt", "Unusual Prompt", "INJECTION.UNUSUAL",
        ("input", "retrieved"), owasp_id="LLM01", timeout_ms=600,
        note="Calls an LLM to judge the prompt. Costs a model call per check.",
    ),
    # --- Disclosure ---
    HubValidator(
        "detect_system_prompt_leakage", "Detect System Prompt Leakage",
        "DISCLOSURE.SYSTEM_PROMPT", ("output",), owasp_id="LLM07",
    ),
    # --- Data protection → the prefixes pii.native and secrets.native use ---
    HubValidator(
        "detect_pii", "Detect PII", "PII.HUB",
        ("input", "output", "retrieved", "tool_args", "tool_result"), owasp_id="LLM02",
    ),
    HubValidator(
        "secrets_present", "Secrets Present", "SECRET.HUB",
        ("input", "output", "tool_args", "tool_result", "memory_write"), owasp_id="LLM02",
    ),
    # --- Content safety → SAFETY.*, matched by baseline's safety rules ---
    HubValidator(
        "toxic_language", "Toxic Language", "SAFETY.TOXIC",
        ("input", "output", "agent_message"), owasp_id="LLM09", timeout_ms=400,
        note="Model-backed. Downloads weights on first use.",
    ),
    HubValidator("nsfw_text", "NSFW Text", "SAFETY.NSFW", ("output",), timeout_ms=400),
    HubValidator("profanity_free", "Profanity Free", "SAFETY.PROFANITY", ("output",)),
    HubValidator("mentions_drugs", "Mentions Drugs", "SAFETY.DRUGS", ("output",)),
    HubValidator("ban_list", "Ban List", "SAFETY.BANNED_TERM", ("input", "output")),
    HubValidator("bias_check", "Bias Check", "SAFETY.BIAS", ("output",), timeout_ms=400),
    # --- Scope and brand ---
    HubValidator(
        "restrict_to_topic", "Restrict To Topic", "TOPIC.OUT_OF_SCOPE",
        ("output",), timeout_ms=400,
        note="Complements the knowledge boundary (P7), which answers a different "
             "question: whether the agent had the data, not whether the topic is in scope.",
    ),
    HubValidator("competitor_check", "Competitor Check", "BRAND.COMPETITOR", ("output",)),
    # --- Generated code and statements → the action side ---
    HubValidator(
        "valid_sql", "Valid SQL", "SCHEMA.SQL_INVALID", ("tool_args", "output"),
        note="Syntax only. analyse_sql (P9) is what refuses an unbounded DELETE.",
    ),
    HubValidator(
        "exclude_sql_predicates", "Exclude SQL Predicates", "ACTION.SQL_PREDICATE",
        ("tool_args",), owasp_id="LLM05",
    ),
    HubValidator(
        "web_sanitization", "Web Sanitization", "CODE.XSS", ("output",), owasp_id="LLM05",
    ),
    HubValidator("valid_json", "Valid JSON", "SCHEMA.JSON_INVALID", ("output", "tool_args")),
    # --- Safety models someone may already run ---
    HubValidator(
        "llama_guard", "Llama Guard", "SAFETY.LLAMA_GUARD", ("input", "output"),
        timeout_ms=900, note="Licence-gated model. Read Meta's terms before enabling.",
    ),
    HubValidator(
        "shield_gemma", "Shield Gemma", "SAFETY.SHIELD_GEMMA", ("input", "output"),
        timeout_ms=900, note="Licence-gated model. Read Google's terms before enabling.",
    ),
)


def _silence_guardrails_telemetry() -> None:
    """Stop Guardrails AI phoning home before any validator runs.

    Found by running this adapter against the real package: importing a Hub
    validator starts an OpenTelemetry exporter that POSTs spans to a third-party
    endpoint (an AWS API Gateway host), and `RC.enable_metrics` defaults to True
    with no environment override — the only way to turn it off is a
    `~/.guardrailsrc` file the operator has to know to write.

    That is not a defect in their project; it is a reasonable default for a
    library. It is intolerable here. This product's first README line is that it
    runs offline with no egress, `NOMETRIA_ALLOW_EGRESS` defaults to false, and
    the whole argument for self-hosting a governance tool is that it does not
    quietly talk to anyone. A control plane that starts exporting telemetry to a
    third party the moment somebody enables a PII check would be breaking its own
    promise, on a page that advertises the promise.

    So it is switched off unconditionally rather than behind our own egress
    setting: allowing egress means our operator chose to let *this product* reach
    a model provider they configured, not to let a transitive dependency report
    on them. Best-effort — their internals have moved between versions, and
    failing to silence telemetry must not take the detector down with it.
    """
    try:
        from guardrails import settings  # type: ignore

        settings.disable_tracing = True
        rc = getattr(settings, "rc", None)
        if rc is not None:
            rc.enable_metrics = False
            # Belt to that braces: the hosted inferencing they are retiring in
            # August 2026 is another way a validator reaches the network.
            if hasattr(rc, "use_remote_inferencing"):
                rc.use_remote_inferencing = False
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        log.warning("could not disable guardrails-ai telemetry: %s", exc)


def _load_validator_class(slug: str) -> type | None:
    """Find the Validator subclass in a hub validator's module.

    Tries the standalone package first (`guardrails_ai.<slug>`, the form their
    README now documents) and falls back to the classic namespace
    (`guardrails.hub`). Returns None if neither is installed — which is the
    normal state, not an error.
    """
    try:
        from guardrails.validator_base import Validator  # type: ignore
    except Exception:
        return None

    # Before anything of theirs is imported or constructed.
    _silence_guardrails_telemetry()

    module = None
    for name in (f"guardrails_ai.{slug}", "guardrails.hub"):
        try:
            module = __import__(name, fromlist=["*"])
            break
        except Exception:
            continue
    if module is None:
        return None

    # The module exports exactly one Validator subclass in the standalone case.
    # In the shared `guardrails.hub` namespace it exports many, so match on the
    # slug: "detect_jailbreak" -> "DetectJailbreak", case-insensitively, which
    # also catches the acronym spellings (NSFWText, ValidSQL) that a naive
    # title-case would miss.
    want = slug.replace("_", "").lower()
    candidates = []
    for attr in dir(module):
        obj = getattr(module, attr, None)
        if isinstance(obj, type) and issubclass(obj, Validator) and obj is not Validator:
            candidates.append(obj)
            if attr.replace("_", "").lower() == want:
                return obj
    return candidates[0] if len(candidates) == 1 else None


class HubValidatorDetector(BaseDetector):
    """One Guardrails Hub validator, as one of our detectors.

    Calls the validator directly rather than through `Guard`. A Guard is an
    orchestrator — it composes validators, handles retries and reask prompts, and
    can call a model. We already have an orchestrator with a latency budget and
    per-detector telemetry, and running a second one inside it would put the
    budget outside the thing it is supposed to bound.
    """

    version = "1.0"

    def __init__(self, spec: HubValidator, **kwargs: Any) -> None:
        self.spec = spec
        self.key = f"rails.hub.{spec.slug}"
        self.surfaces = spec.surfaces
        self.timeout_ms = spec.timeout_ms
        self._kwargs = kwargs

    @property
    def package(self) -> str:
        """The pip package that makes this detector available."""
        return f"guardrails-ai-{self.spec.slug.replace('_', '-')}"

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    def unavailable_reason(self) -> str:
        """Why it is not live, and the one command that changes that.

        Carried on the detector rather than in the gateway's hard-coded table,
        because a catalogue of twenty entries maintained in a different file from
        the catalogue itself will drift on the first addition.
        """
        note = f" {self.spec.note}" if self.spec.note else ""
        return (
            f"{self.spec.label} from the Guardrails AI Hub — not installed. "
            f"Install it with `pip install {self.package}`, then add "
            f"`{self.key}` to enabled_detectors. Hub validators carry their own "
            f"licences, independent of the Apache-2.0 core, so none ships "
            f"enabled.{note}"
        )

    def available(self) -> bool:
        return self._validator is not None

    @functools.cached_property
    def _validator(self) -> Any:
        cls = _load_validator_class(self.spec.slug)
        if cls is None:
            return None
        try:
            # `on_fail` is deliberately not passed: their failure actions (raise,
            # fix, reask) are decisions about what to DO, and what to do is our
            # policy engine's job. We want the finding, not their remedy.
            return cls(**self._kwargs)
        except Exception as exc:  # pragma: no cover - depends on the package
            log.warning("guardrails hub validator %s failed to construct: %s", self.spec.slug, exc)
            return None

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        # Several of these load model weights on first call. The per-detector
        # budget is tens of milliseconds, so paying that cost on a real request
        # would degrade the detector exactly once and look like a flake.
        _ = self._validator

    def _detect(
        self, content: str, context: DetectionContext
    ) -> list[Detection]:  # pragma: no cover - requires optional dependency
        validator = self._validator
        if not content or validator is None:
            return []
        try:
            outcome = validator.validate(content, {})
        except Exception as exc:
            # A validator that throws is a broken check, not a clean pass. Raising
            # lets the pipeline record it as `error` and degrade this one detector,
            # which is the behaviour a missing control needs — silently returning
            # [] would report "nothing found" for a check that never ran.
            raise RuntimeError(f"{self.key} raised: {exc}") from exc

        # Their result types have moved between namespaces across versions, so
        # this reads the shape rather than importing the class. Two independent
        # signals, because either alone is brittle: FailResult carries a
        # non-empty `error_message` and PassResult has none, and the class name
        # says so too. Matching on the name ALONE was the first version of this
        # and it silently treated every failure as a pass the moment a subclass
        # or a rename appeared.
        failed = bool(getattr(outcome, "error_message", None)) or "fail" in type(
            outcome
        ).__name__.lower()
        if not failed:
            return []

        reason = str(getattr(outcome, "error_message", "") or self.spec.label)
        return [
            Detection(
                entity_type=self.spec.entity_type,
                score=1.0,
                end=len(content),
                # The validator's message can quote the offending span verbatim,
                # so it is redacted like any other sample (P5-5): an audit row
                # that echoes the secret it found is a new liability.
                sample=redact_sample(reason, keep=24),
                owasp_id=self.spec.owasp_id,
                atlas_id=self.spec.atlas_id,
                detail={"engine": "guardrails-ai", "validator": self.spec.slug},
            )
        ]


def hub_detectors() -> list[HubValidatorDetector]:
    """Every catalogued validator, as detectors. Unavailable ones included.

    Registering the unavailable ones on purpose: the Detectors strip on the
    Policies page counts "not installed" separately from "off", so an operator
    can see that a jailbreak classifier is one `pip install` away instead of
    having to know the catalogue exists.
    """
    return [HubValidatorDetector(spec) for spec in CATALOGUE]
