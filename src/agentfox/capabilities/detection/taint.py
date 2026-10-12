"""Taint tracking — provenance of content through an execution path.

This is the piece of runtime engineering with no equivalent in any OSS project
surveyed, and it is the reason the product can claim *agent-native*
rather than model-era filtering.

The idea: a model-era guardrail asks "is this string malicious?". The agent-native
question is "**should this action happen, given where its arguments came from?**"
Content entering the agent from an untrusted source (a retrieved document, a tool
result, a sub-agent's output, persisted memory) is tagged. The tag propagates into
tool-call arguments. Policy can then require that a high-impact tool never receives
a tainted argument without human approval — which holds even when the injection
detector missed the payload entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentfox.core.vocab import taint_rank

#: Values shorter than this are ignored when inferring provenance — matching on
#: "1" or "ok" would taint everything and make the signal useless.
MIN_INFERENCE_LENGTH = 6

_NORMALISE = re.compile(r"\s+")


def _norm(value: str) -> str:
    return _NORMALISE.sub(" ", value).strip().lower()


@dataclass(slots=True)
class TaintMark:
    path: str
    source: str
    trust: str = "untrusted"
    propagated_from: str | None = None


@dataclass
class TaintTracker:
    """Per-trace provenance ledger."""

    trace_id: str | None = None
    marks: list[TaintMark] = field(default_factory=list)
    #: normalised content -> source, for inference
    _content: list[tuple[str, str, str]] = field(default_factory=list)
    #: Registered keys of tools whose output an operator declared trusted
    #: (`Tool.output_trust`). Content marked under such a tool's path stays in the
    #: ledger — the record of what the agent read is not rewritten — but it neither
    #: taints an argument copied out of it nor raises the run's high-water mark.
    #: Refreshed from the registry by `Enforcer.guard_tool_call` on every call.
    trusted_tools: frozenset[str] = field(default_factory=frozenset)

    def _trusted(self, path: str | None) -> bool:
        if not self.trusted_tools or not path:
            return False
        from agentfox.capabilities.detection.composition import tool_key_from_origin

        return tool_key_from_origin(path) in self.trusted_tools

    # -- marking ---------------------------------------------------------
    def mark(self, path: str, source: str, content: str | None = None) -> TaintMark:
        trust = "trusted" if source in ("none", "system") else "untrusted"
        mark = TaintMark(path=path, source=source, trust=trust)
        self.marks.append(mark)
        if content and taint_rank(source) >= 1:
            self._content.append((_norm(content), source, path))
        return mark

    def mark_messages(
        self, messages: list[dict[str, Any]], declared: dict[str, str] | None = None
    ) -> list[str]:
        """Tag a chat message array, in OpenAI's shape or Anthropic's. Returns the
        names of the tools already called in it, in order.

        ``declared`` is the caller's ``X-AgentFox-Trust`` map (index -> source), and
        covers everything in that message. Anything not declared is inferred: see
        `message_segments`.
        """
        for segment in message_segments(messages, declared):
            self.mark(segment.path, segment.source, segment.text)
        return tools_called(messages)

    # -- querying --------------------------------------------------------
    def max_source(self) -> str:
        sources = [m.source for m in self.marks if not self._trusted(m.path)]
        if not sources:
            return "none"
        return max(sources, key=taint_rank)

    def infer_source(self, value: Any) -> tuple[str, str | None]:
        """Infer the provenance of a value by matching it against tainted content.

        Returns ``(source, propagated_from_path)``. This is what makes taint work
        without asking the customer to instrument every argument by hand — the
        agent copied the value out of somewhere, and we know where that was.
        """
        text = value if isinstance(value, str) else None
        if text is None or len(text) < MIN_INFERENCE_LENGTH:
            return "none", None
        needle = _norm(text)
        best: tuple[str, str | None] = ("none", None)
        for haystack, source, path in self._content:
            # A value that also appears in untrusted content is still found there:
            # skipping the trusted copy can only ever make the answer stricter.
            if self._trusted(path):
                continue
            if needle and needle in haystack:
                if taint_rank(source) > taint_rank(best[0]):
                    best = (source, path)
        return best

    def taint_arguments(
        self, arguments: dict[str, Any], declared: dict[str, str] | None = None
    ) -> dict[str, TaintMark]:
        """Compute per-argument provenance for a tool call.

        Declared provenance from the caller always wins; anything undeclared is
        inferred. Nested structures are walked so ``{"body": {"to": "..."}}`` is
        covered rather than silently untainted.
        """
        declared = declared or {}
        out: dict[str, TaintMark] = {}

        def walk(node: Any, path: str) -> None:
            if isinstance(node, dict):
                for key, sub in node.items():
                    walk(sub, f"{path}.{key}" if path else key)
                return
            if isinstance(node, list):
                for i, sub in enumerate(node):
                    walk(sub, f"{path}[{i}]")
                return
            top = path.split(".")[0].split("[")[0]
            if path in declared or top in declared:
                source = declared.get(path) or declared[top]
                mark = TaintMark(
                    path=path, source=source, trust="trusted" if source == "none" else "untrusted"
                )
            else:
                source, origin = self.infer_source(node)
                if source == "none":
                    return
                mark = TaintMark(
                    path=path,
                    source=source,
                    trust="untrusted",
                    propagated_from=origin,
                )
            out[path] = mark
            self.marks.append(mark)

        walk(arguments, "")
        return out

    def summary(self) -> dict[str, Any]:
        by_source: dict[str, int] = {}
        for mark in self.marks:
            by_source[mark.source] = by_source.get(mark.source, 0) + 1
        summary: dict[str, Any] = {
            "max_source": self.max_source(),
            "by_source": by_source,
            "untrusted_paths": [
                m.path for m in self.marks if m.trust == "untrusted" and not self._trusted(m.path)
            ][:50],
        }
        trusted = [m.path for m in self.marks if self._trusted(m.path)]
        if trusted:
            # Only present when a declaration changed something, so a summary from a
            # deployment that never declared trust is byte-for-byte what it was.
            summary["trusted_tool_outputs"] = trusted[:50]
        return summary


def _flatten(content: Any) -> str:
    """Multimodal content blocks -> a single searchable string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                inner = block.get("text") or block.get("content") or ""
                # An Anthropic `tool_result` carries its own list of blocks.
                parts.append(_flatten(inner) if isinstance(inner, list) else str(inner))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


