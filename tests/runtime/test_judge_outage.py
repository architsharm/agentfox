"""A judge outage is applied, not just shown.

"On a judge outage: deny the request" (the judgment posture's `fail_closed`) was
stored and displayed but never read: a judge check that got no answer reported
`unavailable`, which the pipeline counted as neither degraded nor errored, so the
request went through. It now blocks, but only when a judge tier is actually switched
on (with none, every judge check reports unavailable by design) and only enforcing.
"""

from __future__ import annotations

from agentfox.capabilities.detection import DetectorPipeline
from agentfox.capabilities.judgment import posture as judgment_posture
from agentfox.capabilities.judgment.capability import Tier
from agentfox.capabilities.judgment.posture import Posture
from agentfox.platform.policy import PolicyDocument, save_policy
from agentfox.platform.registry.service import register_agent
from agentfox.runtime.enforcement import Enforcer

PACK = """
key: judged-pack
mode: {mode}
rules:
  - id: injection.input
    when: {{surface: [input], detection: {{entity_prefix: INJECTION, min_score: 0.7}}}}
    effect: block
"""


class _JudgeDown(DetectorPipeline):
    """Every run asks a judge that does not answer."""

    def run(self, content, context, budget_ms=None):
        result = super().run(content, context, budget_ms=budget_ms)
        result.judge_unavailable.append("injection.judgment")
        return result


def _decide(session, *, posture: Posture, mode: str = "enforce"):
    agent = register_agent(session, "judged-bot")
    save_policy(session, PolicyDocument.from_yaml(PACK.format(mode=mode)), bind_mode=mode)
    with judgment_posture.use(posture):
        return Enforcer(session, pipeline=_JudgeDown()).evaluate(
            agent=agent, identity=None, content="hello", surface="input", persist=False
        )


def test_a_judge_outage_blocks_when_the_posture_denies_on_outage(session):
    result = _decide(session, posture=Posture(tiers=frozenset({Tier.LOCAL_LLM}), fail_closed=True))
    assert result.verdict == "block"
    fired = {r["rule_id"]: r for r in result.rules_fired}
    assert "injection.judgment" in fired["pipeline.judge_outage"]["reason"]


def test_a_judge_outage_is_let_through_when_the_posture_allows_it(session):
    result = _decide(session, posture=Posture(tiers=frozenset({Tier.LOCAL_LLM}), fail_closed=False))
    assert result.verdict == "allow"


def test_no_judge_switched_on_is_not_an_outage(session):
    """With only the deterministic tier, judge checks are unavailable by design."""
    result = _decide(session, posture=Posture(fail_closed=True))
    assert result.verdict == "allow"


def test_watching_never_blocks_on_a_judge_outage(session):
    result = _decide(
        session,
        posture=Posture(tiers=frozenset({Tier.LOCAL_LLM}), fail_closed=True),
        mode="observe",
    )
    assert result.verdict == "allow"
