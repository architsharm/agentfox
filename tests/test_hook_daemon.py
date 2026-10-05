"""The warm daemon a harness hook talks to, and the thin client that talks to it.

A coding-agent harness spawns its hook as a fresh process per tool call.
`import agentfox` pulls in SQLAlchemy, the detector registry and — with the
classifier extra — transformers and torch. Measured on this machine against a
cold daemon: the first guarded call took 3,936ms. With `warm()` at startup,
122ms, then a p50 of 6.4ms. A hook that costs two seconds a call is a hook the
operator removes, so the daemon is not an optimisation to add later; it is the
difference between a hook that ships and one that gets uninstalled.

The load-bearing test in this file is `test_the_client_imports_nothing_heavy`.
Everything else here can be fixed after the fact. That one protects the
property the whole design rests on, and it is undone by a single convenient
import.
"""

from __future__ import annotations

import socket
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from agentfox.hooks import HookDaemon, ping
from agentfox.hooks.client import DaemonUnavailable, guard_tool_call, report_unavailable
from agentfox.hooks.daemon import ensure_run_dir
from agentfox.hooks.protocol import (
    MAX_FRAME,
    PROTOCOL_VERSION,
    ProtocolError,
    read_frame,
    write_frame,
)


@pytest.fixture
def short_dir():
    """A short directory, because `tmp_path` is not one.

    `sockaddr_un.sun_path` is about 100 bytes and pytest's tmp_path is
    routinely longer than that on its own — which is the constraint the
    product hit too, and `check_socket_path` now reports properly instead of
    letting `bind` say "AF_UNIX path too long" and nothing else.
    """
    with tempfile.TemporaryDirectory(prefix="afx", dir="/tmp") as name:
        yield Path(name)


@pytest.fixture
def running(short_dir):
    """A daemon on a socket of this test's own, stopped afterwards."""
    daemon = HookDaemon(short_dir / "run" / "d.sock")
    daemon.start()
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    assert daemon.ready.wait(5)
    yield daemon
    daemon.stop()
    thread.join(timeout=3)


# ---------------------------------------------------------------------------
# The property the design rests on
# ---------------------------------------------------------------------------


def test_the_client_imports_nothing_heavy():
    """The client runs once per tool call, in a process the harness creates
    and destroys. If it drags in the ORM or torch, the daemon has bought
    nothing and the hook costs seconds again.

    A subprocess, because importing them here would already have loaded them
    into this interpreter and the check would pass for the wrong reason.
    """
    source = (
        "import sys; import agentfox.hooks.client as c; "
        "heavy = [m for m in ('sqlalchemy','torch','transformers','agentfox.runtime.enforcement',"
        "'agentfox.detection') if m in sys.modules]; "
        "print(','.join(heavy))"
    )
    out = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", f"the hook client pulled in {out.stdout.strip()}"


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


def test_a_frame_round_trips(tmp_path):
    left, right = socket.socketpair()
    write_frame(left, {"type": "ping", "protocolVersion": PROTOCOL_VERSION})
    assert read_frame(right) == {"type": "ping", "protocolVersion": PROTOCOL_VERSION}


def test_an_oversized_declared_length_is_refused_before_allocating():
    """The reason the cap is checked against the header rather than the body:
    otherwise a four-byte lie makes the daemon reserve a gigabyte."""
    left, right = socket.socketpair()
    left.sendall(struct.pack(">I", MAX_FRAME + 1))
    with pytest.raises(ProtocolError, match="exceeds"):
        read_frame(right)


def test_a_short_read_is_not_mistaken_for_a_whole_frame():
    """`recv` may return short. Treating that as the frame reports a parse
    failure on a message that was still arriving — which on this path reads as
    'the guard is broken' and gets it switched off."""
    left, right = socket.socketpair()
    body = b'{"type":"ping"}'
    left.sendall(struct.pack(">I", len(body)) + body[:5])
    left.close()
    with pytest.raises(ProtocolError, match="still expected"):
        read_frame(right)


def test_a_frame_that_is_not_an_object_is_refused():
    left, right = socket.socketpair()
    body = b"[1, 2, 3]"
    left.sendall(struct.pack(">I", len(body)) + body)
    with pytest.raises(ProtocolError, match="not a JSON object"):
        read_frame(right)


# ---------------------------------------------------------------------------
# The socket itself
# ---------------------------------------------------------------------------


def test_the_socket_is_private(running):
    """The thing on the other end can turn enforcement off, so the door is
    narrow: 0600 inside a 0700 directory, and never a localhost TCP port every
    process on the machine can reach."""
    assert running.path.stat().st_mode & 0o777 == 0o600
    assert running.path.parent.stat().st_mode & 0o777 == 0o700


def test_a_run_directory_we_did_not_create_is_refused(tmp_path):
    """Widening or narrowing somebody else's directory would paper over the
    fact that somebody else can put a socket in it."""
    directory = tmp_path / "theirs"
    directory.mkdir(mode=0o755)
    with pytest.raises(PermissionError, match="0700"):
        ensure_run_dir(directory / "d.sock")


