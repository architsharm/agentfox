"""OpenAI Agents SDK integration (``pip install agentfox[openai-agents]``).

Three pieces, each a native Agents SDK object backed by the AgentFox SDK client, so
they work in-process (`AgentFox(agent)`) or against a gateway
(`AgentFox(agent, base_url=..., api_key=...)`) with no other change:

* `agentfox_input_guardrail` / `agentfox_output_guardrail` — an ``InputGuardrail`` /
  ``OutputGuardrail`` that sends the run's input or final output to AgentFox and trips
  when the decision stopped it.
* `agentfox_tool_guardrail` — a ``ToolInputGuardrail`` (Agents SDK 0.3 and later) that
  authorises each call of a function tool and rejects it with a message to the model.
* `guard_tool` / `guarded_function_tool` — a plain wrapper around the tool's Python
  function, for SDK versions without tool guardrails or for code that also calls the
  function directly.

Design decisions:

* **The tripwire follows the applied verdict** (``verdict``), never the counterfactual
  ``effective_verdict``. In observe mode a policy that *would* block lets the run
  through, and the would-be verdict is reported in ``output_info`` for the dashboard
  to show. Tripping on it would refuse traffic the platform allowed.
* **The ``agents`` package is imported lazily**, at the moment a guardrail is built, so
  ``import agentfox.frameworks.openai_agents`` works without it and fails with a
  clear message only when one is asked for.
* **Client calls run in a worker thread** by default (``run_in_thread=True``): the SDK
  client is synchronous, and an input guardrail runs in parallel with the model, so
  blocking the event loop would serialise them. Pass ``run_in_thread=False`` when the
  client holds a caller's database session that must stay on the calling thread.

Usage::

    from agents import Agent, function_tool
    from agentfox.frameworks.sdk import AgentFox
    from agentfox.frameworks.openai_agents import (
        agentfox_input_guardrail, agentfox_output_guardrail, guarded_function_tool,
    )

    fox = AgentFox("support-triage", base_url="http://localhost:8080", api_key="...")

    @guarded_function_tool(fox, tool="payments.refund")
    def refund(order_id: str, amount: float) -> str: ...

    agent = Agent(
        name="support",
        tools=[refund],
        input_guardrails=[agentfox_input_guardrail(client=fox)],
        output_guardrails=[agentfox_output_guardrail(client=fox)],
    )
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from agentfox.errors import AgentFoxError, ApprovalRequired, PolicyViolation
from agentfox.runtime.enforcement.result import STOPPING_VERDICTS, EnforcementResult

log = logging.getLogger(__name__)

#: Parameter types the Agents SDK injects into a function tool; never policy input.
_CONTEXT_TYPES = frozenset({"RunContextWrapper", "ToolContext"})


def openai_agents_available() -> bool:
    try:
        import agents  # noqa: F401
    except Exception:
        return False
    return True


def _agents() -> Any:
    try:
        import agents  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "agentfox.frameworks.openai_agents needs the OpenAI Agents SDK: "
            "pip install 'agentfox[openai-agents]'"
        ) from exc
    return agents


def _client(agent_slug: str | None, client: Any) -> Any:
    if client is not None:
        return client
    if not agent_slug:
        raise ValueError("pass agent_slug= or client=AgentFox(...)")
    from agentfox.frameworks.sdk import AgentFox

    return AgentFox(agent_slug)


async def _call(run_in_thread: bool, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if run_in_thread:
        return await asyncio.to_thread(fn, *args, **kwargs)
    return fn(*args, **kwargs)


# -- decisions --------------------------------------------------------------


def _info(decision: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a decision a guardrail's ``output_info`` carries."""
    return {
        "verdict": decision.get("verdict", "allow"),
        "effective_verdict": decision.get("effective_verdict", "allow"),
        "mode": decision.get("mode"),
        "user_message": decision.get("user_message") or None,
        "reason": decision.get("reason", ""),
        "trace_id": decision.get("trace_id"),
        "decision_id": decision.get("decision_id"),
        "approval_id": decision.get("approval_id"),
        "rules_fired": decision.get("rules_fired") or [],
        "fix": decision.get("fix"),
        "content": decision.get("content"),
    }


