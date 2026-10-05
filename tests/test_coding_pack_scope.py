"""The coding-agent pack applies to coding agents, and only to them.

From a fresh-user run: `init` bound the pack to every agent, and a customer-support
bot's refund email was flagged as "Personal data in a tool-call argument from a
coding session".
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from agentfox.core.models import Finding
from agentfox.policy import active_policies, load_available, save_policy
from agentfox.policy.coding import (
    CODING_PACK,
    enable_for_agent,
    hooked_agents,
    retire_tool_wildcard,
    scope_coding_pack,
)

HOOKS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "agentfox hooks run --harness claude --agent dev-laptop",
                    }
                ],
            }
        ]
    }
}


def _write_hooks(root):
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(HOOKS))


def _keys(session, slug):
    return {doc.key for doc, _v, _b in active_policies(session, slug, "production")}


def test_hooked_agents_are_read_from_the_hook_command(tmp_path):
    assert hooked_agents(tmp_path) == []
    _write_hooks(tmp_path)
    assert hooked_agents(tmp_path) == ["dev-laptop"]


def test_no_hooks_means_no_coding_pack():
    docs, scoped = scope_coding_pack(load_available(), [])
    assert CODING_PACK not in {d.key for d in docs}
    assert scoped == []


def test_hooks_scope_the_pack_to_those_agents():
    docs, scoped = scope_coding_pack(load_available(), ["dev-laptop"])
    pack = next(d for d in docs if d.key == CODING_PACK)
    assert pack.scope["agents"] == ["dev-laptop"] == scoped
    assert pack.matches_scope("dev-laptop", "production")
    assert not pack.matches_scope("support-bot", "production")


def test_seeded_support_agent_is_not_governed_by_the_coding_pack(seeded):
    assert CODING_PACK not in _keys(seeded, "support-triage")
    assert "baseline" in _keys(seeded, "support-triage")


def test_pii_in_a_support_bots_tool_call_is_not_called_a_coding_session(seeded, enforcer):
    enforcer.guard_tool_call(
        agent_slug="payments-ops",
        tool_key="email.send",
        arguments={"to": "jane.roe@example.com", "body": "Your refund to jane.roe@example.com"},
        intent="confirm a refund",
    )
    titles = " ".join(f.title for f in seeded.query(Finding))
    reasons = json.dumps([f.evidence_json for f in seeded.query(Finding)])
    assert "coding session" not in titles + reasons


def test_install_adds_the_agent_and_keeps_the_mode(seeded):
    assert enable_for_agent(seeded, "dev-laptop") == ["dev-laptop"]
    assert CODING_PACK in _keys(seeded, "dev-laptop")
    assert CODING_PACK not in _keys(seeded, "support-triage")

    from agentfox.policy import set_mode

    set_mode(seeded, CODING_PACK, "enforce")
    assert enable_for_agent(seeded, "ci-bot") == ["ci-bot", "dev-laptop"]
    (doc, _v, binding), *_ = [
        row for row in active_policies(seeded, "ci-bot", "production") if row[0].key == CODING_PACK
    ]
    assert binding.mode == "enforce"


def test_a_wildcard_binding_an_older_init_wrote_is_retired(seeded):
    pack = next(d for d in load_available() if d.key == CODING_PACK)
    save_policy(seeded, pack, author="init")
    assert CODING_PACK in _keys(seeded, "support-triage")
    assert retire_tool_wildcard(seeded)
    assert CODING_PACK not in _keys(seeded, "support-triage")


def test_a_wildcard_binding_a_person_made_is_left_alone(seeded):
    pack = next(d for d in load_available() if d.key == CODING_PACK)
    save_policy(seeded, pack, author="dana@example.com")
    assert not retire_tool_wildcard(seeded)
    assert enable_for_agent(seeded, "dev-laptop") == ["*"]
    assert CODING_PACK in _keys(seeded, "support-triage")


def test_init_skips_the_pack_without_hooks_and_scopes_it_with_them(tmp_path, monkeypatch):
    from agentfox.cli.main import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    first = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert first.exit_code == 0, first.output
    assert "coding-agent not enabled" in first.output

    _write_hooks(tmp_path)
    second = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert second.exit_code == 0, second.output
    assert "coding-agent applies to: dev-laptop" in second.output

    from agentfox.core.db import session_scope

    with session_scope() as session:
        assert CODING_PACK in _keys(session, "dev-laptop")
        assert CODING_PACK not in _keys(session, "support-bot")
