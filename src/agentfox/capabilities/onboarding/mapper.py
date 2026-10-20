"""Map an agent repository into the onboarding structure: who talks to it, the
agents, their tools, and the systems those tools touch.

Static and local: it reads source with ``ast`` and never imports or runs the
user's code. What leaves the machine is names and shapes only — tool names, one
line of each docstring, argument names, a model id — never data or prompts.

Covers the common Python shapes:

* LangChain/LangGraph: ``@tool`` functions, ``Tool(...)`` / ``StructuredTool.from_function``,
  and ``create_agent`` / ``create_react_agent`` / ``AgentExecutor`` calls.
* OpenAI Agents SDK: ``@function_tool``, ``function_tool(fn)`` and
  ``function_tool(needs_approval=True)(fn)``, ``Agent(...)`` and typed
  ``Agent[Context](...)``, each with its own name, tools and hand-offs (``handoffs=[...]``,
  ``a.handoffs = [...]``, ``a.handoffs.append(b)``, ``handoff(agent=b)``).
* Raw function calling: tool schemas written as ``{"type": "function", "function":
  {"name": ...}}`` and passed as ``client.chat.completions.create(tools=...)``.
* Models: chat-model constructors such as ``ChatOpenAI(model=...)``, ``model=`` on an
  agent (a string, or a constant like ``MODEL = "gpt-4o"``), and config defaults
  such as ``os.getenv("OPENAI_MODEL", "gpt-4o-mini")``.

Anything else simply isn't found; it is never guessed.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    "__pycache__",
    "site-packages",
    "build",
    "dist",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "tests",
    "test",
    "archive",
    "examples",
}

TOOL_DECORATORS = {"tool", "function_tool"}
#: Constructors that make a tool out of a function: ``Tool(name=..., func=f)``.
TOOL_CONSTRUCTORS = {"Tool", "StructuredTool", "from_function", "FunctionTool"}
AGENT_FACTORIES = {
    "create_agent": "langchain",
    "create_react_agent": "langgraph",
    "create_tool_calling_agent": "langchain",
    "AgentExecutor": "langchain",
    "initialize_agent": "langchain",
    "Agent": "openai-agents",
}
MODEL_CLASSES = {
    "ChatOpenAI",
    "AzureChatOpenAI",
    "ChatAnthropic",
    "ChatGoogleGenerativeAI",
    "ChatVertexAI",
    "ChatBedrock",
    "ChatMistralAI",
    "ChatGroq",
    "ChatOllama",
    "ChatLiteLLM",
}


@dataclass
class FoundTool:
    name: str
    doc: str
    args: list[str]
    file: str
    line: int


@dataclass
class FoundAgent:
    name: str
    framework: str
    file: str
    line: int
    model: str | None = None
    tool_names: list[str] = field(default_factory=list)
    #: How the runner reaches the live object: module path and attribute.
    module: str | None = None
    attr: str | None = None
    prompt: str = ""
    #: The variables of the agents this one hands work to, read from the code.
    handoffs: list[str] = field(default_factory=list)
    #: Every model id the code names for it (the first is shown).
    models: list[str] = field(default_factory=list)
    #: The code gives it a name (`name="Triage Agent"`), rather than us inventing one.
    named: bool = False
    #: The code lists its tools (`tools=[...]`), even if the list is empty.
    listed: bool = False


# --- What a tool can do, from its name and docstring --------------------------

_READ_PREFIX = re.compile(
    r"^(get|list|check|track|search|find|lookup|look_up|read|fetch|describe|show|view|query_read)_?"
)
_MONEY = re.compile(
    r"refund|payment|payout|charge|transfer|withdraw|credit|invoice|purchase|\bpay\b|\breturn\b|start_return|compensat|reimburs|voucher|payout",
    re.I,
)
_DELETE = re.compile(r"delete|drop|remove|truncate|destroy|purge|wipe", re.I)
_WRITE = re.compile(
    r"update|write|create|insert|set_|modify|cancel|start_|execute|exec\b|run_sql|sql|book|reserve|assign|add_|issue_|submit|approve|grant|reset|change|move_|place_|apply_|schedule|enroll|register|upload|save|post_note|note",
    re.I,
)
_EXPORT = re.compile(r"export|dump|bulk|download_all|all_customers", re.I)
_OUTSIDE = re.compile(
    r"email|send|notify|webhook|slack|sms|http|post_|publish|tweet|escalat|hand.?off|ticket", re.I
)

# (keyword pattern, system name, kind) — first match wins.
_SYSTEMS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"refund|payment|payout|charge|stripe|invoice|\breturn\b|start_return", re.I),
        "Payments",
        "payments",
    ),
    (
        re.compile(r"escalat|human|ticket|helpdesk|zendesk|support team", re.I),
        "Helpdesk",
        "helpdesk",
    ),
    (re.compile(r"order|cart|product|inventory|catalog", re.I), "Orders", "database"),
    (re.compile(r"ship|track|carrier|deliver", re.I), "Shipping carrier", "external"),
    (re.compile(r"email|smtp|sendgrid|mail", re.I), "Email", "email"),
    (re.compile(r"customer|crm|contact|account", re.I), "Customer records", "crm"),
    (re.compile(r"sql|database|postgres|mysql|table|\bdb\b", re.I), "Database", "database"),
    (re.compile(r"slack|webhook|http|api", re.I), "External API", "external"),
]


def classify(name: str, doc: str) -> tuple[str, str]:
    """(risk, reason). risk: high | outside | read_only."""
    # The name says what the tool does; the docstring often mentions what it is
    # *about* ("escalate payment issues"), so it only decides when the name doesn't.
    if _READ_PREFIX.match(name) and not _DELETE.search(name):
        return "read_only", "only reads"
    if _MONEY.search(name):
        return "high", "moves money"
    if _DELETE.search(name):
        return "high", "deletes data"
    if _EXPORT.search(name):
        return "high", "exports personal data"
    if _OUTSIDE.search(name):
        return "outside", "talks to the outside"
    if _WRITE.search(name):
        return "high", "refund" in doc.lower() and "moves money" or "changes data"
    if _MONEY.search(doc):
        return "high", "moves money"
    if _DELETE.search(doc):
        return "high", "deletes data"
    if _OUTSIDE.search(doc):
        return "outside", "talks to the outside"
    return "read_only", "only reads"


def system_for(name: str, doc: str, risk: str) -> tuple[str, str]:
    # A money tool touches payments whatever else its docstring mentions.
    if risk == "high" and _MONEY.search(f"{name} {doc}"):
        return "Payments", "payments"
    # Only a tool that moves money touches payments; one that mentions refunds reads.
    candidates = [s for s in _SYSTEMS if s[2] != "payments" or risk == "high"]
    for pattern, sys_name, kind in candidates:
        if pattern.search(name.replace("_", " ")):
            return sys_name, kind
    for pattern, sys_name, kind in candidates:
        if pattern.search(doc):
            return sys_name, kind
    return "Internal service", "external"


def plain_sentence(doc: str, name: str) -> str:
    first = " ".join(doc.strip().split())
    if not first:
        return f"Runs {name}."
    sentences = re.split(r"(?<=[.!?])\s", first)
    return sentences[0] if sentences[0].endswith((".", "!", "?")) else sentences[0] + "."


# --- AST walk ------------------------------------------------------------------


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    # `Agent[Context](...)`: the generic parameter wraps the name being called.
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _ref(node: ast.AST) -> str | None:
    """The name a reference points at: ``get_order`` or ``tools.get_order``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _wrapped(call: ast.Call) -> tuple[str | None, str | None]:
    """For a call that turns a function into a tool, (function name, tool name override).

    ``function_tool(fn)``, ``function_tool(needs_approval=True)(fn)``, ``tool(fn)``,
    ``Tool(name="x", func=fn)``, ``StructuredTool.from_function(func=fn, name="x")``.
    """
    func = call.func
    # Curried: function_tool(...)(fn) — the decorator's own options carry the override.
    if isinstance(func, ast.Call) and _call_name(func) in TOOL_DECORATORS and call.args:
        override = _const_str(_kw(func, "name_override", "name")) or (
            _const_str(func.args[0]) if func.args else None
        )
        return _ref(call.args[0]), override
    name = _call_name(call)
    if name in TOOL_DECORATORS and call.args and _ref(call.args[0]):
        return _ref(call.args[0]), _const_str(_kw(call, "name_override", "name"))
    if name in TOOL_CONSTRUCTORS:
        fn = _kw(call, "func", "coroutine") or (call.args[0] if call.args else None)
        override = _const_str(_kw(call, "name", "name_override"))
        if fn is not None and _ref(fn):
            return _ref(fn), override
        if override:
            return None, override
    return None, None


