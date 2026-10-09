"""OpenAI Codex CLI, governed through its hooks.

`adapter.py` is the wire contract and the capability rows, `tools.py` its tools as a
hook payload names them, `install.py` its hooks file, and `fixtures/` hook payloads
built from Codex's own hook schemas and tests. Reach it through the registry
(`agentfox.harnesses.get("codex")`), not by importing this package.
"""

from __future__ import annotations

from agentfox.harnesses.codex.adapter import ADAPTER, CodexAdapter

__all__ = ["ADAPTER", "CodexAdapter"]
