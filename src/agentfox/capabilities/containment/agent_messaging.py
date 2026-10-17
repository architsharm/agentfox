"""Inter-agent message signing — NOM-IAM-08, closes OWASP ASI07.

Agent-to-agent traffic is its own boundary rather than being folded into
``tool_result`` with the same governance as a tool call's return value. This
module is the signing half of that boundary —
see :meth:`agentfox.runtime.enforcement.Enforcer.guard_agent_message` for the surface,
replay and agent-card checks that use it.

One HMAC-SHA256 secret per agent, encrypted at rest with the same primitive
:mod:`crypto` already uses for a connected GitHub token. Signing is a shared
secret between the agent and AgentFox's enforcement layer — AgentFox does not
need to *be* the transport to verify a message, only to hold the same key the
sender signed with.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as _secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.crypto import decrypt_secret, encrypt_secret
from agentfox.core.models import AgentSigningKey

#: A signature older than this is rejected even if it verifies — bounds how long a
#: captured signature/nonce pair remains a usable replay target before the anti-
#: replay table (unique on sender+nonce) is even consulted.
DEFAULT_VALIDITY_SECONDS = 300


def mint_signing_key(
    session: Session, agent_id: str, *, created_by: str | None = None
) -> tuple[AgentSigningKey, str]:
    """Generate (or rotate) an agent's signing key.

    Returns the raw key alongside the row — shown once, like an API token
    (``ApiToken``/``TokenManager``): nothing before this point could sign as this
    agent, and nothing after this point can retrieve the raw value again.
    """
    raw = _secrets.token_hex(32)
    existing = session.scalar(select(AgentSigningKey).where(AgentSigningKey.agent_id == agent_id))
    if existing is not None:
        existing.key_encrypted = encrypt_secret(raw)
        existing.created_by = created_by
        existing.revoked_at = None
        key = existing
    else:
        key = AgentSigningKey(
            agent_id=agent_id, key_encrypted=encrypt_secret(raw), created_by=created_by
        )
        session.add(key)
    session.flush()
    return key, raw


def _canonical(sender: str, nonce: str, timestamp: float, payload: str) -> bytes:
    # Fixed field order + explicit separators so signer and verifier never
    # disagree on what was actually signed.
    return f"{sender}\n{nonce}\n{timestamp:.6f}\n{payload}".encode()


def sign_message(
    raw_key: str, *, sender: str, nonce: str, payload: str, timestamp: float | None = None
) -> tuple[str, float]:
    ts = timestamp if timestamp is not None else time.time()
    mac = hmac.new(raw_key.encode(), _canonical(sender, nonce, ts, payload), hashlib.sha256)
    return mac.hexdigest(), ts


def verify_message(
    raw_key: str,
    *,
    sender: str,
    nonce: str,
    payload: str,
    timestamp: float,
    signature: str,
    validity_seconds: int = DEFAULT_VALIDITY_SECONDS,
) -> bool:
    if abs(time.time() - timestamp) > validity_seconds:
        return False
    expected = hmac.new(
        raw_key.encode(), _canonical(sender, nonce, timestamp, payload), hashlib.sha256
    ).hexdigest()
    # constant-time compare — a timing side-channel here would leak the signature
    # byte by byte, defeating the point of signing at all.
    return hmac.compare_digest(expected, signature)


def decrypt_signing_key(key_row: AgentSigningKey) -> str:
    return decrypt_secret(key_row.key_encrypted)
