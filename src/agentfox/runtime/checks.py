"""The modules whose checks the runtime runs, named rather than imported.

`Enforcer.evaluate` runs every check in the registry (`platform/checks.py`) that
applies to the surface, in order. The built-in ones live in the capabilities that own
them; this tuple names those modules so the registry can import them on first use. The
runtime itself imports no check: adding one is a decorated function in its capability
and a line here, or, outside this package, an ``agentfox.checks`` entry point or a
capability pack's ``checks/*.py``.
"""

from __future__ import annotations

from agentfox.platform import checks as registry

#: Imported once, in this order, the first time the runtime asks for checks.
BUILTIN_CHECK_MODULES: tuple[str, ...] = (
    "agentfox.capabilities.grounding.checks",
    "agentfox.capabilities.containment.checks",
    "agentfox.capabilities.detection.checks",
    "agentfox.capabilities.business.checks",
    "agentfox.capabilities.judgment.checks",
)


def checks_for(surface: str, kind: str = "content") -> list[registry.Check]:
    """The checks of ``kind`` that run on ``surface``, in run order."""
    registry.load(BUILTIN_CHECK_MODULES)
    return registry.checks(kind, surface)


__all__ = ["BUILTIN_CHECK_MODULES", "checks_for"]
