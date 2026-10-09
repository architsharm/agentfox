"""Where Codex reads its hooks, and how ``install`` merges ours into that file.

Codex reads hooks from a ``hooks.json`` beside each config layer's ``config.toml``
(``~/.codex/`` for the user, ``<repo>/.codex/`` for a project), and also from an inline
``[hooks]`` table in that ``config.toml``. When a layer has both, Codex merges them and
warns. ``install`` only ever writes ``hooks.json``: rewriting a TOML file the user
maintains by hand, comments and all, is how somebody's settings get clobbered. It does
*read* the inline table, so an event the user already wired to ``agentfox hooks run``
there is not wired a second time.

The ``hooks.json`` schema is Claude Code's: ``{"hooks": {<Event>: [{"matcher": ...,
"hooks": [{"type": "command", "command": ..., "timeout": <seconds>}]}]}}``. Codex
ignores the matcher on ``UserPromptSubmit``, so none is written there.

Install is a merge, never an overwrite: every key already in the file is kept, an event
that already runs our command is left alone, the previous file is kept as
``hooks.json.bak``, and a file that is not JSON is refused rather than replaced.

Codex has no per-user file inside a project (Claude Code's ``settings.local.json``), so
the ``local`` scope writes the project file too.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from agentfox.harnesses.base import (
    FileChange,
    InstallError,
    Scope,
    agents_in_hook_commands,
    hook_command,
)

#: The hooks file each install scope writes, relative to the project root.
HOOKS_FILE = ".codex/hooks.json"
#: The config file whose inline ``[hooks]`` table Codex also reads, in the same folder.
CONFIG_FILE = "config.toml"

#: Seconds Codex waits for the hook. Codex's own default is 600; the AgentFox client
#: gives up on the daemon after 4 and allows with a warning, so anything past that is
#: only headroom for process start.
TIMEOUT_S = 30

#: Shown in Codex's status line while the hook runs.
STATUS_MESSAGE = "AgentFox: checking"

#: Events whose matcher Codex ignores.
_NO_MATCHER = frozenset({"UserPromptSubmit", "Stop", "SessionEnd", "Interrupt"})


def codex_home() -> Path:
    """``$CODEX_HOME``, or ``~/.codex``."""
    env = os.environ.get("CODEX_HOME")
    return Path(env).expanduser() if env else Path.home() / ".codex"


def settings_path(root: Path, scope: Scope) -> Path:
    if scope == "user":
        return codex_home() / "hooks.json"
    return root / HOOKS_FILE


def hook_block(harness: str, agent: str, events: list[str]) -> dict[str, Any]:
    """The ``hooks`` block for ``events`` (native names, in the order they fire)."""
    handler = {
        "type": "command",
        "command": hook_command(harness, agent),
        "timeout": TIMEOUT_S,
        "statusMessage": STATUS_MESSAGE,
    }
    return {
        "hooks": {
            event: [
                {"hooks": [dict(handler)]}
                if event in _NO_MATCHER
                else {"matcher": "*", "hooks": [dict(handler)]}
            ]
            for event in events
        }
    }


def _inline_commands(config: Path) -> dict[str, str]:
    """Event -> the serialised inline ``[hooks]`` entries of a ``config.toml``.

    A config that cannot be read is treated as having none: ``install`` does not write
    it, so it has no business refusing because of it.
    """
    if not config.is_file():
        return {}
    try:
        data = tomllib.loads(config.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return {}
    return {event: json.dumps(entries) for event, entries in hooks.items()}


def merge(path: Path, harness: str, agent: str, events: list[str]) -> FileChange:
    """Our hooks merged into the ``hooks.json`` at ``path``. Idempotent."""
    command = hook_command(harness, agent)
    block = hook_block(harness, agent, events)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise InstallError(f"{path} is not valid JSON") from exc
        if not isinstance(existing, dict) or not isinstance(existing.get("hooks", {}), dict):
            raise InstallError(f"{path} is not a Codex hooks file (no `hooks` object)")
    inline = _inline_commands(path.parent / CONFIG_FILE)
    added = []
    for event, entries in block["hooks"].items():
        hooks = existing.setdefault("hooks", {}).setdefault(event, [])
        if not isinstance(hooks, list):
            raise InstallError(f"{path}: `hooks.{event}` is not a list")
        if any(command in json.dumps(entry) for entry in hooks):
            continue
        if command in inline.get(event, ""):
            continue
        hooks.extend(entries)
        added.append(event)
    return FileChange(
        path=path,
        content=json.dumps(existing, indent=2) + "\n",
        action="unchanged" if not added else ("update" if path.exists() else "create"),
        events=tuple(added),
        backup=True,
    )


def hooked_agents(root: Path) -> list[str]:
    """Agent slugs this project's Codex hooks govern, if any."""
    slugs: set[str] = set()
    folder = root / ".codex"
    for path in (folder / "hooks.json", folder / CONFIG_FILE):
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        slugs.update(agents_in_hook_commands(text))
    return sorted(slugs)


__all__ = [
    "CONFIG_FILE",
    "HOOKS_FILE",
    "STATUS_MESSAGE",
    "TIMEOUT_S",
    "codex_home",
    "hook_block",
    "hooked_agents",
    "merge",
    "settings_path",
]
