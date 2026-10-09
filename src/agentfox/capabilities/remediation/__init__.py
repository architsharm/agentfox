"""Fixing an issue from the issue: the actions the platform can take for each finding.

See `remedies` for the catalogue.
"""

from agentfox.capabilities.remediation.remedies import (
    Remedy,
    RemedyError,
    apply_remedy,
    recheck,
    remedies_for,
)

__all__ = ["Remedy", "RemedyError", "apply_remedy", "recheck", "remedies_for"]
