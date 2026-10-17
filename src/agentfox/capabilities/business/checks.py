"""The business-ladder check the runtime runs on a tool call.

A `ladder` check (`platform/checks.py`): it returns the ladder decisions that apply to
the call rather than ``{evidence_issues, risks}``, because a ladder composes with the
policy verdict by selecting exactly one band, not by lattice maximum. The runtime
combines them in `Enforcer._apply_ladders`.
"""

from __future__ import annotations

import logging

from agentfox.capabilities.business.graph import BUSINESS_RANK
from agentfox.capabilities.business.ladder import LadderDecision
from agentfox.capabilities.business.ladder import evaluate as evaluate_ladder
from agentfox.capabilities.business.store import load_ladders
from agentfox.platform.checks import CheckContext, check

log = logging.getLogger("agentfox.runtime.enforcement")


@check("business.ladders", kind="ladder", surfaces=("tool_args",), order=10)
def ladder_check(ctx: CheckContext) -> list[LadderDecision]:
    """Evaluate the business ladders that apply to this call.

    Only on the tool-argument surface: a ladder bands a number the caller is about
    to act on, and there is no such number on an input or an output. When several
    apply, the strictest wins and the disagreement is a lint finding rather than a
    silent precedence rule — two authors disagreeing is a fact about the
    organisation, not a merge conflict.

    Every deciding ladder is returned, strictest first, because each carries its
    own mode: the strictest *enforcing* ladder is what is applied, and an
    observe ladder stricter than it is only recorded.
    """
    surface, tool_key, arguments, agent = ctx.surface, ctx.tool_key, ctx.arguments, ctx.agent
    if surface != "tool_args" or not arguments:
        return []
    try:
        ladders = load_ladders(ctx.session, tool=tool_key, agent_id=agent.id if agent else None)
    except Exception as exc:  # pragma: no cover - storage must not break the path
        log.warning("business ladders unavailable: %s", exc)
        return []
    if not ladders:
        return []

    request = {"arguments": arguments, "tool": tool_key}
    decisions = [
        evaluate_ladder(ladder, request) for ladder in ladders if ladder.tool in (None, tool_key)
    ]
    decisions = [d for d in decisions if d.matched or d.undecidable]
    return sorted(decisions, key=lambda d: BUSINESS_RANK.get(d.outcome, 0), reverse=True)
