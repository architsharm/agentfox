"""Adding an agent allows the tools its own code hands it, and nothing else.

Every tool `agentfox init` found used to start "Not allowed", so the app's own calls
were refused on the first run and no rule could be tested until each tool was allowed
by hand."""

from __future__ import annotations

from agentfox.platform.identity.service import ensure_identity
from agentfox.platform.registry.service import approve_drafts, propose_draft, upsert_tool


def test_adding_an_agent_allows_its_own_tools_with_taint_limits_on_risky_ones(session):
    upsert_tool(session, "lookup_order", impact="read", actor="t")
    upsert_tool(session, "send_email", impact="irreversible", actor="t")
    agent = propose_draft(
        session, slug="support", name="support", declared_tools=["lookup_order", "send_email"]
    )
    approve_drafts(session, [agent], actor="admin@example.com")

    grants = {c.tool_key: c for c in ensure_identity(session, agent).capabilities}
    assert set(grants) == {"lookup_order", "send_email"}
    assert grants["lookup_order"].max_taint == "memory"  # a read: any argument
    # Sends data out: an argument copied from a tool result or page is still stopped.
    assert grants["send_email"].max_taint == "user"
    assert not grants["send_email"].requires_approval


def test_a_grant_someone_already_made_is_left_alone(session):
    from agentfox.platform.identity.service import grant_capability

    agent = propose_draft(session, slug="support", name="support", declared_tools=["refund"])
    grant_capability(session, ensure_identity(session, agent), "refund", requires_approval=True)
    approve_drafts(session, [agent], actor="admin@example.com")

    [grant] = ensure_identity(session, agent).capabilities
    assert grant.requires_approval is True
