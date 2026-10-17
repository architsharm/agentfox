"""Tenant isolation, enforced by construction rather than by remembering.

The audit finding this closes was blunt: every table carried an ``org_id`` column and
**not one query filtered on it**. That is worse than having no tenancy concept at all,
because the column is precisely what a procurement reviewer looks for and finds — it
creates the appearance of isolation in a schema review while every tenant reads every
other tenant's traces, decisions, findings and evidence.

The obvious fix — add ``.where(X.org_id == current)`` to every query — is the wrong
one. There are several hundred queries here and there will be more next year; the
mechanism would hold exactly until the first person writes a new one and forgets, and
the failure mode of forgetting is a silent cross-tenant data leak that no test catches
because the test wrote both rows itself.

So isolation is applied at the session, not the query. A ``do_orm_execute`` hook
attaches a ``with_loader_criteria`` to **every ORM statement**, which means a query
that does not know about tenancy is filtered anyway, and a query added in a year's
time is filtered without its author having heard of this module.

Empirically verified to cover: ``select()``, ``session.get()``, both
``func.count()`` forms, the legacy ``query()`` API, and ORM-enabled bulk ``update()``
and ``delete()``. The one thing it cannot cover is raw ``text()`` SQL, which is why
:func:`assert_tenant_safe` exists and why the only raw SQL in this codebase reads
Alembic's version table.

**The tenant travels with the session, not with the thread.** The first version of this
bound a context variable inside the authentication dependency, which is wrong in a way
that only a test reveals: FastAPI runs dependencies and handlers in separate threadpool
contexts, so the handler never sees what the dependency set — verified, both for sync
and async endpoints. Binding to ``session.info`` instead makes the tenant a property of
the unit of work, which is what it actually is, and removes the thread question
entirely. The context variable survives as the default for callers that have no request
and no session yet: the CLI, the SDK, background jobs.

**The default is a failure, not a leak.** With nothing bound, queries resolve to the
deployment's configured org rather than to everything. A gateway bug that forgets to
bind therefore shows a user an empty screen — visible, reportable and harmless —
instead of showing them another company's data.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from agentfox.core.models import TenantExempt, TenantScoped, _is_exempt

log = logging.getLogger(__name__)

#: The tenant the current execution context speaks for. A context variable rather than
#: a thread local because the gateway is async: a thread local would bleed one
#: request's tenant into another's coroutine on the same thread, which is the exact
#: failure this module exists to prevent.
_CURRENT_ORG: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agentfox_org", default=None
)

#: Set while an operation has deliberately opted out of filtering. Never set implicitly.
_SYSTEM_SCOPE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agentfox_system_scope", default=False
)


class CrossTenantWrite(PermissionError):
    """Raised when a write would place a row in, or move a row to, another tenant."""


#: Key under which a session carries its tenant. Sessions are the unit of work, and the
#: tenant is a property of the work, so this is the authoritative binding.
SESSION_KEY = "agentfox_org"


def bind_session(session: Session, org_id: str) -> None:
    """Bind a session to a tenant. This is the authoritative binding.

    Used by the request path, where the session is the only thing reliably shared
    between the authentication dependency and the route handler.
    """
    if not org_id:
        raise ValueError("org_id must be a non-empty string")
    session.info[SESSION_KEY] = org_id


def session_org(session: Session | None) -> str:
    """The tenant for a session: its own binding, else the ambient default."""
    if session is not None:
        bound = session.info.get(SESSION_KEY)
        if bound:
            return str(bound)
    return current_org()


def current_org() -> str:
    """The ambient tenant, falling back to the deployment's configured org.

    Falling back rather than raising is deliberate. A single-tenant deployment — which
    is every self-host install — never binds a tenant explicitly, and making that path
    raise would mean the CLI, the SDK and every background job had to know about
    tenancy to do anything. The fallback keeps them working while ensuring that an
    unbound caller sees *one* org's data rather than all of them.
    """
    bound = _CURRENT_ORG.get()
    if bound is not None:
        return bound
    from agentfox.core.config import get_settings

    return get_settings().org_id


def bound_org() -> str | None:
    """The explicitly bound tenant, or None. Distinguishes "unbound" from "default"."""
    return _CURRENT_ORG.get()


@contextmanager
def tenant(org_id: str) -> Iterator[str]:
    """Bind a tenant for the duration of the block.

    Every request path that has an authenticated principal must enter one of these.
    Nesting is permitted and restores the outer tenant on exit, so a background task
    spawned inside a request cannot silently inherit and then outlive it.
    """
    if not org_id:
        raise ValueError("org_id must be a non-empty string")
    token = _CURRENT_ORG.set(org_id)
    try:
        yield org_id
    finally:
        _CURRENT_ORG.reset(token)


def set_current_org(org_id: str) -> None:
    """Bind a tenant without a scope to exit.

    For request handlers, where the task context is discarded at the end of the
    request and so does the binding. Anything longer-lived should use :func:`tenant`,
    which restores the previous value.
    """
    if not org_id:
        raise ValueError("org_id must be a non-empty string")
    _CURRENT_ORG.set(org_id)


@contextmanager
def system_scope(reason: str, *, routine: bool = False) -> Iterator[None]:
    """Read across every tenant. Requires a reason, and says so in the log.

    Legitimate uses fall into two groups. Most are rare and off the request path —
    schema migration, chain verification over the whole log, operator tooling — and
    each is a place where a mistake is a data breach, so they log at warning level.

    The exception is authentication, which is unavoidably cross-tenant: you cannot
    filter by tenant until you know whose tenant it is. That happens on every single
    request, and warning about it would bury the warnings that matter under one line
    per request until nobody reads any of them. Those pass ``routine=True`` and log at
    debug — still greppable, without the noise.
    """
    log.log(
        logging.DEBUG if routine else logging.WARNING,
        "tenancy: cross-tenant scope entered — %s",
        reason,
    )
    token = _SYSTEM_SCOPE.set(True)
    try:
        yield
    finally:
        _SYSTEM_SCOPE.reset(token)


def in_system_scope() -> bool:
    return _SYSTEM_SCOPE.get()


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def _tenant_criteria(execute_state: Any) -> None:
    """Attach the tenant predicate to every ORM statement.

    Deliberately not restricted to selects: ORM-enabled ``update()`` and ``delete()``
    go through this same hook, and a bulk update that crosses tenants is worse than a
    read that does.

    Column and relationship loads are skipped because they are secondary loads for
    objects the session already holds, and re-filtering them would break lazy loading
    of a legitimately-loaded parent.

    The criteria target :class:`TenantScoped`, so a model that does not inherit it is
    simply not filtered. That is not an oversight to be tightened later — it is how
    :class:`~agentfox.core.models.TenantExempt` works, and :func:`assert_tenant_safe` is
    what keeps the set of such models to the ones that were argued for.
    """
    if execute_state.is_column_load or execute_state.is_relationship_load:
        return
    if _SYSTEM_SCOPE.get():
        return
    org = session_org(execute_state.session)
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.org_id == org,
            include_aliases=True,
        )
    )


def _stamp_and_guard(session: Session, _context: Any, _instances: Any) -> None:
    """Stamp new rows with the current tenant, and refuse to move existing ones.

    Stamping on flush rather than relying on a column default means a row cannot be
    created in the wrong tenant by a caller who never thought about tenancy — the
    common case, and the one the column default silently got wrong before.

    The guard on ``dirty`` is the other half: without it, a row could be *read* in one
    tenant and *written* into another, which turns a read filter into a no-op for
    anyone who can update.
    """
    org = session_org(session)
    for obj in session.new:
        if isinstance(obj, TenantScoped) and not getattr(obj, "org_id", None):
            obj.org_id = org

    if _SYSTEM_SCOPE.get():
        return

    for obj in session.dirty:
        if not isinstance(obj, TenantScoped):
            continue
        added, _unchanged, deleted = inspect(obj).attrs["org_id"].history
        if added and deleted and added[0] != deleted[0]:
            raise CrossTenantWrite(
                f"{type(obj).__name__} {getattr(obj, 'id', '?')} cannot move from tenant "
                f"'{deleted[0]}' to '{added[0]}' — org_id is immutable after creation"
            )


def install(factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """Wire isolation into a session factory. Idempotent."""
    if getattr(factory, "_agentfox_tenancy", False):
        return factory
    event.listen(factory, "do_orm_execute", _tenant_criteria)
    event.listen(factory, "before_flush", _stamp_and_guard)
    factory._agentfox_tenancy = True  # type: ignore[attr-defined]
    return factory


# ---------------------------------------------------------------------------
# The structural guarantee: a model that forgets tenancy cannot exist
# ---------------------------------------------------------------------------


def assert_tenant_safe() -> list[str]:
    """Every mapped class must be tenant-scoped. Returns the offenders.

    Called at import time by :mod:`agentfox.core.models`. The point is that adding a model
    next year and forgetting the mixin becomes an immediate, loud import error rather
    than a data leak discovered by a customer. A filter you have to remember is not a
    control; a filter you cannot omit is.

    The one class of exception is a table that exists *before* there is a tenant to
    scope it to — today only the hosted-cloud waitlist. Those are not offenders, but
    they are not invisible either: a model is excused only if it both inherits
    :class:`~agentfox.core.models.TenantExempt` and is named in
    ``models.TENANT_EXEMPT_TABLES``, so the excuse costs a reviewed diff in the file
    that states what it costs. :func:`tenant_exempt_models` lists who has one.
    """
    from agentfox.core.models import Base

    offenders = [
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if not issubclass(mapper.class_, TenantScoped) and not _is_exempt(mapper.class_)
    ]
    return sorted(offenders)


def tenant_exempt_models() -> list[str]:
    """The models the filter above deliberately does not cover.

    Exists so the exemption is something a test and an auditor can *enumerate* rather
    than something they have to go looking for. A row in one of these tables is
    readable from any tenant's session, because no predicate is attached to it.
    """
    from agentfox.core.models import Base

    return sorted(
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantExempt)
    )
