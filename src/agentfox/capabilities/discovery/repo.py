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
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentfox.capabilities.discovery import platforms
from agentfox.capabilities.discovery.agents import (
    AgentCollector,
    AgentEdge,
    AgentSpec,
    agent_key,
    is_test_path,
    wrapped_tool,
)

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
    # AutoGen 0.4+ ships as separate packages; AG2 is the community fork's name.
    "autogen_agentchat": "AutoGen",
    "autogen_core": "AutoGen",
    "autogen_ext": "AutoGen",
    "ag2": "AutoGen",
    "langgraph_supervisor": "LangGraph",
    "langgraph_swarm": "LangGraph",
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
    # Agent frameworks the agent pass reads by shape rather than by a constructor of
    # its own; naming the stack here keeps the report from saying "custom".
    "pydantic_ai": "Pydantic AI",
    "strands": "Strands Agents",
    "agno": "Agno",
    "smolagents": "smolagents",
    "dspy": "DSPy",
    "haystack": "Haystack",
    "semantic_kernel": "Semantic Kernel",
    "agent_framework": "Microsoft Agent Framework",
    "claude_agent_sdk": "Claude Agent SDK",
    "bedrock_agentcore": "Bedrock AgentCore",
    # Voice agents: a framework that runs the pipeline in this process, or the SDK of
    # a hosted platform the agent is configured on (see `discovery/platforms.py`).
    "livekit": "LiveKit",
    "pipecat": "Pipecat",
    "vapi": "Vapi",
    "vapi_python": "Vapi",
    "vapi_server_sdk": "Vapi",
    "retell": "Retell",
    "elevenlabs": "ElevenLabs",
    "telnyx": "Telnyx",
    "twilio": "Twilio",
    "smallestai": "Smallest AI",
    "synthflow": "Synthflow",
}

