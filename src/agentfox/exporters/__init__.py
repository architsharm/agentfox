"""L4 egress: where AgentFox sends what it recorded (trace correlation with LangSmith and
Langfuse, OTLP, SIEM, Prometheus).

Re-exports are lazy so importing this package opens nothing.
"""

from __future__ import annotations

_LAZY = {
    "ExternalRef": ("agentfox.exporters.correlation", "ExternalRef"),
    "link_trace": ("agentfox.exporters.correlation", "link_trace"),
    "links_for": ("agentfox.exporters.correlation", "links_for"),
    "resolve_external": ("agentfox.exporters.correlation", "resolve_external"),
    "render_metrics": ("agentfox.exporters.prometheus", "render_metrics"),
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
