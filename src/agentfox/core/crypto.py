"""Symmetric encryption for secrets we must store but never want to leak.

One primitive (Fernet) and one setting, `AGENTFOX_TOKEN_ENCRYPTION_KEY`, for every
secret held at rest: a connected GitHub account's access token and webhook secret,
source-connection credentials, Slack alert URLs, probe-target auth headers and
agent message-signing keys. There is one boundary to reason about ("is this
deployment configured to hold secrets at rest"), not one per feature.

Key rotation: `AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS` holds retired keys
(comma-separated). Decryption tries the current key first, then each previous key;
encryption only ever uses the current key. `agentfox admin keys rotate` (or the
`keys.rotate` job) re-encrypts every stored value under the current key, after which
the previous keys can be removed. See docs/deployment/key-rotation.md.
"""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken

from agentfox.core.config import get_settings


class EncryptionNotConfigured(RuntimeError):
    """`AGENTFOX_TOKEN_ENCRYPTION_KEY` is unset. Callers map this to a 503 —
    failing closed rather than ever storing a secret unencrypted."""


class DecryptionFailed(RuntimeError):
    """The stored ciphertext doesn't decrypt under the current key or any previous
    key — wrong key, corrupted row, or tampering. Callers map this to a 500."""


class InvalidEncryptionKey(RuntimeError):
    """A configured key is not a Fernet key. Names the variable, never the value."""


def key_fingerprint(key: str | bytes) -> str:
    """A stable, non-secret label for a key: the first 8 hex of its SHA-256.

    Lets status output, checkpoints and the audit chain say *which* key was used
    without saying anything usable about it.
    """
    raw = key.encode() if isinstance(key, str) else key
    return hashlib.sha256(raw).hexdigest()[:8]


def _make_fernet(key: str, variable: str) -> Fernet:
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise InvalidEncryptionKey(
            f"{variable} is not a valid Fernet key (32 url-safe base64-encoded bytes). "
            "Generate one with `openssl rand -base64 32 | tr '+/' '-_'`."
        ) from exc


def current_key() -> str | None:
    return get_settings().token_encryption_key or None


def previous_keys() -> list[str]:
    return get_settings().token_encryption_previous_keys


def _fernet() -> Fernet:
    key = current_key()
    if not key:
        raise EncryptionNotConfigured(
            "AGENTFOX_TOKEN_ENCRYPTION_KEY is unset — refusing to store a secret unencrypted."
        )
    return _make_fernet(key, "AGENTFOX_TOKEN_ENCRYPTION_KEY")


def keyring() -> list[tuple[str, Fernet]]:
    """``(fingerprint, Fernet)`` for the current key, then each previous key."""
    current = _fernet()
    ring = [(key_fingerprint(current_key() or ""), current)]
    for key in previous_keys():
        ring.append(
            (key_fingerprint(key), _make_fernet(key, "AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS"))
        )
    return ring


def encrypt_secret(raw: str) -> str:
    """Encrypt under the current key. Previous keys are never used to encrypt."""
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_with(blob: str, ring: list[tuple[str, Fernet]] | None = None) -> tuple[str, int]:
    """Decrypt ``blob``; return the plaintext and the index of the key that worked
    (0 is the current key). Raises :class:`DecryptionFailed` if none does."""
    ring = ring if ring is not None else keyring()
    token = blob.encode()
    for index, (_fp, fernet) in enumerate(ring):
        try:
            return fernet.decrypt(token).decode(), index
        except InvalidToken:
            continue
    raise DecryptionFailed("stored secret could not be decrypted")


def decrypt_secret(blob: str) -> str:
    return decrypt_with(blob)[0]
