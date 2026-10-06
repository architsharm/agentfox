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

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import Agent, Identity, User
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.platform.identity.operators import (
    API_KEY_PREFIX,
    _why_header_refused,
    header_identity_allowed,
    resolve_token,
)

log = logging.getLogger(__name__)


def _is_sandbox_org(org_id: str | None) -> bool:
    """Whether a tenant is a public-playground sandbox.

    Imported lazily to keep this module free of a dependency on the playground.
    Sandbox tenants hold fixture data belonging to an anonymous visitor and no
    operator, so nothing here may ever resolve a principal into one — see
    :func:`authenticate` and :func:`resolve_agent`.
    """
    from agentfox.apps.gateway.playground_sessions import is_sandbox_id

    return is_sandbox_id(org_id or "")


class AuthenticationRequired(Exception):
    """No usable credential was presented."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


# ---------------------------------------------------------------------------
# Agent credentials — the inline path
# ---------------------------------------------------------------------------


def resolve_agent(session: Session, raw: str) -> tuple[Identity, str] | None:
    """Verify an agent credential and return its identity and tenant.

    The tenant is the one that owns the agent, so a governed completion runs in its
    owner's org. The lookup itself runs in system scope: filtered to the default org,
    an agent belonging to any other tenant could not authenticate at all.
    """
    from agentfox.platform.identity.service import verify_credential

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
