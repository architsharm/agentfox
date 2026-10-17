"""Shared environment setup — imported first by every script in this demo.

Points agentfox at this demo's database: its own SQLite file
(`demo/redteam-live-lang/demo.db`) locally, or the Vercel project's Neon Postgres when
deployed; see `kit/env.py` for the rules, including how to override it. This must run
before anything imports agentfox's settings, since they are cached for the process
lifetime — hence `import _env` is the very first line of every other script here.

`kit/` next to this file is a committed copy of `demo/kit/`: the Vercel project's Root
Directory is this folder, so nothing outside it exists at deploy time. Never edit the
copy; edit `demo/kit/` and run `python scripts/check/demo_kit.py --write`.
"""

from __future__ import annotations

from pathlib import Path

from kit.env import configure

DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = configure(DEMO_DIR)
