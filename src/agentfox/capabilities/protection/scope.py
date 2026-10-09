"""Changing one rule for some agents only.

A rule lives in a pack that applies to every agent. Editing it there changes it for
all of them. To change it for a few, the changed copy goes into each chosen agent's
own layer (``agent.<slug>``, bound at the *agent* level of the hierarchy), where it
wins over the workspace copy for that agent and nobody else.

The hierarchy decides what such a copy may do (`platform/policy/hierarchy.py`):

* **Tighter** (a stronger action, or more sensitive): always allowed. The workspace
  rule stays in force beside it, so an agent can only add caution.
* **Looser** (a weaker action, switched off, or less sensitive): only where the
  workspace rule is marked ``overridable``. Anything else is refused here with
  `LooseningNotAllowed` rather than written as a copy that would do nothing.
* Rules a pack may not ship without (`PROTECTED_RULES`) are never loosened per agent.

"Everything it hands off to" follows ``delegates_to`` lineage edges transitively, so
a change for an orchestrator reaches the sub-agents doing its work.

Each layer is published in the mode it is already in (`publish_in_current_mode`):
an enforcing layer is simulated against that agent's recent traffic first, and a new
layer starts watching. Every write is an operator action in the audit chain.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.protection import layer_key, own_layer
from agentfox.core.models import Agent, LineageEdge, Policy
from agentfox.platform.ledger import operator_log
from agentfox.platform.policy import (
    PolicyDocument,
    Rule,
    current_binding,
    effective_for,
    load_version_document,
    loosens,
    resolve_effective,
)
from agentfox.platform.policy.model import PROTECTED_RULES
from agentfox.platform.policy.publish import Published, current_mode, publish_in_current_mode
from agentfox.platform.policy.simulate import simulate

#: The fields a per-agent change may set, as the rule tuner offers them.
FIELDS = ("effect", "enabled", "min_score", "message", "on_block")

_PROTECTED = {rid for ids in PROTECTED_RULES.values() for rid in ids}


class LooseningNotAllowed(ValueError):
    """A per-agent change would weaken a workspace rule that does not allow it."""

    def __init__(self, rule_id: str, agent: str, policy: str, why: str) -> None:
        self.rule_id = rule_id
        self.agent = agent
        self.policy = policy
        self.protected = rule_id in _PROTECTED
        super().__init__(why)


# --- who --------------------------------------------------------------------


def delegates(session: Session, slug: str) -> list[str]:
    """Every agent ``slug`` hands work to, directly or through another agent."""
    edges: dict[str, list[str]] = {}
    for edge in session.scalars(
        select(LineageEdge).where(
            LineageEdge.relation == "delegates_to", LineageEdge.dst_type == "agent"
        )
    ):
        edges.setdefault(edge.src_id, []).append(edge.dst_id)
    seen: list[str] = []
    queue = deque(edges.get(slug, []))
    while queue:
        nxt = queue.popleft()
        if nxt == slug or nxt in seen:
            continue
        seen.append(nxt)
        queue.extend(edges.get(nxt, []))
    return seen


def agent_tree(session: Session) -> list[dict[str, Any]]:
    """Every agent, with the agents it hands off to nested under it.

    An agent nobody delegates to is a root. One delegated to by several is shown
    under the first; a cycle is cut where it closes.
    """
    agents = {
        a.slug: a
        for a in session.scalars(select(Agent).order_by(Agent.slug))
        if a.status != "draft"
    }
    children: dict[str, list[str]] = {}
    has_parent: set[str] = set()
    for edge in session.scalars(
        select(LineageEdge)
        .where(LineageEdge.relation == "delegates_to", LineageEdge.dst_type == "agent")
        .order_by(LineageEdge.src_id, LineageEdge.dst_id)
    ):
        children.setdefault(edge.src_id, []).append(edge.dst_id)
        if edge.src_id != edge.dst_id:
            has_parent.add(edge.dst_id)

    slugs = sorted(set(agents) | set(children) | has_parent)
    out: list[dict[str, Any]] = []
    placed: set[str] = set()

    def walk(slug: str, depth: int, parent: str | None) -> None:
        if slug in placed:
            return
        placed.add(slug)
        agent = agents.get(slug)
        out.append(
            {
                "slug": slug,
                "name": (agent.name if agent else "") or slug,
                "depth": depth,
                "parent": parent,
                "registered": agent is not None,
            }
        )
        for child in children.get(slug, []):
            walk(child, depth + 1, slug)

    for slug in slugs:
        if slug not in has_parent:
            walk(slug, 0, None)
    for slug in slugs:  # anything only reachable through a cycle
        walk(slug, 0, None)
    return out


# --- reading ----------------------------------------------------------------


def _summary(rule: Rule) -> dict[str, Any]:
    return {
        "effect": rule.effect,
        "enabled": rule.enabled,
        "min_score": rule.when.detection.min_score if rule.when.detection else None,
        "message": rule.message,
        "on_block": rule.on_block,
        "overridable": rule.overridable,
    }


@dataclass
class _View:
    """One agent's rules: its own layer, and what it would get without it."""

    own: PolicyDocument
    default: dict[str, tuple[Rule, str, str]]  # rule id -> (rule, policy key, level)
    effective: Any = None
    own_layer: Any = None


