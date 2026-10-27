"""A detector that errors follows `fail_mode` exactly as one that times out.

A detector that raised (or reported `status="error"`) was recorded as `errored` and
the call was allowed whatever `fail_mode` said, including a deployment and a pack
that both said `closed`: only a timeout counted as degraded, and the fail modes read
only the degraded list. An error is the same reduced coverage as a timeout (the
detector did not check the content), so it is now degraded too: `closed` blocks it
as `pipeline.fail_closed`, `open` allows it and records the gap. LLM judges already
behaved this way (#133) and still do.
"""

from __future__ import annotations

import time

import pytest

from agentfox.capabilities.detection import DetectorPipeline
from agentfox.capabilities.detection.base import BaseDetector, DetectorResult, get_detector
from agentfox.core.config import get_settings
from agentfox.platform.policy import PolicyDocument, save_policy
from agentfox.platform.registry.service import register_agent
from agentfox.runtime.enforcement import Enforcer

PACK = """
key: fm-pack
mode: enforce
fail_mode: {fail_mode}
rules:
  - id: pii.input
    when: {{surface: [input], detection: {{entity_prefix: PII}}}}
    effect: block
"""


class _Ok(BaseDetector):
    key = "fm.ok"
    version = "1"
    surfaces = ("input",)
    timeout_ms = 200

    def available(self) -> bool:
        return True

    def _detect(self, content, context):
        return []


class _Slow(_Ok):
    key = "fm.slow"
    timeout_ms = 20

    def _detect(self, content, context):
        time.sleep(0.2)
        return []


class _Raises(_Ok):
    key = "fm.boom"

    def _detect(self, content, context):
        raise RuntimeError("detector backend unavailable")


class _ReportsError(_Ok):
    """A detector that catches its own failure and says so, rather than raising."""

    key = "fm.reports"

    def detect(self, content, context):
        return DetectorResult(
            detector_key=self.key,
            version=self.version,
            status="error",
            raw={"error": "endpoint returned 500"},
        )


OUTCOMES = {
    "ok": (_Ok, None),
    "timeout": (_Slow, "timeout"),
    "raises": (_Raises, "error: detector backend unavailable"),
    "reports_error": (_ReportsError, "error: endpoint returned 500"),
}


def _decide(session, monkeypatch, detector, *, deployment: str, pack: str, persist=False):
    monkeypatch.setattr(get_settings(), "fail_mode", deployment)
    agent = register_agent(session, "fm-bot")
    save_policy(session, PolicyDocument.from_yaml(PACK.format(fail_mode=pack)), bind_mode="enforce")
    return Enforcer(session, pipeline=DetectorPipeline(detectors=[detector])).evaluate(
        agent=agent, identity=None, content="hello", surface="input", persist=persist
    )


def _fired(result) -> dict[str, dict]:
    return {r["rule_id"]: r for r in result.rules_fired}


@pytest.mark.parametrize("outcome", list(OUTCOMES))
@pytest.mark.parametrize(
    ("deployment", "pack"),
    [("open", "open"), ("open", "closed"), ("closed", "open"), ("closed", "closed")],
)
def test_fail_mode_matrix(session, monkeypatch, deployment, pack, outcome):
    detector_cls, why = OUTCOMES[outcome]
    detector = detector_cls()
    result = _decide(session, monkeypatch, detector, deployment=deployment, pack=pack)
    fired = _fired(result)

    if why is None:  # the detector ran: nothing degraded, nothing to fail closed on
        assert result.verdict == "allow"
        assert result.degraded == []
        assert "pipeline.fail_closed" not in fired
        return

    # Recorded and surfaced the same way whatever the fail mode.
    assert result.degraded == [detector.key]
    closed = "closed" in (deployment, pack)
    if closed:
        assert result.verdict == "block"
        assert result.effective_verdict == "block"
        reason = fired["pipeline.fail_closed"]["reason"]
        assert f"{detector.key}: {why}" in reason
        source = "fail_mode=closed" if deployment == "closed" else "policy fm-pack declares"
        assert source in reason
    else:
        assert result.verdict == "allow"
        assert "pipeline.fail_closed" not in fired


