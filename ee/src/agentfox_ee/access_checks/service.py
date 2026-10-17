"""The customer's own access-control service, asked before a tool call runs.

AgentFox grants say what an *agent* may do. Whether the *person* it acts for may do
it usually lives elsewhere: the customer's RBAC service, an OPA or Cedar server, an
internal entitlements API. Copying those permissions into AgentFox would leave two
sources of truth that drift. So a workspace registers its service here, and a tool
call that matches is posted to it, with the end user, before it runs:

    POST <url>
    {"input": {"subject": "u_123", "groups": ["support"], "agent": "support-bot",
               "tool": "refunds.issue", "impact": "write", "arguments": {...},
               "environment": "production"},
     ...the same fields at the top level}

The ``input`` wrapper is what OPA's data API expects; the top-level copy suits a
purpose-built endpoint. Accepted answers: ``{"allow": bool, "reason"?}``,
``{"decision": "allow" | "deny" | "permit" | "Allow" | "Deny"}`` (Cedar style), and
OPA's ``{"result": bool}`` or ``{"result": {"allow": bool, "reason"?}}``.

* **A deny** blocks the call, or sends it to a person (``on_deny="escalate"``).
* **An outage** (timeout, error, an answer none of the shapes above) is a deny when
  ``fail_mode="closed"`` (the default: an access check that fails open is not one),
  and lets the call through, recorded, when ``"open"``.
* **No end user named**: the authorizer is skipped, unless ``require_principal``, in
  which case the call is denied: the service cannot decide for nobody.
* **Answers are cached** for ``cache_seconds`` per (end user, groups, agent, tool,
  arguments), so a loop does not call the service on every step. Outages are not.

Egress follows the custom-model rules: a public address only when the deployment
allows egress, a private one only when it allows private hosts, link-local never,
through `core.outbound.guarded_post` (address pinned, redirects refused).
"""

from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core import outbound
from agentfox.core.config import get_settings
from agentfox.core.crypto import DecryptionFailed, EncryptionNotConfigured, decrypt_secret
from agentfox.core.models import ExternalAuthorizer, utcnow
from agentfox.core.tenancy import session_org

MIN_TIMEOUT_MS = 50
MAX_TIMEOUT_MS = 3000
MAX_RESPONSE_BYTES = 64_000
MAX_CACHE_ENTRIES = 5000

_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_HEADER = re.compile(r"^[A-Za-z0-9-]{1,100}$")


class AuthorizerUnavailable(RuntimeError):
    """The service could not answer: refused, unreachable, or answered nonsense."""


class AuthorizerSpec(BaseModel):
    key: str
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=1000)
    tools: list[str] = Field(default_factory=lambda: ["*"])
    agents: list[str] = Field(default_factory=list)
    timeout_ms: int = Field(800, ge=MIN_TIMEOUT_MS, le=MAX_TIMEOUT_MS)
    fail_mode: Literal["open", "closed"] = "closed"
    on_deny: Literal["block", "escalate"] = "block"
    require_principal: bool = False
    cache_seconds: int = Field(60, ge=0, le=3600)
    auth_header: str = ""
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip().lower()
        if not _KEY.match(v):
            raise ValueError("key: 2-63 lowercase letters, digits, '-' or '_'")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        try:
            url = httpx.URL(v)
        except (httpx.InvalidURL, TypeError, ValueError) as exc:
            raise ValueError(f"not a valid URL: {exc}") from exc
        if url.scheme not in ("http", "https") or not url.host:
            raise ValueError("the authorizer URL must be http(s) with a host")
        return v

    @field_validator("tools", "agents")
    @classmethod
    def _patterns(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(p.strip() for p in v or [] if p and p.strip()))
        if len(out) > 200:
            raise ValueError("at most 200 entries")
        return out

    @field_validator("auth_header")
    @classmethod
    def _header(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not _HEADER.match(v):
            raise ValueError("auth_header must be a header name, like Authorization or X-Api-Key")
        return v


def spec_of(row: ExternalAuthorizer) -> AuthorizerSpec:
    return AuthorizerSpec(
        key=row.key,
        name=row.name or row.key,
        url=row.url,
        tools=list(row.tools_json or ["*"]),
        agents=list(row.agents_json or []),
        timeout_ms=row.timeout_ms,
        fail_mode=row.fail_mode if row.fail_mode in ("open", "closed") else "closed",
        on_deny=row.on_deny if row.on_deny in ("block", "escalate") else "block",
        require_principal=bool(row.require_principal),
        cache_seconds=row.cache_seconds,
        auth_header=row.auth_header or "",
        enabled=row.enabled,
    )


def to_json(row: ExternalAuthorizer) -> dict[str, Any]:
    """What the API shows. Never the credential, only whether one is stored."""
    spec = spec_of(row)
    return {
        **spec.model_dump(),
        "has_secret": bool(row.auth_secret_encrypted),
        "version": row.version,
        "created_by": row.created_by,
        "last_called_at": row.last_called_at.isoformat() if row.last_called_at else None,
        "last_error": row.last_error,
    }


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    subject: str
    groups: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, value: Any) -> Principal | None:
        """A subject string, or ``{"subject", "groups"?, "attributes"?}``."""
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return cls(subject=value.strip()[:200]) if value.strip() else None
        if isinstance(value, dict) and str(value.get("subject") or "").strip():
            groups = value.get("groups") or []
            attrs = value.get("attributes") or {}
            return cls(
                subject=str(value["subject"]).strip()[:200],
                groups=tuple(str(g) for g in groups if g)[:100] if isinstance(groups, list) else (),
                attributes=attrs if isinstance(attrs, dict) else {},
            )
        return None


