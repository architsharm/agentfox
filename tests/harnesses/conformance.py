"""The harness conformance suite: every registered adapter, against its captured fixtures.

An adapter passes when, for each fixture in ``harnesses/<name>/fixtures/<event>.json``
(a hook payload captured from the real tool, never hand-written):

* the raw payload parses to the :class:`AgentEvent` recorded beside it in
  ``<event>.expected.json``;
* each :class:`Decision` there renders to the exact stdout, stderr and exit code, and
  each daemon verdict reply does too (the path ``agentfox hooks run`` takes);
* its capability matrix agrees with what ``render`` does: a decision the matrix says
  the event cannot honour comes back downgraded, and recorded as downgraded, and one
  it can honour does not;
* ``install`` is idempotent, merges into an existing settings file without losing
  anything in it, and refuses a file it cannot read.

Parametrised over ``agentfox.harnesses.all()``, so a new adapter is tested by being
registered. Nothing here names a harness.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from agentfox import harnesses
from agentfox.harnesses.base import (
    CANONICAL_TOOLS,
    EVENT_KINDS,
    Decision,
    HarnessAdapter,
    InstallError,
    downgrade,
)

REPO = Path(__file__).resolve().parents[2]
IMPACTS = {"read", "write", "high_impact", "irreversible"}

ADAPTERS = harnesses.all()


def _fixtures_dir(adapter: HarnessAdapter) -> Path:
    """``fixtures/`` beside the adapter's own module."""
    return Path(sys.modules[type(adapter).__module__].__file__).parent / "fixtures"


def _fixtures() -> list[tuple[HarnessAdapter, str]]:
    cases = []
    for adapter in ADAPTERS:
        for path in sorted(_fixtures_dir(adapter).glob("*.json")):
            if path.name.endswith(".expected.json") or path.name.startswith("install."):
                continue
            cases.append((adapter, path.name.removesuffix(".json")))
    return cases


FIXTURES = _fixtures()


def _ids(case: tuple[HarnessAdapter, str]) -> str:
    return f"{case[0].name}:{case[1]}"


