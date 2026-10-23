"""Multi-agent structure, read statically: which agents a repository defines, which
tools each one is handed, and which agent hands work to which.

The repo scanner (:mod:`agentfox.capabilities.discovery.repo`) answers "where does this
code talk to a model". For a multi-agent system that answer is not enough to govern
it: a triage agent that can hand off to a refunds agent is two things with two tool
sets, and a guardrail meant for "the refunds agent and everything it delegates to" has
nothing to attach to until the parts have names. Before this, the only source of that
structure was runtime traffic (``derive_lineage`` turning ``subagent`` spans into
``delegates_to`` edges), so a freshly scanned repository came out as one blob per
directory and the hierarchy appeared only after the system had already run ungoverned.

Same rules as the rest of discovery: **no import, no execution**. Python is read with
``ast``; TypeScript and JavaScript with a small brace-aware reader over the source,
for the one shape that is unambiguous there (OpenAI Agents SDK's ``new Agent({...})``).
A constructor counts only when the file imported it from the framework it belongs to,
because ``Agent`` and ``Crew`` are names any codebase may define for itself.

What is recognised, per framework:

* **OpenAI Agents SDK** — ``Agent(name=..., tools=[...], handoffs=[...])``;
  ``handoff(agent)`` inside ``handoffs``; ``other.as_tool(...)`` inside ``tools``.
* **LangGraph** — ``create_react_agent`` / ``create_agent``; ``create_supervisor``
  (supervisor delegates to each worker); ``create_swarm`` (members, plus
  ``create_handoff_tool(agent_name=...)`` handoffs); ``StateGraph`` nodes, where a node
  is an agent when it *is* one (a react agent, a compiled subgraph), calls one, or binds
  tools to a model, and a node that routes to agent nodes (conditional edges or
  ``Command(goto=...)``) is their supervisor.
* **CrewAI** — ``Agent(role=..., tools=[...])``, ``Crew(agents=[...])`` (members, or
  delegation under a hierarchical process or a ``manager_agent``), ``allow_delegation``,
  and the ``@CrewBase`` class layout (``@agent`` methods, ``agents=self.agents``).
* **AutoGen** — AgentChat's ``AssistantAgent`` and friends with ``tools`` and Swarm
  ``handoffs``; ``RoundRobinGroupChat`` / ``SelectorGroupChat`` / ``Swarm`` /
  ``MagenticOneGroupChat`` teams; AG2's ``GroupChat`` and the ``GroupChatManager``
  that runs it.
* **Google ADK** — ``Agent`` / ``LlmAgent`` ``sub_agents`` and ``AgentTool``, and the
  ``Sequential``/``Parallel``/``Loop`` workflow agents.
* **LangChain (pre-1.0)** — ``create_tool_calling_agent(llm, tools, prompt)`` and the
  other ``create_*_agent`` constructors, ``initialize_agent(tools, llm)``, and the
  ``AgentExecutor(agent=..., tools=...)`` that runs one: executor and agent are one.
* **A hand-written loop** — ``client.chat.completions.create(tools=...)``,
  ``responses.create``, Anthropic's ``messages.create`` and LiteLLM's ``completion``,
  its tools read from the JSON schemas. Counted only when the repository has no
  framework agent: beside one it is a script, a demo or a helper.

Across all of them:

* A typed constructor (``Agent[Context](...)``) is the constructor.
* Lists changed after construction count: ``a.handoffs = [...]``,
  ``a.handoffs.append(x)`` / ``.extend([...])`` / ``.insert(i, x)`` / ``+=``, the same
  for ``tools``, in the agent's file or a wiring module. They add to the agent's.
* A tool list need not be inline: a name bound to a list, a helper of the file whose
  ``return`` is one (``tools=build_tools()``), ``tools or ALL_TOOLS``, ``A if c else
  B``, and a list or helper exactly one other file defines. A list that cannot be read
  adds nothing; it is never reported as a tool named after the helper.
* Tools made by a call (``function_tool(fn)``, ``function_tool(name_override="x")(fn)``,
  imported ``tool(fn)``, ``StructuredTool.from_function(fn)``) are named as the code
  names them, and carry their function's docstring and argument names.
* An agent's ``name=`` may be a module constant; its model (:attr:`AgentSpec.model`) a
  literal, a constant, an f-string of constants, an ``os.getenv`` default, or a
  chat-model object (``ChatOpenAI(model=...)``, ``init_chat_model("openai:gpt-4o")``).
  Anything only running the code would tell, such as a ``build_model()`` helper, is None.
* Test, mock and fixture files (:func:`is_test_path`) are not read for agents or tools.

A variable is resolved to the agent it holds inside its own file first, then by a
repository-wide lookup of that name when exactly one file defines it, which covers the
common ``from .billing import billing_agent`` layout without following imports.
Anything that cannot be resolved is left out rather than guessed: a wrong edge in a
delegation graph widens what an "apply to sub-agents" policy reaches.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: How a parent hands work to a child, strongest claim first: when the same pair is
#: related twice (a crew member that is also the manager's delegate), the first wins.
#:
#: * ``handoff`` — the parent passes the conversation over (OpenAI handoffs, Swarm).
#: * ``as_tool`` — the parent calls the child like a tool and keeps the conversation.
#: * ``delegates`` — the parent decides which child works next (a supervisor, a
#:   hierarchical crew's manager, ADK ``sub_agents``).
#: * ``member`` — the child is one of a team the parent runs (a crew, a group chat, a
#:   graph's agent nodes).
RELATIONS = ("handoff", "as_tool", "delegates", "member")

#: What this module recognises, per framework, in a line each: what `agentfox init`
#: prints under "Missing something?". Keep it in step with the docstring above.
RECOGNISED = (
    ("OpenAI Agents SDK", "Agent(name=..., tools=[...], handoffs=[...]), agent.as_tool(...)"),
    ("LangGraph", "create_react_agent / create_agent, create_supervisor, create_swarm, StateGraph"),
    ("LangChain", "@tool, create_tool_calling_agent / initialize_agent, AgentExecutor"),
    ("CrewAI", "Agent(role=..., tools=[...]), Crew(agents=[...]), @CrewBase"),
    ("AutoGen / AG2", "AssistantAgent(tools=...), group chats, Swarm handoffs"),
    ("Google ADK", "Agent / LlmAgent(sub_agents=[...]), AgentTool, workflow agents"),
    (
        "Hand-written loops",
        "chat.completions.create / responses.create / messages.create / litellm "
        "completion(tools=[...]) with JSON tool schemas",
    ),
    ("TypeScript / JavaScript", "OpenAI Agents SDK new Agent({...})"),
)


@dataclass
class AgentSpec:
    """One agent (or the crew, team or graph that runs several) found in code."""

    #: Unique within one scan and stable across scans while the name is unchanged:
    #: the proposed agent's slug is built from it.
    key: str
    name: str
    framework: str
    #: agent | supervisor | crew | team | graph
    kind: str
    file: str
    line: int
    tools: list[str] = field(default_factory=list)
    #: The model id the code gives it (``model="gpt-4o"``, a module constant, an
    #: ``os.getenv`` default, a chat-model object's ``model=``), or None when the code
    #: does not say it in a way that can be read without running it. Never guessed.
    model: str | None = None
    #: Where a local runner finds the live object: the importable module, the name in
    #: it, and how to use that name — ``object`` (the agent itself), ``factory`` (call
    #: it to get the agent) or ``function`` (it runs a function-calling loop).
    module: str | None = None
    attr: str | None = None
    attr_kind: str | None = None
    #: What each of :attr:`tools` says about itself, where the code says it: the
    #: description (a docstring or ``description=``) and argument names.
    tool_details: list[dict[str, Any]] = field(default_factory=list)
    #: False when the code gives the agent no name of its own (``name=``, ``role=``)
    #: and :attr:`name` is only the variable or function it was found under.
    named: bool = True
    #: The agent's instructions or system prompt, when the code says them as a string
    #: that can be read without running anything. Local only: never serialised, never
    #: part of a submission; a caller may derive a label from it (who the agent serves).
    instructions: str | None = field(default=None, repr=False)

    @property
    def top_dir(self) -> str:
        parts = Path(self.file).parts
        return parts[0] if len(parts) > 1 else "root"

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "framework": self.framework,
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "tools": self.tools,
            "model": self.model,
            "ref": (
                {"module": self.module, "attr": self.attr, "kind": self.attr_kind}
                if self.module and self.attr
                else None
            ),
            "tool_details": self.tool_details,
        }


@dataclass
class AgentEdge:
    """``parent`` hands work to ``child`` (both :attr:`AgentSpec.key`)."""

    parent: str
    child: str
    relation: str

    def to_json(self) -> dict[str, str]:
        return {"parent": self.parent, "child": self.child, "relation": self.relation}


# ---------------------------------------------------------------------------
# Raw extraction — one file at a time, references left unresolved
# ---------------------------------------------------------------------------

#: A reference to an agent, resolved once every file has been read:
#: ("idx", n) a raw definition; ("var", name) a variable or factory function;
#: ("label", text) an agent's or graph node's own name; ("class", name) every
#: ``@agent`` method of a CrewBase class.
Ref = tuple[str, Any]


@dataclass
class _Raw:
    idx: int
    framework: str
    kind: str
    file: str
    line: int
    name: str | None = None
    var: str | None = None
    cls: str | None = None
    tools: list[tuple[str, str]] = field(default_factory=list)  # ("name"|"var", text)
    children: list[tuple[Ref, str]] = field(default_factory=list)
    #: CrewAI: this agent may ask the crew's other members for help.
    allow_delegation: bool = False
    #: AG2: the GroupChat a GroupChatManager runs; its members become the manager's.
    absorbs: Ref | None = None
    #: CrewAI: a crew's ``manager_agent``, who delegates to the crew's ``members``.
    manager: Ref | None = None
    members: list[Ref] = field(default_factory=list)
    #: Set when a raw turns out to be nothing worth reporting (an AG2 GroupChat folded
    #: into its manager, a graph with no agent nodes).
    dropped: bool = False
    #: The model id, when read in this file; else a name imported into this file that
    #: may be a module constant elsewhere (resolved by the repository-wide lookup).
    model: str | None = None
    model_var: str | None = None
    #: The module-level name a runner reaches this agent by, and how (see AgentSpec).
    attr: str | None = None
    attr_kind: str | None = None
    #: The code names the agent itself (see AgentSpec.named), and what it instructs it.
    named: bool = False
    instructions: str | None = None
    #: ``triage.handoffs.append(x)`` / ``a.tools += [...]``: this raw is no agent but
    #: more of the agent ``extends`` names. Its children and tools are that agent's.
    extends: Ref | None = None
    #: LangChain ``AgentExecutor(agent=x)``: the executor and ``x`` are one agent.
    wraps: Ref | None = None
    #: A bare provider-SDK function-calling loop, reported only when the repository
    #: has no framework agent: beside one it is a script, a demo or a helper.
    loop: bool = False


class _Deferred(ast.expr):
    """A list this file does not show: one a call builds (``tools=build_tools()``
    with ``build_tools`` imported; ``kind="call"``) or an imported name on one side of
    ``tools or ALL_TOOLS`` (``kind="list"``). Looked up by name across the repository,
    and never itself taken for a tool."""

    _fields = ()

    def __init__(self, name: str, kind: str = "call") -> None:
        super().__init__()
        self.name = name
        self.kind = kind


@dataclass
class _Node:
    name: str
    #: What the node runs, as an agent reference when it can be one.
    ref: Ref | None
    func: ast.FunctionDef | ast.AsyncFunctionDef | None
    #: Names the node function reads: an agent among them is the agent it runs.
    loads: set[str] = field(default_factory=set)
    #: Tools the node function binds to its model, or None when it binds none.
    bound_tools: list[tuple[str, str]] | None = None


@dataclass
class _Graph:
    raw: int
    file: str
    nodes: dict[str, _Node] = field(default_factory=dict)
    #: (source, target, how) with how in "edge" | "route"
    routes: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class _FileResult:
    file: str
    raws: list[_Raw] = field(default_factory=list)
    graphs: list[_Graph] = field(default_factory=list)
    #: variable -> raw index, for this file
    vars: dict[str, int] = field(default_factory=dict)
    #: function or variable name -> tool name, for this file
    tool_defs: dict[str, str] = field(default_factory=dict)
    #: module-level variable names this file defines (for cross-file lookup)
    exported: set[str] = field(default_factory=set)
    #: `triage = build_triage()` — a variable holding what a factory returns
    aliases: dict[str, str] = field(default_factory=dict)
    #: The importable module this file is (Python only).
    module: str | None = None
    #: tool name -> (description, argument names), for tools this file defines
    tool_info: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
    #: module-level list variable -> the tool references it holds
    tool_lists: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: module-level function -> the tool references in the list it returns
    tool_helpers: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: module-level string constant -> its value (``MODEL = "gpt-4o"``)
    consts: dict[str, str] = field(default_factory=dict)
    #: module-level function -> (description, argument names), and tool name -> the
    #: function in another module it wraps: what `function_tool(mod.fn)` says.
    func_info: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
    tool_fn: dict[str, str] = field(default_factory=dict)


#: Constructor -> (framework, role). Matched on the import-resolved dotted path's root
#: package and final name, so `from crewai import Agent` and `crewai.Agent` both match
#: and a local `Agent` class does not.
_AUTOGEN_CHAT_AGENTS = {
    "AssistantAgent",
    "UserProxyAgent",
    "CodeExecutorAgent",
    "SocietyOfMindAgent",
}
_AG2_AGENTS = {"AssistantAgent", "UserProxyAgent", "ConversableAgent"}
_LC_AGENT_FACTORIES = {
    "create_tool_calling_agent",
    "create_openai_tools_agent",
    "create_openai_functions_agent",
    "create_react_agent",
    "create_structured_chat_agent",
    "create_json_chat_agent",
    "create_xml_agent",
}

#: Where a role's tools and model sit when passed positionally.
_TOOLS_ARG = {"react_agent": 1, "lc_agent": 1, "lc_init": 0}
_MODEL_ARG = {"react_agent": 0, "lc_agent": 0, "lc_init": 1}
#: The keyword each role takes its model by.
_MODEL_KW = {
    "openai_agent": ("model",),
    "adk_agent": ("model",),
    "react_agent": ("model",),
    "supervisor": ("model",),
    "lc_agent": ("llm", "model"),
    "lc_init": ("llm", "model"),
    "crew_agent": ("llm",),
    "autogen_agent": ("model_client", "llm_config"),
    "loop": ("model",),
}
#: Where each framework takes the agent's instructions (its system prompt).
_INSTRUCTION_KW = (
    "instructions",
    "system_prompt",
    "prompt",
    "system_message",
    "state_modifier",
    "backstory",
    "goal",
)
_TOOL_ROLES = (
    "openai_agent",
    "crew_agent",
    "autogen_agent",
    "adk_agent",
    "react_agent",
    "lc_agent",
    "lc_init",
    "lc_executor",
)

#: A provider SDK's own function-calling entry points (`client.<path>(tools=...)`),
#: by the package the file must import for the call to count.
_LOOP_CALLS = {
    "chat.completions.create": ("openai", "OpenAI SDK"),
    "responses.create": ("openai", "OpenAI SDK"),
    "messages.create": ("anthropic", "Anthropic SDK"),
    "completion": ("litellm", "LiteLLM"),
    "acompletion": ("litellm", "LiteLLM"),
}

#: File stems that say nothing about which agent a loop is; its directory names it.
_GENERIC_STEMS = {
    "main",
    "app",
    "agent",
    "agents",
    "__init__",
    "server",
    "index",
    "run",
    "bot",
    "chat",
    "loop",
    "client",
    "api",
}

#: Directories and file names that hold tests, mocks and fixtures. Code there builds
#: stand-in agents and tools; it is left out of agent and tool attribution (but not of
#: the repo scan's own findings, which still read it).
_TEST_DIRS = {"tests", "test", "testing", "mocks", "fixtures", "__tests__", "__mocks__"}
_TEST_FILE = re.compile(
    r"^(?:test_.*\.py|.*_test\.py|conftest\.py|.*\.(?:test|spec)\.(?:[jt]sx?|mjs))$"
)


def is_test_path(rel: str) -> bool:
    """True for a file under a tests/mocks/fixtures directory, or a test file."""
    parts = Path(rel).parts
    return any(p in _TEST_DIRS for p in parts[:-1]) or bool(parts and _TEST_FILE.match(parts[-1]))


def _module_name(rel: str) -> str | None:
    path = Path(rel)
    if path.suffix != ".py":
        return None
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts)


def _constructor(qual: str) -> tuple[str, str] | None:
    root = qual.split(".")[0]
    last = qual.rsplit(".", 1)[-1]
    if root == "agents" and last == "Agent":
        return "OpenAI Agents SDK", "openai_agent"
    if root == "crewai":
        if last == "Agent":
            return "CrewAI", "crew_agent"
        if last == "Crew":
            return "CrewAI", "crew"
    if root == "autogen_agentchat":
        if last in _AUTOGEN_CHAT_AGENTS:
            return "AutoGen", "autogen_agent"
        if last in ("RoundRobinGroupChat", "Swarm"):
            return "AutoGen", "team_member"
        if last in ("SelectorGroupChat", "MagenticOneGroupChat"):
            return "AutoGen", "team_delegates"
    if root in ("autogen", "ag2"):
        if last in _AG2_AGENTS:
            return "AutoGen", "autogen_agent"
        if last == "GroupChat":
            return "AutoGen", "groupchat"
        if last == "GroupChatManager":
            return "AutoGen", "gc_manager"
    if qual.startswith("google.adk"):
        if last in ("Agent", "LlmAgent"):
            return "Google ADK", "adk_agent"
        if last in ("SequentialAgent", "ParallelAgent", "LoopAgent"):
            return "Google ADK", "adk_workflow"
    if root == "langgraph":
        if last == "create_react_agent":
            return "LangGraph", "react_agent"
        if last == "StateGraph":
            return "LangGraph", "graph"
    if root == "langchain" and last == "create_agent":
        return "LangGraph", "react_agent"
    if root in ("langchain", "langchain_classic"):
        # The pre-1.0 agent constructors: `create_*_agent(llm, tools, prompt)`, run
        # by an `AgentExecutor`, and the older `initialize_agent(tools, llm)`.
        if last in _LC_AGENT_FACTORIES:
            return "LangChain", "lc_agent"
        if last == "initialize_agent":
            return "LangChain", "lc_init"
        if last in ("AgentExecutor", "from_agent_and_tools"):
            return "LangChain", "lc_executor"
    if root == "langgraph_supervisor" and last == "create_supervisor":
        return "LangGraph", "supervisor"
    if root == "langgraph_swarm" and last == "create_swarm":
        return "LangGraph", "swarm"
    return None


_TOOL_DECORATORS = ("tool", "function_tool", "mcp.tool", "agent.tool", "register_tool")
_TOOL_CONSTRUCTORS = ("Tool", "StructuredTool", "StructuredTool.from_function", "FunctionTool")

#: Cheap pre-filter, so most of a repository is not parsed a second time: a file has
#: to import one of the frameworks above (every constructor is import-gated anyway) or
#: define a decorated tool an agent in another file may name.
_HINT = re.compile(
    r"(?:from|import)\s+(?:agents|crewai|autogen\w*|ag2|google\.adk|langgraph\w*|langchain\w*"
    r"|openai|anthropic|litellm)\b"
    r"|@openai/agents|@(?:\w+\.)?(?:function_)?tool\b"
    # `triage.handoffs.append(x)` in a file of wiring that imports no framework itself.
    r"|\.(?:handoffs|tools)\s*(?:=|\+=|\.(?:append|extend|insert)\s*\()"
    # `MODEL = os.getenv(...)` in a config module an agent file imports its model from.
    r"|(?m:^[A-Z0-9_]*MODEL[A-Z0-9_]*\s*(?::[^=\n]*)?=)"
)

#: Functions that make a tool out of a function: `function_tool(fn)`, `tool(fn)`,
#: `function_tool(name_override="x")(fn)`. Counted only when imported, since `tool`
#: is a name any codebase may define for itself.
_TOOL_WRAPPERS = ("function_tool", "tool")
#: Parameters a framework fills in, not the model: left out of a tool's argument names.
_CONTEXT_PARAMS = {"self", "cls", "ctx", "context", "run_context", "wrapper", "tool_context"}


def _fn_info(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, list[str]]:
    """A function's description (its docstring's first paragraph) and argument names."""
    doc = (ast.get_docstring(fn) or "").strip().split("\n\n", 1)[0]
    args: list[str] = []
    for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]:
        annotation: ast.AST | None = a.annotation
        if isinstance(annotation, ast.Subscript):
            annotation = annotation.value
        ann = _path(annotation) if annotation is not None else ""
        if a.arg in _CONTEXT_PARAMS or ann.rsplit(".", 1)[-1] in (
            "RunContextWrapper",
            "ToolContext",
            "InjectedToolArg",
        ):
            continue
        args.append(a.arg)
    return " ".join(doc.split())[:300], args


def wrapped_tool(call: ast.Call, imported: set[str]) -> tuple[str, str | None] | None:
    """``(tool name, wrapped function name)`` when ``call`` makes a tool of a function.

    ``function_tool(fn)``, ``function_tool(name_override="x")(fn)``, ``tool(fn)``,
    ``tool("x")(fn)``, ``Tool(name="x", func=fn)``, ``StructuredTool.from_function(fn)``,
    ``FunctionTool(fn)``. The tool's name is the one the code gives it, else the
    function's. ``imported`` is the names the file imports: a bare ``tool`` or
    ``function_tool`` counts only when it is one of them.
    """
    func = call.func
    opts: ast.Call | None = None
    target: ast.AST | None = None
    if isinstance(func, ast.Call):  # curried: function_tool(...)(fn)
        opts, func = func, func.func
        target = call.args[0] if call.args else None
    path = _path(func)
    last = path.rsplit(".", 1)[-1]
    override: str | None = None
    if last in _TOOL_WRAPPERS:
        if path.split(".")[0] not in imported:
            return None
        if opts is None:
            opts = call
            args = list(call.args)
            if args and _str(args[0]) is not None:  # tool("search", fn)
                override = _str(args.pop(0))
            target = args[0] if args else _kw(call, "func")
        else:
            override = _str(opts.args[0]) if opts.args else None
        override = _str(_kw(opts, "name_override", "name")) or override
        if target is None:
            return None  # `@function_tool(name_override="x")`: a decorator, read there
    elif opts is None and (
        path in _TOOL_CONSTRUCTORS
        or any(path.endswith(f".{c}") for c in _TOOL_CONSTRUCTORS)
        or path.endswith("FunctionTool.from_defaults")
    ):
        target = _kw(call, "func", "fn", "coroutine") or (call.args[0] if call.args else None)
        override = _str(_kw(call, "name"))
    else:
        return None
    fn_name = (
        target.id
        if isinstance(target, ast.Name)
        else target.attr
        if isinstance(target, ast.Attribute)
        else None
    )
    name = override or fn_name
    return (name, fn_name) if name else None


def _dict_fields(node: ast.AST | None) -> dict[str, ast.AST]:
    if not isinstance(node, ast.Dict):
        return {}
    return {
        k.value: v
        for k, v in zip(node.keys, node.values, strict=False)
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def schema_tool(node: ast.AST) -> tuple[str, str, list[str]] | None:
    """``(name, description, argument names)`` of a tool written as a JSON schema:
    Chat Completions ``{"type": "function", "function": {...}}``, the Responses API's
    flattened form, or Anthropic's ``{"name": ..., "input_schema": ...}``."""
    entries = _dict_fields(node)
    if not entries:
        return None
    fields: dict[str, ast.AST] = {}
    params: ast.AST | None = None
    if _str(entries.get("type")) == "function":
        inner = _dict_fields(entries.get("function"))
        fields = inner or (entries if "parameters" in entries else {})
        params = fields.get("parameters")
    elif "input_schema" in entries:
        fields, params = entries, entries.get("input_schema")
    name = _str(fields.get("name"))
    if not name:
        return None
    args = list(_dict_fields(_dict_fields(params).get("properties")))
    return name, _str(fields.get("description")) or "", args


