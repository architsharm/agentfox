"""`agentfox.auto()` against the real `openai` SDK's Responses API and the real OpenAI
Agents SDK, over a mock HTTP transport (no network, no key).

Skipped where they are not installed (the dev environment does not install them);
run with ``pip install openai openai-agents``. These hold the shapes the fakes in
`test_autoguard_responses` assume to the SDKs themselves: `with_streaming_response`,
`responses.stream()`, and an Agents SDK run, buffered and streamed, whose tool call
is decided before the SDK runs the tool.
"""

from __future__ import annotations

import json

import pytest

openai = pytest.importorskip("openai")
pytest.importorskip("openai.resources.responses")
httpx = pytest.importorskip("httpx")

from agentfox.core.models import Decision  # noqa: E402
from agentfox.frameworks.autoguard import Blocked, auto, off, state  # noqa: E402

CONFIRMATION = "ABC123"


def _response(*items: dict, response_id: str = "resp_1") -> dict:
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o-mini",
        "status": "completed",
        "output": list(items),
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 8,
            "total_tokens": 28,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _message(text: str) -> dict:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _function_call(name: str, arguments: dict) -> dict:
    return {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": name,
        "arguments": json.dumps(arguments),
        "status": "completed",
    }


def _sse(response: dict) -> str:
    """The event stream the API sends for `response`, as the SDK's accumulator
    expects it: each item added, its text streamed, done, then completed."""
    events: list[dict] = [
        {
            "type": "response.created",
            "response": {**response, "output": [], "status": "in_progress"},
        }
    ]
    for index, item in enumerate(response["output"]):
        opened = {**item, "status": "in_progress"}
        if item["type"] == "message":
            opened["content"] = []
        else:
            opened["arguments"] = ""
        events.append({"type": "response.output_item.added", "output_index": index, "item": opened})
        if item["type"] == "message":
            part = {"type": "output_text", "text": "", "annotations": []}
            events.append(
                {
                    "type": "response.content_part.added",
                    "item_id": item["id"],
                    "output_index": index,
                    "content_index": 0,
                    "part": part,
                }
            )
            events.append(
                {
                    "type": "response.output_text.delta",
                    "item_id": item["id"],
                    "output_index": index,
                    "content_index": 0,
                    "delta": item["content"][0]["text"],
                    "logprobs": [],
                }
            )
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": response})
    return "".join(
        f"event: {e['type']}\ndata: {json.dumps({**e, 'sequence_number': i})}\n\n"
        for i, e in enumerate(events)
    )


class _Server:
    """Answers each POST /responses with the next scripted response, streamed when
    the request asks for it, and keeps the request bodies."""

    def __init__(self, *responses: dict) -> None:
        self.script = list(responses)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        response = self.script.pop(0)
        if body.get("stream"):
            return httpx.Response(
                200, text=_sse(response), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=response)


@pytest.fixture(autouse=True)
def _reset():
    yield
    off()


def _clients(server: _Server):
    sync = openai.OpenAI(
        api_key="sk-test", http_client=httpx.Client(transport=httpx.MockTransport(server))
    )
    async_ = openai.AsyncOpenAI(
        api_key="sk-test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(server))
    )
    return sync, async_


def _tool_keys() -> list[str]:
    from agentfox.core.db import session_scope

    with session_scope() as session:
        return [d.tool_key for d in session.query(Decision).filter_by(surface="tool_args").all()]


def test_every_responses_entry_point_is_governed():
    reply = _response(_message("Hello"), _function_call("send_email", {"to": "a@b.co"}))
    server = _Server(*([reply] * 5))
    client, _async = _clients(server)
    governed = auto(agent="sdk-shapes", quiet=True)

    assert client.responses.create(model="gpt-4o-mini", input="hi").output_text == "Hello"
    for _event in client.responses.create(model="gpt-4o-mini", input="hi", stream=True):
        pass
    with client.responses.stream(model="gpt-4o-mini", input="hi") as stream:
        for _event in stream:
            pass
    with client.responses.with_streaming_response.create(model="gpt-4o-mini", input="hi") as raw:
        raw.parse()
    client.responses.with_raw_response.create(model="gpt-4o-mini", input="hi").parse()
    assert governed.calls_governed == 5
    assert _tool_keys() == ["send_email"] * 5


async def test_async_with_streaming_response_is_governed():
    server = _Server(_response(_function_call("send_email", {"to": "a@b.co"})))
    _sync, client = _clients(server)
    governed = auto(agent="sdk-shapes", quiet=True)
    async with client.responses.with_streaming_response.create(
        model="gpt-4o-mini", input="hi", stream=True
    ) as raw:
        async for _event in await raw.parse():
            pass
    assert governed.calls_governed == 1
    assert _tool_keys() == ["send_email"]


# ---------------------------------------------------------------------------
# The OpenAI Agents SDK, with nothing but auto()
# ---------------------------------------------------------------------------


def _seat_agent(client):
    agents = pytest.importorskip("agents")

    @agents.function_tool
    def update_seat(confirmation_number: str, new_seat: str) -> str:
        """Update the seat for a given confirmation number."""
        return f"Updated seat to {new_seat} for confirmation number {confirmation_number}"

    model = agents.OpenAIResponsesModel(model="gpt-4o-mini", openai_client=client)
    return agents, agents.Agent(name="Seat Booking Agent", model=model, tools=[update_seat])


