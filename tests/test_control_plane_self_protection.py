"""An agent could switch off the controls governing it, and nothing stopped it.

A governed agent with shell access could run `agentfox policy observe baseline`
and drop every content policy out of enforce mode, overwrite `agentfox.toml`,
delete the database, or re-point `AGENTFOX_DATABASE_URL` at an empty one. The
only record of it would be the decision log it had just disabled.

This is the control every other control depends on, which is the argument for
treating it differently from the rest of the deny-list: a destructive command
harms the business, and this one harms the ability to see that it happened.

The shape is borrowed from a competitor who had already found it — their
always-on policy carries the reasoning verbatim: an agent that can pause
enforcement can switch off every other policy.
"""

from __future__ import annotations

import pytest
import yaml

from agentfox.config import get_settings
from agentfox.guardrails.actions import analyse_shell
from agentfox.policy.model import PROTECTED_RULES, PolicyDocument
from agentfox.policy.store import load_from_dir


def codes(command: str) -> list[str]:
    return [risk.code for risk in analyse_shell(command).risks]


# ---------------------------------------------------------------------------
# What it catches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "agentfox policy observe baseline",
        "agentfox policy disable tool-containment",
        "agentfox capability revoke support-triage payments.transfer",
        "agentfox agents resume quarantined-bot",
        "agentfox db downgrade -1",
        "agentfox auth issue attacker@example.com",
        # The consolidated names for the same commands (cli/layout.py).
        "agentfox permit revoke support-triage payments.transfer",
        "agentfox permit grant support-triage payments.transfer",
        "agentfox admin db downgrade -1",
        "agentfox admin auth issue attacker@example.com",
        # The CLI reached by its other spellings.
        "uv run agentfox policy observe baseline",
        "uvx agentfox policy observe baseline",
        "python -m agentfox policy observe baseline",
        "python3.12 -m agentfox policy observe baseline",
        # The state behind it, without running the CLI at all.
        "echo 'mode = observe' > agentfox.toml",
        "cat /dev/null > agentfox.toml",
        "rm -f agentfox.db",
        "rm -rf ~/.agentfox",
        "export AGENTFOX_DATABASE_URL=sqlite:////tmp/empty.db",
        "AGENTFOX_STATE_DIR=/tmp/elsewhere agentfox seed",
    ],
)
def test_a_command_that_disables_enforcement_is_a_critical_risk(command):
    assert "control-plane-tamper" in codes(command), command
    risk = next(r for r in analyse_shell(command).risks if r.code == "control-plane-tamper")
    assert risk.severity == "critical"


def test_it_is_caught_mid_chain_not_only_at_the_start():
    """`_shell_segments` exists for this; the rule has to use it."""
    assert "control-plane-tamper" in codes("cd /app && agentfox policy observe baseline")
    assert "control-plane-tamper" in codes("echo working; agentfox policy observe baseline")


# ---------------------------------------------------------------------------
# What it deliberately does not catch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "agentfox policy list",
        "agentfox policy lint",
        "agentfox findings",
        "agentfox doctor",
        "agentfox agents list",
        "agentfox compliance status",
        "agentfox report",
        "agentfox permit list",
        "agentfox admin db current",
        "cat agentfox.toml",
        "grep mode agentfox.toml",
        "ls -la ~/.agentfox",
    ],
)
def test_reading_your_own_governance_is_not_tampering(command):
    """Blocking these would teach people to turn the rule off.

    Inspecting its own governance is what a well-behaved agent is supposed to
    do, and a control with false positives on the ordinary case gets disabled —
    which is the exact outcome this rule exists to prevent.
    """
    assert "control-plane-tamper" not in codes(command), command


def test_ordinary_destructive_commands_still_report_as_destructive():
    """The new family must not shadow the existing one."""
    assert codes("rm -rf /") == ["shell.destructive"]
    assert "shell.destructive" in codes("git push --force origin main")


# ---------------------------------------------------------------------------
# The rule, and the fact that it cannot be switched off
# ---------------------------------------------------------------------------


def test_the_shipped_pack_carries_the_rule_and_blocks_on_it():
    packs = load_from_dir(get_settings().policies_dir)
    pack = next(p for p in packs if p.key == "tool-containment")
    rule = next(r for r in pack.rules if r.id == "control_plane.tamper")
    assert rule.effect == "block"
    assert rule.severity == "critical"
    assert rule.enabled is True
    assert rule.when.action_risk == "control-plane-tamper"
    # It must not be weakenable by a narrower layer either — a team-level
    # override that relaxes this is the same hole by a different route.
    assert rule.overridable is False


def test_a_pack_that_drops_the_rule_will_not_load():
    body = yaml.safe_dump({"key": "tool-containment", "rules": [{"id": "something.else"}]})
    with pytest.raises(Exception) as excinfo:
        PolicyDocument.from_yaml(body)
    # Pydantic wraps the ValueError; the message is the contract, not the class.
    assert "control_plane.tamper" in str(excinfo.value)


def test_a_pack_that_disables_the_rule_will_not_load():
    """The quieter version of the same thing, and the one a script would do."""
    body = yaml.safe_dump(
        {"key": "tool-containment", "rules": [{"id": "control_plane.tamper", "enabled": False}]}
    )
    with pytest.raises(Exception) as excinfo:
        PolicyDocument.from_yaml(body)
    assert "cannot be disabled" in str(excinfo.value)


def test_other_packs_are_unaffected():
    """Only the pack that names a protected rule is constrained."""
    doc = PolicyDocument.from_yaml(yaml.safe_dump({"key": "baseline", "rules": []}))
    assert doc.key == "baseline"
    assert "baseline" not in PROTECTED_RULES


# ---------------------------------------------------------------------------
# And the enforcer actually stops it
# ---------------------------------------------------------------------------
#
# Everything above checks the analyser and the YAML. Neither proves a deny here
# changes what happens, which is the only claim that matters — and the failure a
# competitor documented was exactly a rule everyone believed was a gate while
# the verdict was being discarded downstream.


@pytest.fixture
def shell_agent(seeded):
    from agentfox.identity import ensure_identity, grant_capability
    from agentfox.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    grant_capability(seeded, identity, "shell.run", max_taint="tool_result")
    return agent


def test_the_call_is_refused_even_though_the_tool_itself_was_granted(seeded, enforcer, shell_agent):
    """The capability check passes and the command is still refused."""
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="shell.run",
        arguments={"command": "agentfox policy observe baseline"},
    )
    assert result.blocked
    assert result.taint["capability"]["granted"] is True, "the tool itself was authorised"
    assert "control_plane.tamper" in {r["rule_id"] for r in result.rules_fired}


def test_an_ordinary_command_through_the_same_tool_is_allowed(seeded, enforcer, shell_agent):
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="shell.run",
        arguments={"command": "agentfox findings"},
    )
    assert not result.blocked
    assert "control_plane.tamper" not in {r["rule_id"] for r in result.rules_fired}
