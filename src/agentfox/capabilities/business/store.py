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

from agentfox.capabilities.business.ladder import Ladder
from agentfox.core.models import Agent, BusinessRule
from agentfox.platform.ledger.operator_log import record

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


def delete_ladder(session: Session, key: str, *, actor: str = "", reason: str = "") -> bool:
    """Remove a business rule. Recorded with its bands, since what it decided stops."""
    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    if rule is None:
        return False
    record(
        session,
        "operator.business_rule.deleted",
        actor=actor or "unknown",
        reason=reason or "rule deleted",
        subject_type="business_rule",
        subject_id=key,
        before={"bands": (rule.definition_json or {}).get("bands"), "mode": rule.mode},
    )
    session.delete(rule)
    session.flush()
    return True


#: The order a ladder's outcomes are named by: its strongest band decides what the
#: rule "does" in a list of rules.
STRONGEST = ("block", "escalate", "verify", "redact", "allow")

#: The library a business rule someone wrote (New rule → "Approve above an amount")
#: belongs to: the same "Your rules" as the custom pack's rules.
OWN_LIBRARY = "Your rules"


def rule_id(key: str) -> str:
    """The id a business rule fires under, and the id every list of rules shows."""
    return f"business.{key}"


def strongest_outcome(definition: dict[str, Any]) -> str:
    outcomes = {str(b.get("outcome") or "allow") for b in definition.get("bands") or []}
    return next((o for o in STRONGEST if o in outcomes), "allow")


def _ladder_libraries() -> dict[str, str]:
    """Ladder key -> the title of the shipped library it came from."""
    import yaml

    from agentfox.platform.packs.loader import load_packs

    out: dict[str, str] = {}
    try:
        packs = load_packs()
    except Exception:  # pragma: no cover - a broken pack must not hide the rules
        return out
    for pack in packs:
        for path in pack.files("ladders"):
            try:
                key = (yaml.safe_load(path.read_text()) or {}).get("key")
            except Exception:
                continue
            if key:
                out[str(key)] = pack.manifest.title
    return out


def rule_entries(session: Session) -> list[dict[str, Any]]:
    """Every enabled business rule as a rule in force, in the shape the lists of rules
    take: ``id`` (``business.<key>``), what it does at its strictest band, whether it
    enforces, the agent it is limited to (None: every agent) and its library.

    A business rule is stored apart from the policy packs (it composes by a different
    algebra, see the module docstring), but to a person it is one more rule: Applied
    rules, the rule's page and ``agentfox policy effective`` list it beside the rest.
    """
    rows = list(
        session.scalars(
            select(BusinessRule).where(BusinessRule.enabled.is_(True)).order_by(BusinessRule.key)
        )
    )
    if not rows:
        return []
    libraries = _ladder_libraries()
    slugs = {a.id: a.slug for a in session.scalars(select(Agent))}
    out = []
    for rule in rows:
        definition = dict(rule.definition_json or {})
        effect = strongest_outcome(definition)
        # A rule compiled from a sentence keeps the sentence on its deciding band.
        said = next(
            (
                str(b.get("reason"))
                for b in definition.get("bands") or []
                if b.get("outcome") == effect and b.get("reason")
            ),
            "",
        )
        out.append(
            {
                "rule_id": rule_id(rule.key),
                "key": rule.key,
                "title": definition.get("name") or rule.key,
                "description": rule.description or definition.get("description") or said,
                "effect": effect,
                "enforcement": "enforce" if rule.mode == "enforce" else "observe",
                "tool": rule.tool,
                "agent": slugs.get(rule.agent_id or "") if rule.agent_id else None,
                "library": libraries.get(rule.key, OWN_LIBRARY),
                "version": rule.version,
            }
        )
    return out


def effective_entries(session: Session, agent_slug: str | None = None) -> list[dict[str, Any]]:
    """The business rules in force for ``agent_slug`` (every agent when None), in the
    shape of `EffectivePolicy.explain()` rules, so ``policy effective`` lists them.

    ``source`` is ``business``: a business rule is not a layer of the hierarchy, and
    each enforces or watches by its own mode."""
    return [
        {
            "rule_id": e["rule_id"],
            # A rule compiled from a sentence has no name of its own; the sentence is.
            "title": e["title"] if e["title"] != e["key"] else (e["description"] or e["key"]),
            "description": e["description"],
            "effect": e["effect"],
            "level": "business",
            "scope": e["agent"] or "*",
            "mode": e["enforcement"],
            "enforcement": e["enforcement"],
            "overrides": [],
            "loosened": False,
            "source": f"business:{e['agent'] or '*'}",
            "policy": None,
            "library": e["library"],
        }
        for e in rule_entries(session)
        if e["agent"] is None or agent_slug is None or e["agent"] == agent_slug
    ]


def history(session: Session, key: str) -> list[dict[str, Any]]:
    """Every saved version of a business rule, newest first: its bands, who saved it,
    when and why. Read from the audit chain, where `save_ladder` records each one
    (``operator.business_rule.changed``); ``live`` marks the version in force."""
    from agentfox.core.models import AuditEntry

    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    rows = session.scalars(
        select(AuditEntry)
        .where(
            AuditEntry.subject_type == "business_rule",
            AuditEntry.subject_id == key,
            AuditEntry.action == "operator.business_rule.changed",
        )
        .order_by(AuditEntry.seq.desc())
    ).all()
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        payload = row.payload_json or {}
        after = payload.get("after") or {}
        version = after.get("version")
        if not isinstance(version, int) or version in seen or not after.get("bands"):
            continue
        seen.add(version)
        out.append(
            {
                "version": version,
                "bands": after["bands"],
                "at": row.occurred_at.isoformat() if row.occurred_at else None,
                "author": row.actor_id,
                "notes": payload.get("reason") or "",
                "live": rule is not None and rule.version == version,
            }
        )
    return out


def restore_version(session: Session, key: str, version: int, *, actor: str = "") -> BusinessRule:
    """Put an earlier version's bands back, as a new version in the rule's current
    mode. Raises ValueError for an unknown rule or version."""
    rule = session.scalar(select(BusinessRule).where(BusinessRule.key == key))
    if rule is None:
        raise ValueError(f"unknown business rule '{key}'")
    saved = next((v for v in history(session, key) if v["version"] == version), None)
    if saved is None:
        raise ValueError(f"business rule '{key}' has no recorded version {version}")
    if rule.version == version:
        raise ValueError(f"version {version} of '{key}' is already live")
    definition = {k: v for k, v in dict(rule.definition_json or {}).items() if k != "kind"}
    definition.update({"key": key, "bands": saved["bands"], "mode": rule.mode})
    ladder = Ladder.model_validate(definition)
    agent = session.get(Agent, rule.agent_id) if rule.agent_id else None
    return save_ladder(
        session,
        ladder,
        agent_slug=agent.slug if agent else None,
        enabled=rule.enabled,
        actor=actor,
        reason=f"Restored version {version}",
    )


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
