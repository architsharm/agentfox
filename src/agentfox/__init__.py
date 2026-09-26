"""AgentFox — agent-native, vendor-neutral governance for AI agents in production.

The whole product, from a developer's point of view, is one line:

    import agentfox
    agentfox.auto()

Every model call in the process is then traced, evaluated against policy, and written
to a tamper-evident audit log — in **observe mode**, blocking nothing, until someone
decides otherwise. Nothing else in the codebase changes.

Everything below that is depth for teams that want it: an SDK with explicit sessions
and taint tracking, a LangGraph-native guard, a gateway for non-Python stacks, and a
control plane. The one-liner exists because the sum of small integration asks is why
governance tooling sits in a proof-of-concept for six months.
"""

__version__ = "0.3.1"

# Lazily re-exported so `import agentfox` stays fast and side-effect free — importing
# the package must never open a database or touch a client library.
_LAZY = {
    "auto": ("agentfox.autoguard", "auto"),
    "off": ("agentfox.autoguard", "off"),
    "state": ("agentfox.autoguard", "state"),
    "Blocked": ("agentfox.autoguard", "Blocked"),
    "AgentFox": ("agentfox.sdk", "AgentFox"),
    "PolicyViolation": ("agentfox.sdk", "PolicyViolation"),
    "ApprovalRequired": ("agentfox.sdk", "ApprovalRequired"),
}

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module, attribute = _LAZY[name]
        return getattr(importlib.import_module(module), attribute)
    raise AttributeError(f"module 'agentfox' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
