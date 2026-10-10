"""An agent's circuit breaker: stop a misbehaving agent before a person notices.

The kill switch needs someone watching. An agent that starts looping, or gets steered
into calling tools its rules refuse, produces a burst of blocked calls long before
anyone opens the dashboard. The breaker watches that rate per agent and acts on it:

* **closed** (normal). After a blocked call, the breaker counts the agent's recent
  decisions. When at least ``min_calls`` happened in the last ``window_seconds`` and
  ``block_ratio`` of them were blocked, it trips.
* **open**. In ``pause`` mode every call from the agent is refused, with the reason,
  until ``retry_at``. In ``alert`` mode nothing is refused: tripping raises the issue
  and nothing else, so a team can see what the breaker would do before trusting it.
* **probing**. After the cool-down, calls go through again and are watched. The first
  blocked call reopens it with twice the cool-down (up to an hour); ``probe_calls``
  clean calls close it, and its issue closes itself.

Tripping raises an ``agent_breaker_tripped`` issue either way. A person can reset the
breaker, or change its settings, at any time.

Red-team probes (``redteam.*`` tools) do not count: an attack test blocks calls on
purpose, and should not pause the agent it tests. A person's own pause or stop wins
over the breaker; while one is in force the breaker does nothing.

Why a rate and not a count: a busy agent blocks more calls than a quiet one in
absolute terms, and ``min_calls`` keeps one bad call on a quiet agent from tripping.
The cost on the request path is one indexed count, and only after a blocked call or
while probing.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import Agent, AgentControl, Decision, utcnow
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.findings import open_finding, raise_finding, resolve_finding

FINDING_TYPE = "agent_breaker_tripped"
MODES = ("off", "alert", "pause")
CLOSED, OPEN, PROBING = "closed", "open", "probing"
MAX_COOLDOWN_SECONDS = 3600
SYSTEM_ACTOR = "agentfox.breaker"

#: Settings a person may change, with their bounds.
LIMITS: dict[str, tuple[float, float]] = {
    "window_seconds": (30, 86400),
    "min_calls": (2, 10000),
    "block_ratio": (0.05, 1.0),
    "cooldown_seconds": (10, MAX_COOLDOWN_SECONDS),
    "probe_calls": (1, 100),
}


def defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "mode": s.agent_breaker_mode,
        "window_seconds": s.agent_breaker_window_seconds,
        "min_calls": s.agent_breaker_min_calls,
        "block_ratio": s.agent_breaker_block_ratio,
        "cooldown_seconds": s.agent_breaker_cooldown_seconds,
        "probe_calls": s.agent_breaker_probe_calls,
    }


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _parse(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return _aware(dt.datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def config_of(control: AgentControl | None) -> dict[str, Any]:
    """Settings in force: the agent's own over the deployment's defaults, plus state."""
    stored = dict((control.breaker_json if control else None) or {})
    out = {**defaults(), **{k: v for k, v in stored.items() if k in (*LIMITS, "mode")}}
    out["state"] = stored.get("state") or CLOSED
    for key in ("opened_at", "retry_at", "probe_since", "last_trip_at", "count_from", "reason"):
        out[key] = stored.get(key)
    out["trips"] = int(stored.get("trips") or 0)
    out["reopens"] = int(stored.get("reopens") or 0)
    return out


def _control(session: Session, agent: Agent) -> AgentControl:
    control = session.scalar(select(AgentControl).where(AgentControl.agent_id == agent.id))
    if control is None:
        control = AgentControl(agent_id=agent.id, state="active")
        session.add(control)
        session.flush()
    return control


def _save(control: AgentControl, cfg: dict[str, Any]) -> None:
    # A new dict, so the JSON column sees the change.
    control.breaker_json = {k: v for k, v in cfg.items() if v is not None}


def _audit(session: Session, agent: Agent, action: str, actor: str, payload: dict) -> None:
    chain.append(
        session,
        f"agent.breaker.{action}",
        actor_type="system" if actor == SYSTEM_ACTOR else "user",
        actor_id=actor,
        subject_type="agent",
        subject_id=agent.id,
        payload={"agent": agent.slug, **payload},
    )


# ---------------------------------------------------------------------------
# The request path
# ---------------------------------------------------------------------------


def refusal(session: Session, agent: Agent, control: AgentControl | None) -> str | None:
    """Why this call is refused by the breaker, or None. Moves open to probing on time."""
    if control is None or not control.breaker_json:
        return None
    cfg = config_of(control)
    if cfg["state"] != OPEN:
        return None
    retry_at = _parse(cfg["retry_at"])
    now = utcnow()
    if cfg["mode"] != "pause" or (retry_at is not None and now >= retry_at):
        cfg.update(state=PROBING, probe_since=now.isoformat())
        _save(control, cfg)
        session.flush()
        _audit(session, agent, "probing", SYSTEM_ACTOR, {"after": cfg["reason"]})
        return None
    when = retry_at.strftime("%H:%M UTC") if retry_at else "a person resets it"
    return f"Circuit breaker open: {cfg['reason']}. Retrying at {when}"


def _window_start(cfg: dict[str, Any], now: dt.datetime) -> dt.datetime:
    """Where the current window starts: the window, or a person's reset if later. A
    resumed agent is judged on calls after the resume, not on the burst it was resumed
    from (which would trip it again on the next blocked call)."""
    start = now - dt.timedelta(seconds=float(cfg["window_seconds"]))
    reset_at = _parse(cfg.get("count_from"))
    return max(start, reset_at) if reset_at else start


def _counts(session: Session, agent_id: str, since: dt.datetime) -> tuple[int, int]:
    """(decisions, blocked) for the agent since ``since``, red-team probes left out."""
    base = select(func.count(Decision.id)).where(
        Decision.agent_id == agent_id,
        Decision.created_at >= since,
        (Decision.tool_key.is_(None)) | (~Decision.tool_key.like("redteam.%")),
    )
    total = session.scalar(base) or 0
    blocked = session.scalar(base.where(Decision.verdict == "block")) or 0
    return int(total), int(blocked)


def observe(session: Session, agent: Agent | None, decision: Decision) -> str | None:
    """Count one recorded decision against the agent's breaker. Returns a transition.

    Called after every persisted decision. Cheap when nothing is wrong: a closed
    breaker looks at nothing until a call is blocked.
    """
    if agent is None or (decision.tool_key or "").startswith("redteam."):
        return None
    control = session.scalar(select(AgentControl).where(AgentControl.agent_id == agent.id))
    if control is not None and control.state != "active":
        return None  # a person's pause or stop is in force
    stored_state = ((control.breaker_json if control else None) or {}).get("state") or CLOSED
    if stored_state == CLOSED and decision.verdict != "block":
        return None
    cfg = config_of(control)
    if cfg["mode"] == "off":
        return None
    now = utcnow()

    if cfg["state"] == PROBING:
        since = _parse(cfg["probe_since"]) or now
        total, blocked = _counts(session, agent.id, since)
        if blocked:
            return _trip(session, agent, _control(session, agent), cfg, now, reopen=True)
        if total >= int(cfg["probe_calls"]):
            return _close(
                session,
                agent,
                _control(session, agent),
                cfg,
                actor=SYSTEM_ACTOR,
                note=f"{total} calls passed after the cool-down",
            )
        return None
    if cfg["state"] == OPEN:
        return None

    last = _parse(cfg["last_trip_at"])
    window = dt.timedelta(seconds=float(cfg["window_seconds"]))
    if last is not None and now - last < window:
        return None  # already tripped for this burst (alert mode keeps calling here)
    total, blocked = _counts(session, agent.id, _window_start(cfg, now))
    if total < int(cfg["min_calls"]) or blocked / max(total, 1) < float(cfg["block_ratio"]):
        return None
    cfg["reason"] = (
        f"{blocked} of {total} calls blocked in the last {_span(float(cfg['window_seconds']))}"
    )
    return _trip(session, agent, _control(session, agent), cfg, now, reopen=False)


def _span(seconds: float) -> str:
    if seconds % 3600 == 0:
        hours = int(seconds // 3600)
        return f"{hours} hour" + ("s" if hours != 1 else "")
    if seconds % 60 == 0:
        minutes = int(seconds // 60)
        return f"{minutes} minute" + ("s" if minutes != 1 else "")
    return f"{int(seconds)} seconds"


def _trip(
    session: Session,
    agent: Agent,
    control: AgentControl,
    cfg: dict[str, Any],
    now: dt.datetime,
    *,
    reopen: bool,
) -> str:
    reopens = int(cfg["reopens"]) + 1 if reopen else 0
    cooldown = min(float(cfg["cooldown_seconds"]) * (2**reopens), MAX_COOLDOWN_SECONDS)
    pausing = cfg["mode"] == "pause"
    if reopen:
        cfg["reason"] = f"a call was blocked again after the cool-down ({cfg['reason']})"
    cfg.update(
        state=OPEN if pausing else CLOSED,
        opened_at=now.isoformat() if pausing else None,
        retry_at=(now + dt.timedelta(seconds=cooldown)).isoformat() if pausing else None,
        probe_since=None,
        last_trip_at=now.isoformat(),
        trips=int(cfg["trips"]) + 1,
        reopens=reopens,
    )
    _save(control, cfg)
    session.flush()
    action = "reopened" if reopen else "tripped"
    _audit(
        session,
        agent,
        action,
        SYSTEM_ACTOR,
        {"mode": cfg["mode"], "reason": cfg["reason"], "retry_at": cfg["retry_at"]},
    )
    raise_finding(
        session,
        type=FINDING_TYPE,
        severity="high" if pausing else "medium",
        title=(
            f"Circuit breaker paused {agent.slug}: {cfg['reason']}"
            if pausing
            else f"{agent.slug} would have been paused: {cfg['reason']}"
        ),
        subject_type="agent",
        subject_id=agent.slug,
        evidence={
            "agent": agent.slug,
            "mode": cfg["mode"],
            "reason": cfg["reason"],
            "retry_at": cfg["retry_at"],
            "cooldown_seconds": cooldown,
            "trips": cfg["trips"],
        },
        control_keys=["NOM-RTG-14"],
    )
    return action


def _close(
    session: Session,
    agent: Agent,
    control: AgentControl,
    cfg: dict[str, Any],
    *,
    actor: str,
    note: str,
) -> str:
    cfg.update(state=CLOSED, opened_at=None, retry_at=None, probe_since=None, reopens=0)
    _save(control, cfg)
    session.flush()
    _audit(session, agent, "closed", actor, {"note": note})
    finding = open_finding(session, type=FINDING_TYPE, subject_type="agent", subject_id=agent.slug)
    if finding is not None:
        resolve_finding(
            session,
            finding,
            actor=actor,
            note=f"Breaker closed: {note}",
            automated=actor == SYSTEM_ACTOR,
        )
    return "closed"


# ---------------------------------------------------------------------------
# What a person does
# ---------------------------------------------------------------------------


def status(session: Session, agent: Agent) -> dict[str, Any]:
    control = session.scalar(select(AgentControl).where(AgentControl.agent_id == agent.id))
    cfg = config_of(control)
    total, blocked = _counts(session, agent.id, _window_start(cfg, utcnow()))
    return {**cfg, "agent": agent.slug, "window": {"calls": total, "blocked": blocked}}


def configure(session: Session, agent: Agent, changes: dict[str, Any], *, actor: str) -> dict:
    """Change the agent's breaker settings. Turning it off closes it."""
    control = _control(session, agent)
    cfg = config_of(control)
    before = {k: cfg[k] for k in (*LIMITS, "mode")}
    if "mode" in changes and changes["mode"] is not None:
        if changes["mode"] not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        cfg["mode"] = changes["mode"]
    for key, (low, high) in LIMITS.items():
        value = changes.get(key)
        if value is None:
            continue
        value = float(value)
        if not low <= value <= high:
            raise ValueError(f"{key} must be between {low:g} and {high:g}")
        cfg[key] = int(value) if key != "block_ratio" else round(value, 3)
    _save(control, cfg)
    session.flush()
    _audit(
        session,
        agent,
        "configured",
        actor,
        {"before": before, "after": {k: cfg[k] for k in (*LIMITS, "mode")}},
    )
    if cfg["mode"] != "pause" and cfg["state"] != CLOSED:
        _close(session, agent, control, cfg, actor=actor, note="breaker no longer pauses")
    return status(session, agent)


def reset(session: Session, agent: Agent, *, actor: str, reason: str = "") -> dict[str, Any]:
    """Close the breaker now, a person's call."""
    control = _control(session, agent)
    cfg = config_of(control)
    cfg["last_trip_at"] = None
    cfg["count_from"] = utcnow().isoformat()  # count afresh from here
    _close(session, agent, control, cfg, actor=actor, note=reason or "reset by a person")
    return status(session, agent)


__all__ = [
    "FINDING_TYPE",
    "LIMITS",
    "MODES",
    "config_of",
    "configure",
    "observe",
    "refusal",
    "reset",
    "status",
]
