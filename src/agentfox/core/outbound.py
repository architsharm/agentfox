"""Fetching a URL someone typed, without becoming a way into our own network.

Some features fetch a URL an operator supplies: an OpenAPI spec for hosted-API
discovery, a knowledge-base endpoint or a document a source points at. The server
doing the fetch can usually reach things the operator cannot — its own loopback
services, the private network it runs on, and on every major cloud the instance
metadata endpoint at 169.254.169.254, which hands out credentials. So only globally
routable addresses are fetched by default.

`guarded_get` is the one way to do such a fetch:

* only http(s);
* every address the host resolves to is checked, not just the first, and the
  connection goes to the address that was checked, so a second DNS answer (DNS
  rebinding) cannot swap in another one;
* redirects are followed by hand and each target is checked again;
* the body is read under a size cap rather than buffered whole.

A self-hosted deployment whose spec or knowledge base lives on its own network can
set `outbound_allow_private_hosts`. Link-local (cloud metadata), multicast,
unspecified and reserved addresses stay refused whatever the setting.
"""

from __future__ import annotations

import ipaddress
import socket

import httpx

#: Injected in tests. ``None`` means httpx's real network transport.
_TRANSPORT: httpx.BaseTransport | None = None
#: Indirection so tests can answer DNS without a network.
_getaddrinfo = socket.getaddrinfo

MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = ("http", "https")
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


class OutboundRefused(ValueError):
    """The URL was not fetched: refused, unreachable, or answered with an error."""


def refusal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Why this server must not connect to ``ip`` on an operator's behalf, or None."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # Never, whatever the setting: link-local is where cloud metadata lives.
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return "a link-local, multicast, unspecified or reserved address"
    if ip.is_global:
        return None
    if ip.is_loopback or ip.is_private or ip in _SHARED_ADDRESS_SPACE:
        from agentfox.core.config import get_settings

        if get_settings().outbound_allow_private_hosts:
            return None
        return (
            "an internal address (loopback or private network). If it is on this "
            "deployment's own network, set outbound_allow_private_hosts"
        )
    return "an address that is not publicly routable"


def vet(url: httpx.URL, what: str) -> str:
    """Resolve ``url``'s host and return the one address it is safe to connect to.

    A name that answers with one public and one private address is refused: which
    one a later connection would use is not ours to decide.
    """
    if url.scheme not in _ALLOWED_SCHEMES:
        raise OutboundRefused(
            f"only http(s) URLs can be fetched for {what}, not '{url.scheme or '(none)'}'"
        )
    host = url.host
    if not host:
        raise OutboundRefused(f"the URL for {what} has no host")
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        infos = _getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise OutboundRefused(f"could not resolve '{host}': {exc}") from exc
    addresses: list[str] = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]
        if raw not in addresses:
            addresses.append(raw)
    if not addresses:
        raise OutboundRefused(f"could not resolve '{host}'")
    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise OutboundRefused(f"'{host}' resolved to an unparseable address") from exc
        why = refusal(ip)
        if why is not None:
            raise OutboundRefused(
                f"refusing to fetch {what}: '{host}' resolves to {raw}, {why}. "
                "Fetching it is not allowed."
            )
    return addresses[0]


def guarded_get(
    url_text: str,
    *,
    what: str,
    max_bytes: int,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    truncate: bool = False,
) -> httpx.Response:
    """GET ``url_text`` with every hop vetted and the body read under ``max_bytes``.

    ``what`` names the thing being fetched ("the OpenAPI spec", "the source") for
    error messages. ``headers`` (credentials included) are sent on the first hop
    only: a redirect is never handed the caller's ``Authorization``. A body over
    ``max_bytes`` is refused, or with ``truncate`` cut at ``max_bytes``.
    """
    return _guarded(
        "GET",
        url_text,
        what=what,
        max_bytes=max_bytes,
        timeout=timeout,
        headers=headers,
        truncate=truncate,
    )


def guarded_post(
    url_text: str,
    *,
    what: str,
    json_body: object,
    max_bytes: int,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST a JSON body to ``url_text`` under the same address vetting as `guarded_get`.

    A redirect is refused rather than followed: re-sending a body to wherever a
    server points is how a request ends up somewhere nobody vetted or meant.
    """
    return _guarded(
        "POST",
        url_text,
        what=what,
        max_bytes=max_bytes,
        timeout=timeout,
        headers=headers,
        json_body=json_body,
    )


_NO_BODY = object()


def _guarded(
    method: str,
    url_text: str,
    *,
    what: str,
    max_bytes: int,
    timeout: float,
    headers: dict[str, str] | None,
    truncate: bool = False,
    json_body: object = _NO_BODY,
) -> httpx.Response:
    try:
        url = httpx.URL(url_text)
    except (httpx.InvalidURL, TypeError, ValueError) as exc:
        raise OutboundRefused(f"not a valid URL: {exc}") from exc

    extra = dict(headers or {})
    with httpx.Client(transport=_TRANSPORT, timeout=timeout, follow_redirects=False) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            ip = vet(url, what)
            # Connect to the vetted address; keep the name for Host and TLS (SNI and
            # certificate verification both use `sni_hostname`).
            pinned = url.copy_with(host=ip)
            hop_headers = {**extra, "Host": url.netloc.decode("ascii")}
            extensions = {"sni_hostname": url.host} if url.scheme == "https" else {}
            body_kwargs = {} if json_body is _NO_BODY else {"json": json_body}
            request = client.build_request(
                method, pinned, headers=hop_headers, extensions=extensions, **body_kwargs
            )
            try:
                resp = client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise OutboundRefused(f"could not fetch {what}: {exc}") from exc
            try:
                if resp.is_redirect and method != "GET":
                    raise OutboundRefused(f"{what} answered with a redirect, which is not followed")
                if resp.is_redirect:
                    location = resp.headers.get("location", "")
                    if not location:
                        raise OutboundRefused(f"{what} redirected without a Location")
                    try:
                        url = url.join(location)
                    except (httpx.InvalidURL, ValueError) as exc:
                        raise OutboundRefused(
                            f"{what} redirected to an invalid URL: {exc}"
                        ) from exc
                    extra = {}
                    continue
                if resp.status_code >= 400:
                    raise OutboundRefused(
                        f"could not fetch {what}: HTTP {resp.status_code} from {url}"
                    )
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        if truncate:
                            del body[max_bytes:]
                            break
                        raise OutboundRefused(f"{what} is too large")
                # `iter_bytes` already undid any Content-Encoding, so the copy must not
                # claim one or it would be decoded twice.
                kept = {
                    k: v
                    for k, v in resp.headers.items()
                    if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
                }
                return httpx.Response(
                    resp.status_code, headers=kept, content=bytes(body), request=request
                )
            except httpx.HTTPError as exc:
                raise OutboundRefused(f"could not fetch {what}: {exc}") from exc
            finally:
                resp.close()
    raise OutboundRefused(f"{what} redirected more than {MAX_REDIRECTS} times")
