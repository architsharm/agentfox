"""Hooks: running AgentFox where the agent already is.

`protocol` is the wire, `daemon` is the warm process, `client` is the thin
thing a harness spawns per tool call, and `capability` records whether a deny
on a given harness event actually stops anything — empty until probed, because
an unverified claim about enforcement is the failure this package is built to
avoid.
"""

from __future__ import annotations

from agentfox.hooks.capability import CAPABILITY, Verified, capability_of, describe
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
    "CAPABILITY",
    "PROTOCOL_VERSION",
    "DaemonUnavailable",
    "HookDaemon",
    "ProtocolError",
    "Verified",
    "capability_of",
    "describe",
    "guard_content",
    "guard_tool_call",
    "ping",
    "report_unavailable",
    "socket_path",
    "warm",
]