@pytest.mark.parametrize(
    ("deployment", "pack"),
    [("open", "open"), ("open", "closed"), ("closed", "open"), ("closed", "closed")],
)
def test_an_error_and_a_timeout_get_the_same_decision(session, monkeypatch, deployment, pack):
    timed_out = _decide(session, monkeypatch, _Slow(), deployment=deployment, pack=pack)
    errored = _decide(session, monkeypatch, _Raises(), deployment=deployment, pack=pack)
    assert errored.verdict == timed_out.verdict
    assert errored.effective_verdict == timed_out.effective_verdict
    assert sorted(_fired(errored)) == sorted(_fired(timed_out))


def test_an_observe_decision_never_fails_closed_on_an_error(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "fail_mode", "closed")
    agent = register_agent(session, "fm-bot")
    save_policy(
        session,
        PolicyDocument.from_yaml(PACK.format(fail_mode="closed").replace("enforce", "observe")),
        bind_mode="observe",
    )
    result = Enforcer(session, pipeline=DetectorPipeline(detectors=[_Raises()])).evaluate(
        agent=agent, identity=None, content="hello", surface="input", persist=False
    )
    assert result.effective_verdict == "allow"
    assert result.degraded == ["fm.boom"]


def test_a_built_in_inline_detector_that_raises_is_degraded(session, monkeypatch):
    """Built-in pattern detectors run in the request's own thread; their errors too."""
    secrets = get_detector("secrets.native")

    def boom(content, context):
        raise RuntimeError("regex engine exploded")

    monkeypatch.setattr(secrets, "detect", boom)
    result = _decide(session, monkeypatch, secrets, deployment="closed", pack="open")
    assert result.verdict == "block"
    assert result.degraded == ["secrets.native"]
    assert (
        "secrets.native: error: regex engine exploded"
        in (_fired(result)["pipeline.fail_closed"]["reason"])
    )


def test_an_error_under_fail_open_is_recorded_like_a_timeout(session, monkeypatch):
    """Allowed, and visible where a degraded timeout is: the detector run's status
    and an open `budget_breach` finding naming the detector and why."""
    from agentfox.core.models import DetectorRun, Finding

    result = _decide(session, monkeypatch, _Raises(), deployment="open", pack="open", persist=True)
    session.flush()
    assert result.verdict == "allow"
    assert result.to_json()["degraded"] == ["fm.boom"]
    runs = session.query(DetectorRun).filter_by(detector_key="fm.boom").all()
    assert [r.status for r in runs] == ["error"]
    findings = session.query(Finding).filter_by(type="budget_breach", status="open").all()
    assert [f.title for f in findings] == ["Detector 'fm.boom' degraded on input: error"]
    assert findings[0].evidence_json["degradation"] == {
        "fm.boom": "error: detector backend unavailable"
    }


# --- the survey probe, kept as a regression -------------------------------------


@pytest.mark.parametrize("pack_fail_mode", ["open", "closed"])
@pytest.mark.parametrize("deploy_fail_mode", ["open", "closed"])
def test_probe_raising_detector_follows_fail_mode(
    session, monkeypatch, deploy_fail_mode, pack_fail_mode
):
    """The probe that found this (origin/main 6a082b7): a raising detector was
    allowed in all four cells, while a slow one was blocked in the three closed ones."""

    class Boom(BaseDetector):
        key = "fm.boom"
        version = "1"
        surfaces = ("input",)

        def available(self):
            return True

        def _detect(self, content, context):
            raise RuntimeError("detector backend unavailable")

    result = _decide(session, monkeypatch, Boom(), deployment=deploy_fail_mode, pack=pack_fail_mode)
    rules = [r["rule_id"] for r in result.rules_fired]
    if "closed" in (deploy_fail_mode, pack_fail_mode):
        assert (result.verdict, rules) == ("block", ["pipeline.fail_closed"])
    else:
        assert (result.verdict, rules) == ("allow", [])
