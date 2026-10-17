"""Control-flow integrity: untrusted content may fill values, never choose actions.

The strongest published defence against indirect prompt injection is not a better
detector, it is a structural one: [CaMeL](https://arxiv.org/abs/2503.18813) separates a
privileged planner, which sees only the user's instruction, from a quarantined component
that processes untrusted data and can never influence *which* action runs. The critique
that "guardrails don't work" concedes exactly this design, and it is right to.

The taint tracker already covers half of it: an argument's *value* carries where it
came from, and a value from a retrieved document cannot reach an irreversible tool. This
module covers the other half, which taint cannot see: the **decision to call the tool at
all**.

That distinction matters because the dangerous injection does not always poison an
argument. It says "also send a copy to attacker@evil.example" — a *new step*, with entirely
clean arguments. Every value in that call can be legitimately user-sourced while the call
itself exists only because an attacker asked for it.

Two mechanisms, both deterministic, no model involved:

* **Declared plan.** The caller declares which tools the user's own instruction authorises.
  A tool outside that plan is off-plan, and is reported.
* **Attribution.** If an off-plan tool is *named or implied* by untrusted content the agent
  read, that is not drift, it is the injection working. It is reported at critical severity
  and is designed to be expressible as a policy rule.

Nothing here judges natural language. It compares a declared list against observed calls,
and looks for the tool's own identifiers inside untrusted text — the same discipline the
numeric integrity checkers use: narrow, deterministic, and silent when it has nothing to say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentfox.core.finding import RiskFinding

#: An untrusted surface's content can never be a legitimate source of tool selection.
UNTRUSTED_SELECTORS = {"retrieved", "tool_result", "subagent", "memory"}


@dataclass
class Plan:
    """What the *user's own instruction* authorises, declared before untrusted data is read.

    `tools` is the authorised set. An empty plan means "not declared", and this module then
    reports nothing rather than guessing — an undeclared plan is not evidence of an attack.
    """

    intent: str = ""
    tools: list[str] = field(default_factory=list)

    @property
    def declared(self) -> bool:
        return bool(self.tools)

    def authorises(self, tool_key: str) -> bool:
        if not self.declared:
            return True
        return any(_matches(pattern, tool_key) for pattern in self.tools)

    def to_json(self) -> dict[str, Any]:
        return {"intent": self.intent, "tools": list(self.tools)}


def _matches(pattern: str, tool_key: str) -> bool:
    """`payments.*` authorises `payments.refund`; exact keys otherwise."""
    if pattern == tool_key:
        return True
    if pattern.endswith("*"):
        return tool_key.startswith(pattern[:-1])
    return False


def _identifiers(tool_key: str) -> list[str]:
    """The strings that would give a tool away inside attacker text.

    `payments.transfer` yields "payments.transfer", "transfer", and "send money"-style
    synonyms only where they are unambiguous. Deliberately conservative: a false positive
    here accuses ordinary content of being an attack.
    """
    parts = [p for p in re.split(r"[.\-_/]", tool_key) if p]
    identifiers = {tool_key, tool_key.replace(".", " ")}
    if parts:
        verb = parts[-1]
        if len(verb) > 3:  # "get"/"add" are far too common to attribute anything to
            identifiers.add(verb)
            identifiers.add(verb.replace("_", " "))
    return sorted(identifiers)


def attributes_selection(tool_key: str, untrusted_texts: list[str]) -> str | None:
    """Return the untrusted excerpt that names this tool, if any."""
    identifiers = _identifiers(tool_key)
    for text in untrusted_texts or []:
        haystack = str(text or "").lower()
        if not haystack:
            continue
        for identifier in identifiers:
            needle = identifier.lower()
            if len(needle) < 4:
                continue
            if re.search(rf"(?<![\w.]){re.escape(needle)}(?![\w])", haystack):
                start = max(haystack.find(needle) - 40, 0)
                return str(text)[start : start + 160]
    return None


def check_selection(
    tool_key: str,
    *,
    plan: Plan | None = None,
    untrusted_texts: list[str] | None = None,
    selected_by: str = "user",
) -> RiskFinding | None:
    """Was this tool chosen by the user, or by something the agent read?

    Returns None when there is nothing to say — no declared plan and no untrusted
    attribution — because a checker that fires on absence of information is noise.
    """
    plan = plan or Plan()
    texts = untrusted_texts or []

    if selected_by in UNTRUSTED_SELECTORS:
        return RiskFinding(
            code="control_flow.selected_by_untrusted",
            detail=(
                f"the decision to call {tool_key} was attributed to {selected_by} content, "
                "not to the user's instruction"
            ),
            severity="critical",
            evidence={"tool": tool_key, "selected_by": selected_by, "plan": plan.to_json()},
        )

    if plan.authorises(tool_key):
        return None

    excerpt = attributes_selection(tool_key, texts)
    if excerpt is not None:
        return RiskFinding(
            code="control_flow.injected_step",
            detail=(
                f"{tool_key} is outside the declared plan and is named by untrusted content — "
                "the hallmark of an injected step, whatever its arguments contain"
            ),
            severity="critical",
            evidence={
                "tool": tool_key,
                "plan": plan.to_json(),
                "untrusted_excerpt": excerpt[:200],
            },
        )

    return RiskFinding(
        code="control_flow.off_plan",
        detail=f"{tool_key} is outside the plan declared for this task",
        severity="medium",
        evidence={"tool": tool_key, "plan": plan.to_json()},
    )


__all__ = ["Plan", "check_selection", "attributes_selection", "UNTRUSTED_SELECTORS"]
