"""The attack test never reads as a pass it isn't.

A walk-through on a fresh project (2026-11-08) found the map's panel showing a green
"0/26, 0/34, 0/20, 0/37" for a test where the agent couldn't even be imported, raw
provider errors, a re-run blanking the last numbers, and the OpenAI Agents SDK's own
trace export printing ``[non-fatal] Tracing client error 400`` into the progress output.
"""

from __future__ import annotations

import datetime as dt
import sys
import types

from agentfox.capabilities.onboarding import runner, service
from tests.capabilities.onboarding.test_onboarding_flow import _connect_watch

NOW = dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.UTC)
STRUCTURE = {
    "tools": [
        {"name": "get_flight", "risk": "read_only", "agentId": "a"},
        {"name": "update_seat", "risk": "high", "agentId": "a"},
    ],
    "agents": [{"id": "a", "name": "Seat Booking Agent"}],
    "systems": [],
}


def _not_run(i: int, reason: str, kind: str = "jailbreak") -> dict:
    return {
        "id": f"{kind}-{i:03d}",
        "type": kind,
        "outcome": "not_run",
        "gotThrough": False,
        "reason": reason,
        "sentence": reason,
    }


def test_an_agent_that_cant_be_imported_is_explained_with_the_fix():
    said = runner.explain_not_run(
        "Not run: couldn't load main.triage_agent: ModuleNotFoundError: No module named 'examples'"
    )
    assert "couldn't import your agent (main.triage_agent)" in said
    assert "'examples'" in said and "Install your agent's dependencies" in said
    other = runner.explain_not_run("Not run: couldn't build x: ValueError: <obj at 0x10>")
    assert "0x10" not in other and "Check that it imports on its own" in other


def test_a_run_where_nothing_ran_fails_naming_the_agent_not_a_skipped_set():
    run = service.new_run("before", STRUCTURE, NOW)
    load = "Not run: couldn't load main.agent: ModuleNotFoundError: No module named 'examples'"
    results = [
        # A set that doesn't apply is reported first; the reason that matters is the agent.
        _not_run(0, "Not run: it needs a tool that reads records, and this agent has none."),
        *(_not_run(i, load) for i in range(1, 6)),
    ]
    run = service.add_results(run, results, done=True, error=None, now=NOW)
    assert run["status"] == "failed"
    assert run["error"].startswith("No attack could be run, so this test says nothing")
    assert "'examples'" in run["error"] and "needs a tool" not in run["error"]
    shown = service.to_test_run(run, runner_connected=True, now=NOW)
    # Nothing ran: no verdict anywhere, and never a clean result.
    assert shown["ran"] == 0 and shown["clean"] is False and shown["notRun"] == 6


def test_errored_attacks_are_counted_and_explained_in_a_sentence():
    run = service.new_run("before", STRUCTURE, NOW)
    raw = "openai.AuthenticationError: Error code: 401 - {'error': {'code': 'invalid_api_key'}}"
    results = [
        {"id": f"jailbreak-{i:03d}", "type": "jailbreak", "outcome": "resisted"} for i in range(6)
    ] + [
        {"id": f"jailbreak-{i:03d}", "type": "jailbreak", "outcome": "errored", "error": raw}
        for i in range(6, 8)
    ]
    run = service.add_results(run, results, done=True, error=None, now=NOW)
    shown = service.to_test_run(run, runner_connected=True, now=NOW)
    assert shown["status"] == "done" and shown["clean"] is False
    assert shown["ran"] == 6 and shown["errored"] == 2
    assert "API key was rejected" in shown["errorSummary"]
    assert "Error code" not in shown["errorSummary"]


def test_a_rerun_keeps_the_last_finished_numbers(client):
    me, runner_headers, _send = _connect_watch(client)
    first = client.post("/api/onboarding/runner/poll", headers=runner_headers).json()["job"]
    client.post(
        f"/api/onboarding/runner/runs/{first['runId']}/results",
        json={
            "results": [{"id": "a1", "type": "prompt_injection", "outcome": "got_through"}],
            "done": True,
        },
        headers=runner_headers,
    )
    tests = client.get("/api/onboarding/projects/watch/tests", headers=me).json()
    assert tests["firstPrevious"] is None  # nothing running: nothing to keep

    again = client.post("/api/onboarding/projects/watch/tests", headers=me).json()
    tests = client.get("/api/onboarding/projects/watch/tests", headers=me).json()
    assert tests["first"]["id"] == again["id"] and tests["first"]["status"] == "running"
    assert tests["firstPrevious"]["id"] == first["runId"]
    assert tests["firstPrevious"]["gotThrough"] == 1


class _Provider:
    """The Agents SDK's DefaultTraceProvider, as far as the runner touches it."""

    def __init__(self) -> None:
        self._manual_disabled = None
        self.disabled = False

    def set_disabled(self, disabled: bool) -> None:
        self._manual_disabled = disabled
        self._refresh_disabled_flag()

    def _refresh_disabled_flag(self) -> None:
        self.disabled = bool(self._manual_disabled)


def test_the_sdks_own_tracing_is_off_while_a_suite_runs(monkeypatch):
    provider = _Provider()
    tracing = types.ModuleType("agents.tracing")
    tracing.get_trace_provider = lambda: provider  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agents.tracing", tracing)
    with runner.faking():
        assert provider.disabled is True
    # Put back as the user had it.
    assert provider.disabled is False and provider._manual_disabled is None

    provider.set_disabled(True)  # the user turned it off themselves: it stays off
    with runner.faking():
        assert provider.disabled is True
    assert provider.disabled is True and provider._manual_disabled is True
