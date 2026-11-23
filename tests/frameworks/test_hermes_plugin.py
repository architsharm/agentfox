"""The Hermes Agent plugin in sdk/hermes: verdicts mapped onto Hermes's pre_tool_call directives."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "sdk" / "hermes" / "__init__.py"
_spec = importlib.util.spec_from_file_location("agentfox_hermes_plugin", _PATH)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


class Gateway:
    """Stands in for `Remote`: records each body and answers with `reply`."""

    def __init__(self, reply):
        self.reply = reply
        self.sent: list[tuple[str, dict]] = []

    def post(self, path, body):
        self.sent.append((path, body))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


KW = {"task_id": "t1", "session_id": "s2", "conversation_id": "c1", "tool_call_id": "call_1"}


def guard(reply, **opts):
    gw = Gateway(reply)
    return plugin.Guard("", remote=gw, **opts), gw


def test_allowed_call_runs_and_sends_the_call():
    g, gw = guard({"verdict": "allow", "effective_verdict": "allow"})
    assert g.pre_tool_call(tool_name="terminal", args={"command": "ls"}, **KW) is None
    path, body = gw.sent[0]
    assert path == "/v1/guard/tool_call"
    assert body == {
        "agent": "hermes",
        "tool": "terminal",
        "arguments": {"command": "ls"},
        "provenance": {},
        "declare": {"name": "terminal"},
        "redeem_approved": True,
        "in_process": "enforced",
        "session_id": "c1",
    }


def test_watch_mode_does_not_block():
    g, _ = guard({"verdict": "allow", "effective_verdict": "block", "reason": "would block"})
    assert g.pre_tool_call(tool_name="terminal", args={"command": "rm -rf /"}, **KW) is None


def test_block_uses_the_rules_message():
    g, _ = guard(
        {"verdict": "block", "reason": "internal", "user_message": "Recursive delete blocked"}
    )
    out = g.pre_tool_call(tool_name="terminal", args={"command": "rm -rf ~"}, **KW)
    assert out == {"action": "block", "message": "Recursive delete blocked."}


def test_held_call_points_at_the_approver_in_agentfox():
    g, _ = guard(
        {
            "verdict": "escalate",
            "reason": "Untrusted recipient.",
            "explain_url": "http://af/app/approvals/apr_1",
        }
    )
    out = g.pre_tool_call(tool_name="send_message", args={"to": "x@evil.example"}, **KW)
    assert out["action"] == "block"
    assert "Untrusted recipient." in out["message"]
    assert "http://af/app/approvals/apr_1" in out["message"]
    assert "try again" in out["message"]


def test_held_call_can_use_hermes_own_approval_gate():
    g, gw = guard({"verdict": "escalate", "reason": "Untrusted recipient."}, approvals="hermes")
    out = g.pre_tool_call(tool_name="send_message", args={}, **KW)
    assert out == {
        "action": "approve",
        "message": "AgentFox: Untrusted recipient.",
        "rule_key": "agentfox:send_message",
    }
    assert gw.sent[0][1]["redeem_approved"] is False


def test_fails_closed_unless_told_to_fail_open():
    g, _ = guard(ConnectionError("refused"))
    out = g.pre_tool_call(tool_name="terminal", args={"command": "ls"}, **KW)
    assert out["action"] == "block" and "could not check" in out["message"]
    g, _ = guard(ConnectionError("refused"), fail_mode="open")
    assert g.pre_tool_call(tool_name="terminal", args={"command": "ls"}, **KW) is None


def test_unreachable_gateway_through_the_real_client_fails_closed():
    g = plugin.Guard("http://127.0.0.1:9", "nom_agt_x", timeout=2)
    out = g.pre_tool_call(tool_name="terminal", args={"command": "ls"}, **KW)
    assert out["action"] == "block"


def test_tool_results_travel_as_messages_for_provenance():
    g, gw = guard({"verdict": "allow"}, results_kept=2)
    for i in range(3):
        g.post_tool_call(
            tool_name="web_extract", result=f"page {i}", **{**KW, "tool_call_id": f"c{i}"}
        )
    g.post_tool_call(tool_name="web_extract", result={"text": "elsewhere"}, conversation_id="other")
    g.pre_tool_call(tool_name="terminal", args={"command": "x"}, **KW)
    messages = gw.sent[0][1]["messages"]
    assert [m["content"] for m in messages] == ["page 1", "page 2"]
    assert messages[0] == {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "web_extract",
        "content": "page 1",
    }


def test_settings_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGENTFOX_URL", "http://af:8080/")
    monkeypatch.setenv("AGENTFOX_AGENT_KEY", "nom_agt_x")
    monkeypatch.setenv("AGENTFOX_AGENT", "hermes-ops")
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "open")
    g = plugin.Guard.from_env()
    assert (g.remote.url, g.remote.key, g.agent, g.fail_open) == (
        "http://af:8080",
        "nom_agt_x",
        "hermes-ops",
        True,
    )
    monkeypatch.delenv("AGENTFOX_URL")
    with pytest.raises(ValueError, match="AGENTFOX_URL"):
        plugin.Guard.from_env()


def test_register_wires_both_hooks(monkeypatch):
    monkeypatch.setenv("AGENTFOX_URL", "http://af:8080")
    hooks = {}

    class Ctx:
        def register_hook(self, name, fn):
            hooks[name] = fn

    plugin.register(Ctx())
    assert set(hooks) == {"pre_tool_call", "post_tool_call"}
