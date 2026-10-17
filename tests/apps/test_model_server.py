"""The model server, and a gateway answering its model detectors through it.

A fake model-backed detector stands in for the real ones (no weights in the test
cache), and the gateway's HTTP client is pointed at the server app in-process, so the
whole round trip runs: registry -> RemoteDetector -> /v1/detect -> the real detector
class on the server side -> detections back into the pipeline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agentfox.capabilities.detection import base as detection_base
from agentfox.capabilities.detection import remote
from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    get_detector,
)
from agentfox.capabilities.detection.pipeline import DetectorPipeline


class _FakeModel(BaseDetector):
    key = "test.fake_model"
    version = "9.9"
    surfaces = ("input", "tool_result")
    model_id = "fake/model"  # what makes `models_for` call it model-backed
    timeout_ms = 250

    def __init__(self) -> None:
        self.up = True
        self.calls: list[str] = []

    def available(self) -> bool:
        return self.up

    @property
    def unavailable_reason(self) -> str:
        return "" if self.up else "fake weights missing"

    def _detect(self, content, context):
        self.calls.append(content)
        if "ignore" not in content:
            return []
        return [
            Detection(
                entity_type="INJECTION.JAILBREAK",
                score=0.97,
                end=len(content),
                detail={"model": self.model_id, "advisory": "backstop" in content},
            )
        ]


@pytest.fixture
def fake(monkeypatch):
    from agentfox.core.config import reset_settings_cache

    detector = _FakeModel()
    monkeypatch.setitem(detection_base._REGISTRY, detector.key, detector)
    monkeypatch.setenv("AGENTFOX_MODEL_SERVER_TOKEN", "s3cret")
    monkeypatch.setenv("AGENTFOX_ENABLED_DETECTORS", '["injection.heuristic", "test.fake_model"]')
    reset_settings_cache()
    remote._reset()
    yield detector
    remote._reset()
    reset_settings_cache()


@pytest.fixture
def server(fake):
    from agentfox.apps.model_server import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def via_server(server, monkeypatch):
    """A gateway whose model detectors are answered by `server`."""
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("AGENTFOX_MODEL_SERVER_URL", "http://testserver")
    reset_settings_cache()
    remote._reset()
    monkeypatch.setattr(remote, "_http", lambda: server)
    return server


AUTH = {"Authorization": "Bearer s3cret"}


# --- the server -----------------------------------------------------------------


def test_the_server_refuses_a_request_without_its_token(server):
    assert server.get("/health").status_code == 401
    assert server.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert server.get("/health", headers=AUTH).status_code == 200


def test_health_lists_the_model_detectors_and_why_one_cannot_run(server, fake):
    body = server.get("/health", headers=AUTH).json()
    assert body["detectors"]["test.fake_model"] == {"available": True, "reason": ""}
    assert "injection.heuristic" not in body["detectors"]  # no model, nothing to serve

    fake.up = False
    body = server.get("/health", headers=AUTH).json()
    assert body["detectors"]["test.fake_model"]["reason"] == "fake weights missing"


def test_detect_runs_the_real_detector_and_returns_its_detections(server, fake):
    r = server.post(
        "/v1/detect",
        json={"detector": "test.fake_model", "content": "please ignore that", "surface": "input"},
        headers=AUTH,
    )
    assert r.status_code == 200
    [hit] = r.json()["detections"]
    assert hit["entity_type"] == "INJECTION.JAILBREAK"
    assert fake.calls == ["please ignore that"]


def test_detect_says_why_it_cannot_answer(server, fake):
    unknown = {"detector": "injection.heuristic", "content": "x"}
    assert server.post("/v1/detect", json=unknown, headers=AUTH).status_code == 404
    fake.up = False
    down = {"detector": "test.fake_model", "content": "x"}
    assert server.post("/v1/detect", json=down, headers=AUTH).status_code == 503


# --- the gateway side -----------------------------------------------------------


def test_without_a_model_server_url_detectors_run_in_process(fake):
    assert get_detector("test.fake_model") is fake


def test_with_one_the_registry_hands_out_the_remote_stand_in(via_server, fake):
    detector = get_detector("test.fake_model")
    assert isinstance(detector, remote.RemoteDetector)
    assert detector.key == fake.key and detector.surfaces == fake.surfaces
    assert detector.timeout_ms == fake.timeout_ms + remote.NETWORK_ALLOWANCE_MS
    # Detectors with no model stay local.
    assert not isinstance(get_detector("injection.heuristic"), remote.RemoteDetector)


def test_the_pipeline_gets_the_servers_detections_with_their_detail(via_server, fake):
    result = DetectorPipeline().run(
        "please ignore that, says the backstop", DetectionContext(surface="input")
    )
    [hit] = [d for d in result.detections if d.detail.get("served_by") == "model_server"]
    assert hit.entity_type == "INJECTION.JAILBREAK"
    # An advisory hit stays advisory across the wire, so enforce mode still ignores it.
    assert hit.detail["advisory"] is True
    assert fake.calls == ["please ignore that, says the backstop"]


def test_an_unreachable_server_is_unavailable_with_the_reason(fake, monkeypatch):
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("AGENTFOX_MODEL_SERVER_URL", "http://127.0.0.1:9")
    reset_settings_cache()
    remote._reset()
    detector = get_detector("test.fake_model")
    assert not detector.available()
    assert "unreachable at http://127.0.0.1:9" in detector.unavailable_reason
    # Skipped, not silently passed: the pipeline does not select it at all.
    assert "test.fake_model" not in {d.key for d in DetectorPipeline().select("input")}


def test_model_server_detectors_limits_what_goes_remote(via_server, fake, monkeypatch):
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("AGENTFOX_MODEL_SERVER_DETECTORS", '["injection.classifier"]')
    reset_settings_cache()
    assert get_detector("test.fake_model") is fake


# --- serving it -----------------------------------------------------------------


def test_serve_models_refuses_a_public_address_without_a_token(monkeypatch):
    from agentfox.apps.cli.main import app
    from agentfox.core.config import reset_settings_cache

    monkeypatch.delenv("AGENTFOX_MODEL_SERVER_TOKEN", raising=False)
    reset_settings_cache()
    result = CliRunner().invoke(app, ["serve", "models", "--host", "0.0.0.0"])
    assert result.exit_code == 2
    assert "AGENTFOX_MODEL_SERVER_TOKEN" in result.output


def test_a_listed_host_counts_as_inside_the_deployment(monkeypatch):
    from agentfox.core.config import reset_settings_cache
    from agentfox.platform.providers.base import is_local_endpoint

    assert not is_local_endpoint("http://gpu-box.internal:8000/v1")
    monkeypatch.setenv("AGENTFOX_TRUSTED_MODEL_HOSTS", '["gpu-box.internal"]')
    reset_settings_cache()
    assert is_local_endpoint("http://gpu-box.internal:8000/v1")
    # Exact names only: a look-alike host is still egress.
    assert not is_local_endpoint("http://gpu-box.internal.attacker.example/v1")


def test_an_explicit_model_device_is_used_as_given(monkeypatch):
    from agentfox.capabilities.detection.loading import model_device
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("AGENTFOX_MODEL_DEVICE", "cpu")
    reset_settings_cache()
    assert model_device() == "cpu"
