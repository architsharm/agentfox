"""Per-visitor sandboxes for the public playground, stored in the deployment database.

The playground (`routes/playground.py`) lets an anonymous website visitor attack a
real agent and get a real enforcement verdict, without an account. Each visitor's
"world" is seeded with the same deterministic demo fixtures `agentfox demo` uses
(`seed.seed`): real enforcement code, fixture data.

**A sandbox is a tenant.** Its ``org_id`` is its own session id, and every row the
visitor produces is written under that org. Isolation therefore comes from
`tenancy.py`'s session-level filter, which attaches a tenant predicate to every ORM
statement whether or not the query's author has heard of tenancy — the same mechanism
that separates two paying customers. There is no playground-specific filter to
remember, and adding a route here cannot leak one sandbox into another by omission.

This replaces a module-level ``dict`` of per-sandbox in-memory SQLite engines. That
arrangement worked on a single always-on container and did not work at all on the
deployment in ``api/vercel.json``, where each request may land on a different
serverless instance: a visitor's second request would find no sandbox and be told
theirs had expired, at a random rate that looked like a short timer but was routing.
The per-process ``MAX_SESSIONS`` cap had the same defect — it bounded one instance and
therefore bounded nothing.

What the session id proves and does not prove: it is a 128-bit random value, and it is
the only credential in the playground. Holding it is what grants access, so a sandbox
is private to whoever created it exactly as long as they do not pass the link on. It
identifies no person, and it cannot be revoked short of expiry.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)
from sqlalchemy.orm import Session

from agentfox.core.db import get_sessionmaker
from agentfox.core.models import Base, PlaygroundSandbox, TenantScoped, as_aware, utcnow
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.fixtures.seed import seed as seed_world

log = logging.getLogger(__name__)

#: How long an *idle* sandbox survives. Extended on every action, so this is time
#: since the visitor's last request, not since they arrived. Generous enough to read
#: a report and come back, short enough that a public link does not accumulate
#: sandboxes forever.
SESSION_TTL_SECONDS = 30 * 60

#: Hard cap on concurrently-live sandboxes, counted across the whole deployment now
#: that the registry is in the shared database rather than in one process's memory.
#: The oldest idle sandbox is swept rather than new visitors being refused.
MAX_SESSIONS = 200

#: Cap on how many of its own trace ids a sandbox remembers for the "what happened"
#: sidebar. Older ids are forgotten; the rows they point at go when the sandbox does.
MAX_REMEMBERED_TRACES = 50

#: How often any one process re-scans for expired sandboxes. The scan is a query
#: across every tenant, so it is throttled rather than run on each request; expiry
#: itself is not throttled, because :meth:`PlaygroundStore.get` checks the row it
#: just read and refuses an expired sandbox whether or not a sweep has happened yet.
SWEEP_INTERVAL_SECONDS = 60

#: Sandbox ids, which are also their org ids. Checked before an id from a URL is ever
#: bound to a session: without this, a request for `/api/playground/sessions/org_x/...`
#: would bind a session to the tenant `org_x`. Nothing is read before the check, so a
#: caller cannot name a real tenant and see anything of it.
_SANDBOX_ID = re.compile(r"^pg_[0-9a-f]{32}$")

_ID_RANDOM_BITS = 128


def new_sandbox_id() -> str:
    """A sandbox id: 128 bits from :mod:`secrets`, and the sandbox's tenant key."""
    return f"pg_{secrets.token_hex(_ID_RANDOM_BITS // 8)}"


def is_sandbox_id(value: str) -> bool:
    return bool(_SANDBOX_ID.match(value or ""))


class PlaygroundUnavailable(RuntimeError):
    """The database cannot hold a sandbox yet, and the operator needs to know why.

    The one predictable cause is a deployment that has not run migration
    ``c4a71e8b2d16``. Without it ``playground_sandboxes`` is missing, and ``users.email``
    still carries the old *global* unique index, so seeding a second world fails on the
    fixture users the first world already inserted. `init_db()`'s create_all adds the
    missing table but cannot change an existing table's constraint, so a deployment
    that relies on create_all hits the second half of this and not the first.

    Raised instead of letting the driver error escape, so the response says what to run
    rather than returning an opaque 500 that looks like the playground being broken.
    """


def _ttl_from(now: dt.datetime) -> dt.datetime:
    return now + dt.timedelta(seconds=SESSION_TTL_SECONDS)


