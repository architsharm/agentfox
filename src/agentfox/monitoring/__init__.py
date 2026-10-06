"""Monitoring connected sources: AgentFox re-checks what it was connected to, unattended.

A `Monitor` (one GitHub repository, hosted-API spec or MCP server) is created when the
source is connected and scanned, or by hand (`/api/monitors`, `agentfox scan monitors`).
The `monitors.run` job runs every due monitor: it re-reads the source, diffs it against
the previous run, raises findings for what appeared and closes the ones that cleared.
A GitHub push webhook queues an immediate rescan.

Public surface:

* `service.ensure_monitor`, `service.run_monitor`, `service.run_due`,
  `service.request_run`, `service.monitor_json` — create, run, queue, serialise;
* `service.register_kind` — add a kind of source (a runner returning a `RunOutcome`);
* `service.raise_condition` / `service.reconcile` with `snapshots.Condition` and
  `snapshots.Diff` — turn observations into deduplicated, self-closing findings;
* `alerts.queue_finding_alert` — the Slack message for a finding, sent after commit.
"""

from __future__ import annotations

from agentfox.monitoring.service import (
    JOB_KIND,
    MonitorError,
    RunContext,
    RunOutcome,
    ensure_monitor,
    kinds,
    monitor_json,
    raise_condition,
    reconcile,
    register_kind,
    request_run,
    run_due,
    run_monitor,
)
from agentfox.monitoring.snapshots import Condition, Diff

__all__ = [
    "JOB_KIND",
    "Condition",
    "Diff",
    "MonitorError",
    "RunContext",
    "RunOutcome",
    "ensure_monitor",
    "kinds",
    "monitor_json",
    "raise_condition",
    "reconcile",
    "register_kind",
    "request_run",
    "run_due",
    "run_monitor",
]
