"""Reads local AI coding-assistant session state — a signal static repo scanning
can't see. `discovery.py` finds agents *committed* to a repo; this finds agents a
developer is *actually running* right now, including ad hoc ones that never got
committed (a notebook agent, an MCP tool wired up an hour ago).

Structural metadata only, by a hard whitelist rather than a denylist: this module
reads exactly three things out of each session line — the turn's ``type``, the
model id off an assistant turn, and the ``name`` of any ``tool_use`` block. It never
touches a block's ``input`` (the tool call's arguments) or a text block's ``text``
(the actual conversation) — those keys are never read, so there's nothing to
accidentally leak. Nothing here makes a network call; scanning is the only thing
this module does, and the report is the caller's to keep or discard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SessionScanReport:
    tool_name: str
    root: Path
    found: bool
    sessions_found: int = 0
    sessions_parsed: int = 0
    parse_errors: int = 0
    tools_used: dict[str, int] = field(default_factory=dict)
    mcp_servers: set[str] = field(default_factory=set)
    models_seen: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)

    def to_json(self) -> dict:
        return {
            "tool": self.tool_name,
            "found": self.found,
            "sessions_found": self.sessions_found,
            "sessions_parsed": self.sessions_parsed,
            "tools_used": dict(sorted(self.tools_used.items(), key=lambda kv: -kv[1])),
            "mcp_servers": sorted(self.mcp_servers),
            "models_seen": sorted(self.models_seen),
            "project_count": len(self.projects),
        }


def _record_tool_use(name: object, report: SessionScanReport) -> None:
    if not isinstance(name, str) or not name:
        return
    report.tools_used[name] = report.tools_used.get(name, 0) + 1
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 2 and parts[1]:
            report.mcp_servers.add(parts[1])


def _scan_line(line: dict, report: SessionScanReport) -> None:
    """Whitelist extraction — only ``type``, ``message.model``, and
    ``message.content[].{type,name}`` are ever read from a session line."""
    if line.get("type") != "assistant":
        return
    message = line.get("message")
    if not isinstance(message, dict):
        return
    model = message.get("model")
    if isinstance(model, str) and model:
        report.models_seen.add(model)
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            _record_tool_use(block.get("name"), report)


def scan_claude_code(base: Path | None = None) -> SessionScanReport:
    """Scan Claude Code's local session transcripts (``~/.claude/projects/**/*.jsonl``).

    Each project gets its own subdirectory, named for the working directory the
    session ran in; each session is one JSONL file, one JSON object per line. Missing
    or empty is not an error — most machines running this scan won't have Claude Code
    installed, and that's a normal, reportable outcome, not a failure.
    """
    root = base if base is not None else Path.home() / ".claude" / "projects"
    report = SessionScanReport(tool_name="claude-code", root=root, found=root.is_dir())
    if not report.found:
        return report

    for session_file in sorted(root.glob("**/*.jsonl")):
        report.sessions_found += 1
        report.projects.add(session_file.parent.name)
        try:
            parsed_this_file = False
            with session_file.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        line = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(line, dict):
                        _scan_line(line, report)
                        parsed_this_file = True
            if parsed_this_file:
                report.sessions_parsed += 1
        except OSError:
            report.parse_errors += 1

    return report


#: Registry of session-scan backends. Claude Code's JSONL format is well-understood
#: (it's what's writing this very file); Copilot and Cursor store session state in
#: formats we haven't verified closely enough to parse safely, so they're left out
#: rather than guessed at.
SCANNERS = {"claude-code": scan_claude_code}


def scan_all(base_overrides: dict[str, Path] | None = None) -> list[SessionScanReport]:
    overrides = base_overrides or {}
    return [fn(overrides.get(name)) for name, fn in SCANNERS.items()]