def _path(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    else:
        return ""
    return ".".join(reversed(parts))


def _str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _strings(node: ast.AST | None) -> list[str]:
    """Every string literal a node is or lists (``"a"``, ``["a", "b"]``)."""
    if node is None:
        return []
    if (s := _str(node)) is not None:
        return [s]
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return [s for e in node.elts if (s := _str(e)) is not None]
    return []


def _kw(call: ast.Call, *names: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg in names:
            return kw.value
    return None


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    return _path(node)


class _Extractor:
    """Reads one Python file into raw definitions with unresolved references."""

    def __init__(self, tree: ast.Module, rel: str, start: int) -> None:
        self.tree = tree
        self.rel = rel
        self.out = _FileResult(file=rel)
        self.next_idx = start
        self.imports: dict[str, str] = {}
        #: id(call) -> (var, enclosing class) for `x = Call(...)` and `return Call(...)`
        self.call_target: dict[int, tuple[str | None, str | None]] = {}
        #: id(call) -> raw index
        self.call_raw: dict[int, int] = {}
        #: variable -> list literal it was assigned (tools = [a, b])
        self.lists: dict[str, ast.AST] = {}
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        #: id(call) of every `return Crew(...)` inside a CrewBase `@crew` method
        self.crew_methods: set[int] = set()
        #: raw index -> (its constructor call, its role)
        self.made: dict[int, tuple[ast.Call, str]] = {}
        #: Every name an import binds, relative imports included.
        self.imported: set[str] = set()
        #: variable -> dict literal it was assigned (a tool schema named once, listed later)
        self.dicts: dict[str, ast.AST] = {}
        #: every function by name, for the description and arguments of a tool it becomes
        self.defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        #: variable -> the model id of the chat-model object it holds
        self.models: dict[str, str] = {}
        #: id(call) assigned to a module-level name, and id(call) a module-level
        #: function returns -> that function: how a runner reaches the agent.
        self.module_calls: set[int] = set()
        self.factory_calls: dict[int, str] = {}
        #: module-level function -> the module-level name its call is assigned to
        #: (`agent = build_agent()`): the live object a runner can take as it is.
        self.factory_objects: dict[str, str] = {}
        #: id(call) -> the module-level function it sits in
        self.enclosing: dict[int, str] = {}
        #: variable -> every call assigned to it (`tools = build_tools(kit)`)
        self.bound_calls: dict[str, list[ast.Call]] = defaultdict(list)

    # -- pass A: imports, assignments, functions, tools ----------------------

    def collect(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
                    self.imported.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.imported.add(alias.asname or alias.name)
                    if node.module and not node.level:
                        self.imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                self.defs.setdefault(node.name, node)
        self._module_level()
        for stmt in self.tree.body:
            for target in _assigned_names(stmt):
                self.out.exported.add(target)
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                self.out.exported.add(stmt.name)
        self._walk_scope(self.tree.body, cls=None)

    def _module_level(self) -> None:
        """Module-level string constants, the calls bound to module-level names, and
        which module-level function each call sits in."""
        ambiguous: set[str] = set()
        stack = [self.tree.body]
        while stack:
            body = stack.pop(0)
            for stmt in body:
                if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                    for sub in ast.walk(stmt):
                        if isinstance(sub, ast.Call):
                            self.enclosing.setdefault(id(sub), stmt.name)
                        if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
                            self.factory_calls.setdefault(id(sub.value), stmt.name)
                    continue
                if isinstance(stmt, ast.ClassDef):
                    continue
                value = getattr(stmt, "value", None)
                names = (
                    _assigned_names(stmt) if isinstance(stmt, ast.Assign | ast.AnnAssign) else []
                )
                if isinstance(value, ast.Call) and names:
                    self.module_calls.add(id(value))
                    if isinstance(value.func, ast.Name) and body is self.tree.body:
                        self.factory_objects.setdefault(value.func.id, names[0])
                for name in names:
                    if name in ambiguous:
                        continue
                    text = self.resolve_str(value)
                    if text is None or self.out.consts.get(name, text) != text:
                        # Assigned twice differently, or to something unreadable.
                        self.out.consts.pop(name, None)
                        ambiguous.add(name)
                        continue
                    self.out.consts[name] = text
                stack.extend(_child_bodies(stmt))

    def resolve_str(self, node: ast.AST | None, depth: int = 0) -> str | None:
        """The string an expression always is, read without running anything: a
        literal, a module constant, an f-string or ``+`` of those, or the default of
        ``os.getenv("X", "default")`` / ``os.environ.get("X", "default")``. An
        expression with any part that cannot be read is None, never a fragment."""
        if node is None or depth > 6:
            return None
        if (s := _str(node)) is not None:
            return s
        if isinstance(node, ast.Name):
            return self.out.consts.get(node.id)
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    if value.format_spec is not None:
                        return None
                    inner = self.resolve_str(value.value, depth + 1)
                else:
                    inner = _str(value)
                if inner is None:
                    return None
                parts.append(inner)
            return "".join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.resolve_str(node.left, depth + 1)
            right = self.resolve_str(node.right, depth + 1)
            return left + right if left is not None and right is not None else None
        if isinstance(node, ast.Call):
            path = _path(node.func)
            if (
                path in ("os.getenv", "getenv", "os.environ.get", "environ.get")
                and len(node.args) >= 2
            ):
                return self.resolve_str(node.args[1], depth + 1)
            if path in ("os.getenv", "os.environ.get") and (d := _kw(node, "default")):
                return self.resolve_str(d, depth + 1)
        return None

    def model_of(self, node: ast.AST | None) -> tuple[str | None, str | None]:
        """``(model id, imported name to look up elsewhere)`` for an agent's model
        argument: a string, a constant, a chat-model object or a variable holding one,
        ``llm or "gpt-4o"`` (the one readable side), an AutoGen ``llm_config``."""
        if node is None:
            return None, None
        if (s := self.resolve_str(node)) is not None:
            return s, None
        if isinstance(node, ast.Name):
            if node.id in self.models:
                return self.models[node.id] or None, None
            if node.id in self.imported:
                return None, node.id
            return None, None
        if isinstance(node, ast.Call):
            return self._chat_model(node), None
        if isinstance(node, ast.BoolOp | ast.IfExp):
            sides = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
            found = {m for side in sides if (m := self.model_of(side)[0])}
            return (found.pop() if len(found) == 1 else None), None
        if isinstance(node, ast.Dict):  # AutoGen llm_config={"model": ...}
            fields = _dict_fields(node)
            if "model" in fields:
                return self.model_of(fields["model"])
            configs = fields.get("config_list")
            if isinstance(configs, ast.List) and configs.elts:
                found = {m for e in configs.elts if (m := self.model_of(e)[0])}
                return (found.pop() if len(found) == 1 else None), None
        return None, None

    def _chat_model(self, call: ast.Call) -> str | None:
        """``ChatOpenAI(model="gpt-4o")``, ``init_chat_model("openai:gpt-4o")``,
        ``LitellmModel(model=...)``, ``OpenAIChatCompletionClient(model=...)``: a model
        object from an imported class or function. A local helper (``build_model()``)
        is not read: what it returns depends on its arguments."""
        path = _path(call.func)
        if not path or path.split(".")[0] not in self.imported:
            return None
        node = _kw(call, "model", "model_name", "model_id")
        if node is None and path.rsplit(".", 1)[-1] in ("init_chat_model", "LLM") and call.args:
            node = call.args[0]
        return self.resolve_str(node)

    def _walk_scope(self, body: list[ast.stmt], cls: str | None) -> None:
        for stmt in body:
            if isinstance(stmt, ast.ClassDef):
                self._walk_scope(stmt.body, cls=stmt.name)
                continue
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                self.functions.setdefault(stmt.name, stmt)
                self._check_tool(stmt)
                decorators = {_decorator_name(d).rsplit(".", 1)[-1] for d in stmt.decorator_list}
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
                        # `def researcher(self): return Agent(...)` — the agent is named
                        # by its factory, which is how CrewBase and most builders work.
                        self.call_target.setdefault(id(sub.value), (stmt.name, cls))
                        if "crew" in decorators:
                            self.crew_methods.add(id(sub.value))
                self._walk_scope(stmt.body, cls=cls)
                continue
            self._note_assign(stmt, cls)
            for child_body in _child_bodies(stmt):
                self._walk_scope(child_body, cls=cls)

    def _note_assign(self, stmt: ast.stmt, cls: str | None) -> None:
        value: ast.AST | None = None
        targets: list[str] = []
        if isinstance(stmt, ast.Assign):
            value = stmt.value
            targets = [_target_name(t) for t in stmt.targets]
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            value = stmt.value
            targets = [_target_name(stmt.target)]
        targets = [t for t in targets if t]
        if value is None or not targets:
            return
        var = targets[0]
        if isinstance(value, ast.Call):
            self.call_target[id(value)] = (var, cls)
            self.bound_calls[var].append(value)
            if isinstance(value.func, ast.Name):
                self.out.aliases.setdefault(var, value.func.id)
            path = _path(value.func)
            made = wrapped_tool(value, self.imported)
            if made is not None:
                # `lookup = function_tool(fetch)`: the tool is named by the code or by
                # the function, and says what the function's docstring says.
                self.out.tool_defs[var] = made[0]
                self._note_info(made[0], made[1], value)
            elif path in _TOOL_CONSTRUCTORS or any(
                path.endswith(f".{c}") for c in _TOOL_CONSTRUCTORS
            ):
                name = _str(_kw(value, "name"))
                if name:
                    self.out.tool_defs[var] = name
            model = self._chat_model(value)
            if model is not None:
                if self.models.get(var, model) != model:
                    self.models[var] = ""  # two models under one name: neither
                else:
                    self.models[var] = model
        elif isinstance(value, ast.List | ast.Tuple):
            self.lists[var] = value
        elif isinstance(value, ast.Dict):
            self.dicts[var] = value

    def _note_info(self, name: str, fn_name: str | None, call: ast.Call | None) -> None:
        """Record what a tool says about itself, from its function and its options."""
        if name in self.out.tool_info:
            return
        doc, args = "", list[str]()
        if fn_name and fn_name in self.defs:
            doc, args = _fn_info(self.defs[fn_name])
        if call is not None:
            opts = call.func if isinstance(call.func, ast.Call) else call
            doc = _str(_kw(opts, "description_override", "description")) or doc
        if doc or args:
            self.out.tool_info[name] = (doc, args)
        elif fn_name and fn_name not in self.defs:
            # `function_tool(tools.get_ticket)`: the function lives in another module.
            self.out.tool_fn.setdefault(name, fn_name)

    def _check_tool(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in fn.decorator_list:
            name = _decorator_name(decorator)
            if any(name.endswith(marker) for marker in _TOOL_DECORATORS):
                explicit = None
                if isinstance(decorator, ast.Call) and decorator.args:
                    explicit = _str(decorator.args[0])
                if isinstance(decorator, ast.Call):
                    explicit = explicit or _str(_kw(decorator, "name_override", "name"))
                self.out.tool_defs[fn.name] = explicit or fn.name
                self._note_info(
                    explicit or fn.name,
                    fn.name,
                    decorator if isinstance(decorator, ast.Call) else None,
                )
                return

    # -- pass B: one raw per recognised constructor -------------------------

    def qual(self, func: ast.AST) -> str:
        # `Agent[Context](...)`: the type parameter wraps the constructor being called.
        if isinstance(func, ast.Subscript):
            func = func.value
        path = _path(func)
        if not path:
            return ""
        head, _, rest = path.partition(".")
        base = self.imports.get(head)
        if base is None:
            return ""
        return f"{base}.{rest}" if rest else base

    def create(self) -> None:
        loop: _Raw | None = None
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            match = _constructor(self.qual(node.func))
            if match is None:
                if _kw(node, "tools") is not None:
                    loop = self._loop(node, loop)
                continue
            framework, role = match
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            # `agents` is also the name of plenty of local packages; the SDK's Agent is
            # always given a name, and an instruction, tools or handoffs besides.
            if role == "openai_agent" and not (
                "name" in kwargs and kwargs & {"instructions", "tools", "handoffs", "model"}
            ):
                continue
            var, cls = self.call_target.get(id(node), (None, None))
            raw = _Raw(
                idx=self.next_idx,
                framework=framework,
                kind=_KIND[role],
                file=self.rel,
                line=node.lineno,
                var=var,
                cls=cls,
            )
            raw.name = self._name(node, role, var, cls)
            raw.named = raw.name is not None and raw.name not in (var, cls)
            raw.instructions = self.resolve_str(_kw(node, *_INSTRUCTION_KW))
            model_node = _kw(node, *_MODEL_KW.get(role, ()))
            if model_node is None and role in _MODEL_ARG and len(node.args) > _MODEL_ARG[role]:
                model_node = node.args[_MODEL_ARG[role]]
            raw.model, raw.model_var = self.model_of(model_node)
            if cls is None and id(node) in self.module_calls:
                raw.attr, raw.attr_kind = var, "object"
            elif id(node) in self.factory_calls:
                factory = self.factory_calls[id(node)]
                # `agent = build_agent()` at module level: the module already builds it.
                if factory in self.factory_objects:
                    raw.attr, raw.attr_kind = self.factory_objects[factory], "object"
                else:
                    raw.attr, raw.attr_kind = factory, "factory"
            self.next_idx += 1
            self.call_raw[id(node)] = raw.idx
            self.out.raws.append(raw)
            if var:
                self.out.vars.setdefault(var, raw.idx)
            self.made[raw.idx] = (node, role)

    def _loop(self, call: ast.Call, loop: _Raw | None) -> _Raw | None:
        """``client.chat.completions.create(..., tools=TOOLS)`` and its Anthropic and
        LiteLLM equivalents: a hand-written agent loop. One per file, its tools the
        union of every such call's; reported only if the repository has no framework
        agent (see :class:`_Linker`)."""
        path = _path(call.func)
        hit = next(
            (
                v
                for suffix, v in _LOOP_CALLS.items()
                if path == suffix or path.endswith(f".{suffix}")
            ),
            None,
        )
        if hit is None:
            return loop
        package, framework = hit
        if not any(v.split(".")[0] == package for v in self.imports.values()):
            return loop
        if loop is None:
            stem = Path(self.rel).stem
            parent = Path(self.rel).parent.name
            name = parent if stem in _GENERIC_STEMS and parent else stem
            loop = _Raw(
                idx=self.next_idx,
                framework=framework,
                kind="agent",
                file=self.rel,
                line=call.lineno,
                name=name,
                loop=True,
            )
            func = self.enclosing.get(id(call))
            if func:
                loop.attr, loop.attr_kind = func, "function"
            self.next_idx += 1
            self.out.raws.append(loop)
            self.made[loop.idx] = (call, "loop")
        if loop.model is None:
            loop.model, loop.model_var = self.model_of(_kw(call, "model"))
        self._tools(loop, _kw(call, "tools"))
        return loop

    def _label(self, node: ast.AST | None) -> str | None:
        """A name the code gives: a literal or a module-level string constant."""
        return self.resolve_str(node) if isinstance(node, ast.Constant | ast.Name) else None

    def _name(self, call: ast.Call, role: str, var: str | None, cls: str | None) -> str | None:
        if role == "crew_agent":
            return self._label(_kw(call, "role")) or var
        if role == "crew":
            if id(call) in self.crew_methods and cls:
                return cls
            return self._label(_kw(call, "name")) or var
        if role == "autogen_agent":
            first = call.args[0] if call.args else None
            return self._label(_kw(call, "name")) or self._label(first) or var
        if role == "supervisor":
            return self._label(_kw(call, "supervisor_name")) or "supervisor"
        if role == "graph":
            return var
        return self._label(_kw(call, "name")) or var

    # -- pass C: tools and children -----------------------------------------

    def link(self) -> None:
        for raw in list(self.out.raws):
            call, role = self.made[raw.idx]
            if role in _TOOL_ROLES:
                tools_expr = _kw(call, "tools")
                if tools_expr is None and role in _TOOLS_ARG and len(call.args) > _TOOLS_ARG[role]:
                    tools_expr = call.args[_TOOLS_ARG[role]]
                self._tools(raw, tools_expr)
            if role == "lc_executor":
                inner = _kw(call, "agent") or (call.args[0] if call.args else None)
                raw.wraps = self._ref(inner) if inner is not None else None
            if role == "openai_agent":
                self._handoffs(raw, _kw(call, "handoffs"))
            elif role == "crew_agent":
                delegation = _kw(call, "allow_delegation")
                raw.allow_delegation = isinstance(delegation, ast.Constant) and bool(
                    delegation.value
                )
            elif role == "crew":
                manager = _kw(call, "manager_agent")
                process = _path(_kw(call, "process") or ast.Constant(None))
                members = [
                    ("class", raw.cls) if ref[0] == "class" else ref
                    for elt in self._elements(_kw(call, "agents"))
                    if (ref := self._ref(elt)) is not None
                ]
                if manager is not None:
                    # crew -> its manager -> the members the manager assigns work to.
                    raw.manager = self._ref(manager)
                    raw.members = members
                else:
                    # A hierarchical crew without a named manager gets one from CrewAI
                    # itself, so the crew decides who works next rather than just
                    # running them in order.
                    relation = "delegates" if process.endswith("hierarchical") else "member"
                    raw.children.extend((m, relation) for m in members)
            elif role == "autogen_agent":
                for label in _strings(_kw(call, "handoffs")):
                    raw.children.append((("label", label), "handoff"))
                for elt in self._elements(_kw(call, "handoffs")):
                    if isinstance(elt, ast.Call):
                        target = _str(_kw(elt, "target")) or (
                            _str(elt.args[0]) if elt.args else None
                        )
                        if target:
                            raw.children.append((("label", target), "handoff"))
            elif role in ("team_member", "team_delegates"):
                members = _kw(call, "participants") or (call.args[0] if call.args else None)
                for elt in self._elements(members):
                    self._child(raw, elt, "member" if role == "team_member" else "delegates")
            elif role == "groupchat":
                members = _kw(call, "agents") or (call.args[0] if call.args else None)
                for elt in self._elements(members):
                    self._child(raw, elt, "delegates")
            elif role == "gc_manager":
                group = _kw(call, "groupchat") or (call.args[0] if call.args else None)
                raw.absorbs = self._ref(group) if group is not None else None
            elif role in ("adk_agent", "adk_workflow"):
                relation = "delegates" if role == "adk_agent" else "member"
                for elt in self._elements(_kw(call, "sub_agents")):
                    self._child(raw, elt, relation)
            elif role in ("supervisor", "swarm"):
                members = _kw(call, "agents") or (call.args[0] if call.args else None)
                for elt in self._elements(members):
                    self._child(raw, elt, "delegates" if role == "supervisor" else "member")
                if role == "supervisor":
                    self._tools(raw, _kw(call, "tools"))
            elif role == "graph":
                self._graph(raw)

    def _handoffs(self, raw: _Raw, expr: ast.AST | None) -> None:
        """OpenAI Agents SDK hand-offs: agents, and ``handoff(agent)`` /
        ``handoff(agent=x, on_handoff=...)`` wrapping one."""
        for elt in self._elements(expr):
            if isinstance(elt, ast.Call) and _path(elt.func).rsplit(".", 1)[-1] == "handoff":
                elt = elt.args[0] if elt.args else _kw(elt, "agent")
            self._child(raw, elt, "handoff")

    # -- pass D: an agent's lists changed after it was built ----------------

    def mutate(self) -> None:
        """``a.handoffs = [...]``, ``a.handoffs.append(x)`` / ``.extend([...])`` /
        ``.insert(i, x)``, ``a.handoffs += [...]``, and the same for ``tools``. Each is
        recorded against the variable it changes and joined to that agent once every
        file is read, so wiring in its own module counts too. Hand-offs added this way
        are added to the agent's, never instead of them."""
        for node in ast.walk(self.tree):
            owner: ast.AST | None = None
            attr = ""
            value: ast.AST | None = None
            if isinstance(node, ast.Assign | ast.AugAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if isinstance(node, ast.AugAssign) and not isinstance(node.op, ast.Add):
                    continue
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr in ("handoffs", "tools"):
                        owner, attr, value = target.value, target.attr, node.value
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("append", "extend", "insert")
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr in ("handoffs", "tools")
            ):
                owner, attr = node.func.value.value, node.func.value.attr
                args = node.args[1:] if node.func.attr == "insert" else node.args[:1]
                if not args:
                    continue
                value = args[0] if node.func.attr == "extend" else ast.List(elts=[args[0]])
            if owner is None or value is None:
                continue
            ref = self._ref(owner) if isinstance(owner, ast.Name | ast.Attribute) else None
            if ref is None or ref[0] != "var":
                continue
            if ref[1] not in self.out.vars and ref[1] not in self.imported:
                # Neither an agent of this file nor a name imported into it: some other
                # object with a `tools` list, not an agent elsewhere that shares a name.
                continue
            change = _Raw(
                idx=self.next_idx,
                framework="",
                kind="change",
                file=self.rel,
                line=getattr(node, "lineno", 0),
                dropped=True,
                extends=ref,
            )
            self.next_idx += 1
            if attr == "handoffs":
                self._handoffs(change, value)
            else:
                self._tools(change, value)
            if change.children or change.tools:
                self.out.raws.append(change)

    # -- pass E: what other files may look up by name ------------------------

    def export(self) -> None:
        """Module-level tool lists and list-returning helpers, as tool references, for
        an agent in another file that names them (``tools=ALL_TOOLS``,
        ``tools=build_tools()`` after ``from .tools import ...``), and what each
        module-level function says about itself, for a tool another file makes of it."""
        for stmt in self.tree.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                doc, args = _fn_info(stmt)
                if doc or args:
                    self.out.func_info.setdefault(stmt.name, (doc, args))
        for var, value in self.lists.items():
            if var in self.out.exported:
                probe = _Raw(idx=-1, framework="", kind="", file="", line=0)
                self._tools(probe, value)
                if probe.tools:
                    self.out.tool_lists[var] = probe.tools
        for stmt in self.tree.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                seq = self._returned(stmt, 0)
                if seq:
                    probe = _Raw(idx=-1, framework="", kind="", file="", line=0)
                    self._tool_elements(probe, seq)
                    if probe.tools:
                        self.out.tool_helpers[stmt.name] = probe.tools

    def _elements(self, expr: ast.AST | None) -> list[ast.AST]:
        if expr is None:
            return []
        seq = self._sequence(expr, 0)
        return seq if seq is not None else [expr]

    def _sequence(self, expr: ast.AST, depth: int) -> list[ast.AST] | None:
        """The elements of ``expr`` when it is a list this file shows, else None.

        A literal, ``a + b``, a name bound to one, ``tools or ALL_TOOLS`` and
        ``A if c else B`` (every side that is a list), and a call to a function of this
        file whose ``return`` is one. A call to anything else is a list this file does
        not show: it stands as a :class:`_Deferred` the repository-wide lookup may
        resolve, and is never itself taken for a tool or an agent.
        """
        if depth > 4:
            return None
        if isinstance(expr, ast.List | ast.Tuple | ast.Set):
            out: list[ast.AST] = []
            for elt in expr.elts:
                if isinstance(elt, ast.Starred):
                    out.extend(self._sequence(elt.value, depth + 1) or [elt.value])
                else:
                    out.append(elt)
            return out
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            left = self._sequence(expr.left, depth + 1)
            right = self._sequence(expr.right, depth + 1)
            return (left or [expr.left]) + (right or [expr.right])
        if isinstance(expr, ast.Name) and expr.id in self.lists:
            return self._sequence(self.lists[expr.id], depth + 1)
        if isinstance(expr, ast.Name) and len(self.bound_calls.get(expr.id, ())) == 1:
            # `tools = build_tools(kit)` then `tools=tools`: what that helper of this
            # file returns. Bound to anything else, the name is left as it was.
            call = self.bound_calls[expr.id][0]
            func = call.func
            if isinstance(func, ast.Name) and func.id in self.functions:
                return self._returned(self.functions[func.id], depth + 1) or []
            return None
        if isinstance(expr, ast.BoolOp | ast.IfExp):
            sides = expr.values if isinstance(expr, ast.BoolOp) else [expr.body, expr.orelse]
            found: list[list[ast.AST]] = []
            for side in sides:
                seq = self._sequence(side, depth + 1)
                if seq is None and isinstance(side, ast.Name) and side.id in self.imported:
                    seq = [_Deferred(side.id, "list")]  # a list another module holds
                if seq is not None:
                    found.append(seq)
            # A side that is no list this file shows (a `tools` parameter) adds nothing.
            return [e for s in found for e in s] if found else None
        if isinstance(expr, ast.Call) and id(expr) not in self.call_raw:
            func = expr.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute) and _path(func.value) == "self":
                name = func.attr
            if name and name in self.functions:
                return self._returned(self.functions[name], depth + 1) or []
            if (
                isinstance(func, ast.Name | ast.Attribute)
                and wrapped_tool(expr, self.imported) is None
            ):
                return [_Deferred(name or _path(func).rsplit(".", 1)[-1])]
        return None

    def _returned(
        self, fn: ast.FunctionDef | ast.AsyncFunctionDef, depth: int
    ) -> list[ast.AST] | None:
        out: list[ast.AST] | None = None
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Return) and sub.value is not None:
                seq = self._sequence(sub.value, depth + 1)
                if seq is not None:
                    out = (out or []) + seq
        return out

    def _ref(self, expr: ast.AST | None) -> Ref | None:
        if expr is None:
            return None
        if isinstance(expr, ast.Call):
            if id(expr) in self.call_raw:
                return ("idx", self.call_raw[id(expr)])
            func = expr.func
            if isinstance(func, ast.Name):
                return ("var", func.id)
            if isinstance(func, ast.Attribute) and _path(func.value) == "self":
                return ("var", func.attr)
            return None
        if isinstance(expr, ast.Name):
            return ("var", expr.id)
        if isinstance(expr, ast.Attribute):
            if _path(expr.value) == "self":
                return ("class", None) if expr.attr == "agents" else ("var", expr.attr)
            return ("var", expr.attr)
        if (s := _str(expr)) is not None:
            return ("label", s)
        return None

    def _child(self, raw: _Raw, expr: ast.AST | None, relation: str) -> None:
        ref = self._ref(expr)
        if ref is None:
            return
        if ref[0] == "class":
            ref = ("class", raw.cls)
        raw.children.append((ref, relation))

    def _tools(self, raw: _Raw, expr: ast.AST | None) -> None:
        self._tool_elements(raw, self._elements(expr))

    def _tool_elements(self, raw: _Raw, elements: list[ast.AST]) -> None:
        for elt in elements:
            if isinstance(elt, _Deferred):
                raw.tools.append((elt.kind, elt.name))
                continue
            if isinstance(elt, ast.Dict):
                schema = schema_tool(elt)
                if schema is not None:
                    raw.tools.append(("name", schema[0]))
                    self.out.tool_info.setdefault(schema[0], (schema[1], schema[2]))
                continue
            if isinstance(elt, ast.Name) and elt.id in self.dicts:
                self._tool_elements(raw, [self.dicts[elt.id]])
                continue
            if isinstance(elt, ast.Call):
                made = wrapped_tool(elt, self.imported)
                if made is not None:
                    # `function_tool(fn)`, `function_tool(needs_approval=True)(mod.fn)`
                    self._note_info(made[0], made[1], elt)
                    if made[1] and made[0] == made[1]:
                        raw.tools.append(("var", made[1]))  # may be named elsewhere
                    else:
                        raw.tools.append(("name", made[0]))
                    continue
                path = _path(elt.func)
                last = path.rsplit(".", 1)[-1]
                if last in ("as_tool", "asTool") and isinstance(elt.func, ast.Attribute):
                    self._child(raw, elt.func.value, "as_tool")
                    continue
                if last == "AgentTool":
                    self._child(
                        raw, _kw(elt, "agent") or (elt.args[0] if elt.args else None), "as_tool"
                    )
                    continue
                if last == "create_handoff_tool":
                    target = _str(_kw(elt, "agent_name")) or (
                        _str(elt.args[0]) if elt.args else None
                    )
                    if target:
                        raw.children.append((("label", target), "handoff"))
                    continue
                if last in ("function_tool", "tool", "FunctionTool") and (elt.args or elt.keywords):
                    inner = elt.args[0] if elt.args else _kw(elt, "func")
                    name = _str(_kw(elt, "name", "name_override"))
                    if name:
                        raw.tools.append(("name", name))
                    elif isinstance(inner, ast.Name):
                        raw.tools.append(("var", inner.id))
                    continue
                name = _str(_kw(elt, "name"))
                if name and (path in _TOOL_CONSTRUCTORS or last in _TOOL_CONSTRUCTORS):
                    raw.tools.append(("name", name))
                elif last:
                    # `SerperDevTool()` — a library tool, named by its class.
                    raw.tools.append(("name", last))
            elif isinstance(elt, ast.Name):
                raw.tools.append(("var", elt.id))
            elif isinstance(elt, ast.Attribute):
                raw.tools.append(("var", elt.attr))
            elif (s := _str(elt)) is not None:
                raw.tools.append(("name", s))

    # -- LangGraph StateGraph ------------------------------------------------

    def _graph(self, raw: _Raw) -> None:
        graph = _Graph(raw=raw.idx, file=self.rel)
        names = {raw.var} if raw.var else set()
        if not names:
            return
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = _path(node.func.value)
            method = node.func.attr
            if receiver not in names:
                continue
            if method == "add_node":
                self._add_node(graph, node)
            elif method == "add_edge" and len(node.args) >= 2:
                for src in _node_names(node.args[0]):
                    for dst in _node_names(node.args[1]):
                        graph.routes.append((src, dst, "edge"))
            elif method == "add_conditional_edges" and node.args:
                sources = _node_names(node.args[0])
                path_map = _kw(node, "path_map") or (node.args[2] if len(node.args) > 2 else None)
                targets: list[str] = []
                if isinstance(path_map, ast.Dict):
                    targets = [s for v in path_map.values if (s := _str(v)) is not None]
                else:
                    targets = _strings(path_map)
                if not targets:
                    router = _kw(node, "path") or (node.args[1] if len(node.args) > 1 else None)
                    if isinstance(router, ast.Name) and router.id in self.functions:
                        targets = _returned_strings(self.functions[router.id])
                for src in sources:
                    for dst in targets:
                        graph.routes.append((src, dst, "route"))
            elif method == "compile":
                name = _str(_kw(node, "name"))
                if name:
                    raw.name = name
                var, _ = self.call_target.get(id(node), (None, None))
                if var:
                    self.out.vars.setdefault(var, raw.idx)
                    if id(node) in self.module_calls:
                        raw.attr, raw.attr_kind = var, "object"
        for gname, gnode in graph.nodes.items():
            if gnode.func is not None:
                for dst in _goto_strings(gnode.func):
                    graph.routes.append((gname, dst, "route"))
                gnode.bound_tools = self._bound_tools(gnode.func)
                gnode.loads = _loaded_names(gnode.func)
        self.out.graphs.append(graph)

    def _add_node(self, graph: _Graph, call: ast.Call) -> None:
        if not call.args:
            return
        first = call.args[0]
        name = _str(first)
        value: ast.AST | None
        if name is not None:
            value = call.args[1] if len(call.args) > 1 else _kw(call, "action", "node")
        elif isinstance(first, ast.Name):
            name, value = first.id, first
        else:
            return
        func = None
        if isinstance(value, ast.Name) and value.id in self.functions:
            func = self.functions[value.id]
        graph.nodes[name] = _Node(name=name, ref=self._ref(value), func=func)

    def _bound_tools(self, fn: ast.AST) -> list[tuple[str, str]] | None:
        """The tools a node function binds to its model, or None when it binds none."""
        for sub in ast.walk(fn):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "bind_tools"
            ):
                probe = _Raw(idx=-1, framework="", kind="", file="", line=0)
                self._tools(probe, sub.args[0] if sub.args else _kw(sub, "tools"))
                return probe.tools
        return None


_KIND = {
    "openai_agent": "agent",
    "crew_agent": "agent",
    "crew": "crew",
    "autogen_agent": "agent",
    "team_member": "team",
    "team_delegates": "team",
    "groupchat": "team",
    "gc_manager": "supervisor",
    "adk_agent": "agent",
    "adk_workflow": "team",
    "react_agent": "agent",
    "lc_agent": "agent",
    "lc_init": "agent",
    "lc_executor": "agent",
    "graph": "graph",
    "supervisor": "supervisor",
    "swarm": "team",
}


def _target_name(target: ast.AST) -> str:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute) and _path(target.value) == "self":
        return target.attr
    return ""


