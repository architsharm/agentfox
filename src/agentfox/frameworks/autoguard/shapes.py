"""Reading the client libraries' own shapes: request messages, response text, usage
and stream chunks from OpenAI (chat completions and the Responses API), Anthropic,
LiteLLM and LangChain objects, as plain values the enforcer understands.
"""

from __future__ import annotations

import json
from typing import Any


def _plain(value: Any) -> Any:
    """A pydantic SDK object as the dict it serialises to; anything else unchanged.

    A tool-calling loop appends the SDK's own response message to `messages`
    (``messages.append(response.choices[0].message)``) — a `ChatCompletionMessage`,
    not a dict — and the turn that carried the tool calls was dropped on the floor.
    """
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            dumped = dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:  # pragma: no cover - defensive against SDK shape drift
            pass
    return value


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """`obj[key]` or `obj.key`, whichever shape this SDK version handed back."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _messages_from(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise OpenAI and Anthropic shapes into our message list.

    Anthropic carries the system prompt outside `messages`; folding it back in means
    an injection in a system prompt is evaluated on the same surface either way. For
    the same reason an Anthropic ``tool_result`` block — which arrives inside a
    ``user`` message — becomes a ``tool`` message of its own: it is a tool's output,
    and is evaluated and tainted as one, exactly like OpenAI's ``role="tool"``.
    """
    messages = [_plain(m) for m in kwargs.get("messages") or []]
    system = kwargs.get("system")
    if system:
        text = (
            system
            if isinstance(system, str)
            else " ".join(str(b.get("text", "")) for b in system if isinstance(b, dict))
        )
        messages = [{"role": "system", "content": text}, *messages]
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role, content = str(m.get("role", "user")), m.get("content")
        if isinstance(content, list):
            blocks = [_plain(b) for b in content]
            results = [b for b in blocks if _get(b, "type") == "tool_result"]
            if results:
                out.extend({"role": "tool", "content": _get(b, "content")} for b in results)
                content = [b for b in blocks if _get(b, "type") != "tool_result"]
                if not content:
                    continue
        # Which call a tool message answers, and the calls an assistant turn made, so
        # provenance can name the tool a result came from (and tell a hand-off's
        # acknowledgement from a tool's output).
        kept = {k: m[k] for k in ("name", "tool_call_id", "tool_calls") if m.get(k)}
        out.append({"role": role, "content": content, **kept})
    return out


#: Responses API roles -> our role vocabulary. ``developer`` is the Responses API's
#: name for the system prompt.
_RESPONSES_ROLES = {"developer": "system"}