def _seat_turns() -> tuple[dict, dict]:
    return (
        _response(
            _function_call("update_seat", {"confirmation_number": CONFIRMATION, "new_seat": "12A"})
        ),
        _response(_message("Your seat is now 12A."), response_id="resp_2"),
    )


async def test_an_agents_sdk_run_is_governed_with_its_tool_call():
    server = _Server(*_seat_turns())
    _sync, client = _clients(server)
    governed = auto(agent="customer-service", quiet=True)
    agents, agent = _seat_agent(client)

    result = await agents.Runner.run(agent, f"Move booking {CONFIRMATION} to seat 12A")
    assert result.final_output == "Your seat is now 12A."
    assert governed.calls_governed == 2
    assert _tool_keys() == ["update_seat"]

    from agentfox.core.db import session_scope

    with session_scope() as session:
        decision = session.query(Decision).filter_by(surface="tool_args").one()
        # The confirmation number came from the user's own message.
        assert decision.taint_summary_json["arguments"]["confirmation_number"] == "user"
        # The tool's output went back to the model and was checked as a tool result.
        assert session.query(Decision).filter_by(surface="tool_result").count() >= 1


async def test_a_streamed_agents_sdk_run_is_governed():
    server = _Server(*_seat_turns())
    _sync, client = _clients(server)
    governed = auto(agent="customer-service", quiet=True)
    agents, agent = _seat_agent(client)

    result = agents.Runner.run_streamed(agent, f"Move booking {CONFIRMATION} to seat 12A")
    async for _event in result.stream_events():
        pass
    assert result.final_output == "Your seat is now 12A."
    assert governed.calls_governed == 2
    assert _tool_keys() == ["update_seat"]


async def test_strict_mode_stops_the_tool_before_the_sdk_runs_it():
    server = _Server(*_seat_turns())
    _sync, client = _clients(server)
    auto(agent="customer-service", mode="enforce", quiet=True)  # no grant: default-deny
    agents, agent = _seat_agent(client)
    with pytest.raises(Blocked, match="update_seat"):
        await agents.Runner.run(agent, f"Move booking {CONFIRMATION} to seat 12A")
    assert len(server.requests) == 1, "the tool never ran, so the model was never re-asked"
    assert state().calls_blocked == 1


async def test_an_agents_sdk_handoff_is_recorded_not_refused():
    """The customer_service example's shape: triage hands off to seat booking, with
    an agent that already holds a grant (so default-deny is on)."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding, Span
    from agentfox.platform.identity.service import ensure_identity, grant_capability
    from agentfox.platform.registry.service import register_agent

    agents, seat_agent = _seat_agent(None)
    with session_scope() as session:
        agent = register_agent(session, "customer-service", name="customer-service")
        grant_capability(session, ensure_identity(session, agent), "update_seat")
    server = _Server(
        _response(_function_call("transfer_to_seat_booking_agent", {})),
        _response(_message("Which seat would you like?"), response_id="resp_2"),
    )
    _sync, client = _clients(server)
    model = agents.OpenAIResponsesModel(model="gpt-4o-mini", openai_client=client)
    seat_agent.model = model
    triage = agents.Agent(
        name="Triage Agent",
        model=model,
        handoffs=[
            agents.handoff(agent=seat_agent, tool_name_override="transfer_to_seat_booking_agent")
        ],
    )
    governed = auto(agent="customer-service", quiet=True)

    result = await agents.Runner.run(triage, "I want to change my seat")
    assert result.final_output == "Which seat would you like?"
    assert governed.calls_blocked == 0
    assert _tool_keys() == []
    with session_scope() as session:
        assert session.query(Finding).filter(Finding.type == "containment").count() == 0
        spans = session.query(Span).filter(Span.kind == "subagent").all()
        assert [s.name for s in spans] == ["Seat Booking Agent"]


async def test_an_agent_used_as_a_tool_is_recorded_not_refused():
    """openai-agents-python's agents_as_tools examples: the orchestrator calls its own
    sub-agent through `agent.as_tool(...)`, with an agent that holds a grant (so
    default-deny is on)."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding, Span
    from agentfox.platform.identity.service import ensure_identity, grant_capability
    from agentfox.platform.registry.service import register_agent

    agents = pytest.importorskip("agents")
    with session_scope() as session:
        agent = register_agent(session, "orchestrator", name="orchestrator")
        grant_capability(session, ensure_identity(session, agent), "get_user_name")
    governed = auto(agent="orchestrator", quiet=True)
    server = _Server(
        _response(_function_call("respond_spanish", {"input": "good morning"})),
        _response(_message("Buenos días"), response_id="resp_2"),
        _response(_message("Spanish: Buenos días"), response_id="resp_3"),
    )
    _sync, client = _clients(server)
    model = agents.OpenAIResponsesModel(model="gpt-4o-mini", openai_client=client)
    spanish = agents.Agent(name="spanish_agent", instructions="Spanish.", model=model)
    orchestrator = agents.Agent(
        name="orchestrator",
        model=model,
        tools=[spanish.as_tool(tool_name="respond_spanish", tool_description="Spanish")],
    )

    result = await agents.Runner.run(orchestrator, "Say good morning in Spanish")
    assert result.final_output == "Spanish: Buenos días"
    assert governed.calls_blocked == 0
    assert _tool_keys() == []
    with session_scope() as session:
        assert session.query(Finding).filter(Finding.type == "containment").count() == 0
        spans = session.query(Span).filter(Span.kind == "subagent").all()
        assert [(s.name, s.attributes_json["agentfox.handoff.relation"]) for s in spans] == [
            ("spanish_agent", "as_tool")
        ]