def _assigned_names(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.Assign):
        return [n for t in stmt.targets if (n := _target_name(t))]
    if isinstance(stmt, ast.AnnAssign):
        return [n] if (n := _target_name(stmt.target)) else []
    return []


def _child_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Nested statement lists (if/with/try/for bodies) that are still the same scope."""
    out: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        value = getattr(stmt, attr, None)
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            out.append(value)
    for handler in getattr(stmt, "handlers", []) or []:
        out.append(handler.body)
    return out


def _node_names(expr: ast.AST) -> list[str]:
    """A graph endpoint: a node name, a list of them, or START/END (skipped)."""
    if isinstance(expr, ast.List | ast.Tuple):
        return [n for e in expr.elts for n in _node_names(e)]
    if (s := _str(expr)) is not None:
        return [s]
    if _path(expr).rsplit(".", 1)[-1] == "START":
        return ["__start__"]
    return []


def _returned_strings(fn: ast.AST) -> list[str]:
    return [s for sub in ast.walk(fn) if isinstance(sub, ast.Return) for s in _strings(sub.value)]


def _goto_strings(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Where a node function can send the graph next: ``Command(goto=...)`` literals
    and a ``Command[Literal[...]]`` return annotation."""
    out: list[str] = []
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call) and _path(sub.func).rsplit(".", 1)[-1] == "Command":
            out.extend(_strings(_kw(sub, "goto")))
    ann = fn.returns
    if isinstance(ann, ast.Subscript) and _path(ann.value).rsplit(".", 1)[-1] == "Command":
        inner = ann.slice
        if isinstance(inner, ast.Subscript) and _path(inner.value).rsplit(".", 1)[-1] == "Literal":
            sl = inner.slice
            out.extend(_strings(sl) if not isinstance(sl, ast.Constant) else [sl.value])
    return [s for s in out if isinstance(s, str)]


