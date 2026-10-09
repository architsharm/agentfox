"""What every script here shares: the gateway's address, the operator identity, and
the path to the upstream app that setup.sh cloned."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
BACKEND = HERE / "upstream" / "python-backend"

GATEWAY = os.environ.get("AGENTFOX_GATEWAY", "http://127.0.0.1:8091")
AGENT = os.environ.get("AGENTFOX_AGENT", "airline-cs")
# The local gateway runs development auth: an /api request without a token acts as
# the user this header names. gateway.sh creates this user as the owner. Against a
# hosted gateway, AGENTFOX_API_KEY (an API token from Settings) is used instead.
_KEY = os.environ.get("AGENTFOX_API_KEY")
OPERATOR = {"Authorization": f"Bearer {_KEY}"} if _KEY else {"X-AgentFox-User": "admin@example.com"}

# What users see when the agent's protection stops a message; configure.py sets it and
# check.py expects it back.
BLOCK_MESSAGE = "Sorry, I can only help with your bookings, flights, seats and baggage."


def use_upstream() -> None:
    """Make the cloned app importable, as if running from its python-backend/."""
    if not (BACKEND / "main.py").exists():
        raise SystemExit("upstream app missing: run ./setup.sh first")
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def api(method: str, path: str, **kwargs: Any) -> Any:
    """One control-plane call as the demo operator; raises on an error status."""
    response = httpx.request(method, f"{GATEWAY}{path}", headers=OPERATOR, timeout=60, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()
