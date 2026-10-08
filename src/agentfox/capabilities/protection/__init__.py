"""Protecting one agent: the protections a customer picks, at the sensitivity they pick.

A customer setting up an agent thinks in protections — "stop prompt attacks", "keep
personal data out of replies" — and how strict each should be. Underneath, each is
one or more rules from a shipped pack. This module is the translation, and the one
place that writes an agent's own policy layer.

**The agent layer.** Each agent's choices are a policy pack ``agent.<slug>`` bound at
the *agent* level of the hierarchy (`platform/policy/hierarchy.py`), holding copies of
the chosen pack rules at the chosen threshold, with the agent's end-user message. It
composes ``extend``, which gives the property that matters for free: a narrower level
can only add caution. If the workspace already runs a rule for every agent, this
agent's copy can make it *more* sensitive; it can never make it less, because the
broader rule stays in force beside it. `state` reports that floor so the screen can
show it instead of offering a choice that would do nothing.

New agent layers start watching; a change to an enforcing layer is simulated against
that agent's recent traffic first (`platform/policy/publish.py`).

Words, topics and the allowed-topic list are custom rules scoped to the agent
(`capabilities/detection/custom_store.py`); the route composes the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from agentfox.platform.ledger import operator_log
from agentfox.platform.packs.loader import load_packs
from agentfox.platform.policy import PolicyDocument, Rule, effective_for
from agentfox.platform.policy.publish import Published, current_mode, publish_in_current_mode

#: Sensitivity as a customer says it, and the detection threshold it means. Lower
#: thresholds catch more. The dashboard reads these from the API rather than
#: keeping its own copy.
LEVELS: dict[str, float] = {"low": 0.9, "medium": 0.7, "high": 0.5}
OFF = "off"
ON = "on"  # a protection with no detection threshold is simply on or off


@dataclass(frozen=True)
class Protection:
    key: str
    title: str
    pack: str
    rules: tuple[str, ...]
    #: A detector this protection cannot work without (switched on with it).
    needs: str = ""
    #: A model-backed detector that makes it more accurate, offered as an upgrade.
    better: str = ""
    default: str = "medium"


CATALOGUE: tuple[Protection, ...] = (
    Protection(
        "attacks",
        "Prompt attacks",
        "baseline",
        ("injection.direct", "injection.indirect"),
        better="injection.classifier",
    ),
    Protection("personal_data", "Personal data", "baseline", ("pii.outbound_redact",)),
    Protection("secrets", "Secrets & keys", "baseline", ("secrets.block",), default="high"),
    Protection("harmful", "Harmful content", "baseline", ("safety.harm",)),
    Protection(
        "off_task", "Off-task actions", "agent-integrity", ("intent.misaligned",), default=OFF
    ),
    Protection(
        "unsupported",
        "Unsupported answers",
        "agent-integrity",
        ("grounding.unsupported",),
        needs="grounding.nli",
        default=OFF,
    ),
    Protection(
        "insecure_code", "Insecure code", "agent-integrity", ("code.insecure",), default=OFF
    ),
)

BY_KEY = {p.key: p for p in CATALOGUE}


def layer_key(slug: str) -> str:
    return f"agent.{slug}"


def _template_rules() -> dict[str, Rule]:
    """The shipped rules the catalogue copies, by id."""
    wanted = {rid for p in CATALOGUE for rid in p.rules}
    packs = {p.pack for p in CATALOGUE}
    out: dict[str, Rule] = {}
    for pack in load_packs():
        if pack.id not in packs:
            continue
        for path in pack.files("policies"):
            for rule in PolicyDocument.from_yaml(path.read_text()).rules:
                if rule.id in wanted:
                    out.setdefault(rule.id, rule)
    return out


def _graded(rule: Rule) -> bool:
    return rule.when.detection is not None


def level_of(threshold: float | None) -> str:
    """The named level nearest a threshold."""
    if threshold is None:
        return ON
    return min(LEVELS, key=lambda name: abs(LEVELS[name] - threshold))


# --- reading ---------------------------------------------------------------------


@dataclass
class ProtectionState:
    protection: Protection
    #: What this agent's own layer sets: off, on, or a level.
    level: str
    #: What already applies to every agent (from broader layers), or None.
    inherited: str | None
    #: Whether the inherited rule is enforcing or only watching.
    inherited_mode: str | None
    graded: bool
    available: bool

    def to_json(self) -> dict[str, Any]:
        p = self.protection
        return {
            "key": p.key,
            "title": p.title,
            "level": self.level,
            "inherited": self.inherited,
            "inherited_mode": self.inherited_mode,
            "graded": self.graded,
            "available": self.available,
            "needs": p.needs or None,
            "better": p.better or None,
            "default": p.default,
        }


@dataclass
class AgentProtection:
    slug: str
    protections: list[ProtectionState]
    message: str
    mode: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": self.slug,
            "policy": layer_key(self.slug),
            "mode": self.mode,
            "message": self.message,
            "levels": LEVELS,
            "protections": [p.to_json() for p in self.protections],
        }


def state(session: Session, slug: str) -> AgentProtection:
    templates = _template_rules()
    effective = effective_for(session, slug)
    own_key = layer_key(slug)
    own: dict[str, Rule] = {}
    broader: dict[str, tuple[float | None, str]] = {}
    for layer in effective.applicable:
        for rule in effective.rules_in_force(layer):
            if layer.document.key == own_key:
                own[rule.id] = rule
                continue
            if not rule.enabled:
                continue
            threshold = rule.when.detection.min_score if rule.when.detection else None
            seen = broader.get(rule.id)
            # The most sensitive broader copy is the floor; an enforcing one wins ties.
            if (
                seen is None
                or (threshold or 1) < (seen[0] or 1)
                or (threshold == seen[0] and layer.document.mode == "enforce")
            ):
                broader[rule.id] = (threshold, layer.document.mode)

    states: list[ProtectionState] = []
    message = ""
    for p in CATALOGUE:
        template = templates.get(p.rules[0])
        graded = bool(template and _graded(template))
        mine = [own[r] for r in p.rules if r in own and own[r].enabled]
        if mine:
            first = mine[0]
            level = level_of(first.when.detection.min_score) if first.when.detection else ON
            message = message or first.message
        else:
            level = OFF
        inherited = next((broader[r] for r in p.rules if r in broader), None)
        states.append(
            ProtectionState(
                protection=p,
                level=level,
                inherited=level_of(inherited[0]) if inherited else None,
                inherited_mode=inherited[1] if inherited else None,
                graded=graded,
                available=template is not None,
            )
        )
    return AgentProtection(slug, states, message, current_mode(session, own_key))


# --- writing ---------------------------------------------------------------------


def build_layer(slug: str, choices: dict[str, str], message: str = "") -> PolicyDocument:
    """The agent layer for these choices: ``{protection key: off | on | low | medium | high}``."""
    templates = _template_rules()
    rules: list[Rule] = []
    for key, level in choices.items():
        p = BY_KEY.get(key)
        if p is None:
            raise ValueError(f"unknown protection '{key}'")
        if level == OFF:
            continue
        for rid in p.rules:
            template = templates.get(rid)
            if template is None:
                raise ValueError(f"'{p.title}' needs the {p.pack} pack, which is not available")
            rule = template.model_copy(deep=True)
            if rule.when.detection is not None:
                if level not in LEVELS:
                    raise ValueError(f"'{p.title}' takes low, medium or high, not '{level}'")
                rule.when.detection.min_score = LEVELS[level]
            elif level != ON:
                raise ValueError(f"'{p.title}' is on or off, not '{level}'")
            rule.message = message
            rules.append(rule)
    return PolicyDocument(
        key=layer_key(slug),
        name=f"{slug} protection",
        description=f"Protections chosen for the agent '{slug}'.",
        rules=rules,
    )


def needed_detectors(choices: dict[str, str]) -> list[str]:
    return [BY_KEY[k].needs for k, v in choices.items() if v != OFF and BY_KEY[k].needs]


def save(
    session: Session, slug: str, choices: dict[str, str], message: str, *, actor: str
) -> Published:
    """Write the agent's layer, live in the mode it is already in (new layers watch).

    Switching a protection off removes this agent's copy of its rules, so this is
    recorded as an operator action with the before and after choices.
    """
    doc = build_layer(slug, choices, message)
    before = {p.protection.key: p.level for p in state(session, slug).protections}
    operator_log.record(
        session,
        "operator.agent_protection.saved",
        actor=actor,
        reason=f"protection for agent '{slug}' changed",
        subject_type="agent",
        subject_id=slug,
        before=before,
        after={**before, **choices},
    )
    return publish_in_current_mode(
        session,
        doc,
        actor=actor,
        notes=f"protection for {slug}",
        level="agent",
        scope_id=slug,
        compose="extend",
        agent_slug=slug,
    )
