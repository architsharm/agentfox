"""The thin half: what the harness actually spawns.

Everything here happens in a process the harness creates and destroys per tool
call, so the cost of this module is paid on every call the agent makes. It
imports `socket`, `json` and `struct` and nothing of AgentFox's own beyond the
frame helpers — no SQLAlchemy, no detector registry, no torch. That restraint
is the entire reason the daemon exists, and it is easy to undo by accident:
one convenient import of `..enforcement` here and the hook costs seconds
again.

**What happens when the daemon is not there** is the decision this file turns
on. The honest answer for a governance product would be to fail closed and
block the call. The honest answer for something wired into somebody's editor
is that a guard which bricks their agent when a background process is down
gets uninstalled within the hour, and an uninstalled guard enforces nothing at
all.

So: it reports, loudly, on stderr where the harness shows it, and does not
block — and the gap is recorded as a gap rather than passed off as an allow.
That is the same choice `availability.py` makes for a detector that times out,
with the same caveat: this is the hook path, not the enforcement boundary. An
agent whose only control is a hook on its own machine has one control, and
`agentfox hooks install` says so.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any

from agentfox.hooks.protocol import PROTOCOL_VERSION, ProtocolError, read_frame, socket_path, write_frame

#: The client's half of the daemon's timeout. Shorter, so the client is the one
#: that gives up: if both waited the same length the agent would sometimes see
#: a closed socket rather than a message it can explain.
TIMEOUT_S = 4.0


class DaemonUnavailable(RuntimeError):
    """The daemon is not listening, or did not answer in time."""


def ask(payload: dict[str, Any], *, path: Path | None = None, timeout: float = TIMEOUT_S) -> dict:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    target = path or socket_path()
    try:
        sock.connect(str(target))
    except OSError as exc:
        raise DaemonUnavailable(
            f"no AgentFox daemon at {target} ({exc.strerror or exc}). Start one with "
            "`agentfox daemon`."
        ) from exc
    try:
        write_frame(sock, payload)
        return read_frame(sock)
    except (OSError, ProtocolError) as exc:
        raise DaemonUnavailable(f"the daemon did not answer: {exc}") from exc
    finally:
        sock.close()


def ping(path: Path | None = None) -> bool:
    try:
        reply = ask({"type": "ping", "protocolVersion": PROTOCOL_VERSION}, path=path, timeout=1.0)
    except DaemonUnavailable:
        return False
    return reply.get("type") == "pong"


def guard_tool_call(
    *, agent: str, tool: str, arguments: dict[str, Any], path: Path | None = None
) -> dict[str, Any]:
    """Ask for a verdict. Raises `DaemonUnavailable` rather than deciding."""
    reply = ask(
        {
            "type": "hook",
            "protocolVersion": PROTOCOL_VERSION,
            "agent": agent,
            "tool": tool,
            "arguments": arguments,
        },
        path=path,
    )
    if reply.get("type") == "error":
        raise DaemonUnavailable(str(reply.get("error")))
    return reply


def guard_content(
    *,
    agent: str,
    surface: str,
    content: str,
    tool: str = "",
    taint: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Ask for a verdict on text arriving at a surface. Same daemon, same policy.

    The second and third hook events do not carry a call to authorise — they
    carry a tool's result, or the operator's own turn — so they ask a
    different question of the same engine rather than going somewhere else.
    """
    reply = ask(
        {
            "type": "content",
            "protocolVersion": PROTOCOL_VERSION,
            "agent": agent,
            "surface": surface,
            "content": content,
            "tool": tool,
            "taint": taint,
        },
        path=path,
    )
    if reply.get("type") == "error":
        raise DaemonUnavailable(str(reply.get("error")))
    return reply


def report_unavailable(exc: Exception) -> None:
    """Say it where the operator will see it, and say what it means.

    Not a silent pass. The whole argument of this product is that a control
    which stops reporting is worse than one that was never installed, so the
    one thing this must never do is nothing.
    """
    print(
        f"agentfox: hook could not reach the daemon — {exc}\n"
        "agentfox: this tool call was NOT checked. Nothing was blocked and nothing "
        "was recorded.",
        file=sys.stderr,
    )
