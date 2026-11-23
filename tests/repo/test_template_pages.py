"""The /templates pages claim only what their policy does when the product runs it.

`dashboard/lib/marketing/templates.json` holds, per example agent, the exact CLI lines
the page prints as its policy and the calls it says are run, held or refused. This
runs those lines against a fresh database and puts each call through the enforcer, so
a page cannot keep a verdict the product stopped giving.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = json.loads((REPO_ROOT / "dashboard/lib/marketing/templates.json").read_text())


def _run_policy(lines: list[str]) -> str:
    from agentfox.apps.cli.main import app

    agent = None
    for line in lines:
        args = shlex.split(line)
        assert args[0] == "agentfox", line
        out = CliRunner().invoke(app, args[1:])
        assert out.exit_code == 0, f"{line}\n{out.output}"
        if args[1:3] == ["agents", "register"]:
            agent = args[3]
    assert agent, "the policy registers its agent"
    return agent


def _verdict(agent: str, intent: str, call: dict, untrusted: str | None):
    from agentfox.capabilities.detection.taint import TaintTracker
    from agentfox.core.db import session_scope
    from agentfox.platform.ledger.trace import start_trace
    from agentfox.runtime.enforcement import Enforcer

    tracker = TaintTracker()
    tracker.mark("$.prompt", "user", intent)
    if untrusted:
        tracker.mark("tool:read#1", "tool_result", untrusted)
    with session_scope() as s:
        enforcer = Enforcer(s)
        record, _identity, _ = enforcer.resolve(agent)
        trace = start_trace(s, agent_id=record.id, agent_slug=agent, intent=intent)
        return enforcer.guard_tool_call(
            agent_slug=agent,
            tool_key=call["tool"],
            arguments=call["arguments"],
            intent=intent,
            trace=trace,
            tracker=tracker,
        )


@pytest.mark.parametrize("template", TEMPLATES, ids=[t["slug"] for t in TEMPLATES])
def test_each_call_on_the_page_gets_the_verdict_the_page_prints(template, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # `agentfox init` writes agentfox.toml here
    agent = _run_policy(template["policy"])
    attack = template["attack"]
    calls = [(attack, attack["untrusted"])] + [(c, None) for c in template["calls"]]
    for call, untrusted in calls:
        result = _verdict(agent, template["intent"], call, untrusted)
        fired = {r.get("rule_id") for r in result.rules_fired}
        assert result.verdict == call["verdict"], (call, fired)
        if "rule" in call:
            assert call["rule"] in fired, (call, fired)