def _load(adapter: HarnessAdapter, kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    folder = _fixtures_dir(adapter)
    raw = json.loads((folder / f"{kind}.json").read_text())
    expected = json.loads((folder / f"{kind}.expected.json").read_text())
    return raw, expected


by_adapter = pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
by_fixture = pytest.mark.parametrize("case", FIXTURES, ids=_ids)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_at_least_one_adapter_is_registered():
    assert ADAPTERS


@by_adapter
def test_the_adapter_implements_the_protocol(adapter):
    assert isinstance(adapter, HarnessAdapter)
    assert harnesses.get(adapter.name) is adapter
    assert adapter.maturity in ("stable", "incubating", "sandbox")


def test_every_builtin_is_registered_through_the_entry_point_group():
    """The built-ins use the mechanism an external package would: the fallback table
    and the declared entry points must agree."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    declared = project["project"]["entry-points"][harnesses.ENTRY_POINT_GROUP]
    assert declared == harnesses.BUILTIN


@by_adapter
def test_every_installed_event_has_a_captured_fixture(adapter):
    """An event with no captured payload is an event whose shape was guessed."""
    captured = {kind for a, kind in FIXTURES if a is adapter}
    assert set(adapter.events) <= captured, set(adapter.events) - captured
    assert set(adapter.events) <= set(EVENT_KINDS)


# ---------------------------------------------------------------------------
# Raw payload -> AgentEvent
# ---------------------------------------------------------------------------


@by_fixture
def test_the_captured_payload_parses_to_the_recorded_event(case):
    adapter, kind = case
    raw, expected = _load(adapter, kind)
    assert expected.get("source"), "every fixture says where it was captured"
    event = adapter.parse(raw)
    assert event.kind == kind
    assert event.harness == adapter.name
    for field, value in expected["event"].items():
        assert getattr(event, field) == value, field


# ---------------------------------------------------------------------------
# Decision -> exact stdout and exit code
# ---------------------------------------------------------------------------


@by_fixture
def test_each_decision_renders_exactly(case):
    adapter, kind = case
    raw, expected = _load(adapter, kind)
    event = adapter.parse(raw)
    assert expected["decisions"], "no decisions recorded for this fixture"
    for row in expected["decisions"]:
        out = adapter.render(Decision.from_json(row["decision"]), event)
        assert out.stdout == row["stdout"], row["decision"]
        assert out.stderr == row["stderr"], row["decision"]
        assert out.exit_code == row["exit_code"], row["decision"]
        assert out.decision.kind == row["applied"], row["decision"]
        assert out.decision.downgraded_from == row["downgraded_from"], row["decision"]


@by_fixture
def test_each_daemon_verdict_renders_exactly(case):
    """The path `agentfox hooks run` takes: the daemon's reply, then the adapter."""
    adapter, kind = case
    raw, expected = _load(adapter, kind)
    event = adapter.parse(raw)
    for row in expected.get("verdicts", []):
        out = harnesses.output(adapter.name, event, row["verdict"])
        assert out.stdout == row["stdout"], row["name"]
        assert out.stderr == row["stderr"], row["name"]
        assert out.exit_code == row["exit_code"], row["name"]


# ---------------------------------------------------------------------------
# The capability matrix agrees with render
# ---------------------------------------------------------------------------

_PROBES = {
    "allow": Decision.allow(),
    "deny": Decision.deny("conformance", ["conformance.rule"]),
    "ask": Decision.ask("conformance", ["conformance.rule"]),
    "modify": Decision.modify({"conformance": "rewritten"}),
    "context": Decision.with_context("conformance context"),
}
_ALLOWED_BY = {
    "deny": "can_block",
    "ask": "can_ask",
    "modify": "can_modify",
    "context": "can_inject_context",
}


@by_fixture
def test_the_capability_matrix_is_what_render_does(case):
    adapter, kind = case
    raw, _ = _load(adapter, kind)
    event = adapter.parse(raw)
    caps = adapter.capabilities[kind]
    allow_out = adapter.render(_PROBES["allow"], event)
    assert allow_out.decision.kind == "allow" and not allow_out.decision.downgraded

    for name, flag in _ALLOWED_BY.items():
        out = adapter.render(_PROBES[name], event)
        # render applies exactly the downgrade the matrix implies, and records it.
        assert out.decision.kind == downgrade(_PROBES[name], caps).kind, name
        if getattr(caps, flag):
            assert out.decision.kind == name and not out.decision.downgraded, name
            assert out.stdout != allow_out.stdout, f"{name} renders the same as allow"
        else:
            assert out.decision.kind != name, f"{name} applied where {flag} is false"
            assert out.decision.downgraded_from == name, name
            assert out.decision.downgrade_note, name

    if not caps.can_block and not caps.can_inject_context:
        # Nothing a refusal could do here: it must not pretend otherwise.
        assert adapter.render(_PROBES["deny"], event).stdout == allow_out.stdout


@by_adapter
def test_verified_rows_agree_with_the_matrix(adapter):
    """A row that says `block` on an event the matrix says cannot block (or the
    reverse) is the overclaim the capability table exists to prevent."""
    for kind, caps in adapter.capabilities.items():
        assert kind in adapter.events, kind
        if caps.verified is not None:
            assert (caps.verified.capability == "block") == caps.can_block, kind
            assert caps.verified.version, kind
        if caps.rewrite_verified is not None:
            assert caps.can_modify, kind


@by_adapter
def test_the_tool_map_speaks_the_canonical_vocabulary(adapter):
    for native, canonical in adapter.tool_map.items():
        assert canonical in CANONICAL_TOOLS or canonical.startswith("mcp:"), native
        assert adapter.canonical_tool(native) == canonical
    assert set(adapter.tool_impacts) <= set(adapter.tool_map)
    assert set(adapter.tool_impacts.values()) <= IMPACTS


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


def _existing(adapter: HarnessAdapter) -> dict[str, str]:
    """Optional ``fixtures/install.existing.json``: {relative path: file content} to
    pre-seed before installing, as a user's own settings would be."""
    path = _fixtures_dir(adapter) / "install.existing.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _contains(whole: Any, part: Any) -> bool:
    if isinstance(part, dict):
        return isinstance(whole, dict) and all(
            k in whole and _contains(whole[k], v) for k, v in part.items()
        )
    if isinstance(part, list):
        return isinstance(whole, list) and all(any(_contains(w, p) for w in whole) for p in part)
    return whole == part


@by_adapter
@pytest.mark.parametrize("scope", ["project", "local"])
def test_install_is_idempotent(adapter, scope, tmp_path):
    first = adapter.install(tmp_path, scope, agent="conformance-agent")
    assert first and all(change.action == "create" for change in first)
    for change in first:
        change.apply()
    again = adapter.install(tmp_path, scope, agent="conformance-agent")
    assert [change.action for change in again] == ["unchanged"] * len(again)
    assert [c.content for c in again] == [c.content for c in first]
    assert adapter.hooked_agents(tmp_path) == ["conformance-agent"]


@by_adapter
def test_install_merges_with_existing_settings(adapter, tmp_path):
    seeded = _existing(adapter)
    for rel, content in seeded.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content)
    changes = adapter.install(tmp_path, "project", agent="conformance-agent")
    for change in changes:
        rel = str(change.path.relative_to(tmp_path))
        if rel in seeded:
            assert change.action == "update"
            assert _contains(json.loads(change.content), json.loads(seeded[rel])), rel
        assert "conformance-agent" in change.content
        change.apply()
    # A second agent is added beside the first, not instead of it.
    for change in adapter.install(tmp_path, "project", agent="second-agent"):
        change.apply()
    assert adapter.hooked_agents(tmp_path) == ["conformance-agent", "second-agent"]


@by_adapter
def test_install_refuses_a_settings_file_it_cannot_read(adapter, tmp_path):
    for change in adapter.install(tmp_path, "project", agent="conformance-agent"):
        change.path.parent.mkdir(parents=True, exist_ok=True)
        change.path.write_text("{ not json")
    with pytest.raises(InstallError):
        adapter.install(tmp_path, "project", agent="conformance-agent")


# ---------------------------------------------------------------------------
# The rest of the interface
# ---------------------------------------------------------------------------


@by_adapter
def test_no_hooks_means_no_hooked_agents(adapter, tmp_path):
    assert adapter.hooked_agents(tmp_path) == []


@by_adapter
def test_mcp_config_paths_are_under_the_root(adapter, tmp_path):
    for path in adapter.mcp_config_paths(tmp_path):
        assert path.is_relative_to(tmp_path)


@by_adapter
def test_a_machine_without_the_harness_is_not_an_error(adapter, tmp_path):
    report = adapter.transcripts(tmp_path / "absent")
    assert report is None or report.found is False
