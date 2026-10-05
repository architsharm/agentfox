"""Composed privilege escalation (F3.8, P9-11).

*"A read tool's output surfaces an internal ID that a second, differently-scoped
tool then accepts as if it were user-supplied and authorized."*

Every other check in `actions.py` reasons about **one call at a time**: is this SQL
destructive, does this shell command touch a deny-listed pattern, does this argument
look like an injected fragment. None of them can see the shape this failure mode
actually takes — two individually well-formed, individually permitted calls, where
the *second* one's argument happens to be a value the *first* one just returned.
Neither tool's own scope check has any way to know that, because neither call looks
wrong on its own.

The mechanism: `guardrails.taint.TaintTracker` already tags an argument's value with
`propagated_from` — the path of whichever earlier tool-result content it matched
against (P3-4's provenance ledger, built for a different purpose — flagging
untrusted content flowing into arguments — but it already records exactly the fact
this check needs: *which tool produced this value*). This module adds the one
comparison that was missing: does the *producing* tool's impact tier exceed what the
*consuming* tool alone was scoped for. Everything else (marking, propagation,
persistence) already existed; see `docs/dataset-sourcing.md`'s investigation notes
and `benchmarks/composed_privilege_escalation/README.md` for why no public dataset
tests this specific composition, and why it was built directly instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

#: Tool.impact's own three-tier convention (models.py: "read"/"write"/"irreversible",
#: "the axis policy reasons over"). Reused as-is rather than inventing a parallel
#: ranking — a second scale for the same concept is how these drift out of sync.
IMPACT_RANK = {"read": 0, "write": 1, "irreversible": 2}

#: Prefix used by the SDK's `tool_result()` (sdk/__init__.py) when the caller
#: identifies the producing tool. Kept distinct from MCP governance's own
#: `mcp.<server>.<tool>` convention (integrations/mcp.py) rather than unifying them,
#: to avoid touching that already-shipped, already-tested path.
_SDK_TOOL_RESULT_PREFIX = "tool:"


def tool_key_from_origin(path: str) -> str | None:
    """Recover a producing tool's *registered* key from a taint mark's origin path.

    Two conventions currently encode tool identity in a mark's path:
    - MCP governance (``integrations/mcp.py``): the taint mark's path is
      ``mcp.<server>.<tool>`` (dot-separated — see ``_govern_result``), but the
      tool is actually *registered* under a different format,
      ``integrations.mcp.tool_key()``'s ``mcp:<server>/<tool>`` (colon + slash).
      These are two distinct, already-shipped conventions in the same module,
      not a typo — this function reconstructs the registered form so the
      lookup below hits the real `Tool.key`, rather than importing
      `integrations.mcp` here (guardrails/ stays integration-agnostic; the
      coupling is this one format string, disclosed rather than hidden behind
      an import).
    - The SDK's ``tool_result(text, tool=...)``: ``tool:<tool_key>#<index>``,
      where ``<tool_key>`` is already the registered key as-is.

    Anything else — ``$.content``, ``$.messages[i].content``, ``$.retrieved[...]``,
    or an untagged ``$.tool_result[...]`` from a caller that didn't pass ``tool=``
    — doesn't identify a producing tool, and returns ``None``. That's the correct
    outcome, not a miss: this check is specifically about tool-to-tool flow, and a
    value with no known producing tool can't be compared against one.
    """
    if path.startswith("mcp."):
        parts = path.split(".", 2)
        if len(parts) != 3 or not parts[2]:
            return None
        server, tool = parts[1], parts[2]
        return f"mcp:{server}/{tool}"
    if path.startswith(_SDK_TOOL_RESULT_PREFIX):
        rest = path[len(_SDK_TOOL_RESULT_PREFIX) :]
        key = rest.split("#", 1)[0]
        return key or None
    return None


@dataclass(slots=True)
class CompositionFinding:
    argument_path: str
    origin_tool: str
    origin_impact: str
    consuming_tool: str
    consuming_impact: str

    @property
    def reason(self) -> str:
        return (
            f"argument '{self.argument_path}' carries a value produced by tool "
            f"'{self.origin_tool}' ({self.origin_impact}), now passed into "
            f"'{self.consuming_tool}' ({self.consuming_impact}) — a composition "
            "neither tool's own scope permits alone"
        )

    def to_json(self) -> dict[str, str]:
        return {
            "argument_path": self.argument_path,
            "origin_tool": self.origin_tool,
            "origin_impact": self.origin_impact,
            "consuming_tool": self.consuming_tool,
            "consuming_impact": self.consuming_impact,
            "reason": self.reason,
        }


def check_composed_escalation(
    *,
    consuming_tool_key: str,
    consuming_tool_impact: str,
    argument_propagated_from: dict[str, str],
    tool_impact_lookup: Callable[[str], str | None],
) -> list[CompositionFinding]:
    """F3.8 — does any argument's value originate from a lower-impact tool call.

    ``argument_propagated_from`` maps an argument path to the taint mark's
    ``propagated_from`` (only present for inferred, not caller-declared,
    provenance — a value the agent explicitly declared came from a given source
    isn't a silent composition, it's a disclosed one, and this check is about the
    silent case). ``tool_impact_lookup`` resolves a tool key to its registered
    ``Tool.impact``, or ``None`` if the tool isn't registered — an unregistered
    origin can't be scope-compared, so it's skipped rather than assumed either way.

    A same-tool "escalation" (a tool's own prior output feeding its own next call,
    e.g. pagination) is not flagged — the composition this check cares about is
    genuinely cross-tool.
    """
    consuming_rank = IMPACT_RANK.get(consuming_tool_impact, 0)
    findings: list[CompositionFinding] = []
    for path, origin_path in argument_propagated_from.items():
        origin_tool = tool_key_from_origin(origin_path)
        if origin_tool is None or origin_tool == consuming_tool_key:
            continue
        origin_impact = tool_impact_lookup(origin_tool)
        if origin_impact is None:
            continue
        if IMPACT_RANK.get(origin_impact, 0) < consuming_rank:
            findings.append(
                CompositionFinding(
                    argument_path=path,
                    origin_tool=origin_tool,
                    origin_impact=origin_impact,
                    consuming_tool=consuming_tool_key,
                    consuming_impact=consuming_tool_impact,
                )
            )
    return findings


__all__ = ["IMPACT_RANK", "CompositionFinding", "check_composed_escalation", "tool_key_from_origin"]
