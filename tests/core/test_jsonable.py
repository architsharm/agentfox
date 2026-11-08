"""What an agent framework hands a tool goes over the wire as JSON.

The dashboard's attack test on a LangGraph swarm errored on 28 attacks and 4 normal
requests with "TypeError: Object of type HumanMessage is not JSON serializable": a
hand-off tool's arguments carry the graph's state, messages included, and the check
was posted with them as they were. `agentfox.auto()` in account mode crashed the app
the same way. LangChain is not a dependency here, so its message shape is built to
match: a pydantic-like object from a ``langchain_core`` module with ``type`` and
``content``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

import httpx

from agentfox.core.jsonable import jsonable


class _Message:
    """`langchain_core.messages.BaseMessage` as far as `jsonable` reads it."""

    def __init__(self, type_: str, content, **extra):
        self.type, self.content = type_, content
        for k, v in extra.items():
            setattr(self, k, v)

    def model_dump(self):  # what pydantic would give: the noisy shape, not a chat one
        return {"type": self.type, "content": self.content, "additional_kwargs": {}}


_Message.__module__ = "langchain_core.messages.human"


class _Send:
    __slots__ = ("node", "arg")

    def __init__(self, node, arg):
        self.node, self.arg = node, arg


_Send.__module__ = "langgraph.types"


@dataclasses.dataclass
class _Command:
    goto: str
    update: dict


def test_langchain_messages_become_chat_messages():
    state = {
        "messages": [
            _Message("system", "be nice"),
            _Message("human", "hi"),
            _Message(
                "ai", "", tool_calls=[{"name": "transfer_to_planner", "args": {}, "id": "c1"}]
            ),
            _Message("tool", "ok", tool_call_id="c1", name="transfer_to_planner"),
            _Message("AIMessageChunk", "partial"),
        ]
    }
    out = jsonable(state)
    json.dumps(out)  # the point: no TypeError
    assert out["messages"] == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "transfer_to_planner", "args": {}}],
        },
        {"role": "tool", "content": "ok", "name": "transfer_to_planner", "tool_call_id": "c1"},
        {"role": "assistant", "content": "partial"},
    ]


def test_framework_objects_dates_and_unknowns_never_raise():
    value = {
        "send": _Send("planner", {"m": _Message("human", "x")}),
        "cmd": _Command(goto="planner", update={"messages": [_Message("human", "y")]}),
        "at": dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.UTC),
        "raw": b"bytes",
        "nan": float("nan"),
        "odd": object(),
        "pair": (1, {2}),
    }
    out = jsonable(value)
    json.dumps(out)
    assert out["send"] == {"node": "planner", "arg": {"m": {"role": "user", "content": "x"}}}
    assert out["cmd"]["update"]["messages"] == [{"role": "user", "content": "y"}]
    assert out["at"] == "2026-11-08T12:00:00+00:00" and out["raw"] == "bytes"
    assert out["nan"] is None and isinstance(out["odd"], str) and out["pair"] == [1, [2]]


def test_a_cycle_is_cut_not_followed():
    loop: dict = {}
    loop["self"] = loop
    json.dumps(jsonable(loop))


def _capture() -> tuple[list[dict], httpx.Client]:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"verdict": "allow"})

    return seen, httpx.Client(transport=httpx.MockTransport(handler))


def test_auto_account_mode_posts_a_langgraph_tools_state():
    from agentfox.frameworks.autoguard.remote import Remote

    seen, client = _capture()
    remote = Remote(url="http://gw", key="k")
    remote._client = client
    remote.post(
        "/v1/guard/tool_call",
        {"tool": "lookup", "arguments": {"state": {"messages": [_Message("human", "hi")]}}},
    )
    assert seen[0]["arguments"]["state"]["messages"] == [{"role": "user", "content": "hi"}]


def test_the_attack_tests_checks_post_the_same():
    from agentfox.capabilities.onboarding.client import _Api

    seen, client = _capture()
    api = _Api("http://gw", "k")
    api.http = httpx.Client(base_url="http://gw", transport=client._transport)
    api.post("/runner/runs/r1/guard", {"arguments": {"m": [_Message("human", "hi")]}})
    assert seen[0]["arguments"]["m"] == [{"role": "user", "content": "hi"}]


def test_a_recorded_tool_call_holds_plain_arguments():
    """The call is reported with the run's results: its arguments are plain too."""
    from agentfox.capabilities.onboarding.attacks import Attack
    from agentfox.capabilities.onboarding.runner import _CTX, Verdict, _record, _Run

    checked: list[dict] = []

    def guard(surface, payload):
        checked.append(payload)
        return Verdict("allow")

    attack = Attack(
        id="a1",
        type="prompt_injection",
        message="x",
        forbidden=[],
        canary=None,
        agent_id="ag-1",
        agent_name="planner",
    )
    run = _Run(attack, {}, guard)
    token = _CTX.set(run)
    try:
        _record("transfer_to_planner", {"state": {"messages": [_Message("human", "hi")]}})
    finally:
        _CTX.reset(token)
    json.dumps(run.calls)
    json.dumps(checked)
    assert run.calls[0]["args"]["state"]["messages"][0] == {"role": "user", "content": "hi"}
