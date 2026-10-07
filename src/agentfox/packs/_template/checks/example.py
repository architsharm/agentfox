"""An optional request-path check, registered by decorator (delete it if unneeded).

A check reads one call's `CheckContext` and returns ``{evidence_issues, risks, …}``.
Risks join ``action["risks"]``, so a policy rule matches them with ``action_risk``;
nothing a check returns sets a verdict by itself. It may import only
``agentfox.core``, ``agentfox.platform`` and ``agentfox.capabilities``.
"""

from __future__ import annotations

from typing import Any

from agentfox.platform.checks import CheckContext, check


@check("__NAME__.example", surfaces=["output"], order=1000)
def example_check(ctx: CheckContext) -> dict[str, Any]:
    """Flags an answer that mentions the example marker."""
    if "__EXAMPLE_MARKER__" not in (ctx.content or ""):
        return {}
    return {
        "risks": [
            {
                "code": "__NAME__.example_marker",
                "severity": "medium",
                "detail": "the answer contains the example marker",
            }
        ]
    }