def _view(session: Session, slug: str) -> _View:
    effective = effective_for(session, slug)
    key = layer_key(slug)
    mine = next((layer for layer in effective.applicable if layer.document.key == key), None)
    rest = [layer for layer in effective.applicable if layer is not mine]
    default = resolve_effective(rest, effective.subject)
    return _View(
        own=own_layer(session, slug),
        default={
            r.rule.id: (r.rule, r.layer.document.key if r.layer else "", r.level)
            for r in default.rules
        },
        effective=effective,
        own_layer=mine,
    )


def _has_effect(view: _View, rule: Rule) -> bool:
    """Whether this agent's copy changes anything, given what the hierarchy allows."""
    base = view.default.get(rule.id)
    if base is None or not loosens(rule, base[0]):
        return True
    won = next((r for r in view.effective.rules if r.rule.id == rule.id), None)
    return bool(won and won.layer is view.own_layer and won.loosened)


def agent_changes(session: Session, slug: str) -> list[dict[str, Any]]:
    """The rules this agent's own layer sets, against the workspace default for each.

    ``kind`` is ``changed`` when the workspace also has the rule and ``added`` when
    only this agent does. ``has_effect`` is false for a looser copy the hierarchy
    did not allow: the workspace rule still applies.
    """
    view = _view(session, slug)
    out = []
    for rule in view.own.rules:
        base = view.default.get(rule.id)
        out.append(
            {
                "rule_id": rule.id,
                "description": rule.description,
                "kind": "changed" if base else "added",
                "agent": _summary(rule),
                "default": (
                    {**_summary(base[0]), "policy": base[1], "level": base[2]} if base else None
                ),
                "has_effect": _has_effect(view, rule),
            }
        )
    return out


def rule_agents(session: Session, key: str, rule_id: str) -> dict[str, Any]:
    """Every agent, nested by hand-off, with whether it has its own copy of this rule."""
    tree = agent_tree(session)
    out = []
    for node in tree:
        own = next((r for r in own_layer(session, node["slug"]).rules if r.id == rule_id), None)
        out.append({**node, "own": _summary(own) if own else None})
    base = _pack_rule(session, key, rule_id)
    return {
        "policy": key,
        "rule_id": rule_id,
        "overridable": bool(base and base.overridable),
        "protected": rule_id in _PROTECTED,
        "agents": out,
    }


def _pack_rule(session: Session, key: str, rule_id: str) -> Rule | None:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        return None
    _binding, live = current_binding(session, policy.id)
    if live is None:
        return None
    doc = load_version_document(live)
    return next((r for r in doc.rules if r.id == rule_id), None)


# --- planning ---------------------------------------------------------------


@dataclass
class Planned:
    agent: str
    doc: PolicyDocument
    rule: Rule | None  # None: the agent's copy is removed (back to the default)
    before: dict[str, Any] | None
    mode: str | None
    tighter: bool
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "policy": self.doc.key,
            "mode": self.mode or "observe",
            "before": self.before,
            "after": _summary(self.rule) if self.rule else None,
            "tighter": self.tighter,
        }


def _changed(rule: Rule, change: dict[str, Any]) -> Rule:
    data = rule.model_dump(exclude_none=True)
    for name in FIELDS:
        value = change.get(name)
        if value is None:
            continue
        if name == "min_score":
            if not data.get("when", {}).get("detection"):
                raise ValueError(
                    f"rule '{rule.id}' does not test a detection, so it has no sensitivity"
                )
            data["when"]["detection"]["min_score"] = value
        elif name == "message":
            data["message"] = str(value).strip()
        else:
            data[name] = value
    return Rule.model_validate(data)


def _same(a: Rule, b: Rule) -> bool:
    return a.model_dump() == b.model_dump()


