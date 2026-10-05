"""Storage and retrieval of business rules.

Separate from the policy store for the same reason the evaluation is separate: a
ladder is not a rule with more fields, and putting it in the same table would invite
the same list to be evaluated by the same maximum, which is exactly the composition
mistake this whole package exists to avoid.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.business.ladder import Ladder
from agentfox.core.models import Agent, BusinessRule
from agentfox.prove.audit.operator_log import record

log = logging.getLogger(__name__)


def save_ladder(
    session: Session,
    ladder: Ladder,
    *,
    agent_slug: str | None = None,
    enabled: bool = True,
    actor: str = "",
    reason: str = "",
) -> BusinessRule:
    """Upsert a ladder, bumping its version.

    Versions matter here for the same reason they matter for policy: an auditor asking
    why a refund was approved in March needs the thresholds that were in force in
    March, not the ones agreed since.

    Changing a ladder changes what gets auto-approved, which makes it an operator
    action rather than a configuration write — so it records who changed it, why, and
    what the bands were before.
    """
    agent_id = None
    if agent_slug:
        agent = session.scalar(select(Agent).where(Agent.slug == agent_slug))
        if agent is None:
            raise ValueError(f"unknown agent '{agent_slug}'")
        agent_id = agent.id

    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == ladder.key))
    previous = dict(rule.definition_json or {}) if rule is not None else None
    if rule is None:
        rule = BusinessRule(key=ladder.key)
        session.add(rule)
    else:
        rule.version += 1

    rule.kind = "threshold_ladder"
    rule.owner = ladder.owner
    rule.description = ladder.description
    rule.agent_id = agent_id
    rule.tool = ladder.tool
    rule.field_path = ladder.field_path
    rule.definition_json = ladder.model_dump(by_alias=True, mode="json")
    rule.mode = ladder.mode
    rule.enabled = enabled
    session.flush()

    record(
        session,
        "operator.business_rule.changed",
        actor=actor or ladder.owner or "unknown",
        reason=reason or ("rule created" if previous is None else "rule updated"),
        subject_type="business_rule",
        subject_id=ladder.key,
        before={"bands": previous.get("bands")} if previous else None,
        after={
            "bands": rule.definition_json.get("bands"),
            "mode": rule.mode,
            "version": rule.version,
        },
    )
    return rule


def load_ladders(
    session: Session, *, tool: str | None = None, agent_id: str | None = None
) -> list[Ladder]:
    """Every enabled ladder that could apply, newest definition first.

    A definition that no longer validates is skipped and logged rather than raising:
    one malformed rule written months ago must not take the enforcement path down for
    every other rule that is fine.
    """
    stmt = select(BusinessRule).where(BusinessRule.enabled.is_(True))
    if tool is not None:
        stmt = stmt.where((BusinessRule.tool == tool) | (BusinessRule.tool.is_(None)))
    if agent_id is not None:
        stmt = stmt.where((BusinessRule.agent_id == agent_id) | (BusinessRule.agent_id.is_(None)))

    out: list[Ladder] = []
    for rule in session.scalars(stmt):
        if rule.kind != "threshold_ladder":
            continue
        try:
            out.append(Ladder.model_validate(rule.definition_json))
        except Exception as exc:
            log.warning("business rule '%s' no longer validates and was skipped: %s", rule.key, exc)
    return out


def all_ladders(session: Session) -> list[Ladder]:
    return load_ladders(session)


def set_mode(
    session: Session, key: str, mode: str, *, actor: str = "", reason: str = ""
) -> BusinessRule:
    """Move a rule between observe and enforce.

    The same rule with the opposite effect, which is why this is recorded separately
    from a definition change: an investigation asking "was this rule live in March?"
    is asking about the mode, not the bands.
    """
    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    if rule is None:
        raise ValueError(f"unknown business rule '{key}'")
    if mode not in ("observe", "enforce"):
        raise ValueError("mode must be 'observe' or 'enforce'")
    previous = rule.mode
    rule.mode = mode
    definition = dict(rule.definition_json or {})
    definition["mode"] = mode
    rule.definition_json = definition
    session.flush()
    record(
        session,
        "operator.business_rule.mode_changed",
        actor=actor or "unknown",
        reason=reason or f"mode set to {mode}",
        subject_type="business_rule",
        subject_id=key,
        before={"mode": previous},
        after={"mode": mode},
    )
    return rule


def summary(session: Session) -> dict[str, Any]:
    records = list(session.scalars(select(BusinessRule)))
    return {
        "rules": len(records),
        "enabled": sum(1 for r in records if r.enabled),
        "enforcing": sum(1 for r in records if r.mode == "enforce" and r.enabled),
        "owners": sorted({r.owner for r in records if r.owner}),
        "by_kind": {
            kind: sum(1 for r in records if r.kind == kind)
            for kind in sorted({r.kind for r in records})
        },
    }
