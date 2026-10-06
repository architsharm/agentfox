"""The check registry: what `Enforcer.evaluate` runs beside the detector pipeline.

A *check* is a function from one call's context to a small dict. Capabilities register
their checks with the `check` decorator; the runtime asks this module for the checks
that apply to a surface and runs them in order. The runtime never imports a check: it
names the modules that hold the built-in ones (`runtime/checks.py:BUILTIN_CHECK_MODULES`)
and this module imports them, the way `core/db.py` names its session extensions. Checks
from other packages arrive through the ``agentfox.checks`` entry-point group, and checks
shipped in a capability pack (``checks/*.py``) through the pack loader.

Two kinds, because they compose differently:

* ``content`` checks return ``{evidence_issues, risks, <anything else>}``. Issues become
  findings, risks join ``action["risks"]`` (what a policy's ``action_risk`` condition
  matches), and every other key is recorded in the decision's taint summary. Nothing a
  content check returns sets a verdict by itself.
* ``ladder`` checks return a list of business-ladder decisions, which the runtime
  combines with the policy verdict by its own algebra (exactly one band; security
  dominates).

Ordering is explicit: each check has an ``order`` and they run lowest first (ties in
registration order). The built-in content checks are numbered so the sequence is the
one the runtime has always used: evidence, disclosure, commitment, context,
control flow, sycophancy, trajectory.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: The two kinds of check, see the module docstring.
KINDS = ("content", "ladder")

#: The entry-point group another package registers check modules under. Each entry
#: point names a module; importing it registers its checks.
ENTRY_POINT_GROUP = "agentfox.checks"

#: Where a check without an explicit order goes: after every built-in one.
DEFAULT_ORDER = 1000


@dataclass(frozen=True)
class CheckContext:
    """Everything a check may read about one call. Read-only by convention.

    ``evidence`` is what the caller supplied about the call (retrieval chunks, the
    principal, a declared plan, a decision record…), the same dict the SDK, the
    LangGraph guard and the gateway set on ``Enforcer.evidence``. A check that needs a
    fact the caller did not supply returns nothing rather than guessing it.
    """

    session: Any
    settings: Any
    agent: Any
    surface: str
    content: str
    intent: str | None = None
    evidence: dict[str, Any] | None = None
    trace_id: str | None = None
    tool_key: str | None = None
    arguments: dict[str, Any] | None = None
    memory_entry: dict[str, Any] | None = None
    conversation_window: list[str] | None = None
    #: The request's detector pipeline, for a check that needs to score text itself.
    pipeline: Any = None

    @property
    def action(self) -> dict[str, Any]:
        """The tool call this context is about: its key and arguments."""
        return {"tool": self.tool_key, "arguments": self.arguments or {}}


CheckFn = Callable[[CheckContext], Any]


@dataclass(frozen=True)
class Check:
    """One registered check."""

    key: str
    fn: CheckFn
    kind: str = "content"
    #: The surfaces it runs on; None means every surface.
    surfaces: frozenset[str] | None = None
    order: int = DEFAULT_ORDER
    #: ``builtin``, ``entry_point:<name>`` or ``pack:<id>``. A check that is not built
    #: in can never fail a request: an exception is logged and the check is skipped.
    source: str = "builtin"
    description: str = ""
    seq: int = field(default=0, compare=False)

    def applies(self, surface: str) -> bool:
        return self.surfaces is None or surface in self.surfaces

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "surfaces": sorted(self.surfaces) if self.surfaces is not None else None,
            "order": self.order,
            "source": self.source,
            "description": self.description,
        }


_REGISTRY: dict[str, Check] = {}
_seq = 0
#: Set while a module is being imported for registration, so its checks record where
#: they came from without each decorator having to say.
_current_source = "builtin"


def register(check_: Check) -> Check:
    """Add a check. A key registered twice keeps the first registration.

    First wins, so a pack or a third-party package cannot replace a built-in check
    by reusing its key; it is logged and ignored.
    """
    global _seq
    existing = _REGISTRY.get(check_.key)
    if existing is not None:
        if existing.fn is not check_.fn:
            log.warning(
                "check %r from %s ignored: already registered from %s",
                check_.key,
                check_.source,
                existing.source,
            )
        return existing
    if check_.kind not in KINDS:
        raise ValueError(f"check {check_.key!r}: kind must be one of {KINDS}")
    _seq += 1
    stored = Check(
        key=check_.key,
        fn=check_.fn,
        kind=check_.kind,
        surfaces=check_.surfaces,
        order=check_.order,
        source=check_.source,
        description=check_.description,
        seq=_seq,
    )
    _REGISTRY[stored.key] = stored
    return stored


def check(
    key: str,
    *,
    surfaces: Iterable[str] | None = None,
    order: int = DEFAULT_ORDER,
    kind: str = "content",
    description: str = "",
) -> Callable[[CheckFn], CheckFn]:
    """Register the decorated function as a check under ``key``.

    ``surfaces`` limits where it runs (the runtime does not call it elsewhere);
    ``order`` places it among the others, lowest first. The function takes one
    `CheckContext` and returns a dict (``content``) or a list of ladder decisions
    (``ladder``); an empty result means it found nothing.
    """

    def decorate(fn: CheckFn) -> CheckFn:
        register(
            Check(
                key=key,
                fn=fn,
                kind=kind,
                surfaces=frozenset(surfaces) if surfaces is not None else None,
                order=order,
                source=_current_source,
                description=description or (fn.__doc__ or "").strip().split("\n")[0],
            )
        )
        return fn

    return decorate


def _import(module: str, source: str) -> None:
    global _current_source
    previous, _current_source = _current_source, source
    try:
        importlib.import_module(module)
    finally:
        _current_source = previous


def import_as(source: str, loader: Callable[[], Any]) -> Any:
    """Run ``loader`` with every check it registers attributed to ``source``.

    The pack loader uses this to import a pack's ``checks/*.py`` as ``pack:<id>``.
    """
    global _current_source
    previous, _current_source = _current_source, source
    try:
        return loader()
    finally:
        _current_source = previous


_loaded_builtin: tuple[str, ...] | None = None
_loaded_external = False


def load(builtin_modules: Iterable[str] = ()) -> None:
    """Import the built-in check modules, then entry points and pack checks, once.

    Built-ins are imported unguarded: a built-in check that cannot be imported is a
    broken install and must not pass silently. Entry points and packs are guarded.
    """
    global _loaded_builtin, _loaded_external
    modules = tuple(builtin_modules)
    if _loaded_builtin != modules:
        for module in modules:
            _import(module, "builtin")
        _loaded_builtin = modules
    if not _loaded_external:
        _loaded_external = True
        _load_entry_points()
        _load_pack_checks()


def _load_entry_points() -> None:
    from importlib.metadata import entry_points

    try:
        found = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # pragma: no cover - a broken environment
        return
    for ep in found:
        try:
            _import(ep.value.split(":")[0], f"entry_point:{ep.name}")
        except Exception:
            log.warning("check entry point %s could not be loaded", ep.name, exc_info=True)


def _load_pack_checks() -> None:
    try:
        from agentfox.platform.packs import load_checks

        load_checks()
    except Exception:
        log.warning("capability-pack checks could not be loaded", exc_info=True)


def checks(kind: str = "content", surface: str | None = None) -> list[Check]:
    """The registered checks of ``kind`` (that run on ``surface``), in run order."""
    selected = [
        c for c in _REGISTRY.values() if c.kind == kind and (surface is None or c.applies(surface))
    ]
    return sorted(selected, key=lambda c: (c.order, c.seq))


def run(check_: Check, context: CheckContext) -> Any:
    """Call one check. Only a built-in check may raise through to the request."""
    if check_.source == "builtin":
        return check_.fn(context)
    try:
        return check_.fn(context)
    except Exception:
        log.warning(
            "check %s (%s) failed and was skipped", check_.key, check_.source, exc_info=True
        )
        return None


def merge_content(results: Iterable[dict[str, Any] | None]) -> tuple[dict[str, Any], list[Any]]:
    """Fold content-check results into one evidence dict and one list of risks.

    Each result's ``evidence_issues`` are appended to one list and its ``risks`` to
    another; every other key is merged into the evidence dict, later checks
    overwriting earlier ones. A check that returned an explicit empty
    ``evidence_issues`` list still leaves the key present, so a decision records that
    the check ran and found nothing.
    """
    evidence: dict[str, Any] = {}
    risks: list[Any] = []
    for result in results:
        if not result:
            continue
        rest = dict(result)
        issues = rest.pop("evidence_issues", None)
        risks.extend(rest.pop("risks", None) or [])
        evidence.update(rest)
        if issues:
            evidence["evidence_issues"] = [*evidence.get("evidence_issues", []), *issues]
        elif issues is not None and "evidence_issues" not in evidence:
            evidence["evidence_issues"] = []
    return evidence, risks


def unregister(key: str) -> None:
    """Remove a check. For tests that register their own."""
    _REGISTRY.pop(key, None)


def reset_external() -> None:
    """Forget entry-point and pack checks so the next `load` imports them again (tests)."""
    global _loaded_external
    for key in [k for k, c in _REGISTRY.items() if c.source != "builtin"]:
        del _REGISTRY[key]
    _loaded_external = False


__all__ = [
    "DEFAULT_ORDER",
    "ENTRY_POINT_GROUP",
    "KINDS",
    "Check",
    "CheckContext",
    "check",
    "checks",
    "import_as",
    "load",
    "merge_content",
    "register",
    "reset_external",
    "run",
    "unregister",
]
