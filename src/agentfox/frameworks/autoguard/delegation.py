"""Tool calls that are an agent's own parts, not capabilities.

Agent frameworks give a model more than its tools as tools:

* **Hand-offs** move the conversation to another agent of the same system: the
  OpenAI Agents SDK's ``transfer_to_<agent>``, LangGraph supervisor/swarm handoff
  tools, CrewAI's "Delegate work to coworker".
* **Agents as tools** run a sub-agent and hand its answer back: the Agents SDK's
  ``agent.as_tool(...)``, AutoGen's ``AgentTool`` / ``TeamTool``.
* **Output tools** are how a framework gets structured output out of the model:
  pydantic-ai's ``final_result`` (any ``output_type=`` agent). They reach nothing.

Decided as tool calls, each needs a capability grant: a first run reads as "tried to
X without permission", and once the agent holds any grant they are refused. A
hand-off or an agent-as-tool is recorded as what it is instead, a delegation (a
``subagent`` span and a ``delegates_to`` edge, with discovery's relation vocabulary,
`discovery.agents.RELATIONS`); the agent it reaches is governed on its own model
calls and tools. An output tool is not decided at all; what it carries is the
answer, checked as the model's output.

**Which agent is running.** After a hand-off the calls belong to the agent handed to,
not to the one `auto()` names: the FAQ agent's own lookup tool is the FAQ agent's,
and crediting it to the triage agent read as "triage tried a tool without
permission". Where the framework knows the agent running a model call, that agent is
credited (`agent_for`): the Agents SDK's current agent span (read as its models are
called), a LangGraph supervisor or swarm member (the graph namespace the call runs
in), a CrewAI agent running its task. The agent the system starts with is credited
to the name `auto()` was given, so a one-agent app and the entry agent keep one name.

The names are learned from the frameworks' own objects as they turn them into tools
for a request (`watch`). A framework imported after `auto()` (``auto()`` is the first
line of the file) is watched as it is imported (`_ImportWatch`), so the first
request is already known.
"""

from __future__ import annotations

import contextvars
import functools
import importlib.abc
import importlib.util
import inspect
import logging
import re
import sys
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("agentfox.auto")

#: Tool name -> (the agent it reaches, relation). Learned from framework objects.
DELEGATION_TOOLS: dict[str, tuple[str, str]] = {}

#: Names of tools a framework gives its model only to return structured output.
OUTPUT_TOOLS: set[str] = set()

#: The framework agent running the current model call or tool, when the framework says
#: (`_sdk_scope`, `crew_scope`). LangGraph's is read from the graph's own context.
_ACTIVE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agentfox_active_agent", default=None
)

#: Framework agents first seen running without anything having handed off to them:
#: the system's entry agent, credited to the name `auto()` was given.
_ROOTS: set[str] = set()

#: CrewAI agents that are members of a crew of several: each is credited by name.
_MEMBERS: set[str] = set()

#: The Agents SDK's default hand-off description (`Handoff.default_tool_description`),
#: for a hand-off converted before its converter was watched.
_AGENTS_SDK_HANDOFF = re.compile(r"^Handoff to the (?P<agent>.+?) agent to handle the request\.")


def handoff_of(name: str, spec: dict[str, Any] | None) -> tuple[str, str] | None:
    """(target agent, relation) when the tool call `name` delegates to another agent
    (a hand-off or an agent used as a tool), else None."""
    known = DELEGATION_TOOLS.get(name)
    if known:
        return known
    match = _AGENTS_SDK_HANDOFF.match(str((spec or {}).get("description") or ""))
    if match:
        # Known from here on, so its tool message in the next request is known too.
        _learn(name, match.group("agent"), "handoff")
        return match.group("agent"), "handoff"
    return None


def is_output_tool(name: str) -> bool:
    """Whether `name` is a framework's structured-output tool (pydantic-ai's
    ``final_result``)."""
    return name in OUTPUT_TOOLS


