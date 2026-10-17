"""Detector cut-offs are configuration, not constants.

A threshold that only a code edit can change is one the improvement loop can never tune and an
operator can never adjust for their own traffic. The shipped defaults must not move.
"""

from __future__ import annotations

from agentfox.capabilities.detection.adapters.classifiers import PromptInjectionClassifierDetector
from agentfox.capabilities.detection.adapters.embeddings import EmbeddingSimilarityDetector
from agentfox.core.config import reset_settings_cache


def test_shipped_defaults_are_unchanged():
    reset_settings_cache()
    similarity = EmbeddingSimilarityDetector()
    assert similarity.attack_threshold == 0.6
    assert similarity.benign_margin == 0.05
    assert PromptInjectionClassifierDetector().secondary_threshold == 0.92


def test_configured_cut_offs_take_effect(monkeypatch):
    monkeypatch.setenv("AGENTFOX_EMBEDDING_SIMILARITY_ATTACK_THRESHOLD", "0.72")
    monkeypatch.setenv("AGENTFOX_EMBEDDING_SIMILARITY_BENIGN_MARGIN", "0.1")
    monkeypatch.setenv("AGENTFOX_PROMPT_INJECTION_CLASSIFIER_SECONDARY_THRESHOLD", "0.95")
    reset_settings_cache()
    try:
        similarity = EmbeddingSimilarityDetector()
        assert similarity.attack_threshold == 0.72
        assert similarity.benign_margin == 0.1
        assert PromptInjectionClassifierDetector().secondary_threshold == 0.95
    finally:
        reset_settings_cache()


def test_explicit_arguments_still_win_over_configuration(monkeypatch):
    monkeypatch.setenv("AGENTFOX_EMBEDDING_SIMILARITY_ATTACK_THRESHOLD", "0.72")
    reset_settings_cache()
    try:
        assert EmbeddingSimilarityDetector(attack_threshold=0.5).attack_threshold == 0.5
    finally:
        reset_settings_cache()
