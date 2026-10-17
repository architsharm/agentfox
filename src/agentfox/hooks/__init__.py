"""Hooks: the harness-neutral transport that runs AgentFox where the agent already is.

`protocol` is the wire, `daemon` is the warm process, and `client` is the thin thing a
harness spawns per tool call (`agentfox hooks run`). What any particular harness sends
and expects back — and whether a deny on a given event actually stops anything — is
its adapter's business, in `agentfox.harnesses`.
"""

from __future__ import annotations

from agentfox.hooks.client import (
    DaemonUnavailable,
    guard_content,
    guard_tool_call,
    ping,
    report_unavailable,
)
from agentfox.hooks.daemon import HookDaemon, warm
from agentfox.hooks.protocol import PROTOCOL_VERSION, ProtocolError, socket_path

__all__ = [
    "PROTOCOL_VERSION",
    "DaemonUnavailable",
    "HookDaemon",
    "ProtocolError",
    "guard_content",
    "guard_tool_call",
    "ping",
    "report_unavailable",
    "socket_path",
    "warm",
]
