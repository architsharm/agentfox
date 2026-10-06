"""Framework integrations.

Each integration is optional and degrades cleanly when its framework is absent, so
`pip install agentfox` stays light and the offline story holds.

Re-exports are lazy. Importing them eagerly created a cycle — `enforcement` imports
`correlation`, which would import this package, which would import `mcp`, which
imports `enforcement` — and the cycle only surfaced on a fresh `import agentfox`
rather than in tests that import submodules directly. Lazy attributes keep the
convenience without the trap.
"""

from __future__ import annotations

_LAZY = {
    "ExternalRef": (".correlation", "ExternalRef"),
    "link_trace": (".correlation", "link_trace"),
    "links_for": (".correlation", "links_for"),
    "resolve_external": (".correlation", "resolve_external"),
    "McpGovernor": (".mcp", "McpGovernor"),
    "McpCallBlocked": (".mcp", "McpCallBlocked"),
    "tool_key": (".mcp", "tool_key"),
    "render_metrics": (".prometheus", "render_metrics"),
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module, attribute = _LAZY[name]
        return getattr(importlib.import_module(module, __name__), attribute)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return list(__all__)
