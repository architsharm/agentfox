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
    r"(?:from|import)\s+(?:agents|crewai|autogen\w*|ag2|google\.adk|langgraph\w*|langchain)\b"
    r"|@openai/agents|@(?:\w+\.)?(?:function_)?tool\b"
)


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

    # -- pass A: imports, assignments, functions, tools ----------------------

    def collect(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        for stmt in self.tree.body:
            for target in _assigned_names(stmt):
                self.out.exported.add(target)
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                self.out.exported.add(stmt.name)
        self._walk_scope(self.tree.body, cls=None)

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
            if isinstance(value.func, ast.Name):
                self.out.aliases.setdefault(var, value.func.id)
            path = _path(value.func)
            if path in _TOOL_CONSTRUCTORS or any(
                path.endswith(f".{c}") for c in _TOOL_CONSTRUCTORS
            ):
                name = _str(_kw(value, "name"))
                if name:
                    self.out.tool_defs[var] = name
        elif isinstance(value, ast.List | ast.Tuple):
            self.lists[var] = value

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
                return

    # -- pass B: one raw per recognised constructor -------------------------

    def qual(self, func: ast.AST) -> str:
        path = _path(func)
        if not path:
            return ""
        head, _, rest = path.partition(".")
        base = self.imports.get(head)
        if base is None:
            return ""
        return f"{base}.{rest}" if rest else base

    def create(self) -> None:
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            match = _constructor(self.qual(node.func))
            if match is None:
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
            self.next_idx += 1
            self.call_raw[id(node)] = raw.idx
            self.out.raws.append(raw)
            if var:
                self.out.vars.setdefault(var, raw.idx)
            self.made[raw.idx] = (node, role)

    def _name(self, call: ast.Call, role: str, var: str | None, cls: str | None) -> str | None:
        if role == "crew_agent":
            return _str(_kw(call, "role")) or var
        if role == "crew":
            if id(call) in self.crew_methods and cls:
                return cls
            return _str(_kw(call, "name")) or var
        if role == "autogen_agent":
            first = call.args[0] if call.args else None
            return _str(_kw(call, "name")) or _str(first) or var
        if role == "supervisor":
            return _str(_kw(call, "supervisor_name")) or "supervisor"
        if role == "graph":
            return var
        return _str(_kw(call, "name")) or var

    # -- pass C: tools and children -----------------------------------------

    def link(self) -> None:
        for raw in list(self.out.raws):
            call, role = self.made[raw.idx]
            if role in ("openai_agent", "crew_agent", "autogen_agent", "adk_agent", "react_agent"):
                tools_expr = _kw(call, "tools")
                if tools_expr is None and role == "react_agent" and len(call.args) > 1:
                    tools_expr = call.args[1]
                self._tools(raw, tools_expr)
            if role == "openai_agent":
                for elt in self._elements(_kw(call, "handoffs")):
                    if (
                        isinstance(elt, ast.Call)
                        and _path(elt.func).rsplit(".", 1)[-1] == "handoff"
                    ):
                        elt = elt.args[0] if elt.args else _kw(elt, "agent")
                    self._child(raw, elt, "handoff")
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

    def _elements(self, expr: ast.AST | None) -> list[ast.AST]:
        if expr is None:
            return []
        if isinstance(expr, ast.List | ast.Tuple | ast.Set):
            out: list[ast.AST] = []
            for elt in expr.elts:
                if isinstance(elt, ast.Starred):
                    out.extend(self._elements(elt.value))
                else:
                    out.append(elt)
            return out
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            return self._elements(expr.left) + self._elements(expr.right)
        if isinstance(expr, ast.Name) and expr.id in self.lists:
            return self._elements(self.lists[expr.id])
        return [expr]

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
        for elt in self._elements(expr):
            if isinstance(elt, ast.Call):
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

    def __init__(self) -> None:
        self.files: list[_FileResult] = []
        self._next = 0

    def add(self, source: str, rel: str, suffix: str) -> None:
        if not _HINT.search(source):
            return
        if suffix == ".py":
            try:
                tree = ast.parse(source, filename=rel)
            except (SyntaxError, ValueError):
                return  # reported by the site pass already
            ex = _Extractor(tree, rel, self._next)
            ex.collect()
            ex.create()
            ex.link()
            result = ex.out
        else:
            result = _extract_js(source, rel, self._next)
        self._next += len(result.raws)
        # A file of tools alone is kept too: an agent elsewhere names them.
        if result.raws or result.tool_defs:
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

    def _tool_name(self, ref: tuple[str, str], raw: _Raw) -> str:
        kind, value = ref
        if kind == "name":
            return value
        file = self.file_of.get(raw.idx)
        if file is not None and value in file.tool_defs:
            return file.tool_defs[value]
        found = self.global_tools.get(value) or set()
        return next(iter(found)) if len(found) == 1 else value

    def _new_raw(self, **kw: Any) -> _Raw:
        raw = _Raw(idx=self.next_idx, **kw)
        self.next_idx += 1
        self.raws[raw.idx] = raw
        return raw

    def run(self) -> tuple[list[AgentSpec], list[AgentEdge]]:
        for raw in self.raws.values():
            if raw.name:
                self.labels[_slug(raw.name)].add(raw.idx)
        edges: list[tuple[int, int, str]] = []
        for raw in list(self.raws.values()):
            for ref, relation in raw.children:
                for child in self.resolve(ref, raw):
                    edges.append((raw.idx, child, relation))
        edges.extend(self._graphs())
        edges.extend(self._crew_managers())
        edges = self._fold_groupchats(edges)
        edges.extend(self._crew_delegation(edges))

        # Orchestrators (crews, teams, graphs) are reported only when they run agents.
        parents = {p for p, _, _ in edges}
        for raw in self.raws.values():
            if raw.kind in ("crew", "team", "graph") and raw.idx not in parents:
                raw.dropped = True
        live = {i for i, r in self.raws.items() if not r.dropped}

        keys = self._keys([self.raws[i] for i in sorted(live, key=self._order)])
        specs = [
            AgentSpec(
                key=keys[i],
                name=self.raws[i].name or keys[i],
                framework=self.raws[i].framework,
                kind=self.raws[i].kind,
                file=self.raws[i].file,
                line=self.raws[i].line,
                tools=list(
                    dict.fromkeys(self._tool_name(t, self.raws[i]) for t in self.raws[i].tools)
                ),
            )
            for i in sorted(live, key=self._order)
        ]
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
