"""Pillar 3 — Runtime Guardrails & Security.

Detector registration happens here so that importing ``agentfox.guardrails`` gives
you a working, offline-capable detector set with no optional dependency installed
(X-3). Wrapped OSS adapters register too, but report ``available() == False`` until
their dependency (and, for classifiers, their weights) are actually present.
"""

from __future__ import annotations

from .adapters.classifiers import (
    GraniteGuardianDetector,
    PromptInjectionClassifierDetector,
    RestrictedClassifierDetector,
)
from .adapters.embeddings import EmbeddingSimilarityDetector
from .adapters.presidio import PresidioPiiDetector
from .adapters.hub import CATALOGUE as HUB_CATALOGUE
from .adapters.hub import HubValidatorDetector, hub_detectors
from .adapters.rails import GuardrailsAiDetector, NemoRailsDetector
from .base import (
    SURFACES,
    TAINT_ORDER,
    BaseDetector,
    Detection,
    DetectionContext,
    Detector,
    DetectorResult,
    all_detectors,
    available_detectors,
    get_detector,
    redact_sample,
    register_detector,
    taint_rank,
    warm_all,
)
from .detectors.injection import InjectionHeuristicDetector
from .detectors.pii import NativePiiDetector, redact_content
from .detectors.safety import SafetyLexiconDetector
from .detectors.schema import JsonSchemaDetector
from .detectors.secrets import SecretsDetector
from .pipeline import DetectorPipeline, PipelineResult, fail_verdict
from .taint import TaintMark, TaintTracker, exceeds

# --- Native, always available (offline default) ---
register_detector(InjectionHeuristicDetector())
register_detector(NativePiiDetector())
register_detector(SecretsDetector())
register_detector(SafetyLexiconDetector())
register_detector(JsonSchemaDetector())

# --- Wrapped OSS, available when installed ---
register_detector(PresidioPiiDetector())
register_detector(PromptInjectionClassifierDetector())
register_detector(EmbeddingSimilarityDetector())
register_detector(GraniteGuardianDetector())
register_detector(NemoRailsDetector())
register_detector(GuardrailsAiDetector())

# --- Guardrails AI Hub, one detector per validator (adapters/hub.py) ---
# Registered even when not installed: the Detectors strip counts "not installed"
# separately from "off", so an operator can see a jailbreak classifier is one
# `pip install` away rather than having to know the catalogue exists.
for _hub_detector in hub_detectors():
    register_detector(_hub_detector)

# --- Licence-restricted, opt-in only (Appendix A.4) ---
register_detector(RestrictedClassifierDetector())

__all__ = [
    "SURFACES",
    "TAINT_ORDER",
    "BaseDetector",
    "Detection",
    "DetectionContext",
    "Detector",
    "DetectorPipeline",
    "DetectorResult",
    "EmbeddingSimilarityDetector",
    "GraniteGuardianDetector",
    "GuardrailsAiDetector",
    "InjectionHeuristicDetector",
    "JsonSchemaDetector",
    "NativePiiDetector",
    "NemoRailsDetector",
    "PipelineResult",
    "PresidioPiiDetector",
    "PromptInjectionClassifierDetector",
    "RestrictedClassifierDetector",
    "SafetyLexiconDetector",
    "SecretsDetector",
    "TaintMark",
    "TaintTracker",
    "all_detectors",
    "available_detectors",
    "exceeds",
    "fail_verdict",
    "get_detector",
    "redact_content",
    "redact_sample",
    "HUB_CATALOGUE",
    "HubValidatorDetector",
    "hub_detectors",
    "register_detector",
    "taint_rank",
    "warm_all",
]
