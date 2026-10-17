"""The harness registry: one discovery mechanism, for built-in and external adapters."""

from __future__ import annotations

import importlib.metadata
from dataclasses import replace

import pytest

from agentfox import harnesses
from agentfox.harnesses.base import Decision, EventCaps, decision_from_verdict, downgrade


class _EntryPoint:
    def __init__(self, name: str, value: str, obj: object) -> None:
        self.name, self.value, self._obj = name, value, obj

    def load(self) -> object:
        return self._obj


@pytest.fixture
def fresh_registry():
    harnesses.reset()
    yield
    harnesses.reset()


def _with_entry_points(monkeypatch, *eps):
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda group: list(eps))


def _external():
    builtin = harnesses.get("claude")
    adapter = type("External", (), {})()
    for attr in (
        "display_name",
        "maturity",
        "capabilities",
        "events",
        "tool_map",
        "tool_impacts",
        "canonical_tool",
        "parse",
        "render",
        "install",
        "hooked_agents",
        "mcp_config_paths",
        "transcripts",
    ):
        setattr(adapter, attr, getattr(builtin, attr))
    adapter.name = "external"
    return adapter


def test_an_unknown_harness_is_refused_rather_than_guessed(fresh_registry):
    with pytest.raises(harnesses.UnknownHarness, match="probing"):
        harnesses.get("no-such-agent")


def test_builtins_load_without_installed_metadata(fresh_registry, monkeypatch):
    """Running from a checkout (`PYTHONPATH=src`) has no entry points installed."""
    _with_entry_points(monkeypatch)
    assert harnesses.known() == sorted(harnesses.BUILTIN)


def test_an_external_package_registers_through_the_entry_point(fresh_registry, monkeypatch):
    external = _external()
    _with_entry_points(monkeypatch, _EntryPoint("external", "pkg:ADAPTER", external))
    assert "external" in harnesses.known()
    assert harnesses.get("external") is external


def test_a_builtin_name_cannot_be_taken_over(fresh_registry, monkeypatch):
    impostor = _external()
    impostor.name = "claude"
    _with_entry_points(monkeypatch, _EntryPoint("claude", "evil:ADAPTER", impostor))
    assert harnesses.get("claude") is not impostor
    assert harnesses.registry()["claude"] is not impostor


def test_a_broken_entry_point_does_not_take_the_others_down(fresh_registry, monkeypatch):
    class Broken:
        name, value = "broken", "broken:ADAPTER"

        def load(self):
            raise ImportError("missing dependency")

    _with_entry_points(monkeypatch, Broken())
    assert harnesses.known() == sorted(harnesses.BUILTIN)


# ---------------------------------------------------------------------------
# Downgrades are explicit and recorded
# ---------------------------------------------------------------------------


def test_a_decision_the_event_can_honour_is_left_alone():
    caps = EventCaps(can_block=True, can_modify=True, can_ask=True, can_inject_context=True)
    for decision in (
        Decision.allow(),
        Decision.deny("r"),
        Decision.ask("r"),
        Decision.modify({"a": 1}),
        Decision.with_context("c"),
    ):
        assert downgrade(decision, caps) == decision


def test_a_rewrite_that_cannot_be_applied_is_refused_not_dropped():
    out = downgrade(Decision.modify({"a": 1}, "strip the secret"), EventCaps(can_block=True))
    assert out.kind == "deny"
    assert out.downgraded_from == "modify"
    assert out.reason == "strip the secret"
    assert out.arguments is None


def test_a_refusal_that_cannot_block_becomes_context_and_says_so():
    out = downgrade(Decision.deny("bad", ["r.one"]), EventCaps(can_inject_context=True))
    assert (out.kind, out.downgraded_from, out.rules) == ("context", "deny", ("r.one",))
    assert "cannot stop" in out.downgrade_note


def test_an_event_that_can_do_nothing_allows_and_records_it():
    out = downgrade(Decision.ask("x"), EventCaps())
    assert out.kind == "allow"
    assert out.downgraded_from == "ask"
    assert out.downgrade_note.count(";") == 1  # ask -> deny -> allow, both recorded


def test_an_absent_matrix_is_treated_as_unable_to_do_anything():
    assert downgrade(Decision.deny("x"), None).kind == "allow"


def test_escalate_and_abstain_verdicts_refuse_at_a_hook():
    event = harnesses.parse("claude", {"hook_event_name": "PreToolUse", "tool_name": "Bash"})
    for verdict in ("block", "escalate", "abstain"):
        assert decision_from_verdict({"verdict": verdict}, event).kind == "deny"


def test_a_rewrite_is_only_a_modify_on_a_tool_call_and_only_when_it_differs():
    pre = harnesses.parse(
        "claude",
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "x"}},
    )
    post = replace(pre, event="PostToolUse", kind="tool.post")
    reply = {"verdict": "allow", "rewrittenArguments": {"command": "y"}}
    assert decision_from_verdict(reply, pre).kind == "modify"
    assert decision_from_verdict(reply, post).kind == "allow"
    same = {"verdict": "allow", "rewrittenArguments": {"command": "x"}}
    assert decision_from_verdict(same, pre).kind == "allow"


def test_tool_names_are_canonical_and_mcp_tools_keep_their_server():
    adapter = harnesses.get("claude")
    assert adapter.canonical_tool("Bash") == "shell"
    assert adapter.canonical_tool("mcp__github__create_issue") == "mcp:github/create_issue"
    assert adapter.canonical_tool("SomethingNew") == "native:SomethingNew"