def is_handoff_message(name: str | None) -> bool:
    """A tool message produced by a hand-off: the framework's acknowledgement, not
    content from outside the system (an agent used as a tool returns a sub-agent's
    answer, which is still a tool result)."""
    return bool(name) and DELEGATION_TOOLS.get(str(name), ("", ""))[1] == "handoff"


def handoff_messages(messages: list[Any]) -> dict[str, str]:
    """Message index -> ``user`` for each tool message a hand-off produced, for
    provenance marking: the hand-off carries the conversation the person typed to the
    next agent, and its acknowledgement ("Successfully transferred to ...") is no
    tool's output. Without this the next agent's arguments, all of them copied from
    the person's request, read as copied out of a tool result."""
    from agentfox.capabilities.detection.taint import _calls_in

    produced: dict[str, str] = {}
    out: dict[str, str] = {}
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        for call_id, name in _calls_in(message):
            if call_id:
                produced[call_id] = name
        if str(message.get("role")) in ("tool", "function"):
            name = produced.get(str(message.get("tool_call_id"))) or message.get("name")
            if is_handoff_message(name):
                out[str(i)] = "user"
    return out


def learn_handoff(name: str, target: str) -> None:
    """A hand-off seen where it runs (a LangGraph handoff tool), so the model requests
    that follow know its tool message."""
    _learn(name, target, "handoff")


def lc_handoff(tool: Any) -> tuple[str, str] | None:
    """A LangChain tool that is a hand-off: LangGraph's supervisor and swarm mark
    theirs with ``metadata["__handoff_destination"]``."""
    destination = (getattr(tool, "metadata", None) or {}).get("__handoff_destination")
    return (str(destination), "handoff") if destination else None


def crew_handoff(tool: Any, arguments: dict[str, Any]) -> tuple[str, str] | None:
    """CrewAI's delegation tools ("Delegate work to coworker", "Ask question to
    coworker"): `BaseAgentTool`s, reached through the structured tool's original."""
    original = getattr(tool, "_original_tool", None) or tool
    if not any(c.__name__ == "BaseAgentTool" for c in type(original).__mro__):
        return None
    return str(arguments.get("coworker") or "coworker"), "delegates"


# -- Which agent is running ----------------------------------------------------------


def _targets() -> set[str]:
    """Every agent something hands off to or runs as a tool, by name."""
    return {target for target, _relation in DELEGATION_TOOLS.values()}


def _slug(name: str) -> str:
    from agentfox.platform.registry.service import slugify

    return slugify(name)


def _langgraph_agent() -> str | None:
    """The LangGraph supervisor or swarm member a call runs in: the outermost node of
    the graph's checkpoint namespace (``"faq_agent:<task>|agent:<task>"``), once the
    graph has handed off between agents. A plain graph's nodes are not agents."""
    try:
        from langchain_core.runnables.config import var_child_runnable_config
    except Exception:
        return None
    config = var_child_runnable_config.get() or {}
    namespace = str(
        (config.get("metadata") or {}).get("langgraph_checkpoint_ns")
        or (config.get("configurable") or {}).get("checkpoint_ns")
        or ""
    )
    if not namespace:
        return None
    if not _targets():
        return None  # no hand-off anywhere: one agent, whatever its nodes are called
    return namespace.split("|")[0].partition(":")[0] or None


def running_agent() -> str | None:
    """The framework agent running the current call, by the framework's own name, or
    None when no framework says."""
    return _ACTIVE.get() or _langgraph_agent()


def agent_for(default: str) -> str:
    """The registered agent to credit the current call to.

    ``default`` is the agent `auto()` names. The framework agent running the call is
    credited by its own name (slugged, as `agentfox init` registers it) once
    something has handed off to it or it is one member of a crew; the agent a system
    starts with, which nothing handed off to, is ``default``. With no framework
    agent known, ``default``."""
    name = running_agent()
    if not name:
        return default
    slug = _slug(name)
    if slug == default or name in _ROOTS:
        return default
    if name in _MEMBERS or name in _targets():
        return slug
    _ROOTS.add(name)
    return default


