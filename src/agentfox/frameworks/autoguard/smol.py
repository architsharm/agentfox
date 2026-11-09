"""smolagents, and huggingface_hub's chat client its default model calls.

**Model calls.** smolagents' default `InferenceClientModel` calls
`huggingface_hub.InferenceClient.chat_completion` (``client.chat.completions.create``
is a proxy to it). That method, and `AsyncInferenceClient.chat_completion`, are
governed like OpenAI's: the request and response are OpenAI's chat shape. smolagents'
`OpenAIModel` and `LiteLLMModel` go through the openai and litellm patches; local
models (`TransformersModel`, `MLXModel`, `VLLMModel`) make no network call and are
not governed.

**Tools.** A `ToolCallingAgent` runs the tool calls its model asks for, and a
`CodeAgent` runs code that calls its tools as functions: either way through
`Tool.__call__`. That is where a smolagents tool is governed, as a LangChain or CrewAI
tool is (`_lc_tool_decide`): a refused call hands the agent the refusal as the tool's
result and the run carries on (``tool_refusals="raise"`` raises `Blocked`), and what
the tool returns is checked as a tool result before the model reads it. While an
agent runs (`MultiStepAgent._run_stream`), the tool calls in its model's replies are
left to that guard, so each is decided once. ``final_answer`` is the agent's answer,
not a capability: it is not decided, and in a model reply it is checked as output.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from agentfox.frameworks import autoguard as ag
from agentfox.frameworks.autoguard import delegation

#: smolagents' answer tool (`FinalAnswerTool`).
FINAL_ANSWER = "final_answer"


# -- huggingface_hub ---------------------------------------------------------------


def _hub_request(client: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """The governed view of `chat_completion(messages, *, model=None, stream=False,
    tools=None, ...)`. The reserved evidence kwargs are popped from the caller's."""
    messages = args[0] if args else kwargs.get("messages")
    model = kwargs.get("model") or getattr(client, "model", None) or ""
    governed: dict[str, Any] = {
        "messages": list(messages or []),
        "model": str(model),
        "tools": list(kwargs.get("tools") or []),
        "stream": bool(kwargs.get("stream")),
    }
    for key in ag._EVIDENCE_KWARGS:
        if key in kwargs:
            governed[key] = kwargs.pop(key)
    return governed


def _hub_method(state: ag.AutoState, *, is_async: bool) -> Callable[[Any], Any]:
    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(self: Any, *args: Any, **kwargs: Any) -> Any:
                governed = _hub_request(self, args, kwargs)
                return await ag._agovern(
                    ag._live(state), governed, lambda: original(self, *args, **kwargs)
                )

            return agoverned

        @functools.wraps(original)
        def governed(self: Any, *args: Any, **kwargs: Any) -> Any:
            request = _hub_request(self, args, kwargs)
            return ag._govern(ag._live(state), request, lambda: original(self, *args, **kwargs))

        return governed

    return build


def patch_hub(state: ag.AutoState) -> list[ag.PatchResult]:
    import importlib.util

    try:
        if importlib.util.find_spec("huggingface_hub") is None:
            return ag._not_importable("huggingface_hub", ImportError("huggingface_hub"))
        import huggingface_hub
        from huggingface_hub import AsyncInferenceClient, InferenceClient
    except Exception as exc:
        return ag._not_importable("huggingface_hub", exc)

    version = getattr(huggingface_hub, "__version__", None)
    return [
        ag._patch_attr(
            "huggingface_hub",
            "huggingface_hub",
            InferenceClient,
            "chat_completion",
            _hub_method(state, is_async=False),
            version,
            "InferenceClient.chat_completion",
        ),
        ag._patch_attr(
            "huggingface_hub.async",
            "huggingface_hub",
            AsyncInferenceClient,
            "chat_completion",
            _hub_method(state, is_async=True),
            version,
            "AsyncInferenceClient.chat_completion",
        ),
    ]


# -- smolagents tools ----------------------------------------------------------------


