"""Key rotation for the two keys that protect stored data.

`AGENTFOX_TOKEN_ENCRYPTION_KEY` encrypts secrets at rest; `AGENTFOX_AUDIT_SIGNING_KEY`
signs audit checkpoints. Each has a ``*_PREVIOUS`` companion holding retired keys,
and :mod:`agentfox.platform.keys.rotation` moves everything they still protect onto
the current key. See docs/deployment/key-rotation.md.
"""

from agentfox.platform.keys.rotation import (
    ENCRYPTED_FIELDS,
    ROTATED_ACTION,
    enqueue_if_pending,
    rotate,
    status,
    status_summary,
)

__all__ = [
    "ENCRYPTED_FIELDS",
    "ROTATED_ACTION",
    "enqueue_if_pending",
    "rotate",
    "status",
    "status_summary",
]
