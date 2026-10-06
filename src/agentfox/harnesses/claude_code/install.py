"""Where Claude Code reads its hooks, and how ``install`` merges ours into that file.

The settings schema, read off Claude Code 2.1.220: ``{"hooks": {<Event>: [<entry>]}}``,
where an entry is ``{"matcher": <tool filter>, "hooks": [{"type": "command",
"command": ...}]}``. ``matcher`` is a tool-name filter and the two non-tool events do
not take one.

Install is a merge, never an overwrite: every key already in the file is kept, an
event that already runs our command is left alone, and a file that is not JSON is
refused rather than replaced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentfox.harnesses.base import (
    FileChange,
    InstallError,
    Scope,
    agents_in_hook_commands,
    hook_command,
)

#: The settings file each install scope writes, relative to the project root (or to
#: the home directory for ``user``).
SETTINGS: dict[str, str] = {
    "project": ".claude/settings.json",
    "local": ".claude/settings.local.json",
    "user": ".claude/settings.json",
}

#: The files ``install`` may have written in a project, which ``hooked_agents`` reads.
HOOK_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")


def settings_path(root: Path, scope: Scope) -> Path:
    base = Path.home() if scope == "user" else root
    return base / SETTINGS[scope]


def hook_block(harness: str, agent: str, events: list[str]) -> dict[str, Any]:
    """The ``hooks`` block for ``events`` (native names, in the order they fire)."""
    command = hook_command(harness, agent)
    return {
        "hooks": {
            event: [
                {"matcher": "*", "hooks": [{"type": "command", "command": command}]}
                if event.endswith("ToolUse")
                else {"hooks": [{"type": "command", "command": command}]}
            ]
            for event in events
        }
    }


def merge(path: Path, harness: str, agent: str, events: list[str]) -> FileChange:
    """Our hooks merged into the settings file at ``path``. Idempotent."""
    command = hook_command(harness, agent)
    block = hook_block(harness, agent, events)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise InstallError(f"{path} is not valid JSON") from exc
    added = []
    for event, entries in block["hooks"].items():
        hooks = existing.setdefault("hooks", {}).setdefault(event, [])
        if any(command in json.dumps(entry) for entry in hooks):
            continue
        hooks.extend(entries)
        added.append(event)
    return FileChange(
        path=path,
        content=json.dumps(existing, indent=2) + "\n",
        action="unchanged" if not added else ("update" if path.exists() else "create"),
        events=tuple(added),
    )


def hooked_agents(root: Path) -> list[str]:
    """Agent slugs this project's Claude Code hooks govern, if any."""
    slugs: set[str] = set()
    for rel in HOOK_SETTINGS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        slugs.update(agents_in_hook_commands(text))
    return sorted(slugs)


__all__ = ["HOOK_SETTINGS", "SETTINGS", "hook_block", "hooked_agents", "merge", "settings_path"]
