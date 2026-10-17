"""The warm process a hook talks to.

One thread per connection, one frame each way, and an `Enforcer` built per
request against a session from the pool the daemon already holds open. What
stays warm is the expensive part: the engine, the detector registry, and the
model weights `warm_all()` loads at startup rather than on somebody's first
tool call.

Deliberately simple concurrency. A hook is a blocking call in the agent's own
critical path, so the work is short by construction, and a thread per
connection is both easier to reason about and easier to shut down than an
event loop we would then have to keep the ORM happy inside.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

from agentfox.hooks.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    check_socket_path,
    read_frame,
    socket_path,
    write_frame,
)

log = logging.getLogger(__name__)

#: A hook blocks the agent. If the daemon cannot answer in this long, the
#: client stops waiting and says so rather than hanging the agent — see
#: `client.py`, which owns the other half of this number.
DEFAULT_TIMEOUT_S = 5.0

#: Where content on a surface came from, when the caller does not say. A tool
#: result is third-party content arriving as context — the canonical indirect
#: injection vector — and calling it `user` would let it inherit the trust of
#: something the operator typed.
_TAINT_FOR_SURFACE = {
    "tool_result": "tool_result",
    "retrieved": "retrieved",
    "agent_message": "subagent",
    "memory_write": "memory",
    "reasoning": "tool_result",
}


def ensure_run_dir(path: Path) -> Path:
    """Create the socket's directory at 0700, and refuse to adopt one we did not make.

    A run directory somebody else created, with permissions we did not set, is
    a directory somebody else can put a socket in. Chmod-ing it for them would
    paper over that, so a pre-existing directory that is not ours and not 0700
    is an error rather than something to fix silently.
    """
    directory = path.parent
    if directory.exists():
        mode = directory.stat().st_mode & 0o777
        if mode != 0o700:
            raise PermissionError(
                f"{directory} exists with mode {mode:o}, not 0700. AgentFox will not widen "
                "or narrow a directory it did not create — move it aside, or point "
                "AGENTFOX_STATE_DIR somewhere this process owns."
            )
        return directory
    directory.mkdir(parents=True, mode=0o700)
    return directory


class HookDaemon:
    """Serves hook verdicts over a Unix socket."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or socket_path()
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        #: Set once the listener is bound, so a caller (and the tests) can wait
        #: for readiness instead of sleeping and hoping.
        self.ready = threading.Event()
        self.served = 0

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        check_socket_path(self.path)
        ensure_run_dir(self.path)
        if self.path.exists():
            # A socket file left by a process that died. Connecting to it is
            # the only way to tell that from one that is alive.
            if self._alive():
                raise RuntimeError(f"a daemon is already listening on {self.path}")
            self.path.unlink()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.path))
        # After bind, before listen: there is no window in which the socket
        # exists and is world-readable.
        os.chmod(self.path, 0o600)
        sock.listen(16)
        sock.settimeout(0.2)
        self._sock = sock
        self.ready.set()

    def _alive(self) -> bool:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect(str(self.path))
            write_frame(probe, {"type": "ping", "protocolVersion": PROTOCOL_VERSION})
            return read_frame(probe).get("type") == "pong"
        except (OSError, ProtocolError):
            return False
        finally:
            probe.close()

    def serve_forever(self) -> None:
        if self._sock is None:
            self.start()
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            thread = threading.Thread(target=self._serve_one, args=(conn,), daemon=True)
            thread.start()
            self._threads.append(thread)
            self._threads = [t for t in self._threads if t.is_alive()]

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self.path.unlink(missing_ok=True)

    # --- one request ------------------------------------------------------

    def _serve_one(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(DEFAULT_TIMEOUT_S)
            request = read_frame(conn)
            response = self.handle(request)
        except ProtocolError as exc:
            response = {"type": "error", "error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("hook daemon failed to serve a request")
            response = {"type": "error", "error": f"{type(exc).__name__}: {exc}"}
        try:
            write_frame(conn, response)
        except OSError:
            pass  # the client gave up; nothing to say to a closed socket
        finally:
            conn.close()
            self.served += 1

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """Answer one request. Pure enough to call directly from a test."""
        version = request.get("protocolVersion")
        if version != PROTOCOL_VERSION:
            # Refused rather than guessed: a client and daemon that disagree
            # about the shape of a verdict is how enforcement stops silently.
            return {
                "type": "error",
                "error": (
                    f"protocol version {version!r} is not {PROTOCOL_VERSION}; "
                    "the client and daemon are different versions of agentfox"
                ),
            }

        kind = request.get("type")
        if kind == "ping":
            return {"type": "pong", "protocolVersion": PROTOCOL_VERSION}
        if kind == "hook":
            return self._hook(request)
        if kind == "content":
            return self._content(request)
        return {"type": "error", "error": f"unknown request type {kind!r}"}

    @staticmethod
    def _verdict_payload(result: Any) -> dict[str, Any]:
        """One shape for every kind of request, so a client parses one thing."""
        return {
            "type": "verdict",
            "protocolVersion": PROTOCOL_VERSION,
            "verdict": result.verdict,
            "effectiveVerdict": result.effective_verdict,
            "mode": result.mode,
            "reason": result.reason,
            "rules": [r.get("rule_id") for r in result.rules_fired],
            "decisionId": result.decision_id,
            "degraded": list(result.degraded),
        }

    def _hook(self, request: dict[str, Any]) -> dict[str, Any]:
        from agentfox.core.db import session_scope
        from agentfox.runtime.enforcement import Enforcer

        started = time.perf_counter()
        agent = str(request.get("agent") or "")
        tool = request.get("tool")
        arguments = request.get("arguments") or {}

        if not agent:
            return {"type": "error", "error": "no agent named in the request"}

        with session_scope() as session:
            result = Enforcer(session).guard_tool_call(
                agent_slug=agent,
                tool_key=str(tool or ""),
                arguments=arguments if isinstance(arguments, dict) else {"value": arguments},
            )
            payload = self._verdict_payload(result)
        payload["daemonMs"] = round((time.perf_counter() - started) * 1000, 2)
        return payload

    def _content(self, request: dict[str, Any]) -> dict[str, Any]:
        """A surface carrying text rather than a call: a tool result, a turn.

        The same `Enforcer`, the same policy set, the same decision record —
        the only thing that changes is which surface the rules see. That is
        the point: a hook on `PostToolUse` is not a second product with its
        own rules, it is the existing engine bound at another moment.
        """
        from agentfox.core.db import session_scope
        from agentfox.core.vocab import SURFACES
        from agentfox.runtime.enforcement import Enforcer

        started = time.perf_counter()
        agent = str(request.get("agent") or "")
        surface = str(request.get("surface") or "input")
        content = request.get("content")

        if not agent:
            return {"type": "error", "error": "no agent named in the request"}
        if surface not in SURFACES:
            # Refused rather than coerced to a default. A surface the engine
            # does not know would be evaluated under whichever rules happened
            # to have no surface filter, which is enforcement by accident.
            return {
                "type": "error",
                "error": f"unknown surface {surface!r}; known: {', '.join(SURFACES)}",
            }

        with session_scope() as session:
            # `resolve` then `evaluate`, the same two steps every named guard
            # takes. Not `check_content`, which returns already-serialised JSON
            # and would make this the one request kind whose reply is built
            # differently from the others.
            enforcer = Enforcer(session)
            resolved, identity, _ = enforcer.resolve(agent)
            result = enforcer.evaluate(
                agent=resolved,
                identity=identity,
                content=content if isinstance(content, str) else str(content or ""),
                surface=surface,
                taint_source=str(request.get("taint") or _TAINT_FOR_SURFACE.get(surface, "user")),
                tool_key=str(request.get("tool") or "") or None,
            )
            payload = self._verdict_payload(result)
        payload["daemonMs"] = round((time.perf_counter() - started) * 1000, 2)
        return payload


def warm() -> None:
    """Pay the startup costs before the first request rather than during it."""
    from agentfox.capabilities.detection import warm_all
    from agentfox.core.db import init_db

    init_db()
    warm_all()