def _stops(decision: Mapping[str, Any]) -> bool:
    return decision.get("verdict", "allow") in STOPPING_VERDICTS


def _refusal(result: EnforcementResult) -> str:
    """What the model is told instead of the tool's result."""
    if result.escalated:
        return (
            f"This tool call is held for human approval (approval_id: {result.approval_id}). "
            "Do not retry it; tell the user it is waiting for approval."
        )
    message = result.user_message or result.reason or "blocked by policy"
    return f"This tool call was blocked by policy: {message}"


# -- content ------------------------------------------------------------------


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(parts)
    return ""


def input_text(run_input: Any) -> str:
    """The user-authored text in an Agents SDK run input.

    A run input is a string or a list of response input items. Only user messages are
    policy input here: assistant turns and tool outputs in a carried-over history were
    checked when they were produced.
    """
    if isinstance(run_input, str):
        return run_input
    texts = []
    for item in run_input or []:
        item = item if isinstance(item, Mapping) else getattr(item, "__dict__", {})
        if item.get("role") == "user":
            text = _text_of(item.get("content"))
            if text:
                texts.append(text)
    return "\n".join(texts)


def output_text(output: Any) -> str:
    """An agent's final output as text: a string, or a structured output as JSON."""
    if isinstance(output, str):
        return output
    dump = getattr(output, "model_dump_json", None)
    if callable(dump):
        return dump()
    try:
        return json.dumps(output, default=str)
    except (TypeError, ValueError):
        return str(output)


# -- input and output guardrails ------------------------------------------------


def agentfox_input_guardrail(
    agent_slug: str | None = None,
    *,
    client: Any = None,
    name: str = "agentfox_input",
    run_in_thread: bool = True,
) -> Any:
    """An Agents SDK ``InputGuardrail`` that checks the run's input with AgentFox.

    It trips when AgentFox stopped the input (applied verdict ``block``, ``escalate``
    or ``abstain``); the Runner then raises ``InputGuardrailTripwireTriggered``, whose
    ``guardrail_result.output.output_info`` holds ``user_message``, ``trace_id`` and the
    rest of the decision.
    """
    agents = _agents()
    fox = _client(agent_slug, client)

    async def guardrail(ctx: Any, agent: Any, run_input: Any) -> Any:
        text = input_text(run_input)
        if not text:
            return agents.GuardrailFunctionOutput(output_info=None, tripwire_triggered=False)
        decision = await _call(run_in_thread, fox.check, text, surface="input")
        return agents.GuardrailFunctionOutput(
            output_info=_info(decision), tripwire_triggered=_stops(decision)
        )

    guardrail.__name__ = name
    return agents.input_guardrail(guardrail)


def agentfox_output_guardrail(
    agent_slug: str | None = None,
    *,
    client: Any = None,
    name: str = "agentfox_output",
    run_in_thread: bool = True,
) -> Any:
    """An Agents SDK ``OutputGuardrail`` that checks the agent's final output.

    Trips like `agentfox_input_guardrail`. When AgentFox asks for a re-ask rather than a
    refusal, ``output_info["fix"]["instruction"]`` is the correction to send the model.
    A redaction does not trip; the redacted text is in ``output_info["content"]``.
    """
    agents = _agents()
    fox = _client(agent_slug, client)

    async def guardrail(ctx: Any, agent: Any, output: Any) -> Any:
        decision = await _call(run_in_thread, fox.check, output_text(output), surface="output")
        return agents.GuardrailFunctionOutput(
            output_info=_info(decision), tripwire_triggered=_stops(decision)
        )

    guardrail.__name__ = name
    return agents.output_guardrail(guardrail)


