"""This demo's tools: the shared kit's (`kit/support_tools.py`), under this demo's agent.

The dataset, the four tool implementations, the capability grants and
`GovernedToolkit` live once in the kit; see its docstring for how every call is
governed. The only thing this demo sets is its own agent slug, so its identity never
collides with the other demo's even if the two shared a database. The CrewAI crew (`crew.py`)
imports everything from here.
"""

from __future__ import annotations

from dataclasses import dataclass

import _env  # noqa: F401  -- puts the kit on the path and picks the database first
from kit.support_tools import (
    CAPABILITY_GRANTS,
    CUSTOMERS,
    ORDERS,
    OUTBOX,
    REFUND_LEDGER,
    SERVER_NAME,
    TOOL_DESCRIPTORS,
    decision_summary,
    declared_tool_keys,
)
from kit.support_tools import GovernedToolkit as _KitToolkit

AGENT_SLUG = "support-crew-live"


@dataclass
class GovernedToolkit(_KitToolkit):
    """`kit.support_tools.GovernedToolkit`, defaulting to this demo's agent."""

    agent_slug: str = AGENT_SLUG


__all__ = [
    "AGENT_SLUG",
    "CAPABILITY_GRANTS",
    "CUSTOMERS",
    "ORDERS",
    "OUTBOX",
    "REFUND_LEDGER",
    "SERVER_NAME",
    "TOOL_DESCRIPTORS",
    "GovernedToolkit",
    "decision_summary",
    "declared_tool_keys",
]
