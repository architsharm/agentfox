"""Bringing guardrails written for another tool into AgentFox.

An importer reads another tool's configuration and returns an `ImportPlan`: what
each guardrail becomes here, and what it cannot become. It never writes anything and
never runs the input — a plan is shown to the operator first, and applying it is the
caller's job (`routes/imports.py`), through the same stores a hand-made change uses.

Every guardrail lands as one of four things:

* ``custom_rule`` — a word list, pattern or topic, saved as a custom rule;
* ``detector``    — a built-in detector to switch on for the workspace;
* ``pack``        — a shipped policy pack that already covers it, installed watching;
* ``skipped``     — nothing here does that job, with the reason.

Adding an importer for another tool means one module that returns this plan; the
route, the screen and the apply step are shared.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from agentfox.capabilities.detection.custom import CustomRuleSpec

ItemKind = Literal["custom_rule", "detector", "pack", "skipped"]


@dataclass
class PlanItem:
    #: The guardrail as the source tool names it, e.g. "CompetitorCheck".
    source: str
    kind: ItemKind
    #: What it becomes: a rule key, detector key or pack id. Empty when skipped.
    target: str = ""
    title: str = ""
    #: One short line for the screen: what changes, or why nothing does.
    note: str = ""
    #: A custom rule's action once enforcing (block / redact / allow). Packs and
    #: detectors keep their own, so it is empty for them.
    effect: str = ""
    on_block: str = "refuse"
    rule: CustomRuleSpec | None = None
    line: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "target": self.target,
            "title": self.title,
            "note": self.note,
            "effect": self.effect,
            "on_block": self.on_block,
            "rule": self.rule.model_dump() if self.rule else None,
            "line": self.line,
        }


@dataclass
class ImportPlan:
    tool: str
    items: list[PlanItem] = field(default_factory=list)
    #: Input the parser could not read at all (not a guardrail it skipped).
    errors: list[str] = field(default_factory=list)

    def of(self, kind: ItemKind) -> list[PlanItem]:
        return [i for i in self.items if i.kind == kind]

    def to_json(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "items": [i.to_json() for i in self.items],
            "errors": self.errors,
            "summary": {k: len(self.of(k)) for k in ("custom_rule", "detector", "pack", "skipped")},
        }


Planner = Callable[..., ImportPlan]

#: Importers by the tool they read. Resolved on use, so the module for one tool is
#: imported only when someone imports from it.
IMPORTERS: dict[str, str] = {
    "guardrails-ai": "agentfox.capabilities.detection.importers.guardrails_ai",
}


def planner(tool: str) -> Planner | None:
    module = IMPORTERS.get(tool)
    if module is None:
        return None
    import importlib

    return importlib.import_module(module).plan
