"""What every command module shares: one console, a database session, JSON output."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

console = Console()


def _session():
    from agentfox.core.db import init_db, session_scope

    init_db()
    return session_scope()


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(payload, default=str))
