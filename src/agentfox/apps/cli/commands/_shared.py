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


def dashboard_url() -> str:
    """The web dashboard this project is set up with, or "" when there is none.

    A pip install has no web UI: text that says "Policies → Libraries" there points
    at a page that does not exist. Only `agentfox up` with a dashboard (self-hosted or
    Cloud) records one, in `.agentfox/up.json`; `AGENTFOX_DASHBOARD_URL` names one too.
    """
    import os
    from pathlib import Path

    from agentfox.apps.cli.wizard.detect import load_answers

    return (
        os.environ.get("AGENTFOX_DASHBOARD_URL")
        or str(load_answers(Path.cwd()).get("dashboard_url") or "")
    ).rstrip("/")


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(payload, default=str))
