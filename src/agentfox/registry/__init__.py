"""Pillar 1 — Discovery & Agent Registry."""

from agentfox.registry.control import all_controls, get_control, kill, quarantine, resume, set_state, state_of
from agentfox.registry.service import (
    assess_delegation,
    attest_registry,
    derive_lineage,
    detect_shadow_agents,
    inventory,
    lineage,
    observe_agent,
    record_edge,
    register_agent,
    scan_mcp_server,
    slugify,
    unowned_agents,
    upsert_mcp_server,
    upsert_tool,
)

__all__ = [
    "all_controls",
    "assess_delegation",
    "attest_registry",
    "derive_lineage",
    "detect_shadow_agents",
    "get_control",
    "kill",
    "inventory",
    "lineage",
    "observe_agent",
    "quarantine",
    "record_edge",
    "register_agent",
    "resume",
    "scan_mcp_server",
    "set_state",
    "slugify",
    "state_of",
    "unowned_agents",
    "upsert_mcp_server",
    "upsert_tool",
]
