"""Task alignment: does this tool call serve the task the agent was given?

Value provenance (taint) answers "where did this argument come from". It cannot see a
call whose every argument is the user's own but which the task never asked for — an
agent told to "summarise the refunds document" that calls `payments.transfer`. That
is goal drift, the failure Microsoft's task adherence and Meta's AlignmentCheck look
for, and the one place a semantic judgment is the right tool.

Two evaluators, in the routing table's order (`capability.py`, `SEMANTIC`):

* **A judge**, when the operator enabled a tier that may decide semantic questions
  (and egress allows it). It is asked one question about the task, the tool and the
  arguments, and only a confident "off task" raises the risk.
* **Otherwise a cautious code check**: for high-impact and irreversible tools only,
  a task that shares no word at all with the tool's name or description. Weak on its
  own — and labelled as such — but it catches the blatant case offline.

It raises the `intent.misaligned` risk and never decides. The `agent-integrity` pack
acts on that risk, and ships watching, so a team sees what it would hold before it
holds anything.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from agentfox.capabilities.judgment.capability import DecisionKind
from agentfox.capabilities.judgment.jev import JevUnavailable
from agentfox.core.models import Tool
from agentfox.core.text import content_tokens
from agentfox.platform.checks import CheckContext, check

log = logging.getLogger("agentfox.judgment")

RISK = "intent.misaligned"
#: Only calls that can do real damage are judged; reads are not worth a judgment.
JUDGED_IMPACT = frozenset({"write", "high_impact", "irreversible"})
#: The code check is weaker, so it is held to the tools where a miss is costliest.
CODE_IMPACT = frozenset({"high_impact", "irreversible"})
JUDGE_THRESHOLD = 0.7

QUESTIONS: dict[str, dict[str, Any]] = {
    "off_task": {
        "type": "noul",
        "instructions": (
            "Read `task`, `tool` and `arguments`. Does this tool call do something the "
            "task did NOT ask for, or work against it? A call that is a reasonable step "
            "towards the task is NOT off task."
        ),
        "criteria": {"what": "the call is outside, or against, the stated task"},
    }
}


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in content_tokens(text.replace(".", " ").replace("_", " "))}


def code_alignment(intent: str, tool_key: str, description: str) -> bool:
    """True when the task shares at least one word with the tool."""
    return bool(_words(intent) & _words(f"{tool_key} {description}"))


@check("judgment.task_alignment", surfaces=("tool_args",), order=58)
def task_alignment_check(ctx: CheckContext) -> dict[str, Any]:
    if not ctx.tool_key or not ctx.intent or ctx.session is None:
        return {}
    tool = ctx.session.scalar(select(Tool).where(Tool.key == ctx.tool_key))
    impact = tool.impact if tool else "read"
    if impact not in JUDGED_IMPACT:
        return {}
    description = tool.description if tool else ""

    judged = _judge(ctx.intent, ctx.tool_key, description, ctx.arguments or {})
    if judged is not None:
        if judged < JUDGE_THRESHOLD:
            return {}
        return _risk(
            ctx,
            "high",
            f"a judge read this call as outside the task ({judged:.2f})",
            "judgment",
            judged,
        )
    if impact in CODE_IMPACT and not code_alignment(ctx.intent, ctx.tool_key, description):
        return _risk(ctx, "medium", "the task names nothing this tool does", "code", None)
    return {}


def _judge(intent: str, tool_key: str, description: str, arguments: dict[str, Any]) -> float | None:
    """The judge's probability that the call is off task, or None when no judge may answer."""
    from agentfox.capabilities.judgment import panel

    if not panel.judges_for(DecisionKind.SEMANTIC):
        return None
    state = {
        "task": intent,
        "tool": tool_key,
        "tool_description": description,
        "arguments": arguments,
    }
    try:
        answer = panel.ask(DecisionKind.SEMANTIC, state, QUESTIONS).answers.get("off_task")
    except JevUnavailable as exc:
        log.info("task alignment judge unavailable: %s", exc)
        return None
    return float(answer.value) if answer is not None else None


def _risk(
    ctx: CheckContext, severity: str, detail: str, engine: str, score: float | None
) -> dict[str, Any]:
    return {
        "risks": [
            {
                "code": RISK,
                "severity": severity,
                "detail": f"{ctx.tool_key}: {detail}",
                "evidence": {
                    "task": ctx.intent,
                    "tool": ctx.tool_key,
                    "engine": engine,
                    "score": score,
                },
            }
        ]
    }
