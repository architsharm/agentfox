"""Pillar 6 — the control catalog and data retention.

The open core loads the control catalog (controls, their framework mappings as data,
obligations) because policy rules and threat coverage reference control ids, and keeps
data retention and legal holds because every self-hosted deployment needs them.
Turning the catalog into an auditor's view (control status, reviews and sign-off, risk,
evidence) is AgentFox Enterprise (`ee/`).
"""

from agentfox.capabilities.compliance import catalog, retention
from agentfox.capabilities.compliance.catalog import (
    load_catalog,
    load_obligations,
    sync_catalog,
    sync_obligations,
)

__all__ = [
    "catalog",
    "load_catalog",
    "load_obligations",
    "retention",
    "sync_catalog",
    "sync_obligations",
]
