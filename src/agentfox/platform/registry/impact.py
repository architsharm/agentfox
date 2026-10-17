"""A tool's impact: declared where someone said it, otherwise inferred from its name.

Containment reasons over `Tool.impact` (``read``, ``write``, ``high_impact``,
``irreversible``), so every place that has to put a number on a tool it has not been
told about asks :func:`infer_impact`: the MCP governor registering a server's tools,
`auto()` registering a tool the model called, the learned-permissions loop suggesting a
declaration, the exposure scan, and the coding-agent hooks declaring a harness's
built-in tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Verbs that change something. Everything else defaults to read, and an operator can
#: override per tool in the registry — this is a starting classification, not a claim
#: to understand every server's semantics.
_WRITE_HINTS = ("create", "update", "delete", "write", "send", "post", "put", "execute", "run")
_IRREVERSIBLE_HINTS = ("delete", "drop", "purge", "send", "transfer", "deploy", "revoke")

#: Words the hints above do not treat as irreversible but a person would: money moves
#: and messages leave. Only the cautious reading uses them (`auto()` and the
#: learned-permissions suggestion), not the MCP governor's registration.
_IRREVERSIBLE_WORDS = (
    "refund",
    "pay",
    "charge",
    "transfer",
    "wire",
    "email",
    "sms",
    "message",
    "notify",
    "publish",
    "cancel",
    "close",
)

#: Tool key -> impact, for every `@fox.tool(key, impact=...)` declared in this
#: process. The decorator also writes the row, but it runs at import time, which can
#: be before the database exists; this is what `auto()` consults when it registers a
#: tool the model called, so a declaration made in code beats a guess from the name
#: even when that write could not happen yet.
_DECLARED: dict[str, str] = {}


def declare_impact(tool_key: str, impact: str) -> None:
    """Record an impact declared in code (`@fox.tool(impact=...)`) for this process."""
    _DECLARED[tool_key] = impact


def declared_impact(tool_key: str) -> str | None:
    """The impact code in this process declared for ``tool_key``, if any."""
    return _DECLARED.get(tool_key)


def infer_impact(
    name: str,
    descriptor: dict[str, Any] | None = None,
    *,
    declared: Mapping[str, str] | None = None,
    cautious: bool = False,
) -> str:
    """The impact of the tool called ``name``.

    ``declared`` is a table of known impacts (a harness's built-in tools, say); a name
    in it gets its declared value. Otherwise the impact is guessed from the name and
    the descriptor's description. ``cautious`` also treats a name whose last path
    segment moves money or sends a message as irreversible, the reading for a guess
    that is never confirmed before it is used.
    """
    if declared is not None and name in declared:
        return declared[name]
    haystack = f"{name} {(descriptor or {}).get('description', '')}".lower()
    if any(h in haystack for h in _IRREVERSIBLE_HINTS):
        return "irreversible"
    if cautious and any(w in name.rsplit("/", 1)[-1].lower() for w in _IRREVERSIBLE_WORDS):
        return "irreversible"
    if any(h in haystack for h in _WRITE_HINTS):
        return "write"
    return "read"


__all__ = ["declare_impact", "declared_impact", "infer_impact"]