@dataclass
class AuthzDecision:
    authorizer: str
    allowed: bool
    reason: str
    on_deny: str
    outcome: str  # allow | deny | unavailable | no_principal
    cached: bool = False
    latency_ms: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "authorizer": self.authorizer,
            "allowed": self.allowed,
            "outcome": self.outcome,
            "reason": self.reason,
            "on_deny": self.on_deny,
            "cached": self.cached,
            "latency_ms": round(self.latency_ms, 1),
        }


_cache: dict[tuple, tuple[float, bool, str]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_get(key: tuple) -> tuple[bool, str] | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        if hit[0] < time.monotonic():
            _cache.pop(key, None)
            return None
        return hit[1], hit[2]


def _cache_put(key: tuple, ttl: int, allowed: bool, reason: str) -> None:
    if ttl <= 0:
        return
    with _cache_lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            now = time.monotonic()
            for k in [k for k, v in _cache.items() if v[0] < now] or list(_cache)[:500]:
                _cache.pop(k, None)
        _cache[key] = (time.monotonic() + ttl, allowed, reason)


def _applies(spec: AuthorizerSpec, agent_slug: str | None, tool_key: str) -> bool:
    if spec.agents and agent_slug not in spec.agents:
        return False
    return any(fnmatch.fnmatchcase(tool_key, p) for p in spec.tools or ["*"])


def egress_refusal(url: str) -> str | None:
    try:
        ip = outbound.vet(httpx.URL(url), "the authorizer")
    except (outbound.OutboundRefused, httpx.InvalidURL, ValueError) as exc:
        return str(exc)
    if ipaddress.ip_address(ip).is_global and not get_settings().allow_egress:
        return (
            "the authorizer is on the public internet and this deployment has egress "
            "switched off (AGENTFOX_ALLOW_EGRESS). Reach it on this deployment's own "
            "network, or turn egress on where the gateway runs"
        )
    return None


def parse_answer(body: Any) -> tuple[bool, str]:
    """(allowed, reason) from the answer shapes in the module docstring."""
    if isinstance(body, bool):
        return body, ""
    if not isinstance(body, dict):
        raise AuthorizerUnavailable("the authorizer did not answer with a JSON object")
    reason = str(body.get("reason") or body.get("message") or "")[:500]
    if isinstance(body.get("allow"), bool):
        return body["allow"], reason
    if isinstance(body.get("allowed"), bool):
        return body["allowed"], reason
    decision = body.get("decision")
    if isinstance(decision, str):
        verdict = decision.strip().lower()
        if verdict in ("allow", "permit", "allowed"):
            return True, reason
        if verdict in ("deny", "forbid", "denied"):
            return False, reason
    if "result" in body:
        return parse_answer(body["result"])
    raise AuthorizerUnavailable("the authorizer's answer had no allow or decision")


def _headers(row: ExternalAuthorizer) -> dict[str, str]:
    if not (row.auth_header and row.auth_secret_encrypted):
        return {}
    try:
        return {row.auth_header: decrypt_secret(row.auth_secret_encrypted)}
    except (EncryptionNotConfigured, DecryptionFailed) as exc:
        raise AuthorizerUnavailable(
            "its stored credential could not be decrypted on this deployment"
        ) from exc


def call(row: ExternalAuthorizer, payload: dict[str, Any]) -> tuple[bool, str]:
    """Ask the service once. Raises `AuthorizerUnavailable`."""
    refused = egress_refusal(row.url)
    if refused:
        raise AuthorizerUnavailable(refused)
    try:
        resp = outbound.guarded_post(
            row.url,
            what=f"the '{row.key}' authorizer",
            json_body={"input": payload, **payload},
            max_bytes=MAX_RESPONSE_BYTES,
            timeout=max(MIN_TIMEOUT_MS, min(row.timeout_ms, MAX_TIMEOUT_MS)) / 1000,
            headers=_headers(row),
        )
        body = resp.json()
    except outbound.OutboundRefused as exc:
        raise AuthorizerUnavailable(str(exc)) from exc
    except ValueError as exc:
        raise AuthorizerUnavailable("the authorizer did not answer with JSON") from exc
    return parse_answer(body)


def authorize(
    session: Session,
    *,
    agent_slug: str | None,
    tool_key: str,
    impact: str,
    arguments: dict[str, Any] | None,
    principal: Principal | None,
    environment: str = "production",
) -> list[AuthzDecision]:
    """Ask every enabled authorizer this call matches. Empty when none does."""
    rows = [
        r
        for r in session.scalars(
            select(ExternalAuthorizer)
            .where(ExternalAuthorizer.enabled.is_(True))
            .order_by(ExternalAuthorizer.key)
        )
    ]
    out: list[AuthzDecision] = []
    for row in rows:
        try:
            spec = spec_of(row)
        except ValueError:
            continue
        if not _applies(spec, agent_slug, tool_key):
            continue
        if principal is None:
            if spec.require_principal:
                out.append(
                    AuthzDecision(
                        spec.key,
                        False,
                        "no end user was named for this call, and this access check needs one",
                        spec.on_deny,
                        "no_principal",
                    )
                )
            continue
        payload = {
            "subject": principal.subject,
            "groups": list(principal.groups),
            "attributes": principal.attributes,
            "agent": agent_slug,
            "tool": tool_key,
            "impact": impact,
            "arguments": arguments or {},
            "environment": environment,
        }
        args_hash = hashlib.sha256(
            json.dumps(
                {"arguments": arguments or {}, "attributes": principal.attributes},
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        cache_key = (
            session_org(session),
            row.id,
            row.version,
            principal.subject,
            principal.groups,
            agent_slug,
            tool_key,
            args_hash,
        )
        hit = _cache_get(cache_key)
        if hit is not None:
            allowed, reason = hit
            out.append(
                AuthzDecision(
                    spec.key,
                    allowed,
                    reason,
                    spec.on_deny,
                    "allow" if allowed else "deny",
                    cached=True,
                )
            )
            continue
        started = time.perf_counter()
        try:
            allowed, reason = call(row, payload)
        except AuthorizerUnavailable as exc:
            row.last_error = str(exc)[:500]
            row.last_called_at = utcnow()
            closed = spec.fail_mode == "closed"
            out.append(
                AuthzDecision(
                    spec.key,
                    not closed,
                    f"the access check could not be reached ({exc})"
                    + ("; failing closed" if closed else "; failing open"),
                    spec.on_deny,
                    "unavailable",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            )
            continue
        row.last_error = None
        row.last_called_at = utcnow()
        _cache_put(cache_key, spec.cache_seconds, allowed, reason)
        out.append(
            AuthzDecision(
                spec.key,
                allowed,
                reason,
                spec.on_deny,
                "allow" if allowed else "deny",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Managing
# ---------------------------------------------------------------------------


def list_authorizers(session: Session) -> list[ExternalAuthorizer]:
    return list(session.scalars(select(ExternalAuthorizer).order_by(ExternalAuthorizer.key)))


def get_authorizer(session: Session, key: str) -> ExternalAuthorizer | None:
    return session.scalar(select(ExternalAuthorizer).where(ExternalAuthorizer.key == key))


def save_authorizer(
    session: Session,
    spec: AuthorizerSpec,
    *,
    secret: str | None,
    actor: str,
) -> tuple[ExternalAuthorizer, bool]:
    """Create or update by key. ``secret=None`` keeps the stored one, ``""`` clears it."""
    from agentfox.core.crypto import encrypt_secret
    from agentfox.platform.ledger import chain

    row = get_authorizer(session, spec.key)
    created = row is None
    if row is None:
        row = ExternalAuthorizer(key=spec.key, created_by=actor)
        session.add(row)
    row.name = spec.name
    row.url = spec.url
    row.tools_json = spec.tools or ["*"]
    row.agents_json = spec.agents
    row.timeout_ms = spec.timeout_ms
    row.fail_mode = spec.fail_mode
    row.on_deny = spec.on_deny
    row.require_principal = spec.require_principal
    row.cache_seconds = spec.cache_seconds
    row.auth_header = spec.auth_header
    row.enabled = spec.enabled
    if secret is not None:
        row.auth_secret_encrypted = encrypt_secret(secret) if secret else None
    if not spec.auth_header:
        row.auth_secret_encrypted = None
    row.version = 1 if created else (row.version or 1) + 1
    session.flush()
    chain.append(
        session,
        "authorizer.created" if created else "authorizer.updated",
        actor_type="user",
        actor_id=actor,
        subject_type="external_authorizer",
        subject_id=row.id,
        payload={k: v for k, v in to_json(row).items() if k not in ("last_error",)},
    )
    return row, created


def delete_authorizer(session: Session, row: ExternalAuthorizer, *, actor: str) -> None:
    from agentfox.platform.ledger import chain

    chain.append(
        session,
        "authorizer.deleted",
        actor_type="user",
        actor_id=actor,
        subject_type="external_authorizer",
        subject_id=row.id,
        payload={"key": row.key, "url": row.url},
    )
    session.delete(row)
    session.flush()


__all__ = [
    "AuthorizerSpec",
    "AuthorizerUnavailable",
    "AuthzDecision",
    "Principal",
    "authorize",
    "call",
    "clear_cache",
    "delete_authorizer",
    "get_authorizer",
    "list_authorizers",
    "parse_answer",
    "save_authorizer",
    "spec_of",
    "to_json",
]
