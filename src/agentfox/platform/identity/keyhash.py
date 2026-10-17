"""Storing and checking machine-generated keys: operator tokens and agent keys.

Both kinds of key are 40 random characters from a 62-symbol alphabet — about 238 bits.
For a secret that strong, a single SHA-256 is as safe to store as any slow hash: a
leaked digest cannot be reversed or guessed, which is why GitHub and Stripe store
their tokens this way. A slow hash such as argon2 exists for human passwords, whose
low entropy makes guessing feasible, and its cost is deliberate.

That cost was paid on every request: each dashboard page makes ten to twenty API
calls, and every inline guard call presents an agent key, and each one ran an argon2
verification (tens of milliseconds on a laptop, several times that on a small
serverless CPU). So keys are now stored as ``sha256$<hex>`` and checked with a
constant-time compare. Keys stored before this as argon2 hashes still verify, and are
re-stored in the new form the first time they are used, so nobody is signed out.
"""

from __future__ import annotations

import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

SCHEME = "sha256$"
_argon2 = PasswordHasher()


def hash_key(raw: str) -> str:
    return SCHEME + hashlib.sha256(raw.encode()).hexdigest()


def check_key(stored: str, raw: str) -> tuple[bool, str | None]:
    """``(matches, upgraded)``: whether ``raw`` matches, and the new stored form when
    the match was against a legacy argon2 hash (the caller saves it)."""
    if stored.startswith(SCHEME):
        return hmac.compare_digest(stored, hash_key(raw)), None
    try:
        _argon2.verify(stored, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False, None
    return True, hash_key(raw)
