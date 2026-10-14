"""The compliance tools for the MCP server (`agentfox serve mcp`)."""

from __future__ import annotations

from typing import Any


def mcp_tools(Tool: Any) -> dict[str, Any]:  # noqa: N803 - the core's Tool class
    from agentfox.apps.mcp_server import _opts, _string
    from agentfox_ee.compliance.frameworks import FRAMEWORK_TITLES

    tools = [
        Tool(
            "agentfox_compliance_status",
            "Compliance posture",
            "Shows control posture (effective, degraded, failing, not implemented), optionally "
            "for one framework. Mappings are engineering drafts, not legal advice.",
            {
                "framework": _string("Framework id.", enum=sorted(FRAMEWORK_TITLES)),
                "verbose": {"type": "boolean", "description": "List every control."},
            },
            argv=lambda a, s: [
                "report",
                "status",
                *_opts(a, framework="--framework", verbose="--verbose"),
            ],
        ),
        Tool(
            "agentfox_compliance_frameworks",
            "Compliance frameworks",
            "Lists supported frameworks with mapped-control coverage and review status.",
            argv=lambda a, s: ["report", "frameworks"],
        ),
    ]
    return {t.name: t for t in tools}
