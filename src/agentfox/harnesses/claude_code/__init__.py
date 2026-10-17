"""Claude Code, governed through its hooks.

`adapter.py` is the wire contract and the capability rows, `tools.py` its built-in
tools, `install.py` its settings file, `transcripts.py` its local session history, and
`fixtures/` hook payloads captured from the real tool. Reach it through the registry
(`agentfox.harnesses.get("claude")`), not by importing this package.
"""

from __future__ import annotations

from agentfox.harnesses.claude_code.adapter import ADAPTER, ClaudeCodeAdapter

__all__ = ["ADAPTER", "ClaudeCodeAdapter"]
