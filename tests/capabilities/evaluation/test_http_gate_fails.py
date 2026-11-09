"""The HTTP gate can fail a build (wow3 prove B4).

``POST /api/eval/gate`` answered 200 with ``passed: false``, and the CI tab's snippet
used ``curl -s``, so no build ever failed on it. It also took ``min_pass_rate: 1.5``.
A failed gate now answers 412 with the same body; the rate must be a share."""

from __future__ import annotations

from agentfox.platform.providers import register_provider
from tests.capabilities.evaluation.test_gate_errors import _BrokenProvider
from tests.conftest import as_user

ME = as_user("priya@example.com")


def test_a_failed_gate_is_not_a_2xx(client):
    register_provider(_BrokenProvider())
    r = client.post(
        "/api/eval/gate",
        json={"suite": "support-quality", "target": {"provider": "broken-test-provider"}},
        headers=ME,
    )
    assert r.status_code == 412, r.text
    body = r.json()
    assert body["passed"] is False and body["junit"] and body["sarif"]


def test_a_passing_gate_is_200(client):
    r = client.post(
        "/api/eval/gate",
        json={"suite": "support-quality", "target": {"provider": "echo"}, "min_pass_rate": 0},
        headers=ME,
    )
    assert r.status_code == 200, r.text
    assert r.json()["passed"] is True


def test_a_pass_rate_above_one_is_refused(client):
    r = client.post(
        "/api/eval/gate", json={"suite": "support-quality", "min_pass_rate": 1.5}, headers=ME
    )
    assert r.status_code == 422
