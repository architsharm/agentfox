"""Verify a Microsoft Entra ID app-only access token.

Copilot Studio calls an external threat detection endpoint with a bearer token it
obtains as the customer's own Entra app (a Federated Identity Credential on a
single-tenant app in the customer's tenant). Accepting it means checking, without a
JWT library this project does not otherwise need:

* the signature (RS256) against the tenant's published signing keys;
* ``exp`` and ``nbf`` (five minutes of clock skew);
* ``tid`` and ``iss``: the customer's tenant, in either token version's issuer form;
* ``appid`` (v1) or ``azp`` (v2): the customer's app, the one the admin entered in
  the Power Platform admin center, so a token any other app in that tenant gets for
  this audience is refused;
* ``aud``: the endpoint's base URL (the scope Copilot Studio requests), or this
  deployment's app id.

The keys are fetched from ``login.microsoftonline.com`` and kept for an hour; a token
signed with a key not in the cached set refreshes it once (Entra rotates keys).
"""

from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

#: Clock skew allowed on `exp` and `nbf`.
SKEW_S = 300
#: How long a tenant's signing keys are kept before they are fetched again.
KEYS_TTL_S = 3600
KEYS_URL = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


class TokenInvalid(ValueError):
    """The token was refused. The message says which check failed, never the token."""


def _b64(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def fetch_keys(tenant_id: str) -> dict[str, Any]:
    """The tenant's JWKS document. Replaced in tests."""
    response = httpx.get(KEYS_URL.format(tenant=tenant_id), timeout=5.0)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def _key(tenant_id: str, kid: str) -> rsa.RSAPublicKey:
    for refresh in (False, True):
        with _lock:
            cached = _cache.get(tenant_id)
            fresh = cached is not None and time.time() - cached[0] < KEYS_TTL_S
        if refresh or not fresh:
            try:
                document = fetch_keys(tenant_id)
            except (httpx.HTTPError, ValueError) as exc:
                raise TokenInvalid("the tenant's signing keys could not be fetched") from exc
            with _lock:
                _cache[tenant_id] = (time.time(), document)
            cached = _cache[tenant_id]
        for jwk in (cached[1] if cached else {}).get("keys") or []:
            if isinstance(jwk, dict) and jwk.get("kid") == kid and jwk.get("kty") == "RSA":
                n = int.from_bytes(_b64(jwk["n"]), "big")
                e = int.from_bytes(_b64(jwk["e"]), "big")
                return rsa.RSAPublicNumbers(e, n).public_key()
    raise TokenInvalid("the token was signed with a key the tenant does not publish")


def verify_app_token(
    token: str,
    *,
    tenant_id: str,
    app_id: str,
    audiences: set[str],
    now: float | None = None,
) -> dict[str, Any]:
    """The token's claims, or :class:`TokenInvalid`."""
    if not tenant_id or not app_id:
        raise TokenInvalid("the connection has no Entra tenant or app id")
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        header = json.loads(_b64(head_b64))
        claims = json.loads(_b64(body_b64))
        signature = _b64(sig_b64)
    except (ValueError, TypeError) as exc:
        raise TokenInvalid("the token is not a JWT") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise TokenInvalid("the token is not a JWT")
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise TokenInvalid("the token is not RS256-signed")
    key = _key(tenant_id, str(header["kid"]))
    try:
        key.verify(
            signature,
            f"{head_b64}.{body_b64}".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise TokenInvalid("the token's signature does not verify") from exc

    now = time.time() if now is None else now
    if not isinstance(claims.get("exp"), int | float) or now > claims["exp"] + SKEW_S:
        raise TokenInvalid("the token has expired")
    if isinstance(claims.get("nbf"), int | float) and now < claims["nbf"] - SKEW_S:
        raise TokenInvalid("the token is not valid yet")
    if str(claims.get("tid") or "").lower() != tenant_id.lower():
        raise TokenInvalid("the token is from another tenant")
    issuers = {
        f"https://login.microsoftonline.com/{tenant_id}/v2.0".lower(),
        f"https://sts.windows.net/{tenant_id}/".lower(),
    }
    if str(claims.get("iss") or "").lower() not in issuers:
        raise TokenInvalid("the token's issuer is not the tenant's")
    caller = str(claims.get("azp") or claims.get("appid") or "")
    if caller.lower() != app_id.lower():
        raise TokenInvalid("the token is not the configured app's")
    aud = claims.get("aud")
    presented = set(aud) if isinstance(aud, list) else {str(aud or "")}
    wanted = {a.rstrip("/").lower() for a in audiences if a}
    if not {p.rstrip("/").lower() for p in presented} & wanted:
        raise TokenInvalid("the token is for another audience")
    return claims
