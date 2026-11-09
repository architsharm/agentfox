"""Google GenAI (``google-genai``), and Google ADK, which calls Gemini through it.

`Models.generate_content` and `generate_content_stream`, and their `AsyncModels`
twins (the ones ADK's `Gemini` model calls), are governed like any other client
library's entry point (`_govern`): the request's ``contents`` and
``config.system_instruction`` are read as a chat conversation (`shapes._genai_messages`),
a ``function_response`` part is a tool's result, and the ``function_call`` parts of
the reply are the tool calls checked before the caller's code (or ADK) runs them.

Automatic function calling, where the SDK itself runs Python functions passed as
``config.tools``, calls each one through `_extra_utils.invoke_function_from_dict_args`
(or its async twin) inside `generate_content`: the reply that asked for the call never
leaves the SDK. Those two functions are governed where the function runs, as a
LangChain or CrewAI tool is (`_lc_tool_decide`): a refused call hands the model the
refusal as the function's result, and what a function returns is checked as a tool
result before the model reads it.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from agentfox.frameworks import autoguard as ag
from agentfox.frameworks.autoguard.shapes import _genai_messages, _get, _plain


def _tools(config: Any) -> list[dict[str, Any]]:
    """``config.tools`` in OpenAI's shape, for the tool descriptions impact inference
    reads: each `Tool`'s ``function_declarations``, and the Python functions passed
    for automatic function calling, by name and docstring."""
    tools: list[dict[str, Any]] = []
    for tool in (_get(config, "tools") if config is not None else None) or []:
        declarations = _get(tool, "function_declarations")
        if declarations is None and callable(tool):
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": getattr(tool, "__name__", "function"),
                        "description": inspect.getdoc(tool) or "",
                    },
                }
            )
            continue
        for declaration in declarations or []:
            name = _get(declaration, "name")
            if not name:
                continue
            parameters = _get(declaration, "parameters_json_schema") or _get(
                declaration, "parameters"
            )
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(name),
                        "description": str(_get(declaration, "description") or ""),
                        "parameters": _plain(parameters) or {},
                    },
                }
            )
    return tools


def _request(kwargs: dict[str, Any], *, stream: bool) -> dict[str, Any]:
    """The governed view of a `generate_content` call. The caller's kwargs are what
    the SDK receives, the reserved evidence kwargs popped first (the SDK's methods
    take keyword arguments only, and would refuse them)."""
    config = kwargs.get("config")
    governed: dict[str, Any] = {
        "messages": _genai_messages(kwargs.get("contents"), config),
        "model": str(kwargs.get("model") or ""),
        "tools": _tools(config),
        "stream": stream,
    }
    for key in ag._EVIDENCE_KWARGS:
        if key in kwargs:
            governed[key] = kwargs.pop(key)
    return governed


def _method(state: ag.AutoState, *, is_async: bool, stream: bool) -> Callable[[Any], Any]:
    """Wrapper factory for `Models.generate_content[_stream]` and the async twins."""

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(*args: Any, **kwargs: Any) -> Any:
                governed = _request(kwargs, stream=stream)
                return await ag._agovern(
                    ag._live(state), governed, lambda: original(*args, **kwargs)
                )

            return agoverned

        @functools.wraps(original)
        def governed(*args: Any, **kwargs: Any) -> Any:
            request = _request(kwargs, stream=stream)
            return ag._govern(ag._live(state), request, lambda: original(*args, **kwargs))

        return governed

    return build


def _function_name(function: Any) -> str:
    return str(getattr(function, "__name__", "") or type(function).__name__)


def _refusal(state: ag.AutoState, name: str, result: Any) -> str:
    if state.tool_refusals == "raise":
        # The SDK hands an exception from a function to the model as its error.
        raise ag.Blocked(result, f"agentfox: tool call '{name}' refused: {result.reason}")
    if result.escalated and result.approval_id:
        return ag._HELD_MESSAGE.format(approval_id=result.approval_id)
    return "This tool call was blocked by policy: " + (
        result.user_message or result.reason or "not allowed"
    )


def _checked(state: ag.AutoState, name: str, trace_id: str | None, output: Any) -> Any:
    text = output if isinstance(output, str) else str(output)
    withheld = ag._lc_tool_result(state, trace_id, text)
    if withheld is None:
        ag._TOOL_RESULTS.add(state.session_id, name, text)
        return output
    message = withheld.user_message or withheld.reason or "it failed a policy check"
    return f"This tool's result was withheld by policy: {message}"


def _function_call(state: ag.AutoState, *, is_async: bool) -> Callable[[Any], Any]:
    """Wrapper factory for `invoke_function_from_dict_args(args, function)` and its
    async twin: one automatic function call, decided where it runs.

    The function runs outside AgentFox's own scope (`_IN_AGENTFOX` is set for the
    whole governed `generate_content` around it), so a model call the function makes
    is the app's own and is governed too."""

    def before(args: Any, function: Any) -> tuple[str | None, str, str | None]:
        st = ag._live(state)
        name = _function_name(function)
        arguments = dict(args) if isinstance(args, dict) else {"_value": args}
        allowed, result, trace_id = ag._lc_tool_decide(st, name, arguments)
        return (None if allowed else _refusal(st, name, result)), name, trace_id

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(args: Any, function_to_invoke: Any) -> Any:
                refusal, name, trace_id = before(args, function_to_invoke)
                if refusal is not None:
                    return refusal
                token = ag._IN_AGENTFOX.set(False)
                try:
                    output = await original(args, function_to_invoke)
                finally:
                    ag._IN_AGENTFOX.reset(token)
                return _checked(ag._live(state), name, trace_id, output)

            return agoverned

        @functools.wraps(original)
        def governed(args: Any, function_to_invoke: Any) -> Any:
            refusal, name, trace_id = before(args, function_to_invoke)
            if refusal is not None:
                return refusal
            token = ag._IN_AGENTFOX.set(False)
            try:
                output = original(args, function_to_invoke)
            finally:
                ag._IN_AGENTFOX.reset(token)
            return _checked(ag._live(state), name, trace_id, output)

        return governed

    return build


