"""Codex CLI's own tools: what each is called in AgentFox's vocabulary, and what it can do.

The names are the ones Codex writes into a hook payload's ``tool_name``, read off the
Codex source (``codex-rs/core/src/tools/hook_names.rs`` and the tool handlers) rather
than off its model-facing tool names. They differ, and the difference matters:

* Every shell path (``shell``, ``exec_command``, unified exec, a command nested in code
  mode) reaches a hook as ``Bash``, with ``tool_input: {"command": "<string>"}``.
* File edits reach a hook as ``apply_patch``, with the whole patch in
  ``tool_input.command``. ``Edit`` and ``Write`` are only *matcher aliases* in Codex; they
  never appear in a payload, so they are not declared here.
* MCP tools arrive as ``mcp__<server>__<tool>``, the same spelling Claude Code uses.
* Hosted tools (web search) run on OpenAI's side and never reach a hook at all.
"""

from __future__ import annotations

import re
from typing import Any

#: Native tool name -> declared impact. ``install`` declares and grants these.
#:
#: ``Bash`` is ``write`` for the reason given in the Claude Code adapter: a shell has no
#: fixed impact, so the tool-level impact is the floor and the shell analyser supplies
#: the ceiling per command (``rm -rf /`` still reaches ``shell.destructive``).
TOOL_IMPACTS: dict[str, str] = {
    "Bash": "write",
    "apply_patch": "write",
    "view_image": "read",
    "update_plan": "read",
    # Starts another agent with its own tools; its blast radius is not its own.
    "spawn_agent": "high_impact",
}

#: Native tool name -> canonical name, so a harness-neutral policy never says `Bash`.
TOOL_MAP: dict[str, str] = {
    "Bash": "shell",
    "apply_patch": "file.edit",
    "view_image": "file.read",
    "update_plan": "plan.update",
    "spawn_agent": "agent.spawn",
}

#: The tools whose ``tool_input`` is ``{"command": <string>}`` and whose rewrite Codex
#: accepts only as a string ``command`` (anything else is reported as a hook error and
#: the original call runs).
COMMAND_TOOLS = frozenset({"Bash", "apply_patch"})

#: Codex names an MCP tool ``mcp__<server>__<tool>``.
MCP_PREFIX = "mcp__"

#: The file headers of Codex's patch format (``*** Add File: path`` and so on).
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", re.MULTILINE)
_PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+?)\s*$", re.MULTILINE)


def mcp_server_of(name: str) -> str | None:
    """The MCP server a Codex tool name belongs to, or None if it is not one."""
    if not name.startswith(MCP_PREFIX):
        return None
    parts = name.split("__")
    return parts[1] if len(parts) >= 2 and parts[1] else None


def canonical_tool(name: str) -> str:
    """``Bash`` -> ``shell``; ``mcp__github__create_issue`` -> ``mcp:github/create_issue``."""
    if name in TOOL_MAP:
        return TOOL_MAP[name]
    server = mcp_server_of(name)
    if server is not None:
        tool = "__".join(name.split("__")[2:])
        return f"mcp:{server}/{tool}" if tool else f"mcp:{server}"
    return f"native:{name}"


def patch_paths(patch: str) -> list[str]:
    """Every file a Codex patch adds, updates, deletes or moves to, in order."""
    seen: list[str] = []
    for match in [*_PATCH_FILE.finditer(patch), *_PATCH_MOVE.finditer(patch)]:
        path = match.group(1).strip()
        if path and path not in seen:
            seen.append(path)
    return seen


def arguments_of(tool: str, tool_input: Any) -> dict[str, Any]:
    """``tool_input`` as the arguments AgentFox evaluates.

    An ``apply_patch`` call carries its patch under ``command``, which every action rule
    reads as a shell command: a patch adding a line that says ``rm -rf`` would be refused
    as if it ran it, and an ordinary edit would be judged as a shell. So the patch is
    passed as ``patch``, with the files it touches beside it as ``paths``, which is what
    a path rule needs. :func:`tool_input_of` turns a rewrite back into Codex's shape.
    """
    if not isinstance(tool_input, dict):
        return {"value": tool_input}
    if tool == "apply_patch" and isinstance(tool_input.get("command"), str):
        patch = tool_input["command"]
        rest = {k: v for k, v in tool_input.items() if k != "command"}
        return {**rest, "patch": patch, "paths": patch_paths(patch)}
    return dict(tool_input)


def tool_input_of(tool: str, arguments: dict[str, Any], original: dict[str, Any]) -> Any:
    """A rewrite of ``arguments`` as the ``updatedInput`` Codex accepts, or None.

    For a command tool Codex reads one field, a string ``command``. A rewrite is laid
    over the call's own arguments, so one that leaves the command alone sends it back
    unchanged, and one with no string command at all cannot be expressed: None, and the
    caller refuses the call rather than letting Codex run the original.
    """
    if tool not in COMMAND_TOOLS:
        return dict(arguments)
    merged = {**original, **arguments}
    key = "patch" if tool == "apply_patch" else "command"
    command = merged.get(key)
    return {"command": command} if isinstance(command, str) and command else None


__all__ = [
    "COMMAND_TOOLS",
    "MCP_PREFIX",
    "TOOL_IMPACTS",
    "TOOL_MAP",
    "arguments_of",
    "canonical_tool",
    "mcp_server_of",
    "patch_paths",
    "tool_input_of",
]
