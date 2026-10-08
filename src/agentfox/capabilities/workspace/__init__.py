"""A workspace's guardrails as one file, for teams that keep configuration in git.

``export_bundle`` writes everything an operator configured — every bound policy with
its mode and place in the hierarchy (shipped packs, the `custom` pack, each agent's
protection layer), the custom rules behind the `custom` pack, and the detector
switches — as one YAML document. ``plan`` compares a file with the workspace and
``apply`` makes the workspace match it.

Three rules keep applying a file from being the easy way to switch protection off:

* **Nothing the file omits is removed.** A policy, custom rule or detector switch
  missing from the file is left alone and reported as such. Deleting is done on
  purpose, in the dashboard, one thing at a time.
* **Enforcing still needs a simulation.** A policy the file moves to ``enforce`` is
  replayed over the last week first and the simulation recorded, exactly what the
  ``/mode`` route requires, and the impact is returned.
* **Everything is audited.** Custom rules and detectors go through their own audited
  writers; the apply itself is one operator-log entry listing what changed.

The file is data: it is parsed with ``yaml.safe_load`` and validated by the same
models a hand-made change goes through, so it can never express more than the
dashboard can.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.detection.custom import CustomRuleSpec
from agentfox.capabilities.detection.custom_store import RuleSeed, list_rules, save_rules, spec_of
from agentfox.capabilities.detection.detector_settings import overrides, set_enabled
from agentfox.core.models import Policy
from agentfox.platform.ledger import operator_log
from agentfox.platform.policy import PolicyDocument, current_binding, load_version_document
from agentfox.platform.policy.publish import publish_in_current_mode
from agentfox.platform.policy.simulate import record_simulation, simulate
from agentfox.platform.policy.store import set_mode

KIND = "agentfox/workspace"
FORMAT_VERSION = 1


class PolicyEntry(BaseModel):
    key: str
    mode: Literal["observe", "enforce"] = "observe"
    level: Literal["org", "team", "agent", "user"] = "org"
    scope: str = "*"
    compose: Literal["extend", "restrict", "override"] = "extend"
    policy: dict[str, Any]


class Bundle(BaseModel):
    kind: Literal["agentfox/workspace"] = KIND
    version: int = FORMAT_VERSION
    policies: list[PolicyEntry] = Field(default_factory=list)
    custom_rules: list[CustomRuleSpec] = Field(default_factory=list)
    detectors: dict[str, bool] = Field(default_factory=dict)


class BundleError(ValueError):
    """The file is not a workspace bundle this version can read."""


# --- export ----------------------------------------------------------------------


def _body(doc: PolicyDocument) -> dict[str, Any]:
    """A policy as it is written in the file: no mode (the entry carries it), no defaults."""
    return doc.model_dump(mode="json", exclude={"mode", "key"}, exclude_defaults=True)


def _live(session: Session) -> dict[str, tuple[PolicyEntry, PolicyDocument]]:
    out: dict[str, tuple[PolicyEntry, PolicyDocument]] = {}
    for policy in session.scalars(select(Policy).order_by(Policy.key)):
        binding, version = current_binding(session, policy.id)
        if binding is None or version is None:
            continue
        doc = load_version_document(version)
        entry = PolicyEntry(
            key=policy.key,
            mode=binding.mode,
            level=binding.level or "org",
            scope=binding.scope_id or "*",
            compose=binding.compose or "extend",
            policy=_body(doc),
        )
        out[policy.key] = (entry, doc)
    return out


def export_bundle(session: Session) -> Bundle:
    return Bundle(
        policies=[entry for entry, _doc in _live(session).values()],
        custom_rules=[spec_of(row) for row in list_rules(session)],
        detectors=dict(sorted(overrides(session).items())),
    )


def dump(bundle: Bundle) -> str:
    data = bundle.model_dump(mode="json", exclude_defaults=False)
    data["custom_rules"] = [
        r.model_dump(mode="json", exclude_defaults=True) | {"key": r.key, "name": r.name}
        for r in bundle.custom_rules
    ]
    header = (
        "# AgentFox workspace. Apply with `agentfox policy apply <file>` or Policies → Code.\n"
        "# Anything left out of this file is left alone, never removed.\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def parse(text: str) -> Bundle:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BundleError(f"not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != KIND:
        raise BundleError(f"not an AgentFox workspace file (expected `kind: {KIND}`)")
    if data.get("version", FORMAT_VERSION) > FORMAT_VERSION:
        raise BundleError(f"written by a newer AgentFox (format {data['version']})")
    try:
        bundle = Bundle.model_validate(data)
        for entry in bundle.policies:
            PolicyDocument.model_validate({**entry.policy, "key": entry.key})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise BundleError(f"{where}: {first['msg']}") from exc
    return bundle


# --- plan ------------------------------------------------------------------------


Change = Literal["new", "changed", "mode", "unchanged", "not_in_file"]


@dataclass
class Item:
    kind: Literal["policy", "custom_rule", "detector"]
    key: str
    change: Change
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "change": self.change, "detail": self.detail}


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)

    @property
    def changes(self) -> list[Item]:
        return [i for i in self.items if i.change in ("new", "changed", "mode")]

    @property
    def enforces(self) -> list[str]:
        """Policies this plan would move to enforce."""
        return [i.key for i in self.items if i.kind == "policy" and "→ enforce" in i.detail]

    def to_json(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.change] = counts.get(item.change, 0) + 1
        return {
            "items": [i.to_json() for i in self.items],
            "counts": counts,
            "enforces": self.enforces,
        }


def _doc_of(entry: PolicyEntry) -> PolicyDocument:
    return PolicyDocument.model_validate({**entry.policy, "key": entry.key, "mode": entry.mode})


def plan(session: Session, bundle: Bundle) -> Plan:
    out = Plan()
    live = _live(session)
    named = set()
    for entry in bundle.policies:
        named.add(entry.key)
        current = live.get(entry.key)
        if current is None:
            out.items.append(
                Item("policy", entry.key, "new", f"{entry.mode}, {entry.level}:{entry.scope}")
            )
            continue
        cur_entry, cur_doc = current
        body_changed = _body(_doc_of(entry)) != _body(cur_doc)
        mode_changed = entry.mode != cur_entry.mode
        detail = f"{cur_entry.mode} → {entry.mode}" if mode_changed else ""
        if (entry.level, entry.scope, entry.compose) != (
            cur_entry.level,
            cur_entry.scope,
            cur_entry.compose,
        ):
            detail = ", ".join(
                filter(None, [detail, "placement kept (change it in the dashboard)"])
            )
        change: Change = "changed" if body_changed else "mode" if mode_changed else "unchanged"
        out.items.append(Item("policy", entry.key, change, detail))
    out.items += [
        Item("policy", key, "not_in_file", "left alone") for key in live if key not in named
    ]

    rules = {row.key: spec_of(row) for row in list_rules(session)}
    for spec in bundle.custom_rules:
        current = rules.get(spec.key)
        change = "new" if current is None else "unchanged" if current == spec else "changed"
        out.items.append(Item("custom_rule", spec.key, change, spec.name))
    named_rules = {s.key for s in bundle.custom_rules}
    out.items += [
        Item("custom_rule", k, "not_in_file", "left alone") for k in rules if k not in named_rules
    ]

    switches = overrides(session)
    for key, on in bundle.detectors.items():
        change = (
            "unchanged" if switches.get(key) == on else "new" if key not in switches else "changed"
        )
        out.items.append(Item("detector", key, change, "on" if on else "off"))
    return out


# --- apply -----------------------------------------------------------------------


@dataclass
class Applied:
    plan: Plan
    simulations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {**self.plan.to_json(), "simulations": self.simulations}


def apply(session: Session, bundle: Bundle, *, actor: str, reason: str = "") -> Applied:
    """Make the workspace match ``bundle``, leaving alone everything it omits."""
    the_plan = plan(session, bundle)
    changed = {(i.kind, i.key) for i in the_plan.changes}
    result = Applied(the_plan)
    why = reason or "applied from a workspace file"
    operator_log.record(
        session,
        "operator.workspace.applied",
        actor=actor,
        reason=why,
        subject_type="workspace",
        subject_id="*",
        after=the_plan.to_json(),
    )

    # Custom rules first: the `custom` policy in the file then carries their tuning.
    specs = [s for s in bundle.custom_rules if ("custom_rule", s.key) in changed]
    if specs:
        save_rules(session, [(s, RuleSeed()) for s in specs], actor=actor, reason=why)

    for key, on in bundle.detectors.items():
        if ("detector", key) in changed:
            set_enabled(session, key, on, actor=actor, reason=why)

    for entry in bundle.policies:
        if ("policy", entry.key) not in changed:
            continue
        doc = _doc_of(entry)
        published = publish_in_current_mode(
            session,
            doc,
            actor=actor,
            notes=why,
            level=entry.level,
            scope_id=entry.scope,
            compose=entry.compose,
        )
        if published.mode == entry.mode:
            continue
        if entry.mode == "enforce":
            since = dt.datetime.now(dt.UTC) - dt.timedelta(days=7)
            diff = simulate(session, doc, since=since)
            record_simulation(session, doc, diff, run_by=actor, scope={"source": why})
            result.simulations[entry.key] = diff.to_json()
        set_mode(session, entry.key, entry.mode, version=published.version)
    return result
