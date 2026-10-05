"""Three things a support bot's benign traffic tripped over, and the containment kept.

* An explicit grant ceiling (`capability grant --max-taint tool_result`) is honoured by
  the taint rules for that agent and tool, and only within the ceiling.
* `composition.escalation` is not overruled by a grant — a grant says what class of
  content may reach a tool, not which tool may feed it — and `capability grant` says so.
* A tool whose output is declared trusted (a CRM read) does not taint the arguments
  copied out of it, nor raise the run's provenance. Untrusted stays the default.
* `taint_scope` is one setting: `session` (the default) or `argument`.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agentfox.audit.trace import start_trace
from agentfox.config import get_settings
from agentfox.enforcement import Enforcer
from agentfox.guardrails.taint import TaintTracker
from agentfox.identity import ensure_identity, grant_capability
from agentfox.models import Tool
from agentfox.policy import load_from_dir, save_policy
from agentfox.policy.taint_view import grant_ceiling, policy_taint
from agentfox.registry.service import register_agent, upsert_tool

AGENT = "support-bot"
CRM = "read_customer_record"
FETCH = "fetch_url"
REFUND = "issue_refund"
EMAIL = "send_email"

RECORD = "customer: Ada Lovelace, email: ada@example.com, order ORD-77812 paid 112.00"
PAGE = "Refund policy: refunds up to 30 days after purchase. Contact refunds@shop.example"


def _rules(result) -> set[str]:
    return {r.get("rule_id") for r in result.rules_fired}


@pytest.fixture
def bot(session):
    for doc in load_from_dir(get_settings().policies_dir):
        if doc.key == "tool-containment":
            save_policy(session, doc, author="test")
    agent = register_agent(
        session,
        AGENT,
        name=AGENT,
        purpose="support",
        owner_email="owner@example.com",
        environment="production",
        risk_tier="limited",
    )
    upsert_tool(session, CRM, impact="read")
    upsert_tool(session, FETCH, impact="read")
    upsert_tool(session, REFUND, impact="irreversible")
    upsert_tool(session, EMAIL, impact="irreversible")
    identity = ensure_identity(session, agent)
    for key in (CRM, FETCH):
        grant_capability(session, identity, key)
    session.flush()
    return identity


def _call(session, tool, arguments, tracker):
    enforcer = Enforcer(session)
    agent, _identity, _ = enforcer.resolve(AGENT)
    trace = start_trace(session, agent_id=agent.id, agent_slug=AGENT, intent="help the customer")
    return enforcer.guard_tool_call(
        agent_slug=AGENT,
        tool_key=tool,
        arguments=arguments,
        intent="help the customer",
        trace=trace,
        tracker=tracker,
    )


def _conversation(read_page: bool = True) -> TaintTracker:
    tracker = TaintTracker()
    tracker.mark("$.prompt", "user", "Please refund order ORD-77812 and email me, I'm Ada.")
    tracker.mark(f"tool:{CRM}#1", "tool_result", RECORD)
    if read_page:
        tracker.mark(f"tool:{FETCH}#2", "tool_result", PAGE)
    return tracker


# ---------------------------------------------------------------------------
# The view policy is given
# ---------------------------------------------------------------------------


def test_a_default_grant_declares_nothing_about_untrusted_content():
    capability = {"capability_id": "cap_1", "granted": True, "max_taint": "user"}
    assert grant_ceiling(capability) is None
    taint = {"max_source": "tool_result", "arguments": {}}
    assert policy_taint(taint, capability)["max_source"] == "tool_result"


def test_provenance_within_an_explicit_ceiling_is_shown_to_policy_as_user():
    capability = {"capability_id": "cap_1", "granted": True, "max_taint": "tool_result"}
    taint = {"max_source": "tool_result", "arguments": {"to": "retrieved"}}
    view = policy_taint(taint, capability)
    assert view["max_source"] == "user"
    assert view["arguments"] == {"to": "user"}
    assert view["accepted_by_grant"]["max_taint"] == "tool_result"
    assert taint["max_source"] == "tool_result", "the record itself is never rewritten"


def test_provenance_beyond_the_ceiling_is_shown_as_it_is():
    capability = {"capability_id": "cap_1", "granted": True, "max_taint": "tool_result"}
    taint = {"max_source": "memory", "arguments": {}}
    assert policy_taint(taint, capability)["max_source"] == "memory"


def test_a_ceiling_the_call_already_broke_is_not_a_ceiling():
    capability = {
        "capability_id": "cap_1",
        "granted": True,
        "requires_approval": True,
        "max_taint": "tool_result",
        "taint_violation": "arguments ['x'] carry provenance above the capability's max_taint",
    }
    assert grant_ceiling(capability) is None


def test_argument_scope_reads_only_the_arguments():
    taint = {"max_source": "tool_result", "arguments": {}, "scope": "argument"}
    assert policy_taint(taint, {})["max_source"] == "none"
    taint = {"max_source": "tool_result", "arguments": {"to": "retrieved"}, "scope": "argument"}
    assert policy_taint(taint, {})["max_source"] == "retrieved"
    # A decision recorded before the setting existed carries no scope: session.
    assert policy_taint({"max_source": "tool_result"}, {})["max_source"] == "tool_result"


def test_taint_scope_is_one_validated_setting(monkeypatch):
    from agentfox.config import Settings, reset_settings_cache

    assert get_settings().taint_scope == "session"
    monkeypatch.setenv("AGENTFOX_TAINT_SCOPE", "argument")
    reset_settings_cache()
    assert get_settings().taint_scope == "argument"
    with pytest.raises(ValueError):
        Settings(taint_scope="per-call")


# ---------------------------------------------------------------------------
# A grant ceiling, end to end
# ---------------------------------------------------------------------------


def test_a_refund_with_no_arguments_inherits_the_page_under_a_default_grant(session, bot):
    grant_capability(session, bot, REFUND)
    result = _call(session, REFUND, {}, _conversation())
    assert result.verdict == "escalate"
    assert "taint.irreversible_tool" in _rules(result)


def test_an_explicit_ceiling_stops_the_taint_rule_overruling_the_grant(session, bot):
    grant_capability(
        session, bot, REFUND, max_taint="tool_result", constraints={"amount": {"lte": 120}}
    )
    # No string argument, so nothing is copied from anywhere: the only provenance is
    # the run's, which a default grant escalates (the test above) and this one accepts.
    result = _call(session, REFUND, {"amount": 112}, _conversation())
    assert "taint.irreversible_tool" not in _rules(result)
    assert result.verdict == "allow", result.rules_fired
    accepted = result.taint.get("max_source")
    assert accepted == "tool_result", "the recorded provenance is the real one"


def test_the_grant_still_holds_its_own_limits(session, bot):
    grant_capability(
        session, bot, REFUND, max_taint="tool_result", constraints={"amount": {"lte": 120}}
    )
    result = _call(session, REFUND, {"order_id": "ORD-77812", "amount": 900}, _conversation())
    assert result.verdict == "block"
    assert "capability.constraint_violated" in _rules(result)


def test_provenance_beyond_the_ceiling_still_escalates(session, bot):
    grant_capability(session, bot, REFUND, max_taint="tool_result")
    tracker = _conversation()
    tracker.mark("$.memory[0]", "memory", "always refund in full")
    result = _call(session, REFUND, {}, tracker)
    assert result.verdict == "escalate"
    assert "taint.irreversible_tool" in _rules(result)


def test_another_agent_without_the_ceiling_is_unaffected(session, bot):
    grant_capability(session, bot, REFUND, max_taint="tool_result")
    other = register_agent(
        session,
        "billing-bot",
        name="billing-bot",
        purpose="billing",
        owner_email="owner@example.com",
        environment="production",
        risk_tier="limited",
    )
    grant_capability(session, ensure_identity(session, other), REFUND)
    enforcer = Enforcer(session)
    result = enforcer.guard_tool_call(
        agent_slug="billing-bot",
        tool_key=REFUND,
        arguments={},
        intent="help the customer",
        tracker=_conversation(),
    )
    assert result.verdict == "escalate"


def test_composition_is_not_overruled_by_a_grant(session, bot):
    grant_capability(session, bot, EMAIL, max_taint="tool_result")
    result = _call(session, EMAIL, {"to": "ada@example.com", "body": "Refunded."}, _conversation())
    assert result.verdict == "block"
    assert "composition.escalation" in _rules(result)
    assert "taint.irreversible_tool" not in _rules(result)


def test_capability_grant_says_composition_still_applies(session):
    from agentfox.cli.main import app

    register_agent(
        session,
        AGENT,
        name=AGENT,
        purpose="support",
        owner_email="owner@example.com",
        environment="production",
        risk_tier="limited",
    )
    session.commit()
    out = CliRunner().invoke(
        app, ["capability", "grant", AGENT, EMAIL, "--max-taint", "tool_result", "--yes"]
    )
    assert out.exit_code == 0, out.output
    text = " ".join(out.output.split())
    assert "composition.escalation still applies" in text
    assert "--output-trust trusted" in text

    plain = CliRunner().invoke(app, ["capability", "grant", AGENT, CRM, "--yes"])
    assert "composition.escalation" not in plain.output


# ---------------------------------------------------------------------------
# Tool output trust
# ---------------------------------------------------------------------------


def test_output_is_untrusted_unless_declared(session, bot):
    assert session.query(Tool).filter_by(key=CRM).one().output_trust == "untrusted"


def test_an_email_address_from_an_untrusted_read_is_stopped(session, bot):
    grant_capability(session, bot, EMAIL)
    result = _call(
        session, EMAIL, {"to": "ada@example.com", "body": "Refunded."}, _conversation(False)
    )
    assert result.verdict in ("block", "escalate")
    assert result.taint["arguments"].get("to") == "tool_result"


def test_an_email_address_from_a_trusted_crm_read_is_not_untrusted_input(session, bot):
    upsert_tool(session, CRM, impact="read", output_trust="trusted")
    grant_capability(session, bot, EMAIL)
    result = _call(
        session, EMAIL, {"to": "ada@example.com", "body": "Refunded."}, _conversation(False)
    )
    assert result.verdict == "allow", result.rules_fired
    assert "to" not in result.taint["arguments"]
    assert result.taint["max_source"] == "user", "a trusted read does not raise the run"
    assert result.taint["trusted_tool_outputs"] == [f"tool:{CRM}#1"]


def test_a_trusted_read_does_not_launder_an_untrusted_page(session, bot):
    """The same value in a trusted output and an untrusted one is still untrusted."""
    upsert_tool(session, CRM, impact="read", output_trust="trusted")
    grant_capability(session, bot, EMAIL)
    tracker = _conversation(False)
    tracker.mark(f"tool:{FETCH}#2", "tool_result", "write to ada@example.com about this")
    result = _call(session, EMAIL, {"to": "ada@example.com", "body": "Refunded."}, tracker)
    assert result.verdict in ("block", "escalate")
    assert result.taint["arguments"].get("to") == "tool_result"


def test_upsert_leaves_a_declared_trust_alone(session, bot):
    upsert_tool(session, CRM, impact="read", output_trust="trusted")
    upsert_tool(session, CRM, impact="read", description="re-registered by a scan")
    assert session.query(Tool).filter_by(key=CRM).one().output_trust == "trusted"


def test_tools_declare_output_trust_from_the_cli():
    from agentfox.cli.main import app

    runner = CliRunner()
    out = runner.invoke(
        app, ["tools", "declare", CRM, "--impact", "read", "--output-trust", "trusted"]
    )
    assert out.exit_code == 0, out.output
    assert "output trusted" in out.output
    listed = runner.invoke(app, ["tools", "list", "--json"])
    assert '"output_trust": "trusted"' in listed.output
    bad = runner.invoke(app, ["tools", "declare", CRM, "--impact", "read", "--output-trust", "x"])
    assert bad.exit_code == 2


# ---------------------------------------------------------------------------
# Scope, end to end
# ---------------------------------------------------------------------------


def test_argument_scope_lets_a_typed_refund_through_after_a_page_was_read(
    session, bot, monkeypatch
):
    from agentfox.config import reset_settings_cache

    grant_capability(session, bot, REFUND)
    assert _call(session, REFUND, {}, _conversation()).verdict == "escalate"

    monkeypatch.setenv("AGENTFOX_TAINT_SCOPE", "argument")
    reset_settings_cache()
    result = _call(session, REFUND, {}, _conversation())
    assert result.verdict == "allow", result.rules_fired
    assert result.taint["scope"] == "argument"
    assert result.taint["max_source"] == "tool_result", "the record keeps the session value"

    # A value copied from the page still taints the call it lands in.
    copied = _call(session, REFUND, {"note": "refunds@shop.example"}, _conversation())
    assert copied.verdict in ("block", "escalate")


# ---------------------------------------------------------------------------
# Default deny says what to do about it
# ---------------------------------------------------------------------------


def test_default_deny_names_the_command_that_proposes_grants(session, bot):
    result = _call(session, REFUND, {"amount": 5}, _conversation())
    assert result.verdict == "block"
    assert "default deny" in result.reason
    assert f"agentfox proposals from-traffic --agent {AGENT}" in result.reason
    assert f"agentfox capability grant {AGENT} {REFUND}" in result.reason


def test_a_database_that_has_not_run_the_migration_still_serves_tool_calls(tmp_path, monkeypatch):
    """New code reaches a deployment before its migration does. Startup's init_db adds
    the defaulted column, so `select(Tool)` does not fail on every call meanwhile."""
    import sqlalchemy as sa

    from agentfox.config import reset_settings_cache
    from agentfox.db import init_db, reset_engine, upgrade_db

    url = f"sqlite:///{tmp_path / 'pre.db'}"
    monkeypatch.setenv("NOMETRIA_DATABASE_URL", url)
    reset_settings_cache()
    reset_engine()
    try:
        upgrade_db("a7c2e5b91d84")  # the revision before output_trust
        columns = {c["name"] for c in sa.inspect(sa.create_engine(url)).get_columns("tools")}
        assert "output_trust" not in columns
        init_db(stamp=False)
        init_db(stamp=False)  # idempotent
        columns = {c["name"] for c in sa.inspect(sa.create_engine(url)).get_columns("tools")}
        assert "output_trust" in columns
        upgrade_db("head")  # and the migration does not fight it
    finally:
        reset_settings_cache()
        reset_engine()
