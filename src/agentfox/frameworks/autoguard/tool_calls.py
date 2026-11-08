"""The tool calls a governed response asks for, read in either provider's shape, and
the provenance of the conversation that led to them.

A model that calls tools does not act: it returns a request to act, and the
caller's own code runs it. That request is the one moment a patched client
library can stand between an injected instruction and its effect — so every tool
call in a governed response goes through `Enforcer.guard_tool_call`, the same path
`AgentSession.guard_tool` and MCP governance take, before the response is handed
back. Found by a fresh-user run: a support bot whose four tools ran 25 calls, among
them `send_email(to=attacker, body=<customer record>)`, and not one was recorded.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from agentfox.capabilities.detection.taint import TaintTracker
from agentfox.frameworks.autoguard.shapes import _get, _plain

log = logging.getLogger("agentfox.runtime.autoguard")


@dataclass
class _ToolCall:
    """One tool call the model asked for, in either provider's shape."""

    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


def _arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments as a dict. OpenAI sends a JSON string, Anthropic an object.

    Unparseable arguments are kept as ``{"_raw": ...}`` rather than dropped: a
    model can be talked into emitting malformed JSON, and a call whose arguments we
    could not read must not be a call nothing looked at.
    """
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            raw = json.loads(raw)
        except ValueError:
            return {"_raw": raw}
    if raw is None:
        return {}
    raw = _plain(raw)
    return raw if isinstance(raw, dict) else {"_value": raw}


def _calls_in_message(message: Any) -> list[_ToolCall]:
    """The tool calls one assistant message carries: OpenAI ``tool_calls`` (and the
    legacy single ``function_call``), Anthropic ``tool_use`` content blocks, and
    LangChain's ``AIMessage.tool_calls`` (``{"name", "args", "id"}``)."""
    calls: list[_ToolCall] = []
    for call in _get(message, "tool_calls") or []:
        function = _get(call, "function")
        if function is not None:
            name = _get(function, "name")
            raw = _get(function, "arguments")
        else:  # LangChain
            name = _get(call, "name")
            raw = _get(call, "args")
        if name:
            calls.append(_ToolCall(str(name), _arguments(raw), _get(call, "id")))
    legacy = _get(message, "function_call")
    if legacy is not None and _get(legacy, "name"):
        calls.append(_ToolCall(str(_get(legacy, "name")), _arguments(_get(legacy, "arguments"))))
    content = _get(message, "content")
    if isinstance(content, list):
        for block in content:
            if _get(block, "type") == "tool_use" and _get(block, "name"):
                calls.append(
                    _ToolCall(
                        str(_get(block, "name")),
                        _arguments(_get(block, "input")),
                        _get(block, "id"),
                    )
                )
    return calls


#: Responses API output items the caller's own code acts on: a function tool, a
#: custom (free-form) tool, and the computer / shell / patch actions the app executes.
#: Each is a tool call to authorise before the response is handed back. Item type ->
#: the field holding its arguments.
_CLIENT_ITEMS = {
    "function_call": "arguments",
    "custom_tool_call": "input",
    "computer_call": "action",
    "local_shell_call": "action",
    "shell_call": "action",
    "apply_patch_call": "operation",
}

#: Responses API output items for tools OpenAI runs itself. They have already run
#: when the response arrives, so they are recorded, never authorised.
_HOSTED_ITEMS = {
    "web_search_call": "web_search",
    "file_search_call": "file_search",
    "code_interpreter_call": "code_interpreter",
    "image_generation_call": "image_generation",
    "mcp_call": "mcp",
    "tool_search_call": "tool_search",
}


def _responses_calls(items: list[Any]) -> list[_ToolCall]:
    """The client-run tool calls among a Responses API response's output items."""
    calls: list[_ToolCall] = []
    for item in items:
        kind = str(_get(item, "type"))
        field = _CLIENT_ITEMS.get(kind)
        if field is None:
            continue
        if kind in ("function_call", "custom_tool_call"):
            name = _get(item, "name")
        else:  # computer / shell / patch actions are named by what they are
            name = kind.removesuffix("_call")
        if not name:
            continue
        raw = _get(item, field)
        if kind == "custom_tool_call" and isinstance(raw, str):
            arguments = {"input": raw}  # free-form text, not JSON
        else:
            arguments = _arguments(raw)
        calls.append(_ToolCall(str(name), arguments, _get(item, "call_id") or _get(item, "id")))
    return calls


