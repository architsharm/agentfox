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
    ) -> None:
        """Tag a chat message array.

        ``declared`` is the caller's ``X-Nometria-Trust`` map (index -> source).
        Anything not declared is inferred from role: ``system`` is trusted, ``user``
        is user-tainted, ``tool`` output is tool_result-tainted.
        """
        declared = declared or {}
        for i, message in enumerate(messages):
            role = str(message.get("role", "user"))
            source = declared.get(str(i)) or {
                "system": "none",
                "developer": "none",
                "assistant": "none",
                "user": "user",
                "tool": "tool_result",
                "function": "tool_result",
            }.get(role, "user")
            content = message.get("content")
            text = content if isinstance(content, str) else _flatten(content)
            self.mark(f"$.messages[{i}].content", source, text)

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
                parts.append(str(block.get("text") or block.get("content") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


def exceeds(actual: str, allowed: str) -> bool:
    """True when ``actual`` provenance is more dangerous than ``allowed``."""
    return taint_rank(actual) > taint_rank(allowed)


__all__ = ["TaintTracker", "TaintMark", "exceeds", "_flatten"]
