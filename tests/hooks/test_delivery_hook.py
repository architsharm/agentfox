"""The delivery policies through `agentfox hooks run`, on Claude Code's own payloads.

Run with ``AGENTFOX_DELIVERY=only`` so no daemon is needed: the point here is the
wiring (state carried across hook processes, the reply shape per event), not the
policies themselves, which `tests/capabilities/delivery` covers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentfox.hooks.run import run

FIXTURES = Path(__file__).resolve().parents[2] / "src/agentfox/harnesses/claude_code/fixtures"
TASK = "Start an HTTP server on port 8000 that serves ./site. It must stay running."


@pytest.fixture
def hook(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFOX_DELIVERY", "only")
    monkeypatch.setenv("AGENTFOX_DELIVERY_STATE", str(tmp_path))

    def send(event: str, **fields) -> dict:
        payload = {"session_id": "s-1", "cwd": "/w", "hook_event_name": event, **fields}
        out = run("claude", "agent", json.dumps(payload))
        assert out.exit_code == 0 and not out.stderr, out.stderr
        return out.body

    return send


def bash(hook, phase: str, command: str, **extra) -> dict:
    return hook(phase, tool_name="Bash", tool_input={"command": command, **extra})


def test_a_service_left_attached_is_sent_back_once(hook):
    hook("UserPromptSubmit", prompt=TASK)
    bash(hook, "PreToolUse", "python3 -m http.server 8000", run_in_background=True)
    bash(hook, "PostToolUse", "python3 -m http.server 8000", run_in_background=True)

    first = hook("Stop", stop_hook_active=False)
    assert first["decision"] == "block"
    assert "(delivery.service_persistence)" in first["reason"]
    assert hook("Stop", stop_hook_active=True) == {}


def test_a_detached_and_probed_service_stops_cleanly(hook):
    hook("UserPromptSubmit", prompt=TASK)
    for cmd in (
        "setsid nohup python3 -m http.server 8000 > /tmp/h.log 2>&1 < /dev/null &",
        "curl -sI localhost:8000",
    ):
        bash(hook, "PreToolUse", cmd)
        bash(hook, "PostToolUse", cmd)
    assert hook("Stop", stop_hook_active=False) == {}


def test_a_refused_open_is_a_pre_tool_deny(hook):
    hook("UserPromptSubmit", prompt="The database app.db is corrupted; recover the rows.")
    body = bash(hook, "PreToolUse", "sqlite3 app.db .tables")
    decision = body["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "evidence_preservation" in decision["permissionDecisionReason"]


def test_an_instruction_before_a_write_is_context_not_a_refusal(hook):
    hook("UserPromptSubmit", prompt="Replace foo with bar in a.txt. Do not modify anything else.")
    body = hook("PreToolUse", tool_name="Edit", tool_input={"file_path": "a.txt"})
    decision = body["hookSpecificOutput"]
    assert decision["permissionDecision"] == "allow"
    assert decision["additionalContext"].startswith("AgentFox: ")


def test_off_means_off(hook, monkeypatch):
    monkeypatch.setenv("AGENTFOX_DELIVERY", "off")
    raw = (FIXTURES / "stop.json").read_text()
    assert run("claude", "agent", raw).body == {}
