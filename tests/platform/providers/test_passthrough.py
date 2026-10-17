"""The inline proxy forwards the client's request; it does not rebuild it.

Agent frameworks depend on fields a rebuilt request drops: ``tools``, ``tool_choice``,
``response_format`` for structured outputs, and no ``temperature`` at all for models
that only accept the default.
"""

from __future__ import annotations

from typing import Any

import httpx

from agentfox.platform.providers.base import CompletionRequest
from agentfox.platform.providers.remote import AnthropicProvider, OpenAIProvider
from agentfox.runtime.enforcement.streaming import _merge_tool_calls

FIELDS = {
    "tools": [{"type": "function", "function": {"name": "cancel_flight", "parameters": {}}}],
    "tool_choice": "auto",
    "parallel_tool_calls": False,
    "response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
    "max_completion_tokens": 200,
}


class _Response:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


def _capture(monkeypatch, reply: dict[str, Any]) -> dict[str, Any]:
    sent: dict[str, Any] = {}

    def post(url, json, headers, timeout):  # noqa: A002 - httpx's own keyword
        sent.update(json)
        return _Response(reply)

    monkeypatch.setattr(httpx, "post", post)
    return sent


def test_openai_gets_the_clients_fields_and_no_invented_temperature(monkeypatch):
    sent = _capture(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    request = CompletionRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-5.2",
        passthrough=FIELDS,
        passthrough_protocol="openai",
    )
    OpenAIProvider().complete(request)
    assert {k: sent[k] for k in FIELDS} == FIELDS
    assert "temperature" not in sent and sent["model"] == "gpt-5.2"


def test_tool_calls_come_back(monkeypatch):
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "cancel_flight", "arguments": "{}"},
    }
    _capture(monkeypatch, {"choices": [{"message": {"content": None, "tool_calls": [call]}}]})
    out = OpenAIProvider().complete(
        CompletionRequest(messages=[], passthrough=FIELDS, passthrough_protocol="openai")
    )
    assert (
        out.tool_calls == [call]
        and out.to_openai("m")["choices"][0]["finish_reason"] == "tool_calls"
    )


def test_fields_for_another_protocol_are_not_forwarded(monkeypatch):
    sent = _capture(monkeypatch, {"content": [{"type": "text", "text": "ok"}]})
    AnthropicProvider().complete(
        CompletionRequest(
            messages=[{"role": "user", "content": "hi"}],
            passthrough=FIELDS,
            passthrough_protocol="openai",
        )
    )
    assert "response_format" not in sent and "temperature" in sent


def test_without_passthrough_the_old_defaults_hold(monkeypatch):
    sent = _capture(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    OpenAIProvider().complete(CompletionRequest(messages=[], temperature=0.0))
    assert sent["temperature"] == 0.0


def test_streamed_tool_call_fragments_assemble():
    calls: dict[int, dict] = {}
    _merge_tool_calls(
        calls, [{"index": 0, "id": "c1", "function": {"name": "cancel_", "arguments": '{"conf'}}]
    )
    _merge_tool_calls(
        calls, [{"index": 0, "function": {"name": "flight", "arguments": 'irmation": "X"}'}}]
    )
    assert calls[0]["id"] == "c1"
    assert calls[0]["function"] == {"name": "cancel_flight", "arguments": '{"confirmation": "X"}'}


def test_the_vendors_own_key_variable_is_accepted(monkeypatch):
    # Hosting dashboards tell people to set ANTHROPIC_API_KEY / OPENAI_API_KEY; a
    # gateway that only read AGENTFOX_* had a key configured and could not use it.
    from agentfox.platform.providers.remote import AnthropicProvider, OpenAIProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert AnthropicProvider()._api_key() == "sk-ant-test"
    assert OpenAIProvider()._api_key() == "sk-test"
