"""The setup key `agentfox init --key` presents.

It is an operator token in everything but reach (``platform/identity/operators``):
stored as a hash with a findable prefix, shown in full once when it is made, expiring
(``onboarding_key_ttl_days``), revocable from the token list or by rotating it, and
written to the audit log when it is issued or revoked. Its ``afi_`` prefix keeps it
from ever authenticating as the operator; the onboarding runner routes accept nothing
else.

It acts for the user who made it, so every use checks that user is still active and
still holds a role that may change the registry: deactivating someone, or moving them
to a read-only role, ends their key with it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import ApiToken, OnboardingSession, User, utcnow
from agentfox.core.tenancy import system_scope
from agentfox.platform.identity.keyhash import hash_key
from agentfox.platform.identity.operators import (
    _token_is_live,
    issue_token,
    prefix_length,
    resolve_token_record,
    revoke_token,
)

SETUP_KEY_PREFIX = "afi_"
#: The ``ApiToken.name`` every setup key carries: how they are told from operator tokens.
SETUP_KEY_NAME = "agentfox init setup key"


class SetupKeyRefused(Exception):
    """The key is well formed but may not be used. The message says why, for the CLI."""


def live_key(session: Session, user: User) -> ApiToken | None:
    """The user's current setup key, if it is neither revoked nor expired."""
    now = utcnow()
    tokens = session.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == user.id, ApiToken.name == SETUP_KEY_NAME)
        .order_by(ApiToken.created_at.desc())
    )
    return next((t for t in tokens if _token_is_live(t, now)), None)


def mint(
    session: Session, user: User, row: OnboardingSession, *, reason: str
) -> tuple[ApiToken, str]:
    """A new setup key for ``user``, revoking any they had. The raw key is returned
    once and never stored."""
    actor = user.email or user.id
    for old in session.scalars(
        select(ApiToken).where(
            ApiToken.user_id == user.id,
            ApiToken.name == SETUP_KEY_NAME,
            ApiToken.revoked_at.is_(None),
        )
    ):
        revoke_token(session, old.id, actor=actor, reason=f"setup key replaced: {reason}")
    token, raw = issue_token(
        session,
        user,
        name=SETUP_KEY_NAME,
        ttl_days=get_settings().onboarding_key_ttl_days or None,
        actor=actor,
        reason=reason,
        prefix=SETUP_KEY_PREFIX,
    )
    row.init_key = token.id
    session.flush()
    return token, raw


def describe(token: ApiToken | None, raw: str | None = None) -> dict[str, object]:
    """The key as the dashboard sees it: the value only when it was just made."""
    return {
        "value": raw,
        "createdNow": raw is not None,
        "hasKey": token is not None,
        "prefix": token.key_prefix if token is not None else None,
        "createdAt": token.created_at.isoformat() if token and token.created_at else None,
        "expiresAt": token.expires_at.isoformat() if token and token.expires_at else None,
    }


def _adopt_legacy(session: Session, raw: str) -> ApiToken | None:
    """A key from before keys were hashed, still in plaintext on its session row.

    Moved onto a token the first time it is used (the same "re-store on first use" the
    operator tokens' hash upgrade does), so a running `agentfox init` keeps working
    through a deploy that ships before the migration. The migration does the same for
    every row at once.
    """
    with system_scope("onboarding legacy setup key", routine=True):
        row = session.scalar(select(OnboardingSession).where(OnboardingSession.init_key == raw))
        if row is None:
            return None
        user = session.get(User, row.user_id)
        if user is None:
            return None
        token = ApiToken(
            user_id=user.id,
            name=SETUP_KEY_NAME,
            key_prefix=raw[: prefix_length(SETUP_KEY_PREFIX)],
            key_hash=hash_key(raw),
            expires_at=_legacy_expiry(),
            org_id=row.org_id,
        )
        session.add(token)
        session.flush()
        row.init_key = token.id
        session.flush()
        return token


def _legacy_expiry() -> dt.datetime | None:
    days = get_settings().onboarding_key_ttl_days
    return utcnow() + dt.timedelta(days=days) if days else None


def resolve(
    session: Session, raw: str, *, allowed_roles: Collection[str]
) -> tuple[ApiToken, User, OnboardingSession]:
    """The token, its user and their onboarding row for a presented setup key.

    Raises ``LookupError`` for a key that matches nothing live, ``SetupKeyRefused``
    for one whose user may no longer use it.
    """
    if not raw.startswith(SETUP_KEY_PREFIX):
        raise LookupError(raw)
    token = resolve_token_record(session, raw, prefix=SETUP_KEY_PREFIX)
    if token is None:
        token = _adopt_legacy(session, raw)
    if token is None or token.name != SETUP_KEY_NAME:
        raise LookupError(raw)
    with system_scope("onboarding setup key owner", routine=True):
        user = session.get(User, token.user_id)
        row = session.scalar(
            select(OnboardingSession).where(OnboardingSession.user_id == token.user_id)
        )
    if user is None or not user.active:
        raise SetupKeyRefused(
            "The account this setup key belongs to is no longer active. Ask an admin for access."
        )
    if user.role not in allowed_roles:
        raise SetupKeyRefused(
            f"This setup key's owner now has the '{user.role}' role, which can't add agents. "
            "Ask someone who can to make a new key."
        )
    if row is None:  # a token named like a setup key, minted some other way
        raise LookupError(raw)
    return token, user, row
