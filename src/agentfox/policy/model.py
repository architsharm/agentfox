"""Declarative policy model (P6-1).

The catalog's advice is to put OPA/Rego underneath rather than hand-roll an engine —
and we do (``policy/opa.py``). But Rego is not a language a CISO or a GRC lead will
read, review or sign off, and *"write once, enforce at runtime **and** report"* is
the whole point of the pillar. So the authored artefact is this declarative YAML,
which compiles to either evaluator.

A policy version is immutable (X-4). Every ``Decision`` records the exact version in
force, which is what stops "that rule was always on" retro-fitting (Appendix E.1.5).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from agentfox.core.vocab import COMPARATORS

Effect = Literal["allow", "redact", "mask", "tokenize", "abstain", "block", "escalate"]


class DetectionCondition(BaseModel):
    entity: str | None = None
    entity_prefix: str | None = None
    min_score: float = 0.5
    min_count: int = 1


class ArgumentCondition(BaseModel):
    path: str
    op: str = "eq"
    value: Any = None

    @field_validator("op")
    @classmethod
    def _known_op(cls, v: str) -> str:
        if v not in COMPARATORS:
            raise ValueError(f"unknown operator '{v}'; expected one of {sorted(COMPARATORS)}")
        return v


class Condition(BaseModel):
    """All present fields must match (AND). Absent fields are ignored."""

    surface: list[str] | None = None
    environment: list[str] | None = None
    agent: str | None = None  # glob on slug
    risk_tier: list[str] | None = None
    tool: str | None = None  # glob on tool key
    tool_impact: list[str] | None = None
    #: False when the call names a tool the registry has never heard of. Either
    #: the model invented it, or it is real and nobody declared it; both are
    #: worth a human, and neither is the same question as "may this agent use
    #: this tool", which is `capability`.
    tool_known: bool | None = None
    detection: DetectionCondition | None = None
    argument: ArgumentCondition | None = None
    #: Fires when argument provenance is more dangerous than this level.
    taint_exceeds: str | None = None
    capability: str | None = None  # denied | requires_approval | granted
    #: P9 — the *semantics of the generated artefact*, not the tool it was passed to.
    #: An agent with a legitimate `db.query` capability can still pass `DROP TABLE`.
    action_operation: list[str] | None = None  # read | write | destructive | admin | unknown
    #: Fires when the estimated blast radius is at or above this level.
    blast_radius_at_least: str | None = None  # none | bounded | unknown | unbounded | catastrophic
    action_reversible: bool | None = None
    action_risk: str | None = None  # glob on risk code, e.g. "sql.*"
    budget_exceeded: bool | None = None
    loop_detected: bool | None = None
    intent_declared: bool | None = None
    detector_degraded: bool | None = None
    #: Conditions that must hold before the agent may declare itself finished.
    #: Fires on the `completion` surface when any named condition is missing
    #: from, or false in, what the caller reported. This is the one rule shape
    #: that is not about whether an action is safe — it is about whether the
    #: agent is allowed to stop, which is the question nobody was asking.
    completion_requires: list[str] | None = None
    #: Escape hatch for conditions the schema does not model yet.
    expr: str | None = None


class Rule(BaseModel):
    id: str
    description: str = ""
    when: Condition = Field(default_factory=Condition)
    effect: Effect = "block"
    reason: str = ""
    #: Controls this rule provides evidence for (feeds P6-4 continuous monitoring).
    controls: list[str] = Field(default_factory=list)
    severity: str = "medium"
    enabled: bool = True
    #: Redaction style when effect is redact/mask/tokenize.
    redaction: str = "mask"
    #: P12-2 — may a narrower level weaken this rule? Loosening is a grant, not a
    #: right, so the default is no. Tightening never needs permission.
    overridable: bool = False


#: Rules a pack may not ship without, by pack key.
#:
#: `control_plane.tamper` blocks the commands that would switch AgentFox's own
#: enforcement off — putting a policy back into observe mode, changing an
#: agent's grants, rolling the schema back, writing to the config or the state
#: directory. Every other rule in `tool-containment.yaml` is downstream of it:
#: an agent that can pause enforcement can switch off all of them, so a pack
#: that has quietly dropped this one still reports as enforcing while enforcing
#: nothing that matters.
#:
#: Checked in the model rather than at load, and raised rather than warned, for
#: the reason `availability.py` gives for NEVER_OPEN: a setting that can be
#: changed under pressure at three in the morning is not a guarantee. A
#: deployment that genuinely does not want this rule removes the whole pack,
#: which is visible in `agentfox policy list`; silently disabling one rule
#: inside it is not.
PROTECTED_RULES: dict[str, tuple[str, ...]] = {
    "tool-containment": ("control_plane.tamper",),
}


class ProtectedRuleMissing(ValueError):
    """A pack was loaded without a rule that pack is not allowed to be without.

    Raised inside a pydantic validator, so callers see it wrapped in a
    `ValidationError` rather than as this type — the message survives, the class
    does not. It is a named class anyway because the message is the contract and
    a bare `ValueError` in the validator would read, to the next person, as an
    ordinary field problem rather than a deliberate refusal.
    """


class PolicyDocument(BaseModel):
    key: str
    name: str = ""
    description: str = ""
    version: int = 1
    #: observe never blocks; it records what *would* have happened (PRD R3).
    mode: Literal["observe", "enforce"] = "observe"
    default_effect: Effect = "allow"
    fail_mode: Literal["open", "closed"] = "open"
    scope: dict[str, Any] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _protected_rules_present(self) -> PolicyDocument:
        required = PROTECTED_RULES.get(self.key)
        if not required:
            return self
        by_id = {rule.id: rule for rule in self.rules}
        for rule_id in required:
            rule = by_id.get(rule_id)
            if rule is None:
                raise ProtectedRuleMissing(
                    f"policy pack '{self.key}' is missing '{rule_id}', which it may not "
                    "ship without: that rule is what stops a governed agent switching "
                    "off every other rule in the pack. Remove the whole pack if you do "
                    "not want it — that is visible; dropping this one rule is not."
                )
            if not rule.enabled:
                raise ProtectedRuleMissing(
                    f"'{rule_id}' in policy pack '{self.key}' cannot be disabled: it is "
                    "what stops a governed agent switching off every other rule in the "
                    "pack, including the ones still marked enabled."
                )
        return self

    @classmethod
    def from_yaml(cls, body: str) -> PolicyDocument:
        return cls.model_validate(yaml.safe_load(body) or {})

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(exclude_none=True), sort_keys=False)

    def matches_scope(self, agent_slug: str | None, environment: str | None) -> bool:
        agents = self.scope.get("agents")
        if agents and agent_slug:
            if not any(fnmatch.fnmatch(agent_slug, pattern) for pattern in agents):
                return False
        envs = self.scope.get("environments")
        if envs and environment and environment not in envs:
            return False
        return True


# ---------------------------------------------------------------------------
# Evaluation input / output
# ---------------------------------------------------------------------------


@dataclass
class PolicyInput:
    """Everything the engine reasons over.

    Note what is here that a model-era filter does not have: ``tool_impact``,
    ``taint`` provenance per argument, ``prior_tools``, and the capability decision.
    That is the difference between "is this string bad" and "should this action
    happen" (P3-4).
    """

    agent_slug: str | None = None
    risk_tier: str = "limited"
    environment: str = "production"
    surface: str = "input"
    tool_key: str | None = None
    tool_impact: str = "read"
    #: True when no tool was named (the question does not arise) or the tool is
    #: in the registry.
    tool_known: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)
    intent: str | None = None
    detections: list[dict[str, Any]] = field(default_factory=list)
    taint: dict[str, Any] = field(default_factory=dict)
    capability: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    #: P9 — the action-assurance summary for this call, empty when nothing executable
    #: was found in the arguments.
    action: dict[str, Any] = field(default_factory=dict)
    prior_tools: list[str] = field(default_factory=list)
    detector_degraded: bool = False
    #: Observable facts at the moment the agent claims to be done, e.g.
    #: {"committed": True, "ci_green": False}. Supplied by the caller, who is
    #: the only one who can see them; which of them are *required* is the
    #: policy's business, not the caller's.
    completion: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": self.agent_slug,
            "risk_tier": self.risk_tier,
            "environment": self.environment,
            "surface": self.surface,
            "tool": self.tool_key,
            "tool_impact": self.tool_impact,
            "arguments": self.arguments,
            "intent": self.intent,
            "detections": self.detections,
            "taint": self.taint,
            "capability": self.capability,
            "budget": self.budget,
            "prior_tools": self.prior_tools,
            "detector_degraded": self.detector_degraded,
        }


@dataclass
class FiredRule:
    rule_id: str
    effect: str
    reason: str
    severity: str = "medium"
    controls: list[str] = field(default_factory=list)
    redaction: str = "mask"
    #: The mode of the pack this rule was evaluated under, so a reader of one entry
    #: can tell whether its effect was applied or only recorded. A decision merges
    #: several packs and they need not share a mode, which is exactly how a sandbox
    #: bound in observe ended up with a decision labelled `enforce`.
    mode: str = "observe"
    #: Exact entity types this rule's detection condition names, and entity families
    #: it names by prefix. Both empty for a rule that does not test detections at all
    #: — a tool, capability or taint rule.
    #:
    #: Kept as two fields rather than one list because the engine matches them by
    #: different operations (equality and `startswith`), and collapsing them would
    #: mean the explanation re-deriving which is which from a naming convention the
    #: policy files do not follow: they write `entity_prefix: INJECTION`, not
    #: `INJECTION.`.
    #:
    #: Carried at all because the explanation has to say *which* match decided the
    #: outcome, and without this it could only guess by score. On an injection
    #: payload that guess was wrong in the most damaging possible way: the attacker's
    #: own email address scored 0.90 against the injection's 0.85, so
    #: `injection.direct` was reported as having fired on `PII.EMAIL`. A reader
    #: concludes the product does not understand what it caught, and on that evidence
    #: they are right.
    entities: list[str] = field(default_factory=list)
    entity_prefixes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "effect": self.effect,
            "reason": self.reason,
            "severity": self.severity,
            "controls": self.controls,
            "mode": self.mode,
            "entities": self.entities,
            "entity_prefixes": self.entity_prefixes,
        }


@dataclass
class PolicyDecision:
    verdict: str = "allow"
    rules_fired: list[FiredRule] = field(default_factory=list)
    policy_key: str | None = None
    policy_version: int | None = None
    mode: str = "observe"
    #: What the verdict *would* have been in enforce mode. In observe mode the
    #: caller is not blocked, but this is what gets reported and simulated against.
    effective_verdict: str = "allow"
    engine: str = "native"

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def redactions(self) -> list[FiredRule]:
        return [r for r in self.rules_fired if r.effect in ("redact", "mask", "tokenize")]

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "effective_verdict": self.effective_verdict,
            "mode": self.mode,
            "engine": self.engine,
            "policy": self.policy_key,
            "policy_version": self.policy_version,
            "rules_fired": [r.to_json() for r in self.rules_fired],
        }
