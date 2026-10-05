"""Shared environment setup — imported first by every script in this demo.

Points agentfox at a dedicated SQLite file living next to this demo, never at the
repo's own `agentfox.db` (used by the dashboard and the rest of the dev environment).
This must run before anything imports agentfox's settings, since they are cached for
the process lifetime (`agentfox.core.config.get_settings`, `@lru_cache`) — hence importing
this module (`import _env`) is the very first line of every other script here.

The path is overridable: set `NOMETRIA_DATABASE_URL` yourself before running a script
and this file's `setdefault` is a no-op.

**Deployed (Vercel) case**: the project's Postgres comes from Vercel's native Neon
integration, connected with a custom env-var prefix of `NOMETRIA_DATABASE` — but
Neon's own base variable name is itself `POSTGRES_URL`/`DATABASE_URL`, so the
integration produces `NOMETRIA_DATABASE_POSTGRES_URL` (prefix + Neon's name), not
`NOMETRIA_DATABASE_URL` directly (confirmed directly against the actual generated
variable list — searching for `NOMETRIA_DATABASE_URL` returns nothing; only the
doubled-up names exist). Rather than hand-copy the secret's raw value into a second,
manually-created variable (redundant, and easy to get subtly wrong — an initial
attempt at exactly that hit "Could not parse SQLAlchemy URL from given URL string"),
derive `NOMETRIA_DATABASE_URL` from the integration's own variable at import time.
This also fixes the driver: Neon's connection strings use the bare `postgresql://`
scheme (psycopg2's default dialect), but this demo installs `psycopg` (v3) per
`requirements.txt` — SQLAlchemy needs `postgresql+psycopg://` to pick that driver.
"""

from __future__ import annotations

import os
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = DEMO_DIR / "demo.db"

if "NOMETRIA_DATABASE_URL" not in os.environ:
    _neon_url = os.environ.get("NOMETRIA_DATABASE_POSTGRES_URL") or os.environ.get(
        "NOMETRIA_DATABASE_DATABASE_URL"
    )
    if _neon_url:
        if _neon_url.startswith("postgres://"):
            _neon_url = "postgresql+psycopg://" + _neon_url[len("postgres://") :]
        elif _neon_url.startswith("postgresql://"):
            _neon_url = "postgresql+psycopg://" + _neon_url[len("postgresql://") :]
        os.environ["NOMETRIA_DATABASE_URL"] = _neon_url

os.environ.setdefault("NOMETRIA_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
