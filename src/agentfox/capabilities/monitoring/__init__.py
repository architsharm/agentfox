"""Reading a connected source: GitHub repository downloads and webhook signatures
(`github`), and the snapshot a scan leaves behind (`snapshots`), so the next look can
be diffed against it.

Re-checking connected sources on a schedule (monitors, their findings and Slack alerts)
is AgentFox Enterprise (`agentfox_ee.monitoring`).
"""

from __future__ import annotations

from agentfox.capabilities.monitoring.snapshots import Condition, Diff

__all__ = ["Condition", "Diff"]
