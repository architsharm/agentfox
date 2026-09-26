"""Microsoft Presidio adapter — PII detection (P3-2).

Appendix A.1: MIT, actively maintained, the de-facto OSS standard. The build-vs-reuse
rule is explicit about this one — *rebuilding PII detection from scratch would be
pure duplicated work.* We wrap it and own the policy/action layer above it.

Exposure if Presidio changes status: **low**. It sits behind ``Detector`` and the
native implementation in ``detectors/pii.py`` covers the offline path.
"""

from __future__ import annotations

import functools

from ..base import BaseDetector, Detection, DetectionContext, redact_sample

# Presidio's entity names -> our taxonomy, so a policy written against
# `PII.US_SSN` behaves identically whichever engine produced the finding.
_ENTITY_MAP = {
    "EMAIL_ADDRESS": "PII.EMAIL",
    "PHONE_NUMBER": "PII.US_PHONE",
    "CREDIT_CARD": "PII.CREDIT_CARD",
    "US_SSN": "PII.US_SSN",
    "US_PASSPORT": "PII.US_PASSPORT",
    "US_DRIVER_LICENSE": "PII.US_DRIVER_LICENSE",
    "IBAN_CODE": "PII.IBAN",
    "IP_ADDRESS": "PII.IP_ADDRESS",
    "PERSON": "PII.PERSON",
    "LOCATION": "PII.LOCATION",
    # Presidio's DATE_TIME recognizer flags any date-shaped mention (a statement
    # date, an event date), not specifically a birthdate — mapping it to
    # PII.DATE_OF_BIRTH overclaims what was actually found (benchmarked: 1.6-21.3%
    # precision against that label in benchmarks/pii/). PII.DATE_TIME names it for
    # what it is; `detectors/pii.py`'s own regex still owns PII.DATE_OF_BIRTH.
    "DATE_TIME": "PII.DATE_TIME",
    "MEDICAL_LICENSE": "PII.MEDICAL_LICENSE",
    "UK_NHS": "PII.UK_NHS",
    "UK_NINO": "PII.UK_NINO",
    "IN_AADHAAR": "PII.IN_AADHAAR",
    "IN_PAN": "PII.IN_PAN",
    "CRYPTO": "PII.CRYPTO_WALLET",
}

#: Presidio's PERSON/LOCATION/DATE_TIME recognisers are noisy in agent traffic;
#: excluded by default and re-enabled per policy. A guardrail with poor precision
#: gets switched off (PRD R3). US_DRIVER_LICENSE and US_PASSPORT join them per
#: benchmarks/pii/README.md: both are low-specificity numeric/alphanumeric-ID
#: patterns that fire on account numbers, reference IDs, and other short codes
#: in dense documents far more often than on the real thing (3.2%/0.9%
#: precision for driver's license across two datasets; 10.7% for passport),
#: and — unlike US_SSN — neither has a confidence-score tier that cleanly
#: separates true from false positives, so a `_MIN_SCORE` threshold isn't an
#: option (checked directly; see README). US_PHONE has the identical
#: no-clean-threshold problem at comparable precision (24.2%) but is
#: deliberately *not* excluded here: phone numbers are common, high-value PII
#: in real agent traffic, and losing that recall by default would cost more
#: than the noise costs — left as a disclosed, open problem instead of a
#: blanket exclusion.
DEFAULT_EXCLUDED = {"PERSON", "LOCATION", "DATE_TIME", "US_DRIVER_LICENSE", "US_PASSPORT"}

#: Presidio's own confidence score is discrete, not continuous, and for some
#: recognisers the low tier is cleanly separable from real hits rather than a
#: gradient. Benchmarked on gretelai/synthetic_pii_finance_multilingual
#: (benchmarks/pii/README.md): US_SSN's 0.05 ("regex matched, no context words
#: nearby") tier accounts for 444 of 453 false positives — bare 9-digit codes
#: in dense financial documents (account numbers, routing numbers) — against
#: only 7 of 76 true positives at that same tier. Filtering it out trades ~9%
#: of this recogniser's recall for roughly a 6x precision gain. Not applied
#: elsewhere: US_DRIVER_LICENSE's true and false positives are scored across
#: the *same* tiers with no clean cut point (see README), so a threshold
#: there would just be arbitrary — that recogniser is excluded by default
#: instead (see DEFAULT_EXCLUDED above).
_MIN_SCORE: dict[str, float] = {"US_SSN": 0.1}