@contextmanager
def _tenant_session(org_id: str) -> Iterator[Session]:
    """A session from the deployment's one factory, bound to a sandbox's tenant.

    The factory is `db.get_sessionmaker()` — the same one every other route uses, with
    tenant isolation already installed. Obtaining a second, unfiltered factory here is
    exactly the hole `tenancy.py` exists to keep closed.
    """
    if not is_sandbox_id(org_id):
        raise ValueError(f"not a playground sandbox id: {org_id!r}")
    session = get_sessionmaker()()
    bind_session(session, org_id)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _purge_sandbox(session: Session, org_id: str) -> None:
    """Delete every row belonging to one expired sandbox tenant.

    Two locks on a destructive statement, deliberately. The session is bound to the
    sandbox's tenant, so `tenancy.py` attaches its predicate to each ORM delete; the
    explicit ``org_id ==`` is a second, visible one, because the cost of this being
    wrong is another tenant's rows. The id format is re-checked here too, so this can
    never be pointed at a real org even by a caller that skipped the route.

    Tables are emptied child-first (reverse dependency order) so foreign keys hold
    throughout — SQLite runs with ``PRAGMA foreign_keys=ON`` and Postgres enforces
    them regardless.

    This does delete the sandbox's ``AuditEntry`` rows, which are append-only
    everywhere else in the product. It is the disposal of a whole throwaway tenant on
    a stated TTL, not an edit to a retained tenant's chain: no row of a real customer
    is reachable from here, and nothing rewrites a chain in place.
    """
    if not is_sandbox_id(org_id):
        raise ValueError(f"refusing to purge a tenant that is not a sandbox: {org_id!r}")

    position = {table.name: index for index, table in enumerate(Base.metadata.sorted_tables)}
    mappers = sorted(
        Base.registry.mappers,
        key=lambda mapper: position.get(mapper.local_table.name, -1),
        reverse=True,
    )
    for mapper in mappers:
        model = mapper.class_
        # Skip the tables that hold no tenant's rows — `models.TenantExempt`, today just
        # the waitlist. They have no `org_id` to compare, so this loop would raise on
        # them, and a sweep that raises is a sandbox that never expires. Filtering on
        # `TenantScoped` rather than naming the table keeps that true for the next one:
        # "delete this tenant's rows" can only mean the tables that have a tenant.
        if not issubclass(model, TenantScoped):
            continue
        session.execute(delete(model).where(model.org_id == org_id))


@dataclass(frozen=True)
class PlaygroundSession:
    """A handle on one sandbox. Holds no data of its own — the rows are in the
    database and the tenant key is the id, so a handle built on one instance means
    the same thing on any other.
    """

    id: str
    expires_at: dt.datetime
    created_at: dt.datetime

    @property
    def org_id(self) -> str:
        return self.id

    def open(self) -> Session:
        """A session bound to this sandbox's tenant. The caller closes it."""
        session = get_sessionmaker()()
        bind_session(session, self.org_id)
        return session

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        with _tenant_session(self.org_id) as session:
            yield session

    def remember_trace(self, session: Session, trace_id: str | None) -> None:
        """Record a trace id for the sidebar, on the sandbox's own row.

        Takes the session because the list has to survive this process: the previous
        in-memory list was lost the moment the request finished on a serverless
        instance, so the sidebar came back empty on the next request.
        """
        if not trace_id:
            return
        row = session.get(PlaygroundSandbox, self.id)
        if row is None:
            return
        existing = list(row.trace_ids or [])
        existing.append(trace_id)
        # Reassign rather than mutate: the column is plain JSON, and an in-place
        # append is not seen by the unit of work, so nothing would be written.
        row.trace_ids = existing[-MAX_REMEMBERED_TRACES:]

    def trace_ids(self, session: Session) -> list[str]:
        row = session.get(PlaygroundSandbox, self.id)
        return list(row.trace_ids or []) if row is not None else []