# -- tool calls ------------------------------------------------------------------


def _authorise(
    fox: Any,
    tool: str,
    arguments: dict[str, Any],
    provenance: dict[str, str] | None,
    approval_id: str | None = None,
) -> EnforcementResult:
    """One `/v1/guard/tool_call` decision, inside the caller's AgentFox session if any.

    Joining the active ``with fox.session(intent=...)`` block is what gives the decision
    the declared intent, the session's taint marks and the tools already called.
    """
    current = getattr(fox, "current_session", None)
    active = current() if callable(current) else None
    if active is not None:
        return active.guard_tool(
            tool, arguments, provenance=provenance, raise_on_block=False, approval_id=approval_id
        )
    with fox.session() as ad_hoc:
        return ad_hoc.guard_tool(
            tool, arguments, provenance=provenance, raise_on_block=False, approval_id=approval_id
        )


class _HeldCalls:
    """Approvals this process is waiting on, so an approved call can run when retried.

    A held call returns to the model as a refusal naming its approval; the model, or
    the user, tries again later. Without this the retry was a new call — a new
    approval for a reviewer, and the approved one never used. Calls are matched on
    tool and arguments; an approved match is retried with its ``approval_id`` and
    runs once, a denied or expired one is forgotten.
    """

    def __init__(self) -> None:
        self._held: dict[tuple[str, str], str] = {}

    @staticmethod
    def _key(tool: str, arguments: dict[str, Any]) -> tuple[str, str]:
        return tool, json.dumps(arguments, sort_keys=True, default=str)

    def approved(self, fox: Any, tool: str, arguments: dict[str, Any]) -> str | None:
        key = self._key(tool, arguments)
        approval_id = self._held.get(key)
        if approval_id is None:
            return None
        try:
            status = str((fox.approval(approval_id) or {}).get("status", "pending"))
        except Exception:  # noqa: BLE001 - an unreadable approval is decided afresh
            status = "unknown"
        if status == "approved":
            self._held.pop(key, None)
            return approval_id
        if status != "pending":
            self._held.pop(key, None)
        return None

    def remember(self, tool: str, arguments: dict[str, Any], result: EnforcementResult) -> None:
        if result.escalated and result.approval_id:
            self._held[self._key(tool, arguments)] = result.approval_id


def _authorise_held(
    fox: Any,
    held: _HeldCalls,
    tool: str,
    arguments: dict[str, Any],
    provenance: dict[str, str] | None,
) -> EnforcementResult:
    """`_authorise`, redeeming an approval a person granted for this exact call."""
    approval_id = held.approved(fox, tool, arguments)
    result = _authorise(fox, tool, arguments, provenance, approval_id)
    held.remember(tool, arguments, result)
    return result


