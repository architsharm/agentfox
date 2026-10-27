"""A judge outage is applied, through the same path as any degraded detector.

"On a judge outage: deny the request" (the judgment posture's `fail_closed`) was
stored and displayed but never read. It is now one more source for the degraded
path that `fail_mode` already governs:

* A judge that was asked and did not answer (unreachable, an error) is degraded,
  exactly like a judge that timed out, so the deployment's and the packs'
  `fail_mode` treat the two the same.
* The posture's `fail_closed` adds a block on top, for judges only, and only when
  an enforcing rule on this surface relies on what the silent judge finds
  (`pipeline.judge_outage`). It can never loosen a `fail_mode` that says closed.
* A payload the egress gate refused to send (`pii_egress=block` on text with an
  email address in it) is not an outage: the judge is healthy and was never asked.
"""

from __future__ import annotations

import time

import pytest

from agentfox.capabilities.detection import DetectorPipeline
from agentfox.capabilities.detection.base import BaseDetector, DetectionContext
from agentfox.capabilities.detection.custom import (
    CustomRuleSpec,
    CustomValidatorDetector,
    compile_rule,
)
from agentfox.capabilities.detection.detectors.judgment import (
    InjectionJudgmentDetector,
    PiiJudgmentDetector,
)
from agentfox.capabilities.detection.validators import get_validator
from agentfox.capabilities.detection.validators.detector import ValidatorDetector
from agentfox.capabilities.judgment import JevAnswer, JevClient, JevResult, JudgmentGateway, panel
from agentfox.capabilities.judgment import posture as judgment_posture
from agentfox.capabilities.judgment.capability import DecisionKind, Tier
from agentfox.capabilities.judgment.egress import EgressRefused
from agentfox.capabilities.judgment.jev import JevUnavailable
from agentfox.capabilities.judgment.posture import Posture
from agentfox.core.config import get_settings
from agentfox.platform.policy import PolicyDocument, save_policy
from agentfox.platform.registry.service import register_agent
from agentfox.runtime.enforcement import Enforcer

INJECTION_PACK = """
key: judged-pack
mode: {mode}
fail_mode: {fail_mode}
rules:
  - id: injection.input
    when: {{surface: [input], detection: {{entity_prefix: INJECTION, min_score: 0.7}}}}
    effect: block
"""

PII_PACK = """
key: pii-pack
mode: enforce
rules:
  - id: pii.unlocated
    when: {{surface: [input], detection: {{entity: PII.PRESENT_UNLOCATED}}}}
    effect: block
"""

#: An enforcing pack whose only detection rule is about something no judge finds.
SECRETS_PACK = """
key: secrets-pack
mode: enforce
rules:
  - id: secrets.input
    when: {{surface: [input], detection: {{entity_prefix: SECRET}}}}
    effect: block
"""

#: An enforcing pack with no detection rule at all.
NO_DETECTION_PACK = """
key: tools-pack
mode: enforce
rules:
  - id: tools.shell
    when: {{tool: "shell.*"}}
    effect: block
"""

ORDER = "Hi, my email is jane@example.com - where is my order?"

#: The JEV tier on (the router reads the posture's tiers), and the outage choice.
STRICT = Posture(tiers=frozenset({Tier.JEV}), fail_closed=True)
LAX = Posture(tiers=frozenset({Tier.JEV}), fail_closed=False)


class _Client(JevClient):
    """A healthy judge: answers every question, no network."""

    def __init__(self) -> None:
        super().__init__(api_key="test")
        self.asked = 0

    def ask(self, state, questions):  # type: ignore[override]
        self.asked += 1
        return JevResult(answers={q: JevAnswer(q, "noul", 0.01, 1.0) for q in questions})


class _Down(JudgmentGateway):
    """A judge tier that is down: every ask fails, as a 503 would."""

    def __init__(self) -> None:
        super().__init__(JevClient(api_key="test"), backend="remote")

    def ask(self, state, questions):  # type: ignore[override]
        raise JevUnavailable("HTTP 503: upstream unavailable")


class _Slow(JudgmentGateway):
    """A judge tier that does not answer in time."""

    def __init__(self) -> None:
        super().__init__(JevClient(api_key="test"), backend="remote")

    def ask(self, state, questions):  # type: ignore[override]
        time.sleep(0.3)
        return JevResult()


