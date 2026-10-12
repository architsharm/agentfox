"""The validator interface: one small check, its settings, and what it reports.

A detector (`detection/base.py`) is the runtime's unit: it has a latency budget,
measured precision and a place on the Checks screen. A *validator* is smaller — a
single check with a settings schema — so a new one is a file, not an adapter.
`ValidatorDetector` turns a validator into a detector, and a custom rule of kind
``validator`` runs one with the settings a workspace gave it, so both get the
pipeline's budgets, obfuscation views, tuning and policy for free.

Three kinds, by what decides:

* ``rule`` — code on this host: a pattern, a parser, a list. Offline, deterministic.
* ``model`` — a local model (a Hugging Face classifier, an embedding model). Needs an
  optional dependency and a weight download, never a network call per request.
* ``judge`` — a question put to the judgment tier (`capabilities/judgment/panel.py`),
  which owns egress, redaction and which provider may answer.

Validators are registered (`validators/__init__.py`) and discoverable through the
``agentfox.validators`` entry-point group, so a package outside this repository adds
one exactly as the built-in ones are added.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

Kind = Literal["rule", "model", "judge"]


class NoParams(BaseModel):
    """Settings for a validator that takes none."""

    model_config = ConfigDict(extra="forbid")


@dataclass(slots=True)
class Finding:
    """One thing a validator objects to. ``start == end == 0`` means the whole text."""

    reason: str
    start: int = 0
    end: int = 0
    score: float = 1.0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CheckContext:
    """What a validator may know beyond the text: where it is, which tool, which agent."""

    surface: str = "output"
    tool: str | None = None
    agent_slug: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Validator:
    """Subclass, set the class attributes, implement :meth:`check`.

    ``Params`` is a pydantic model; its fields are the validator's settings, checked
    when a rule is saved so a bad value never reaches a request. A validator whose
    ``Params`` can be built with no arguments also runs as a stand-alone detector,
    ``validator.<name>``; one that needs settings (a system prompt, a column list)
    runs only through a custom rule that supplies them.
    """

    name: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    #: Our taxonomy, so existing policies match it (INJECTION.*, PII.*, SAFETY.*, …).
    entity_type: ClassVar[str] = ""
    surfaces: ClassVar[tuple[str, ...]] = ("output",)
    kind: ClassVar[Kind] = "rule"
    Params: ClassVar[type[BaseModel]] = NoParams
    #: Importable modules this needs; absent ones make it unavailable, not broken.
    requires: ClassVar[tuple[str, ...]] = ()
    #: Model ids it downloads, for the Checks screen and `admin detectors pull`.
    models: ClassVar[tuple[str, ...]] = ()
    #: Where the logic came from. Ported code keeps its upstream licence.
    upstream: ClassVar[str | None] = None
    license: ClassVar[str] = "Apache-2.0"
    owasp_id: ClassVar[str | None] = None
    atlas_id: ClassVar[str | None] = None
    #: None: the pipeline default. Model forward passes declare more.
    timeout_ms: ClassVar[int | None] = None
    #: Total pipeline budget this needs when selected (a network judge cannot finish
    #: in the default). See `DetectorPipeline.run`.
    requires_budget_ms: ClassVar[int | None] = None
    #: Also offered as a stand-alone detector (``validator.<name>``) on the Checks
    #: screen. Only for checks worth switching on for every request; format checks
    #: (casing, length) stay rule-only so the screen lists what governs.
    detector: ClassVar[bool] = False
    #: Re-run on decoded readings (base64, homoglyphs) of the text. Off for checks
    #: about the text's shape, where a decoded reading is a different text.
    scan_views: ClassVar[bool] = True

    def available(self) -> bool:
        return all(importlib.util.find_spec(m) is not None for m in self.requires)

    def unavailable_reason(self) -> str:
        missing = [m for m in self.requires if importlib.util.find_spec(m) is None]
        if missing:
            return f"needs {', '.join(missing)} (install the extra that provides it)"
        return ""

    def warm(self) -> None:
        """Load anything slow (a model) off the request path. No-op for rules."""

    @classmethod
    def params(cls, raw: dict[str, Any] | None = None) -> BaseModel:
        """Validated settings. Raises ``ValueError`` with a readable message."""
        try:
            return cls.Params(**(raw or {}))
        except ValidationError as exc:
            parts = [
                f"{'.'.join(str(p) for p in e['loc']) or 'params'}: {e['msg']}"
                for e in exc.errors()
            ]
            raise ValueError(f"{cls.name}: " + "; ".join(parts)) from None

    @classmethod
    def standalone(cls) -> bool:
        """Whether it can run with no settings at all."""
        try:
            cls.Params()
        except ValidationError:
            return False
        return True

    def check(self, text: str, params: Any, ctx: CheckContext) -> list[Finding]:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label or self.name,
            "description": self.description,
            "entity_type": self.entity_type,
            "surfaces": list(self.surfaces),
            "kind": self.kind,
            "standalone": self.standalone(),
            "detector": self.detector and self.standalone(),
            "params_schema": self.Params.model_json_schema(),
            "models": list(self.models),
            "upstream": self.upstream,
            "license": self.license,
            "available": self.available(),
            "unavailable_reason": "" if self.available() else self.unavailable_reason(),
        }


def span_finding(text: str, start: int, end: int, reason: str, **detail: Any) -> Finding:
    """A finding at a span, clipped to the text."""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    return Finding(reason=reason, start=start, end=end, detail=dict(detail))
