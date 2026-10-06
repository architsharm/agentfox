"""Pillar 3 — Runtime Guardrails & Security.

Detector registration happens here so that importing ``agentfox.detection`` gives
you a working, offline-capable detector set with no optional dependency installed.
Wrapped OSS adapters register too, but report ``available() == False`` until
their dependency (and, for classifiers, their weights) are actually present.
"""

from __future__ import annotations

from agentfox.detection.adapters.classifiers import (
    GraniteGuardianDetector,
    PromptInjectionClassifierDetector,
    RestrictedClassifierDetector,
)
from agentfox.detection.adapters.embeddings import EmbeddingSimilarityDetector
from agentfox.detection.adapters.hub import CATALOGUE as HUB_CATALOGUE
from agentfox.detection.adapters.hub import HubValidatorDetector, hub_detectors
from agentfox.detection.adapters.presidio import PresidioPiiDetector
from agentfox.detection.adapters.rails import GuardrailsAiDetector, NemoRailsDetector
from agentfox.detection.base import (
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
    warm_all,
)
from agentfox.detection.detectors.injection import InjectionHeuristicDetector
from agentfox.detection.detectors.judgment import InjectionJudgmentDetector, PiiJudgmentDetector
from agentfox.detection.detectors.pii import NativePiiDetector, redact_content
from agentfox.detection.detectors.safety import SafetyLexiconDetector
from agentfox.detection.detectors.schema import JsonSchemaDetector
from agentfox.detection.detectors.secrets import SecretsDetector
from agentfox.detection.pipeline import DetectorPipeline, PipelineResult, fail_verdict
from agentfox.detection.taint import TaintMark, TaintTracker, exceeds

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

# --- Judgment-backed, available only when a judgment tier is enabled ---
# Unlike the adapters above, this one's availability is a *policy* question as
# well as an install question: `judgment/capability.py` decides whether a
# judgment tier may answer PATTERN_OPEN at all, and `allow_egress` decides
# whether anything may leave. See detectors/judgment.py.
register_detector(InjectionJudgmentDetector())
register_detector(PiiJudgmentDetector())

# --- Guardrails AI Hub, one detector per validator (adapters/hub.py) ---
# Registered even when not installed: the Detectors strip counts "not installed"
# separately from "off", so an operator can see a jailbreak classifier is one
# `pip install` away rather than having to know the catalogue exists.
for _hub_detector in hub_detectors():
    register_detector(_hub_detector)

# --- Licence-restricted, opt-in only ---
register_detector(RestrictedClassifierDetector())

__all__ = [
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
    "warm_all",
]