class active:
    """``with active(name):`` credits the calls made inside to framework agent
    ``name``. Never fails the call it wraps."""

    def __init__(self, name: Any) -> None:
        self.name = str(name) if name else None
        self.token: contextvars.Token[str | None] | None = None

    def __enter__(self) -> active:
        if self.name:
            self.token = _ACTIVE.set(self.name)
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self.token is not None:
            try:
                _ACTIVE.reset(self.token)
            except ValueError:  # pragma: no cover - exited in another context
                _ACTIVE.set(None)
            self.token = None


def crew_member(agent: Any) -> str | None:
    """A CrewAI agent's name (its role), noted as a crew member when its crew has
    several agents, so each is credited by its own name."""
    role = getattr(agent, "role", None)
    if not role:
        return None
    crew = getattr(agent, "crew", None)
    if len(getattr(crew, "agents", None) or ()) > 1:
        _MEMBERS.add(str(role))
    return str(role)


def _sdk_current_agent() -> str | None:
    """The Agents SDK agent whose turn this is: the current agent (or turn) span, which
    the SDK opens for the running agent whether or not tracing is exported."""
    try:
        from agents.tracing import get_current_span
    except Exception:
        return None
    data = getattr(get_current_span(), "span_data", None)
    kind = type(data).__name__
    if kind == "AgentSpanData":
        return getattr(data, "name", None)
    if kind == "TurnSpanData":
        return getattr(data, "agent_name", None)
    return None


def _scoped(func: Callable[..., Any]) -> Callable[..., Any]:
    """`func` (an Agents SDK model's ``get_response`` / ``stream_response``) run with the
    SDK's current agent as the running agent."""
    if inspect.isasyncgenfunction(func):

        async def scoped_stream(*args: Any, **kwargs: Any) -> Any:
            with active(_sdk_current_agent()):
                async for item in func(*args, **kwargs):
                    yield item

        return scoped_stream
    if inspect.iscoroutinefunction(func):

        async def scoped_call(*args: Any, **kwargs: Any) -> Any:
            with active(_sdk_current_agent()):
                return await func(*args, **kwargs)

        return scoped_call

    def scoped(*args: Any, **kwargs: Any) -> Any:
        with active(_sdk_current_agent()):
            return func(*args, **kwargs)

    return scoped


# -- Learning the names from the frameworks' own objects -----------------------------


def _learn(name: Any, target: Any, relation: str) -> None:
    if name and target:
        DELEGATION_TOOLS[str(name)] = (str(target), relation)


def _sdk_handoff(args: tuple[Any, ...], kwargs: dict[str, Any], _result: Any) -> None:
    """`Converter._convert_handoff_tool(handoff)` / `convert_handoff_tool(handoff)`."""
    handoff = args[1] if len(args) > 1 else kwargs.get("handoff")
    _learn(getattr(handoff, "tool_name", None), getattr(handoff, "agent_name", None), "handoff")


def _sdk_agent_tool(tool: Any) -> None:
    """An Agents SDK `FunctionTool` made by `agent.as_tool(...)`."""
    if getattr(tool, "_is_agent_tool", False):
        agent = getattr(tool, "_agent_instance", None)
        name = getattr(tool, "name", None)
        _learn(name, getattr(agent, "name", None) or name, "as_tool")


def _sdk_tools(args: tuple[Any, ...], kwargs: dict[str, Any], _result: Any) -> None:
    """Responses `Converter.convert_tools(tools, handoffs, ...)`."""
    tools = args[1] if len(args) > 1 else kwargs.get("tools")
    handoffs = args[2] if len(args) > 2 else kwargs.get("handoffs")
    for tool in tools or ():
        _sdk_agent_tool(tool)
    for handoff in handoffs or ():
        _sdk_handoff((None, handoff), {}, None)