#: Imports matched by dotted prefix, for packages whose top-level name (`google`) is
#: shared with unrelated SDKs. The OpenAI Agents SDK's `agents` is left to the agent
#: pass: a repository's own `agents` package is too common to label from the import.
_FRAMEWORK_PREFIXES = {
    "google.adk": "Google ADK",
    "google.cloud.dialogflowcx": "Dialogflow CX",
    "google.cloud.dialogflow_v2": "Dialogflow",
    # `livekit` alone is the rooms and media SDK; the agent framework is a subpackage.
    "livekit.agents": "LiveKit Agents",
    "livekit.plugins": "LiveKit Agents",
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

#: Constructors that *define* an agent system without running it: CrewAI's
#: `Crew(...)` and LangGraph's `StateGraph(...)`. Reported as `agent_definition`
#: sites, for the inventory, and deliberately **not** counted as model calls: a
#: definition calls nothing, and counting each one (2,031 of them in LangGraph's own
#: repository, plus every `re.compile` in a file that imported LangGraph) made the
#: coverage line read "2039 of 8 model call sites". Requires the defining file to have
#: imported the framework (checked in `scan_file`), since `Crew`-shaped names are too
#: common to trust on their own. What *runs* one of these (`crew.kickoff()`,
#: `graph.invoke()`, `Runner.run()`) is a model call: see :data:`_AGENT_RUNS`.
_AGENT_DEFINITIONS = {
    "Crew": "CrewAI",
    "StateGraph": "LangGraph",
}

#: Calls that run an agent, and so call its model, for frameworks that wrap the
#: provider call: a repository built on one can show zero provider calls while
#: clearly running an agent (crewAI-examples: 17 tools, `model_calls: 0`; the Agents
#: SDK's customer-service example: three agents, then "No model calls found").
#: Path -> (provider, the name the file must import for the shape to mean this).
_AGENT_RUNS = {
    "Runner.run": ("openai-agents", "Runner"),
    "Runner.run_sync": ("openai-agents", "Runner"),
    "Runner.run_streamed": ("openai-agents", "Runner"),
}
#: Methods that run an agent object, whichever framework built it: `agent.run_sync()`
#: (Pydantic AI), `team.run()` (AutoGen), `agent.invoke()` (LangGraph), `agent.chat()`
#: (LlamaIndex). Counted only on a variable the agent pass found an agent in (see
#: `_promote_agent_runs`), never on the method name alone.
_AGENT_METHODS = {
    "run", "run_sync", "run_stream", "run_async", "arun", "iter", "invoke", "ainvoke",
    "stream", "astream", "kickoff", "kickoff_async", "chat", "achat", "query", "aquery",
    "initiate_chat", "a_initiate_chat", "generate_reply", "a_generate_reply", "run_live",
    "run_stream_events",
}  # fmt: skip

#: CrewAI's run methods, on a crew or a flow; counted in a file that imported crewai.
_CREW_RUNS = ("kickoff", "kickoff_async", "kickoff_for_each", "kickoff_for_each_async")

#: LangChain runnable methods. On their own they mean nothing (a prompt template and
#: an output parser have them too); on a chat model or a compiled graph they are the
#: model call.
_RUNNABLE_METHODS = ("invoke", "ainvoke", "stream", "astream", "batch", "abatch")

#: Calls whose result is a chat model: tools or a schema can only be bound to one, and
#: these constructors build one.
_CHAT_MODEL_CALLS = ("bind_tools", "with_structured_output", "init_chat_model")
_CHAT_MODEL_CLASS = re.compile(
    r"^(?:Azure)?Chat(?:OpenAI|Anthropic\w*|Google\w*|Vertex\w*|Bedrock\w*|Mistral\w*"
    r"|Ollama|Groq|Fireworks|Together|Cohere|DeepSeek|XAI|Perplexity|LiteLLM\w*|HuggingFace"
    r"|NVIDIA|Databricks|Watsonx|Cerebras|Ollama\w*)$"
)
#: Calls whose result runs as an agent graph, and the builders `.compile()` turns into one.
_GRAPH_FACTORIES = ("create_react_agent", "create_agent")
_GRAPH_BUILDERS = ("StateGraph", "MessageGraph", "create_supervisor", "create_swarm")


def _chain(expr: ast.AST) -> list[ast.Call]:
    """The calls along a receiver chain, outermost first: `a(x).b(y)` -> [b(y), a(x)]."""
    out: list[ast.Call] = []
    node = expr
    while True:
        if isinstance(node, ast.Await):
            node = node.value
        elif isinstance(node, ast.Call):
            out.append(node)
            node = node.func
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            return out


def _last(call: ast.Call) -> str:
    """The name a call is made by: `a.b.c(...)` -> "c"."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


#: Executable-artefact shapes worth flagging even without a model call nearby: these
#: are executable output an agent can act through, and a repo that builds SQL from an
#: f-string is where a mass-deletion incident starts.
_SQL_BUILD = re.compile(
    r"""(?:execute|executemany|cursor\.execute|text)\s*\(\s*f?["']\s*"""
    r"""(?:SELECT|INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)""",
    re.I,
)


def _sql_is_built(line: str, match: re.Match[str]) -> bool:
    """Whether the SQL string `_SQL_BUILD` matched is assembled from values rather than
    written out. A constant query with placeholders (`"... WHERE id = ?", (uid,)`)
    is the safe shape and is not a finding; an f-string, `%` or `.format()` on the
    literal, or `+` onto it, is. A literal that runs past the line, or ends it, is
    reported, since the rest cannot be seen from here."""
    text = match.group(0)
    quote_at = max(text.rfind('"'), text.rfind("'"))
    if quote_at < 0:  # pragma: no cover - the pattern always contains a quote
        return True
    if text[:quote_at].endswith("f"):
        return True
    quote = text[quote_at]
    start = match.start() + quote_at + 1
    i = start
    while i < len(line):
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == quote:
            break
        i += 1
    else:
        return True
    rest = line[i + 1 :].lstrip()
    # Nothing after the literal on this line: what joins it comes on the next one.
    return not rest or rest.startswith(("%", "+", ".format"))


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
    #: (:data:`agentfox.capabilities.discovery.exposure.FLAGS`), in that order. Empty means none was
    #: found,
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
    #: filesystem walk at all — an OpenAPI spec scan (`discovery/openapi.py`) or a
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
    #: Each agent the code defines, with its own tools, and which hands work to which
    #: (:mod:`agentfox.capabilities.discovery.agents`). Empty for a repository whose
    #: framework is not one that module reads, which is not a claim there are none.
    agents: list[AgentSpec] = field(default_factory=list)
    agent_edges: list[AgentEdge] = field(default_factory=list)
    #: Tools the scan found that no agent above is handed: defined but unused, or used
    #: in a way the static read could not follow. Test, mock and fixture files are left
    #: out. Local only: like every tool name, never part of a submission.
    unassigned_tools: list[str] = field(default_factory=list)
    #: Test, docs and benchmark files left out of the report (`scan(include_tests=...)`),
    #: read for hard-coded secrets only. Counted so the output can say so.
    excluded_files: int = 0

    @property
    def multi_agent(self) -> bool:
        """Two or more agents were found, so the scan proposes one per agent instead
        of one per directory (``registry.service.propose_from_scan``)."""
        return len(self.agents) >= 2

    def agent_summary(self, limit: int = 8) -> list[str]:
        """The multi-agent structure as short lines for a terminal: a count, then each
        agent that hands work on and to whom. Empty for a single-agent repository."""
        if not self.multi_agent:
            return []
        lines = [f"{len(self.agents)} agents, {len(self.agent_edges)} handoff(s) between them"]
        # "{parent} hands off to {children}", or with a suffix: "triage uses kb as a tool".
        words = {
            "handoff": ("hands off to", ""),
            "as_tool": ("uses", " as a tool"),
            "delegates": ("delegates to", ""),
            "member": ("runs", ""),
        }
        children: dict[tuple[str, str], list[str]] = {}
        for edge in self.agent_edges:
            children.setdefault((edge.parent, edge.relation), []).append(edge.child)
        for (parent, relation), kids in list(children.items())[:limit]:
            verb, after = words.get(relation, ("delegates to", ""))
            lines.append(f"{parent} {verb} {', '.join(kids)}{after}")
        if len(children) > limit:
            lines.append(f"... and {len(children) - limit} more; `--json` lists them all")
        return lines

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
        out — see :mod:`agentfox.capabilities.discovery.exposure`."""
        return [s for s in self.sites if s.kind == "lethal_trifecta"]

    @property
    def governable(self) -> list[Site]:
        """The call sites coverage is measured over: `model_call` sites only.

        A framework that wraps the provider call is covered by counting the call that
        *runs* its agent (`Runner.run`, `crew.kickoff`, a compiled graph's `invoke`) as a
        model call, not by counting its definitions: a `StateGraph(...)` calls nothing,
        and adding the 2,031 in LangGraph's own repository to an 8-call denominator is
        how "2039 of 8 model call sites are ungoverned" was printed.
        """
        return self.model_calls

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
            # The multi-agent structure: one entry per agent (with its own tools) and
            # one per "parent hands work to child" relation between them.
            "agents": [a.to_json() for a in self.agents],
            "agent_edges": [e.to_json() for e in self.agent_edges],
            "unassigned_tools": self.unassigned_tools,
            "excluded_files": self.excluded_files,
        }

    def to_submission_payload(self, *, source: str, tool_names: bool = False) -> dict[str, Any]:
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

        It also carries each agent the code defines, by name, framework, kind and
        top-level directory, and for a multi-agent system which agent hands work to
        which: the structure a reviewer needs to approve the system as the separate
        agents it is. A single agent is sent too, so its proposal carries the name
        `agentfox up` and `agentfox init` register it under, not the directory's. An agent's
        name is the one it gives itself in code (``Agent(name="Billing")``), the same
        kind of identifier as a directory name. Its tools' names are not sent, for the
        same reason a ``tool`` site's are not: they stay on this machine, and only the
        connected-repo scan, which reads the code server-side, records them.

        ``tool_names`` is for a payload that does not leave this machine: `agentfox up`
        recording the scan in a local database (`wizard/backend.Local`). There each
        agent's own tools are added, so its project shows them before any traffic.
        """

        def top_dir(rel_path: str) -> str:
            # The same rule as `AgentSpec.top_dir`: a file at the top level is "root",
            # so a site there groups with the agent defined there, not under its own
            # file name as a second agent.
            parts = Path(rel_path).parts
            return parts[0] if len(parts) > 1 else "root"

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
            "agents": [
                {
                    "key": a.key,
                    "name": a.name,
                    "framework": a.framework,
                    "kind": a.kind,
                    "top_dir": a.top_dir,
                    **({"tools": list(a.tools)} if tool_names else {}),
                }
                for a in self.agents
            ],
            "agent_edges": [e.to_json() for e in self.agent_edges] if self.multi_agent else [],
        }

    def next_step(self, suggest_auto: bool = True) -> str:
        """One sentence telling the operator what to do next.

        A report that ends without a next action makes the reader do the synthesis,
        and most readers will not. ``suggest_auto=False`` leaves out the advice to add
        ``agentfox.auto()``, for a caller that offers a command doing it instead.
        """
        if self.trifectas and not self.inconclusive:
            places = (
                "1 place in this repository can be steered by an instruction hidden in "
                "content it reads"
                if len(self.trifectas) == 1
                else f"{len(self.trifectas)} places in this repository can be steered by an "
                "instruction hidden in content they read"
            )
            first = (
                f"{places} into sending private data out. Contain "
                + ("it" if len(self.trifectas) == 1 else "those")
                + " first — each lethal-trifecta finding names the command."
            )
            if not suggest_auto:
                return first
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
        if self.inconclusive and not self.skipped_suffixes:
            # Nothing here at all: an empty folder, not a repository in a language the
            # scan cannot read. Said plainly instead of "Seen and skipped: no other
            # files were present" under a claim to say nothing about this repository.
            return (
                "There are no files here to scan. Run `agentfox scan <path>` on the "
                "repository that holds your agent."
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
        if not self.governable and self.agents:
            # Not "no model calls found" under a list of agents: each agent calls a
            # model, the scan just did not see where it is started.
            return (
                f"Found {len(self.agents)} agent(s) but no line that runs one or calls a "
                "model directly — they are started from somewhere this scan does not read "
                "(a server, a notebook, a deployment config such as langgraph.json). "
                "Add `import agentfox; agentfox.auto()` where they start."
                if suggest_auto
                else f"Found {len(self.agents)} agent(s) but no line that runs one or calls "
                "a model directly — they are started from somewhere this scan does not read "
                "(a server, a notebook, a deployment config such as langgraph.json)."
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
                f"No model calls found in {self.code_files_scanned} source "
                f"file{'' if self.code_files_scanned == 1 else 's'}. "
                f"This scan reads {SUPPORTED_LANGUAGES}; anything else in the repository "
                "was not examined. If this repo calls a model through a wrapper we don't "
                "recognise, govern it explicitly with the SDK."
            )
        n = len(self.ungoverned)
        ungoverned = "1 model call is ungoverned." if n == 1 else f"{n} model calls are ungoverned."
        if self.ungoverned and not suggest_auto:
            return ungoverned
        if self.ungoverned:
            return (
                f"{ungoverned} Add "
                "`import agentfox; agentfox.auto()` to your entry point — nothing else "
                "in the codebase has to change."
            )
        return "Every model call is governed. Run `agentfox doctor` to check the runtime config."


def _name_unnamed_root_agents(specs: list[AgentSpec], root: Path) -> None:
    """An agent the code gives no name, in a top-level file called main.py, app.py and
    the like, is named after the repository rather than "main": the name the scan,
    `agentfox init` and `agentfox up` all use for it."""
    from agentfox.capabilities.discovery.agents import _GENERIC_STEMS

    repo = root.resolve().name
    for spec in specs:
        path = Path(spec.file)
        if repo and len(path.parts) == 1 and path.stem in _GENERIC_STEMS and spec.name == path.stem:
            spec.name = repo


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


def _arg_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """A function's argument names, `self` and `cls` left out."""
    a = fn.args
    names = [x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
    return [n for n in names if n not in ("self", "cls")]


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
        #: Names this file imports, and each function's docstring: read up front, for
        #: tools made by a call (`function_tool(fn)`) wherever the call sits.
        self._imported: set[str] = set()
        #: Top-level packages this file imports from (`crewai`, `langgraph`).
        self._packages: set[str] = set()
        self._docs: dict[str, str] = {}
        #: What a name assigned in this file holds, when it is one of the runnables
        #: that make `.invoke()` a model call: "chat_model", "graph", "builder", "crew".
        #: Scope-blind on purpose: `model = ...bind_tools(...)` inside a function and
        #: `await model.ainvoke(...)` beside it is the shape, and a name reused for
        #: something else in the same file is rare enough not to design for.
        self._holds: dict[str, str] = {}
        #: Module-level functions, with their line and docstring, for tools an agent
        #: is handed as plain functions (`TOOLS = [search]`).
        self.functions: dict[str, tuple[int, str, list[str]]] = {}
        #: `x.run(...)`-shaped calls: (receiver, method, line, label, receiver imported).
        #: A model call when the agent pass finds an agent held in `x` (decided after
        #: every file is read).
        self.runs: list[tuple[str, str, int, str, bool]] = []
        #: Each function's argument names, for a tool that takes a path (`classify_tool`).
        self._args: dict[str, list[str]] = {}

    def visit_Module(self, node: ast.Module) -> None:
        assigns: list[tuple[str, ast.AST]] = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import | ast.ImportFrom):
                for alias in sub.names:
                    self._imported.add(alias.asname or alias.name.split(".")[0])
                modules = [a.name for a in sub.names] if isinstance(sub, ast.Import) else []
                if isinstance(sub, ast.ImportFrom) and sub.module and not sub.level:
                    modules.append(sub.module)
                self._packages |= {m.split(".")[0] for m in modules}
            elif isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                self._docs.setdefault(sub.name, ast.get_docstring(sub) or "")
                self._args.setdefault(sub.name, _arg_names(sub))
            elif isinstance(sub, ast.Assign):
                assigns += [(_attribute_path(t), sub.value) for t in sub.targets]
            elif isinstance(sub, ast.AnnAssign | ast.NamedExpr) and sub.value is not None:
                assigns.append((_attribute_path(sub.target), sub.value))
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                self.functions.setdefault(
                    stmt.name, (stmt.lineno, ast.get_docstring(stmt) or "", _arg_names(stmt))
                )
        # Twice, so `graph = builder.compile()` after `builder = StateGraph(...)` and an
        # alias of an alias both resolve whatever order the assignments come in.
        for _ in range(2):
            for name, value in assigns:
                held = self._holding(value)
                if name and held:
                    self._holds[name] = held
        self.generic_visit(node)

    def _holding(self, expr: ast.AST) -> str | None:
        """What an expression evaluates to, when it is a chat model, a runnable graph,
        a graph builder or a crew; None for anything else."""
        if isinstance(expr, ast.Await):
            expr = expr.value
        if isinstance(expr, ast.Name | ast.Attribute):
            return self._holds.get(_attribute_path(expr))
        calls = _chain(expr)
        if not calls:
            return None
        names = [_last(c) for c in calls]
        if any(n in _CHAT_MODEL_CALLS or _CHAT_MODEL_CLASS.match(n) for n in names):
            return "chat_model"
        if names[0] == "compile":
            receiver = calls[0].func.value if isinstance(calls[0].func, ast.Attribute) else None
            built = self._holding(receiver) if receiver is not None else None
            if built == "builder" or any(n in _GRAPH_BUILDERS for n in names[1:]):
                return "graph"
            return None
        if names[0] in _GRAPH_FACTORIES:
            return "graph"
        if names[0] in _GRAPH_BUILDERS:
            return "builder"
        if names[0] == "Crew" or names[0] == "crew":
            return "crew"
        return None

    def _agent_run(self, node: ast.Call, path: str) -> tuple[str, str] | None:
        """(provider, what) when this call runs an agent or a chat model."""
        if path in _AGENT_RUNS:
            provider, needs = _AGENT_RUNS[path]
            if needs in self._imported:
                return provider, "runs an agent"
            return None
        if not isinstance(node.func, ast.Attribute):
            return None
        method = node.func.attr
        receiver = node.func.value
        if method in _CREW_RUNS and (
            "crewai" in self._packages or self._holding(receiver) == "crew"
        ):
            return "crewai", "runs a crew"
        if method in _RUNNABLE_METHODS:
            held = self._holding(receiver)
            if held == "chat_model":
                return "langchain", ""
            if held == "graph":
                return "langgraph", "runs the graph"
        return None

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
        for prefix, name in _FRAMEWORK_PREFIXES.items():
            if module == prefix or module.startswith(f"{prefix}."):
                label = name
        if label:
            self.frameworks.add(label)
        if root == "agentfox":
            self.governed = True

    def visit_Call(self, node: ast.Call) -> None:
        path = _attribute_path(node.func)
        # `agentfox.auto()` anywhere in a file means its model calls are governed.
        if path.endswith("auto") and "agentfox" in path:
            self.governed = True
        run = self._agent_run(node, path)
        if run is not None:
            provider, what = run
            # The whole receiver chain, so `MyCrew().crew().kickoff` does not read as a
            # bare `kickoff(...)`; its tail when it is long.
            label = ast.unparse(node.func)
            label = label if len(label) <= 60 else "…" + label[-59:]
            self.sites.append(
                Site(
                    kind="model_call",
                    file=self.path,
                    line=node.lineno,
                    detail=f"{label}(...)" + (f" — {what}" if what else ""),
                    provider=provider,
                    # A run site is where an agent starts, not a risk of its own: it is
                    # counted as a model call (ungoverned until auto() covers it) and
                    # listed for information. A direct client call stays high.
                    severity="info" if what else "high",
                )
            )
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _AGENT_METHODS
            and isinstance(node.func.value, ast.Name | ast.Attribute)
        ):
            receiver = _attribute_path(node.func.value)
            self.runs.append(
                (receiver, node.func.attr, node.lineno, path, receiver in self._imported)
            )
        for suffix, provider in () if run is not None else _MODEL_CALLS.items():
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
        self._check_wrapped_tool(node)
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
                            severity="info",
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
                explicit = description = None
                if isinstance(decorator, ast.Call):
                    if decorator.args:
                        explicit = _str_value(decorator.args[0])
                    # `@function_tool(name_override="x", description_override="...")`
                    for kw in decorator.keywords:
                        if kw.arg in ("name_override", "name") and not explicit:
                            explicit = _str_value(kw.value)
                        elif kw.arg in ("description_override", "description"):
                            description = _str_value(kw.value)
                self._add_tool(
                    explicit or node.name,
                    description or ast.get_docstring(node) or "",
                    node.lineno,
                    f"@{name} {node.name}()",
                    _arg_names(node),
                )
                break

    def _check_wrapped_tool(self, node: ast.Call) -> None:
        """`lookup = function_tool(fetch)`, `function_tool(name_override="x")(fetch)`,
        `tool(fetch)`, `StructuredTool.from_function(fetch)`: a tool made by a call,
        named as the code names it (else by its function) and described by that
        function's docstring when this file defines it."""
        made = wrapped_tool(node, self._imported)
        if made is None:
            return
        name, fn = made
        description = None
        opts = node.func if isinstance(node.func, ast.Call) else node
        for kw in opts.keywords:
            if kw.arg in ("description_override", "description"):
                description = _str_value(kw.value)
        self._add_tool(
            name,
            description or self._docs.get(fn or "", ""),
            node.lineno,
            f"{_attribute_path(opts.func)}({fn or name})",
            self._args.get(fn or ""),
        )

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

    def _add_tool(
        self, name: str, description: str, line: int, how: str, args: list[str] | None = None
    ) -> None:
        # The same schema appears twice in one file often enough (a list built twice,
        # a retry path) that counting it twice would inflate the headline.
        if name in self._tool_names:
            return
        self._tool_names.add(name)
        from agentfox.capabilities.discovery.exposure import FLAG_LABEL, classify_tool

        caps = classify_tool(name, description, args or ())
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
    "@openai/agents": "OpenAI Agents SDK",
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
    "@openai/agents-realtime": "OpenAI Realtime",
    "@openai/agents/realtime": "OpenAI Realtime",
    "@anthropic-ai/claude-agent-sdk": "Claude Agent SDK",
    "@mastra": "Mastra",
    "@voltagent": "VoltAgent",
    "@strands-agents": "Strands Agents",
    "@aws-sdk/client-bedrock-agent-runtime": "Bedrock Agents",
    "@aws-sdk/client-bedrock-agentcore": "Bedrock AgentCore",
    "@aws-sdk/client-lex-runtime-v2": "Amazon Lex",
    "@aws-sdk/client-connect": "Amazon Connect",
    "@google-cloud/dialogflow-cx": "Dialogflow CX",
    "@google-cloud/dialogflow": "Dialogflow",
    "@n8n": "n8n",
    "n8n-workflow": "n8n",
    # Voice agents (see the Python map).
    "@livekit/agents": "LiveKit Agents",
    "@pipecat-ai": "Pipecat",
    "@vapi-ai": "Vapi",
    "retell-sdk": "Retell",
    "retell-client-js-sdk": "Retell",
    "@elevenlabs": "ElevenLabs",
    "@11labs": "ElevenLabs",
    "elevenlabs": "ElevenLabs",
    "telnyx": "Telnyx",
    "twilio": "Twilio",
    "agora-rtc-sdk-ng": "Agora",
    "agora-agent-uikit": "Agora",
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


#: `import { Agent, run } from "@openai/agents"`, and the call it makes possible.
_JS_RUN_IMPORT = re.compile(
    r"""import\s*\{[^}]*(?<![\w$])run(?![\w$])[^}]*\}\s*from\s*["']@openai/agents["']"""
)
_JS_AGENT_RUN = re.compile(r"(?<![\w$.])run\s*\(\s*[\w$]")


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
    # `run` only means the Agents SDK's runner when the file imported it by that name.
    agents_run = bool(_JS_RUN_IMPORT.search(source))
    for line_no, line in enumerate(lines, start=1):
        if _JS_COMMENT_LINE.match(line):
            continue
        code = code_lines[line_no - 1] if line_no <= len(code_lines) else line
        # One site per line, most specific pattern first, so `.chat.completions.create`
        # is not also counted by `.completions.create`. Matched against `code`, so a
        # call shown inside a string or a comment is not counted as one.
        runs = _JS_AGENT_RUN.search(code) if agents_run else None
        if runs:
            # The Agents SDK's `run(agent, input)`: runs the agent, so calls its model.
            sites.append(
                Site(
                    kind="model_call",
                    file=rel,
                    line=line_no,
                    detail=f"{runs.group(0).strip()} — runs an agent",
                    provider="openai-agents",
                    severity="info",
                )
            )
        for pattern, provider, required in () if runs else _JS_MODEL_CALLS:
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
                        severity="info",
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
                    from agentfox.capabilities.discovery.exposure import FLAG_LABEL, classify_tool

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


def scan_file(
    path: Path,
    root: Path,
    *,
    functions: dict[str, tuple[int, str, list[str]]] | None = None,
    runs: list[tuple[str, str, int, str, bool]] | None = None,
) -> tuple[list[Site], set[str], bool]:
    """The sites in one file. ``functions``, when given, is filled with the file's
    module-level functions (name -> line, docstring), for tools handed to an agent as
    plain functions."""
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
        if functions is not None:
            functions.update(visitor.functions)
        if runs is not None:
            runs.extend(visitor.runs)
    elif path.suffix in JS_SUFFIXES:
        js_sites, js_frameworks = _scan_javascript(source, rel)
        sites.extend(js_sites)
        frameworks |= js_frameworks

    for line_no, line in enumerate(source.splitlines(), start=1):
        sql = _SQL_BUILD.search(line)
        if sql and _sql_is_built(line, sql):
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
            sites.append(_secret_site(rel, line_no))
    return sites, frameworks, governed


def _secret_site(rel: str, line_no: int) -> Site:
    return Site(
        kind="secret",
        file=rel,
        line=line_no,
        # Never echo the match: a scan report that reprints the key it found is a
        # second copy of the leak.
        detail="hard-coded credential in source",
        severity="critical",
    )


def _secrets_in(path: Path, rel: str) -> list[Site]:
    """Only the hard-coded secrets in a file the scan otherwise leaves out."""
    try:
        source = path.read_text(errors="ignore")
    except OSError:  # pragma: no cover - unreadable file
        return []
    return [
        _secret_site(rel, n)
        for n, line in enumerate(source.splitlines(), start=1)
        if _HARDCODED_SECRET.search(line)
    ]


#: Directories of code that is about the product rather than part of it: docs and
#: their build scripts, benchmarks, integration and end-to-end suites. Left out of a
#: scan by default with tests, mocks and fixtures (:func:`is_test_path`).
_NON_PRODUCT_DIRS = {
    "docs",
    "doc",
    "documentation",
    "bench",
    "benchmark",
    "benchmarks",
    "integration_tests",
    "integration-tests",
    "e2e",
}


def is_excluded_path(rel: str) -> bool:
    """True for a file a default scan does not report on: a test, mock or fixture, or
    anything under a docs, benchmark or integration-test directory."""
    parts = Path(rel).parts
    return is_test_path(rel) or any(p.lower() in _NON_PRODUCT_DIRS for p in parts[:-1])


def _add_agent_tools(
    report: ScanReport, functions: dict[str, dict[str, tuple[int, str, list[str]]]]
) -> None:
    """A `tool` site for each tool an agent is handed that no decorator or constructor
    declared: a plain function in a list (`TOOLS = [search]`, then `ToolNode(TOOLS)` and
    `.bind_tools(TOOLS)`), which LangGraph and others accept as-is.

    Without this the agent line read "ReAct Agent · 1 tool" and the line under it "can
    reach: 0 tools", and `agentfox up` declared nothing for the agent to be granted. The
    function is found where it is defined, nearest the agent first; a name no file
    defines as a function gets no site, since the static read cannot say what it is.
    """
    from agentfox.capabilities.discovery.exposure import FLAG_LABEL, classify_tool

    have = {(s.name, s.file) for s in report.tools}
    named = {s.name for s in report.tools}
    defined: dict[str, list[tuple[str, int, str, list[str]]]] = defaultdict(list)
    for file, funcs in functions.items():
        for name, (line, doc, args) in funcs.items():
            defined[name].append((file, line, doc, args))
    for agent in report.agents:
        for name in agent.tools:
            if name in named or name not in defined:
                continue
            here = Path(agent.file).parent
            file, line, doc, args = max(
                defined[name], key=lambda d: (d[0] == agent.file, _shared(Path(d[0]).parent, here))
            )
            if (name, file) in have:
                continue
            have.add((name, file))
            details = {d["name"]: d for d in agent.tool_details}
            doc = str(details.get(name, {}).get("description") or doc)
            caps = classify_tool(name, doc, args)
            flags = caps.ordered()
            what = "; ".join(caps.phrases.get(f, FLAG_LABEL[f]) for f in flags)
            report.sites.append(
                Site(
                    kind="tool",
                    file=file,
                    line=line,
                    detail=f"tool {name}() handed to {agent.name}" + (f" — {what}" if what else ""),
                    severity="medium",
                    name=name,
                    capabilities=flags,
                    caps=caps,
                )
            )


def _promote_agent_runs(
    report: ScanReport, runs: dict[str, list[tuple[str, str, int, str, bool]]]
) -> None:
    """A model call for each `x.run(...)`-shaped call on a variable an agent is held in.

    Framework-agnostic by construction: the agent pass already knows which variables
    hold an agent (in any framework it reads), so `support_agent.run_sync(...)` and
    `team.run(...)` count without a per-framework list of run methods. The variable is
    matched in its own file first, then, when the file imported the name, against the
    one agent anywhere held under it.
    """
    local: dict[tuple[str, str], AgentSpec] = {}
    anywhere: dict[str, list[AgentSpec]] = defaultdict(list)
    for agent in report.agents:
        for name in {agent.var, agent.attr} - {None}:
            local.setdefault((agent.file, str(name)), agent)
            anywhere[str(name)].append(agent)
    counted = {(s.file, s.line) for s in report.model_calls}
    governed = set(report.governed_files)
    for file, calls in runs.items():
        for receiver, _method, line, label, imported in calls:
            if (file, line) in counted:
                continue
            agent = local.get((file, receiver))
            if agent is None and imported and len(anywhere.get(receiver, [])) == 1:
                agent = anywhere[receiver][0]
            if agent is None:
                continue
            counted.add((file, line))
            report.sites.append(
                Site(
                    kind="model_call",
                    file=file,
                    line=line,
                    detail=f"{label}(...) — runs {agent.name}",
                    provider=re.sub(r"[^a-z0-9]+", "-", agent.framework.lower()).strip("-"),
                    severity="info",
                    governed=file in governed,
                )
            )


def _shared(a: Path, b: Path) -> int:
    """How many leading path components two directories share."""
    n = 0
    for x, y in zip(a.parts, b.parts, strict=False):
        if x != y:
            break
        n += 1
    return n


#: A code file this large is generated or minified (a bundle, a vendored build), not
#: code anyone wrote an agent in; reading it costs more than every other file.
MAX_CODE_BYTES = 1_000_000


def _git_files(root: Path) -> tuple[set[str], set[str]] | None:
    """The files git would show here (tracked, plus untracked ones not ignored) and
    their directories; None when the root is not a git work tree. What `.gitignore`
    leaves out (build output, generated code, data) is not the repository's code."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True,
            timeout=60,
            check=True,
        ).stdout.decode(errors="ignore")
    except (OSError, subprocess.SubprocessError):
        return None
    files = {f for f in out.split("\0") if f}
    if not files:
        return None
    dirs = {str(Path(f).parent) for f in files}
    dirs |= {str(p) for d in list(dirs) for p in Path(d).parents}
    return files, dirs


def scan(
    root: str | Path = ".",
    *,
    include_config: bool = True,
    llm_apps: bool = False,
    include_tests: bool = False,
) -> ScanReport:
    """Walk a repository and report every surface worth governing.

    ``llm_apps``: with no agent structure found, report each package that calls a
    model as a low-confidence "LLM app" agent. `agentfox init` asks for it so it can
    say what it saw; discovery submissions do not, so a scan never proposes a draft
    agent on model calls alone.

    ``include_tests``: also report the model calls, tools and agent definitions in
    tests, docs and benchmarks (:func:`is_excluded_path`). Off by default: in a
    framework's own repository they are most of the code (LangGraph's root read as
    2,031 agent definitions and 76 tools, nearly all from tests), and none of it is
    an agent anyone deploys. Hard-coded secrets are reported there either way."""
    root_path = Path(root).resolve()
    report = ScanReport(root=str(root_path))
    frameworks: set[str] = set()
    agents = AgentCollector()

    suffixes = set(CODE_SUFFIXES)
    if include_config:
        suffixes |= CONFIG_SUFFIXES
    report.code_files_scanned = 0
    git = _git_files(root_path)
    #: Files that may hold a hosted platform's agent definition (`discovery/platforms`).
    platform_files: list[Path] = []
    #: file -> its module-level functions, for tools handed over as plain functions.
    functions: dict[str, dict[str, tuple[int, str, list[str]]]] = defaultdict(dict)
    #: file -> its `x.run(...)`-shaped calls, for `_promote_agent_runs`.
    runs: dict[str, list[tuple[str, str, int, str, bool]]] = defaultdict(list)
    agents.include_tests = include_tests

    for dirpath, dirnames, filenames in os.walk(root_path):
        rel_dir = os.path.relpath(dirpath, root_path)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS
            and not d.startswith(".")
            and (git is None or os.path.normpath(os.path.join(rel_dir, d)) in git[1])
        ]
        for filename in filenames:
            path = Path(dirpath) / filename
            if git is not None and os.path.normpath(os.path.join(rel_dir, filename)) not in git[0]:
                continue
            if (
                include_config
                and platforms.is_candidate(path)
                and not is_test_path(os.path.join(rel_dir, filename))
            ):
                platform_files.append(path)
            if path.suffix in CODE_SUFFIXES and path.stat().st_size > MAX_CODE_BYTES:
                report.skipped_suffixes["(generated or minified)"] = (
                    report.skipped_suffixes.get("(generated or minified)", 0) + 1
                )
                continue
            if path.suffix not in suffixes:
                # Recorded, not discarded: "we read nothing here" is the finding that
                # matters when the answer comes back empty, and it cannot be recovered
                # later from a count of files that were read.
                suffix = path.suffix.lower() or "(no extension)"
                report.skipped_suffixes[suffix] = report.skipped_suffixes.get(suffix, 0) + 1
                continue
            rel = os.path.normpath(os.path.join(rel_dir, filename))
            if not include_tests and is_excluded_path(rel):
                # Read for secrets only: a key committed in a test is still committed.
                report.excluded_files += 1
                report.sites.extend(_secrets_in(path, rel))
                continue
            report.files_scanned += 1
            if path.suffix in CODE_SUFFIXES:
                report.code_files_scanned += 1
            try:
                sites, found, governed = scan_file(
                    path, root_path, functions=functions[rel], runs=runs[rel]
                )
            except RuntimeError as exc:
                report.errors.append(str(exc))
                continue
            frameworks |= found
            if path.suffix in CODE_SUFFIXES:
                source = path.read_text(errors="ignore")
                agents.add(source, str(path.relative_to(root_path)), path.suffix)
                frameworks |= platforms.detect_code_platforms(source)
            if governed:
                report.governed_files.append(str(path.relative_to(root_path)))
            for site in sites:
                if site.kind in ("model_call", "agent_definition") and governed:
                    site.governed = True
                    site.severity = "info"
                report.sites.append(site)

    report.agents, report.agent_edges = agents.finish()
    _name_unnamed_root_agents(report.agents, root_path)
    hosted = platforms.detect(platform_files, root_path)
    frameworks |= hosted.platforms
    hosted_agents, hosted_edges = _platform_agents(hosted, {a.key for a in report.agents})
    report.agents.extend(hosted_agents)
    report.agent_edges.extend(hosted_edges)
    if not report.agents and llm_apps:
        report.agents = _llm_apps(report)
    _add_agent_tools(report, functions)
    _promote_agent_runs(report, runs)
    given = {name for a in report.agents for name in a.tools}
    report.unassigned_tools = sorted(
        {
            s.name
            for s in report.tools
            if s.name and s.name not in given and not is_test_path(s.file)
        }
    )
    # The OpenAI Agents SDK imports as `agents`, a name too common among a repository's
    # own packages to detect from the import alone; an agent built with it is proof.
    frameworks |= {a.framework for a in report.agents}
    if "LiveKit Agents" in frameworks:
        frameworks.discard("LiveKit")  # `from livekit import agents` beside it
    report.frameworks = sorted(frameworks)
    _detect_mcp(root_path, report)
    _detect_trifectas(report)
    return report


def _platform_agents(
    hosted: platforms.Result, taken: set[str]
) -> tuple[list[AgentSpec], list[AgentEdge]]:
    """Agents a hosted platform's definition files describe, as :class:`AgentSpec`
    entries beside the ones the code defines, with keys unique among both; and each
    team's ``member`` edges (a Vapi squad runs its assistants)."""
    out = []
    keys: dict[tuple[str, str], str] = {}
    for found in hosted.agents:
        key = agent_key(found.name, found.file, taken)
        taken.add(key)
        keys.setdefault((found.file, found.name), key)
        out.append(
            AgentSpec(
                key=key,
                name=found.name,
                framework=found.platform,
                kind=found.kind,
                file=found.file,
                line=found.line,
                tools=found.tools,
                model=found.model,
                named=found.named,
                confidence=found.confidence,
                evidence=found.evidence,
            )
        )
    edges = [
        AgentEdge(keys[(found.file, found.name)], keys[(found.file, member)], "member")
        for found in hosted.agents
        for member in found.members
        if (found.file, member) in keys
    ]
    return out, edges


#: Directories that hold packages rather than being one: an app is named by the
#: directory under them.
_CONTAINER_DIRS = {"src", "apps", "packages", "libs", "lib", "services", "backend", "frontend"}


def _llm_apps(report: ScanReport) -> list[AgentSpec]:
    """When no agent structure is found but the code calls a model: one low-confidence
    "LLM app" per package that calls one, with the tools defined in that package as
    its possible tools. Init then says what it saw instead of "no agents"."""
    calls = [s for s in report.model_calls if not is_test_path(s.file)]
    if not calls:
        return []

    def package(rel: str) -> str:
        parts = Path(rel).parts[:-1]
        while parts and parts[0] in _CONTAINER_DIRS:
            parts = parts[1:]
        return parts[0] if parts else Path(rel).stem

    groups: dict[str, list[Site]] = {}
    for site in calls:
        groups.setdefault(package(site.file), []).append(site)
    tools: dict[str, list[str]] = {}
    for site in report.tools:
        if site.name and not is_test_path(site.file):
            tools.setdefault(package(site.file), []).append(site.name)
    out = []
    for name, sites in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]:
        first = min(sites, key=lambda s: (s.file, s.line))
        provider = next((s.provider for s in sites if s.provider), None)
        out.append(
            AgentSpec(
                key=re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "llm-app",
                name=name,
                framework=f"{provider} calls" if provider else "LLM calls",
                kind="agent",
                file=first.file,
                line=first.line,
                tools=sorted(set(tools.get(name, []))),
                named=False,
                confidence="low",
                evidence=f"{len(sites)} model call(s), no agent structure found",
            )
        )
    return out


