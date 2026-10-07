"""The product's HTTP header names, and the pre-rename spelling still accepted.

Every header agentfox emits is ``X-AgentFox-*``. Until the legacy spelling is
retired, every header it *reads* is accepted as either ``x-agentfox-<name>`` or the
pre-rename ``x-nometria-<name>``, with the new one winning when a request carries
both: a client that has not been updated yet keeps working, and one that has is
never overridden by a stale header it forgot to remove.

Two ways in, depending on who holds the request:

* the gateway rewrites the raw ASGI headers once, in `LegacyHeaderMiddleware`
  (``agentfox.apps.gateway.app``), via :func:`normalize_asgi_headers`, so every
  route below it declares and reads only the ``x-agentfox-*`` names;
* code reading a headers mapping it does not own (the FastAPI middleware in a
  customer's app, the SDK reading a gateway response) calls :func:`get_header`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

PREFIX = "x-agentfox-"
#: Accepted on input only, never emitted. Removed when the rename is finished.
LEGACY_PREFIX = "x-nometria-"


def name(suffix: str) -> str:
    """``x-agentfox-<suffix>``, lower-case (header names are case-insensitive)."""
    return PREFIX + suffix.lower()


def get_header(headers: Mapping[str, str], suffix: str) -> str | None:
    """The value of ``x-agentfox-<suffix>``, else of ``x-nometria-<suffix>``.

    ``headers`` must be case-insensitive (Starlette's and httpx's ``Headers`` are).
    An empty value counts as absent.
    """
    return headers.get(PREFIX + suffix) or headers.get(LEGACY_PREFIX + suffix) or None


def normalize_asgi_headers(raw: Iterable[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Raw ASGI headers with every ``x-nometria-*`` renamed to ``x-agentfox-*``.

    A legacy header is dropped when the request also carries its ``x-agentfox-*``
    twin (the new name wins); otherwise it is renamed in place. Nothing else is
    touched, and the order of the remaining headers is kept. With no legacy header
    present the input list itself is returned.
    """
    if not isinstance(raw, list):
        raw = list(raw)
    legacy = LEGACY_PREFIX.encode()
    if not any(key.lower().startswith(legacy) for key, _ in raw):
        return raw
    present = {key.lower() for key, _ in raw}
    out: list[tuple[bytes, bytes]] = []
    for key, value in raw:
        lowered = key.lower()
        if lowered.startswith(legacy):
            renamed = PREFIX.encode() + lowered[len(legacy) :]
            if renamed in present:
                continue
            out.append((renamed, value))
        else:
            out.append((key, value))
    return out


__all__ = ["LEGACY_PREFIX", "PREFIX", "get_header", "name", "normalize_asgi_headers"]