def _sdk_tool(args: tuple[Any, ...], kwargs: dict[str, Any], _result: Any) -> None:
    """Chat Completions `Converter.tool_to_openai(tool)`."""
    _sdk_agent_tool(args[1] if len(args) > 1 else kwargs.get("tool"))


def _autogen_tool(tool: Any) -> None:
    """An AutoGen `AgentTool` / `TeamTool` (a `TaskRunnerTool`): it runs the agent or
    team it holds."""
    runner = getattr(tool, "_task_runner", None)
    if runner is not None:
        name = getattr(tool, "name", None)
        _learn(name, getattr(runner, "name", None) or name, "as_tool")


def _autogen_task_runner(args: tuple[Any, ...], kwargs: dict[str, Any], _result: Any) -> None:
    """`TaskRunnerTool.__init__(self, ...)`: an agent or team made into a tool. The
    agents hand their model only the tools' schemas (through a workbench), so this
    is where the object is still seen."""
    if args:
        _autogen_tool(args[0])


def _autogen_tools(args: tuple[Any, ...], kwargs: dict[str, Any], _result: Any) -> None:
    """autogen-ext's per-client `convert_tools(tools)`, for code that hands a model
    client the tool objects themselves."""
    for tool in (args[0] if args else kwargs.get("tools")) or ():
        _autogen_tool(tool)


def _pydantic_ai_request(args: tuple[Any, ...], kwargs: dict[str, Any], result: Any) -> None:
    """`Model.prepare_request(...)` -> (settings, `ModelRequestParameters`): its
    ``output_tools`` are the output tools this request offers."""
    params = result[1] if isinstance(result, tuple) and len(result) > 1 else None
    for tool_def in getattr(params, "output_tools", None) or ():
        if getattr(tool_def, "name", None):
            OUTPUT_TOOLS.add(str(tool_def.name))


#: module -> [(owner attribute or "" for the module itself, attribute, learner)].
_WATCHED: dict[str, list[tuple[str, str, Callable[..., None]]]] = {
    "agents.models.openai_responses": [
        ("Converter", "_convert_handoff_tool", _sdk_handoff),
        ("Converter", "convert_tools", _sdk_tools),
    ],
    "agents.models.chatcmpl_converter": [
        ("Converter", "convert_handoff_tool", _sdk_handoff),
        ("Converter", "tool_to_openai", _sdk_tool),
    ],
    "pydantic_ai.models": [("Model", "prepare_request", _pydantic_ai_request)],
    "autogen_agentchat.tools._task_runner_tool": [
        ("TaskRunnerTool", "__init__", _autogen_task_runner)
    ],
    **{
        f"autogen_ext.models.{client}": [("", "convert_tools", _autogen_tools)]
        for client in (
            "openai._openai_client",
            "anthropic._anthropic_client",
            "ollama._ollama_client",
            "azure._azure_ai_client",
        )
    },
}


