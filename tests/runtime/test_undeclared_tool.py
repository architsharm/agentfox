"""A call to a tool the registry has never heard of.

`capability.denied` answers "may this agent use this tool". Nothing answered
"is there such a tool" — and a call to one that does not exist is either the
model inventing it or a real tool nobody declared. Both want a person, and
neither is a permission question, because there is no permission to check
against.

Worse than merely unhandled: an undeclared tool inherited `impact = "read"`,
the least dangerous value in the vocabulary, so every impact-based rule above
`read` skipped the one case where the platform knows least about what is about
to happen.
"""

from __future__ import annotations

import pytest

from agentfox.core.models import Agent
from agentfox.identity import ensure_identity, grant_capability
from agentfox.policy.engine import NativePolicyEngine
from agentfox.policy.model import Condition, PolicyDocument, PolicyInput, Rule
from agentfox.runtime.enforcement import Enforcer


def _fires(tool_known: bool) -> bool:
    doc = PolicyDocument(
        key="t",
        mode="enforce",
        rules=[Rule(id="tool.not_declared", when=Condition(tool_known=False), effect="escalate")],
    )
    decision = NativePolicyEngine().evaluate(
        doc, PolicyInput(agent_slug="a", tool_key="x", tool_known=tool_known)
    )
    return decision.verdict == "escalate"


def test_the_condition_separates_known_from_unknown():
    assert _fires(tool_known=False)
    assert not _fires(tool_known=True)


def test_a_call_with_no_tool_at_all_is_not_an_unknown_tool(seeded):
    """The question does not arise on an input or output surface, and a rule
    that fired there would flag every ordinary message."""
    result = Enforcer(seeded).evaluate(
        agent=seeded.query(Agent).filter_by(slug="support-triage").one(),
        identity=None,
        content="hello",
        surface="input",
    )
    assert "tool.not_declared" not in {r["rule_id"] for r in result.rules_fired}


@pytest.fixture
def invented_tool_agent(seeded):
    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    # Granted by wildcard, so the capability check cannot be what stops it —
    # this has to be the registry answering, not the permission layer.
    grant_capability(seeded, identity, "*", max_taint="tool_result")
    return agent


def test_a_tool_the_registry_never_heard_of_is_escalated(seeded, invented_tool_agent):
    result = Enforcer(seeded).guard_tool_call(
        agent_slug="support-triage",
        tool_key="crm.definitely_not_a_real_tool",
        arguments={"id": "1"},
    )
    assert "tool.not_declared" in {r["rule_id"] for r in result.rules_fired}
    assert result.verdict == "escalate"


def test_a_declared_tool_through_the_same_path_is_untouched(seeded, invented_tool_agent):
    """`kb.search` is in the seed, so the only difference from the test above
    is whether the registry holds the key."""
    result = Enforcer(seeded).guard_tool_call(
        agent_slug="support-triage",
        tool_key="kb.search",
        arguments={"q": "refund policy"},
    )
    assert "tool.not_declared" not in {r["rule_id"] for r in result.rules_fired}


def test_the_shipped_rule_is_not_a_permission_rule():
    """If this were folded into `capability.denied` it would be silent for any
    agent holding a wildcard grant — which is exactly the test above."""
    from agentfox.core.config import get_settings
    from agentfox.policy.store import load_from_dir

    packs = load_from_dir(get_settings().policies_dir)
    rule = next(
        r
        for p in packs
        if p.key == "tool-containment"
        for r in p.rules
        if r.id == "tool.not_declared"
    )
    assert rule.when.tool_known is False
    assert rule.when.capability is None
    assert rule.effect == "escalate"