class _SlowInjectionJudge(InjectionJudgmentDetector):
    timeout_ms = 20


class _SlowSecrets(BaseDetector):
    """A detector that is not a judge, timing out."""

    key = "secrets.slow"
    version = "1"
    surfaces = ("input",)
    timeout_ms = 20

    def available(self) -> bool:
        return True

    def _detect(self, content, context):
        time.sleep(0.3)
        return []


@pytest.fixture
def judgment_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "judgment_tiers", ["deterministic", "jev"])
    monkeypatch.setattr(s, "allow_egress", True)


def _decide(
    session,
    detector,
    *,
    posture: Posture,
    pack: str = INJECTION_PACK,
    mode: str = "enforce",
    fail_mode: str = "open",
    content: str = "hello",
):
    agent = register_agent(session, "judged-bot")
    doc = PolicyDocument.from_yaml(pack.format(mode=mode, fail_mode=fail_mode))
    save_policy(session, doc, bind_mode=doc.mode)
    with judgment_posture.use(posture):
        return Enforcer(session, pipeline=DetectorPipeline(detectors=[detector])).evaluate(
            agent=agent, identity=None, content=content, surface="input", persist=False
        )


def _fired(result) -> dict[str, dict]:
    return {r["rule_id"]: r for r in result.rules_fired}


# --- the posture applies, scoped to rules that rely on the judge -------------


def test_an_outage_blocks_when_the_posture_denies_and_a_rule_relies_on_the_judge(
    session, judgment_on
):
    result = _decide(session, InjectionJudgmentDetector(_Down()), posture=STRICT)
    assert result.verdict == "block"
    fired = _fired(result)["pipeline.judge_outage"]
    assert "injection.judgment" in fired["reason"]
    assert "judged-pack (injection.input)" in fired["reason"]
    assert fired["evidence"]["judges"]["injection.judgment"] == [
        "INJECTION.INSTRUCTION_IN_DATA",
        "INJECTION.EXFILTRATION",
    ]


def test_an_outage_is_a_degraded_detector_when_the_posture_allows_it(session, judgment_on):
    result = _decide(session, InjectionJudgmentDetector(_Down()), posture=LAX)
    assert result.verdict == "allow"
    assert "injection.judgment" in result.degraded
    assert "pipeline.judge_outage" not in _fired(result)


@pytest.mark.parametrize("pack", [SECRETS_PACK, NO_DETECTION_PACK], ids=["other-rule", "no-rule"])
def test_an_outage_does_not_block_where_no_rule_relies_on_the_judge(session, judgment_on, pack):
    result = _decide(session, InjectionJudgmentDetector(_Down()), posture=STRICT, pack=pack)
    assert result.verdict == "allow"
    assert "pipeline.judge_outage" not in _fired(result)


def test_watching_never_blocks_on_a_judge_outage(session, judgment_on):
    result = _decide(session, InjectionJudgmentDetector(_Down()), posture=STRICT, mode="observe")
    assert result.verdict == "allow"
    assert "pipeline.judge_outage" not in _fired(result)


# --- an egress refusal is a choice, not an outage ----------------------------


@pytest.mark.parametrize("pack", [PII_PACK, NO_DETECTION_PACK], ids=["pii-rule", "no-rule"])
def test_a_refused_payload_with_a_healthy_judge_is_not_an_outage(
    session, judgment_on, monkeypatch, pack
):
    """The audit's reproduction: `pii_egress=block`, a customer's email in the text,
    the judge healthy. The payload is not sent, which is the policy working, and
    neither the posture nor a closed deployment treats it as an outage."""
    monkeypatch.setattr(get_settings(), "fail_mode", "closed")
    # Recorded checks run a judge no enforcing rule relies on after the response;
    # this is about the refusal itself, so the judge runs inline either way.
    monkeypatch.setattr(get_settings(), "judgment_inline", "always")
    client = _Client()
    gateway = JudgmentGateway(client, backend="remote", pii_egress="block")
    seen = []

    class _Recording(PiiJudgmentDetector):
        def detect(self, content, context):
            seen.append(super().detect(content, context))
            return seen[-1]

    result = _decide(session, _Recording(gateway), posture=STRICT, pack=pack, content=ORDER)
    assert [(r.status, r.raw["cause"]) for r in seen] == [("unavailable", "refused")]
    assert result.verdict == "allow"
    assert "pipeline.judge_outage" not in _fired(result)
    assert "pipeline.fail_closed" not in _fired(result)
    assert "pii.judgment" not in result.degraded
    assert client.asked == 0  # never sent