def _detect_mcp(root: Path, report: ScanReport) -> None:
    """MCP servers are declared in config, not code, so they need their own pass.

    Reads every MCP client config under the root (`exposure.KNOWN_MCP_CONFIGS`) and
    never starts a server: what a server can do is classified from how it is declared.
    """
    from agentfox.capabilities.discovery.exposure import (
        FLAG_LABEL,
        classify_mcp_server,
        is_mcp_config,
        parse_mcp_config,
    )

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            if not is_mcp_config(path):
                continue
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

    * **Tools an agent is handed are grouped by agent system.** One model reads
      everything its tools return, and agents joined by a handoff, a delegation or a
      crew share what they read; so each connected set of agents (the agent graph's
      components) is one group, holding every tool any of them is handed. Two scripts
      side by side in `examples/basic/`, each with its own agent, are two groups:
      grouping by directory once joined one script's `fetch_random_image` with
      another's `send_email` into an "agent" nobody wrote.
    * **Tools no agent is known to hold are grouped by directory**, the closest static
      stand-in for "one agent" when the agent pass found none: tools declared in
      `tools.py` are handed to the model in `agent.py` next to it far more often than
      across packages. A file that defines an agent of its own is a script, though,
      and its leftover tools stay in a group of their own. A group whose tools all sit
      in one file is labelled with that file; otherwise with the directory.
    * **MCP servers are grouped by the config file that declares them.** Every
      server in one `.mcp.json` is loaded into the same client session, so they
      share one model — that is exactly the condition the trifecta needs. They are
      not merged with code tools in the same directory, because an MCP config
      configures an IDE or assistant, not necessarily the application beside it.
    """
    from agentfox.capabilities.discovery.exposure import Member, containment_hint, trifecta_sentence

    tools = [s for s in report.tools if s.caps is not None and s.name]
    by_name: dict[str, list[Site]] = defaultdict(list)
    for site in tools:
        by_name[site.name or ""].append(site)

    # Each agent's own tool sites: the definition nearest the agent when two files
    # define a tool by the same name.
    held: dict[str, list[Site]] = {}
    for agent in report.agents:
        here = Path(agent.file).parent
        mine: list[Site] = []
        for name in agent.tools:
            if by_name.get(name):
                mine.append(
                    max(
                        by_name[name],
                        key=lambda s: (s.file == agent.file, _shared(Path(s.file).parent, here)),
                    )
                )
        held[agent.key] = mine
    claimed = {id(s) for sites in held.values() for s in sites}

    # Connected agent systems, by the edges between agents.
    parent = {a.key: a.key for a in report.agents}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for edge in report.agent_edges:
        if edge.parent in parent and edge.child in parent:
            parent[find(edge.parent)] = find(edge.child)
    systems: dict[str, list[AgentSpec]] = defaultdict(list)
    for agent in report.agents:
        systems[find(agent.key)].append(agent)

    #: (label, file, sites, agents, mcp)
    groups: list[tuple[str, str, list[Site], list[AgentSpec], bool]] = []
    for members in systems.values():
        sites = list({id(s): s for a in members for s in held[a.key]}.values())
        if not sites:
            continue
        lead = members[0]
        names = ", ".join(a.name for a in members[:3]) + (", …" if len(members) > 3 else "")
        if len(members) > 1:
            label = f"{names} ({lead.file})"
        elif lead.named:
            label = f"{lead.name} ({lead.file})"
        else:
            label = lead.file  # an agent the code never named is its file
        groups.append((label, lead.file, sites, members, False))

    agent_files = {a.file for a in report.agents}
    loose: dict[str, list[Site]] = defaultdict(list)
    for site in tools:
        if id(site) in claimed:
            continue
        key = site.file if site.file in agent_files else str(Path(site.file).parent)
        loose[key].append(site)
    for key, sites in sorted(loose.items()):
        files = sorted({s.file for s in sites})
        if len(files) == 1:
            label = files[0]
        else:
            label = "./" if key == "." else f"{key}/"
        groups.append((label, label, sites, [], False))

    servers: dict[str, list[Site]] = defaultdict(list)
    for site in report.mcp_servers:
        if site.caps is not None and site.name:
            servers[site.file].append(site)
    for config, sites in sorted(servers.items()):
        groups.append((config, config, sites, [], True))

    found: list[Site] = []
    for label, file, sites, agents, mcp in groups:
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
                file=file,
                line=first.line,
                detail=sentence,
                provider="mcp" if mcp else None,
                severity="critical",
                capabilities=["private_data", "untrusted_input", "exfiltration"],
                evidence={
                    **evidence,
                    "fix": containment_hint(
                        evidence, mcp=mcp, agent=_agent_slug(report, agents, evidence)
                    ),
                },
            )
        )
    # First in the list as well as first in severity: this is the finding.
    report.sites[:0] = found


def _agent_slug(
    report: ScanReport, agents: list[AgentSpec], evidence: dict[str, list[str]]
) -> str | None:
    """The slug `agentfox up` registers the agent holding a trifecta's way out under:
    the repository's name for a repository with one agent, else the agent's own name.
    None when the group is not an agent the scan found."""
    if not agents:
        return None
    channel = (evidence.get("exfiltration") or [""])[0]
    holder = next((a for a in agents if channel in a.tools), agents[0])
    if len(report.agents) == 1:
        name = Path(report.root).name
    else:
        name = holder.name
    return re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-") or None