#: The spaCy model `AnalyzerEngine()` loads when given no configuration. Their
#: `NlpEngineProvider` hardcodes the same fallback, and their default conf names
#: it; it is repeated here because the check below has to ask about the exact
#: model Presidio will ask for, and any other answer is a guess.
_SPACY_MODEL = "en_core_web_lg"


@functools.lru_cache(maxsize=1)
def _analyzer():  # pragma: no cover - requires optional dependency
    from presidio_analyzer import AnalyzerEngine

    return AnalyzerEngine()


class PresidioPiiDetector(BaseDetector):
    key = "pii.presidio"
    version = "1.0"
    surfaces = ("input", "output", "tool_args", "tool_result", "retrieved")

    def __init__(self, language: str = "en", excluded: set[str] | None = None) -> None:
        self.language = language
        self.excluded = DEFAULT_EXCLUDED if excluded is None else excluded

    def available(self) -> bool:
        try:
            import presidio_analyzer  # noqa: F401
        except Exception:
            return False
        return self._model_present()

    @staticmethod
    def _model_present() -> bool:
        """Is the spaCy model there, or would asking for it reach the network?

        `available()` used to answer yes the moment `presidio_analyzer`
        imported, and `AnalyzerEngine()` is built lazily on the first real
        request. Measured on a clean install of `agentfox[pii]`:

          available(): True
          detect():    downloaded en_core_web_lg (400.7 MB) and returned in 29,791ms

        A 400MB `pip install` from inside a guarded request, against a 300ms
        pre-flight budget and a 40ms per-detector timeout, on a product whose
        first README line is that it runs offline. `allow_egress` was false
        throughout; it gates our own outbound calls and never saw this one.

        Air-gapped, the same `available(): True` is followed by every request
        raising a ProxyError against raw.githubusercontent.com — so the
        Detectors strip reported PII as covered by a check that could not run.

        `adapters/classifiers.py` already had the rule and the comment for
        exactly this: "never trigger a download at request time. Absent weights
        mean 'unavailable', not 'fetch it now'." One adapter honoured it; this
        one did not.
        """
        try:
            import spacy.util

            return _SPACY_MODEL in spacy.util.get_installed_models()
        except Exception:
            return False

    @property
    def unavailable_reason(self) -> str:
        try:
            import presidio_analyzer  # noqa: F401
        except Exception:
            return (
                "Microsoft Presidio is not installed. `pip install "
                "'agentfox[pii]'`, then download its language model with "
                f"`python -m spacy download {_SPACY_MODEL}`."
            )
        return (
            f"Microsoft Presidio is installed but its spaCy model "
            f"({_SPACY_MODEL}, ~400MB) is not. Download it ahead of time with "
            f"`python -m spacy download {_SPACY_MODEL}`. It is deliberately not "
            "fetched on demand: that would put a 400MB download inside a "
            "guarded request, and this product does not reach the network "
            "during one. `pii.native` covers the offline path meanwhile."
        )

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        # Building the engine loads the model from disk, which measured about a
        # second. `detector_timeout_ms` is tens of milliseconds, so paying it on
        # a real request degrades that request and looks like a flake.
        if self._model_present():
            _analyzer()

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        results = _analyzer().analyze(text=content, language=self.language)
        out: list[Detection] = []
        for r in results:
            if r.entity_type in self.excluded:
                continue
            if r.score < _MIN_SCORE.get(r.entity_type, 0.0):
                continue
            out.append(
                Detection(
                    entity_type=_ENTITY_MAP.get(r.entity_type, f"PII.{r.entity_type}"),
                    score=float(r.score),
                    start=r.start,
                    end=r.end,
                    sample=redact_sample(content[r.start : r.end]),
                    owasp_id="LLM02",
                    atlas_id="AML.T0057",
                    detail={"engine": "presidio", "presidio_entity": r.entity_type},
                )
            )
        return out