def test_a_refusal_reports_its_cause(judgment_on):
    result = PiiJudgmentDetector(
        JudgmentGateway(_Client(), backend="remote", pii_egress="block")
    ).detect(ORDER, DetectionContext(surface="input"))
    assert result.status == "unavailable"
    assert result.raw["cause"] == "refused"

    down = InjectionJudgmentDetector(_Down()).detect("hello", DetectionContext(surface="input"))
    assert down.status == "unavailable"
    assert down.raw["cause"] == "outage"


def test_every_tier_refusing_is_a_refusal_and_any_tier_down_is_an_outage():
    class _Refuses:
        def ask(self, state, questions):
            raise EgressRefused("pii_egress is block")

    class _Fails:
        def ask(self, state, questions):
            raise JevUnavailable("timed out")

    q = {"x": {"type": "noul"}}
    with pytest.raises(JevUnavailable) as refused:
        panel.ask(DecisionKind.PATTERN_OPEN, {}, q, panel=[(Tier.JEV, _Refuses())])
    assert refused.value.cause == "refused"
    with pytest.raises(JevUnavailable) as mixed:
        panel.ask(
            DecisionKind.PATTERN_OPEN,
            {},
            q,
            panel=[(Tier.JEV, _Refuses()), (Tier.LOCAL_LLM, _Fails())],
        )
    assert mixed.value.cause == "outage"


# --- a timeout and an "unavailable" are the same outage ----------------------


@pytest.mark.parametrize(
    "detector",
    [
        pytest.param(lambda: InjectionJudgmentDetector(_Down()), id="unavailable"),
        pytest.param(lambda: _SlowInjectionJudge(_Slow()), id="timeout"),
    ],
)
@pytest.mark.parametrize(
    ("posture", "fail_mode", "verdict"),
    [
        (LAX, "open", "allow"),
        (STRICT, "open", "block"),
        (LAX, "closed", "block"),
    ],
)
def test_a_timeout_and_an_unanswered_judge_get_the_same_verdict(
    session, judgment_on, detector, posture, fail_mode, verdict
):
    result = _decide(session, detector(), posture=posture, fail_mode=fail_mode)
    assert result.verdict == verdict
    assert "injection.judgment" in result.degraded


# --- fail_mode still governs, and posture cannot loosen it -------------------


