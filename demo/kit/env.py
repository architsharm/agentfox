"""Environment setup shared by both demos: which database agentfox talks to.

Each demo's own `_env.py` calls `configure(<its own folder>)` as the very first import
of every script there. This must run before anything imports agentfox's settings,
since they are cached for the process lifetime (`agentfox.core.config.get_settings`,
`@lru_cache`).

Locally, it points agentfox at a dedicated SQLite file next to the calling demo
(`<demo folder>/demo.db`), never at the repo's own `agentfox.db` (used by the dashboard
and the rest of the dev environment), and never at the other demo's file. The path is
overridable: set `AGENTFOX_DATABASE_URL` yourself before running a script.

**Deployed (Vercel) case**: the project's Postgres comes from Vercel's native Neon
integration, connected with the custom env-var prefix `AGENTFOX_DATABASE`. Neon's own base variable names are
`POSTGRES_URL`/`DATABASE_URL`, so the integration produces
`AGENTFOX_DATABASE_POSTGRES_URL` (prefix + Neon's name), not `AGENTFOX_DATABASE_URL`
directly — only the doubled-up names exist. Rather than hand-copy the secret's raw
value into a second, manually-created variable (redundant, and easy to get subtly
wrong — an initial attempt at exactly that hit "Could not parse SQLAlchemy URL from
given URL string"), derive `AGENTFOX_DATABASE_URL` from the integration's own
variable. This also fixes the driver: Neon's connection strings use the bare
`postgresql://` scheme (psycopg2's default dialect), but the deployed demo installs
`psycopg` (v3) per its `requirements.txt` — SQLAlchemy needs `postgresql+psycopg://`
to pick that driver. Neither Neon variable is ever set locally, so this branch is a
no-op there. The integration's pre-rename `NOMETRIA_DATABASE` prefix is no longer read
(docs/deployment/vercel-env-rename.md).
"""

from __future__ import annotations

import os
from pathlib import Path

#: Set by hand, it means "use this database", and nothing here touches it.
_EXPLICIT = ("AGENTFOX_DATABASE_URL",)

#: What a Neon integration generates under the `AGENTFOX_DATABASE` prefix.
_NEON = ("AGENTFOX_DATABASE_POSTGRES_URL", "AGENTFOX_DATABASE_DATABASE_URL")


def _neon_database_url() -> str | None:
    url = next((os.environ[name] for name in _NEON if os.environ.get(name)), None)
    if not url:
        return None
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme) :]
    return url


def configure(demo_dir: Path) -> Path:
    """Point agentfox at this demo's database; return the default SQLite path."""
    default_db_path = Path(demo_dir).resolve() / "demo.db"
    if any(name in os.environ for name in _EXPLICIT):
        return default_db_path
    neon_url = _neon_database_url()
    os.environ["AGENTFOX_DATABASE_URL"] = neon_url or f"sqlite:///{default_db_path}"
    return default_db_path
