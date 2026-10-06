"""Principal resolution — who is calling, and which tenant they speak for.

The control plane never trusts an unverified ``X-Nometria-User`` header on its own:
if it did, anyone who could reach the port would be any user they named, with write
access to policy, controls and the kill switch. Confining that header to development
is enforced at runtime, not by convention.

Tenant isolation on its own is a lock with the key left in:
filtering by ``org_id`` is exact and pointless if the caller chooses their own
identity. The two only work as a pair.

Three principals, resolved here and nowhere else:

* **Operators** — humans and CI using the control plane. API tokens, argon2-hashed,
  prefix-narrowed so verification is one hash comparison rather than one per token.
* **Agents** — the inline enforcement path. Agent credentials bind the tenant that
  owns the agent, so a governed completion runs in its owner's org rather than the
  default one.
* **Development** — the header, allowed only where it is obviously safe and refused
  everywhere else, loudly.

**Authentication precedes tenancy, so it runs in system scope.** We cannot filter by
tenant until we know whose tenant it is. That inversion is confined to the lookups on
this page, each of which resolves a *credential* and nothing else, and every one binds
the tenant immediately afterwards.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import DEV_ENVIRONMENTS as _DEV_ENVIRONMENTS
from agentfox.core.config import get_settings
from agentfox.core.models import Agent, ApiToken, Identity, User, utcnow
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.prove.audit.operator_log import record

log = logging.getLogger(__name__)

API_KEY_PREFIX = "nom_api_"
#: How much of the key identifies the row. Long enough to make the candidate set one
#: token in practice, short enough to be safe to log and to print in a listing.
PREFIX_LENGTH = len(API_KEY_PREFIX) + 8

_hasher = PasswordHasher()

#: Environments where an unverified identity header is acceptable. Defined in
#: core.config (the published-secrets guard uses the same set) and re-exported here.
DEV_ENVIRONMENTS = _DEV_ENVIRONMENTS


def _is_sandbox_org(org_id: str | None) -> bool:
    """Whether a tenant is a public-playground sandbox.

    Imported lazily to keep this module free of a dependency on the playground.
    Sandbox tenants hold fixture data belonging to an anonymous visitor and no
    operator, so nothing here may ever resolve a principal into one — see
    :func:`authenticate` and :func:`resolve_agent`.
    """
    from agentfox.gateway.playground_sessions import is_sandbox_id

    return is_sandbox_id(org_id or "")


class AuthenticationRequired(Exception):
    """No usable credential was presented."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


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
            "required and the X-Nometria-User header is not accepted."
        )
    return (
        f"this deployment runs in environment '{settings.environment}', which is not a "
        "development environment, so the X-Nometria-User header is not accepted."
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
            "user named in X-Nometria-User, or admin@example.com — anyone who can reach "
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

    Only the argon2 hash is persisted, so a database disclosure does not hand over
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
        key_hash=_hasher.hash(raw),
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
            try:
                _hasher.verify(token.key_hash, raw)
            except VerifyMismatchError:
                continue
            return token
    return None


# ---------------------------------------------------------------------------
# Agent credentials — the inline path
# ---------------------------------------------------------------------------


def resolve_agent(session: Session, raw: str) -> tuple[Identity, str] | None:
    """Verify an agent credential and return its identity and tenant.

    This path bound no tenant at all before: every governed completion ran in the
    deployment's default org whatever the agent's owner. Under isolation that was
    doubly wrong — the credential lookup itself was filtered to the default org, so an
    agent belonging to any other tenant simply could not authenticate.
    """
    from agentfox.identity.service import verify_credential

    with system_scope("resolving an agent credential to its identity", routine=True):
        identity = verify_credential(session, raw)
        if identity is None:
            return None
        org = identity.org_id
        if identity.agent_id:
            agent = session.get(Agent, identity.agent_id)
            if agent is not None:
                org = agent.org_id
    if _is_sandbox_org(org):
        # A playground sandbox seeds its own agent credentials. They are random and
        # never shown to the visitor, so this is defence in depth rather than a known
        # path: the inline API is not a way into a sandbox, whatever credential is
        # presented. It does not make sandbox credentials secret — it makes them
        # useless here.
        log.warning("refused an agent credential resolving to a playground sandbox")
        return None
    return identity, org


# ---------------------------------------------------------------------------
# The one entry point
# ---------------------------------------------------------------------------


def authenticate(
    session: Session,
    *,
    authorization: str | None,
    header_user: str | None,
) -> User:
    """Resolve an operator, bind their tenant, or refuse.

    Ordered so the real credential always wins: a deployment that has tokens
    configured cannot be downgraded to header identity by a caller who simply omits
    the ``Authorization`` header.
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]

    if token and token.startswith(API_KEY_PREFIX):
        user = resolve_token(session, token)
        if user is None:
            raise AuthenticationRequired("invalid, expired or revoked API token")
        bind_session(session, user.org_id)
        return user

    if not header_identity_allowed():
        # Naming the reason matters: the commonest cause of this in practice is a
        # developer running against a deployment they did not realise was production.
        # It is not always the environment, though — an explicit auth_mode refuses the
        # header in development too, and blaming 'development' for that sent people
        # looking in the wrong place.
        raise AuthenticationRequired(
            f"authentication required: {_why_header_refused()} Send "
            "'Authorization: Bearer nom_api_…' — create one with "
            "`agentfox admin auth issue <email>`."
        )

    email = header_user or "admin@example.com"
    with system_scope("resolving a development identity header", routine=True):
        candidates = list(session.scalars(select(User).where(User.email == email)))
    # Email is unique per tenant, not globally (see models.User), so this lookup can
    # see more than one row. Two rules resolve it, and both are stated rather than
    # left to whichever row the database returns first:
    #   * a playground sandbox's fixture users are never operators;
    #   * the deployment's own configured tenant wins, then the lowest org_id, so the
    #     same header always resolves to the same user.
    operators = [u for u in candidates if not _is_sandbox_org(u.org_id)]
    default_org = get_settings().org_id
    operators.sort(key=lambda u: (u.org_id != default_org, u.org_id))
    user = operators[0] if operators else None
    if user is None or not user.active:
        raise AuthenticationRequired(
            f"unknown user '{email}'. Send X-Nometria-User or a nom_api_ bearer token."
        )
    log.debug("development identity header accepted for %s", email)
    bind_session(session, user.org_id)
    return user
