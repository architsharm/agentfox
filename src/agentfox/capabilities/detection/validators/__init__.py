"""The validator registry.

Built-in validators live in `validators/builtin/`, one module per family, and
register themselves on import. Anything outside this repository registers through
the ``agentfox.validators`` entry-point group, pointing at a :class:`Validator`
subclass (or an instance)::

    [project.entry-points."agentfox.validators"]
    order_ids = "acme_checks.validators:OrderIdValidator"

The registry is loaded on first use, not at import, so importing the detection
package stays cheap and a broken third-party validator cannot stop it importing.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    NoParams,
    Validator,
    span_finding,
)

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "agentfox.validators"

#: Modules under `builtin/` that register validators.
BUILTIN_MODULES = (
    "text",
    "structure",
    "sql",
    "web",
    "lists",
    "disclosure",
    "models",
    "judges",
)

_REGISTRY: dict[str, Validator] = {}
_loaded = False


def register_validator(validator: Validator | type[Validator]) -> Validator:
    """Add a validator. A class is instantiated; a later name replaces an earlier one."""
    instance = validator() if isinstance(validator, type) else validator
    if not instance.name:
        raise ValueError(f"{type(instance).__name__} has no name")
    _REGISTRY[instance.name] = instance
    return instance


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in BUILTIN_MODULES:
        importlib.import_module(f"agentfox.capabilities.detection.validators.builtin.{module}")
    _load_entry_points()


def _load_entry_points() -> None:
    from importlib.metadata import entry_points

    try:
        found = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # pragma: no cover - broken metadata
        return
    for ep in found:
        try:
            register_validator(ep.load())
        except Exception as exc:
            # One bad plug-in is logged and skipped; it must not take the rest down.
            log.warning("validator entry point %s failed to load: %s", ep.name, exc)


def get_validator(name: str) -> Validator | None:
    _load()
    return _REGISTRY.get(name)


def all_validators() -> dict[str, Validator]:
    _load()
    return dict(_REGISTRY)


def check(
    name: str, text: str, params: dict[str, Any] | None = None, ctx: CheckContext | None = None
) -> list[Finding]:
    """Run one validator by name. For tests, the CLI and benchmarks."""
    validator = get_validator(name)
    if validator is None:
        raise KeyError(f"no validator named {name!r}")
    return validator.check(text, validator.params(params), ctx or CheckContext())


__all__ = [
    "ENTRY_POINT_GROUP",
    "CheckContext",
    "Finding",
    "NoParams",
    "Validator",
    "all_validators",
    "check",
    "get_validator",
    "register_validator",
    "span_finding",
]
