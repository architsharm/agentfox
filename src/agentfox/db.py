"""Database session management.

SQLite by default so the whole control plane runs with no infrastructure at all
(NFR-9); Postgres via ``NOMETRIA_DATABASE_URL`` for anything real.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def configure_pool(url: str, *, workers: int = 1) -> dict:
    """Connection-pool settings for the deployment, and a refusal to misconfigure it.

    SQLite is a single-writer database. It is a fine default for a single-process
    install and it cannot back a multi-worker deployment: the second worker does not
    fail loudly, it takes a write lock and the first one waits, which surfaces as the
    governance layer being intermittently slow — and a governance layer that is
    intermittently slow gets its timeout raised until it fails open. So the
    misconfiguration is raised at startup rather than discovered as latency.

    For Postgres the pool is sized per worker, with ``pool_pre_ping`` because the
    connection this layer needs is the one it needs during an incident, and a stale
    handle then costs a request that mattered. ``lock_timeout``/``statement_timeout``
    are also set for every Postgres connection (see ``_build_engine``'s "connect"
    listener, not this dict) — without them, two sessions contending for the same
    row wait on Postgres's default unbounded lock queue, which in a request-scoped
    caller reads as a silent hang, not a slow query or an error. They're applied via
    a plain ``SET`` after connecting rather than ``connect_args``' ``options=``
    startup parameter, because a pooled endpoint (Neon's PgBouncer-style pooler, the
    actual deployed case this was found against) rejects arbitrary startup
    parameters outright and refuses the connection entirely.
    """
    if url.startswith("sqlite"):
        if workers > 1:
            raise RuntimeError(
                f"SQLite cannot back {workers} workers — it is single-writer, and the "
                "contention surfaces as intermittent latency rather than an error. "
                "Use PostgreSQL for a multi-worker deployment, or run one worker."
            )
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }


def _ensure_sqlite_directory(url: str) -> None:
    """Create the directory a SQLite file lives in, if it does not exist.

    SQLite will create the *file* and not the directory, and SQLAlchemy reports
    the miss as `OperationalError: unable to open database file` wrapped in a
    forty-line traceback pointing at `dialect.connect`, which says nothing about
    a missing directory. On a fresh PyPI install that is the first thing
    `agentfox init` does, against a state directory that by definition does not
    exist yet — so the very first command anyone runs would end in a stack trace.
    """
    if not url.startswith("sqlite"):
        return
    path = make_url(url).database
    # ":memory:" and a bare "sqlite://" have no file to make room for.
    if not path or path == ":memory:":
        return
    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _build_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    _ensure_sqlite_directory(url)
    kwargs: dict = {"echo": settings.sql_echo, "future": True}
    kwargs.update(configure_pool(url, workers=getattr(settings, "workers", 1) or 1))
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            # WAL keeps the gateway's write path from blocking dashboard reads.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    else:

        @event.listens_for(engine, "connect")
        def _postgres_session_gucs(dbapi_conn, _record):  # pragma: no cover - trivial
            # Set per-session, not via connect_args' `options=` startup parameter:
            # a pooled Postgres endpoint (Neon's PgBouncer-style pooler, the actual
            # deployed case) rejects arbitrary startup parameters outright —
            # "unsupported startup parameter in options: lock_timeout" — which
            # took the whole app down at startup rather than just this GUC. A
            # plain SET after connecting works against both a pooled and a direct
            # connection. See configure_pool()'s docstring for why this exists.
            cur = dbapi_conn.cursor()
            cur.execute("SET lock_timeout = '5s'")
            cur.execute("SET statement_timeout = '20s'")
            cur.close()
            dbapi_conn.commit()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    """The one session factory, with tenant isolation already wired in.

    Isolation is installed here rather than at each call site so that there is no way
    to obtain an unfiltered session by accident — a second, unprotected factory would
    reintroduce exactly the leak this closes.
    """
    global _SessionLocal
    if _SessionLocal is None:
        from .tenancy import install as install_tenancy

        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
        install_tenancy(_SessionLocal)
        try:
            from .webhooks import install as install_webhooks

            install_webhooks(_SessionLocal)
        except Exception:  # pragma: no cover - webhooks must never block sessions
            import logging

            logging.getLogger(__name__).warning("finding webhooks not installed", exc_info=True)
    return _SessionLocal


def init_db(stamp: bool = True) -> None:
    """Create the schema directly.

    Convenience for tests and first-run local use. **Production upgrades go through
    Alembic** (`agentfox db upgrade`) — `create_all` cannot evolve an existing schema,
    which is the defect PL-2 fixed.

    When ``stamp`` is set and Alembic is available, the fresh database is stamped at
    ``head`` so a later `alembic upgrade` does not try to re-create tables that are
    already there.
    """
    engine = get_engine()
    fresh = not inspect(engine).has_table("agents")
    Base.metadata.create_all(engine)
    if stamp and fresh:
        _stamp_head()


def migration_root() -> tuple[Path, Path] | None:
    """Where alembic.ini and the migration scripts are, or None if unavailable.

    Two layouts, because there are two ways to have this package. In the
    repository both sit at the root. Installed from PyPI they are copied into
    the package itself (see the force-include in pyproject.toml) — the root
    copies are simply not in the wheel, which is why `agentfox db upgrade` used
    to die with a raw alembic traceback naming a path inside the user's venv.
    """
    from .config import REPO_ROOT

    packaged = Path(__file__).resolve().parent
    for ini, scripts in (
        (REPO_ROOT / "alembic.ini", REPO_ROOT / "migrations"),
        (packaged / "_alembic.ini", packaged / "_migrations"),
    ):
        if ini.is_file() and scripts.is_dir():
            return ini, scripts
    return None


def _alembic_config(revision_hint: str) -> Any:
    """An alembic Config pointed at whichever copy of the migrations exists."""
    from alembic.config import Config

    found = migration_root()
    if found is None:
        raise RuntimeError(
            "migration scripts are not available in this installation, so "
            f"'{revision_hint}' cannot run. Reinstall agentfox from PyPI, or run "
            "this from a source checkout."
        )
    ini, scripts = found
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(scripts))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def _stamp_head() -> None:
    """Mark a create_all-built database as being at the latest revision."""
    try:
        from alembic import command

        if migration_root() is None:
            return
        command.stamp(_alembic_config("stamp"), "head")
    except Exception:  # pragma: no cover - alembic is optional for library use
        pass


def upgrade_db(revision: str = "head") -> None:
    """Run migrations against the configured database."""
    from alembic import command

    command.upgrade(_alembic_config("db upgrade"), revision)


def downgrade_db(revision: str) -> None:
    from alembic import command

    command.downgrade(_alembic_config("db downgrade"), revision)


def current_revision() -> str | None:
    from sqlalchemy import text

    with get_engine().connect() as conn:
        try:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        except Exception:
            return None
    return row[0] if row else None


def reset_engine() -> None:
    """Test hook. Drops cached engine/sessionmaker so settings changes take effect."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
