"""Agents on a hosted platform whose tool calls are governed by webhook.

A Vapi assistant, a Retell agent or a Copilot Studio agent calls a URL of its owner's
choosing before a tool runs. :class:`~agentfox.core.models.PlatformConnection` is what
that URL points at: the agent the call is governed as, the customer's own tool server
an allowed call is forwarded to, and the secret that proves a delivery came from the
platform. The routes that receive those calls are in
``apps/gateway/routes/platform_hooks.py``.

The tool server is registered here by an operator, and checked twice: when it is
registered (``https``, a public host) and again before every forward, against what the
host resolves to then, because a name that pointed at a public address at registration
can point at ``169.254.169.254`` an hour later. A gateway that forwards wherever a
request says is a relay into the network it runs in.
"""

from __future__ import annotations

import ipaddress
import secrets
import socket
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import is_development
from agentfox.core.crypto import decrypt_secret, encrypt_secret
from agentfox.core.models import Agent, PlatformConnection
from agentfox.core.models.registry import PLATFORMS
from agentfox.core.tenancy import system_scope

#: How long a forward to the customer's tool server may take. Under every platform's
#: own tool timeout (Vapi 20 s by default, Retell 120 s), so a slow server is answered
#: with a refusal the agent can speak instead of the platform's generic timeout.
FORWARD_TIMEOUT_S = 15.0

#: The most a tool server's answer may be. A forward returns it to the platform as is.
MAX_FORWARD_BYTES = 1_000_000

#: Platforms whose allowed calls are forwarded, so a tool server is required.
FORWARDS = ("vapi", "retell")


class ConnectionError_(ValueError):
    """A connection that cannot be saved: the message says why, for the operator."""


def _local_upstreams_allowed() -> bool:
    """Development may forward to a tool server on this machine (`http://localhost`);
    any other environment may not."""
    return is_development()


def check_upstream(url: str) -> str:
    """The tool server URL, or :class:`ConnectionError_` if it is not one a gateway may
    forward to: ``https`` to a host that is not an address on a private network."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ConnectionError_("the tool server must be an https:// URL")
    if parts.username or parts.password:
        raise ConnectionError_("put credentials in the platform's headers, not in the URL")
    local = _local_upstreams_allowed()
    if parts.scheme == "http" and not local:
        raise ConnectionError_("the tool server must be an https:// URL")
    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        literal = None
    if literal is not None and not local and not literal.is_global:
        raise ConnectionError_("the tool server may not be an address on a private network")
    if not local and parts.hostname.lower() in ("localhost", "metadata.google.internal"):
        raise ConnectionError_("the tool server may not be this machine")
    return parts.geturl()


def _resolves_public(host: str) -> bool:
    """True when every address ``host`` resolves to now is a public one."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


def create(
    session: Session,
    agent: Agent,
    platform: str,
    *,
    upstream_url: str | None = None,
    secret: str | None = None,
    config: dict[str, Any] | None = None,
    actor: str = "",
) -> tuple[PlatformConnection, str | None]:
    """Register ``agent`` as running on ``platform``. Returns the connection and, for
    Vapi when no secret was given, the secret made for it (shown once)."""
    if platform not in PLATFORMS:
        raise ConnectionError_(f"unknown platform '{platform}'; one of {', '.join(PLATFORMS)}")
    made = None
    if platform in FORWARDS:
        if not upstream_url:
            raise ConnectionError_(
                f"a {platform} connection forwards allowed tool calls to your tool server; "
                "give its URL as upstream_url"
            )
        upstream_url = check_upstream(upstream_url)
    else:
        upstream_url = None
    if platform == "vapi" and not secret:
        # The bearer secret Vapi's credential sends; made here so it is long and random.
        secret = made = "afv_" + secrets.token_urlsafe(32)
    if platform == "retell" and not secret:
        raise ConnectionError_(
            "Retell signs each call with your Retell API key; give it as secret so the "
            "signature can be checked"
        )
    config = dict(config or {})
    if platform == "copilot_studio":
        for key in ("tenant_id", "app_id"):
            if not str(config.get(key) or "").strip():
                raise ConnectionError_(
                    f"a Copilot Studio connection needs config.{key}: the Entra "
                    f"{'tenant' if key == 'tenant_id' else 'application (client)'} id "
                    "Copilot Studio authenticates with"
                )
    connection = PlatformConnection(
        agent_id=agent.id,
        platform=platform,
        upstream_url=upstream_url,
        secret_encrypted=encrypt_secret(secret) if secret else None,
        config_json=config,
        created_by=actor,
    )
    session.add(connection)
    session.flush()
    return connection, made


def for_agent(session: Session, agent: Agent) -> list[PlatformConnection]:
    return list(
        session.scalars(
            select(PlatformConnection)
            .where(PlatformConnection.agent_id == agent.id)
            .order_by(PlatformConnection.created_at)
        )
    )


def find(session: Session, connection_id: str, platform: str) -> PlatformConnection | None:
    """The enabled connection a hook URL names, whichever tenant owns it.

    A platform's delivery carries no tenant: the connection id in its URL is how the
    gateway learns whose agent the call is, so the lookup is cross-tenant by design and
    the caller must bind the session to the connection's ``org_id`` before anything
    else, and verify the delivery with the connection's own secret.
    """
    with system_scope("platform hook: finding the connection a webhook URL names", routine=True):
        connection = session.get(PlatformConnection, connection_id)
    if connection is None or connection.platform != platform or not connection.enabled:
        return None
    return connection


def secret_of(connection: PlatformConnection) -> str | None:
    if not connection.secret_encrypted:
        return None
    try:
        return decrypt_secret(connection.secret_encrypted)
    except Exception:  # noqa: BLE001 - an unreadable secret verifies nothing
        return None


def to_json(connection: PlatformConnection, base_url: str = "") -> dict[str, Any]:
    path = f"/v1/hooks/{connection.platform.replace('_', '-')}/{connection.id}"
    return {
        "id": connection.id,
        "platform": connection.platform,
        "upstream_url": connection.upstream_url,
        "has_secret": bool(connection.secret_encrypted),
        "config": connection.config_json or {},
        "enabled": connection.enabled,
        "hook_url": f"{base_url.rstrip('/')}{path}" if base_url else path,
        "created_at": connection.created_at.isoformat() if connection.created_at else None,
    }


class ForwardFailed(RuntimeError):
    """The tool server could not be reached or answered with an error. The message
    is safe to speak: it names no host, header or body."""


def forward(connection: PlatformConnection, body: bytes, headers: dict[str, str]) -> httpx.Response:
    """POST ``body`` to the connection's tool server and return its answer.

    Checked again here, against what the host resolves to now (see the module
    docstring). Redirects are not followed: a 302 to an internal address is the same
    relay by another route. The client resolves the name again when it connects, so a
    resolver that answers differently twice in a second is not stopped by this check;
    the registration-time rules and the operator who registered the host are.
    """
    url = connection.upstream_url or ""
    try:
        check_upstream(url)
    except ConnectionError_ as exc:
        raise ForwardFailed("the tool server is not configured correctly") from exc
    host = urlsplit(url).hostname or ""
    if not _local_upstreams_allowed() and not _resolves_public(host):
        raise ForwardFailed("the tool server is not reachable from the gateway")
    try:
        with httpx.Client(timeout=FORWARD_TIMEOUT_S, follow_redirects=False) as client:
            response = client.post(url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise ForwardFailed("the tool server did not answer") from exc
    if len(response.content) > MAX_FORWARD_BYTES:
        raise ForwardFailed("the tool server's answer was too large")
    return response
