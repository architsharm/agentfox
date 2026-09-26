"""Guardrail-orchestration adapters — NeMo Guardrails and Guardrails AI (P3-1/P3-9).

Both are Apache-2.0 and actively maintained (Appendix A.1), and the catalog's advice
is "compose checks; don't hand-roll the runner". We take that seriously but not
literally: our pipeline is the primary runner because it has to enforce the latency
budget (NFR-1), record per-detector telemetry (P3-11), and feed control status
(P6-4) — none of which these projects model. They are wrapped as *detectors inside*
our pipeline, which is the same wrap-the-primitive-own-the-interface split used
everywhere else.

Licence caution carried from Appendix A.1: the Guardrails AI **core** is Apache-2.0,
but individual Guardrails Hub validators carry their own licences. Any Hub validator
must be licence-checked before it ships, so none is enabled by default.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any

from ..base import BaseDetector, Detection, DetectionContext, redact_sample

log = logging.getLogger(__name__)


class NemoRailsDetector(BaseDetector):
    """NVIDIA NeMo Guardrails — programmable rails (Colang).

    Turned on by pointing `nemo_rails_config_path` at a directory holding a NeMo
    config (`config.yml` plus any Colang files) and adding `rails.nemo` to
    `enabled_detectors`. Until that setting existed this detector could not be
    reached at all: it was registered as `NemoRailsDetector()` with no path, and
    `available()` returns False without one, so `pip install agentfox[rails]`
    installed a dependency that nothing could ever use.

    The path is read from settings on every call rather than captured at
    construction, because registration happens at import time — before a config
    file has necessarily been resolved — and a value frozen then would ignore
    the operator's config.

    Note that NeMo's rails need a model: its dialog rails match intent through
    an LLM, and even a purely Colang flow raises `No LLM provided to llm_call()`
    without one. The config directory must therefore declare a model NeMo can
    reach. That is a property of NeMo, not of this adapter — but it is the first
    thing that goes wrong, so `_detect` treats a config that cannot run as a
    failed check rather than a clean pass.
    """

    key = "rails.nemo"
    version = "1.0"
    surfaces = ("input", "output")

    def __init__(self, config_path: str | None = None) -> None:
        #: An explicit path wins over settings; used by tests and by anyone
        #: constructing the detector directly rather than through the registry.
        self._explicit_config_path = config_path

    @property
    def config_path(self) -> str | None:
        if self._explicit_config_path:
            return self._explicit_config_path
        from ...config import get_settings

        return get_settings().nemo_rails_config_path or None

    def available(self) -> bool:
        path = self.config_path
        if not path:
            return False
        # A path that is not there is a misconfiguration, not an absence. Saying
        # so beats an LLMRails constructor exception on the first real request.
        if not Path(path).expanduser().is_dir():
            return False
        try:
            import nemoguardrails  # noqa: F401
        except Exception:
            return False
        return True

    @property
    def unavailable_reason(self) -> str:
        path = self.config_path
        try:
            import nemoguardrails  # noqa: F401
        except Exception:
            return (
                "NVIDIA NeMo Guardrails — the `nemoguardrails` package is not "
                "installed. `pip install 'agentfox[rails]'`, then set "
                "`nemo_rails_config_path` to a NeMo config directory and add "
                "`rails.nemo` to enabled_detectors."
            )
        if not path:
            return (
                "NVIDIA NeMo Guardrails is installed but has no rails to run. "
                "Set `nemo_rails_config_path` (AGENTFOX_NEMO_RAILS_CONFIG_PATH) "
                "to a directory holding a NeMo `config.yml` and its Colang "
                "files, then add `rails.nemo` to enabled_detectors. Which rails "
                "to run is a deployment's decision, so there is no default."
            )
        return (
            f"NVIDIA NeMo Guardrails — `nemo_rails_config_path` is set to "
            f"{path!r}, which is not a directory. It must point at the folder "
            "holding `config.yml`, not at the file itself."
        )

    @functools.cached_property
    def _rails(self):  # pragma: no cover - requires optional dependency
        from nemoguardrails import LLMRails, RailsConfig

        return LLMRails(RailsConfig.from_path(str(Path(self.config_path).expanduser())))

    #: NeMo's own text for "something in here blew up", from
    #: `nemoguardrails.guardrails.iorails.INTERNAL_ERROR_MESSAGE`. Matched as a
    #: string rather than imported, because importing a constant out of their
    #: internals is a harder dependency than reading one sentence.
    _INTERNAL_ERROR = "an internal error has occurred"

    #: Fallback only, for a nemoguardrails too old to return activated rails.
    _REFUSAL_MARKERS = ("i'm not able to", "i am not able to", "i cannot", "i can't")

    def _detect(
        self, content: str, context: DetectionContext
    ) -> list[Detection]:  # pragma: no cover
        if not content:
            return []

        # Ask for the activated rails, not just the reply. NeMo answers with a
        # *message*, and reading a verdict out of prose meant matching on
        # phrases like "i cannot" — which misses a rail whose refusal is worded
        # differently, and cannot tell a refusal from a failure at all.
        rails_fired: list[str] = []
        try:
            result = self._rails.generate(
                messages=[{"role": "user", "content": content}],
                options={"log": {"activated_rails": True}},
            )
            response = getattr(result, "response", result)
            if isinstance(response, list):
                response = response[-1] if response else {}
            log_obj = getattr(result, "log", None)
            rails_fired = [
                getattr(rail, "name", "?")
                for rail in (getattr(log_obj, "activated_rails", None) or [])
                if getattr(rail, "stop", False)
            ]
        except Exception:
            # `options` is not accepted by every version; the prose reading below
            # still works, so fall back rather than losing the detector.
            response = self._rails.generate(messages=[{"role": "user", "content": content}])

        text = response.get("content", "") if isinstance(response, dict) else str(response)
        lowered = text.lower()

        # A rails config that cannot run is a broken check, not a clean pass.
        # Measured: with no model configured for a `self check input` flow, NeMo
        # catches its own ValueError, answers "I'm sorry, an internal error has
        # occurred." and marks the rail stopped. Reading that as prose found no
        # refusal marker in it, so a completely non-functional rails config
        # reported zero detections — "nothing found" for a check that never ran.
        # `adapters/hub.py` already raises in this situation for the same reason;
        # this one did not.
        if self._INTERNAL_ERROR in lowered:
            raise RuntimeError(
                f"{self.key} could not run: NeMo returned its internal-error "
                f"response for the config at {self.config_path}. Its own log has "
                "the cause — most often no model configured for the flow."
            )

        stopped = bool(rails_fired) or any(m in lowered for m in self._REFUSAL_MARKERS)
        if stopped:
            return [
                Detection(
                    entity_type="RAILS.BLOCKED",
                    score=0.9,
                    end=len(content),
                    sample=redact_sample(text, keep=24),
                    detail={
                        "engine": "nemoguardrails",
                        "config": self.config_path,
                        "rails": rails_fired,
                    },
                )
            ]
        return []


class GuardrailsAiDetector(BaseDetector):
    """Guardrails AI validators — structured output and I/O validation."""

    key = "rails.guardrails_ai"
    version = "1.0"
    surfaces = ("output", "tool_args")

    def __init__(self, validators: list[Any] | None = None) -> None:
        #: Explicit validator instances win over settings; used by tests and by
        #: anyone composing a Guard in code.
        self._explicit_validators = list(validators or [])

    @property
    def validator_slugs(self) -> list[str]:
        """Hub slugs named in settings, e.g. ["valid_json", "detect_pii"]."""
        if self._explicit_validators:
            return []
        from ...config import get_settings

        return [s for s in (get_settings().guardrails_ai_validators or []) if s]

    @property
    def validators(self) -> list[Any]:
        """The validator instances this Guard composes.

        Resolved from settings each time rather than captured at construction,
        for the same reason as `NemoRailsDetector.config_path`: the detector is
        registered at import time, before an operator's config exists.

        Slugs go through the Hub loader, so a slug that is not installed, or
        whose package is installed and broken, resolves to nothing here exactly
        as it does for the per-validator `rails.hub.*` detectors — one loader,
        one set of failure modes.
        """
        if self._explicit_validators:
            return list(self._explicit_validators)
        return [v for v in (self._resolve(slug) for slug in self.validator_slugs) if v is not None]

    @staticmethod
    def _resolve(slug: str) -> Any:
        from .hub import _load_validator_class

        cls = _load_validator_class(slug)
        if cls is None:
            return None
        try:
            return cls()
        except Exception as exc:  # pragma: no cover - depends on the package
            log.warning("guardrails-ai validator %s failed to construct: %s", slug, exc)
            return None

    def available(self) -> bool:
        try:
            import guardrails  # noqa: F401
        except Exception:
            return False
        return bool(self.validators)

    @property
    def unavailable_reason(self) -> str:
        try:
            import guardrails  # noqa: F401
        except Exception:
            return (
                "Guardrails AI — the `guardrails-ai` package is not installed. "
                "`pip install 'agentfox[validators]'`, then name the validators "
                "to run in `guardrails_ai_validators`."
            )
        asked = self.validator_slugs
        if not asked:
            return (
                "Guardrails AI is installed but has no validators to run. Name "
                "them in `guardrails_ai_validators` (AGENTFOX_GUARDRAILS_AI_"
                "VALIDATORS), e.g. [\"valid_json\", \"detect_pii\"], and install "
                "each one — Hub validators carry licences independent of the "
                "Apache-2.0 core, so none is enabled by inheritance. Prefer the "
                "per-validator `rails.hub.*` detectors unless you specifically "
                "want several evaluated as one Guard: this one reports every "
                "failure as SCHEMA.VIOLATION, which no policy rule matches."
            )
        missing = [slug for slug in asked if self._resolve(slug) is None]
        return (
            "Guardrails AI — none of the named validators could be loaded: "
            f"{', '.join(missing)}. Install each with `pip install "
            "guardrails-ai-<slug-with-dashes>`; if it is already installed, it "
            "failed to construct and the log line above says why."
        )

    @functools.cached_property
    def _guard(self):  # pragma: no cover - requires optional dependency
        from .hub import _silence_guardrails_telemetry

        # Before their package builds anything. `_resolve` already does this for
        # slug-configured validators; a caller passing instances never went
        # through it, and Guardrails AI's OTLP exporter ships spans to an AWS
        # endpoint of theirs the moment a Guard exists.
        _silence_guardrails_telemetry()
        from guardrails import Guard

        guard = Guard()
        # `use_many` was theirs through 0.5.x and is gone by 0.11, where `use`
        # takes the spread instead. pyproject allows >=0.5, so both are real.
        # Against 0.11 the old call raised `'Guard' object has no attribute
        # 'use_many'` on the first request — the composite could never run.
        if hasattr(guard, "use_many"):
            return guard.use_many(*self.validators)
        return guard.use(*self.validators)

    def _detect(
        self, content: str, context: DetectionContext
    ) -> list[Detection]:  # pragma: no cover
        if not content:
            return []
        summaries: list[str] = []
        try:
            outcome = self._guard.validate(content)
        except Exception as exc:
            # Their default `on_fail` RAISES on a failed validation rather than
            # returning an outcome — so the old code, which only read
            # `validation_passed`, turned every genuine finding into a thrown
            # detector. The pipeline then recorded `error` and degraded the
            # check, which reports a real violation as a broken control: the
            # one direction a guardrail must never fail in.
            if type(exc).__name__ != "ValidationError":
                raise
            summaries = [" ".join(str(exc).split())[:300]]
            outcome = None
        else:
            if getattr(outcome, "validation_passed", True):
                return []
            summaries = [str(s) for s in (getattr(outcome, "validation_summaries", None) or [])][
                :10
            ]
        return [
            Detection(
                entity_type="SCHEMA.VIOLATION",
                score=1.0,
                end=len(content),
                sample="guardrails-ai validation failed",
                owasp_id="LLM05",
                detail={
                    "engine": "guardrails-ai",
                    "validators": (
                        self.validator_slugs or [type(v).__name__ for v in self.validators]
                    ),
                    "summaries": summaries,
                },
            )
        ]
