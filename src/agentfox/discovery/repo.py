"""Static discovery — point it at a repository and it highlights what is ungoverned.

The adoption problem this solves is not technical. A platform team asked to "adopt
governance" has to first answer a question nobody has written down: *where does this
codebase actually talk to a model?* In a mature repo that is thirty call sites across
eight services, some behind wrappers, some in notebooks, one in a cron job somebody
left. Until that list exists, every governance conversation is speculative.

So this walks the source and produces the list. Deliberately **static** — no import,
no execution, no network. A discovery tool that imports the target codebase runs
arbitrary code from a repo the operator may not trust, and fails on anything with a
side effect at import time, which is most real applications.

The output is ranked by what an engineer should look at first, not by file order. An
alphabetical list of forty findings is the same as no list.

**Reading Python only, and then saying "clean", was the worst failure this scanner
had.** Pointed at a TypeScript repository it opened the three JSON config files it
recognised, matched nothing, and printed "No model calls found" — a security product
reporting a clean result after looking at none of the source. Two things follow from
that and are load-bearing here: the scanner reads TypeScript and JavaScript as well as
Python, and a scan that read no file it understands says exactly that instead of
reporting an absence of findings (:attr:`ScanReport.inconclusive`).

The TypeScript/JavaScript pass is regex over source lines, not a parse: there is no JS
parser in this project's dependencies and adding one to a static scanner is a large
cost for a list of call sites. It is therefore written for precision over recall — a
false "you are ungoverned" is a lie in the same way a false "clean" is. Call shapes
that are ambiguous on their own (LangChain's `.invoke()`, which every runnable
including a prompt template has) are deliberately not matched, so this pass under-
reports rather than inventing findings, and the report says which languages it read.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Directories never worth walking. Skipping them is the difference between a scan
#: that takes a second and one that walks node_modules.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    "site-packages",
    ".tox",
    ".idea",
    ".vscode",
    "htmlcov",
    ".terraform",
}

#: Source files this scanner can actually read for model calls. A file outside this
#: set is counted as skipped and named in the report, never silently ignored.
PYTHON_SUFFIXES = {".py"}
JS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs"}
CODE_SUFFIXES = PYTHON_SUFFIXES | JS_SUFFIXES

#: Read for secrets and for MCP server declarations, not for model calls. Opening one
#: of these is not evidence that the repository's source was examined, which is why
#: they are counted separately from :data:`CODE_SUFFIXES`.
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".env"}

#: What to tell an operator when a scan read nothing it understands.
SUPPORTED_LANGUAGES = "Python (.py), TypeScript and JavaScript (.ts, .tsx, .js, .jsx, .mjs)"

#: Call shapes that mean "a model was invoked". Matched on the attribute path rather
#: than the receiver, because the receiver is a variable whose name we cannot know.
_MODEL_CALLS = {
    "chat.completions.create": "openai",
    "completions.create": "openai",
    "messages.create": "anthropic",
    "responses.create": "openai",
    "generate_content": "vertex",
    "converse": "bedrock",
    "invoke_model": "bedrock",
    "ainvoke": "langchain",
    "invoke": "langchain",
    "predict": "langchain",
    "acompletion": "litellm",
    "completion": "litellm",
}

#: Imports that identify the stack, so the report can say what the repo is built on.
_FRAMEWORK_IMPORTS = {
    "langgraph": "LangGraph",
    "langchain": "LangChain",
    "llama_index": "LlamaIndex",
    "crewai": "CrewAI",
    "autogen": "AutoGen",
    "openai": "OpenAI SDK",
    "anthropic": "Anthropic SDK",
    "litellm": "LiteLLM",
    "boto3": "AWS SDK",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "mcp": "MCP",
    "fastmcp": "FastMCP",
    "ragas": "Ragas",
    "langsmith": "LangSmith",
    "langfuse": "Langfuse",
    "opentelemetry": "OpenTelemetry",
    "agentfox": "AgentFox",
}

#: Tool-ish decorators. A decorated function an agent can call is a tool whether or
#: not anyone registered it, and an unregistered tool is the F-family blind spot.
_TOOL_DECORATORS = ("tool", "function_tool", "mcp.tool", "agent.tool", "register_tool")

#: Tool *constructors* that take the tool's name as a keyword: LangChain's
#: `Tool(name=...)` / `StructuredTool.from_function(name=...)`, LlamaIndex's
#: `FunctionTool.from_defaults(name=...)`.
_TOOL_CONSTRUCTORS = (
    "Tool",
    "StructuredTool",
    "StructuredTool.from_function",
    "FunctionTool.from_defaults",
)

#: Framework orchestration entrypoints — CrewAI's `Crew(...).kickoff()` and
#: LangGraph's `StateGraph(...).compile()` wrap the model call rather than making it
#: directly, so a repo built on either framework can show zero `_MODEL_CALLS` matches
#: while clearly running an agent (confirmed against a real crewAI-examples clone:
#: framework detected, 17 tools found, `model_calls: 0` — a false "nothing to govern"
#: read on the exact frameworks the report says it found). Requires the defining
#: file to have actually imported the framework (checked in `scan_file`), since
#: `compile` and `Crew`/`Agent`-shaped names are too common to trust on their own.
_AGENT_DEFINITIONS = {
    "kickoff": "CrewAI",
    "compile": "LangGraph",
    "Crew": "CrewAI",
    "StateGraph": "LangGraph",
}

#: Executable-artefact shapes worth flagging even without a model call nearby: these
#: are executable output an agent can act through, and a repo that builds SQL from an
#: f-string is where a mass-deletion incident starts.
_SQL_BUILD = re.compile(
    r"""(?:execute|executemany|cursor\.execute|text)\s*\(\s*f?["']\s*"""
    r"""(?:SELECT|INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)""",
    re.I,
)
_SHELL_CALL = re.compile(r"\b(?:os\.system|subprocess\.(?:run|call|Popen|check_output))\s*\(")

#: Secrets in source. Narrow on purpose — a loose pattern here produces a wall of
#: false positives and the report gets ignored.
_HARDCODED_SECRET = re.compile(
    r"""(?:api_key|apikey|secret|password|token)\s*=\s*["'](?:sk-|ghp_|xox|AKIA|AIza)[\w-]{12,}""",
    re.I,
)


@dataclass
class Site:
    """One place in the codebase worth governing."""

    # model_call | agent_definition | tool | mcp_server | lethal_trifecta | sql_build |
    # shell_call | secret
    kind: str
    file: str
    line: int
    detail: str
    provider: str | None = None
    governed: bool = False
    severity: str = "info"
    #: The tool's or MCP server's own name, when the site is one.
    name: str | None = None
    #: Which of the three trifecta flags this tool or server carries
    #: (:data:`agentfox.discovery.exposure.FLAGS`), in that order. Empty means none was found,
    #: which for an unknown MCP server means "could not tell", not "safe".
    capabilities: list[str] = field(default_factory=list)
    #: For a `lethal_trifecta` site: flag -> the tools or servers that supply it.
    evidence: dict[str, Any] = field(default_factory=dict)
    #: The classification itself, with the plain-English phrases. Not serialised.
    caps: Any = field(default=None, repr=False, compare=False)

    def to_json(self) -> dict[str, Any]:
        out = {
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
            "provider": self.provider,
            "governed": self.governed,
            "severity": self.severity,
        }
        if self.kind in ("tool", "mcp_server", "lethal_trifecta"):
            out["name"] = self.name
            out["capabilities"] = self.capabilities
        if self.evidence:
            out["evidence"] = self.evidence
        return out


@dataclass
class ScanReport:
    root: str
    #: Every file opened, source and config alike.
    files_scanned: int = 0
    #: Files opened whose language this scanner can read for model calls
    #: (:data:`CODE_SUFFIXES`). ``None`` means this report did not come from a
    #: filesystem walk at all — an OpenAPI spec scan (`discovery_openapi.py`) or a
    #: hand-built report — so there is nothing to claim about source coverage either
    #: way, and :attr:`inconclusive` stays False.
    code_files_scanned: int | None = None
    #: Suffix -> how many files carried it and were not read. What makes it possible
    #: to say *which* languages were seen and skipped rather than just "none matched".
    skipped_suffixes: dict[str, int] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    governed_files: list[str] = field(default_factory=list)

    @property
    def inconclusive(self) -> bool:
        """True when the walk read no file in a language this scanner understands.

        The distinction this exists to preserve: "we looked and found no model calls"
        and "we could not look" are different answers, and only the first is evidence
        of anything. Reporting the second as the first is a security product calling a
        repository clean after reading none of it, which is how this scanner behaved on
        every TypeScript repository until it learned to read TypeScript.
        """
        return self.code_files_scanned == 0

    def skipped_summary(self, limit: int = 6) -> str:
        """The skipped extensions, most common first, as a readable clause."""
        if not self.skipped_suffixes:
            return "no other files were present"
        ranked = sorted(self.skipped_suffixes.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ", ".join(f"{suffix} ({count})" for suffix, count in ranked[:limit])
        remaining = len(ranked) - limit
        return shown + (f" and {remaining} more extension(s)" if remaining > 0 else "")

    @property
    def model_calls(self) -> list[Site]:
        return [s for s in self.sites if s.kind == "model_call"]

    @property
    def agent_definitions(self) -> list[Site]:
        return [s for s in self.sites if s.kind == "agent_definition"]

    @property
    def tools(self) -> list[Site]:
        return [s for s in self.sites if s.kind == "tool"]

    @property
    def mcp_servers(self) -> list[Site]:
        return [s for s in self.sites if s.kind == "mcp_server"]

    @property
    def trifectas(self) -> list[Site]:
        """Groups that can read private data, ingest untrusted content and send data
        out — see :mod:`agentfox.discovery.exposure`."""
        return [s for s in self.sites if s.kind == "lethal_trifecta"]

    @property
    def governable(self) -> list[Site]:
        """`model_call` sites plus framework orchestration entrypoints.

        A pure `model_call` count is vacuous on a CrewAI/LangGraph repo that never
        calls the provider SDK directly — this is what makes coverage mean something
        on exactly the frameworks the report says it found.
        """
        return self.model_calls + self.agent_definitions

    @property
    def ungoverned(self) -> list[Site]:
        return [s for s in self.governable if not s.governed]

    @property
    def coverage(self) -> float:
        """Fraction of governable call sites that are governed.

        1.0 with no call sites at all means "nothing found to govern", which is only
        meaningful alongside :attr:`inconclusive`: on a scan that read no source, this
        is 1.0 because the denominator is empty, not because anything was verified.
        Any caller showing this number should show `inconclusive` with it.
        """
        calls = self.governable
        if not calls:
            return 1.0
        return sum(1 for s in calls if s.governed) / len(calls)

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for site in self.sites:
            counts[site.kind] = counts.get(site.kind, 0) + 1
        return dict(sorted(counts.items()))

    def ranked(self, limit: int | None = None) -> list[Site]:
        """What to look at first. An alphabetical list of forty findings is no list."""
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        ranked = sorted(
            self.sites,
            key=lambda s: (order.get(s.severity, 9), s.governed, s.file, s.line),
        )
        return ranked[:limit] if limit else ranked

    def to_json(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files_scanned": self.files_scanned,
            "code_files_scanned": self.code_files_scanned,
            "skipped_suffixes": dict(
                sorted(self.skipped_suffixes.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            "supported_languages": SUPPORTED_LANGUAGES,
            # True means this scan read nothing it understands; every count below is
            # then an absence of evidence, not evidence of absence.
            "inconclusive": self.inconclusive,
            "frameworks": self.frameworks,
            "model_calls": len(self.model_calls),
            "agent_definitions": len(self.agent_definitions),
            # Kept as the literal model-call-only count for anyone already reading this
            # key; `ungoverned` (and the coverage it drives) also count framework
            # orchestration entrypoints — see `governable`.
            "ungoverned_model_calls": len([s for s in self.model_calls if not s.governed]),
            "ungoverned_governable": len(self.ungoverned),
            "coverage": round(self.coverage, 3),
            "tools": len(self.tools),
            "mcp_servers": len(self.mcp_servers),
            "lethal_trifectas": [s.to_json() for s in self.trifectas],
            "counts": self.by_kind(),
            "sites": [s.to_json() for s in self.sites],
            "errors": self.errors,
        }

    def to_submission_payload(self, *, source: str) -> dict[str, Any]:
        """The redacted subset of this report that `agentfox scan --submit` /
        `agentfox scan --sessions --submit` are allowed to send to a control plane.

        `to_json()` is for the local `--json` flag and keeps everything, including
        each site's file, line and `detail` — `detail` is the one field that can carry
        literal source text (a shell command line, an f-string). None of that belongs
        off this machine. What crosses the wire is only: counts, which frameworks were
        detected, and — for the three kinds a scan can turn into a proposed agent —
        which top-level directory each one lives in, exactly the granularity the
        connected-repo scan (``routes/integrations.py``) already groups proposals by.
        No file path deeper than its first component, no line numbers, no detail
        text, no error messages.
        """

        def top_dir(rel_path: str) -> str:
            parts = Path(rel_path).parts
            return parts[0] if parts else "root"

        return {
            "source": source,
            "label": Path(self.root).resolve().name or "repo",
            "files_scanned": self.files_scanned,
            "frameworks": self.frameworks,
            "coverage": round(self.coverage, 3),
            "counts": self.by_kind(),
            "sites": [
                {"kind": s.kind, "top_dir": top_dir(s.file), "provider": s.provider}
                for s in self.sites
                # A trifecta crosses the wire as its kind and directory only — enough
                # for `propose_from_scan` to raise that agent's risk tier, nothing
                # about which tools or what they read.
                if s.kind in ("agent_definition", "tool", "model_call", "lethal_trifecta")
            ],
        }

    def next_step(self) -> str:
        """One sentence telling the operator what to do next.

        A report that ends without a next action makes the reader do the synthesis,
        and most readers will not.
        """
        if self.trifectas and not self.inconclusive:
            first = (
                f"{len(self.trifectas)} place(s) in this repository can be steered by an "
                "instruction hidden in content they read into sending private data out. "
                "Contain those first — each lethal-trifecta finding names the command."
            )
            if self.ungoverned or not self.governable:
                return (
                    f"{first} Then add `import agentfox; agentfox.auto()` to your entry "
                    "point to see every model and tool call as it happens."
                )
            # Everything is already wrapped: suggesting auto() again reads as though
            # it would fix the trifecta, and it does not — the tools still reach the
            # same things.
            return (
                f"{first} Every model call here is already governed, and that does not "
                "remove a trifecta: what the tools can reach does."
            )
        if self.inconclusive:
            # Never reachable by the "no model calls found" branch below: a scan that
            # read nothing has no basis for saying anything was absent.
            return (
                "This scan read no source file it understands, so it says nothing about "
                f"whether this repository calls a model. Supported: {SUPPORTED_LANGUAGES}. "
                f"Seen and skipped: {self.skipped_summary()}. "
                "Point the scan at a directory containing source in a supported language, "
                "or govern the calls explicitly with the SDK."
            )
        if not self.governable:
            if self.code_files_scanned is None:
                # Not a filesystem walk (an OpenAPI spec scan), so there is no file
                # count to quote and no language coverage to claim.
                return (
                    "No model calls found. If this repo calls a model through a wrapper "
                    "we don't recognise, govern it explicitly with the SDK."
                )
            return (
                f"No model calls found in {self.code_files_scanned} source file(s). "
                f"This scan reads {SUPPORTED_LANGUAGES}; anything else in the repository "
                "was not examined. If this repo calls a model through a wrapper we don't "
                "recognise, govern it explicitly with the SDK."
            )
        if self.ungoverned:
            return (
                f"{len(self.ungoverned)} model call(s) are ungoverned. Add "
                "`import agentfox; agentfox.auto()` to your entry point — nothing else "
                "in the codebase has to change."
            )
        return "Every model call is governed. Run `agentfox doctor` to check the runtime config."


def _attribute_path(node: ast.AST) -> str:
    """Render `a.b.c(...)` as "a.b.c" without needing to know what `a` is."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _str_value(node: ast.AST | None) -> str | None:
    """The string a node is, if it is a literal one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    return _attribute_path(node) if isinstance(node, ast.Attribute | ast.Name) else ""


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.sites: list[Site] = []
        self.frameworks: set[str] = set()
        self.governed = False
        # Framework-gated until the full file is visited (see scan_file) — the import
        # may appear anywhere relative to the call in an unusual layout.
        self._pending_agent_defs: list[tuple[Site, str]] = []
        self._tool_names: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._note_import(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self._note_import(node.module)
        self.generic_visit(node)

    def _note_import(self, module: str) -> None:
        root = module.split(".")[0]
        label = _FRAMEWORK_IMPORTS.get(root)
        if label:
            self.frameworks.add(label)
        if root == "agentfox":
            self.governed = True

    def visit_Call(self, node: ast.Call) -> None:
        path = _attribute_path(node.func)
        # `agentfox.auto()` anywhere in a file means its model calls are governed.
        if path.endswith("auto") and "agentfox" in path:
            self.governed = True
        for suffix, provider in _MODEL_CALLS.items():
            if path.endswith(suffix):
                # `invoke` and `completion` are common words; require a model-ish
                # keyword before claiming a model call, or every .invoke() in a repo
                # becomes a finding.
                if suffix in ("invoke", "ainvoke", "predict", "completion") and not any(
                    kw.arg in ("model", "messages", "prompt", "input") for kw in node.keywords
                ):
                    continue
                self.sites.append(
                    Site(
                        kind="model_call",
                        file=self.path,
                        line=node.lineno,
                        detail=f"{path}(...)",
                        provider=provider,
                        severity="high",
                    )
                )
                break
        if path in _TOOL_CONSTRUCTORS or any(path.endswith(f".{c}") for c in _TOOL_CONSTRUCTORS):
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            name = _str_value(kwargs.get("name"))
            if name:
                self._add_tool(
                    name,
                    _str_value(kwargs.get("description")) or "",
                    node.lineno,
                    f"{path}(name={name!r})",
                )
        for suffix, fw in _AGENT_DEFINITIONS.items():
            if path == suffix or path.endswith(f".{suffix}"):
                self._pending_agent_defs.append(
                    (
                        Site(
                            kind="agent_definition",
                            file=self.path,
                            line=node.lineno,
                            detail=f"{path}(...)",
                            provider=fw.lower(),
                            severity="high",
                        ),
                        fw,
                    )
                )
                break
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_tool(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_tool(node)
        self.generic_visit(node)

    def _check_tool(self, node: Any) -> None:
        for decorator in node.decorator_list:
            name = _decorator_name(decorator)
            if any(name.endswith(marker) for marker in _TOOL_DECORATORS):
                # `@tool("lookup")` names the tool explicitly; otherwise it is the
                # function's own name.
                explicit = None
                if isinstance(decorator, ast.Call) and decorator.args:
                    explicit = _str_value(decorator.args[0])
                self._add_tool(
                    explicit or node.name,
                    ast.get_docstring(node) or "",
                    node.lineno,
                    f"@{name} {node.name}()",
                )
                break

    def visit_Dict(self, node: ast.Dict) -> None:
        """A tool handed to a model as a schema rather than a decorated function.

        This is how most production agents built on a provider SDK declare tools —
        `client.chat.completions.create(tools=[{"type": "function", ...}])`, often
        through a module-level list. Matching the dict itself, wherever it sits,
        covers the inline `tools=` kwarg, the list assigned to a variable and passed
        later, and the list built in another module, without data-flow analysis.
        """
        entries = {
            k.value: v
            for k, v in zip(node.keys, node.values, strict=False)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        kind = None
        name = description = None
        if _str_value(entries.get("type")) == "function":
            inner = entries.get("function")
            if isinstance(inner, ast.Dict):
                # Chat Completions: {"type": "function", "function": {"name": ...}}
                fields = {
                    k.value: v
                    for k, v in zip(inner.keys, inner.values, strict=False)
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
                name = _str_value(fields.get("name"))
                description = _str_value(fields.get("description"))
                kind = "OpenAI function schema"
            elif "name" in entries and "parameters" in entries:
                # Responses API: the same fields, flattened.
                name = _str_value(entries.get("name"))
                description = _str_value(entries.get("description"))
                kind = "OpenAI function schema"
        elif "name" in entries and "input_schema" in entries:
            name = _str_value(entries.get("name"))
            description = _str_value(entries.get("description"))
            kind = "Anthropic tool schema"
        if kind and name:
            self._add_tool(name, description or "", node.lineno, f"{kind} {name}")
        self.generic_visit(node)

    def _add_tool(self, name: str, description: str, line: int, how: str) -> None:
        # The same schema appears twice in one file often enough (a list built twice,
        # a retry path) that counting it twice would inflate the headline.
        if name in self._tool_names:
            return
        self._tool_names.add(name)
        from agentfox.discovery.exposure import FLAG_LABEL, classify_tool

        caps = classify_tool(name, description)
        flags = caps.ordered()
        what = "; ".join(caps.phrases.get(f, FLAG_LABEL[f]) for f in flags)
        self.sites.append(
            Site(
                kind="tool",
                file=self.path,
                line=line,
                detail=f"tool {how}" + (f" — {what}" if what else ""),
                severity="medium",
                name=name,
                capabilities=flags,
                caps=caps,
            )
        )


# ---------------------------------------------------------------------------
# TypeScript / JavaScript
# ---------------------------------------------------------------------------
#
# Regex over source lines, not a parse. Written for precision: every pattern below is
# either an attribute path that is distinctive on its own (`.chat.completions.create`)
# or a bare name that is only counted when the file imported the package it belongs to
# (`generateText` without an import from `ai` is somebody else's function).
#
# Deliberately not matched, and why:
#   * `.invoke()` / `.stream()` / `.batch()` — in LangChain JS these are the methods on
#     every runnable, including prompt templates and output parsers. Matching them
#     would report a prompt template as a model call. The model constructors below are
#     matched instead, which is one site per model rather than one per chain call.
#   * `useChat` / `useCompletion` — React hooks that call the app's own route handler,
#     not a provider. The route handler is where the model call is, and it is matched
#     there.
#   * `embed` / `embedMany` — embeddings, not generation, so nothing to govern.
#
# The cost of that choice, stated rather than left to be discovered: a call shape that
# is ambiguous on its own is only counted in a file that imported the SDK it belongs
# to. A repository that constructs its client in one module and calls it from another
# will have the call under-reported. That is the direction to be wrong in for a tool
# whose other failure mode is telling a team they are ungoverned when they are not —
# and the scan still names the framework, so the report does not go silent.

#: Module specifier -> framework label. Looked up longest-prefix-first, so
#: `@langchain/langgraph` beats `@langchain` and a subpath import resolves to its
#: package.
_JS_FRAMEWORK_IMPORTS = {
    "openai": "OpenAI SDK",
    "@anthropic-ai/sdk": "Anthropic SDK",
    "@anthropic-ai/bedrock-sdk": "Anthropic SDK",
    "@anthropic-ai/vertex-sdk": "Anthropic SDK",
    "ai": "Vercel AI SDK",
    "@ai-sdk": "Vercel AI SDK",
    "@langchain/langgraph": "LangGraph",
    "@langchain": "LangChain",
    "langchain": "LangChain",
    "llamaindex": "LlamaIndex",
    "@llamaindex": "LlamaIndex",
    "crewai-ts": "CrewAI",
    "@modelcontextprotocol/sdk": "MCP",
    "@google/generative-ai": "Google GenAI SDK",
    "@google/genai": "Google GenAI SDK",
    "@google-cloud/vertexai": "Google GenAI SDK",
    "@aws-sdk/client-bedrock-runtime": "AWS SDK",
    "next": "Next.js",
    "express": "Express",
    "langfuse": "Langfuse",
    "langsmith": "LangSmith",
    "@opentelemetry": "OpenTelemetry",
}

#: `import x from "pkg"`, `import "pkg"`, `require("pkg")`, `await import("pkg")`.
_JS_IMPORT = re.compile(r"""\b(?:from|require|import)\s*\(?\s*["']([^"']+)["']""")

#: A line that is only a comment. Cheap guard against a commented-out call, or prose
#: in a docblock, becoming a finding.
_JS_COMMENT_LINE = re.compile(r"^\s*(?://|/\*|\*)")

#: (pattern, provider, required framework labels or None if the shape stands alone).
_JS_MODEL_CALLS: tuple[tuple[re.Pattern[str], str, tuple[str, ...] | None], ...] = (
    (re.compile(r"\.chat\.completions\.(?:create|stream)\s*\("), "openai", None),
    (re.compile(r"\.beta\.chat\.completions\.(?:parse|stream)\s*\("), "openai", None),
    # Gated: each of these is a plausible method name on something that is not a
    # model client (`db.messages.create`, `surveyResponses.create`), so the file has
    # to have imported the SDK for the shape to mean what it looks like.
    (re.compile(r"\.responses\.(?:create|stream|parse)\s*\("), "openai", ("OpenAI SDK",)),
    (re.compile(r"\.completions\.create\s*\("), "openai", ("OpenAI SDK",)),
    (
        re.compile(r"\.messages\.(?:create|stream)\s*\("),
        "anthropic",
        ("Anthropic SDK",),
    ),
    (
        re.compile(r"\.generateContent(?:Stream)?\s*\("),
        "google",
        ("Google GenAI SDK",),
    ),
    (
        re.compile(
            r"\bnew\s+(?:ConverseCommand|ConverseStreamCommand|InvokeModelCommand"
            r"|InvokeModelWithResponseStreamCommand)\s*\("
        ),
        "bedrock",
        None,
    ),
    (
        re.compile(
            r"\bnew\s+Chat(?:OpenAI|Anthropic|GoogleGenerativeAI|VertexAI|BedrockConverse"
            r"|MistralAI|Ollama|Groq|Fireworks|Together|Cohere|DeepSeek)\s*\("
        ),
        "langchain",
        ("LangChain", "LangGraph"),
    ),
    (re.compile(r"\binitChatModel\s*\("), "langchain", ("LangChain", "LangGraph")),
    (
        re.compile(r"\b(?:generateText|streamText|generateObject|streamObject|streamUI)\s*\("),
        "vercel-ai",
        ("Vercel AI SDK",),
    ),
)

#: Framework orchestration entrypoints — same reasoning as `_AGENT_DEFINITIONS` for
#: Python: these wrap the model call rather than making it, so a repo built on one can
#: show zero model calls while clearly running an agent.
_JS_AGENT_DEFINITIONS: tuple[tuple[re.Pattern[str], str, tuple[str, ...]], ...] = (
    (re.compile(r"\bcreateReactAgent\s*\("), "LangGraph", ("LangChain", "LangGraph")),
    (re.compile(r"\bnew\s+StateGraph\s*\("), "LangGraph", ("LangChain", "LangGraph")),
    (re.compile(r"\bnew\s+AgentExecutor\s*\("), "LangChain", ("LangChain", "LangGraph")),
)

#: Tool declarations, each gated on the package that defines the shape.
_JS_TOOLS: tuple[tuple[re.Pattern[str], str, tuple[str, ...]], ...] = (
    (re.compile(r"\btool\s*\(\s*\{"), "Vercel AI SDK tool", ("Vercel AI SDK",)),
    (
        re.compile(r"""\.(?:registerTool|tool)\s*\(\s*["']([\w.\-]+)["']"""),
        "MCP tool",
        ("MCP",),
    ),
)


_JS_NAMED_TOOL = re.compile(r"""\b(\w+)["']?\s*[:=]\s*tool\s*\(\s*\{""")


def _js_framework(specifier: str) -> str | None:
    """Resolve an import specifier to a framework label, longest prefix first.

    Relative imports are the repository's own modules and carry no framework
    information, so they resolve to nothing.
    """
    if not specifier or specifier.startswith((".", "/")):
        return None
    candidates = [specifier]
    parts = specifier.split("/")
    if specifier.startswith("@"):
        candidates.append("/".join(parts[:2]))
        candidates.append(parts[0])
    else:
        candidates.append(parts[0])
    for candidate in candidates:
        label = _JS_FRAMEWORK_IMPORTS.get(candidate)
        if label:
            return label
    return None


def _js_code_only(source: str) -> list[str]:
    """The source's lines with everything inside string, template and comment
    literals blanked to spaces, so columns and line numbers are unchanged.

    A pattern found in a literal is text about code, not code: a docs page that
    shows `client.chat.completions.create(...)` in a template string calls no model.
    Expressions inside a template literal's `${...}` stay code. JSX `<code>` and
    `<pre>` contents are blanked too: they are text a page shows, never executed.
    """
    out = list(source)
    i, n = 0, len(source)
    stack: list[str] = []  # open template literals and the `${` braces inside them
    depth: list[int] = []
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        in_template = bool(stack) and stack[-1] == "`"
        if in_template:
            if c == "\\":
                out[i] = " "
                if i + 1 < n and source[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if c == "`":
                stack.pop()
                i += 1
                continue
            if c == "$" and nxt == "{":
                stack.append("{")
                depth.append(0)
                i += 2
                continue
            if c != "\n":
                out[i] = " "
            i += 1
            continue
        if stack and stack[-1] == "{":
            if c == "{":
                depth[-1] += 1
            elif c == "}":
                if depth[-1] == 0:
                    stack.pop()
                    depth.pop()
                    i += 1
                    continue
                depth[-1] -= 1
        if c == "<" and (source.startswith("<code", i) or source.startswith("<pre", i)):
            # JSX <code>/<pre> content is text shown to a reader, never executed.
            tag = "code" if source.startswith("<code", i) else "pre"
            start = source.find(">", i)
            end = source.find(f"</{tag}>", start)
            if start != -1 and end != -1:
                for k in range(start + 1, end):
                    if source[k] != "\n":
                        out[k] = " "
                i = end + len(tag) + 3
                continue
        if c == "/" and nxt == "/":
            j = source.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and nxt == "*":
            j = source.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if source[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c in "'\"":
            j = i + 1
            while j < n and source[j] != c and source[j] != "\n":
                j += 2 if source[j] == "\\" else 1
            for k in range(i + 1, min(j, n)):
                out[k] = " "
            i = j + 1
            continue
        if c == "`":
            stack.append("`")
        i += 1
    return "".join(out).splitlines()


def _scan_javascript(source: str, rel: str) -> tuple[list[Site], set[str]]:
    """Find model calls, agent definitions and tool declarations in one TS/JS file.

    Two passes, because an import can appear below the call that needs it (a top-level
    `await import`, or simply a file whose imports are not all at the top): frameworks
    are collected first, then the gated patterns are matched against that set.
    """
    lines = source.splitlines()
    frameworks: set[str] = set()
    for line in lines:
        if _JS_COMMENT_LINE.match(line):
            continue
        for specifier in _JS_IMPORT.findall(line):
            label = _js_framework(specifier)
            if label:
                frameworks.add(label)

    def gated(required: tuple[str, ...] | None) -> bool:
        return required is None or bool(frameworks.intersection(required))

    code_lines = _js_code_only(source)
    sites: list[Site] = []
    for line_no, line in enumerate(lines, start=1):
        if _JS_COMMENT_LINE.match(line):
            continue
        code = code_lines[line_no - 1] if line_no <= len(code_lines) else line
        # One site per line, most specific pattern first, so `.chat.completions.create`
        # is not also counted by `.completions.create`. Matched against `code`, so a
        # call shown inside a string or a comment is not counted as one.
        for pattern, provider, required in _JS_MODEL_CALLS:
            match = pattern.search(code)
            if match and gated(required):
                sites.append(
                    Site(
                        kind="model_call",
                        file=rel,
                        line=line_no,
                        detail=match.group(0).strip(),
                        provider=provider,
                        severity="high",
                    )
                )
                break
        for pattern, framework, required in _JS_AGENT_DEFINITIONS:
            match = pattern.search(code)
            if match and gated(required):
                sites.append(
                    Site(
                        kind="agent_definition",
                        file=rel,
                        line=line_no,
                        detail=match.group(0).strip(),
                        provider=framework.lower(),
                        severity="high",
                    )
                )
                break
        for pattern, label, required in _JS_TOOLS:
            match = pattern.search(line)
            # Tool names live in string literals, so the line is matched as written,
            # but the match has to start in code.
            if match and code[match.start()] == line[match.start()] and gated(required):
                name = match.group(1) if match.groups() else None
                if name is None:
                    # `const sendEmail = tool({` / `sendEmail: tool({` names the tool.
                    named = _JS_NAMED_TOOL.search(line)
                    name = named.group(1) if named else None
                caps = None
                flags: list[str] = []
                what = ""
                if name:
                    from agentfox.discovery.exposure import FLAG_LABEL, classify_tool

                    caps = classify_tool(name)
                    flags = caps.ordered()
                    what = "; ".join(caps.phrases.get(f, FLAG_LABEL[f]) for f in flags)
                sites.append(
                    Site(
                        kind="tool",
                        file=rel,
                        line=line_no,
                        detail=f"{label}: {match.group(0).strip()}"
                        + (f" — {what}" if what else ""),
                        severity="medium",
                        name=name,
                        capabilities=flags,
                        caps=caps,
                    )
                )
                break
    return sites, frameworks


def scan_file(path: Path, root: Path) -> tuple[list[Site], set[str], bool]:
    rel = str(path.relative_to(root))
    try:
        source = path.read_text(errors="ignore")
    except OSError as exc:  # pragma: no cover - unreadable file
        raise RuntimeError(f"{rel}: {exc}") from exc

    sites: list[Site] = []
    frameworks: set[str] = set()
    governed = False

    if path.suffix == ".py":
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:
            # A file we cannot parse is reported, never skipped silently: an
            # unparseable file is exactly where an ungoverned call would hide.
            raise RuntimeError(f"{rel}: {exc.msg} (line {exc.lineno})") from exc
        visitor = _Visitor(rel)
        visitor.visit(tree)
        sites.extend(visitor.sites)
        sites.extend(site for site, fw in visitor._pending_agent_defs if fw in visitor.frameworks)
        frameworks |= visitor.frameworks
        governed = visitor.governed
    elif path.suffix in JS_SUFFIXES:
        js_sites, js_frameworks = _scan_javascript(source, rel)
        sites.extend(js_sites)
        frameworks |= js_frameworks

    for line_no, line in enumerate(source.splitlines(), start=1):
        if _SQL_BUILD.search(line):
            sites.append(
                Site(
                    kind="sql_build",
                    file=rel,
                    line=line_no,
                    detail="SQL built from a string in code — only checked if the "
                    "query passes through a governed tool",
                    severity="medium",
                )
            )
        if _SHELL_CALL.search(line):
            sites.append(
                Site(
                    kind="shell_call",
                    file=rel,
                    line=line_no,
                    detail=line.strip()[:90],
                    severity="medium",
                )
            )
        if _HARDCODED_SECRET.search(line):
            sites.append(
                Site(
                    kind="secret",
                    file=rel,
                    line=line_no,
                    # Never echo the match: a scan report that reprints the key it found
                    # is a second copy of the leak.
                    detail="hard-coded credential in source",
                    severity="critical",
                )
            )
    return sites, frameworks, governed


def scan(root: str | Path = ".", *, include_config: bool = True) -> ScanReport:
    """Walk a repository and report every surface worth governing."""
    root_path = Path(root).resolve()
    report = ScanReport(root=str(root_path))
    frameworks: set[str] = set()

    suffixes = set(CODE_SUFFIXES)
    if include_config:
        suffixes |= CONFIG_SUFFIXES
    report.code_files_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix not in suffixes:
                # Recorded, not discarded: "we read nothing here" is the finding that
                # matters when the answer comes back empty, and it cannot be recovered
                # later from a count of files that were read.
                suffix = path.suffix.lower() or "(no extension)"
                report.skipped_suffixes[suffix] = report.skipped_suffixes.get(suffix, 0) + 1
                continue
            report.files_scanned += 1
            if path.suffix in CODE_SUFFIXES:
                report.code_files_scanned += 1
            try:
                sites, found, governed = scan_file(path, root_path)
            except RuntimeError as exc:
                report.errors.append(str(exc))
                continue
            frameworks |= found
            if governed:
                report.governed_files.append(str(path.relative_to(root_path)))
            for site in sites:
                if site.kind in ("model_call", "agent_definition") and governed:
                    site.governed = True
                    site.severity = "info"
                report.sites.append(site)

    report.frameworks = sorted(frameworks)
    _detect_mcp(root_path, report)
    _detect_trifectas(report)
    return report


def _detect_mcp(root: Path, report: ScanReport) -> None:
    """MCP servers are declared in config, not code, so they need their own pass.

    Reads every MCP client config under the root (`.mcp.json`, `.cursor/mcp.json`,
    `claude_desktop_config.json`, `.claude.json`, `.claude/settings*.json`) and never
    starts a server: what a server can do is classified from how it is declared.
    """
    from agentfox.discovery.exposure import (
        FLAG_LABEL,
        MCP_CONFIG_NAMES,
        classify_mcp_server,
        parse_mcp_config,
    )

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            claude_settings = Path(dirpath).name == ".claude" and filename in (
                "settings.json",
                "settings.local.json",
            )
            if filename not in MCP_CONFIG_NAMES and not claude_settings:
                continue
            path = Path(dirpath) / filename
            for decl in parse_mcp_config(path, root=root):
                caps = classify_mcp_server(decl)
                flags = caps.ordered()
                if not caps.known:
                    what = (
                        "unknown server — AgentFox can't tell what it can reach; give it "
                        f"the tool list with `agentfox scan mcp {decl.name} --file tools.json`"
                    )
                elif flags:
                    what = "; ".join(caps.phrases.get(f, FLAG_LABEL[f]) for f in flags)
                else:
                    what = "no access to private data or the outside world"
                if decl.url:
                    drift = "Remote, so its tools can change at any time"
                elif decl.pinned_version:
                    drift = f"Pinned to {decl.pinned_version}"
                else:
                    drift = "No version pinned, so its tools can change after you review them"
                report.sites.append(
                    Site(
                        kind="mcp_server",
                        file=decl.config,
                        line=1,
                        detail=f"MCP server '{decl.name}' — {what}. {drift}",
                        severity="high",
                        name=decl.name,
                        capabilities=flags,
                        caps=caps,
                    )
                )


def _detect_trifectas(report: ScanReport) -> None:
    """Add one critical `lethal_trifecta` site per group that has all three legs.

    Grouping, and why:

    * **Tools in code are grouped by directory.** A Python package or a JS app
      directory is the closest static stand-in for "one agent": tools declared in
      `tools.py` are handed to the model in `agent.py` next to it far more often
      than across packages. A group whose tools all sit in one file is labelled with
      that file; otherwise with the directory.
    * **MCP servers are grouped by the config file that declares them.** Every
      server in one `.mcp.json` is loaded into the same client session, so they
      share one model — that is exactly the condition the trifecta needs. They are
      not merged with code tools in the same directory, because an MCP config
      configures an IDE or assistant, not necessarily the application beside it.
    """
    from agentfox.discovery.exposure import Member, containment_hint, trifecta_sentence

    code_groups: dict[str, list[Site]] = {}
    mcp_groups: dict[str, list[Site]] = {}
    for site in report.sites:
        if site.kind == "tool" and site.caps is not None and site.name:
            code_groups.setdefault(str(Path(site.file).parent), []).append(site)
        elif site.kind == "mcp_server" and site.caps is not None and site.name:
            mcp_groups.setdefault(site.file, []).append(site)

    found: list[Site] = []
    for groups, mcp in ((code_groups, False), (mcp_groups, True)):
        for directory, sites in sorted(groups.items()):
            files = sorted({s.file for s in sites})
            if mcp or len(files) == 1:
                label = files[0]
            else:
                label = "./" if directory == "." else f"{directory}/"
            members = [Member(s.name or "?", s.caps, s.file, s.line) for s in sites]
            unknown = [s.name or "?" for s in sites if not s.caps.known]
            result = trifecta_sentence(label, members, unknown=unknown)
            if result is None:
                continue
            sentence, evidence = result
            first = min(sites, key=lambda s: (s.file, s.line))
            found.append(
                Site(
                    kind="lethal_trifecta",
                    file=label,
                    line=first.line,
                    detail=sentence,
                    provider="mcp" if mcp else None,
                    severity="critical",
                    capabilities=["private_data", "untrusted_input", "exfiltration"],
                    evidence={**evidence, "fix": containment_hint(evidence, mcp=mcp)},
                )
            )
    # First in the list as well as first in severity: this is the finding.
    report.sites[:0] = found
