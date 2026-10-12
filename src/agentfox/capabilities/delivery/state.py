"""What the delivery policies remember about one agent session, between hook calls.

Each hook call is a fresh process, so the session's history lives in a small JSON
file named after the session id. Writes go to a temporary file first and are then
renamed into place, so a hook killed halfway leaves the previous state behind,
never a torn one. A file that cannot be read starts the session over: losing a
nudge is better than failing the agent's call.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass
class SessionState:
    #: Policy names whose eligibility test matched the task text.
    eligible: list[str] = field(default_factory=list)
    #: Facts read off the task text that refine a policy ("database", "credential").
    flags: list[str] = field(default_factory=list)
    #: Monotonic counter of tool calls that ran, so "after" has a meaning.
    seq: int = 0
    #: Named marks -> the ``seq`` at which they were last seen ("launch", "probe"…).
    marks: dict[str, int] = field(default_factory=dict)
    #: Policy name -> how many times it has intervened this session.
    nudges: dict[str, int] = field(default_factory=dict)

    def mark(self, name: str) -> None:
        self.marks[name] = self.seq

    def at(self, name: str) -> int:
        """The ``seq`` at which ``name`` was last marked, or 0 if never."""
        return self.marks.get(name, 0)

    def after(self, later: str, earlier: str) -> bool:
        """``later`` was marked after the last ``earlier``, and ``earlier`` happened."""
        return self.at(earlier) > 0 and self.at(later) > self.at(earlier)


def path_for(root: Path, session_id: str) -> Path:
    return root / f"{_SAFE_ID.sub('_', session_id or 'unknown')}.json"


def load(root: Path, session_id: str) -> SessionState:
    try:
        data: dict[str, Any] = json.loads(path_for(root, session_id).read_text())
        return SessionState(**{k: v for k, v in data.items() if k in SessionState.__annotations__})
    except (OSError, ValueError, TypeError):
        return SessionState()


def save(root: Path, session_id: str, state: SessionState) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        target = path_for(root, session_id)
        fd, tmp = tempfile.mkstemp(dir=root, prefix=".", suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(asdict(state), fh)
        os.replace(tmp, target)
    except OSError:
        pass  # a hook must never fail the agent's call over its own bookkeeping


__all__ = ["SessionState", "load", "path_for", "save"]