#: The provenance a message's role implies when nobody declared one.
ROLE_SOURCE = {
    "system": "none",
    "developer": "none",
    "assistant": "none",
    "user": "user",
    "tool": "tool_result",
    "function": "tool_result",
}


@dataclass(frozen=True, slots=True)
class Segment:
    """One piece of a conversation with a single provenance.

    Usually a whole message. An Anthropic ``user`` message that carries
    ``tool_result`` blocks is split: each result is its own segment, and whatever
    else the message says is one more. ``blocks`` are the indices into the
    message's content list this segment covers, or None for the whole content.
    """

    index: int
    path: str
    source: str
    text: str
    blocks: tuple[int, ...] | None = None


def tools_called(messages: list[Any]) -> list[str]:
    """The tools the conversation has already called, in order."""
    return [name for message in messages for _id, name in _calls_in(message)]


def message_segments(messages: list[Any], declared: dict[str, str] | None = None) -> list[Segment]:
    """Split a chat message array into segments of one provenance each.

    Undeclared provenance follows the role (`ROLE_SOURCE`), with one exception that
    matters: an Anthropic ``tool_result`` block arrives inside a ``role="user"``
    message, but it is a tool's output, and is ``tool_result`` exactly like OpenAI's
    ``role="tool"``. Marked by role, a payee copied out of a tool result read as
    something the person typed. A tool's output is marked ``tool:<tool>#<index>``
    when the call that produced it is in the conversation, so composition checks
    and `Tool.output_trust` can name the producing tool; ``$.messages[i].content``
    (or ``…content[j]`` for one of several blocks) otherwise.
    """
    declared = declared or {}
    produced_by: dict[str, str] = {}
    out: list[Segment] = []

    def tool_path(i: int, name: Any, fallback: str) -> str:
        return f"tool:{name}#{i}" if name else fallback

    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        for call_id, name in _calls_in(message):
            if call_id:
                produced_by[call_id] = name
        role = str(message.get("role") or "user")
        content = message.get("content")
        path = f"$.messages[{i}].content"
        source = declared.get(str(i))
        if role in ("tool", "function"):
            name = produced_by.get(str(message.get("tool_call_id"))) or message.get("name")
            out.append(
                Segment(i, tool_path(i, name, path), source or "tool_result", _flatten(content))
            )
            continue
        results = (
            [j for j, b in enumerate(content) if _is_tool_result(b)]
            if isinstance(content, list)
            else []
        )
        if not results:
            text = content if isinstance(content, str) else _flatten(content)
            out.append(Segment(i, path, source or ROLE_SOURCE.get(role, "user"), text))
            continue
        for j in results:
            block = content[j]
            name = produced_by.get(str(block.get("tool_use_id")))
            out.append(
                Segment(
                    i,
                    tool_path(i, name, f"{path}[{j}]"),
                    source or "tool_result",
                    _flatten([block]),
                    (j,),
                )
            )
        rest = tuple(j for j in range(len(content)) if j not in results)
        if rest:
            text = _flatten([content[j] for j in rest])
            out.append(Segment(i, path, source or ROLE_SOURCE.get(role, "user"), text, rest))
    return out


def _is_tool_result(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "tool_result"


def _calls_in(message: Any) -> list[tuple[str | None, str]]:
    """``(call id, tool name)`` for each tool call one message carries: OpenAI
    ``tool_calls`` (and the legacy ``function_call``), LangChain's
    ``{"name", "args", "id"}`` and Anthropic ``tool_use`` blocks."""
    if not isinstance(message, dict):
        return []
    calls: list[tuple[str | None, str]] = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else call
        if function.get("name"):
            calls.append((str(call["id"]) if call.get("id") else None, str(function["name"])))
    legacy = message.get("function_call")
    if isinstance(legacy, dict) and legacy.get("name"):
        calls.append((None, str(legacy["name"])))
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name"):
                calls.append((str(block["id"]) if block.get("id") else None, str(block["name"])))
    return calls


def exceeds(actual: str, allowed: str) -> bool:
    """True when ``actual`` provenance is more dangerous than ``allowed``."""
    return taint_rank(actual) > taint_rank(allowed)


__all__ = [
    "ROLE_SOURCE",
    "Segment",
    "TaintMark",
    "TaintTracker",
    "_flatten",
    "exceeds",
    "message_segments",
    "tools_called",
]