def plan(
    session: Session,
    key: str,
    rule_id: str,
    agents: list[str],
    change: dict[str, Any],
    *,
    include_delegates: bool = False,
) -> list[Planned]:
    """What each chosen agent's layer would become. Writes nothing.

    Raises `LooseningNotAllowed` for the first agent where the change would weaken
    a workspace rule that is not ``overridable``, and `ValueError` for a change the
    rule cannot take.
    """
    change = {k: v for k, v in change.items() if k in FIELDS and v is not None}
    if not change:
        raise ValueError("nothing to change")
    targets: list[str] = []
    for slug in agents:
        for s in [slug, *(delegates(session, slug) if include_delegates else [])]:
            if s not in targets:
                targets.append(s)
    pack_rule = _pack_rule(session, key, rule_id)

    planned: list[Planned] = []
    for slug in targets:
        view = _view(session, slug)
        own = next((r for r in view.own.rules if r.id == rule_id), None)
        base = view.default.get(rule_id)
        start = own or (base[0] if base else None) or pack_rule
        if start is None:
            raise ValueError(f"no rule '{rule_id}' in '{key}'")
        new = _changed(start.model_copy(deep=True), change)

        parent = base[0] if base else None
        if parent is not None and loosens(new, parent):
            where = base[1]
            if rule_id in _PROTECTED:
                raise LooseningNotAllowed(
                    rule_id,
                    slug,
                    where,
                    f"'{rule_id}' cannot be loosened for any agent. It stops an agent "
                    "switching off the other rules.",
                )
            if not parent.overridable:
                raise LooseningNotAllowed(
                    rule_id,
                    slug,
                    where,
                    f"This would loosen '{rule_id}' for {slug}, and the workspace rule in "
                    f"'{where}' does not allow agents to loosen it. Tighten it instead, "
                    "or allow agents to loosen it on the workspace rule first.",
                )

        rules = [r for r in view.own.rules if r.id != rule_id]
        keep = parent is None or not _same(new, parent)
        if keep:
            rules.append(new)
        doc = view.own.model_copy(update={"rules": rules})
        planned.append(
            Planned(
                agent=slug,
                doc=doc,
                rule=new if keep else None,
                before=_summary(own) if own else None,
                mode=current_mode(session, doc.key),
                tighter=parent is None or not loosens(new, parent),
            )
        )
    return planned


def preview(session: Session, planned: list[Planned], days: int = 7) -> dict[str, Any]:
    """Replay each agent's recent traffic against its new layer, as if enforcing."""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    totals = {"newly_blocked": 0, "newly_allowed": 0, "newly_escalated": 0}
    replayed = 0
    for p in planned:
        diff = simulate(session, p.doc, agent_slug=p.agent, since=since).to_json()
        replayed += diff["replayed"]
        for k in totals:
            totals[k] += diff["counts"][k]
    return {"replayed": replayed, "counts": totals}


# --- writing ----------------------------------------------------------------


def apply_for_agents(
    session: Session, planned: list[Planned], *, rule_id: str, actor: str, reason: str
) -> list[dict[str, Any]]:
    """Write each planned agent layer, live in the mode that layer is already in."""
    out = []
    for p in planned:
        operator_log.record(
            session,
            "operator.agent_rule.changed",
            actor=actor,
            reason=reason,
            subject_type="agent",
            subject_id=p.agent,
            before=p.before,
            after=_summary(p.rule) if p.rule else None,
            extra={"rule": rule_id, "policy": p.doc.key},
        )
        published = _publish(session, p.agent, p.doc, actor=actor, notes=f"{rule_id} for {p.agent}")
        out.append({**p.to_json(), **_published(published)})
    return out


def reset_for_agent(
    session: Session, slug: str, rule_id: str, *, actor: str, reason: str
) -> dict[str, Any] | None:
    """Remove this agent's own copy of a rule, so the workspace rule applies again.

    Returns None when the agent has no copy of the rule.
    """
    own = own_layer(session, slug)
    current = next((r for r in own.rules if r.id == rule_id), None)
    if current is None:
        return None
    operator_log.record(
        session,
        "operator.agent_rule.reset",
        actor=actor,
        reason=reason,
        subject_type="agent",
        subject_id=slug,
        before=_summary(current),
        after=None,
        extra={"rule": rule_id, "policy": own.key},
    )
    doc = own.model_copy(update={"rules": [r for r in own.rules if r.id != rule_id]})
    published = _publish(session, slug, doc, actor=actor, notes=f"{rule_id} reset for {slug}")
    return {"agent": slug, "rule_id": rule_id, **_published(published)}


def _publish(session: Session, slug: str, doc: PolicyDocument, *, actor: str, notes: str):
    return publish_in_current_mode(
        session,
        doc,
        actor=actor,
        notes=notes,
        level="agent",
        scope_id=slug,
        compose="extend",
        agent_slug=slug,
    )


def _published(p: Published) -> dict[str, Any]:
    return {"version": p.version, "mode": p.mode, "simulation": p.simulation}
