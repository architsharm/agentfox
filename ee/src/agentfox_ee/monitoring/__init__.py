"""Monitoring connected sources: AgentFox re-checks what it was connected to, unattended.
Part of AgentFox Enterprise (BSL 1.1, see ee/LICENSE).

A `Monitor` (one GitHub repository, hosted-API spec, MCP server or deployed agent) is
created when the source is connected and scanned (the open core asks for it through the
``monitors.ensure`` service), or by hand (`/api/monitors`, `agentfox scan monitors`).
The `monitors.run` job runs every due monitor: it re-reads the source, diffs it against
the previous run, raises findings for what appeared and closes the ones that cleared. A
GitHub push webhook queues an immediate rescan (``monitors.request_run``).
"""

from __future__ import annotations

SCHEDULES = (
    {
        "kind": "monitors.run",
        "interval_seconds": 10 * 60,
        "enabled": True,
        "payload": {},
        "why": "re-check connected sources whose own interval has passed",
    },
)
