"""Any value an agent framework hands us, as plain JSON: what goes over the wire.

A tool's arguments, a conversation or a framework's state carry the framework's own
objects: LangChain and LangGraph messages (``HumanMessage``, ``AIMessage`` with its
``tool_calls``, ``ToolMessage``), pydantic models, dataclasses, dates. ``json`` refuses
them ("Object of type HumanMessage is not JSON serializable"), and a check that never
reached the server is a check that didn't happen. Everything that posts what an agent
did to an AgentFox server (the attack test's checks and results, `agentfox.auto()` in
account mode) sends ``jsonable(body)`` instead of the body.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import uuid
from collections.abc import Mapping
from decimal import Decimal
from pathlib import PurePath
from typing import Any

#: A LangChain message's ``type`` -> the chat role the guards read.
_ROLES = {
    "human": "user",
    "HumanMessageChunk": "user",
    "ai": "assistant",
    "AIMessageChunk": "assistant",
    "system": "system",
    "SystemMessageChunk": "system",
    "tool": "tool",
    "ToolMessageChunk": "tool",
    "function": "function",
    "FunctionMessageChunk": "function",
}

#: Deep enough for any real message or state; a cycle or a pathological object
#: stops here as its text instead of recursing forever.
_MAX_DEPTH = 24


def jsonable(value: Any) -> Any:
    """``value`` with every framework object replaced by plain JSON values.

    A LangChain/LangGraph message becomes ``{"role", "content"}`` plus its
    ``name``, ``tool_calls`` and ``tool_call_id`` when it has them, the shape the
    chat-completions APIs and AgentFox's guards read. A pydantic model becomes what it
    dumps to, a dataclass its fields, a date its ISO text, and anything else its
    ``str``: never an exception.
    """
    return _plain(value, 0)


def _plain(value: Any, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if depth >= _MAX_DEPTH:
        return _text(value)
    if isinstance(value, Mapping):
        return {str(k): _plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v, depth + 1) for v in value]
    message = _message(value, depth)
    if message is not None:
        return message
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return _plain(value.value, depth + 1)
    if isinstance(value, (uuid.UUID, PurePath)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump) and not isinstance(value, type):
        try:
            return _plain(dump(), depth + 1)
        except Exception:  # noqa: BLE001 - a model that can't dump is sent as text
            return _text(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _plain(getattr(value, f.name, None), depth + 1)
            for f in dataclasses.fields(value)
        }
    fields = _framework_fields(value)
    if fields is not None:
        return {k: _plain(v, depth + 1) for k, v in fields.items()}
    return _text(value)


def _framework_fields(value: Any) -> dict[str, Any] | None:
    """A LangChain/LangGraph object that is neither a model nor a dataclass (LangGraph's
    ``Send``): its public attributes, so a message inside it is sent as one."""
    if not (type(value).__module__ or "").startswith(("langchain", "langgraph")):
        return None
    names = [n for c in type(value).__mro__ for n in getattr(c, "__slots__", ())]
    names += list(getattr(value, "__dict__", {}))
    fields = {n: getattr(value, n, None) for n in dict.fromkeys(names) if not n.startswith("_")}
    fields = {n: v for n, v in fields.items() if not callable(v)}
    return fields or None


def _is_message(value: Any) -> bool:
    """A LangChain message (``langchain_core.messages.BaseMessage``), without importing
    LangChain: a ``type`` string and ``content``, from a langchain module."""
    module = type(value).__module__ or ""
    return (
        module.startswith(("langchain", "langgraph"))
        and isinstance(getattr(value, "type", None), str)
        and hasattr(value, "content")
    )


def _message(value: Any, depth: int) -> dict[str, Any] | None:
    if not _is_message(value):
        return None
    kind = value.type
    role = _ROLES.get(kind) or (getattr(value, "role", None) if kind == "chat" else None) or kind
    out: dict[str, Any] = {"role": str(role), "content": _plain(value.content, depth + 1)}
    name = getattr(value, "name", None)
    if name:
        out["name"] = str(name)
    calls = getattr(value, "tool_calls", None)
    if calls:
        out["tool_calls"] = [
            {
                "id": _get(c, "id"),
                "name": _get(c, "name"),
                "args": _plain(_get(c, "args") or {}, depth + 2),
            }
            for c in calls
        ]
    call_id = getattr(value, "tool_call_id", None)
    if call_id:
        out["tool_call_id"] = str(call_id)
    return out


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)


def _text(value: Any) -> str:
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - a broken __str__ still sends something
        return f"<{type(value).__name__}>"