class PlaygroundStore:
    """Creates, resolves and sweeps sandboxes.

    Stateless apart from a sweep timestamp: every instance of this class, in every
    process, sees the same sandboxes, because they are rows. That is the property the
    serverless deployment needs and the module-level dict could not provide.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    # -- creation ---------------------------------------------------------

    def create(self) -> PlaygroundSession:
        self.sweep()
        self._enforce_cap()

        session_id = new_sandbox_id()
        now = utcnow()
        try:
            with _tenant_session(session_id) as session:
                session.add(
                    PlaygroundSandbox(
                        id=session_id,
                        expires_at=_ttl_from(now),
                        last_used_at=now,
                        trace_ids=[],
                    )
                )
                # Seeded inside the same transaction and the same tenant binding, so a
                # sandbox is never visible half-built: either the whole world is there
                # or no row is.
                seed_world(session, email_namespace=session_id)
        except (IntegrityError, OperationalError, ProgrammingError) as exc:
            log.error("playground: could not create a sandbox", exc_info=True)
            raise PlaygroundUnavailable(
                "The playground could not create a sandbox. If this deployment has not "
                "run migration c4a71e8b2d16, run it: it adds playground_sandboxes, and "
                "makes users.email unique per tenant instead of globally."
            ) from exc
        except SQLAlchemyError as exc:  # pragma: no cover - unexpected driver failure
            log.error("playground: could not create a sandbox", exc_info=True)
            raise PlaygroundUnavailable("The playground could not create a sandbox.") from exc
        return PlaygroundSession(id=session_id, expires_at=_ttl_from(now), created_at=now)

    # -- resolution -------------------------------------------------------

    def get(self, session_id: str) -> PlaygroundSession | None:
        """Resolve a sandbox, or None if it never existed or has expired.

        The two are deliberately indistinguishable to the caller: telling a visitor
        which one it was would confirm ids for someone guessing them.
        """
        if not is_sandbox_id(session_id):
            return None
        self.sweep_if_due()

        now = utcnow()
        try:
            with _tenant_session(session_id) as session:
                row = session.get(PlaygroundSandbox, session_id)
                if row is None:
                    return None
                if (as_aware(row.expires_at) or now) <= now:
                    _purge_sandbox(session, session_id)
                    return None
                row.last_used_at = now
                row.expires_at = _ttl_from(now)
                return PlaygroundSession(
                    id=row.id,
                    expires_at=_ttl_from(now),
                    created_at=as_aware(row.created_at) or now,
                )
        except SQLAlchemyError as exc:
            # Not "your sandbox expired": the sandbox may well exist and the database
            # could not be asked. Saying it expired would send a visitor away over an
            # operator problem, which is what :class:`PlaygroundUnavailable` exists to
            # keep separate.
            log.error("playground: could not read sandbox %s", session_id, exc_info=True)
            raise PlaygroundUnavailable(
                "The playground could not read this sandbox. If this deployment has "
                "not run migration c4a71e8b2d16, run it."
            ) from exc

    # -- sweeping ---------------------------------------------------------

    def sweep_if_due(self) -> int:
        """Sweep at most once every :data:`SWEEP_INTERVAL_SECONDS` per process."""
        with self._lock:
            if time.monotonic() - self._last_sweep < SWEEP_INTERVAL_SECONDS:
                return 0
            self._last_sweep = time.monotonic()
        return self.sweep()

    def sweep(self) -> int:
        """Delete every sandbox whose idle TTL has run out. Returns how many."""
        expired = self._ids_where(expired_before=utcnow())
        for session_id in expired:
            self._drop(session_id)
        if expired:
            log.info("playground: swept %d expired sandbox(es)", len(expired))
        return len(expired)

    def _enforce_cap(self) -> None:
        """Keep the live sandbox count under :data:`MAX_SESSIONS`, deployment-wide."""
        live = self._ids_where()
        surplus = len(live) - MAX_SESSIONS + 1
        for session_id in live[:surplus] if surplus > 0 else []:
            self._drop(session_id)

    def _ids_where(self, *, expired_before: dt.datetime | None = None) -> list[str]:
        """Sandbox ids, least recently used first.

        Cross-tenant on purpose and only here: the cap and the sweep are properties of
        the deployment, not of any one sandbox, so this is the one query that has to
        see all of them. It reads ids and timestamps from the sandbox registry table
        only — never a sandbox's contents.
        """
        statement = select(PlaygroundSandbox.id).order_by(PlaygroundSandbox.last_used_at)
        if expired_before is not None:
            statement = statement.where(PlaygroundSandbox.expires_at <= expired_before)
        session = get_sessionmaker()()
        try:
            with system_scope("playground sandbox registry sweep", routine=True):
                return [row for row in session.scalars(statement)]
        except SQLAlchemyError:
            # Best effort, and loud about it. Housekeeping must not be what turns a
            # database problem into a failed request; an empty answer here means the
            # cap is not enforced and expired sandboxes are not swept on this pass,
            # which is why it logs at error rather than passing quietly.
            log.error("playground: sandbox registry unreadable, sweep skipped", exc_info=True)
            return []
        finally:
            session.close()

    def _drop(self, session_id: str) -> None:
        if not is_sandbox_id(session_id):  # pragma: no cover - defensive
            return
        try:
            with _tenant_session(session_id) as session:
                _purge_sandbox(session, session_id)
        except Exception:  # pragma: no cover - a sweep must never fail a request
            log.warning("playground: could not sweep sandbox %s", session_id, exc_info=True)


_store = PlaygroundStore()


def get_store() -> PlaygroundStore:
    return _store


class RateLimiter:
    """In-process sliding-window limiter.

    Per process, which on the serverless deployment means per instance: it bounds one
    instance's share of abuse and does not bound a client that is spread across
    instances. That is a real limit and it is stated here rather than implied — a
    distributed limiter needs a store this deployment does not have, and the sandbox
    cap and TTL above, which are now deployment-wide, are what actually bound the cost.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


#: New sandboxes per client address. Each one seeds a fresh world and (if the
#: classifier ensemble is enabled) runs real model inference — bounded per-IP so
#: this can't be turned into a free compute sink.
session_creation_limiter = RateLimiter(limit=8, window_seconds=3600)

#: Actions (chat / tool-call / enforce-toggle / state) per sandbox. High enough for
#: a human clicking around, low enough to bound a scripted hammer on one session.
action_limiter = RateLimiter(limit=40, window_seconds=60)
