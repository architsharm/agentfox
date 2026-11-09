"""A degraded detector's issue says why and what fixes it.

The issue read "Detector 'injection.classifier' degraded on input: timeout" when the
detector's libraries were missing, and offered no fix. It now carries the cause and,
for a missing library or model, the command that fixes it.
"""

from __future__ import annotations

from sqlalchemy import select

from agentfox.capabilities.detection import base as detection_base
from agentfox.capabilities.detection.base import DetectorResult
from agentfox.capabilities.detection.pipeline import PipelineResult
from agentfox.core.models import Finding
from agentfox.platform.ledger.findings import record_detector_health


class _Model(detection_base.BaseDetector):
    key = "test.model_detector"
    model_id = "org/some-model"
    timeout_ms = 250

    def __init__(self, ready: bool, reason: str = "") -> None:
        self.ready = ready
        self.unavailable_reason = reason

    def available(self) -> bool:
        return self.ready

    def _detect(self, content, context):
        return []


def _degraded(status: str, **raw) -> PipelineResult:
    return PipelineResult(
        results=[
            DetectorResult(
                detector_key=_Model.key, version="1", status=status, raw=raw, duration_ms=250.0
            )
        ],
        degraded=[_Model.key],
    )


def test_a_detector_that_cannot_run_here_says_install(monkeypatch):
    detector = _Model(False, "needs `pip install 'agentfox[classifiers]'`")
    monkeypatch.setitem(detection_base._REGISTRY, detector.key, detector)

    why = _degraded("timeout").explain(detector.key)

    assert "cannot run here" in why["cause"]
    assert "pip install 'agentfox[classifiers]'" in why["fix"]


def test_a_missing_library_error_says_install(monkeypatch):
    monkeypatch.setitem(detection_base._REGISTRY, _Model.key, _Model(True))

    why = _degraded("error", error="No module named 'torch'\nTraceback ...").explain(_Model.key)

    assert why["cause"] == "it failed: No module named 'torch'"
    assert "pip install 'agentfox[classifiers]'" in why["fix"]


def test_a_real_timeout_names_the_allowance_and_a_fix(monkeypatch):
    monkeypatch.setitem(detection_base._REGISTRY, _Model.key, _Model(True))

    why = _degraded("timeout").explain(_Model.key)

    assert "250 ms" in why["cause"]
    assert "CPU" in why["fix"]


def test_the_issue_and_its_remedy_carry_cause_and_fix(session, monkeypatch):
    from agentfox.capabilities.remediation.remedies import remedies_for

    detector = _Model(False, "needs `pip install 'agentfox[classifiers]'`")
    monkeypatch.setitem(detection_base._REGISTRY, detector.key, detector)

    record_detector_health(
        session, subject_id="agent_1", surface="input", pipeline_result=_degraded("timeout")
    )
    [finding] = session.scalars(select(Finding).where(Finding.type == "budget_breach"))

    assert "cannot run here" in finding.title
    assert "pip install" in finding.evidence_json["fix"]
    [remedy] = remedies_for(session, finding)
    assert "pip install 'agentfox[classifiers]'" in remedy.hint