def patch(state: ag.AutoState) -> list[ag.PatchResult]:
    """Patch google-genai. Reported as ``google-genai`` and ``google-genai.async``,
    each patched when every entry point of its kind is."""
    import importlib.util

    try:
        if importlib.util.find_spec("google.genai") is None:
            return ag._not_importable("google-genai", ImportError("google-genai"))
        from google import genai
        from google.genai import _extra_utils, models
    except Exception as exc:
        return ag._not_importable("google-genai", exc)

    version = getattr(genai, "__version__", None)
    parts: dict[bool, list[ag.PatchResult]] = {False: [], True: []}
    for is_async, owner in ((False, models.Models), (True, models.AsyncModels)):
        prefix = "google-genai.async" if is_async else "google-genai"
        cls = owner.__name__
        for attr, stream in (("generate_content", False), ("generate_content_stream", True)):
            label = prefix if not stream else f"{prefix}.stream"
            parts[is_async].append(
                ag._patch_attr(
                    label,
                    "google-genai",
                    owner,
                    attr,
                    _method(state, is_async=is_async, stream=stream),
                    version,
                    f"{cls}.{attr}",
                )
            )
    # Automatic function calling: not every version has it; the model calls are
    # governed either way, so a missing one is said in the detail, not a failure.
    afc: list[str] = []
    for is_async, attr in (
        (False, "invoke_function_from_dict_args"),
        (True, "invoke_function_from_dict_args_async"),
    ):
        result = ag._patch_attr(
            f"google-genai.functions{'.async' if is_async else ''}",
            "google-genai",
            _extra_utils,
            attr,
            _function_call(state, is_async=is_async),
            version,
            "automatic function calls",
        )
        if result.patched:
            afc.append(result.detail)
    state.genai_functions = bool(afc)

    results = []
    for label, is_async in (("google-genai", False), ("google-genai.async", True)):
        failed = [p for p in parts[is_async] if not p.patched]
        details = [p.detail for p in parts[is_async] if p.detail != "already patched"]
        if afc and details:
            details.append("automatic function calls")
        detail = failed[0].detail if failed else ", ".join(details) or "already patched"
        results.append(ag.PatchResult(label, not failed, detail, version))
    return results
