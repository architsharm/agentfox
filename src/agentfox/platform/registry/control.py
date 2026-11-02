"""Kill switch and quarantine.

The control every competitor ships. Design decisions worth stating:

* **Reversible.** An irreversible kill switch is one nobody dares use, so it stays
  unused during the incident it was built for. Both states resume cleanly.
* **Audited on both edges.** Stopping an agent and restarting it are equally
  interesting to an auditor — "who turned it back on, and why" is the harder question.
* **Checked before anything else.** `Enforcer.preflight` consults this before taint,
  detectors or policy. A killed agent must not reach a model even if every policy
  would have allowed it.
* **Not an issue.** Pausing is someone's own decision, so it is recorded (audit chain,
  control history) rather than raised as an open finding against the person who did it.
* **Two states, not one.** `quarantined` ("we are investigating") and `killed`
  ("stop now") block identically but declare different intent, and an incident review
  will ask which was declared.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, AgentControl, AuditEntry, utcnow
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.findings import open_finding, resolve_finding

STATES = ("active", "quarantined", "killed")


class UnknownAgent(Exception):
    pass


def _agent(session: Session, slug: str) -> Agent:
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    if agent is None:
        raise UnknownAgent(f"unknown agent '{slug}'")
    return agent


def get_control(session: Session, slug: str) -> AgentControl | None:
    agent = _agent(session, slug)
    return session.scalar(select(AgentControl).where(AgentControl.agent_id == agent.id))


def state_of(session: Session, slug: str) -> str:
    control = get_control(session, slug)
    return control.state if control else "active"


def set_state(
    session: Session,
    slug: str,
    state: str,
    *,
    reason: str = "",
    actor: str = "system",
) -> AgentControl:
    """Transition an agent between active / quarantined / killed."""
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    agent = _agent(session, slug)

    control = session.scalar(select(AgentControl).where(AgentControl.agent_id == agent.id))
    if control is None:
        control = AgentControl(agent_id=agent.id, state="active")
        session.add(control)
        session.flush()

    previous = control.state
    if previous == state:
        return control

    control.previous_state = previous
    control.state = state
    control.reason = reason or None
    control.actor = actor
    control.changed_at = utcnow()
    session.flush()

    chain.append(
        session,
        f"agent.{state}" if state != "active" else "agent.resumed",
        actor_type="user",
        actor_id=actor,
        subject_type="agent",
        subject_id=agent.id,
        payload={
            "agent": agent.slug,
            "from": previous,
            "to": state,
            "reason": reason,
        },
    )

    # Pausing or stopping is a person's own deliberate action: it is recorded in the
    # audit chain above (and shown as the agent's control history), not raised as an
    # open issue that would page the very person who just clicked it. Earlier
    # versions did raise an `agent_stopped` finding per stop; any still open close on
    # resume, under the name of the person who resumed it.
    if state == "active":
        for stopped in ("quarantined", "killed"):
            finding = open_finding(
                session,
                type="agent_stopped",
                subject_type="agent",
                subject_id=agent.id,
                fingerprint_parts=(stopped,),
            )
            if finding is not None:
                resolve_finding(
                    session,
                    finding,
                    actor=actor,
                    note=f"agent resumed from {previous}: {reason or 'no reason given'}",
                )
    session.flush()
    return control


def quarantine(session: Session, slug: str, *, reason: str = "", actor: str = "system"):
    return set_state(session, slug, "quarantined", reason=reason, actor=actor)


def kill(session: Session, slug: str, *, reason: str = "", actor: str = "system"):
    return set_state(session, slug, "killed", reason=reason, actor=actor)


def resume(session: Session, slug: str, *, reason: str = "", actor: str = "system"):
    return set_state(session, slug, "active", reason=reason, actor=actor)


def all_controls(session: Session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    from agentfox.platform.registry.breaker import config_of

    for control in session.scalars(select(AgentControl)):
        agent = session.get(Agent, control.agent_id)
        breaker = config_of(control)
        out.append(
            {
                "agent": agent.slug if agent else control.agent_id,
                "state": control.state,
                "previous_state": control.previous_state,
                "reason": control.reason,
                "actor": control.actor,
                "changed_at": control.changed_at.isoformat() if control.changed_at else None,
                "breaker": {
                    k: breaker[k] for k in ("mode", "state", "retry_at", "reason", "trips")
                },
            }
        )
    return out


#: The audit actions that make up an agent's control history: a person's pause, stop
#: and resume, and the circuit breaker's own transitions and settings changes.
_HISTORY_ACTIONS = ("agent.quarantined", "agent.killed", "agent.resumed")


def history(session: Session, slug: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Who paused, stopped or resumed this agent (and what the breaker did), newest first.

    Read from the audit chain, so it is the same record an auditor verifies.
    """
    agent = _agent(session, slug)
    rows = session.scalars(
        select(AuditEntry)
        .where(
            AuditEntry.subject_type == "agent",
            AuditEntry.subject_id == agent.id,
            AuditEntry.action.in_(_HISTORY_ACTIONS) | AuditEntry.action.like("agent.breaker.%"),
        )
        .order_by(AuditEntry.seq.desc())
        .limit(max(1, min(int(limit), 200)))
    )
    out: list[dict[str, Any]] = []
    for e in rows:
        payload = e.payload_json or {}
        occurred = e.occurred_at
        out.append(
            {
                "action": e.action,
                "actor": e.actor_id,
                "actor_type": e.actor_type,
                "at": occurred.isoformat() if occurred else None,
                "from": payload.get("from"),
                "to": payload.get("to"),
                "reason": payload.get("reason")
                or payload.get("note")
                or payload.get("after")
                or None,
            }
        )
    return out


def control_of(session: Session, slug: str, *, limit: int = 20) -> dict[str, Any]:
    """One agent's control record, with its history: what the agent page's banner and
    Controls tab show."""
    control = get_control(session, slug)
    return {
        "agent": slug,
        "state": control.state if control else "active",
        "previous_state": control.previous_state if control else None,
        "reason": control.reason if control else None,
        "actor": control.actor if control else None,
        "changed_at": control.changed_at.isoformat() if control and control.changed_at else None,
        "history": history(session, slug, limit=limit),
    }
