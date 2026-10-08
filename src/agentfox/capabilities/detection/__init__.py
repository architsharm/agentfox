"""Pillar 3 — Runtime Guardrails & Security.

Detector registration happens here so that importing ``agentfox.capabilities.detection`` gives
you a working, offline-capable detector set with no optional dependency installed.
Wrapped OSS adapters register too, but report ``available() == False`` until
their dependency (and, for classifiers, their weights) are actually present.
"""

from __future__ import annotations

from agentfox.capabilities.detection.adapters.classifiers import (
    GraniteGuardianDetector,
    PromptInjectionClassifierDetector,
    RestrictedClassifierDetector,
)
from agentfox.capabilities.detection.adapters.embeddings import EmbeddingSimilarityDetector
from agentfox.capabilities.detection.adapters.grounding import GroundingNliDetector
from agentfox.capabilities.detection.adapters.hub import CATALOGUE as HUB_CATALOGUE
from agentfox.capabilities.detection.adapters.hub import HubValidatorDetector, hub_detectors
from agentfox.capabilities.detection.adapters.presidio import PresidioPiiDetector
from agentfox.capabilities.detection.adapters.rails import GuardrailsAiDetector, NemoRailsDetector
from agentfox.capabilities.detection.base import (
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
from agentfox.capabilities.detection.custom import CustomListDetector, CustomTopicDetector
from agentfox.capabilities.detection.detectors.code import InsecureCodeDetector
from agentfox.capabilities.detection.detectors.injection import InjectionHeuristicDetector
from agentfox.capabilities.detection.detectors.judgment import (
    InjectionJudgmentDetector,
    PiiJudgmentDetector,
)
from agentfox.capabilities.detection.detectors.pii import NativePiiDetector, redact_content
from agentfox.capabilities.detection.detectors.safety import SafetyLexiconDetector
from agentfox.capabilities.detection.detectors.schema import JsonSchemaDetector
from agentfox.capabilities.detection.detectors.secrets import SecretsDetector
from agentfox.capabilities.detection.pipeline import DetectorPipeline, PipelineResult, fail_verdict
from agentfox.capabilities.detection.taint import TaintMark, TaintTracker, exceeds

# --- Native, always available (offline default) ---
register_detector(InjectionHeuristicDetector())
register_detector(NativePiiDetector())
register_detector(SecretsDetector())
register_detector(SafetyLexiconDetector())
register_detector(JsonSchemaDetector())
# A workspace's own words, patterns and topics (custom.py); free with none defined.
register_detector(CustomListDetector())
# Insecure code in what a coding agent writes or runs (detectors/code.py).
register_detector(InsecureCodeDetector())

# --- Wrapped OSS, available when installed ---
register_detector(PresidioPiiDetector())
register_detector(PromptInjectionClassifierDetector())
register_detector(EmbeddingSimilarityDetector())
register_detector(GraniteGuardianDetector())
register_detector(GroundingNliDetector())
register_detector(CustomTopicDetector())
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
