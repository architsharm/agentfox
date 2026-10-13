"""Your own access control, asked before a tool call runs. See `service.py`."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def tool_call_hook(session: Session, *, principal: Any = None, **call: Any) -> list[Any]:
    """The `tool_call` hook (`agentfox.core.extensions`): every matching check's decision."""
    from agentfox_ee.access_checks import service

    return service.authorize(session, principal=service.Principal.parse(principal), **call)


def routers() -> list[Any]:
    from agentfox_ee.access_checks.routes import router

    return [router]
