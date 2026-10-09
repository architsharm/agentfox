"""Operators: the humans and CI that use the control plane, and how they authenticate.

Creating an operator, minting and revoking their API tokens, verifying a presented
token, and the deployment's authentication posture (whether the development identity
header is accepted). The CLI and the gateway both use these; resolving a request to a
principal is the gateway's job (`agentfox.apps.gateway.auth`).

API tokens are hashed (`keyhash`) and prefix-narrowed, so verifying one is one hash
comparison rather than one per token, and a database disclosure does not hand over
working credentials. Lookups run in system scope because the token is what says which
tenant to scope to.
"""

from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import DEV_ENVIRONMENTS as _DEV_ENVIRONMENTS
from agentfox.core.config import get_settings
from agentfox.core.models import ApiToken, User, utcnow
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.platform.identity.keyhash import check_key, hash_key
from agentfox.platform.ledger.operator_log import record

API_KEY_PREFIX = "nom_api_"
#: How much of the key identifies the row. Long enough to make the candidate set one
#: token in practice, short enough to be safe to log and to print in a listing.
PREFIX_LENGTH = len(API_KEY_PREFIX) + 8


#: Environments where an unverified identity header is acceptable. Defined in
#: core.config (the published-secrets guard uses the same set) and re-exported here.
DEV_ENVIRONMENTS = _DEV_ENVIRONMENTS


def header_identity_allowed() -> bool:
    """Whether the development identity header may be used.

    ``auth_mode`` is explicit when set. Left at ``auto`` it follows the environment,
    and treats anything it does not recognise as production — an unrecognised value is
    much more likely to be a misconfiguration than an intent to disable authentication.
    """
    settings = get_settings()
    mode = (settings.auth_mode or "auto").lower()
    if mode == "development":
        return True
    if mode in ("token", "oidc", "strict"):
        return False
    return settings.environment.lower() in DEV_ENVIRONMENTS


def _why_header_refused() -> str:
    settings = get_settings()
    mode = (settings.auth_mode or "auto").lower()
    if mode != "auto":
        return (
            f"this deployment sets auth_mode='{settings.auth_mode}', so API tokens are "
            "required and the X-AgentFox-User header is not accepted."
        )
    return (
        f"this deployment runs in environment '{settings.environment}', which is not a "
        "development environment, so the X-AgentFox-User header is not accepted."
    )


def auth_posture() -> str:
    """One line saying how callers are authenticated, for the startup banner and logs.

    Starts with ``DEVELOPMENT`` exactly when the identity header is accepted, so a
    caller can key a warning off it without re-deriving the rule.
    """
    settings = get_settings()
    if header_identity_allowed():
        return (
            f"DEVELOPMENT auth (environment={settings.environment}, "
            f"auth_mode={settings.auth_mode}): /api requests without a token act as the "
            "user named in X-AgentFox-User, or admin@example.com — anyone who can reach "
            "this port is that user. Never expose it."
        )
    return (
        f"token auth (environment={settings.environment}, auth_mode={settings.auth_mode}): "
        "/api needs 'Authorization: Bearer nom_api_…'; an agent key must be valid."
    )


# ---------------------------------------------------------------------------
# Operator tokens
# ---------------------------------------------------------------------------


#: The roles an operator may hold — the keys of the matrix in gateway/deps.py.
OPERATOR_ROLES = ("owner", "admin", "security", "compliance", "developer", "auditor")


class OperatorExists(ValueError):
    """An operator with that email already exists in that tenant."""


def create_operator(
    session: Session,
    email: str,
    *,
    role: str = "owner",
    name: str = "",
    org_id: str | None = None,
    actor: str = "",
    reason: str = "",
) -> User:
    """Create an operator in a tenant, without loading any demo data.

    The first-operator path for a self-hosted deployment. Before it, the only ways to
    get a user into a fresh database were GitHub sign-in (which needs an OAuth app
    and a dashboard) and `agentfox admin seed` (which also writes demo agents,
    policies and traffic into what is meant to be a production database).
    """
    email = email.strip()
    if "@" not in email:
        raise ValueError(f"'{email}' is not an email address")
    if role not in OPERATOR_ROLES:
        raise ValueError(f"unknown role '{role}'. Choose one of: {', '.join(OPERATOR_ROLES)}")
    org = org_id or get_settings().org_id
    with system_scope("creating an operator", routine=True):
        existing = session.scalar(select(User).where(User.email == email, User.org_id == org))
    if existing is not None:
        raise OperatorExists(f"'{email}' already exists in {org} (role {existing.role})")
    bind_session(session, org)
    user = User(email=email, name=name or email.split("@", 1)[0], role=role, org_id=org)
    session.add(user)
    session.flush()
    record(
        session,
        "operator.user.created",
        actor=actor or "cli",
        reason=reason or f"operator '{email}' created with role {role}",
        subject_type="user",
        subject_id=user.id,
        after={"email": email, "role": role, "org_id": org},
    )
    return user


