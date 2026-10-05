"""Static analysis for the hosted-API onboarding path.

``discovery.py`` needs source on disk to walk with ``ast`` — a non-starter for a team
whose AI system is a hosted API they call, not code they'd hand over. This module
produces the same ``Site``-shaped output from an OpenAPI document instead: each
operation becomes one governable site, so the rest of the onboarding pipeline (site
grouping, draft agent/policy creation in ``routes/integrations.py``) is reused
unchanged.

Only the *spec document* is ever fetched — never an operation on the live API. That
mirrors ``discovery.scan``'s own "static, never import, never execute" guarantee for a
repo, just for a different kind of target.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import httpx

from agentfox.discovery.repo import ScanReport, Site

#: A fetched spec document beyond this is refused outright — a resource-exhaustion
#: guard on server-supplied content, the same shape as the repo-tarball size cap.
_MAX_SPEC_BYTES = 5 * 1024 * 1024

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
#: Mutating methods are worth flagging more prominently than a plain read — not a
#: judgement about the endpoint itself, just a sorting hint for the review UI.
_METHOD_SEVERITY = {
    "get": "info",
    "post": "info",
    "put": "warn",
    "patch": "warn",
    "delete": "warn",
}


class SpecFetchError(ValueError):
    """The spec document could not be fetched or parsed. Never a code-execution
    failure — this module never runs anything from the target, only reads text."""


#: Injected in tests. ``None`` means httpx's real network transport.
_TRANSPORT: httpx.BaseTransport | None = None
#: Indirection so tests can answer DNS without a network.
_getaddrinfo = socket.getaddrinfo

_FETCH_TIMEOUT_SECONDS = 20.0
_MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = ("http", "https")
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _refusal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Why this server must not connect to ``ip`` on an operator's behalf, or None.

    The spec URL is operator input, and the server fetching it can usually reach
    things the operator cannot: its own loopback services, the private network it
    runs on, and — on every major cloud — the instance metadata endpoint at
    169.254.169.254, which hands out credentials. So only globally routable
    addresses are fetched by default.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # Never, whatever the setting: link-local is where cloud metadata lives.
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return "a link-local, multicast, unspecified or reserved address"
    if ip.is_global:
        return None
    internal = ip.is_loopback or ip.is_private or ip in _SHARED_ADDRESS_SPACE
    if internal:
        from agentfox.core.config import get_settings

        if get_settings().spec_fetch_allow_private_hosts:
            return None
        return (
            "an internal address (loopback or private network). If the spec is on "
            "this deployment's own network, set spec_fetch_allow_private_hosts"
        )
    return "an address that is not publicly routable"


def _vet(url: httpx.URL) -> str:
    """Resolve ``url``'s host and return the one address it is safe to connect to.

    Every resolved address is checked, not just the first: a name that answers with
    one public and one private address is refused, because which one a later
    connection would use is not ours to decide. The caller then connects to the
    returned address itself, so a second lookup (DNS rebinding) cannot swap in a
    different one between the check and the connection.
    """
    if url.scheme not in _ALLOWED_SCHEMES:
        raise SpecFetchError(
            f"only http(s) spec URLs can be fetched, not '{url.scheme or '(none)'}'"
        )
    host = url.host
    if not host:
        raise SpecFetchError("the spec URL has no host")
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        infos = _getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise SpecFetchError(f"could not resolve '{host}': {exc}") from exc
    addresses: list[str] = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]
        if raw not in addresses:
            addresses.append(raw)
    if not addresses:
        raise SpecFetchError(f"could not resolve '{host}'")
    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise SpecFetchError(f"'{host}' resolved to an unparseable address") from exc
        why = _refusal(ip)
        if why is not None:
            raise SpecFetchError(
                f"refusing to fetch the spec: '{host}' resolves to {raw}, {why}. "
                "Fetching it is not allowed."
            )
    return addresses[0]


def _guarded_get(spec_url: str) -> httpx.Response:
    """GET ``spec_url`` with every hop vetted, and the body read under the size cap.

    Redirects are followed by hand, at most ``_MAX_REDIRECTS``, and each target is
    vetted exactly like the first URL — a public host answering ``302 Location:
    http://169.254.169.254/`` is the textbook way round a check made only once.
    """
    try:
        url = httpx.URL(spec_url)
    except (httpx.InvalidURL, TypeError, ValueError) as exc:
        raise SpecFetchError(f"not a valid URL: {exc}") from exc

    with httpx.Client(
        transport=_TRANSPORT, timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        for _hop in range(_MAX_REDIRECTS + 1):
            ip = _vet(url)
            # Connect to the vetted address; keep the name for Host and TLS (SNI and
            # certificate verification both use `sni_hostname`).
            pinned = url.copy_with(host=ip)
            headers = {"Host": url.netloc.decode("ascii")}
            extensions = {}
            if url.scheme == "https":
                extensions["sni_hostname"] = url.host
            request = client.build_request("GET", pinned, headers=headers, extensions=extensions)
            try:
                resp = client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise SpecFetchError(f"could not fetch the OpenAPI spec: {exc}") from exc
            try:
                if resp.is_redirect:
                    location = resp.headers.get("location", "")
                    if not location:
                        raise SpecFetchError("the spec URL redirected without a Location")
                    try:
                        url = url.join(location)
                    except (httpx.InvalidURL, ValueError) as exc:
                        raise SpecFetchError(
                            f"the spec URL redirected to an invalid URL: {exc}"
                        ) from exc
                    continue
                if resp.status_code >= 400:
                    raise SpecFetchError(
                        f"could not fetch the OpenAPI spec: HTTP {resp.status_code} from {url}"
                    )
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_SPEC_BYTES:
                        raise SpecFetchError("OpenAPI spec is too large to scan")
                # `iter_bytes` already undid any Content-Encoding, so the copy must not
                # claim one or it would be decoded twice.
                headers = {
                    k: v
                    for k, v in resp.headers.items()
                    if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
                }
                return httpx.Response(
                    resp.status_code, headers=headers, content=bytes(body), request=request
                )
            except httpx.HTTPError as exc:
                raise SpecFetchError(f"could not fetch the OpenAPI spec: {exc}") from exc
            finally:
                resp.close()
    raise SpecFetchError(f"the spec URL redirected more than {_MAX_REDIRECTS} times")


def fetch_spec(spec_url: str) -> dict[str, Any]:
    """Fetch and parse an OpenAPI document (JSON or YAML) from a URL.

    Only public http(s) addresses are fetched (see `_refusal`), redirects are
    re-vetted hop by hop, and the connection goes to the address that was checked.
    """
    resp = _guarded_get(spec_url)

    content_type = resp.headers.get("content-type", "")
    looks_like_yaml = "yaml" in content_type or spec_url.lower().endswith((".yaml", ".yml"))

    def _parse_yaml() -> dict[str, Any]:
        import yaml

        try:
            parsed = yaml.safe_load(resp.text)
        except Exception as exc:
            raise SpecFetchError(
                f"the document at that URL is not valid JSON or YAML: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise SpecFetchError("the document did not parse to an OpenAPI object")
        return parsed

    if looks_like_yaml:
        return _parse_yaml()
    try:
        return resp.json()
    except Exception:
        return _parse_yaml()


def scan_spec(spec: dict[str, Any], *, source_label: str = "") -> ScanReport:
    """Turn a parsed OpenAPI document into the same site-shaped output
    ``discovery.scan`` produces from a repo.

    Every operation becomes a ``tool``-kind site — an endpoint is a capability an
    agent (or a human, via this API) can invoke, which is exactly what a ``tool``
    site already means in the repo-scan vocabulary.
    """
    title = (spec.get("info") or {}).get("title") or source_label or "hosted-api"
    report = ScanReport(root=source_label or title)
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        report.errors.append("no `paths` object in the OpenAPI document")
        return report

    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, op in operations.items():
            method_key = str(method).lower()
            if method_key not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            summary = op.get("summary") or op.get("operationId") or f"{method_key.upper()} {path}"
            report.sites.append(
                Site(
                    kind="tool",
                    file=title,
                    line=0,
                    detail=f"{method_key.upper()} {path} — {summary}",
                    provider="hosted_api",
                    governed=False,
                    severity=_METHOD_SEVERITY[method_key],
                )
            )

    report.files_scanned = 1
    report.frameworks = ["hosted_api"]
    return report