@dataclass
class _HostedCall:
    """A tool OpenAI ran on the model's behalf (web search, file search, code
    interpreter, hosted MCP, ...): recorded from the response, never stopped."""

    name: str
    detail: dict[str, Any]
    status: str | None = None


def _hosted_calls_of(response: Any) -> list[_HostedCall]:
    """The hosted-tool items in a Responses API response. Never raises."""
    try:
        if getattr(response, "choices", None) is not None:
            return []
        items = _get(response, "output")
        if not isinstance(items, list):
            return []
        hosted: list[_HostedCall] = []
        for item in items:
            name = _HOSTED_ITEMS.get(str(_get(item, "type")))
            if name is None:
                continue
            plain = _plain(item)
            detail: dict[str, Any] = {}
            if isinstance(plain, dict):
                # What it did, not what it returned: the query, the server and tool,
                # the code. Results can be large and are the model's to read.
                for key in ("action", "queries", "server_label", "name", "arguments", "code"):
                    if plain.get(key) not in (None, "", [], {}):
                        detail[key] = plain[key]
            if name == "mcp" and _get(item, "server_label"):
                name = f"mcp:{_get(item, 'server_label')}.{_get(item, 'name') or ''}".rstrip(".")
            hosted.append(_HostedCall(name, detail, _get(item, "status")))
        return hosted
    except Exception as exc:  # pragma: no cover - defensive against SDK shape drift
        log.warning("agentfox: could not read hosted tools from the response: %s", exc)
        return []


def _tool_calls_of(response: Any) -> list[_ToolCall]:
    """Every tool call in a buffered response, in order. Never raises."""
    try:
        choices = getattr(response, "choices", None)
        if choices:
            return [c for choice in choices for c in _calls_in_message(_get(choice, "message"))]
        items = _get(response, "output")
        if isinstance(items, list):  # the Responses API
            return _responses_calls(items)
        return _calls_in_message(response)
    except Exception as exc:  # pragma: no cover - defensive against SDK shape drift
        log.warning("agentfox: could not read tool calls from the response: %s", exc)
        return []


def _tool_specs(kwargs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Tool name -> descriptor (``description``, ``inputSchema``) from the request's
    ``tools``, in OpenAI's ``{"type": "function", "function": {...}}`` shape or
    Anthropic's flat one. The description is what impact inference reads."""
    specs: dict[str, dict[str, Any]] = {}
    for raw in kwargs.get("tools") or []:
        tool = _plain(raw)
        function = _get(tool, "function") or tool
        name = _get(function, "name")
        if not name:
            continue
        specs[str(name)] = {
            "description": str(_get(function, "description") or ""),
            "inputSchema": _get(function, "parameters") or _get(function, "input_schema") or {},
        }
    return specs


def _provenance_of(
    kwargs: dict[str, Any], declared_for: Any = None
) -> tuple[TaintTracker, list[str]]:
    """A taint tracker over this conversation, and the tools already called in it.

    The request carries the whole conversation — that is how a tool-calling client
    works — so the tracker is rebuilt from it on every call rather than kept between
    calls. The marking is `TaintTracker.mark_messages`, the one the gateway uses, so
    the SDK and the HTTP proxy cannot disagree about where a value came from: a
    tool's result is ``tool_result`` taint (``tool:<tool>#<index>`` when the call
    that produced it can be found), Anthropic ``tool_result`` blocks included.

    ``declared_for(messages)`` may return index -> source for messages whose
    provenance is known better than their role says: a framework that quotes a
    tool's result back to its model inside its own message (CrewAI's
    "Observation:") is declared ``tool_result`` there.
    """
    tracker = TaintTracker()
    messages = [_plain_message(m) for m in kwargs.get("messages") or []]
    declared = declared_for(messages) if declared_for is not None else None
    prior = tracker.mark_messages(messages, declared or None)
    return tracker, prior


def _plain_message(raw: Any) -> Any:
    """A message, its content blocks and its tool calls as plain dicts: a loop mixes
    the SDK's own objects into the dicts it builds."""
    message = _plain(raw)
    if not isinstance(message, dict):
        return message
    out = dict(message)
    if isinstance(out.get("content"), list):
        out["content"] = [_plain(b) for b in out["content"]]
    if isinstance(out.get("tool_calls"), list):
        out["tool_calls"] = [_plain(c) for c in out["tool_calls"]]
    return out
