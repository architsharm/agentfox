"""Claude Code's own tools: what each is called in AgentFox's vocabulary, and what it can do.

These are not the operator's inventory — they are the harness's, fixed by the product
the agent runs in, and an operator should not have to declare `Bash` before a hook is
useful. Without them every call trips `tool.not_declared` and the reason the agent
reads is "the registry has never seen this tool" no matter what the call actually was,
which buries the control that mattered. Found immediately on the first end-to-end run.
"""

from __future__ import annotations

#: Native tool name -> declared impact. ``install`` declares and grants these.
#:
#: The impacts are the point. `Bash` is not irreversible even though it can be `rm
#: -rf`; `Read` and `Grep` are reads; `Task` is high impact because it spawns an agent
#: that has its own tools. Getting these right is what makes the containment rules —
#: which reason over `tool_impact` — mean anything at a hook.
TOOL_IMPACTS: dict[str, str] = {
    # `write`, not `irreversible`, and the distinction is the whole reason this
    # product parses actions. A shell tool has no fixed impact: `ls -la` is a read and
    # `rm -rf /` is catastrophic, and declaring the tool at its worst case made
    # `intent.undeclared_irreversible` fire on every command the agent ran — found on
    # the first end-to-end run, where `git status` was refused.
    #
    # The tool-level impact is the floor. `analyse_shell` supplies the ceiling per
    # command, which is what `action_risk` and `action_operation` exist for: `rm -rf`
    # still reaches `shell.destructive`, `terraform apply` still reaches
    # `infrastructure-mutation`, and `ls` reaches neither.
    "Bash": "write",
    "BashOutput": "read",
    "KillShell": "write",
    "Write": "write",
    "Edit": "write",
    "NotebookEdit": "write",
    "Read": "read",
    "Glob": "read",
    "Grep": "read",
    "WebFetch": "read",
    "WebSearch": "read",
    # Spawns an agent with its own tools, so its blast radius is not its own — the
    # cascade rules have something to reason about here.
    "Task": "high_impact",
}

#: Native tool name -> canonical name, so a harness-neutral policy never says `Bash`.
TOOL_MAP: dict[str, str] = {
    "Bash": "shell",
    "BashOutput": "shell.output",
    "KillShell": "shell.kill",
    "Write": "file.write",
    "Edit": "file.edit",
    "NotebookEdit": "notebook.edit",
    "Read": "file.read",
    "Glob": "file.search",
    "Grep": "file.search",
    "WebFetch": "web.fetch",
    "WebSearch": "web.search",
    "Task": "agent.spawn",
}

#: Claude Code names an MCP tool ``mcp__<server>__<tool>``.
MCP_PREFIX = "mcp__"


def mcp_server_of(name: str) -> str | None:
    """The MCP server a Claude Code tool name belongs to, or None if it is not one."""
    if not name.startswith(MCP_PREFIX):
        return None
    parts = name.split("__")
    return parts[1] if len(parts) >= 2 and parts[1] else None


def canonical_tool(name: str) -> str:
    """``Bash`` -> ``shell``; ``mcp__github__create_issue`` -> ``mcp:github/create_issue``.

    A tool with no canonical meaning keeps its own name under ``native:``, so it is
    never mistaken for one that has.
    """
    if name in TOOL_MAP:
        return TOOL_MAP[name]
    server = mcp_server_of(name)
    if server is not None:
        tool = "__".join(name.split("__")[2:])
        return f"mcp:{server}/{tool}" if tool else f"mcp:{server}"
    return f"native:{name}"


__all__ = ["MCP_PREFIX", "TOOL_IMPACTS", "TOOL_MAP", "canonical_tool", "mcp_server_of"]
