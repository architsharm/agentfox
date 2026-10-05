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

from agentfox.detection.taint import TaintTracker, _flatten
from agentfox.runtime.autoguard.shapes import _get, _plain

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


def _tool_calls_of(response: Any) -> list[_ToolCall]:
    """Every tool call in a buffered response, in order. Never raises."""
    try:
        choices = getattr(response, "choices", None)
        if choices:
            return [c for choice in choices for c in _calls_in_message(_get(choice, "message"))]
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


def _provenance_of(kwargs: dict[str, Any]) -> tuple[TaintTracker, list[str]]:
    """A taint tracker over this conversation, and the tools already called in it.

    The request carries the whole conversation — that is how a tool-calling client
    works — so the tracker is rebuilt from it on every call rather than kept between
    calls. A tool's result is marked ``tool:<tool>#<index>`` when the call that
    produced it can be found (so composed-escalation checks can name the producing
    tool), ``$.messages[i].content`` otherwise; both are ``tool_result`` taint. Roles
    otherwise follow `TaintTracker.mark_messages`.
    """
    tracker = TaintTracker()
    prior: list[str] = []
    produced_by: dict[str, str] = {}

    def mark_result(i: int, name: str | None, content: Any) -> None:
        path = f"tool:{name}#{i}" if name else f"$.messages[{i}].content"
        tracker.mark(path, "tool_result", _flatten(_plain(content)))

    for i, raw in enumerate(kwargs.get("messages") or []):
        message = _plain(raw)
        for call in _calls_in_message(message):
            prior.append(call.name)
            if call.call_id:
                produced_by[str(call.call_id)] = call.name
        role = str(_get(message, "role") or "user")
        content = _get(message, "content")
        if role in ("tool", "function"):
            call_id = _get(message, "tool_call_id")
            mark_result(i, produced_by.get(str(call_id)) or _get(message, "name"), content)
            continue
        if isinstance(content, list):
            rest = []
            for block in (_plain(b) for b in content):
                if _get(block, "type") == "tool_result":
                    call_id = _get(block, "tool_use_id")
                    mark_result(i, produced_by.get(str(call_id)), _get(block, "content"))
                else:
                    rest.append(block)
            content = rest
        source = {"system": "none", "developer": "none", "assistant": "none"}.get(role, "user")
        tracker.mark(f"$.messages[{i}].content", source, _flatten(content))
    return tracker, prior
