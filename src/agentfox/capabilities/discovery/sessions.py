"""What a scan of local AI coding-assistant session state reports — a signal static
repo scanning can't see. `repo.py` finds agents *committed* to a repo; a session scan
finds agents a developer is *actually running* right now, including ad hoc ones that
never got committed (a notebook agent, an MCP tool wired up an hour ago).

Each harness reads its own transcript format (`HarnessAdapter.transcripts`, in
`agentfox.harnesses`); this module holds only the report they all fill in.

Structural metadata only, by a hard whitelist rather than a denylist: a scanner records
the turn's model, and the *name* of each tool used. It never records a tool call's
arguments or the conversation's text, so there is nothing to accidentally leak. Nothing
here makes a network call; the report is the caller's to keep or discard.
"""

from __future__ import annotations

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

    def record_tool(self, name: str, mcp_server: str | None = None) -> None:
        """Count one use of ``name``, and the MCP server it belongs to, if any."""
        self.tools_used[name] = self.tools_used.get(name, 0) + 1
        if mcp_server:
            self.mcp_servers.add(mcp_server)

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


__all__ = ["SessionScanReport"]
