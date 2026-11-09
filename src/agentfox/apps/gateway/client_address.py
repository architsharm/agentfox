"""The visitor's address, for the per-address limits on the public routes.

``request.client.host`` is the address of whatever opened the connection. Behind a
proxy (Vercel's edge, a load balancer) that is the proxy, for every visitor, so a
limit keyed on it is one shared bucket: the playground's eight sandboxes an hour were
eight for the whole internet. ``X-Forwarded-For`` carries the real address, but the
client sets that header too, so it is only read as far as ``trusted_proxy_hops``
says proxies we trust have written it (`config.Settings.forwarded_for_hops`).

With ``hops`` trusted proxies, each appends the address it received the request from,
so the visitor is the ``hops``-th entry from the right. Anything further left was
supplied by the client and is ignored.
"""

from __future__ import annotations

from fastapi import Request

from agentfox.core.config import get_settings


def client_address(request: Request, *, hops: int | None = None) -> str:
    """The address a per-visitor limit should count against."""
    peer = request.client.host if request.client else "unknown"
    trusted = get_settings().forwarded_for_hops if hops is None else max(0, hops)
    if trusted <= 0:
        return peer
    header = request.headers.get("x-forwarded-for", "")
    entries = [part.strip() for part in header.split(",") if part.strip()]
    if len(entries) < trusted:
        # Fewer entries than proxies we were told about: the request did not come
        # through them, so the header proves nothing. The peer is all we know.
        return peer
    return entries[-trusted]
