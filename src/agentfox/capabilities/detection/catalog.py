"""What each detector catches, and where it comes from — for the Checks screen.

The detector registry knows how to run a check; it does not say what kind of problem
the check is for, or whether it is code that ships with AgentFox, an open-source
model someone has to download, an LLM judge that needs a provider, or something
the workspace brought itself. A customer choosing what runs asks exactly those
questions, so they are answered once, here, rather than guessed from a key in
TypeScript.

Licences are named only for the model ids this project ships as defaults and has
checked. A model an operator configured instead is reported with no licence rather
than an invented one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agentfox.capabilities.detection.models import models_for

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from agentfox.platform.policy import Rule

#: Display order of the groups, and their names.
GROUPS: tuple[tuple[str, str], ...] = (
    ("attacks", "Prompt attacks"),
    ("data", "Personal data & secrets"),
    ("content", "Harmful content"),
    ("grounding", "Grounding & wrong answers"),
    ("yours", "Your own"),
)

#: Detector key prefix -> group, most specific first.
_GROUP_BY_KEY: tuple[tuple[str, str], ...] = (
    ("custom.", "yours"),
    ("injection.", "attacks"),
    ("code.", "attacks"),
    ("rails.nemo", "attacks"),
    ("pii.", "data"),
    ("secrets.", "data"),
    ("safety.", "content"),
    ("grounding.", "grounding"),
    ("schema.", "grounding"),
    ("rails.guardrails_ai", "grounding"),
)

#: Entity prefix -> group, for detectors that report one (the Hub validators).
_GROUP_BY_ENTITY = {
    "INJECTION": "attacks",
    "DISCLOSURE": "attacks",
    "CODE": "attacks",
    "ACTION": "attacks",
    "PII": "data",
    "SECRET": "data",
    "SAFETY": "content",
    "BRAND": "content",
    "TOPIC": "content",
    "QUALITY": "grounding",
    "FORMAT": "grounding",
    "SCHEMA": "grounding",
    "GROUNDING": "grounding",
}

#: The default model ids this project ships, and their licences.
MODEL_LICENSES = {
    "leolee99/PIGuard": "MIT",
    "protectai/deberta-v3-base-prompt-injection-v2": "Apache-2.0",
    "sentence-transformers/all-MiniLM-L6-v2": "Apache-2.0",
    "cross-encoder/nli-deberta-v3-small": "Apache-2.0",
    "ibm-granite/granite-guardian-3.0-2b": "Apache-2.0",
    "meta-llama/Llama-Guard-3-8B": "Llama 3.1 Community (restricted)",
}

#: Licences of the open-source packages wrapped without a model download.
_PACKAGE_LICENSES = {
    "pii.presidio": "MIT",
    "rails.nemo": "Apache-2.0",
    "rails.guardrails_ai": "Apache-2.0",
}

#: Detectors decided by a judgment tier (JEV or an LLM), not by code on this host.
JUDGE_DETECTORS = frozenset({"injection.judgment", "pii.judgment"})

#: Where a detector runs, in the three words a customer uses.
_WHERE = {
    "input": "input",
    "output": "output",
    "tool_args": "tools",
    "tool_result": "tools",
    "tool_call": "tools",
    "mcp": "tools",
    "retrieved": "context",
    "memory_write": "context",
    "agent_message": "context",
}


#: Detector key prefix -> the kind of finding it reports, for detectors that don't
#: state one (`spec.entity_type`). The kind is the first part of the entity type a
#: detection carries (`INJECTION.JAILBREAK` -> `INJECTION`), which is what a policy
#: rule matches on (`detection.entity_prefix`): it is how a check feeds a rule.
_FINDS_BY_KEY = (
    ("injection.", "INJECTION"),
    ("unicode.", "INJECTION"),
    ("pii.", "PII"),
    ("secrets.", "SECRET"),
    ("safety.", "SAFETY"),
    ("schema.", "SCHEMA"),
    ("rails.guardrails_ai", "SCHEMA"),
    ("rails.nemo", "RAILS"),
    ("grounding.", "GROUNDING"),
    ("code.", "CODE"),
    ("custom.", "CUSTOM"),
)


def finds_of(detector: Any) -> str:
    """The kind of finding a detector reports (`INJECTION`, `PII`, …); empty if unknown."""
    spec = getattr(detector, "spec", None)
    entity = str(getattr(spec, "entity_type", "") or "")
    if entity:
        return entity.split(".")[0]
    key = str(getattr(detector, "key", ""))
    for prefix, kind in _FINDS_BY_KEY:
        if key.startswith(prefix):
            return kind
    return ""


def group_of(detector: Any) -> str:
    key = str(getattr(detector, "key", ""))
    spec = getattr(detector, "spec", None)
    entity = str(getattr(spec, "entity_type", "") or "")
    if entity:
        return _GROUP_BY_ENTITY.get(entity.split(".")[0], "content")
    for prefix, group in _GROUP_BY_KEY:
        if key.startswith(prefix):
            return group
    return "content"


def source_of(detector: Any) -> str:
    """builtin | open_source | llm_judge | yours."""
    key = str(getattr(detector, "key", ""))
    if key.startswith("custom."):
        return "yours"
    if key in JUDGE_DETECTORS:
        return "llm_judge"
    validator = getattr(detector, "validator", None)
    if validator is not None:
        return {"judge": "llm_judge", "model": "open_source"}.get(validator.kind, "builtin")
    if models_for(detector) or key in _PACKAGE_LICENSES or key.startswith("rails."):
        return "open_source"
    return "builtin"


def where(surfaces: tuple[str, ...] | list[str]) -> list[str]:
    """input / output / tools / context, in that order, for the surfaces given."""
    found = {_WHERE.get(s, "context") for s in surfaces}
    return [w for w in ("input", "output", "tools", "context") if w in found]


def describe(detector: Any, feeds: Iterable[Feed] | None = None) -> dict[str, Any]:
    """The Checks-screen facts for one detector.

    ``feeds`` (from :func:`feeds_for`) lets a check the workspace fills in itself say
    what it actually reports: ``custom.models`` reports whatever prefixes its
    registered models were given, not just ``CUSTOM``.
    """
    key = str(getattr(detector, "key", ""))
    validator = getattr(detector, "validator", None)
    # A ported validator states its weights' licence itself (checked against each
    # model card when it was ported); our own table covers the rest.
    weights = getattr(validator, "model_license", "") or None
    models = [{"id": m, "license": MODEL_LICENSES.get(m) or weights} for m in models_for(detector)]
    if models and models[0]["license"]:
        license_ = models[0]["license"]
    elif validator is not None:
        license_ = validator.license
    else:
        license_ = _PACKAGE_LICENSES.get(key)
    return {
        **(
            {"upstream": validator.upstream, "label": validator.label}
            if validator is not None
            else {}
        ),
        "group": group_of(detector),
        "finds": finds_of(detector),
        # Every kind it can report. One for a shipped check; for `custom.models`, the
        # prefixes of the models registered (a PII model makes it a PII check too).
        "finds_all": finds_all_of(detector, feeds),
        "source": source_of(detector),
        "where": where(tuple(getattr(detector, "surfaces", ()) or ())),
        "models": models,
        "license": license_,
    }


# --- which checks can fire a rule ----------------------------------------------------

#: What a detection rule with neither `entity` nor `entity_prefix` looks for: any
#: detection at all (`engine._detection_matches` skips both tests), not nothing.
ANY = "any"

#: The detectors that match a workspace rule of each kind (`custom.py`).
_CUSTOM_RULE_DETECTORS: dict[str, tuple[str, ...]] = {
    "terms": ("custom.lists",),
    "patterns": ("custom.lists",),
    "condition": ("custom.lists",),
    "topic": ("custom.lists", "custom.topics"),
    "validator": ("custom.validators",),
}
_FILLED_BY_WORKSPACE = ("custom.models", *{k for v in _CUSTOM_RULE_DETECTORS.values() for k in v})


@dataclass(frozen=True)
class Feed:
    """One way a check can report a finding: which detector, what, and where.

    ``finds`` is a kind (``PII``) for a shipped check, whose exact entity types are not
    known ahead of time, or an exact entity (``CUSTOM.ACME``) for a workspace's own
    rule or model, whose entity is fixed by its key.
    """

    detector: str
    finds: str
    surfaces: tuple[str, ...]
    #: ``rule:<key>`` / ``model:<key>`` for the workspace's own; empty for a shipped check.
    via: str = ""

    @property
    def kind(self) -> str:
        return self.finds.split(".")[0]


def workspace_feeds(session: Session) -> list[Feed]:
    """What the workspace's own rules and models make its custom checks report.

    Disabled rows report nothing. A row that no longer validates is skipped.
    """
    from sqlalchemy import select

    from agentfox.capabilities.detection import custom_models, custom_store
    from agentfox.capabilities.detection.custom import DEFAULT_SURFACES, entity_for
    from agentfox.core.models import CustomModel, CustomRule

    out: list[Feed] = []
    for row in session.scalars(select(CustomModel).where(CustomModel.enabled.is_(True))):
        try:
            spec = custom_models.spec_of(row)
        except ValueError:
            continue
        finds = entity_for(spec.key) if spec.entity_prefix == "CUSTOM" else spec.entity_prefix
        out.append(Feed("custom.models", finds, tuple(spec.surfaces), f"model:{spec.key}"))
    for row in session.scalars(select(CustomRule).where(CustomRule.enabled.is_(True))):
        detectors = _CUSTOM_RULE_DETECTORS.get(row.kind)
        if not detectors:
            continue  # a sequence is a check on the run, not a detection
        try:
            spec = custom_store.spec_of(row)
        except ValueError:
            continue
        surfaces = tuple(spec.surfaces or DEFAULT_SURFACES)
        out.extend(Feed(d, entity_for(spec.key), surfaces, f"rule:{spec.key}") for d in detectors)
    return out


def feeds_for(detectors: Mapping[str, Any], session: Session | None = None) -> list[Feed]:
    """Every way the given detectors can report a finding.

    With a session, the custom checks are spelled out by what the workspace
    registered (one feed per model or rule, with its own entity and surfaces);
    without one, each reports its default kind everywhere it runs.
    """
    out: list[Feed] = []
    for key, d in detectors.items():
        if session is not None and key in _FILLED_BY_WORKSPACE:
            continue
        out.append(Feed(key, finds_of(d), tuple(getattr(d, "surfaces", ()) or ())))
    if session is not None:
        out.extend(f for f in workspace_feeds(session) if f.detector in detectors)
    return out


def finds_all_of(detector: Any, feeds: Iterable[Feed] | None = None) -> list[str]:
    """Every kind a detector can report, from its feeds when given."""
    key = str(getattr(detector, "key", ""))
    if feeds is not None and key in _FILLED_BY_WORKSPACE:
        kinds = list(dict.fromkeys(f.kind for f in feeds if f.detector == key))
        if kinds:
            return kinds
    kind = finds_of(detector)
    return [kind] if kind else []


def rule_finds(rule: Rule) -> str:
    """What a rule looks for: an entity or prefix, ``any``, or empty (not about content)."""
    detection = rule.when.detection
    if detection is None:
        return ""
    return detection.entity or detection.entity_prefix or ANY


def rule_surfaces(rule: Rule) -> list[str] | None:
    """The surfaces a rule is limited to; None when it names none (it applies on every one)."""
    return list(rule.when.surface) if rule.when.surface else None


def can_fire(rule: Rule, feed: Feed) -> bool:
    """Whether this feed can produce a detection this rule matches, where the rule looks.

    Two things must hold: the finding is what the rule looks for (by kind for a shipped
    check, exactly for a workspace rule or model), and the check runs on a surface the
    rule is limited to.
    """
    detection = rule.when.detection
    if detection is None:
        return False
    surfaces = rule.when.surface
    if surfaces and not set(surfaces) & set(feed.surfaces):
        return False
    if detection.entity:
        want, exact = detection.entity, True
    elif detection.entity_prefix:
        want, exact = detection.entity_prefix, False
    else:
        return True
    if "." in feed.finds:  # an exact entity: compare as the policy engine will
        return feed.finds == want if exact else feed.finds.startswith(want)
    # A kind: the check reports something under it; which exact one isn't known.
    return want.split(".")[0] == feed.kind


def checks_for_rule(rule: Rule, feeds: Iterable[Feed]) -> list[str]:
    """The detectors that can fire a rule: what they find, where it looks. Sorted."""
    return sorted({f.detector for f in feeds if can_fire(rule, f)})
