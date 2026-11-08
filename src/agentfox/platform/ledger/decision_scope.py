"""How a recorded decision was scoped when it ran: which fired rules only watched.

Lives in the platform layer so the ledger (lists of runs) and containment findings
read a decision the same way without the ledger importing a capability.
"""

from __future__ import annotations

from typing import Any


def recorded_only(rule: dict[str, Any], scope: tuple[str, frozenset[str]]) -> bool:
    """Whether this rule only watched: its pack observes, or the caller let the call
    run past it (``scope``: auto() in observe mode, or a rule it exempts)."""
    in_process, exempt = scope
    if rule.get("mode", "enforce") == "observe":
        return True
    return in_process == "none" or str(rule.get("rule_id") or "") in exempt


def decision_scope(taint_summary: dict[str, Any] | None) -> tuple[str, frozenset[str]]:
    """The caller's in-process scope as the enforcer recorded it on the decision."""
    summary = taint_summary or {}
    return (
        str(summary.get("in_process") or "enforced"),
        frozenset(summary.get("exempt_rules") or ()),
    )
