"""Symmetric encryption for secrets we must store but never want to leak.

Same primitive and same fail-closed behaviour `gateway/routes/integrations.py`
already uses for a connected GitHub account's access token — extracted here so a
second call site (source connection credentials) doesn't reimplement it. Both
share the one `NOMETRIA_TOKEN_ENCRYPTION_KEY` setting: there is one boundary to
reason about ("is this deployment configured to hold secrets at rest"), not one
per feature.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from agentfox.core.config import get_settings


class EncryptionNotConfigured(RuntimeError):
    """`NOMETRIA_TOKEN_ENCRYPTION_KEY` is unset. Callers map this to a 503 —
    failing closed rather than ever storing a secret unencrypted."""


class DecryptionFailed(RuntimeError):
    """The stored ciphertext doesn't decrypt under the configured key — wrong
    key, corrupted row, or tampering. Callers map this to a 500."""


def _fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise EncryptionNotConfigured(
            "NOMETRIA_TOKEN_ENCRYPTION_KEY is unset — refusing to store a secret unencrypted."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_secret(blob: str) -> str:
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionFailed("stored secret could not be decrypted") from exc