def issue_token(
    session: Session,
    user: User,
    *,
    name: str = "",
    ttl_days: int | None = 365,
    actor: str = "",
    reason: str = "",
) -> tuple[ApiToken, str]:
    """Mint an operator token. The raw value is returned once and never stored.

    Only a hash is persisted (`keyhash`), so a database disclosure does not hand over
    working credentials — which is the whole reason the audit log and the token store
    can sit in the same database.

    Minting an identity is recorded. The credential is identified by the token id in
    the entry's subject rather than by any part of the key — the chain's capture-time
    redaction treats the key prefix as a secret and scrubs it, which is correct, and
    recording a field that always reads `<redacted>` would only look like evidence.
    """
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32).replace("-", "").replace("_", "")[:40]
    token = ApiToken(
        user_id=user.id,
        name=name or "unnamed",
        key_prefix=raw[:PREFIX_LENGTH],
        key_hash=hash_key(raw),
        expires_at=(utcnow() + dt.timedelta(days=ttl_days)) if ttl_days else None,
        org_id=user.org_id,
    )
    session.add(token)
    session.flush()
    record(
        session,
        "operator.credential.issued",
        actor=actor or user.email or user.id,
        reason=reason or f"token '{token.name}' issued",
        subject_type="api_token",
        subject_id=token.id,
        after={
            "name": token.name,
            "for_user": user.id,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        },
    )
    return token, raw


def revoke_token(session: Session, token_id: str, *, actor: str = "", reason: str = "") -> bool:
    """End a credential.

    The window between issue and revoke is the exposure window, and it can only be
    reconstructed if both ends are recorded.
    """
    token = session.get(ApiToken, token_id)
    if token is None or token.revoked_at is not None:
        return False
    token.revoked_at = utcnow()
    session.flush()
    record(
        session,
        "operator.credential.revoked",
        actor=actor or "unknown",
        reason=reason or "token revoked",
        subject_type="api_token",
        subject_id=token.id,
        before={
            "name": token.name,
            "issued_at": token.created_at.isoformat()
            if getattr(token, "created_at", None)
            else None,
        },
    )
    return True


def _token_is_live(token: ApiToken, now: dt.datetime) -> bool:
    if token.revoked_at is not None:
        return False
    if token.expires_at is None:
        return True
    expires = token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.UTC)
    return expires > now


def resolve_token(session: Session, raw: str) -> User | None:
    """Verify an operator token and return its user, or None.

    Runs in system scope because the token store is the thing that tells us which
    tenant to scope to. Nothing else on this path reads tenant data.
    """
    token = resolve_token_record(session, raw)
    if token is None:
        return None
    with system_scope("resolving an operator token to its user", routine=True):
        user = session.get(User, token.user_id)
    if user is None or not user.active:
        return None
    return user


def resolve_token_record(session: Session, raw: str) -> ApiToken | None:
    """The live token row a raw operator token verifies against, or None.

    Separate from :func:`resolve_token` for the one caller that needs the credential
    rather than the person: signing out revokes *this* token and no other.
    """
    if not raw.startswith(API_KEY_PREFIX):
        return None
    now = utcnow()
    with system_scope("resolving an operator token to its user", routine=True):
        candidates = list(
            session.scalars(select(ApiToken).where(ApiToken.key_prefix == raw[:PREFIX_LENGTH]))
        )
        for token in candidates:
            if not _token_is_live(token, now):
                continue
            matches, upgraded = check_key(token.key_hash, raw)
            if not matches:
                continue
            if upgraded:
                token.key_hash = upgraded
                session.flush()
            return token
    return None