def _tool_refs(node: ast.AST | None) -> list[str]:
    """The tools a ``tools=[...]`` list names: variables, attributes, wrapped functions."""
    if node is None:
        return []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out: list[str] = []
        for e in node.elts:
            for n in _tool_refs(e):
                if n not in out:
                    out.append(n)
        return out
    if isinstance(node, ast.Call):
        fn, override = _wrapped(node)
        if override or fn:
            return [override or fn]  # type: ignore[list-item]
        # `tools=build_tools()`: resolved later to the list that function returns.
        callee = _call_name(node)
        return [f"{callee}()"] if callee else []
    if isinstance(node, ast.Starred):
        return _tool_refs(node.value)
    # `tools or ALL_TOOLS`, `A if x else B`: every branch may be the list.
    if isinstance(node, ast.BoolOp):
        return [n for v in node.values for n in _tool_refs(v)]
    if isinstance(node, ast.IfExp):
        return _tool_refs(node.body) + _tool_refs(node.orelse)
    ref = _ref(node)
    return [ref] if ref else []


def _schema_tool(node: ast.Dict) -> FoundTool | None:
    """A raw function-calling schema: ``{"type": "function", "function": {"name": ...}}``."""
    fields = {
        _const_str(k): v for k, v in zip(node.keys, node.values, strict=False) if k is not None
    }
    if _const_str(fields.get("type")) != "function" or not isinstance(
        fields.get("function"), ast.Dict
    ):
        return None
    fn = {
        _const_str(k): v
        for k, v in zip(fields["function"].keys, fields["function"].values, strict=False)
        if k is not None
    }  # type: ignore[union-attr]
    name = _const_str(fn.get("name"))
    if not name:
        return None
    args: list[str] = []
    params = fn.get("parameters")
    if isinstance(params, ast.Dict):
        p = {
            _const_str(k): v
            for k, v in zip(params.keys, params.values, strict=False)
            if k is not None
        }
        props = p.get("properties")
        if isinstance(props, ast.Dict):
            args = [a for a in (_const_str(k) for k in props.keys if k is not None) if a]
    return FoundTool(name, _const_str(fn.get("description")) or "", args, "", node.lineno)


