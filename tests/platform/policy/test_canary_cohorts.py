"""#29 — a canary's cohorts are counted per policy, on effective verdicts.

Cohorts were counted by `Decision.policy_version_id`, a single id that names
whichever pack governed the decision — usually another policy's version — so a
canary never gathered a sample; and only the applied verdict counted, so a policy
in observe always showed a block rate of zero and could never be canaried.
"""

from __future__ import annotations

from agentfox.core.models import Decision
from agentfox.platform.policy import PolicyDocument, canary_health, save_policy, start_canary

OTHER = "key: other-pack\nmode: enforce\nrules: []\n"
V1 = "key: cohort-test\nmode: observe\nrules: []\n"
V2 = "key: cohort-test\nmode: observe\nname: v2\nrules: []\n"


def _record(session, governing_id: str, version_ids: list[str], *, total: int, blocked: int):
    for i in range(total):
        session.add(
            Decision(
                agent_id=None,
                verdict="allow",  # observe: nothing was applied
                policy_version_id=governing_id,
                policy_version_ids=version_ids,
                rules_fired_json=(
                    [{"rule_id": "x", "effect": "block", "mode": "observe"}] if i < blocked else []
                ),
                mode="observe",
            )
        )
    session.flush()


def test_cohorts_count_this_policys_versions_and_effective_blocks(session):
    _p, other = save_policy(session, PolicyDocument.from_yaml(OTHER), bind_mode="enforce")
    _p, v1 = save_policy(session, PolicyDocument.from_yaml(V1), bind_mode="observe")
    _p, v2 = save_policy(session, PolicyDocument.from_yaml(V2), bind_mode="observe")
    canary = start_canary(session, "cohort-test", min_sample=5)

    # Every decision names the other pack as its single governing version.
    _record(session, other.id, [other.id, v1.id], total=10, blocked=4)
    _record(session, other.id, [other.id, v2.id], total=8, blocked=2)

    health = canary_health(session, canary)
    assert health["stable"]["decisions"] == 10
    assert health["candidate"]["decisions"] == 8
    assert health["stable"]["block_rate"] == 0.4
    assert health["candidate"]["block_rate"] == 0.25
    assert health["ready"] is True
