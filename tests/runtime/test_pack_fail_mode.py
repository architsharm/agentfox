"""#42 — a pack's own `fail_mode` is read.

Only the deployment-wide `fail_mode` was consulted when detectors degraded; a
pack declaring `fail_mode: closed` (as tool-containment and the EU pack ship)
had no effect, though the schema documents it as per-policy.
"""

from __future__ import annotations

from agentfox.detection import DetectorPipeline
from agentfox.platform.policy import PolicyDocument, save_policy
from agentfox.registry.service import register_agent
from agentfox.runtime.enforcement import Enforcer

PACK = """
key: closed-pack
mode: {mode}
fail_mode: {fail_mode}
rules:
  - id: pii.input
    when: {{surface: [input], detection: {{entity_prefix: PII}}}}
    effect: redact
"""


class _Degraded(DetectorPipeline):
    """Every run reports a detector that did not finish."""

    def run(self, content, context, budget_ms=None):
        result = super().run(content, context, budget_ms=budget_ms)
        result.degraded.append("pii.slow")
        return result


def _decide(session, *, mode="enforce", fail_mode="closed", surface="input"):
    agent = register_agent(session, "fm-bot")
    save_policy(
        session,
        PolicyDocument.from_yaml(PACK.format(mode=mode, fail_mode=fail_mode)),
        bind_mode=mode,
    )
    return Enforcer(session, pipeline=_Degraded()).evaluate(
        agent=agent, identity=None, content="hello", surface=surface, persist=False
    )


def test_an_enforcing_fail_closed_pack_blocks_a_degraded_call(session):
    result = _decide(session)  # deployment fail_mode is the default, open
    assert result.verdict == "block"
    fired = {r["rule_id"]: r for r in result.rules_fired}
    assert "closed-pack" in fired["pipeline.fail_closed"]["reason"]


def test_a_fail_open_pack_lets_a_degraded_call_through(session):
    assert _decide(session, fail_mode="open").verdict == "allow"


def test_an_observe_pack_never_blocks_on_degradation(session):
    assert _decide(session, mode="observe").verdict == "allow"


def test_a_pack_with_no_detection_rule_on_this_surface_does_not_fail_closed(session):
    """Its coverage did not depend on the detectors that degraded."""
    assert _decide(session, surface="output").verdict == "allow"