def _tool_input(tool: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """`Tool.__call__(*args, sanitize_inputs_outputs=False, **kwargs)`: keyword
    arguments, a single dict of them, or positional arguments in ``tool.inputs`` order."""
    arguments = {k: v for k, v in kwargs.items() if k != "sanitize_inputs_outputs"}
    if len(args) == 1 and not arguments and isinstance(args[0], dict):
        return dict(args[0])
    names = list(getattr(tool, "inputs", None) or {})
    for index, value in enumerate(args):
        key = names[index] if index < len(names) else f"_arg{index}"
        arguments[key] = value
    return arguments


def _tool_method(state: ag.AutoState) -> Callable[[Any], Any]:
    """Wrapper factory for `Tool.__call__`."""

    def build(original: Any) -> Any:
        @functools.wraps(original)
        def governed(self: Any, *args: Any, **kwargs: Any) -> Any:
            name = str(getattr(self, "name", "") or type(self).__name__)
            if ag._IN_AGENTFOX.get() or name == FINAL_ANSWER:
                return original(self, *args, **kwargs)
            st = ag._live(state)
            arguments = _tool_input(self, args, kwargs)
            allowed, result, trace_id = ag._lc_tool_decide(st, name, arguments)
            if not allowed:
                if st.tool_refusals == "raise":
                    raise ag.Blocked(
                        result, f"agentfox: tool call '{name}' refused: {result.reason}"
                    )
                if result.escalated and result.approval_id:
                    return ag._HELD_MESSAGE.format(approval_id=result.approval_id)
                reason = result.user_message or result.reason or "not allowed"
                return f"This tool call was blocked by policy: {reason}"
            output = original(self, *args, **kwargs)
            text = output if isinstance(output, str) else str(output)
            withheld = ag._lc_tool_result(st, trace_id, text)
            if withheld is None:
                ag._TOOL_RESULTS.add(st.session_id, name, text)
                return output
            message = withheld.user_message or withheld.reason or "it failed a policy check"
            return f"This tool's result was withheld by policy: {message}"

        return governed

    return build


def _run_scope(original: Any) -> Any:
    """Wrapper for `MultiStepAgent._run_stream`, a generator: every step it runs is
    marked as smolagents' (`_FROM_SMOLAGENTS`), so the tool calls in its model's
    replies are left to the tool-level guard. The mark is set around each resumption,
    not around the call that only creates the generator."""

    @functools.wraps(original)
    def scoped(*args: Any, **kwargs: Any) -> Any:
        steps = original(*args, **kwargs)
        try:
            while True:
                token = ag._FROM_SMOLAGENTS.set(True)
                try:
                    step = next(steps)
                except StopIteration as done:
                    return done.value
                finally:
                    ag._FROM_SMOLAGENTS.reset(token)
                yield step
        finally:
            steps.close()

    return scoped


def patch_tools(state: ag.AutoState) -> list[ag.PatchResult]:
    """smolagents tools, governed where they run. Reported as ``smolagents.tools``."""
    import importlib.util

    try:
        if importlib.util.find_spec("smolagents") is None:
            return ag._not_importable("smolagents tools", ImportError("smolagents"))
        import smolagents
        from smolagents import agents, tools
    except Exception as exc:
        return ag._not_importable("smolagents tools", exc)

    version = getattr(smolagents, "__version__", None)
    results = [
        ag._patch_attr(
            "smolagents.tools",
            "smolagents",
            tools.Tool,
            "__call__",
            _tool_method(state),
            version,
            "Tool.__call__",
        )
    ]
    # A subclass with its own `__call__` (`PipelineTool`) is patched too.
    for owner in (getattr(tools, "PipelineTool", None),):
        if owner is not None and "__call__" in owner.__dict__:
            ag._patch_attr(
                f"smolagents.tools.{owner.__name__}",
                "smolagents",
                owner,
                "__call__",
                _tool_method(state),
                version,
                f"{owner.__name__}.__call__",
            )
    run = getattr(agents.MultiStepAgent, "_run_stream", None)
    scoped = run is not None and inspect.isgeneratorfunction(
        getattr(run, "__agentfox_original__", run)
    )
    if scoped:
        ag._patch_attr(
            "smolagents.agent",
            "smolagents",
            agents.MultiStepAgent,
            "_run_stream",
            _run_scope,
            version,
            "MultiStepAgent._run_stream",
        )
    delegation.OUTPUT_TOOLS.add(FINAL_ANSWER)
    # Without the run scope a model reply's tool calls are decided there as well as
    # where they run: twice, but never not at all.
    state.smol_tools = results[0].patched and scoped
    return results
