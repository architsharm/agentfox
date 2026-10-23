"""Detectors run on worker threads, and must see the request's context there.

A workspace's judgment posture (which judge tiers it switched on, whether personal
data may be sent to a judge) and its tenant are context variables set for the
request. A worker thread started from a pool does not inherit them, so before this a
detector fell back to the deployment's settings and the default org: a workspace's
own `pii_egress=block` was ignored and its judge tiers looked "not configured".
"""

from __future__ import annotations

from agentfox.capabilities.detection.base import DetectionContext, DetectorResult
from agentfox.capabilities.detection.pipeline import DetectorPipeline
from agentfox.capabilities.judgment import posture as judgment_posture
from agentfox.capabilities.judgment.egress import PiiEgress
from agentfox.core import tenancy


class _Seen:
    """Records, from inside the detector, what context it ran with."""

    def __init__(self, key: str = "probe.context", heavy: bool = False) -> None:
        self.key, self.version, self.surfaces = key, "1", ("input",)
        self.timeout_ms = None
        if heavy:  # routed to the pipeline's heavy pool
            self.requires_budget_ms = 10
        self.seen: dict[str, object] = {}

    def available(self) -> bool:
        return True

    def detect(self, content: str, context: DetectionContext) -> DetectorResult:
        self.seen = {
            "pii_egress": judgment_posture.effective().pii_egress,
            "org": tenancy.bound_org(),
        }
        return DetectorResult(detector_key=self.key, version=self.version)


def _workspace_posture() -> judgment_posture.Posture:
    default = judgment_posture.from_settings()
    assert default.pii_egress != PiiEgress.BLOCK  # so the test can tell them apart
    return judgment_posture.Posture(
        tiers=default.tiers,
        pii_egress=PiiEgress.BLOCK,
        fail_closed=default.fail_closed,
        backend=default.backend,
    )


def test_a_detector_sees_the_requests_posture_and_tenant():
    light, heavy = _Seen("probe.light"), _Seen("probe.heavy", heavy=True)
    pipeline = DetectorPipeline(detectors=[light, heavy], budget_ms=2000)
    with tenancy.tenant("org_workspace_a"), judgment_posture.use(_workspace_posture()):
        pipeline.run("hello", DetectionContext(surface="input"))
    for d in (light, heavy):
        assert d.seen == {"pii_egress": PiiEgress.BLOCK, "org": "org_workspace_a"}, d.key


def test_one_requests_context_never_leaks_into_the_next():
    """Pool threads are reused: a later request without a posture must see the
    deployment's own settings, not the previous request's."""
    probe = _Seen()
    pipeline = DetectorPipeline(detectors=[probe], budget_ms=2000, max_workers=1)
    with tenancy.tenant("org_workspace_a"), judgment_posture.use(_workspace_posture()):
        pipeline.run("first", DetectionContext(surface="input"))
    pipeline.run("second", DetectionContext(surface="input"))
    assert probe.seen == {
        "pii_egress": judgment_posture.from_settings().pii_egress,
        "org": None,
    }


def test_each_custom_model_call_sees_the_requests_posture_and_tenant(monkeypatch):
    """Several workspace models are called side by side on their own pool."""
    from types import SimpleNamespace

    from agentfox.capabilities.detection import custom_models

    seen: list[tuple[object, object]] = []

    def call_model(model, content, surface):
        seen.append((judgment_posture.effective().pii_egress, tenancy.bound_org()))
        raise custom_models.ModelUnavailable("not called in this test")

    monkeypatch.setattr(custom_models, "call_model", call_model)
    models = [SimpleNamespace(key=f"m{i}", surfaces=("input",), fail_mode="open") for i in range(3)]
    context = DetectionContext(surface="input", extra={"custom_models": models})
    with tenancy.tenant("org_workspace_a"), judgment_posture.use(_workspace_posture()):
        custom_models.CustomModelDetector().detect("hello", context)
    assert seen == [(PiiEgress.BLOCK, "org_workspace_a")] * 3
