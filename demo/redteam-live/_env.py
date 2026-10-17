"""Shared environment setup — imported first by every script in this demo.

Makes the shared kit (`demo/kit/`) importable and points agentfox at this demo's own
SQLite file (`demo/redteam-live/demo.db`); see `kit/env.py` for the rules, including
how to override the database. This must run before anything imports agentfox's
settings, since they are cached for the process lifetime — hence `import _env` is the
very first line of every other script here.

This demo is not deployed anywhere, so it imports `demo/kit/` in place by putting
`demo/` on `sys.path`. (The LangChain demo deploys with its own folder as the Vercel
root, so it carries a committed copy of the kit instead.)
"""

from __future__ import annotations

import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
if str(DEMO_DIR.parent) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR.parent))

from kit.env import configure  # noqa: E402  -- needs demo/ on sys.path first

DEFAULT_DB_PATH = configure(DEMO_DIR)