def _arguments(fn: Callable[..., Any], args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
    """The call's arguments by name, without the context the SDK injects."""
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        return dict(kwargs)
    out: dict[str, Any] = {}
    for key, value in bound.arguments.items():
        if type(value).__name__ in _CONTEXT_TYPES:
            continue
        out[key] = value
    return out


def guard_tool(
    client: Any,
    *,
    tool: str | None = None,
    provenance: dict[str, str] | None = None,
    raise_on_block: bool = False,
    run_in_thread: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a tool function so AgentFox authorises every call before it runs.

    ``tool`` is the AgentFox tool key (default: the function's name). On a block the
    function does not run and the wrapper returns a refusal string, which the Agents
    SDK hands the model as the tool's result; on an escalation the refusal names the
    ``approval_id``. ``raise_on_block=True`` raises `PolicyViolation` /
    `ApprovalRequired` instead. Sync and async functions are both supported, and the
    signature is preserved so ``function_tool`` builds the same schema.
    """

    held = _HeldCalls()

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        key = tool or fn.__name__

        def settle(result: EnforcementResult) -> str | None:
            if result.verdict in STOPPING_VERDICTS:
                if raise_on_block:
                    if result.escalated:
                        raise ApprovalRequired(result)
                    raise PolicyViolation(result)
                return _refusal(result)
            return None

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                arguments = _arguments(fn, args, kwargs)
                result = await _call(
                    run_in_thread, _authorise_held, client, held, key, arguments, provenance
                )
                refusal = settle(result)
                if refusal is not None:
                    return refusal
                return await fn(*args, **kwargs)

            async_wrapper._agentfox_tool = key  # type: ignore[attr-defined]
            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = _authorise_held(client, held, key, _arguments(fn, args, kwargs), provenance)
            refusal = settle(result)
            if refusal is not None:
                return refusal
            return fn(*args, **kwargs)

        wrapper._agentfox_tool = key  # type: ignore[attr-defined]
        return wrapper

    return decorator


def guarded_function_tool(
    client: Any,
    *,
    tool: str | None = None,
    provenance: dict[str, str] | None = None,
    raise_on_block: bool = False,
    run_in_thread: bool = True,
    **function_tool_kwargs: Any,
) -> Callable[[Callable[..., Any]], Any]:
    """`guard_tool` then the Agents SDK's ``function_tool``, as one decorator.

    Extra keyword arguments go to ``function_tool`` (``name_override``,
    ``description_override``, ...).
    """
    agents = _agents()
    guard = guard_tool(
        client,
        tool=tool,
        provenance=provenance,
        raise_on_block=raise_on_block,
        run_in_thread=run_in_thread,
    )

    def decorator(fn: Callable[..., Any]) -> Any:
        return agents.function_tool(guard(fn), **function_tool_kwargs)

    return decorator


def agentfox_tool_guardrail(
    client: Any,
    *,
    tools: Mapping[str, str] | None = None,
    provenance: dict[str, str] | None = None,
    raise_on_block: bool = False,
    name: str = "agentfox_tool_call",
    run_in_thread: bool = True,
) -> Any:
    """An Agents SDK ``ToolInputGuardrail`` (SDK 0.3+) that authorises each tool call.

    Attach with ``function_tool(fn, tool_input_guardrails=[...])``. ``tools`` maps the
    SDK tool name to an AgentFox tool key where they differ. A stopped call is rejected
    with a message to the model (``reject_content``), and the run continues;
    ``raise_on_block=True`` halts the run with ``ToolInputGuardrailTripwireTriggered``.
    """
    agents = _agents()
    if not hasattr(agents, "tool_input_guardrail"):
        raise ImportError(
            "tool guardrails need openai-agents 0.3 or later; use guard_tool() instead"
        )
    names = dict(tools or {})
    held = _HeldCalls()

    async def guardrail(data: Any) -> Any:
        ctx = data.context
        sdk_name = getattr(ctx, "tool_name", "") or ""
        raw = getattr(ctx, "tool_arguments", None) or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (TypeError, ValueError):
            arguments = {"_raw": raw}
        if not isinstance(arguments, dict):
            arguments = {"_value": arguments}
        key = names.get(sdk_name, sdk_name)
        result = await _call(
            run_in_thread, _authorise_held, client, held, key, arguments, provenance
        )
        info = _info(result.to_json())
        if result.verdict not in STOPPING_VERDICTS:
            return agents.ToolGuardrailFunctionOutput.allow(output_info=info)
        if raise_on_block:
            return agents.ToolGuardrailFunctionOutput.raise_exception(output_info=info)
        return agents.ToolGuardrailFunctionOutput.reject_content(
            message=_refusal(result), output_info=info
        )

    guardrail.__name__ = name
    return agents.tool_input_guardrail(guardrail)


__all__ = [
    "AgentFoxError",
    "ApprovalRequired",
    "PolicyViolation",
    "agentfox_input_guardrail",
    "agentfox_output_guardrail",
    "agentfox_tool_guardrail",
    "guard_tool",
    "guarded_function_tool",
    "input_text",
    "openai_agents_available",
    "output_text",
]