def test_a_closed_deployment_blocks_a_judge_outage_even_when_the_posture_allows(
    session, judgment_on, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fail_mode", "closed")
    result = _decide(session, InjectionJudgmentDetector(_Down()), posture=LAX)
    assert result.verdict == "block"
    assert "injection.judgment" in _fired(result)["pipeline.fail_closed"]["reason"]


def test_a_closed_deployment_still_blocks_a_degraded_non_judge_detector(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "fail_mode", "closed")
    result = _decide(session, _SlowSecrets(), posture=LAX, pack=SECRETS_PACK)
    assert result.verdict == "block"
    fired = _fired(result)
    assert "secrets.slow" in fired["pipeline.fail_closed"]["reason"]
    assert "pipeline.judge_outage" not in fired


def test_the_posture_does_not_apply_to_a_detector_that_is_not_a_judge(session):
    """Non-judge detectors keep main's behaviour: open by default."""
    result = _decide(session, _SlowSecrets(), posture=STRICT, pack=SECRETS_PACK)
    assert result.verdict == "allow"
    assert "secrets.slow" in result.degraded


# --- validator judges report the same way ------------------------------------


def _politeness() -> ValidatorDetector:
    return ValidatorDetector(get_validator("politeness_check"))


def test_a_judge_validator_reports_an_outage_and_a_refusal_apart(monkeypatch):
    det = _politeness()
    ctx = DetectionContext(surface="output")

    monkeypatch.setattr(panel, "ask", _raises(JevUnavailable("HTTP 503")))
    down = det.detect("you are an idiot", ctx)
    assert (down.status, down.raw["cause"]) == ("unavailable", "outage")
    assert down.raw["entities"] == ["QUALITY.IMPOLITE"]

    monkeypatch.setattr(panel, "ask", _raises(EgressRefused("pii_egress is block")))
    refused = det.detect("you are an idiot", ctx)
    assert (refused.status, refused.raw["cause"]) == ("unavailable", "refused")


def test_a_judge_validator_outage_reaches_the_pipeline(monkeypatch):
    det = _politeness()
    monkeypatch.setattr(det, "available", lambda: True)
    monkeypatch.setattr(panel, "ask", _raises(JevUnavailable("HTTP 503")))
    result = DetectorPipeline(detectors=[det]).run("rude", DetectionContext(surface="output"))
    assert result.judge_outage == {"validator.politeness_check": ["QUALITY.IMPOLITE"]}
    assert "validator.politeness_check" in result.degraded

    monkeypatch.setattr(panel, "ask", _raises(EgressRefused("refused")))
    result = DetectorPipeline(detectors=[det]).run("rude", DetectionContext(surface="output"))
    assert result.judge_outage == {}
    assert result.degraded == []


def test_a_workspace_judge_rule_down_leaves_the_other_rules_standing(monkeypatch):
    monkeypatch.setattr(panel, "ask", _raises(JevUnavailable("HTTP 503")))
    monkeypatch.setattr(get_validator("politeness_check"), "available", lambda: True)
    nice = compile_rule(
        CustomRuleSpec(
            key="be-nice", name="Be nice", kind="validator", validator={"name": "politeness_check"}
        )
    )
    as_json = compile_rule(
        CustomRuleSpec(
            key="as-json", name="As JSON", kind="validator", validator={"name": "valid_json"}
        )
    )
    ctx = DetectionContext(surface="output", extra={"custom_rules": [nice, as_json]})
    result = CustomValidatorDetector().detect("not json at all", ctx)
    assert [d.entity_type for d in result.detections] == ["CUSTOM.AS_JSON"]
    assert result.status == "unavailable"
    assert result.raw["cause"] == "outage"
    assert result.raw["entities"] == ["CUSTOM.BE_NICE"]
    assert result.raw["rules"] == {"be-nice": "outage"}


def _raises(exc: Exception):
    def ask(*_args, **_kwargs):
        raise exc

    return ask


def test_a_judge_no_enforcing_rule_relies_on_runs_after_the_response(session, judgment_on):
    """`judgment_inline = "when_relied"`: when no enforcing rule here could act on the
    judge's findings, a recorded check does not wait for it (about a second in
    production). The judge still runs, after the response, and its run is recorded
    the same way an inline one is."""
    from agentfox.core.models import DetectorRun

    assert get_settings().judgment_inline == "when_relied"
    agent = register_agent(session, "judged-bot")
    doc = PolicyDocument.from_yaml(NO_DETECTION_PACK.format())
    save_policy(session, doc, bind_mode=doc.mode)
    session.commit()
    detector = InjectionJudgmentDetector(_Slow())
    started = time.perf_counter()
    with judgment_posture.use(LAX):
        result = Enforcer(session, pipeline=DetectorPipeline(detectors=[detector])).evaluate(
            agent=agent, identity=None, content="hello", surface="input"
        )
    session.commit()
    assert time.perf_counter() - started < 0.25  # the judge sleeps 0.3 s
    assert "injection.judgment" not in result.degraded
    deadline = time.time() + 5
    while time.time() < deadline:
        session.expire_all()
        if session.query(DetectorRun).filter_by(detector_key="injection.judgment").count():
            break
        time.sleep(0.05)
    assert session.query(DetectorRun).filter_by(detector_key="injection.judgment").count() == 1


def test_a_judge_an_enforcing_rule_relies_on_stays_inline(session, judgment_on):
    """A recorded check whose enforcing rule could act on the judge waits for it: the
    judge's outage is seen, and blocks, on this very check."""
    agent = register_agent(session, "judged-bot")
    doc = PolicyDocument.from_yaml(INJECTION_PACK.format(mode="enforce", fail_mode="open"))
    save_policy(session, doc, bind_mode=doc.mode)
    session.commit()
    detector = InjectionJudgmentDetector(_Down())
    with judgment_posture.use(STRICT):
        result = Enforcer(session, pipeline=DetectorPipeline(detectors=[detector])).evaluate(
            agent=agent, identity=None, content="hello", surface="input"
        )
    assert result.verdict == "block"
    assert "pipeline.judge_outage" in _fired(result)
