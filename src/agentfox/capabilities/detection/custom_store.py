"""Storing a workspace's custom rules, and keeping the `custom` policy pack in step.

A custom rule has two halves. Its *definition* — the words, patterns, topic or
sequence — is a `CustomRule` row, read by the detector (via the enforcer) and by the
sequence check. Its *decision* — the action, the end-user message, whether it is on
— is a rule in the managed ``custom`` policy pack, so it goes through the same
engine, modes, simulation, versioning and tuning screens as every shipped rule.

`sync_policy` is the only writer of that pack. It regenerates the rule list from the
rows and keeps whatever an operator has since tuned on each existing rule (action,
message, sensitivity, on/off), so editing a word list never silently resets the
action someone chose on the Tune tab.

**The enforcing gate holds here too.** Making a version live while the pack enforces
requires a recorded simulation of exactly that version, the same requirement the
`/mode` route imposes on a hand-edited pack. A new custom rule in an enforcing pack is
therefore simulated against recent traffic first, and the impact is returned so the
screen can show it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.detection.custom import (
    CONTENT_KINDS,
    CompiledRule,
    CustomRuleSpec,
    SequenceSpec,
    compile_rule,
    entity_for,
    rule_id_for,
)
from agentfox.core.models import CustomModel, CustomRule, Policy
from agentfox.platform.ledger import operator_log
from agentfox.platform.policy import (
    DetectionCondition,
    PolicyDocument,
    current_binding,
    load_version_document,
)
from agentfox.platform.policy.model import Condition, Rule
from agentfox.platform.policy.publish import Published, publish_in_current_mode

POLICY_KEY = "custom"
POLICY_NAME = "Your rules"


#: What a change to the custom rules published (see `platform/policy/publish.py`).
SyncResult = Published


# --- reading ------------------------------------------------------------------


def spec_of(row: CustomRule) -> CustomRuleSpec:
    return CustomRuleSpec(
        key=row.key,
        name=row.name or row.key,
        kind=row.kind,
        polarity=row.polarity,
        entries=list(row.entries_json or []),
        examples=list(row.examples_json or []),
        description=row.description or "",
        surfaces=list(row.surfaces_json or []),
        agents=list(row.agents_json or []),
        case_sensitive=row.case_sensitive,
        sequence=SequenceSpec(**row.config_json["sequence"])
        if (row.config_json or {}).get("sequence")
        else None,
        enabled=row.enabled,
    )


def list_rules(session: Session) -> list[CustomRule]:
    return list(session.scalars(select(CustomRule).order_by(CustomRule.key)))


def get_rule(session: Session, key: str) -> CustomRule | None:
    return session.scalar(select(CustomRule).where(CustomRule.key == key))


def compiled_rules(session: Session, agent_slug: str | None) -> list[CompiledRule]:
    """The enabled content rules that apply to this agent, ready to match."""
    out: list[CompiledRule] = []
    for row in session.scalars(
        select(CustomRule).where(CustomRule.enabled.is_(True), CustomRule.kind.in_(CONTENT_KINDS))
    ):
        agents = row.agents_json or []
        if agents and agent_slug not in agents:
            continue
        try:
            compiled = compile_rule(spec_of(row))
        except ValueError:  # a row that no longer validates is skipped, never fatal
            continue
        if compiled is not None:
            out.append(compiled)
    return out


def sequence_rules(session: Session, agent_slug: str | None) -> list[tuple[str, SequenceSpec]]:
    out = []
    for row in session.scalars(
        select(CustomRule).where(CustomRule.enabled.is_(True), CustomRule.kind == "sequence")
    ):
        agents = row.agents_json or []
        if agents and agent_slug not in agents:
            continue
        seq = (row.config_json or {}).get("sequence")
        if seq:
            out.append((row.key, SequenceSpec(**seq)))
    return out


# --- writing ------------------------------------------------------------------


@dataclass(frozen=True)
class RuleSeed:
    """How a new rule's policy entry starts out; the Tune tab's to change afterwards."""

    effect: str = "block"
    message: str = ""
    on_block: str = "refuse"
    severity: str = "medium"


def save_rule(
    session: Session,
    spec: CustomRuleSpec,
    *,
    actor: str,
    effect: str = "block",
    message: str = "",
    on_block: str = "refuse",
    severity: str = "medium",
) -> tuple[CustomRule, SyncResult]:
    """Create or update one custom rule, then regenerate the `custom` pack."""
    rows, sync = save_rules(
        session, [(spec, RuleSeed(effect, message, on_block, severity))], actor=actor
    )
    return rows[0], sync


def save_rules(
    session: Session, items: list[tuple[CustomRuleSpec, RuleSeed]], *, actor: str, reason: str = ""
) -> tuple[list[CustomRule], SyncResult]:
    """Create or update several custom rules, then regenerate the `custom` pack once.

    One policy version for the lot, so an import of ten rules is one change to
    review and roll back, not ten.
    """
    rows: list[CustomRule] = []
    seed: dict[str, dict[str, Any]] = {}
    for spec, rule_seed in items:
        row = get_rule(session, spec.key)
        before = _row_json(row) if row else None
        if row is None:
            row = CustomRule(key=spec.key, created_by=actor)
            session.add(row)
        else:
            row.version = (row.version or 1) + 1
        row.name = spec.name
        row.kind = spec.kind
        row.polarity = spec.polarity
        row.entries_json = spec.entries
        row.examples_json = spec.examples
        row.description = spec.description
        row.surfaces_json = spec.surfaces
        row.agents_json = spec.agents
        row.case_sensitive = spec.case_sensitive
        row.config_json = {"sequence": spec.sequence.model_dump()} if spec.sequence else {}
        row.enabled = spec.enabled
        session.flush()
        operator_log.record(
            session,
            "operator.custom_rule.saved",
            actor=actor,
            reason=reason or f"custom rule '{spec.key}' {'updated' if before else 'created'}",
            subject_type="custom_rule",
            subject_id=row.id,
            before=before,
            after=_row_json(row),
        )
        seed[rule_id_for(spec.key)] = {
            "effect": rule_seed.effect,
            "message": rule_seed.message,
            "on_block": rule_seed.on_block,
            "severity": rule_seed.severity,
        }
        rows.append(row)
    return rows, sync_policy(session, actor=actor, seed=seed)


def delete_rule(session: Session, key: str, *, actor: str) -> SyncResult | None:
    row = get_rule(session, key)
    if row is None:
        return None
    operator_log.record(
        session,
        "operator.custom_rule.deleted",
        actor=actor,
        reason=f"custom rule '{key}' deleted",
        subject_type="custom_rule",
        subject_id=row.id,
        before=_row_json(row),
    )
    session.delete(row)
    session.flush()
    return sync_policy(session, actor=actor)


def _row_json(row: CustomRule) -> dict[str, Any]:
    return {
        "key": row.key,
        "kind": row.kind,
        "polarity": row.polarity,
        "entries": list(row.entries_json or []),
        "agents": list(row.agents_json or []),
        "enabled": row.enabled,
    }


def _policy_rule(row: CustomRule, previous: Rule | None, seed: dict[str, Any]) -> Rule:
    spec = spec_of(row)
    rid = rule_id_for(row.key)
    if spec.kind == "sequence":
        when = Condition(action_risk=rid)
    else:
        when = Condition(
            detection=DetectionCondition(
                entity_prefix=spec.entity,
                min_score=previous.when.detection.min_score
                if previous and previous.when.detection
                else 0.5,
            )
        )
    kept = previous or Rule(id=rid, **{k: v for k, v in seed.items() if v not in (None, "")})
    return Rule(
        id=rid,
        description=spec.name,
        when=when,
        effect=kept.effect,
        reason=f"{spec.name} — your rule",
        severity=kept.severity,
        enabled=kept.enabled and spec.enabled,
        message=kept.message,
        on_block=kept.on_block,
        redaction=kept.redaction,
    )


def _model_policy_rule(row: CustomModel, previous: Rule | None, seed: dict[str, Any]) -> Rule:
    """The rule for a workspace model reporting under `CUSTOM` (`custom_models.py`)."""
    rid = rule_id_for(row.key)
    kept = previous or Rule(id=rid, **{k: v for k, v in seed.items() if v not in (None, "")})
    return Rule(
        id=rid,
        description=row.name or row.key,
        when=Condition(
            detection=DetectionCondition(
                entity_prefix=entity_for(row.key),
                min_score=previous.when.detection.min_score
                if previous and previous.when.detection
                else row.threshold,
            )
        ),
        effect=kept.effect,
        reason=f"{row.name or row.key}: your model",
        severity=kept.severity,
        enabled=kept.enabled and row.enabled,
        message=kept.message,
        on_block=kept.on_block,
        redaction=kept.redaction,
    )


def sync_policy(
    session: Session, *, actor: str, seed: dict[str, dict[str, Any]] | None = None
) -> SyncResult:
    """Regenerate the `custom` pack from the rows and make it live in its current mode."""
    seed = seed or {}
    policy = session.scalar(select(Policy).where(Policy.key == POLICY_KEY))
    live = current_binding(session, policy.id)[1] if policy else None
    previous: dict[str, Rule] = {}
    if live is not None:
        previous = {r.id: r for r in load_version_document(live).rules}

    rows = list_rules(session)
    doc = PolicyDocument(
        key=POLICY_KEY,
        name=POLICY_NAME,
        description=(
            "Rules written in your own words: blocked words and patterns, topics, "
            "sequences of actions, and your own models."
        ),
        rules=[
            _policy_rule(r, previous.get(rule_id_for(r.key)), seed.get(rule_id_for(r.key), {}))
            for r in rows
        ]
        + [
            _model_policy_rule(
                m, previous.get(rule_id_for(m.key)), seed.get(rule_id_for(m.key), {})
            )
            for m in session.scalars(
                select(CustomModel)
                .where(CustomModel.entity_prefix == "CUSTOM")
                .order_by(CustomModel.key)
            )
            if m.key not in {r.key for r in rows}
        ],
    )
    return publish_in_current_mode(session, doc, actor=actor, notes="custom rules changed")