_MODEL_ID = re.compile(
    r"^(gpt|o\d|claude|gemini|llama|mistral|mixtral|qwen|deepseek|command|phi|grok)[\w.:\-/]*$",
    re.I,
)


def _kw(call: ast.Call, *names: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg in names:
            return k.value
    return None


def _names_in(node: ast.AST | None) -> list[str]:
    return (
        [n.id for n in ast.walk(node)]
        if node is not None and False
        else ([n.id for n in ast.walk(node) if isinstance(n, ast.Name)] if node is not None else [])
    )


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    return None


class _FileVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, module: str) -> None:
        self.rel = rel
        self.module = module
        self.tools: list[FoundTool] = []
        self.functions: dict[str, FoundTool] = {}  # every function, for tools wrapped by a call
        self.wrapped: list[tuple[str, str | None]] = []  # (function name, tool name override)
        self.models: dict[str, str] = {}  # variable -> model id
        self.model_ids: list[str] = []
        self.tool_lists: dict[str, list[str]] = {}  # variable -> tool names
        self.strings: dict[str, str] = {}  # variable -> string constant (prompts)
        self.factories: dict[str, ast.Call] = {}  # function name -> agent factory call inside it
        self.agent_calls: list[tuple[ast.Call, str | None]] = []  # (call, assigned var)
        self.handoffs: dict[str, list[str]] = {}  # agent variable -> variables it hands off to
        self.aliases: dict[str, str] = {}  # function name -> the tool name it is registered as
        self.assigned: dict[int, str] = {}  # id(agent call) -> the variable it is assigned to
        self.returns: dict[str, list[str]] = {}  # function name -> tools in the list it returns
        self._func_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        args = [
            a.arg
            for a in node.args.args
            if a.arg not in ("self", "cls", "context", "ctx", "run_context")
        ]
        doc = ast.get_docstring(node) or ""
        self.functions.setdefault(node.name, FoundTool(node.name, doc, args, self.rel, node.lineno))
        for dec in node.decorator_list:
            if _call_name(dec) in TOOL_DECORATORS:
                name = node.name
                described = doc
                if isinstance(dec, ast.Call):
                    name = (
                        _const_str(_kw(dec, "name_override", "name"))
                        or (_const_str(dec.args[0]) if dec.args else None)
                        or name
                    )
                    described = _const_str(_kw(dec, "description_override", "description")) or doc
                self.tools.append(FoundTool(name, described, args, self.rel, node.lineno))
                self.aliases[node.name] = name
        # `def build_tools(): return [function_tool(a), ...]`
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, (ast.List, ast.Tuple)):
                self.returns[node.name] = _tool_refs(stmt.value)
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # `TOOL_SCHEMAS: list[dict] = [...]` reads like a plain assignment.
        if node.value is not None:
            self.visit_Assign(
                ast.Assign(targets=[node.target], value=node.value, lineno=node.lineno)
            )
        else:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Dict(self, node: ast.Dict) -> None:
        t = _schema_tool(node)
        if t is not None:
            t.file = self.rel
            self.tools.append(t)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        value = node.value
        if isinstance(value, ast.Call):
            cname = _call_name(value)
            if cname in MODEL_CLASSES or cname == "init_chat_model":
                model = _const_str(_kw(value, "model", "model_name")) or (
                    _const_str(value.args[0]) if value.args else None
                )
                for t in targets:
                    self.models[t] = model or cname
        if isinstance(value, (ast.List, ast.Tuple)):
            names = _tool_refs(value)
            # A list of raw schemas names its tools by their "name" fields.
            schema_names = [
                t.name for e in value.elts if isinstance(e, ast.Dict) and (t := _schema_tool(e))
            ]
            for t in targets:
                self.tool_lists[t] = names + [n for n in schema_names if n not in names]
        if isinstance(value, ast.Call) and targets and _call_name(value) in AGENT_FACTORIES:
            self.assigned[id(value)] = targets[0]
        # `triage.handoffs = [a, handoff(agent=b)]`
        for t in node.targets:
            if (
                isinstance(t, ast.Attribute)
                and t.attr == "handoffs"
                and isinstance(t.value, ast.Name)
            ):
                self.handoffs.setdefault(t.value.id, []).extend(_agent_refs(value))
        s = _const_str(value)
        if s:
            for t in targets:
                self.strings[t] = s
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        cname = _call_name(node)
        if cname in MODEL_CLASSES or cname == "init_chat_model":
            model = _const_str(_kw(node, "model", "model_name")) or (
                _const_str(node.args[0]) if node.args else None
            )
            if model:
                self.model_ids.append(model)
        # Config defaults: os.getenv("OPENAI_MODEL", "gpt-4o-mini"), env.get("MODEL", ...).
        if cname in ("getenv", "get") and len(node.args) >= 2:
            key, default = _const_str(node.args[0]), _const_str(node.args[1])
            if key and default and "MODEL" in key.upper() and _MODEL_ID.match(default):
                self.model_ids.append(default)
        fn, override = _wrapped(node)
        if fn or override:
            self.wrapped.append((fn or override, override))  # type: ignore[arg-type]
            if fn and override:
                self.aliases[fn] = override
        # `a.handoffs.append(b)` / `a.handoffs.extend([b, c])`
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and f.attr in ("append", "extend")
            and isinstance(f.value, ast.Attribute)
            and f.value.attr == "handoffs"
            and isinstance(f.value.value, ast.Name)
        ):
            for a in node.args:
                self.handoffs.setdefault(f.value.value.id, []).extend(_agent_refs(a))
        is_agent = cname in AGENT_FACTORIES and (
            _kw(node, "tools") is not None or cname in ("create_agent", "Agent")
        )
        # A raw loop: client.chat.completions.create(tools=...) / client.responses.create(tools=...)
        raw = (
            cname == "create"
            and _kw(node, "tools") is not None
            and _kw(node, "messages", "input") is not None
        )
        if is_agent or raw:
            if self._func_stack:
                self.factories[self._func_stack[-1]] = node
            self.agent_calls.append((node, None))
        self.generic_visit(node)


