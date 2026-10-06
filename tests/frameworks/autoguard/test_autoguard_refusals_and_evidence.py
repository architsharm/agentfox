"""auto()'s refusal names the rule that refused, it creates the agent's identity,
and the evidence kwargs are never silently dropped (#83, #5)."""

from __future__ import annotations

import sys

import pytest

from agentfox.frameworks.autoguard import Blocked, auto, off
from tests.frameworks.autoguard.test_autoguard import _install_fake_openai
from tests.frameworks.autoguard.test_autoguard_tool_calls import (
    TOOLS,
    _bind_shipped_policies,
    _exfiltration_turn,
    fake_openai,  # noqa: F401 - fixture
)


def _db():
    from agentfox.core.db import session_scope

    return session_scope()


def test_a_policy_mode_refusal_leads_with_the_rule_that_refused(fake_openai):  # noqa: F811
    """#83: with no grants, capability default-deny is exempt in policy mode. It must
    not be what the message says refused the call."""
    _bind_shipped_policies()
    client, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    auto(agent="support-bot", quiet=True)

    with pytest.raises(Blocked) as excinfo:
        client().create(model="gpt-4o", messages=messages, tools=TOOLS)
    message = str(excinfo.value)
    assert message.startswith("agentfox: tool call send_email was refused by taint."), message
    assert "capability.denied not applied" in message


def test_auto_creates_the_agents_identity(fake_openai):  # noqa: F811
    """#83: a refusal said "no resolved identity for the caller" and a grant had
    nothing to attach to until `permit grant` made one."""
    from agentfox.core.models import Agent, Identity

    auto(agent="support-bot", quiet=True)
    with _db() as session:
        agent = session.query(Agent).filter_by(slug="support-bot").one()
        identity = session.query(Identity).filter_by(agent_id=agent.id).one()
        assert identity.principal == "agent:support-bot"
        assert identity.last_used_at is not None


@pytest.fixture
def openai_reply():
    saved = {k: sys.modules.get(k) for k in list(sys.modules) if k.startswith("openai")}

    def install(reply: str):
        return _install_fake_openai(reply)

    yield install
    off()
    for key in [k for k in list(sys.modules) if k.startswith("openai")]:
        del sys.modules[key]
    for key, value in saved.items():
        if value is not None:
            sys.modules[key] = value


def test_chunks_without_a_principal_are_checked_for_source_authority(openai_reply):
    """#5: `agentfox_chunks` with no `agentfox_principal` skipped every evidence
    check. An answer built on a deprecated source is a finding either way."""
    from agentfox.capabilities.grounding.provenance import register_source
    from agentfox.core.models import Finding

    with _db() as session:
        register_source(session, "wiki-2019", tier="approved", deprecated=True)

    client, _calls = openai_reply("The refund window is 30 days [wiki-2019].")
    auto(agent="support-bot", quiet=True)
    client().create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "refund window?"}],
        agentfox_chunks=[{"source": "wiki-2019", "text": "refund window is 30 days"}],
    )
    with _db() as session:
        types = {f.type for f in session.query(Finding).all()}
    assert "source_authority" in types, types


def test_an_unregistered_principal_is_recorded_not_ignored(openai_reply):
    """#5: a subject nobody registered resolved to no principal, and the entitlement
    check then recorded nothing. It is evaluated as itself, with no groups."""
    from agentfox.capabilities.grounding.entitlement import grant
    from agentfox.core.models import DisclosureEvent, EndUserPrincipal

    with _db() as session:
        grant(session, "kb/*", principal="all-staff")  # a group grant: not this subject's
        grant(session, "kb/faq", principal="bob@acme.com", principal_kind="subject")

    client, _calls = openai_reply("Refunds within 30 days.")
    auto(agent="support-bot", quiet=True)
    client().create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        agentfox_principal={"subject": "bob@acme.com"},
        agentfox_chunks=[
            {"source": "kb/faq", "text": "Refunds within 30 days."},
            {"source": "kb/salaries", "text": "Head of Eng: 210,000."},
        ],
    )
    with _db() as session:
        event = session.query(DisclosureEvent).one()
        assert event.principal_subject == "bob@acme.com"
        assert (event.candidates, event.withheld) == (2, 1)
        # Evaluated, not registered: the subject is not written as a principal.
        assert session.query(EndUserPrincipal).count() == 0
