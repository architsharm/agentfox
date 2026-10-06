"""FastAPI dependency resolving a playground sandbox from its path `session_id`.

Split out from `playground.py` only so the per-action rate limit is applied in
exactly one place, shared by every route that takes a `session_id` path param,
rather than repeated at the top of each handler.
"""

from __future__ import annotations

from fastapi import HTTPException

from agentfox.apps.gateway.playground_sessions import (
    PlaygroundSession,
    PlaygroundUnavailable,
    action_limiter,
    get_store,
)


def playground_session(session_id: str) -> PlaygroundSession:
    try:
        record = get_store().get(session_id)
    except PlaygroundUnavailable as exc:
        # 503, not 404: "expired or never existed" would be a false statement about
        # the visitor's sandbox when the real problem is that the database could not
        # be read.
        raise HTTPException(503, str(exc)) from exc
    if record is None:
        raise HTTPException(
            404, "This playground sandbox has expired or never existed — create a new one."
        )
    if not action_limiter.check(session_id):
        raise HTTPException(429, "Slow down — too many actions on this sandbox in the last minute.")
    return record
