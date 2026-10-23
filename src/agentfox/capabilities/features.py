"""Features: what the workspace turns on for every project, and what one project changes.

A developer thinks "is personal-data masking on for this project?", not "which pack
holds `pii.outbound_redact` and is there an agent-level copy". This module answers in
their terms, for the two kinds of switch the product has:

* **Protections** (`protection.CATALOGUE`): rules in shipped packs. The workspace
  value is the rule as its pack has it. A project's value is its own copy, in its
  layer (``agent.<slug>``), when it has one; without one it inherits. A project can
  always be stricter. It can be looser (lower, or off) only where the workspace lets
  projects change it (the rules' ``overridable`` flag, which this module calls
  ``open_to_projects``), and never for a protected rule. That is the hierarchy's own
  rule (`platform/policy/hierarchy.py`), applied by `protection/scope.py`.
* **Checks** (detectors): `detector_settings` holds the workspace's choice and each
  project's, and a project may change it either way.

Setting a project to the workspace's value removes its copy, so "the same as the
workspace" and "inherited" are one state and a later workspace change reaches it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities import protection
from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection import detector_settings as checks
from agentfox.capabilities.detection.catalog import GROUPS, describe, feeds_for
from agentfox.capabilities.protection import scope
from agentfox.core.models import Policy
from agentfox.platform.ledger import operator_log
from agentfox.platform.policy import (
    PolicyDocument,
    Rule,
    current_binding,
    effective_for,
    load_version_document,
)
from agentfox.platform.policy.model import PROTECTED_RULES
from agentfox.platform.policy.publish import current_mode, publish_in_current_mode

OFF, ON = protection.OFF, protection.ON
_PROTECTED = {rid for ids in PROTECTED_RULES.values() for rid in ids}


class FeatureLocked(ValueError):
    """A project change the workspace does not allow (it would loosen a closed rule)."""


# --- protections: reading -----------------------------------------------------------


def _level(rule: Rule | None) -> str | None:
    """off / on / low / medium / high for one rule copy; None when there is none."""
    if rule is None:
        return None
    if not rule.enabled:
        return OFF
    detection = rule.when.detection
    return protection.level_of(detection.min_score) if detection else ON


def _workspace_rules(session: Session, slug: str | None) -> dict[str, tuple[Rule, str]]:
    """Every rule in force above the project layer: rule id -> (rule, pack key).

    For a project, everything but its own layer (its team's rules included); for the
    workspace, what applies with no project named.
    """
    if slug:
        view = scope._view(session, slug)
        return {rid: (rule, key) for rid, (rule, key, _level) in view.default.items()}
    effective = effective_for(session)
    return {r.rule.id: (r.rule, r.layer.document.key if r.layer else "") for r in effective.rules}


def _mode_word(mode: str | None) -> str | None:
    return {"enforce": "blocking", "observe": "watching"}.get(mode or "")


def protections(session: Session, slug: str | None = None) -> list[dict[str, Any]]:
    """Each protection: the workspace's value, the project's own (or None), what applies."""
    workspace = _workspace_rules(session, slug)
    own = {r.id: r for r in protection.own_layer(session, slug).rules} if slug else {}
    own_mode = current_mode(session, protection.layer_key(slug)) if slug else None
    templates = protection._template_rules()
    out = []
    for p in protection.CATALOGUE:
        first = p.rules[0]
        base = workspace.get(first)
        mine = own.get(first)
        template = templates.get(first)
        graded = bool((base and base[0].when.detection) or (template and template.when.detection))
        ws_level = _level(base[0]) if base else OFF
        open_to_projects = bool(base and base[0].overridable)
        protected = any(r in _PROTECTED for r in p.rules)
        project = _level(mine)
        applied = ws_level
        if project is not None:
            # A looser copy only counts where the workspace lets projects loosen it.
            looser = _rank(project) < _rank(ws_level)
            if not looser or (open_to_projects and not protected):
                applied = project
        out.append(
            {
                "key": p.key,
                "title": p.title,
                "graded": graded,
                "pack": base[1] if base else p.pack,
                "installed": base is not None,
                "available": template is not None or base is not None,
                "workspace": ws_level,
                "workspace_mode": _mode_word(current_mode(session, base[1])) if base else None,
                "open_to_projects": open_to_projects and not protected,
                "protected": protected,
                "project": project,
                "project_mode": _mode_word(own_mode) if project is not None else None,
                "effective": applied,
                "needs": p.needs or None,
            }
        )
    return out


_ORDER = {OFF: 0, "low": 1, "medium": 2, ON: 2, "high": 3}


def _rank(level: str | None) -> int:
    return _ORDER.get(level or OFF, 0)


def _change(level: str, graded: bool) -> dict[str, Any]:
    if level == OFF:
        return {"enabled": False}
    if graded:
        if level not in protection.LEVELS:
            raise ValueError(f"this protection takes off, low, medium or high, not '{level}'")
        return {"enabled": True, "min_score": protection.LEVELS[level]}
    if level != ON:
        raise ValueError(f"this protection is on or off, not '{level}'")
    return {"enabled": True}


# --- protections: writing -----------------------------------------------------------


def _live_doc(session: Session, key: str) -> PolicyDocument | None:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        return None
    _binding, live = current_binding(session, policy.id)
    return load_version_document(live) if live else None


def set_workspace_protection(
    session: Session,
    key: str,
    *,
    level: str | None = None,
    open_to_projects: bool | None = None,
    actor: str,
    reason: str = "",
) -> dict[str, Any]:
    """Change a protection for every project: its rules, edited in the packs that hold
    them, live in the mode each pack is already in (enforcing packs are replayed
    first, as for any generated change)."""
    p = protection.BY_KEY.get(key)
    if p is None:
        raise ValueError(f"unknown protection '{key}'")
    if open_to_projects and any(r in _PROTECTED for r in p.rules):
        raise FeatureLocked(f"'{p.title}' cannot be opened to projects: it is protected")
    workspace = _workspace_rules(session, None)
    by_pack: dict[str, list[str]] = defaultdict(list)
    for rid in p.rules:
        if rid in workspace:
            by_pack[workspace[rid][1]].append(rid)
    if not by_pack:
        raise ValueError(
            f"'{p.title}' needs the {p.pack} pack, which this workspace has not installed"
        )
    before = {"level": _level(workspace[p.rules[0]][0]) if p.rules[0] in workspace else None}
    published = []
    for pack, ids in by_pack.items():
        doc = _live_doc(session, pack)
        if doc is None:
            continue
        data = doc.model_dump(exclude_none=True)
        for r in data["rules"]:
            if r["id"] not in ids:
                continue
            if level is not None:
                change = _change(level, bool(r.get("when", {}).get("detection")))
                r["enabled"] = change["enabled"]
                if "min_score" in change:
                    r["when"]["detection"]["min_score"] = change["min_score"]
            if open_to_projects is not None:
                r["overridable"] = open_to_projects
        result = publish_in_current_mode(
            session,
            PolicyDocument.model_validate(data),
            actor=actor,
            notes=f"{p.title} for every project",
        )
        published.append(
            {
                "policy": pack,
                "version": result.version,
                "mode": result.mode,
                "simulation": result.simulation,
            }
        )
    operator_log.record(
        session,
        "operator.workspace_protection.changed",
        actor=actor,
        reason=reason or f"protection '{key}' changed for every project",
        subject_type="protection",
        subject_id=key,
        before=before,
        after={"level": level, "open_to_projects": open_to_projects},
    )
    return {"published": published}


def set_project_protection(
    session: Session, slug: str, key: str, level: str | None, *, actor: str, reason: str = ""
) -> dict[str, Any]:
    """Set a protection for one project, or with ``None`` go back to the workspace's."""
    p = protection.BY_KEY.get(key)
    if p is None:
        raise ValueError(f"unknown protection '{key}'")
    workspace = _workspace_rules(session, slug)
    if level is None:
        for rid in p.rules:
            scope.reset_for_agent(session, slug, rid, actor=actor, reason=reason or "inherit")
        return {"project": None}
    if not any(rid in workspace for rid in p.rules):
        # Nothing to inherit from: the project's own copy is the whole protection.
        states = {s.protection.key: s.level for s in protection.state(session, slug).protections}
        states[key] = level
        protection.save(session, slug, states, "", actor=actor)
        return {"project": level}
    applied = []
    for rid in p.rules:
        if rid not in workspace:
            continue
        rule, pack = workspace[rid]
        try:
            planned = scope.plan(
                session, pack, rid, [slug], _change(level, rule.when.detection is not None)
            )
        except scope.LooseningNotAllowed as exc:
            raise FeatureLocked(
                f"The workspace does not let projects lower '{p.title}'. Change it for "
                "every project, or let projects change it on the workspace's features."
                if not exc.protected
                else f"'{p.title}' cannot be lowered for a single project."
            ) from exc
        applied += scope.apply_for_agents(
            session,
            planned,
            rule_id=rid,
            actor=actor,
            reason=reason or f"{p.title} {level} for {slug}",
        )
    return {"project": level, "applied": applied}


# --- checks --------------------------------------------------------------------------


def checks_for(session: Session, slug: str | None = None) -> list[dict[str, Any]]:
    """Every detector: whether it is installed, the workspace's switch, the project's."""
    detectors = all_detectors()
    workspace_on = checks.enabled_for(session)
    project = checks.agent_overrides(session, slug) if slug else {}
    group_names = dict(GROUPS)
    feeds = feeds_for(detectors, session)
    out = []
    for key in sorted(detectors):
        if key == checks.WORKSPACE_RULES or key == checks.WORKSPACE_VALIDATORS:
            continue  # on wherever a workspace rule exists; switched with the rule
        d = detectors[key]
        facts = describe(d, feeds)
        mine = project.get(key)
        ws = key in workspace_on
        effective = ws if mine is None else (mine or key in checks.ALWAYS_ON)
        out.append(
            {
                "key": key,
                "label": facts.get("label"),
                "group": facts["group"],
                "group_title": group_names.get(facts["group"], facts["group"]),
                "source": facts["source"],
                "where": facts["where"],
                "finds": facts["finds"],
                "finds_all": facts["finds_all"],
                "installed": d.available(),
                "always_on": key in checks.ALWAYS_ON,
                "workspace": ws,
                "project": mine,
                "effective": effective,
            }
        )
    return out


def features(session: Session, slug: str | None = None) -> dict[str, Any]:
    return {
        "agent": slug,
        "levels": [OFF, *protection.LEVELS],
        "protections": protections(session, slug),
        "checks": checks_for(session, slug),
    }
