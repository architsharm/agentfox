"""One agent, one key: the slug every path gives a name.

`agentfox scan`, `agentfox up`, `agentfox init`, a submitted scan and `auto("...")`
at runtime all turn the name the code (or the user) gives an agent into the registry
key through :func:`slug`, so `FinancialPlannerAgent`, `financial_planner_agent` and
"Financial planner agent" are one agent, `financial-planner-agent`. The name as
written is kept separately, for display.
"""

from __future__ import annotations

import re

_NOT_SLUG = re.compile(r"[^a-z0-9-]+")
#: Word boundaries inside a CamelCase name: `GameBuilderCrew`, `LLMAgent`.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def slug(value: str | None, default: str = "agent") -> str:
    """Lower case, words joined by hyphens, whether written `snake_case`, `CamelCase`
    or as a sentence."""
    words = _CAMEL.sub("-", (value or "").strip())
    return _NOT_SLUG.sub("-", words.lower()).strip("-") or default


def legacy_slug(value: str | None, default: str = "agent") -> str:
    """The key earlier releases gave a name: CamelCase words run together
    (`FinancialPlannerAgent` -> `financialplanneragent`). Looked up only to find an
    agent registered under it, never to name a new one."""
    return _NOT_SLUG.sub("-", (value or "").strip().lower()).strip("-") or default
