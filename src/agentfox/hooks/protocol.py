"""The wire between the `agentfox hook` client and the `agentfoxd` daemon.

**Why a daemon exists at all.** A coding-agent harness runs its hook as a fresh
process per tool call. `import agentfox` pulls in SQLAlchemy, the detector
registry and — where the classifier extra is installed — transformers and
torch; that is seconds, not milliseconds, and it happens before a single
policy sees the command. A hook that costs two seconds is a hook the operator
removes. So the client stays thin and the work happens in a process that is
already warm: the database engine connected, the detector pipeline built, the
model weights resident.

This is the same shape a competitor arrived at, and their measurement is the
argument for it: 700ms of per-call runtime boot down to about 0.7ms once the
work moved behind a socket. The daemon is not an optimisation to add later. It
is the difference between a hook that ships and one that gets uninstalled.

**Transport.** One Unix domain socket, one connection per request, one frame
each way. No request-id multiplexing because there is never more than one
logical request in flight on a connection.

**Framing.** Four bytes of big-endian length, then that many bytes of UTF-8
JSON. A declared length over `MAX_FRAME` is refused before a buffer that size
is allocated, so a malformed or hostile length cannot make the daemon reserve
a gigabyte.

**Why not HTTP.** The gateway already speaks HTTP and this deliberately does
not. A localhost TCP port is reachable by every process on the machine and by
anything that can make the browser issue a request; a `0600` socket in a
`0700` directory is reachable by one user. The thing on the other end can turn
enforcement off, so the narrower door is the right one.
"""

from __future__ import annotations

import json
import os
import socket
import struct
from pathlib import Path
from typing import Any

#: Bumped when a field changes meaning. The daemon refuses a mismatch rather
#: than guessing, because a client and daemon that disagree about the shape of
#: a verdict is the failure mode where enforcement silently stops.
PROTOCOL_VERSION = 1

#: 4 MiB. A hook payload is a tool call and its arguments; the cap is headroom,
#: not an expected size.
MAX_FRAME = 4 * 1024 * 1024

_HEADER = struct.Struct(">I")

#: `sockaddr_un.sun_path` is 104 bytes on macOS and 108 on Linux, including the
#: terminator. Exceeding it fails at `bind` with a bare "AF_UNIX path too
#: long", which says nothing about which path or what to do — and the path is
#: derived from the state root, so a deep `AGENTFOX_STATE_DIR` hits this
#: through no fault of the operator's.
MAX_SOCKET_PATH = 100


class ProtocolError(RuntimeError):
    """The frame on the wire was not one we can act on."""


#: Names the daemon's socket outright. Only the socket moves: the database and
#: everything else stay under the state root.
SOCKET_ENV_VAR = "AGENTFOX_SOCKET"


def socket_path(state_root: Path | None = None) -> Path:
    """Where the daemon listens.

    ``AGENTFOX_SOCKET`` when it is set. Otherwise under the state root rather
    than `/tmp`: the state root is already the place this installation writes
    things only it should read, and a predictable path in a world-writable
    directory is how a socket gets pre-created by somebody else.

    When that path is too long for a Unix socket (a deep home or state
    directory), a short one in this user's own directory under the system temp
    directory, named for the state root so two installations never share one.
    The docs used to say to set ``AGENTFOX_STATE_DIR`` for this, which also
    moved the database out from under the hooks; nobody has to now.
    """
    override = os.environ.get(SOCKET_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if state_root is None:
        from agentfox.core.config import STATE_ROOT

        state_root = STATE_ROOT
    default = state_root / "run" / "agentfoxd.sock"
    if len(str(default).encode()) <= MAX_SOCKET_PATH:
        return default
    return short_socket_path(state_root)


def short_socket_path(state_root: Path) -> Path:
    """The fallback: ``<tmp>/agentfox-<uid>/<hash of the state root>.sock``. The
    directory is created 0700 and must be this user's (`daemon.ensure_run_dir`)."""
    import hashlib
    import tempfile

    tag = hashlib.sha256(str(state_root).encode()).hexdigest()[:12]
    user = os.getuid() if hasattr(os, "getuid") else "user"
    base = Path(tempfile.gettempdir())
    path = base / f"agentfox-{user}" / f"{tag}.sock"
    if len(str(path).encode()) > MAX_SOCKET_PATH:
        path = Path("/tmp") / f"agentfox-{user}" / f"{tag}.sock"
    return path


def check_socket_path(path: Path) -> None:
    """Refuse a path the kernel will not accept, and say what to do about it."""
    encoded = len(str(path).encode())
    if encoded > MAX_SOCKET_PATH:
        raise ProtocolError(
            f"the socket path is {encoded} bytes, over the ~{MAX_SOCKET_PATH} a Unix "
            f"socket allows:\n  {path}\n"
            f"Set {SOCKET_ENV_VAR} to a shorter path (only the socket moves), or pass --socket."
        )


def write_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ProtocolError(f"frame of {len(body)} bytes exceeds the {MAX_FRAME}-byte cap")
    sock.sendall(_HEADER.pack(len(body)) + body)


def read_frame(sock: socket.socket) -> dict[str, Any]:
    header = _recv_exactly(sock, _HEADER.size)
    (length,) = _HEADER.unpack(header)
    if length > MAX_FRAME:
        # Refused before allocating, which is the point of checking here
        # rather than after the read.
        raise ProtocolError(f"declared frame of {length} bytes exceeds the {MAX_FRAME}-byte cap")
    body = _recv_exactly(sock, length)
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"frame was not JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ProtocolError("frame was not a JSON object")
    return decoded


def _recv_exactly(sock: socket.socket, count: int) -> bytes:
    """Read exactly `count` bytes or raise.

    `recv` is allowed to return short, and a hook client that treats a short
    read as a whole frame reports a parse failure on a message that was simply
    still arriving — which, on this path, reads as "the guard is broken" and
    gets it switched off.
    """
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ProtocolError(
                f"connection closed with {remaining} of {count} bytes still expected"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
