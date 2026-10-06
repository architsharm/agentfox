"""Environment setup shared by both demos: which database agentfox talks to.

Each demo's own `_env.py` calls `configure(<its own folder>)` as the very first import
of every script there. This must run before anything imports agentfox's settings,
since they are cached for the process lifetime (`agentfox.core.config.get_settings`,
`@lru_cache`).

Locally, it points agentfox at a dedicated SQLite file next to the calling demo
(`<demo folder>/demo.db`), never at the repo's own `agentfox.db` (used by the dashboard
and the rest of the dev environment), and never at the other demo's file. The path is
overridable: set `AGENTFOX_DATABASE_URL` (or the older `NOMETRIA_DATABASE_URL`)
yourself before running a script. The default is written under the older name on
purpose: every agentfox version reads it, including an older vendored wheel, and the
current one reads `AGENTFOX_DATABASE_URL` first, so an explicit override still wins.

**Deployed (Vercel) case**: the project's Postgres comes from Vercel's native Neon
integration, connected with a custom env-var prefix of `NOMETRIA_DATABASE` — but
Neon's own base variable name is itself `POSTGRES_URL`/`DATABASE_URL`, so the
integration produces `NOMETRIA_DATABASE_POSTGRES_URL` (prefix + Neon's name), not
`NOMETRIA_DATABASE_URL` directly (confirmed directly against the actual generated
variable list — searching for `NOMETRIA_DATABASE_URL` returns nothing; only the
doubled-up names exist). Rather than hand-copy the secret's raw value into a second,
manually-created variable (redundant, and easy to get subtly wrong — an initial
attempt at exactly that hit "Could not parse SQLAlchemy URL from given URL string"),
derive `NOMETRIA_DATABASE_URL` from the integration's own variable. This also fixes
the driver: Neon's connection strings use the bare `postgresql://` scheme (psycopg2's
default dialect), but the deployed demo installs `psycopg` (v3) per its
`requirements.txt` — SQLAlchemy needs `postgresql+psycopg://` to pick that driver.
Neither Neon variable is ever set locally, so this branch is a no-op there.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Either name set by hand means "use this database", and nothing here touches it.
_EXPLICIT = ("AGENTFOX_DATABASE_URL", "NOMETRIA_DATABASE_URL")


def _neon_database_url() -> str | None:
    url = os.environ.get("NOMETRIA_DATABASE_POSTGRES_URL") or os.environ.get(
        "NOMETRIA_DATABASE_DATABASE_URL"
    )
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
    os.environ["NOMETRIA_DATABASE_URL"] = neon_url or f"sqlite:///{default_db_path}"
    return default_db_path
