"""The Claude Code hook contract, as measured rather than as documented.

Every field and behaviour asserted here was established by installing a hook
into a live Claude Code 2.1.220 session and watching what happened. The probe
denied one sentinel string and allowed everything else, so the session stayed
usable while the deny path was exercised for real.

What it established:

  deny        `hookSpecificOutput.permissionDecision: "deny"` stopped the call
              and `permissionDecisionReason` reached the agent verbatim.
  rewrite     `updatedInput` replaced the command — ours ran, not the model's.
  exit 2      also blocks, and is the wrong mechanism: the harness prefixes
              stderr with the hook script's path, so the operator reads
              "[/path/to/hook.sh]: <reason>" instead of the reason.

Cross-checked against the shipped bundle, where the PreToolUse schema and the
allow|deny|ask|defer vocabulary are visible as plaintext, and `defer` is
documented print-mode only.
"""

from __future__ import annotations

import pytest

from agentfox.hooks import harness as H
from agentfox.hooks.capability import CAN_REWRITE_INPUT, capability_of

#: The payload shape recorded from a live session, field for field.
LIVE_PAYLOAD = {
    "session_id": "51690438-15cf-42ec-80c2-29ce269bcca9",
    "transcript_path": "/Users/x/.claude/projects/p/s.jsonl",
    "cwd": "/Users/x/repo",
    "scratchpad_dir": "/private/tmp/claude-501/x/scratchpad",
    "prompt_id": "fbd8706b-7f87-41f9-b6ef-f334ea16826e",
    "permission_mode": "auto",
    "agent_type": "claude",
    "effort": {"level": "high"},
    "hook_event_name": "PreToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "ls -la"},
    "tool_use_id": "toolu_0189f7ecUBp1BdF23NioxoiP",
}


def test_the_real_payload_parses():
    call = H.parse("claude", LIVE_PAYLOAD)
    assert call.tool == "Bash"
    assert call.arguments == {"command": "ls -la"}
    assert call.event == "PreToolUse"
    assert call.session_id.startswith("51690438")
    assert call.cwd == "/Users/x/repo"
    assert call.permission_mode == "auto"


def test_a_non_dict_tool_input_does_not_crash_the_hook():
    """A hook that throws takes the agent's tool call with it."""
    call = H.parse("claude", {**LIVE_PAYLOAD, "tool_input": "raw string"})
    assert call.arguments == {"value": "raw string"}


def test_an_unknown_harness_is_refused_rather_than_guessed():
    """Assuming another harness matches this shape is how a hook reports
    itself as a gate while enforcing nothing."""
    with pytest.raises(H.UnknownHarness, match="probing"):
        H.parse("cursor", LIVE_PAYLOAD)


# ---------------------------------------------------------------------------
# What we send back
# ---------------------------------------------------------------------------


def test_a_block_renders_the_shape_that_was_probed_to_work():
    call = H.parse("claude", LIVE_PAYLOAD)
    out = H.render("claude", call, {"verdict": "block", "reason": "no", "rules": ["r.one"]})
    hook = out["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["permissionDecision"] == "deny"
    assert "r.one" in hook["permissionDecisionReason"], "the agent needs to know what it tripped"


def test_escalate_refuses_rather_than_falling_through():
    """At a hook there is nobody to escalate to: the agent is mid-call and
    nobody is watching a queue. Refusing with the reason is the honest
    rendering; letting it through because the verdict was not literally
    'block' is the failure."""
    call = H.parse("claude", LIVE_PAYLOAD)
    for verdict in ("escalate", "abstain"):
        out = H.render("claude", call, {"verdict": verdict, "reason": "needs a human"})
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", verdict


def test_an_allow_says_allow_and_nothing_else():
    call = H.parse("claude", LIVE_PAYLOAD)
    hook = H.render("claude", call, {"verdict": "allow"})["hookSpecificOutput"]
    assert hook["permissionDecision"] == "allow"
    assert "updatedInput" not in hook, "an ordinary allow should not round-trip the arguments"


def test_a_rewritten_argument_is_sent_as_updated_input():
    """Probed: `updatedInput` replaces the call. That makes an `alter` verdict
    — strip the secret, bound the statement — enforceable at a hook rather
    than downgraded to a refusal."""
    call = H.parse("claude", LIVE_PAYLOAD)
    hook = H.render(
        "claude",
        call,
        {"verdict": "allow", "rewrittenArguments": {"command": "ls"}},
    )["hookSpecificOutput"]
    assert hook["updatedInput"] == {"command": "ls"}


def test_an_unchanged_rewrite_is_not_sent():
    call = H.parse("claude", LIVE_PAYLOAD)
    hook = H.render(
        "claude", call, {"verdict": "allow", "rewrittenArguments": {"command": "ls -la"}}
    )["hookSpecificOutput"]
    assert "updatedInput" not in hook


# ---------------------------------------------------------------------------
# The harness's own tools
# ---------------------------------------------------------------------------


def test_the_shell_tool_is_not_declared_irreversible():
    """Found on the first end-to-end run, where `git status` was refused.

    A shell tool has no fixed impact: `ls -la` is a read and `rm -rf /` is
    catastrophic. Declaring the tool at its worst case made
    `intent.undeclared_irreversible` fire on every command the agent ran. The
    tool-level impact is the floor; `analyse_shell` supplies the ceiling.
    """
    assert H.HARNESS_TOOLS["claude"]["Bash"] == "write"


def test_read_only_tools_are_declared_as_reads():
    for tool in ("Read", "Glob", "Grep", "WebFetch", "WebSearch"):
        assert H.HARNESS_TOOLS["claude"][tool] == "read", tool


def test_a_subagent_spawn_is_high_impact():
    """Its blast radius is not its own — it spawns an agent with its own
    tools, which is what the cascade rules reason about."""
    assert H.HARNESS_TOOLS["claude"]["Task"] == "high_impact"


# ---------------------------------------------------------------------------
# The claims we are allowed to make
# ---------------------------------------------------------------------------


def test_claude_pretooluse_is_recorded_as_probed():
    row = capability_of("claude", "PreToolUse")
    assert row is not None
    assert row.capability == "block"
    assert row.evidence == "LIVE_PROBE"
    # The version is part of the claim, not a footnote: a row whose version
    # has moved is due for a re-probe, not evidence.
    assert row.version == "2.1.220"


def test_rewriting_is_recorded_separately_from_blocking():
    assert "claude" in CAN_REWRITE_INPUT
    assert CAN_REWRITE_INPUT["claude"].evidence == "LIVE_PROBE"


def test_no_other_harness_is_claimed():
    """One harness has been probed. The rest are absent, and absent means
    unverified rather than a gap to fill with plausible values."""
    from agentfox.hooks.capability import CAPABILITY

    assert {harness for harness, _event in CAPABILITY} == {"claude"}
