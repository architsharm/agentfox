"""Gateway dependencies — sessions, auth, RBAC.

The role matrix is enforced here. The property that matters for the
product's credibility: ``auditor`` can read everything and mutate nothing. An audit
log an auditor could alter is not an audit log.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.auth import AuthenticationRequired, authenticate, resolve_agent
from agentfox.core.db import get_session
from agentfox.core.models import Agent, Identity, User
from agentfox.core.tenancy import bind_session
from agentfox.platform.identity.operators import header_identity_allowed, resolve_token

log = logging.getLogger(__name__)

# Route family -> roles permitted to mutate. Everyone listed in READ_ROLES may read.
WRITE_ROLES: dict[str, set[str]] = {
    "registry": {"owner", "admin", "security", "developer"},
    "identity": {"owner", "admin", "security"},
    "approvals": {"owner", "admin", "security"},
    "policy": {"owner", "admin", "security", "developer"},
    "policy_production": {"owner", "admin", "security"},
    "eval": {"owner", "admin", "developer"},
    "compliance": {"owner", "admin", "compliance"},
    "evidence": {"owner", "admin", "security", "compliance", "auditor"},
    "users": {"owner", "admin"},
    # Filing a false positive is open to anyone who can read a decision, but
    # *acting* on one by suppressing a detector is a security decision — a developer
    # silencing a control to unblock a demo is the failure mode this separation exists
    # to prevent.
    "suppressions": {"owner", "admin", "security"},
    # Retrying a dead-lettered job re-runs already-attempted work (evidence
    # export, a red-team sweep) — same blast radius as the operation itself,
    # so the same roles that can run evidence/eval in the first place.
    "jobs": {"owner", "admin", "security", "compliance", "auditor", "developer"},
    # Judgment posture decides whether customer payloads leave the building at all.
    # A developer may change thresholds and run evaluations; turning on a tier that
    # sends a support ticket to a third party is not a developer's call to make, for
    # the same reason silencing a detector is not.
    "judgment_posture": {"owner", "admin", "security"},
    # Adding, pausing or running a monitor of a connected source: the same people who
    # can connect the source or scan it in the first place.
    "monitors": {"owner", "admin", "security", "developer"},
    # Where alerts about the tenant's findings are sent outside the deployment.
    "alerts": {"owner", "admin", "security"},
    # Enabling live probes points adversarial traffic at a running agent; the opt-in
    # is recorded with the caller's name, and it is a security call to make.
    "probes": {"owner", "admin", "security"},
    # Attesting a control against a framework: the people who answer for compliance,
    # and the auditor whose job the attestation is. Security and developers run the
    # controls; they do not sign off their own work.
    "control_review": {"owner", "admin", "compliance", "auditor"},
    # Changing how long data is kept, or purging now, destroys records. Not an
    # auditor's call (they read the record), and not security's alone.
    "retention": {"owner", "admin", "compliance"},
}

ALL_ROLES = {"owner", "admin", "security", "compliance", "developer", "auditor"}


def db(session: Session = Depends(get_session)) -> Session:
    return session


def get_agent_or_404(session: Session, slug: str) -> Agent:
    """Resolve an agent by slug, or the 404 every agent-slug route needs otherwise."""
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    if agent is None:
        raise HTTPException(404, f"unknown agent '{slug}'")
    return agent


def current_user(
    request: Request,
    session: Session = Depends(get_session),
    authorization: Annotated[str | None, Header()] = None,
    x_agentfox_user: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the control-plane caller and bind their tenant.

    All of the reasoning lives in :mod:`agentfox.apps.gateway.auth`, so there is exactly one
    place that decides who a caller is — the previous arrangement documented the
    development shortcut as "confined to this function", which was true and did not
    stop it being live in production.
    """
    try:
        user = authenticate(session, authorization=authorization, header_user=x_agentfox_user)
    except AuthenticationRequired as exc:
        raise HTTPException(status_code=401, detail=exc.detail) from exc
    request.state.user = user
    request.state.org_id = user.org_id
    activate_posture(session)
    return user


def activate_posture(session: Session) -> None:
    """Bind this tenant's judgment posture for the rest of the request.

    Called from the two dependencies that resolve who the caller is, because that is
    the moment the tenant is known and before any detector runs. Set without a reset
    for the same reason :func:`agentfox.core.tenancy.set_current_org` is: each request runs
    in its own context, so the binding is discarded with it and cannot leak into the
    next one.

    A failure here is deliberately swallowed. Posture decides which *optional* tiers
    are consulted; the deterministic tier is always on and is what the request is
    actually governed by. Taking an inline completion down because a settings row
    could not be read would turn a configuration problem into an outage, and the
    fallback — the deployment's own settings — is the stricter answer anyway.
    """
    from agentfox.capabilities.judgment import posture as _posture

    try:
        _posture.activate(_posture.load(session))
    except Exception as exc:  # noqa: BLE001
        log.warning("judgment posture unreadable, falling back to settings: %s", exc)