def _part_text(content: Any) -> str:
    """The text of a Responses content value: a string, or a list of parts
    (``input_text`` / ``output_text`` / ``text``, ``refusal``); images and files carry
    none."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    texts = []
    for part in content:
        text = _get(part, "text")
        if text is None:
            text = _get(part, "refusal")
        if isinstance(text, str):
            texts.append(text)
    return "\n".join(texts)


def _responses_messages(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    """An OpenAI Responses API request (``instructions`` + ``input``) as a chat
    message list in OpenAI's chat shape, so the same pre-flight and provenance
    marking read it.

    ``input`` is a string (one user turn) or a list of items: messages (with or
    without ``type: "message"``), the model's earlier ``function_call`` items
    (kept as an assistant turn's ``tool_calls``, so a result can name the tool that
    produced it) and ``function_call_output`` items, which are a tool's result and
    become ``role="tool"`` messages: ``tool_result`` taint, exactly like chat
    completions' tool messages. Reasoning, hosted-tool and other items carry nothing
    the model reads as instructions and are skipped.
    """
    messages: list[dict[str, Any]] = []
    instructions = kwargs.get("instructions")
    if isinstance(instructions, str) and instructions:
        messages.append({"role": "system", "content": instructions})
    raw = kwargs.get("input")
    if isinstance(raw, str):
        if raw:
            messages.append({"role": "user", "content": raw})
        return messages
    if not isinstance(raw, (list, tuple)):
        return messages
    for item in raw:
        item = _plain(item)
        kind = _get(item, "type")
        role = _get(item, "role")
        if kind in (None, "message") and role:
            role = _RESPONSES_ROLES.get(str(role), str(role))
            messages.append({"role": role, "content": _part_text(_get(item, "content"))})
        elif kind in ("function_call", "custom_tool_call"):
            arguments = _get(item, "arguments")
            if arguments is None:
                arguments = _get(item, "input")
            call = {
                "id": _get(item, "call_id") or _get(item, "id"),
                "type": "function",
                "function": {"name": _get(item, "name"), "arguments": arguments or ""},
            }
            last = messages[-1] if messages else None
            if last is not None and last.get("role") == "assistant" and "tool_calls" in last:
                last["tool_calls"].append(call)  # parallel calls: one assistant turn
            else:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif kind in ("function_call_output", "custom_tool_call_output"):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": _get(item, "call_id"),
                    "content": _part_text(_get(item, "output")),
                }
            )
    return messages


def _response_items(response: Any) -> list[Any] | None:
    """The ``output`` items of a Responses API response, or None for any other shape."""
    if getattr(response, "choices", None) is not None:
        return None
    output = _get(response, "output")
    return output if isinstance(output, list) else None


def _text_of(response: Any) -> str:
    """Pull the assistant text out of whichever client shape came back."""
    try:
        choices = getattr(response, "choices", None)
        if choices:
            return getattr(choices[0].message, "content", "") or ""
        items = _response_items(response)
        if items is not None:  # the Responses API: `message` items' output_text parts
            return "".join(
                str(_get(part, "text") or "")
                for item in items
                if _get(item, "type") == "message"
                for part in _get(item, "content") or []
                if _get(part, "type") == "output_text"
            )
        content = getattr(response, "content", None)
        if isinstance(content, list):
            return "".join(getattr(block, "text", "") or "" for block in content)
        if isinstance(content, str):  # LangChain's AIMessage.content is a plain string
            return content
    except Exception:  # pragma: no cover - defensive against SDK shape drift
        pass
    return ""


def _rewrite_text(response: Any, text: str) -> bool:
    """Put ``text`` back where `_text_of` read the assistant text from, in the
    client's own response object, so the caller's code keeps working on it.

    Returns whether it was written. Mirrors `_text_of` shape for shape: OpenAI and
    LiteLLM ``choices[0].message.content``; Anthropic text blocks (read as one
    concatenated text, so the rewrite goes into the first text block and the others
    are emptied — non-text blocks such as ``tool_use`` are left alone); LangChain's
    ``AIMessage.content`` string.
    """
    try:
        choices = getattr(response, "choices", None)
        if choices:
            message = choices[0].message
            message.content = text
            return getattr(message, "content", None) == text
        items = _response_items(response)
        if items is not None:  # the Responses API: same rule as Anthropic's blocks
            parts = [
                part
                for item in items
                if _get(item, "type") == "message"
                for part in _get(item, "content") or []
                if _get(part, "type") == "output_text"
            ]
            if not parts:
                return False
            for index, part in enumerate(parts):
                if isinstance(part, dict):
                    part["text"] = text if index == 0 else ""
                else:
                    part.text = text if index == 0 else ""
            return _text_of(response) == text
        content = getattr(response, "content", None)
        if isinstance(content, list):
            blocks = [b for b in content if isinstance(getattr(b, "text", None), str)]
            if not blocks:
                return False
            for index, block in enumerate(blocks):
                block.text = text if index == 0 else ""
            return _text_of(response) == text
        if isinstance(content, str):
            response.content = text
            return getattr(response, "content", None) == text
    except Exception:  # read-only or frozen SDK object: the caller refuses instead
        return False
    return False


def _usage_of(response: Any) -> dict[str, int]:
    """Pull input/output token counts out of whichever client shape came back —
    same normalise-across-providers pattern as `_text_of`, needed because this path
    governs the caller's own raw SDK response, never AgentFox's own
    `CompletionResponse` (the shape `Enforcer._charge_budget` was written against).
    OpenAI's `usage.prompt_tokens`/`completion_tokens` and Anthropic's
    `usage.input_tokens`/`output_tokens` are both covered; an unrecognised shape
    returns an empty dict rather than guessing, which is a silent no-charge, not a
    wrong one.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    try:
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        if output_tokens is None:
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
        return {"input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0)}
    except Exception:  # pragma: no cover - defensive against SDK shape drift
        return {}


def _chunk_text(chunk: Any) -> str:
    """The text a single streamed chunk carries.

    OpenAI and LiteLLM: ``chunk.choices[0].delta.content``. Anthropic: the
    ``content_block_delta`` event's ``delta.text`` (other event types carry none).
    """
    try:
        choices = getattr(chunk, "choices", None)
        if choices:
            content = getattr(getattr(choices[0], "delta", None), "content", None)
            return content if isinstance(content, str) else ""
        kind = getattr(chunk, "type", None)
        if kind == "content_block_delta":
            text = getattr(getattr(chunk, "delta", None), "text", None)
            return text if isinstance(text, str) else ""
        if kind == "response.output_text.delta":  # the Responses API
            text = getattr(chunk, "delta", None)
            return text if isinstance(text, str) else ""
    except Exception:  # pragma: no cover - defensive against SDK shape drift
        pass
    return ""


#: Responses API stream events that end the response and carry it whole.
_RESPONSES_FINAL_EVENTS = ("response.completed", "response.incomplete", "response.failed")


def _chunk_final_response(chunk: Any) -> Any:
    """The whole response a Responses API stream's final event carries, else None.

    Read in preference to the deltas: it holds the text, every output item (tool
    calls, hosted tools) and the usage exactly as a buffered call would have."""
    if getattr(chunk, "type", None) in _RESPONSES_FINAL_EVENTS:
        return getattr(chunk, "response", None)
    return None


def _chunk_tool_calls(chunk: Any, parts: dict[int, dict[str, Any]]) -> None:
    """Accumulate the tool-call fragments a streamed chunk carries into ``parts``.

    OpenAI and LiteLLM: ``choices[0].delta.tool_calls[*]``, keyed by ``index``, the
    name and id on the first fragment and the JSON arguments spread across the rest.
    Anthropic: a ``content_block_start`` whose block is a ``tool_use`` opens one at
    the event's ``index``; ``input_json_delta`` events extend its arguments.
    """
    choices = getattr(chunk, "choices", None)
    if choices:
        for fragment in _get(_get(choices[0], "delta"), "tool_calls") or []:
            index = _get(fragment, "index", 0) or 0
            part = parts.setdefault(int(index), {"name": "", "id": None, "args": []})
            if _get(fragment, "id"):
                part["id"] = _get(fragment, "id")
            function = _get(fragment, "function")
            if _get(function, "name"):
                part["name"] = str(_get(function, "name"))
            if _get(function, "arguments"):
                part["args"].append(str(_get(function, "arguments")))
        return
    kind = getattr(chunk, "type", None)
    if kind == "response.output_item.done":
        # The Responses API: a finished `function_call` item carries its whole
        # arguments, so the `function_call_arguments.delta` events need no assembly.
        item = getattr(chunk, "item", None)
        if _get(item, "type") == "function_call":
            parts[int(getattr(chunk, "output_index", 0) or 0)] = {
                "name": str(_get(item, "name") or ""),
                "id": _get(item, "call_id"),
                "args": [str(_get(item, "arguments") or "")],
            }
        return
    if kind == "content_block_start":
        block = getattr(chunk, "content_block", None)
        if _get(block, "type") == "tool_use":
            initial = _get(block, "input")
            parts[int(getattr(chunk, "index", 0) or 0)] = {
                "name": str(_get(block, "name") or ""),
                "id": _get(block, "id"),
                # Anthropic opens the block with an empty `input` and streams the
                # real one; a non-empty one (a replayed stream) is kept as the start.
                "args": [json.dumps(initial)] if initial else [],
            }
    elif kind == "content_block_delta":
        delta = getattr(chunk, "delta", None)
        if _get(delta, "type") == "input_json_delta":
            part = parts.get(int(getattr(chunk, "index", 0) or 0))
            if part is not None:
                part["args"].append(str(_get(delta, "partial_json") or ""))


def _chunk_usage(chunk: Any) -> dict[str, int]:
    """Token counts a streamed chunk carries: OpenAI's final ``include_usage`` chunk,
    Anthropic's ``message_start`` (input) and ``message_delta`` (output) events."""
    if getattr(chunk, "type", None) == "message_start":
        return _usage_of(getattr(chunk, "message", None))
    final = _chunk_final_response(chunk)  # the Responses API's last event
    if final is not None:
        return _usage_of(final)
    return _usage_of(chunk)


#: LangChain message `.type` -> our role vocabulary.
_LC_ROLES = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _lc_messages_from(chat_input: Any) -> list[dict[str, Any]]:
    """Normalise whatever `BaseChatModel.invoke` was given into our message list.

    LangChain accepts a bare string, a `PromptValue`, or a sequence of `BaseMessage`
    (or plain dicts). Whichever shape arrives, the point is the same as
    `_messages_from`: evaluate on the same surface regardless of how the caller built
    the input.
    """
    if isinstance(chat_input, str):
        return [{"role": "user", "content": chat_input}]

    if hasattr(chat_input, "to_messages"):  # a PromptValue
        chat_input = chat_input.to_messages()

    sequence = chat_input if isinstance(chat_input, (list, tuple)) else [chat_input]
    messages: list[dict[str, Any]] = []
    for item in sequence:
        if isinstance(item, dict):
            messages.append({"role": str(item.get("role", "user")), "content": item.get("content")})
            continue
        content = getattr(item, "content", None)
        msg_type = getattr(item, "type", None)
        if content is None and msg_type is None:
            continue
        role = _LC_ROLES.get(str(msg_type), str(msg_type or "user"))
        messages.append(
            {"role": role, "content": content if isinstance(content, str) else str(content)}
        )
    return messages