def test_a_stale_socket_file_is_replaced(short_dir):
    """Left by a process that died. Connecting is the only way to tell that
    from one that is alive."""
    import stat

    path = short_dir / "run" / "d.sock"
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text("")  # not a socket, just a leftover file
    assert not stat.S_ISSOCK(path.stat().st_mode)

    daemon = HookDaemon(path)
    daemon.start()
    try:
        # `start()` binds and listens; it does not accept. Pinging here would
        # connect to the backlog and then time out waiting for a reply nobody
        # is serving, which says nothing about whether the stale file was
        # cleared. What this test is about is that it was.
        assert stat.S_ISSOCK(path.stat().st_mode)
    finally:
        daemon.stop()


def test_a_second_daemon_will_not_take_a_live_socket(running):
    with pytest.raises(RuntimeError, match="already listening"):
        HookDaemon(running.path).start()


def test_stopping_removes_the_socket(short_dir):
    daemon = HookDaemon(short_dir / "run" / "d.sock")
    daemon.start()
    assert daemon.path.exists()
    daemon.stop()
    assert not daemon.path.exists()


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def test_ping_answers(running):
    assert ping(running.path) is True


def test_a_protocol_mismatch_is_refused_not_guessed(running):
    """A client and daemon that disagree about the shape of a verdict is how
    enforcement stops silently."""
    reply = running.handle({"type": "ping", "protocolVersion": PROTOCOL_VERSION + 1})
    assert reply["type"] == "error"
    assert "different versions" in reply["error"]


def test_an_unknown_request_type_is_refused(running):
    reply = running.handle({"type": "nonsense", "protocolVersion": PROTOCOL_VERSION})
    assert reply["type"] == "error"


def test_a_hook_with_no_agent_is_refused(running):
    reply = running.handle({"type": "hook", "protocolVersion": PROTOCOL_VERSION, "tool": "x"})
    assert reply["type"] == "error" and "agent" in reply["error"]


def test_a_verdict_comes_back_over_the_socket(seeded, running):
    """The whole point, end to end: a real enforcement decision, over a real
    socket, from a process that did not import anything to serve it."""
    from agentfox.identity import ensure_identity, grant_capability
    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    grant_capability(seeded, ensure_identity(seeded, agent), "shell.run", max_taint="tool_result")
    seeded.commit()

    reply = guard_tool_call(
        agent="support-triage",
        tool="shell.run",
        arguments={"command": "agentfox policy observe baseline"},
        path=running.path,
    )
    assert reply["verdict"] == "block"
    assert "control_plane.tamper" in reply["rules"]
    assert isinstance(reply["daemonMs"], float)


# ---------------------------------------------------------------------------
# When it is not there
# ---------------------------------------------------------------------------


def test_a_missing_daemon_raises_rather_than_deciding(tmp_path):
    """The client does not get to decide the verdict. It says it could not
    ask, and the caller chooses — which is a decision worth making once, in
    one place, rather than implicitly here."""
    with pytest.raises(DaemonUnavailable, match="agentfox daemon"):
        guard_tool_call(agent="a", tool="t", arguments={}, path=tmp_path / "nothing.sock")


def test_ping_reports_false_rather_than_raising(tmp_path):
    assert ping(tmp_path / "nothing.sock") is False


def test_the_gap_is_reported_as_a_gap(capsys):
    """The one thing this must never do is nothing. A control that stops
    reporting is worse than one that was never installed."""
    report_unavailable(DaemonUnavailable("socket missing"))
    err = capsys.readouterr().err
    assert "NOT checked" in err
    assert "Nothing was blocked and nothing was recorded" in err


# ---------------------------------------------------------------------------
# What we will not claim
# ---------------------------------------------------------------------------


def test_the_capability_table_never_claims_block_for_an_unprobed_event():
    """ABSENT MEANS UNVERIFIED. A hedge rendered as a capability is still a
    claim, and an unverified claim about enforcement is what that table exists
    to prevent.

    Uses cursor rather than claude: claude/PreToolUse has since been probed
    live, and this test failing when that happened is the table working — the
    assertion has to move to a harness nobody has checked, not be relaxed.
    """
    from agentfox.hooks import capability_of, describe

    assert capability_of("cursor", "PreToolUse") is None
    text = describe("cursor", "PreToolUse")
    assert text.startswith("cursor/PreToolUse: unverified")
    # It may mention blocking — it says the question is open — but it must
    # never assert the affirmative.
    assert "a deny stops the call (" not in text
    assert "treat it as observation" in text


def test_a_socket_path_the_kernel_will_not_accept_says_so(tmp_path):
    """`bind` fails with "AF_UNIX path too long" and names neither the path
    nor the fix. The state root is where this path comes from, so a deep
    AGENTFOX_STATE_DIR hits it through no fault of the operator's — and
    pytest's own tmp_path is long enough to hit it, which is how this was
    found."""
    from agentfox.hooks.protocol import check_socket_path

    with pytest.raises(ProtocolError) as excinfo:
        check_socket_path(Path("/" + "d" * 120) / "agentfoxd.sock")
    assert "AGENTFOX_STATE_DIR" in str(excinfo.value)
