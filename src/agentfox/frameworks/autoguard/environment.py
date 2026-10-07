"""What the app is built on and what to call it: frameworks already loaded, which
patched client each one reaches the model through, and the agent name guessed from
the environment.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from agentfox.core.config import env

if TYPE_CHECKING:
    from agentfox.frameworks.autoguard import PatchResult


#: Modules whose presence in `sys.modules` tells us what the app is built on. Reading
#: `sys.modules` rather than importing keeps detection free of side effects — we learn
#: what the app already loaded, not what it *could* load.
_FRAMEWORK_MODULES = {
    "langgraph": "langgraph",
    "langchain": "langchain",
    "llama_index": "llamaindex",
    "crewai": "crewai",
    "autogen": "autogen",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "mcp": "mcp",
    "ragas": "ragas",
    "litellm": "litellm",
}


#: Detected framework -> the client libraries (patch labels) it calls the model
#: through. Only frameworks that make model calls are listed; web frameworks and MCP
#: carry no model traffic of their own.
_FRAMEWORK_ROUTES: dict[str, tuple[str, ...]] = {
    "langgraph": ("langchain", "openai", "anthropic"),
    "langchain": ("langchain",),
    "crewai": ("litellm", "openai", "anthropic"),
    "llamaindex": ("openai", "anthropic"),
    "autogen": ("openai", "anthropic"),
    "ragas": ("langchain", "openai"),
}


def detect_frameworks() -> list[str]:
    return sorted({name for module, name in _FRAMEWORK_MODULES.items() if module in sys.modules})


def _framework_routes(
    frameworks: list[str], patches: list[PatchResult]
) -> dict[str, dict[str, str]]:
    by_label = {p.library: p for p in patches}
    routes: dict[str, dict[str, str]] = {}
    for framework in frameworks:
        clients = _FRAMEWORK_ROUTES.get(framework)
        if not clients:
            continue
        statuses: dict[str, str] = {}
        for client in clients:
            sync = by_label.get(client)
            async_ = by_label.get(f"{client}.async")
            sync_ok = bool(sync and sync.patched)
            async_ok = bool(async_ and async_.patched)
            if sync_ok and async_ok:
                statuses[client] = "governed"
            elif sync_ok:
                statuses[client] = "governed (sync only)"
            elif async_ok:
                statuses[client] = "governed (async only)"
            elif sync is not None and sync.detail != "not installed":
                # Installed but we could not patch it: say so, loudly.
                statuses[client] = f"NOT governed ({sync.detail})"
            # Not installed: the framework cannot be routing through it — omitted.
        routes[framework] = statuses
    return routes


def default_agent_slug() -> str:
    """Guess a sensible agent name so `auto()` needs no arguments at all.

    Order: explicit env var, then the service name conventions used by most
    deployments, then the entry-point script. A wrong-but-stable guess is far better
    than a required argument — the developer can rename the agent in the registry
    later, and until then their traffic is at least attributed to *something*.
    """
    explicit = env("AGENT")  # AGENTFOX_AGENT
    if explicit:
        return explicit
    for var in (
        "OTEL_SERVICE_NAME",
        "SERVICE_NAME",
        "APP_NAME",
        "K_SERVICE",
    ):
        value = os.environ.get(var)
        if value:
            return value
    entry = os.path.basename(sys.argv[0] or "")
    if entry and entry not in ("python", "python3", "-c", "pytest"):
        return os.path.splitext(entry)[0]
    return "default-agent"