def _agent_refs(node: ast.AST) -> list[str]:
    """The agents a hand-off list names: ``[a, handoff(agent=b)]``."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return [r for e in node.elts for r in _agent_refs(e)]
    if isinstance(node, ast.Call) and _call_name(node) == "handoff":
        target = _kw(node, "agent") or (node.args[0] if node.args else None)
        return [r for r in [_ref(target)] if r] if target is not None else []
    ref = _ref(node)
    return [ref] if ref else []


def _module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _project_name(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            name = tomllib.loads(pyproject.read_text()).get("project", {}).get("name")
            if name:
                return str(name)
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return root.resolve().name


def _who_talks(root: Path, prompts: str) -> tuple[str, str]:
    text = prompts.lower()
    label = (
        "Customers"
        if re.search(r"customer|buyer|shopper|client", text)
        else "Employees"
        if re.search(r"employee|staff|it support|helpdesk", text)
        else "Users"
    )
    for entry, how in (
        ("chat.py", "chat"),
        ("app.py", "app"),
        ("server.py", "API"),
        ("main.py", "app"),
        ("streamlit_app.py", "web app"),
        ("bot.py", "bot"),
    ):
        if (root / entry).is_file():
            return label, f"{how}, {entry}"
    return label, "chat"


def map_repository(root: str | Path = ".") -> dict[str, Any]:
    """Scan ``root`` and return ``{"structure": Structure, "agents": [runner refs]}``."""
    root = Path(root).resolve()
    visitors: list[_FileVisitor] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(rel))
        except (SyntaxError, ValueError):
            continue
        v = _FileVisitor(str(rel), _module_name(rel))
        v.visit(tree)
        # Module-level `agent = build_agent()` / `agent = create_agent(...)`: how the
        # runner will reach the live object.
        v.module_refs = []  # type: ignore[attr-defined]
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                callee = _call_name(stmt.value)
                for t in stmt.targets:
                    if isinstance(t, ast.Name) and (
                        callee in AGENT_FACTORIES or callee in v.factories
                    ):
                        v.module_refs.append((t.id, stmt.value, stmt.lineno))  # type: ignore[attr-defined]
        visitors.append(v)

    tools: dict[str, FoundTool] = {}
    tool_lists: dict[str, list[str]] = {}
    models: dict[str, str] = {}
    model_ids: list[str] = []
    prompts: list[str] = []
    functions: dict[str, FoundTool] = {}
    aliases: dict[str, str] = {}
    strings: dict[str, str] = {}
    returns: dict[str, list[str]] = {}
    for v in visitors:
        returns.update(v.returns)
        functions.update({k: f for k, f in v.functions.items() if k not in functions})
        aliases.update(v.aliases)
        strings.update(v.strings)
    for v in visitors:
        for t in v.tools:
            tools.setdefault(t.name, t)
        # A function made into a tool by a call keeps its own docstring and arguments.
        for fn, override in v.wrapped:
            base = functions.get(fn)
            name = override or aliases.get(fn) or fn
            if base is not None:
                tools.setdefault(name, FoundTool(name, base.doc, base.args, base.file, base.line))
            elif override:
                tools.setdefault(name, FoundTool(name, "", [], v.rel, 0))
        tool_lists.update(v.tool_lists)
        models.update({k: m for k, m in v.models.items() if m})
        model_ids.extend(v.model_ids)
        prompts.extend(
            s for k, s in v.strings.items() if "prompt" in k.lower() or "instruction" in k.lower()
        )
    ctx = _Context(
        tools,
        tool_lists,
        models,
        model_ids,
        project=_project_name(root),
        aliases=aliases,
        strings=strings,
        returns=returns,
    )

    agents: list[FoundAgent] = []
    for v in visitors:
        refs = getattr(v, "module_refs", [])
        referenced = set()
        for var, call, line in refs:
            factory_call = (
                call
                if _call_name(call) in AGENT_FACTORIES
                else v.factories.get(_call_name(call), call)
            )
            referenced.add(id(factory_call))
            agents.append(_agent_from_call(var, factory_call, v, line, ctx))
        for call, _ in v.agent_calls:
            if id(call) not in referenced:
                agents.append(_agent_from_call(None, call, v, call.lineno, ctx))

    # One agent per call site, not per reference to it.
    seen: set[tuple[str, int]] = set()
    unique: list[FoundAgent] = []
    for a in agents:
        key = (a.file, a.line) if a.module is None else (a.module, a.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)
    agents = unique
    # A raw `chat.completions.create(tools=...)` loop is an agent only when nothing else
    # is: beside a framework agent it is a script, a demo or a helper. One per file.
    if any(a.framework != "openai" for a in agents):
        agents = [a for a in agents if a.framework != "openai"]
    else:
        files: set[str] = set()
        agents = [a for a in agents if not (a.file in files or files.add(a.file))]
    project = ctx.project
    if len(agents) == 1:
        a = agents[0]
        # An agent the code never named takes the project's name.
        if not a.named:
            a.name = project
        # One agent and no tools= list: every tool in the repo is its.
        if not a.tool_names and not a.listed:
            a.tool_names = list(tools)

    # Hand-offs name agents by the variable they were assigned to.
    by_var = {a.attr: a for a in agents if a.attr}
    for v in visitors:
        for owner, targets in v.handoffs.items():
            if owner in by_var:
                for t in targets:
                    if t not in by_var[owner].handoffs:
                        by_var[owner].handoffs.append(t)

    who, detail = _who_talks(root, " ".join(prompts))
    structure: dict[str, Any] = {
        "sources": [{"id": "src-1", "label": who, "detail": detail}] if agents else [],
        "agents": [],
        "tools": [],
        "systems": [],
    }
    systems: dict[str, dict[str, str]] = {}
    ids = {id(a): f"ag-{i + 1}" for i, a in enumerate(agents)}
    for i, a in enumerate(agents):
        agent_id = f"ag-{i + 1}"
        structure["agents"].append(
            {
                "id": agent_id,
                "name": a.name,
                "model": a.model or "unknown model",
                "models": a.models,
                "framework": a.framework,
                "sourceIds": ["src-1"],
                "handsOffTo": [
                    ids[id(by_var[t])] for t in a.handoffs if t in by_var and by_var[t] is not a
                ],
            }
        )
        for tname in a.tool_names:
            t = tools.get(tname)
            if not t:
                continue
            risk, _why = classify(t.name, t.doc)
            sys_name, kind = system_for(t.name, t.doc, risk)
            sys_id = "sys-" + re.sub(r"[^a-z0-9]+", "-", sys_name.lower()).strip("-")
            systems.setdefault(sys_id, {"id": sys_id, "name": sys_name, "kind": kind})
            structure["tools"].append(
                {
                    "id": f"t-{agent_id}-{t.name}",
                    "name": t.name,
                    "agentId": agent_id,
                    "risk": risk,
                    "whatItDoes": plain_sentence(t.doc, t.name),
                    "systemId": sys_id,
                    "args": t.args,
                }
            )
    structure["systems"] = list(systems.values())
    runners = [
        {"agentId": f"ag-{i + 1}", "module": a.module, "attr": a.attr, "framework": a.framework}
        for i, a in enumerate(agents)
    ]
    return {"structure": structure, "agents": runners, "project": project, "root": str(root)}


@dataclass
class _Context:
    tools: dict[str, FoundTool]
    tool_lists: dict[str, list[str]]
    models: dict[str, str]
    model_ids: list[str]
    project: str
    aliases: dict[str, str]
    strings: dict[str, str]
    returns: dict[str, list[str]]


def _model_of(node: ast.AST | None, ctx: _Context) -> str | None:
    """`model="gpt-4o"`, `model=MODEL` (a constant), `model=llm` (a chat-model variable)."""
    model = _const_str(node)
    if model:
        return model
    for n in _names_in(node):
        if n in ctx.models:
            return ctx.models[n]
        if n in ctx.strings and _MODEL_ID.match(ctx.strings[n]):
            return ctx.strings[n]
    return None


def _agent_from_call(
    var: str | None, call: ast.Call, v: _FileVisitor, line: int, ctx: _Context
) -> FoundAgent:
    cname = _call_name(call)
    listed_node = _kw(call, "tools")
    tool_names: list[str] = []

    def expand(names: list[str], depth: int = 0) -> None:
        for n in names:
            if n.endswith("()"):
                # A helper that builds the list: follow it (not forever).
                if depth < 3:
                    expand(ctx.returns.get(n[:-2], []), depth + 1)
                continue
            n = ctx.aliases.get(n, n)
            if n in ctx.tool_lists and depth < 3:
                expand(ctx.tool_lists[n], depth + 1)
            elif n not in tool_names:
                tool_names.append(n)

    expand(_tool_refs(listed_node))
    tool_names = [t for t in tool_names if t in ctx.tools]
    model_node = _kw(call, "model", "llm") or (
        call.args[0] if call.args and cname not in ("Agent", "create") else None
    )
    model = _model_of(model_node, ctx)
    candidates = list(dict.fromkeys([m for m in [model, *ctx.model_ids] if m]))
    model = model or (candidates[0] if candidates else None)
    name_node = _kw(call, "name")
    name = _const_str(name_node) or (
        ctx.strings.get(name_node.id) if isinstance(name_node, ast.Name) else None
    )
    framework = "openai" if cname == "create" else AGENT_FACTORIES.get(cname, "python")
    if not _model_of(model_node, ctx) and framework in ("openai", "openai-agents"):
        # The model is chosen at run time; of the ones the config names, an OpenAI one
        # is the likelier for an OpenAI agent.
        candidates.sort(key=lambda m: 0 if re.match(r"^(gpt|o\d)", m, re.I) else 1)
        model = candidates[0] if candidates else None
    agent = FoundAgent(
        name=name or var or ctx.project,
        framework=framework,
        file=v.rel,
        line=line,
        model=model,
        tool_names=tool_names,
        module=v.module if var else None,
        attr=var or _assigned_to(v, call),
        models=candidates[:3],
    )
    agent.named = bool(name)
    agent.listed = listed_node is not None
    agent.handoffs = _agent_refs(_kw(call, "handoffs")) if _kw(call, "handoffs") is not None else []
    return agent


def _assigned_to(v: _FileVisitor, call: ast.Call) -> str | None:
    """The variable an agent call is assigned to anywhere in its file, for hand-offs."""
    return v.assigned.get(id(call))
