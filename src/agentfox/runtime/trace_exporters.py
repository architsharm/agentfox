"""The exporters the runtime tells about each governed trace.

When a completion is governed, the runtime records the caller's external trace ids
(LangSmith, Langfuse, OTel) against its own trace and pushes the verdict back to them.
That work belongs to `agentfox.exporters`, which sits above the runtime, so the runtime
names its exporters here instead of importing them, the way `core/db.py` names its
session extensions.

An exporter is any object with

* ``link(session, trace_id, correlation)`` — called when a trace starts, with whatever
  the caller passed as ``correlation`` (headers, or a list of references);
* ``push(session, trace_id, *, verdict, effective_verdict, rules, agent_slug)`` —
  called with each verdict worth reporting.

The caller wraps every call so an exporter can never fail the request.
"""

from __future__ import annotations

import importlib
from typing import Any

#: ``module:attribute`` of each exporter, in the order they are told.
TRACE_EXPORTERS: tuple[str, ...] = ("agentfox.exporters.correlation:TraceCorrelation",)

_loaded: list[Any] | None = None


def trace_exporters() -> list[Any]:
    """The exporters named in `TRACE_EXPORTERS`, imported once."""
    global _loaded
    if _loaded is None:
        loaded = []
        for target in TRACE_EXPORTERS:
            module, attribute = target.split(":")
            loaded.append(getattr(importlib.import_module(module), attribute)())
        _loaded = loaded
    return _loaded


__all__ = ["TRACE_EXPORTERS", "trace_exporters"]