def require(family: str):
    """Dependency factory enforcing write permission for a route family."""

    def _guard(user: User = Depends(current_user)) -> User:
        allowed = WRITE_ROLES.get(family, set())
        if user.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"role '{user.role}' may not modify '{family}'. Permitted: {sorted(allowed)}."
                ),
            )
        return user

    return _guard


def agent_credential(
    session: Session = Depends(get_session),
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    """Extract an agent key from the inline request, and bind that agent's tenant.

    Without the binding every governed completion would run in the deployment's default
    org whatever the agent's owner — and because the credential lookup is itself
    tenant-filtered, an agent in any other tenant could not authenticate at all.

    An absent credential is not an error here: the inline path deliberately serves
    unregistered agents so that shadow traffic is *observed* rather than turned away.
    It simply stays in the default tenant. A presented ``nom_agt_`` key that
    does not verify is a 401. An operator token (``nom_api_``) binds its workspace.
    """
    if not (authorization and authorization.lower().startswith("bearer ")):
        activate_posture(session)
        return None
    token = authorization.split(" ", 1)[1].strip()
    if token.startswith("nom_api_"):
        # An operator's API token (Settings, API keys): the calls are that workspace's
        # traffic. Ignored, they were governed and recorded in the default tenant, so
        # a team integrating with the token from their own Settings page saw nothing
        # on their dashboard. It names no agent, so the agent is the one in the body.
        user = resolve_token(session, token)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid, expired or revoked API token")
        bind_session(session, user.org_id)
        activate_posture(session)
        return None
    if not token.startswith("nom_agt_"):
        activate_posture(session)
        return None
    resolved = resolve_agent(session, token)
    if resolved is None:
        # A presented agent key that does not verify — wrong, revoked, expired, or
        # belonging to a playground sandbox — is a refusal, in every environment.
        # Passing it through would attribute the call to whichever agent the body
        # named, so a made-up `nom_agt_` string would work exactly as well as the
        # real one. "No credential" (shadow traffic, served and
        # observed) and "a bad credential" are different things.
        raise HTTPException(
            status_code=401,
            detail=(
                "invalid, expired or revoked agent key. Issue a new one from the "
                "agent's Identity page (POST /api/identities/{id}/credentials), or "
                "send no Authorization header to be governed as an unregistered agent."
            ),
        )
    _identity, org_id = resolved
    bind_session(session, org_id)
    # After the binding, so an unregistered agent gets the default tenant's posture
    # rather than none at all — shadow traffic is governed, which is the point of
    # serving it in the first place.
    activate_posture(session)
    return token


def operator_or_agent(
    request: Request,
    session: Session = Depends(get_session),
    authorization: Annotated[str | None, Header()] = None,
    x_agentfox_user: Annotated[str | None, Header()] = None,
) -> User | Identity:
    """An operator, or an agent presenting its own key (``nom_agt_…``).

    For the few control-plane reads an agent needs about *itself* — the approval it
    is waiting on. The route decides what an agent may see; an operator goes
    through exactly the same resolution as `current_user`.
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token.startswith("nom_agt_"):
            resolved = resolve_agent(session, token)
            if resolved is None:
                raise HTTPException(status_code=401, detail="invalid, expired or revoked agent key")
            identity, org_id = resolved
            bind_session(session, org_id)
            request.state.org_id = org_id
            activate_posture(session)
            return identity
    return current_user(request, session, authorization, x_agentfox_user)


def ingest_credential(
    session: Session = Depends(get_session),
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    """Who may write telemetry through ``POST /v1/traces``.

    Ingest is a write: it stores spans, creates traces and registers the agents it
    sees. The inline enforcement routes serve an unauthenticated caller because they
    *govern* that caller's request; ingest governs nothing, it only records what the
    caller claims happened, so an anonymous caller there is someone forging the audit
    trail and the shadow-agent inventory.

    Outside development (``header_identity_allowed()`` is false) a caller must present
    either an agent key (``nom_agt_…``, the data-plane credential, bound to its
    agent's tenant) or an operator token (``nom_api_…``) whose role may write to the
    registry. Development keeps the old behaviour: no credential needed, default
    tenant — the same rule the control plane's identity header follows.
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if token and token.startswith("nom_agt_"):
        resolved = resolve_agent(session, token)
        if resolved is not None:
            bind_session(session, resolved[1])
            return token
    elif token and token.startswith("nom_api_"):
        user = resolve_token(session, token)
        if user is not None:
            allowed = WRITE_ROLES["registry"]
            if user.role not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"role '{user.role}' may not ingest telemetry. "
                        f"Permitted: {sorted(allowed)}."
                    ),
                )
            bind_session(session, user.org_id)
            return token

    if header_identity_allowed():
        return None
    raise HTTPException(
        status_code=401,
        detail=(
            "authentication required to ingest traces. Send 'Authorization: Bearer "
            "nom_agt_…' (an agent key) or 'Bearer nom_api_…' (an operator token)."
        ),
    )


def session_iter() -> Iterator[Session]:
    yield from get_session()
