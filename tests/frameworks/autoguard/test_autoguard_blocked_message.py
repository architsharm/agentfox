"""An injection refused in the user's app (audit 2026-11-08, A6): `Blocked` reads as
one sentence naming the rule, and uncaught it prints one line, not a traceback."""

from __future__ import annotations

import sys

from agentfox.frameworks.autoguard import Blocked, _blocked_hook, auto, off
from agentfox.runtime.enforcement import EnforcementResult


def _injection() -> EnforcementResult:
    return EnforcementResult(
        verdict="block",
        effective_verdict="block",
        mode="enforce",
        reason="Prompt injection detected.; System prompt extraction attempt.",
        rules_fired=[
            {"rule_id": "injection.direct", "effect": "block", "mode": "enforce",
             "reason": "Prompt injection detected."},
            {"rule_id": "injection.system_prompt_leak", "effect": "block", "mode": "enforce",
             "reason": "System prompt extraction attempt."},
        ],
    )


def test_the_message_is_one_sentence_naming_the_rule():
    message = str(Blocked(_injection()))
    assert message == (
        "Jailbreaks & prompt injection: Prompt injection detected "
        "(also: System prompt extraction)."
    )
    assert ".;" not in message and "injection.direct" not in message


def test_an_uncaught_blocked_prints_one_line(capsys):
    previous: list = []
    hook = _blocked_hook(lambda *a: previous.append(a))
    try:
        raise Blocked(_injection())
    except Blocked as exc:
        hook(type(exc), exc, exc.__traceback__)
    err = capsys.readouterr().err
    assert err.strip().splitlines() == [
        "AgentFox blocked this message: Jailbreaks & prompt injection: Prompt injection "
        "detected (also: System prompt extraction). Catch agentfox.Blocked to handle it."
    ]
    assert previous == []


def test_other_exceptions_reach_the_previous_hook(capsys):
    previous: list = []
    hook = _blocked_hook(lambda *a: previous.append(a))
    error = ValueError("not ours")
    hook(ValueError, error, None)
    assert previous and previous[0][1] is error
    assert capsys.readouterr().err == ""


def test_auto_installs_the_hook_and_off_removes_it(fake_openai):
    before = sys.excepthook
    auto(agent="support-bot", quiet=True)
    assert getattr(sys.excepthook, "__agentfox__", False)
    auto(agent="support-bot", quiet=True)  # twice: still one layer
    assert sys.excepthook.__agentfox_previous__ is before
    off()
    assert sys.excepthook is before