def _wrap(owner: Any, attr: str, learn: Callable[..., None], patched: dict[str, Any]) -> None:
    raw = getattr(owner, "__dict__", {}).get(attr)
    is_classmethod = isinstance(raw, classmethod)
    func = raw.__func__ if is_classmethod else raw
    if not callable(func) or getattr(func, "__agentfox__", False):
        return

    def watched(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        try:
            learn(args, kwargs, result)
        except Exception as exc:  # pragma: no cover - learning must not break the call
            log.debug("agentfox: could not read %s.%s: %s", owner, attr, exc)
        return result

    functools.update_wrapper(watched, func)
    watched.__agentfox__ = True  # type: ignore[attr-defined]
    watched.__agentfox_original__ = raw  # type: ignore[attr-defined]
    setattr(owner, attr, classmethod(watched) if is_classmethod else watched)
    name = getattr(owner, "__name__", str(owner))
    patched[f"agent-parts.{name}.{attr}"] = (owner, attr, True)


#: module -> [(class, method)]: the Agents SDK's models, whose calls run with the SDK's
#: current agent as the running agent (`_scoped`).
_SCOPED: dict[str, list[tuple[str, str]]] = {
    "agents.models.openai_responses": [
        ("OpenAIResponsesModel", "get_response"),
        ("OpenAIResponsesModel", "stream_response"),
    ],
    "agents.models.openai_chatcompletions": [
        ("OpenAIChatCompletionsModel", "get_response"),
        ("OpenAIChatCompletionsModel", "stream_response"),
    ],
    "agents.extensions.models.litellm_model": [
        ("LitellmModel", "get_response"),
        ("LitellmModel", "stream_response"),
    ],
}


def _wrap_scope(owner: Any, attr: str, patched: dict[str, Any]) -> None:
    raw = getattr(owner, "__dict__", {}).get(attr)
    if not callable(raw) or getattr(raw, "__agentfox__", False):
        return
    scoped = _scoped(raw)
    functools.update_wrapper(scoped, raw)
    scoped.__agentfox__ = True  # type: ignore[attr-defined]
    scoped.__agentfox_original__ = raw  # type: ignore[attr-defined]
    setattr(owner, attr, scoped)
    patched[f"agent-parts.{getattr(owner, '__name__', owner)}.{attr}"] = (owner, attr, True)


def _watch_module(module_name: str, patched: dict[str, Any]) -> None:
    module = sys.modules.get(module_name)
    if module is None:
        return
    for owner_name, attr, learn in _WATCHED.get(module_name, ()):
        owner = getattr(module, owner_name, None) if owner_name else module
        if owner is not None:
            _wrap(owner, attr, learn, patched)
    for owner_name, attr in _SCOPED.get(module_name, ()):
        owner = getattr(module, owner_name, None)
        if owner is not None:
            _wrap_scope(owner, attr, patched)


def watch(patched: dict[str, Any]) -> None:
    """Watch every framework module already imported; cheap once done."""
    for module_name in {**_WATCHED, **_SCOPED}:
        _watch_module(module_name, patched)


class _ImportWatch(importlib.abc.MetaPathFinder):
    """Watches a framework module as it is imported, so the names its first request
    offers are known before that request is governed."""

    def __init__(self, patched: dict[str, Any]) -> None:
        self.patched = patched
        self._busy = threading.local()

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        watched = fullname in _WATCHED or fullname in _SCOPED
        if not watched or getattr(self._busy, "on", False):
            return None
        self._busy.on = True
        try:
            spec = importlib.util.find_spec(fullname)
        except Exception:  # pragma: no cover - let the normal machinery report it
            return None
        finally:
            self._busy.on = False
        loader = getattr(spec, "loader", None)
        exec_module = getattr(loader, "exec_module", None)
        if spec is None or exec_module is None:
            return None
        patched = self.patched

        def exec_and_watch(module: Any) -> None:
            exec_module(module)
            try:
                _watch_module(fullname, patched)
            except Exception as exc:  # pragma: no cover - never fail the app's import
                log.debug("agentfox: could not watch %s: %s", fullname, exc)

        try:
            loader.exec_module = exec_and_watch
        except Exception:  # pragma: no cover - a loader that cannot be wrapped
            return None
        return spec


_IMPORT_WATCH: _ImportWatch | None = None


def start(patched: dict[str, Any]) -> None:
    """Watch what is imported now and what is imported later."""
    global _IMPORT_WATCH
    watch(patched)
    if _IMPORT_WATCH is None:
        _IMPORT_WATCH = _ImportWatch(patched)
        sys.meta_path.insert(0, _IMPORT_WATCH)


def stop() -> None:
    global _IMPORT_WATCH
    if _IMPORT_WATCH is not None:
        try:
            sys.meta_path.remove(_IMPORT_WATCH)
        except ValueError:  # pragma: no cover
            pass
        _IMPORT_WATCH = None
    DELEGATION_TOOLS.clear()
    OUTPUT_TOOLS.clear()
    _ROOTS.clear()
    _MEMBERS.clear()
