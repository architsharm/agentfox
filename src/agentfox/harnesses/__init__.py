"""Harnesses: the coding agents AgentFox governs through their hooks.

One adapter per harness (`base.HarnessAdapter`), found through one mechanism: the
``agentfox.harnesses`` entry-point group. The built-in adapters are registered in
AgentFox's own ``pyproject.toml`` exactly as an external ``agentfox-harness-*`` package
would register its own; when the distribution's metadata is not installed (running from
a checkout with ``PYTHONPATH=src``), the built-in list below stands in for it.

Callers outside this package and `hooks/` go through these functions — ``get``,
``known``, ``all`` and the helpers over them — and never import an adapter module
directly; an import-linter contract holds that.

Adding a harness: one folder beside ``claude_code/`` (adapter, tools, install, captured
``fixtures/``), one entry point, and ``tests/harnesses/conformance.py`` passing for it.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentfox.harnesses.base import (
    AgentEvent,
    Decision,
    HarnessAdapter,
    HookOutput,
    decision_from_verdict,
)

if TYPE_CHECKING:
    from agentfox.capabilities.discovery.sessions import SessionScanReport

log = logging.getLogger(__name__)

#: The entry-point group adapters register under.
ENTRY_POINT_GROUP = "agentfox.harnesses"

#: The built-in adapters, as their entry points name them. Used only for a name the
#: installed entry points did not provide.
BUILTIN: dict[str, str] = {
    "claude": "agentfox.harnesses.claude_code:ADAPTER",
}

_registry: dict[str, HarnessAdapter] | None = None


class UnknownHarness(ValueError):
    """No adapter for this harness, and guessing one is how a hook lies."""


def _resolve(target: Any) -> HarnessAdapter:
    adapter = target() if isinstance(target, type) else target
    if not isinstance(adapter, HarnessAdapter):
        raise TypeError(f"{target!r} does not implement HarnessAdapter")
    return adapter


def _load_builtin(spec: str) -> HarnessAdapter:
    module, _, attr = spec.partition(":")
    return _resolve(getattr(importlib.import_module(module), attr))


def _load() -> dict[str, HarnessAdapter]:
    from importlib.metadata import entry_points

    adapters: dict[str, HarnessAdapter] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            adapter = _resolve(ep.load())
        except Exception:  # a broken plugin must not take the others down
            log.warning("harness entry point %r failed to load", ep.value, exc_info=True)
            continue
        if adapter.name != ep.name:
            log.warning(
                "harness entry point %r names an adapter called %r; skipped",
                ep.name,
                adapter.name,
            )
            continue
        if adapter.name in BUILTIN and ep.value != BUILTIN[adapter.name]:
            log.warning(
                "harness entry point %r reuses the built-in name %r; skipped", ep.value, ep.name
            )
            continue
        adapters.setdefault(adapter.name, adapter)
    for name, spec in BUILTIN.items():
        if name not in adapters:
            adapters[name] = _load_builtin(spec)
    return dict(sorted(adapters.items()))


def registry() -> Mapping[str, HarnessAdapter]:
    """Every registered adapter by name, loaded once per process."""
    global _registry
    if _registry is None:
        _registry = _load()
    return _registry


def reset() -> None:
    """Forget the loaded adapters (tests that register their own)."""
    global _registry
    _registry = None


def known() -> list[str]:
    """The names ``agentfox hooks run --harness`` accepts, sorted."""
    return list(registry())


def all() -> list[HarnessAdapter]:
    """Every registered adapter, in name order."""
    return list(registry().values())


def get(name: str) -> HarnessAdapter:
    """The adapter called ``name``. Raises :class:`UnknownHarness`.

    A built-in name resolves without reading every installed distribution's entry
    points: `get` runs on every tool call the agent makes (`agentfox hooks run`), and
    that scan, with the `importlib.metadata` import it needs, costs about 20ms there.
    The answer is the same object either way, because built-in names are reserved — an
    entry point from another package that reuses one is skipped.
    """
    if _registry is None and name in BUILTIN:
        return _load_builtin(BUILTIN[name])
    adapter = registry().get(name)
    if adapter is None:
        raise UnknownHarness(
            f"no adapter for harness {name!r}. Known: {', '.join(known())}. "
            "Adding one means probing what its hook actually does with a verdict, not "
            "assuming it matches another harness."
        )
    return adapter


# ---------------------------------------------------------------------------
# Helpers over the registry
# ---------------------------------------------------------------------------


def parse(name: str, raw: Mapping[str, Any]) -> AgentEvent:
    """A raw hook payload from harness ``name``, as an :class:`AgentEvent`."""
    return get(name).parse(raw)


def output(name: str, event: AgentEvent, decision: Decision | Mapping[str, Any]) -> HookOutput:
    """What the hook process prints and exits with.

    ``decision`` is a :class:`Decision`, or the daemon's verdict reply, which is read
    with :func:`base.decision_from_verdict`.
    """
    if not isinstance(decision, Decision):
        decision = decision_from_verdict(decision, event)
    return get(name).render(decision, event)


def render(name: str, event: AgentEvent, decision: Decision | Mapping[str, Any]) -> dict[str, Any]:
    """The JSON object the hook prints, for a caller that wants it parsed."""
    return output(name, event, decision).body


def hooked_agents(root: Path | None = None) -> list[str]:
    """Agent slugs any harness's hooks in this project govern, if any."""
    root = Path(root or Path.cwd())
    slugs: set[str] = set()
    for adapter in all():
        slugs.update(adapter.hooked_agents(root))
    return sorted(slugs)


def mcp_config_paths(root: Path) -> list[Path]:
    """The MCP config files any harness reads in this project (existing or not)."""
    paths: list[Path] = []
    for adapter in all():
        paths.extend(p for p in adapter.mcp_config_paths(root) if p not in paths)
    return paths


def transcripts(overrides: Mapping[str, Path] | None = None) -> list[SessionScanReport]:
    """Every harness's local session scan, where it has one. ``overrides`` maps a
    harness name to the directory to read instead of its default."""
    overrides = overrides or {}
    reports = []
    for adapter in all():
        report = adapter.transcripts(overrides.get(adapter.name))
        if report is not None:
            reports.append(report)
    return reports


def tool_impacts(name: str) -> dict[str, str]:
    """Harness ``name``'s built-in tools and their declared impact."""
    return dict(get(name).tool_impacts)


def __getattr__(attr: str) -> Any:
    # A registry view, computed on use so importing this package loads nothing.
    if attr == "HARNESS_TOOLS":
        return {adapter.name: dict(adapter.tool_impacts) for adapter in all()}
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


__all__ = [
    "BUILTIN",
    "ENTRY_POINT_GROUP",
    "UnknownHarness",
    "all",
    "get",
    "hooked_agents",
    "known",
    "mcp_config_paths",
    "output",
    "parse",
    "registry",
    "render",
    "reset",
    "tool_impacts",
    "transcripts",
]
