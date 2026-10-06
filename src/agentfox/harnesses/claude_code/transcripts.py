"""Reads Claude Code's local session transcripts for the quickscan session report.

Structural metadata only, by a hard whitelist rather than a denylist: this module reads
exactly three things out of each session line — the turn's ``type``, the model id off
an assistant turn, and the ``name`` of any ``tool_use`` block. It never touches a
block's ``input`` (the tool call's arguments) or a text block's ``text`` (the actual
conversation) — those keys are never read, so there's nothing to accidentally leak.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentfox.capabilities.discovery.sessions import SessionScanReport
from agentfox.harnesses.claude_code.tools import mcp_server_of


def _record_tool_use(name: object, report: SessionScanReport) -> None:
    if not isinstance(name, str) or not name:
        return
    report.record_tool(name, mcp_server_of(name))


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


__all__ = ["scan_claude_code"]
