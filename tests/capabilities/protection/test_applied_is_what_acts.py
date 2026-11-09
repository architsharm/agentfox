"""Applied rules lists what the enforcer actually applies to each agent.

After onboarding, Policies said "0 rules · Not applied" while the shipped fallback
recorded would-blocks and `capability.default_deny` / `composition.escalation`
refused calls: rules the enforcer applies without a binding were invisible, and
`composition.escalation` belonged to no library a person could find.
"""

from __future__ import annotations

from agentfox.capabilities.protection.applied import applied_rules
from agentfox.capabilities.protection.libraries import library_titles
from agentfox.platform.policy import load_from_dir, save_policy
from agentfox.platform.registry.service import register_agent

CONTAINMENT = "tool-containment"


def _rows(session) -> dict[str, dict]:
    return {r["id"]: r for r in applied_rules(session)["rules"]}


def test_with_nothing_bound_the_fallback_and_containment_facts_are_listed_watching(session):
    register_agent(session, "payables", name="payables")
    session.commit()
    rows = _rows(session)

    # The shipped fallback the enforcer evaluates when nothing is bound.
    assert rows["injection.direct"]["mode"] == "observe"
    # Its own containment facts, in Tool containment, watching like that library.
    title = library_titles()[CONTAINMENT]
    for rule_id in ("capability.default_deny", "composition.escalation"):
        assert rows[rule_id]["mode"] == "observe", rule_id
        assert rows[rule_id]["libraries"] == [title]
        assert rows[rule_id]["builtIn"] is True


def test_the_containment_facts_block_where_tool_containment_blocks(session):
    register_agent(session, "payables", name="payables")
    for doc in load_from_dir():
        if doc.key == CONTAINMENT:
            save_policy(session, doc, author="test", bind_mode="enforce")
    session.commit()
    rows = _rows(session)

    assert rows["composition.escalation"]["mode"] == "enforce"
    # The pack's own `capability.denied` stands for the missing-grant fact.
    assert rows["capability.denied"]["mode"] == "enforce"
    assert "capability.default_deny" not in rows
    # Nothing else is bound for it, but a pack is: no fallback.
    assert "injection.direct" not in rows


def test_library_cards_agree_with_applied_rules(session):
    """The Libraries tab reads the same facts: with nothing bound, the baseline is on
    by default (watching) and Tool containment's built-in rules watch."""
    from agentfox.capabilities.protection.libraries import library_status

    register_agent(session, "payables", name="payables")
    session.commit()
    baseline = library_status(session, "baseline", ["payables"])
    assert baseline["agents"] == [] and baseline["fallback"] is True
    containment = library_status(session, CONTAINMENT, ["payables"])
    assert containment["builtIn"] is True and containment["fallback"] is False

    for doc in load_from_dir():
        if doc.key == CONTAINMENT:
            save_policy(session, doc, author="test", bind_mode="observe")
    session.commit()
    # Something is bound now: the fallback no longer applies, and the card says so.
    assert library_status(session, "baseline", ["payables"])["fallback"] is False
