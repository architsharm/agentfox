"""Shared environment setup — imported first by every script in this demo.

Points agentfox at a dedicated SQLite file living next to this demo, never at the
repo's own `agentfox.db` (used by the dashboard and the rest of the dev environment).
This must run before anything imports agentfox's settings, since they are cached for
the process lifetime (`agentfox.core.config.get_settings`, `@lru_cache`) — hence importing
this module (`import _env`) is the very first line of every other script here.

The path is overridable: set `NOMETRIA_DATABASE_URL` yourself before running a script
and this file's `setdefault` is a no-op.
"""

from __future__ import annotations

import os
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = DEMO_DIR / "demo.db"

os.environ.setdefault("NOMETRIA_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
