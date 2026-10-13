"""The `compliance.recompute` job: keep control status current."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agentfox.platform.ledger import chain

DAY = 86_400


def recompute_compliance(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from agentfox.apps.jobs import _actor
    from agentfox_ee.compliance import compute_all, posture

    window_days = int(payload.get("window_days") or 30)
    statuses = compute_all(session, window_days)
    actor_type, actor_id = _actor(payload)
    chain.append(
        session,
        "compliance.computed",
        actor_type=actor_type,
        actor_id=actor_id,
        payload={"controls": len(statuses), "window_days": window_days},
    )
    return {"computed": len(statuses), "window_days": window_days, "posture": posture(session)}


SCHEDULES = (
    {
        "kind": "compliance.recompute",
        "interval_seconds": DAY,
        "enabled": True,
        "payload": {"window_days": 30},
        "why": "keep control status current",
    },
)