def _loaded_names(fn: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


# ---------------------------------------------------------------------------
# TypeScript / JavaScript — OpenAI Agents SDK only
# ---------------------------------------------------------------------------

_JS_AGENT_DECL = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*(?:new\s+Agent|Agent\.create)\s*\(\s*\{"
)
_JS_TOOL_DECL = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*tool\s*\(\s*\{")
_JS_AGENTS_IMPORT = re.compile(r"""from\s+["']@openai/agents(?:[-/][\w/-]*)?["']""")


def _js_object(source: str, start: int) -> dict[str, str]:
    """The top-level ``key: value`` pairs of the object literal opening at ``start``.

    A reader, not a parser: it tracks bracket depth and string literals, which is all
    an object literal of names and arrays needs.
    """
    out: dict[str, str] = {}
    depth = 0
    i = start
    n = len(source)
    key_start = start + 1
    while i < n:
        c = source[i]
        if c in "'\"`":
            j = i + 1
            while j < n and source[j] != c:
                j += 2 if source[j] == "\\" else 1
            i = j + 1
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth == 0:
                _js_pair(source[key_start:i], out)
                return out
        elif c == "," and depth == 1:
            _js_pair(source[key_start:i], out)
            key_start = i + 1
        i += 1
    return out


def _js_pair(text: str, out: dict[str, str]) -> None:
    key, sep, value = text.partition(":")
    key = key.strip()
    if sep and re.fullmatch(r"\w+", key):
        out[key] = value.strip()
    elif re.fullmatch(r"\w+", key):
        out[key] = key  # shorthand `{ tools }`


def _js_elements(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    items, depth, cur = [], 0, ""
    for c in value[1:-1]:
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        if c == "," and depth == 0:
            items.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        items.append(cur.strip())
    return items


def _js_string(value: str) -> str | None:
    m = re.fullmatch(r"""\s*(["'`])([^"'`]+)\1\s*""", value)
    return m.group(2) if m else None


def _extract_js(source: str, rel: str, start: int) -> _FileResult:
    out = _FileResult(file=rel)
    if not _JS_AGENTS_IMPORT.search(source):
        return out
    for m in _JS_TOOL_DECL.finditer(source):
        fields = _js_object(source, m.end() - 1)
        out.tool_defs[m.group(1)] = _js_string(fields.get("name", "")) or m.group(1)
    idx = start
    for m in _JS_AGENT_DECL.finditer(source):
        fields = _js_object(source, m.end() - 1)
        var = m.group(1)
        raw = _Raw(
            idx=idx,
            framework="OpenAI Agents SDK",
            kind="agent",
            file=rel,
            line=source.count("\n", 0, m.start()) + 1,
            name=_js_string(fields.get("name", "")) or var,
            var=var,
        )
        idx += 1
        for item in _js_elements(fields.get("tools", "")):
            as_tool = re.match(r"(\w+)\.asTool\s*\(", item)
            if as_tool:
                raw.children.append((("var", as_tool.group(1)), "as_tool"))
            elif re.fullmatch(r"\w+", item):
                raw.tools.append(("var", item))
        for item in _js_elements(fields.get("handoffs", "")):
            target = re.match(r"(?:handoff\s*\(\s*)?(\w+)", item)
            if target:
                raw.children.append((("var", target.group(1)), "handoff"))
        out.raws.append(raw)
        out.vars.setdefault(var, raw.idx)
        out.exported.add(var)
    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


class AgentCollector:
    """Accumulates raw definitions file by file; :meth:`finish` resolves them."""

    def __init__(self, *, include_tests: bool = False) -> None:
        self.files: list[_FileResult] = []
        self._next = 0
        #: Read test, mock and fixture files too (see :func:`is_test_path`).
        self.include_tests = include_tests

    def add(self, source: str, rel: str, suffix: str) -> None:
        if not self.include_tests and is_test_path(rel):
            return
        if not _HINT.search(source):
            # No framework here, but a plain module of functions another file turns
            # into tools (`function_tool(tools.get_ticket)`): keep what each says.
            if suffix == ".py" and "def " in source:
                self._functions_only(source, rel)
            return
        if suffix == ".py":
            try:
                tree = ast.parse(source, filename=rel)
            except (SyntaxError, ValueError):
                return  # reported by the site pass already
            ex = _Extractor(tree, rel, self._next)
            ex.out.module = _module_name(rel)
            ex.collect()
            ex.create()
            ex.link()
            ex.mutate()
            ex.export()
            result = ex.out
            self._next = ex.next_idx
        else:
            result = _extract_js(source, rel, self._next)
            self._next += len(result.raws)
        # A file of tools alone is kept too: an agent elsewhere names them.
        if (
            result.raws
            or result.tool_defs
            or result.tool_lists
            or result.tool_helpers
            or result.consts
            or result.func_info
        ):
            self.files.append(result)

    def _functions_only(self, source: str, rel: str) -> None:
        try:
            tree = ast.parse(source, filename=rel)
        except (SyntaxError, ValueError):
            return
        result = _FileResult(file=rel)
        result.module = _module_name(rel)
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                doc, args = _fn_info(stmt)
                if doc or args:
                    result.func_info.setdefault(stmt.name, (doc, args))
        if result.func_info:
            self.files.append(result)

    def finish(self) -> tuple[list[AgentSpec], list[AgentEdge]]:
        return _Linker(self.files, self._next).run()


class _Linker:
    def __init__(self, files: list[_FileResult], next_idx: int) -> None:
        self.files = files
        self.raws: dict[int, _Raw] = {r.idx: r for f in files for r in f.raws}
        self.file_of: dict[int, _FileResult] = {r.idx: f for f in files for r in f.raws}
        self.next_idx = next_idx
        # Repository-wide lookups, used only when a name is defined in exactly one file.
        self.global_vars: dict[str, set[int]] = defaultdict(set)
        self.global_tools: dict[str, set[str]] = defaultdict(set)
        for f in files:
            for var, idx in f.vars.items():
                if var in f.exported:
                    self.global_vars[var].add(idx)
            for var, name in f.tool_defs.items():
                self.global_tools[var].add(name)
        self.global_lists: dict[str, list[_FileResult]] = defaultdict(list)
        self.global_helpers: dict[str, list[_FileResult]] = defaultdict(list)
        self.global_consts: dict[str, set[str]] = defaultdict(set)
        self.global_info: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
        for f in files:
            for var in f.tool_lists:
                self.global_lists[var].append(f)
            for name in f.tool_helpers:
                self.global_helpers[name].append(f)
            for name, value in f.consts.items():
                self.global_consts[name].add(value)
            for name, info in f.tool_info.items():
                self.global_info[name].append(info)
        self.global_funcs: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
        for f in files:
            for name, info in f.func_info.items():
                self.global_funcs[name].append(info)
        #: inner raw -> the AgentExecutor raw that runs it (the two are one agent)
        self.merged: dict[int, int] = {}
        #: raw -> tool references added after construction, with their own file
        self.extra_tools: dict[int, list[tuple[tuple[str, str], _FileResult | None]]] = defaultdict(
            list
        )
        self.labels: dict[str, set[int]] = defaultdict(set)
        #: (graph raw, node name) -> raw, filled by the graph pass
        self.node_agents: dict[tuple[int, str], int] = {}

    def _by_var(self, var: str, file: _FileResult | None, depth: int = 0) -> int | None:
        if file is not None and var in file.vars:
            return file.vars[var]
        found = self.global_vars.get(var) or set()
        if len(found) == 1:
            return next(iter(found))
        if file is not None and var in file.aliases and depth < 3:
            return self._by_var(file.aliases[var], file, depth + 1)
        return None

    def _by_label(self, label: str, file: str) -> int | None:
        hits = self.labels.get(_slug(label)) or set()
        local = [i for i in hits if self.raws[i].file == file]
        if len(local) == 1:
            return local[0]
        return next(iter(hits)) if len(hits) == 1 else None

    def resolve(self, ref: Ref, raw: _Raw) -> list[int]:
        kind, value = ref
        file = self.file_of.get(raw.idx)
        if kind == "idx":
            return [value]
        if kind == "var":
            hit = self._by_var(value, file)
            return [hit] if hit is not None else []
        if kind == "label":
            hit = self._by_label(value, raw.file)
            return [hit] if hit is not None else []
        if kind == "class":
            return [
                r.idx
                for r in self.raws.values()
                if r.file == raw.file and r.cls == value and r.kind == "agent" and r.idx != raw.idx
            ]
        return []

    def _tool_names(
        self, ref: tuple[str, str], file: _FileResult | None, depth: int = 0
    ) -> list[str]:
        """The tool names a reference stands for: a name, a variable holding a tool,
        or a list (a module-level variable or a helper's return) another file holds.
        In this file first, then by a name exactly one file defines. A list or helper
        that cannot be found adds nothing rather than a tool named after it."""
        kind, value = ref
        if kind == "name":
            return [value]
        if depth > 4:
            return []
        if kind == "var":
            if file is not None and value in file.tool_defs:
                return [file.tool_defs[value]]
            if file is not None and value in file.tool_lists:
                return self._expand(file.tool_lists[value], file, depth)
            found = self.global_tools.get(value) or set()
            if len(found) == 1:
                return [next(iter(found))]
            owners = self.global_lists.get(value)
            if owners:
                if len(owners) > 1:
                    return []
                return self._expand(owners[0].tool_lists[value], owners[0], depth)
            return [value]
        if kind == "call":
            if file is not None and value in file.tool_helpers:
                return self._expand(file.tool_helpers[value], file, depth)
            owners = self.global_helpers.get(value) or []
            if len(owners) == 1:
                return self._expand(owners[0].tool_helpers[value], owners[0], depth)
        if kind == "list":
            lists = self.global_lists.get(value) or []
            if len(lists) == 1:
                return self._expand(lists[0].tool_lists[value], lists[0], depth)
        return []

    def _expand(
        self, refs: list[tuple[str, str]], file: _FileResult | None, depth: int
    ) -> list[str]:
        return [n for r in refs for n in self._tool_names(r, file, depth + 1)]

    def _tools_of(self, idx: int) -> list[str]:
        raw = self.raws[idx]
        file = self.file_of.get(idx)
        refs = [(t, file) for t in raw.tools] + self.extra_tools.get(idx, [])
        for inner, outer in self.merged.items():
            if outer == idx:
                inner_file = self.file_of.get(inner)
                refs = [(t, inner_file) for t in self.raws[inner].tools] + refs
        return list(dict.fromkeys(n for t, f in refs for n in self._tool_names(t, f)))

    def _model_of(self, idx: int) -> str | None:
        """The agent's model as its own file reads it, else an imported constant that
        exactly one file defines. Never another agent's or a repository-wide guess."""
        raw = self.raws[idx]
        model, var = raw.model, raw.model_var
        if model is None and var is None:
            for inner, outer in self.merged.items():
                if outer == idx:
                    model, var = self.raws[inner].model, self.raws[inner].model_var
        if model is None and var is not None:
            found = self.global_consts.get(var) or set()
            model = next(iter(found)) if len(found) == 1 else None
        return model

    def _details(self, idx: int, tools: list[str]) -> list[dict[str, Any]]:
        file = self.file_of.get(idx)
        out: list[dict[str, Any]] = []
        for name in tools:
            info = file.tool_info.get(name) if file is not None else None
            fn = file.tool_fn.get(name) if file is not None else None
            for pool in (self.global_info.get(name, []), self.global_funcs.get(fn or "", [])):
                found = {(d, tuple(a)) for d, a in pool}
                if info is None and len(found) == 1:
                    doc, args = next(iter(found))
                    info = (doc, list(args))
            if info is not None:
                out.append({"name": name, "description": info[0], "args": list(info[1])})
        return out

    def _new_raw(self, **kw: Any) -> _Raw:
        raw = _Raw(idx=self.next_idx, **kw)
        self.next_idx += 1
        self.raws[raw.idx] = raw
        return raw

    def run(self) -> tuple[list[AgentSpec], list[AgentEdge]]:
        for raw in self.raws.values():
            if raw.name and raw.extends is None:
                self.labels[_slug(raw.name)].add(raw.idx)
        self._merge_executors()
        edges: list[tuple[int, int, str]] = []
        for raw in list(self.raws.values()):
            owners = [raw.idx]
            if raw.extends is not None:
                # `a.handoffs.append(x)`: x is resolved where the line is, joined to `a`.
                owners = [
                    i for i in self.resolve(raw.extends, raw) if self.raws[i].extends is None
                ][:1]
                for owner in owners:
                    file = self.file_of.get(raw.idx)
                    self.extra_tools[owner].extend((t, file) for t in raw.tools)
            for ref, relation in raw.children:
                for child in self.resolve(ref, raw):
                    edges.extend((owner, child, relation) for owner in owners)
        edges.extend(self._graphs())
        edges.extend(self._crew_managers())
        edges = self._fold_groupchats(edges)
        edges.extend(self._crew_delegation(edges))
        edges = [(self.merged.get(p, p), self.merged.get(c, c), r) for p, c, r in edges]

        # Orchestrators (crews, teams, graphs) are reported only when they run agents.
        parents = {p for p, _, _ in edges}
        for raw in self.raws.values():
            if raw.kind in ("crew", "team", "graph") and raw.idx not in parents:
                raw.dropped = True
        # A hand-written loop is an agent only when nothing else is.
        if any(not r.dropped and not r.loop for r in self.raws.values()):
            for raw in self.raws.values():
                raw.dropped = raw.dropped or raw.loop
        live = {i for i, r in self.raws.items() if not r.dropped}

        keys = self._keys([self.raws[i] for i in sorted(live, key=self._order)])
        specs = []
        for i in sorted(live, key=self._order):
            raw = self.raws[i]
            module = self.file_of[i].module if i in self.file_of else None
            tools = self._tools_of(i)
            specs.append(
                AgentSpec(
                    key=keys[i],
                    name=raw.name or keys[i],
                    framework=raw.framework,
                    kind=raw.kind,
                    file=raw.file,
                    line=raw.line,
                    tools=tools,
                    model=self._model_of(i),
                    module=module if raw.attr else None,
                    attr=raw.attr if module else None,
                    attr_kind=raw.attr_kind if module and raw.attr else None,
                    tool_details=self._details(i, tools),
                    named=raw.named,
                    instructions=raw.instructions,
                )
            )
        seen: set[tuple[int, int]] = set()
        out_edges: list[AgentEdge] = []
        rank = {r: n for n, r in enumerate(RELATIONS)}
        for parent, child, relation in sorted(edges, key=lambda e: rank.get(e[2], 9)):
            if parent == child or parent not in live or child not in live:
                continue
            if (parent, child) in seen:
                continue
            seen.add((parent, child))
            out_edges.append(AgentEdge(keys[parent], keys[child], relation))
        out_edges.sort(key=lambda e: (e.parent, e.child))
        return specs, out_edges

    def _order(self, idx: int) -> tuple[str, int, int]:
        raw = self.raws[idx]
        return (raw.file, raw.line, idx)

    def _keys(self, raws: list[_Raw]) -> dict[int, str]:
        """A unique, stable key per agent: its name, then its file when two share one."""
        base = {r.idx: _slug(r.name or f"{Path(r.file).stem}-{r.kind}") for r in raws}
        counts: dict[str, int] = defaultdict(int)
        for key in base.values():
            counts[key] += 1
        out: dict[int, str] = {}
        used: set[str] = set()
        for raw in raws:
            key = base[raw.idx]
            if counts[key] > 1:
                key = f"{key}-{_slug(Path(raw.file).stem)}"
            candidate, n = key, 2
            while candidate in used:
                candidate, n = f"{key}-{n}", n + 1
            used.add(candidate)
            out[raw.idx] = candidate
        return out

    def _graphs(self) -> list[tuple[int, int, str]]:
        edges: list[tuple[int, int, str]] = []
        for f in self.files:
            for graph in f.graphs:
                graph_raw = self.raws[graph.raw]
                agents: dict[str, int] = {}
                for name, node in graph.nodes.items():
                    hit: int | None = None
                    if node.ref is not None:
                        found = self.resolve(node.ref, graph_raw)
                        hit = found[0] if found and found[0] != graph.raw else None
                    if hit is None and node.func is not None:
                        # A node function that runs an agent stands for that agent.
                        found_ids = {
                            i
                            for n in node.loads
                            if (i := self._by_var(n, f)) is not None
                            and i != graph.raw
                            and self.raws[i].kind != "graph"
                        }
                        if len(found_ids) == 1:
                            hit = found_ids.pop()
                    if hit is None and node.bound_tools is not None:
                        # A node that binds tools to a model is an agent of its own.
                        hit = self._new_raw(
                            framework="LangGraph",
                            kind="agent",
                            file=graph_raw.file,
                            line=node.func.lineno if node.func else graph_raw.line,
                            name=name,
                            tools=node.bound_tools,
                        ).idx
                        self.file_of[hit] = f
                    if hit is not None:
                        agents[name] = hit
                # A node that routes to agent nodes is their supervisor, whatever it is.
                for src, dst, how in graph.routes:
                    if (
                        how == "route"
                        and dst in agents
                        and src not in agents
                        and src in graph.nodes
                    ):
                        node = graph.nodes[src]
                        agents[src] = self._new_raw(
                            framework="LangGraph",
                            kind="supervisor",
                            file=graph_raw.file,
                            line=node.func.lineno if node.func else graph_raw.line,
                            name=src,
                        ).idx
                        self.file_of[agents[src]] = f
                routed = {
                    (agents[s], agents[d])
                    for s, d, how in graph.routes
                    if how == "route" and s in agents and d in agents and s != d
                }
                # A worker that hands control back (`Command(goto="supervisor")`) is
                # returning, not delegating: of a pair routing both ways, the side that
                # routes to more agents is the supervisor. A tie is a pair of peers.
                fan_out: dict[int, int] = defaultdict(int)
                for parent, _ in routed:
                    fan_out[parent] += 1
                routed = {
                    (a, b) for a, b in routed if not ((b, a) in routed and fan_out[b] > fan_out[a])
                }
                has_parent: set[int] = set()
                for parent, child in routed:
                    edges.append((parent, child, "delegates"))
                    has_parent.add(child)
                for src, dst, how in graph.routes:
                    if how != "edge" or src not in agents or dst not in agents or src == dst:
                        continue
                    a, b = agents[src], agents[dst]
                    if (b, a) in routed or (a, b) in routed:
                        continue  # a worker returning to its supervisor
                    edges.append((a, b, "handoff"))
                    has_parent.add(b)
                for idx in dict.fromkeys(agents.values()):
                    if idx not in has_parent:
                        edges.append((graph.raw, idx, "member"))
        return edges

    def _merge_executors(self) -> None:
        """LangChain: ``AgentExecutor(agent=x, tools=...)`` runs the agent ``x`` builds,
        so the two are one agent, reported as the executor (what is invoked), with the
        tools and model of both."""
        for raw in list(self.raws.values()):
            if raw.wraps is None:
                continue
            inner = [i for i in self.resolve(raw.wraps, raw) if i != raw.idx]
            if len(inner) == 1 and self.raws[inner[0]].kind == "agent":
                self.merged[inner[0]] = raw.idx
                self.raws[inner[0]].dropped = True

    def _fold_groupchats(self, edges: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
        """AG2: a GroupChatManager runs a GroupChat; the chat's members are its own."""
        for raw in self.raws.values():
            if raw.absorbs is None:
                continue
            for group in self.resolve(raw.absorbs, raw):
                members = [(p, c, r) for p, c, r in edges if p == group]
                if not members:
                    continue
                self.raws[group].dropped = True
                edges = [e for e in edges if e[0] != group and e[1] != group]
                edges.extend((raw.idx, c, "delegates") for _, c, _ in members)
        return edges

    def _crew_members(self, crew: _Raw) -> list[int]:
        return [i for ref in crew.members for i in self.resolve(ref, crew)]

    def _crew_managers(self) -> list[tuple[int, int, str]]:
        """CrewAI: a crew runs its ``manager_agent``, who delegates to every member."""
        out: list[tuple[int, int, str]] = []
        for crew in list(self.raws.values()):
            if crew.manager is None:
                continue
            members = self._crew_members(crew)
            for manager in self.resolve(crew.manager, crew):
                out.append((crew.idx, manager, "member"))
                out.extend((manager, m, "delegates") for m in members if m != manager)
        return out

    def _crew_delegation(self, edges: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
        """CrewAI: an agent with ``allow_delegation=True`` may hand work to any crewmate."""
        out: list[tuple[int, int, str]] = []
        crews: dict[int, list[int]] = defaultdict(list)
        for parent, child, _ in edges:
            if self.raws[parent].kind == "crew":
                crews[parent].append(child)
        for crew in self.raws.values():
            if crew.manager is not None:
                crews[crew.idx] = self._crew_members(crew)
        for members in crews.values():
            for member in members:
                if self.raws[member].allow_delegation:
                    out.extend((member, other, "delegates") for other in members if other != member)
        return out


_SLUG = re.compile(r"[^a-z0-9-]+")


def _slug(value: str) -> str:
    return _SLUG.sub("-", (value or "").strip().lower()).strip("-") or "agent"
