"""AgentFox CLI.

`app` and `main` are loaded on first use rather than on import of the package, so
importing a command module (`agentfox.apps.cli.commands._shared`, or an extension's
CLI that builds on it) does not build the whole command tree first. Built eagerly, an
extension's CLI module imported before `main` re-entered itself half-initialised and
its commands were silently left out.
"""

from __future__ import annotations

from typing import Any

__all__ = ["app", "main"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        import importlib

        return getattr(importlib.import_module("agentfox.apps.cli.main"), name)
    raise AttributeError(name)
