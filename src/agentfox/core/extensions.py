"""Extensions: how the enterprise package (and anything else) plugs into the open core.

The open core never imports an extension. An extension is found by the
``agentfox.extensions`` entry point group, or as the ``agentfox_ee`` module when that
is importable (a checkout with ``ee/src`` on the path), and contributes through the
optional attributes below. Each one is collected where core would otherwise have had
to name the module: the gateway mounts its routers, the job runner registers its
handlers, the scheduler adds its defaults, and so on.

An extension object may define any of:

* ``name`` (str) and ``features`` (iterable of str): what it adds, for `/api/meta`
  and the dashboard's navigation.
* ``routers()``: FastAPI routers to mount on the gateway.
* ``jobs()``: ``{kind: handler}`` for the job runner.
* ``schedules()``: dicts with ``kind``, ``interval_seconds``, ``enabled``, ``payload``
  and ``why``, added to the default schedules.
* ``session_extensions()``: ``(module:function, label)`` commit listeners.
* ``write_roles()``: ``{family: roles}`` merged into the gateway's RBAC matrix.
* ``privileged()``: dotted paths of privileged operator actions (`operator_log`).
* ``cli(app)``: add Typer commands to the CLI.
* ``mcp_tools(server)``: add tools to the MCP server.
* ``hooks()``: ``{event: callable}`` for the events core emits (see `EVENTS`).
* ``services()``: ``{name: callable}`` that core code may call when present, such as
  ``"compliance.posture"``; core asks with :func:`service` and works without it.

A failing extension is logged and skipped: an optional package must never stop the
open core from starting.
"""

from __future__ import annotations

import functools
import importlib
import logging
import os
from collections.abc import Callable, Iterable
from typing import Any

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "agentfox.extensions"
#: Importable module names tried when no entry point is installed (a source checkout).
WELL_KNOWN_MODULES = ("agentfox_ee",)
#: Set to 1 to run the open core alone even where an extension is installed.
DISABLE_ENV = "AGENTFOX_DISABLE_EXTENSIONS"

#: Events core emits, and what each hook receives.
EVENTS = {
    # (session, org_id) after a workspace is created.
    "org_created": "a new workspace exists",
    # (session, source) after a repository, MCP server or API source is connected.
    "source_connected": "a source was connected or probed",
    # (session, call) for a tool call nothing has refused yet; returns decisions.
    "tool_call": "authorize a tool call",
    # (session) -> dict | None: a section for the posture summary.
    "posture": "a posture summary section",
}


def _instance(obj: Any) -> Any:
    """An extension object from whatever the entry point or module exposes: a module
    with an ``extension()`` factory, the factory itself, a class, or an instance.

    The factory case is what an installed package's entry point resolves to
    (``agentfox_ee:extension``); returned uncalled, it loaded as an "extension" that
    contributed nothing, which a source checkout (module path) never showed.
    """
    import inspect

    if hasattr(obj, "extension") and callable(obj.extension):
        return obj.extension()
    if isinstance(obj, type) or inspect.isfunction(obj):
        return obj()
    return obj


@functools.cache
def loaded() -> tuple[Any, ...]:
    if os.environ.get(DISABLE_ENV) == "1":
        return ()
    found: dict[str, Any] = {}
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                ext = _instance(ep.load())
                found[getattr(ext, "name", ep.name)] = ext
            except Exception as exc:  # pragma: no cover - a broken plug-in
                log.warning("extension %s failed to load: %s", ep.name, exc)
    except Exception:  # pragma: no cover - broken metadata
        pass
    for module in WELL_KNOWN_MODULES:
        try:
            ext = _instance(importlib.import_module(module))
        except ModuleNotFoundError:
            continue
        except Exception as exc:  # pragma: no cover - a broken checkout
            log.warning("extension %s failed to load: %s", module, exc)
            continue
        found.setdefault(getattr(ext, "name", module), ext)
    return tuple(found.values())


def reset() -> None:
    """Forget what was loaded (tests)."""
    loaded.cache_clear()


def names() -> list[str]:
    return [str(getattr(e, "name", type(e).__name__)) for e in loaded()]


def features() -> frozenset[str]:
    out: set[str] = set()
    for ext in loaded():
        out.update(getattr(ext, "features", ()) or ())
    return frozenset(out)


def has(feature: str) -> bool:
    return feature in features()


def collect(attr: str, *args: Any) -> list[Any]:
    """Call ``attr(*args)`` on every extension that has it and flatten the results.

    Mappings are returned as ``(key, value)`` pairs; use :func:`merged` for a dict.
    """
    out: list[Any] = []
    for ext in loaded():
        fn = getattr(ext, attr, None)
        if not callable(fn):
            continue
        try:
            result = fn(*args)
        except Exception as exc:
            log.warning("extension %s.%s failed: %s", getattr(ext, "name", ext), attr, exc)
            continue
        if result is None:
            continue
        if isinstance(result, dict):
            out.extend(result.items())
        elif isinstance(result, Iterable) and not isinstance(result, str | bytes):
            out.extend(result)
        else:
            out.append(result)
    return out


def merged(attr: str) -> dict[Any, Any]:
    return dict(collect(attr))


def hooks(event: str) -> list[Callable[..., Any]]:
    if event not in EVENTS:
        raise KeyError(f"unknown extension event {event!r}")
    out: list[Callable[..., Any]] = []
    for ext in loaded():
        table = getattr(ext, "hooks", None)
        mapping = table() if callable(table) else (table or {})
        fn = mapping.get(event)
        if callable(fn):
            out.append(fn)
    return out


def emit(event: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Run every hook for an event; a failing hook is logged, never raised."""
    results = []
    for fn in hooks(event):
        try:
            results.append(fn(*args, **kwargs))
        except Exception as exc:
            log.warning("extension hook %s failed: %s", event, exc)
    return results


def service(name: str) -> Callable[..., Any] | None:
    """A named callable an extension provides, or None when none is installed."""
    for ext in loaded():
        table = getattr(ext, "services", None)
        mapping = table() if callable(table) else (table or {})
        fn = mapping.get(name)
        if callable(fn):
            return fn
    return None
