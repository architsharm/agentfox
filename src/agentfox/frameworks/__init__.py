"""L4 ingress for application frameworks: the SDK, `auto()`, LangGraph, FastAPI and the MCP
governor.

Each one maps its framework's calls onto the `Enforcer` and degrades cleanly when its
framework is absent, so `pip install agentfox` stays light.

Re-exports are lazy: `agentfox.frameworks.mcp` imports the runtime, and importing this
package must not.
"""

from __future__ import annotations

_LAZY = {
    "McpGovernor": ("agentfox.frameworks.mcp", "McpGovernor"),
    "McpCallBlocked": ("agentfox.frameworks.mcp", "McpCallBlocked"),
    "tool_key": ("agentfox.frameworks.mcp", "tool_key"),
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module, attribute = _LAZY[name]
        return getattr(importlib.import_module(module), attribute)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return list(__all__)
