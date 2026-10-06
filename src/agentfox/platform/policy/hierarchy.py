"""Hierarchical policy composition.

**Evidence.** Two of eleven senior engineers surveyed hand-built this. Derrick
(Murphy USA, ex-Apple/Cigna/Ally) quantified it: *"hierarchical policy framework
(company → team → user) with inheritance/override rules, context isolation, and tool
permissions... reducing policy misconfigurations by **87%**."*

That number is the whole argument. Flat policy does not merely scale badly — it
*causes incidents*, because with forty agents across eight teams nobody can hold the
interaction of a dozen overlapping documents in their head.

Four levels, narrowest wins on ties:

    org  →  team  →  agent  →  user

Three composition modes, and the asymmetry between them is the safety property:

``extend``    add rules; the parent's still apply. The default.
``restrict``  tighten. **Always permitted** — a child may make itself safer without
              asking, because nobody needs authorisation to be more careful.
``override``  loosen. Permitted **only** where the parent marked the rule
              ``overridable: true``. Loosening is a grant, not a right.

The other half of the design is not the algorithm but the *explanation*:
:func:`resolve_effective` reports, for every rule in force, which level it came from
and what it overrode. Opacity is what makes flat policy dangerous, so a resolver that
produced a correct answer nobody could read would have missed the point.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

from agentfox.core.vocab import EFFECT_RANK, SURFACES
from agentfox.platform.policy.model import PolicyDocument, Rule
from agentfox.prove.compliance.risk import EU_CLASSES

#: Broadest to narrowest. Order is load-bearing: later levels win ties.
LEVELS = ("org", "team", "agent", "user")

MODES = ("extend", "restrict", "override")


def level_rank(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError:
        return -1


@dataclass
class PolicyLayer:
    """One policy document bound at one level of the hierarchy."""

    document: PolicyDocument
    level: str = "org"
    #: Which org / team / agent / user this layer applies to. ``*`` means all.
    scope_id: str = "*"
    mode: str = "extend"

    def applies_to(self, subject: dict[str, str]) -> bool:
        if self.level not in LEVELS:
            return False
        if self.scope_id == "*":
            return True
        return fnmatch.fnmatch(str(subject.get(self.level, "")), self.scope_id)


@dataclass
class ResolvedRule:
    """A rule in force, with the provenance that makes it explicable."""

    rule: Rule
    level: str
    scope_id: str
    mode: str
    overrides: list[str] = field(default_factory=list)
    #: Set when this rule replaced a weaker one from a broader level.
    loosened: bool = False
    #: The layer this rule came from. The runtime evaluates each rule under its own
    #: layer's binding (and so its own observe/enforce mode); `policy effective`
    #: only needs the level and scope above.
    layer: PolicyLayer | None = field(default=None, repr=False, compare=False)
    #: Broader rules this one tightened. They stay in force at runtime, each under
    #: its own layer's mode: a `restrict` may only ever add caution, so an org rule
    #: that a team tightened in an observe-mode layer is still enforced by the org.
    #: Under the lattice maximum the outcome is the tighter rule either way; keeping
    #: them is what stops a tightening from quietly demoting the broader rule's mode.
    #: Cleared by a granted loosening, which is the one way a rule leaves force.
    superseded: list[tuple[PolicyLayer, Rule]] = field(default_factory=list, repr=False)

    @property
    def enforcement(self) -> str:
        """observe | enforce — the mode of the binding this rule came from."""
        return self.layer.document.mode if self.layer is not None else "observe"

    def to_json(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule.id,
            "description": self.rule.description,
            "effect": self.rule.effect,
            "level": self.level,
            "scope": self.scope_id,
            "mode": self.mode,
            "enforcement": self.enforcement,
            "overrides": self.overrides,
            "loosened": self.loosened,
            "source": f"{self.level}:{self.scope_id}",
        }


@dataclass
class EffectivePolicy:
    """The composed policy, plus why each rule is in it."""

    rules: list[ResolvedRule] = field(default_factory=list)
    #: "enforce" when any applicable layer enforces. A summary of the deployment,
    #: not of any one rule: each layer keeps its own mode (`layer_modes`), and each
    #: rule is applied or only recorded according to its own layer's mode.
    mode: str = "observe"
    default_effect: str = "allow"
    layers: list[str] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    #: One entry per applicable layer: which policy, where it sits, and its mode.
    layer_modes: list[dict[str, str]] = field(default_factory=list)
    #: The applicable layers themselves, broadest first.
    applicable: list[PolicyLayer] = field(default_factory=list, repr=False)
    #: Bound versions left out because they no longer load (`store.load_version_document`).
    unloadable: list[dict[str, Any]] = field(default_factory=list)

    def rules_in_force(self, layer: PolicyLayer) -> list[Rule]:
        """The rules from ``layer`` that resolution kept, in the layer's own order.

        This is what the runtime evaluates for that layer: the rules that won
        resolution plus the broader rules they tightened (see
        :attr:`ResolvedRule.superseded`). A rule rejected as an illegal loosening,
        or replaced by a granted loosening, is not in force and is not returned.
        """
        kept: set[int] = set()
        for resolved in self.rules:
            if resolved.layer is layer:
                kept.add(id(resolved.rule))
            for source, rule in resolved.superseded:
                if source is layer:
                    kept.add(id(rule))
        return [rule for rule in layer.document.rules if id(rule) in kept]

    def document(self, key: str = "effective") -> PolicyDocument:
        """Collapse to a single document the existing engine can evaluate."""
        return PolicyDocument(
            key=key,
            name="Effective policy",
            mode=self.mode,
            default_effect=self.default_effect,  # type: ignore[arg-type]
            rules=[resolved.rule for resolved in self.rules],
        )

    def explain(self) -> dict[str, Any]:
        return {
            "layers": self.layers,
            "layer_modes": self.layer_modes,
            "mode": self.mode,
            "default_effect": self.default_effect,
            "rules": [r.to_json() for r in self.rules],
            "rejected": self.rejected,
            "unloadable_policies": self.unloadable,
        }


def resolve_effective(
    layers: list[PolicyLayer], subject: dict[str, str] | None = None
) -> EffectivePolicy:
    """Compose layers into the policy actually in force for ``subject``.

    ``subject`` is a mapping like ``{"org": "acme", "team": "finance",
    "agent": "payments-ops", "user": "priya@acme.com"}``. Layers that do not apply
    are skipped rather than merged, which is what gives context isolation:
    a team never sees another team's rules because they were never in scope.
    """
    subject = subject or {}
    applicable = [layer for layer in layers if layer.applies_to(subject)]
    applicable.sort(key=lambda layer: level_rank(layer.level))

    effective = EffectivePolicy(
        layers=[f"{layer.level}:{layer.scope_id}({layer.mode})" for layer in applicable],
        layer_modes=[
            {
                "policy": layer.document.key,
                "level": layer.level,
                "scope": layer.scope_id,
                "compose": layer.mode,
                "mode": layer.document.mode,
            }
            for layer in applicable
        ],
        applicable=applicable,
    )
    by_id: dict[str, ResolvedRule] = {}
    overridable: dict[str, bool] = {}

    for layer in applicable:
        document = layer.document
        # The summary mode is "enforce" if any applicable layer enforces. It is a
        # summary only: each rule is applied under its own layer's mode, and a
        # narrower observe layer never demotes a broader enforced rule (a rule it
        # tightens stays in force under the broader layer — `superseded`).
        if document.mode == "enforce":
            effective.mode = "enforce"
        if EFFECT_RANK.get(document.default_effect, 0) > EFFECT_RANK.get(
            effective.default_effect, 0
        ):
            effective.default_effect = document.default_effect

        for rule in document.rules:
            existing = by_id.get(rule.id)
            marked = bool(getattr(rule, "overridable", False))

            if existing is None:
                by_id[rule.id] = ResolvedRule(
                    rule=rule,
                    level=layer.level,
                    scope_id=layer.scope_id,
                    mode=layer.mode,
                    layer=layer,
                )
                overridable[rule.id] = marked
                continue

            tightening = EFFECT_RANK[rule.effect] >= EFFECT_RANK[existing.rule.effect]

            # `restrict` may only tighten. A layer that declares restraint and then
            # loosens is a misconfiguration, not a permission — so it is rejected
            # loudly rather than silently applied.
            if layer.mode == "restrict" and not tightening:
                effective.rejected.append(
                    {
                        "rule_id": rule.id,
                        "level": layer.level,
                        "scope": layer.scope_id,
                        "reason": (
                            f"mode 'restrict' cannot weaken '{existing.rule.effect}' "
                            f"(from {existing.level}) to '{rule.effect}'"
                        ),
                    }
                )
                continue

            if not tightening and not overridable.get(rule.id, False):
                effective.rejected.append(
                    {
                        "rule_id": rule.id,
                        "level": layer.level,
                        "scope": layer.scope_id,
                        "reason": (
                            f"cannot loosen '{existing.rule.effect}' (from "
                            f"{existing.level}) to '{rule.effect}' — the upstream rule "
                            "is not marked overridable"
                        ),
                    }
                )
                continue

            by_id[rule.id] = ResolvedRule(
                rule=rule,
                level=layer.level,
                scope_id=layer.scope_id,
                mode=layer.mode,
                overrides=[*existing.overrides, f"{existing.level}:{existing.scope_id}"],
                loosened=not tightening,
                layer=layer,
                # A tightening keeps the broader rule in force beside it; a granted
                # loosening is the one thing that takes a rule out of force.
                superseded=(
                    [*existing.superseded, (existing.layer, existing.rule)]
                    if tightening and existing.layer is not None
                    else []
                ),
            )
            overridable[rule.id] = marked

    effective.rules = sorted(by_id.values(), key=lambda r: (level_rank(r.level), r.rule.id))
    return effective


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


@dataclass
class LintFinding:
    code: str
    severity: str
    rule_id: str
    message: str
    level: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
        }


#: Values a condition field may take. A rule naming anything else can never
#: match, so it is a rule that reports as enforced and enforces nothing.
#:
#: Only fields whose full set of legal values is knowable from here are listed.
#: `action_risk` deliberately is not: risk codes are emitted from several
#: modules and a rule may glob over them, so a whitelist would be a second
#: place to keep in step and would flag working rules as dead — which is worse
#: than the problem it set out to solve.
_ENUMERABLE_CONDITIONS: dict[str, tuple[str, ...]] = {
    "surface": SURFACES,
    "action_operation": ("read", "write", "destructive", "admin", "unknown"),
    # From `compliance.risk.EU_CLASSES`, imported rather than retyped — a
    # second copy of this list is what the check exists to catch.
    "risk_tier": EU_CLASSES,
    # `high_impact` sits between write and irreversible; `seed.py` and the
    # onboarding summary both use it.
    "tool_impact": ("read", "write", "high_impact", "irreversible"),
}


def _unreachable(rule: Rule) -> str | None:
    """Why this rule can never fire, or None if it can.

    A competitor throws at load when a policy names an implementation that does
    not exist, and their reasoning is the one this project is built on: the
    guard then allows, exits zero, and still reports itself as having run — a
    machine reporting that a check happened when it never did. We had no
    equivalent: `lint_policy` caught duplicate ids and shadowing, and nothing
    asked whether a rule's own conditions could ever be true.
    """
    for field_name, allowed in _ENUMERABLE_CONDITIONS.items():
        value = getattr(rule.when, field_name, None)
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        unknown = [v for v in values if v not in allowed]
        if len(unknown) == len(values):
            return (
                f"every value in `{field_name}` is unknown ({', '.join(sorted(unknown))}); "
                f"this rule can never match. Known: {', '.join(allowed)}"
            )

    # The mistake the completion surface invites: naming the conditions without
    # scoping the rule to the surface that supplies them.
    if rule.when.completion_requires and rule.when.surface != ["completion"]:
        return (
            "`completion_requires` only has values on the `completion` surface, and this "
            "rule is not scoped to it — add `surface: [completion]`"
        )

    return None


def _unknown_values(rule: Rule) -> list[str]:
    """Values a rule names that no request can ever carry, field by field.

    A rule whose *every* value is unknown is reported as `unreachable`; this catches
    the rest — `surface: [input, toolargs]` still fires on input, but `toolargs` is
    a typo that silently drops the tool-argument surface the author meant.
    """
    out: list[str] = []
    for field_name, allowed in _ENUMERABLE_CONDITIONS.items():
        value = getattr(rule.when, field_name, None)
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        unknown = [v for v in values if v not in allowed]
        if unknown and len(unknown) < len(values):
            out.append(
                f"`{field_name}` names unknown value(s) {', '.join(sorted(map(str, unknown)))}; "
                f"known: {', '.join(allowed)}"
            )
    return out


def lint_policy(layers: list[PolicyLayer]) -> list[LintFinding]:
    """Catch the misconfigurations that hierarchy makes possible.

    This is the half of hierarchical policy that produces the 87%. Composition without a linter just
    moves the confusion somewhere harder to see.
    """
    findings: list[LintFinding] = []
    ordered = sorted(layers, key=lambda layer: level_rank(layer.level))

    seen: dict[str, tuple[str, str, Rule]] = {}
    overridable: dict[str, bool] = {}

    for layer in ordered:
        ids_in_layer: set[str] = set()
        for rule in layer.document.rules:
            # Duplicate ids inside one document: the second silently wins.
            if rule.id in ids_in_layer:
                findings.append(
                    LintFinding(
                        "duplicate-id",
                        "high",
                        rule.id,
                        # Positional order is (code, severity, rule_id, message, level);
                        # passing a `message=` keyword as well would raise TypeError.
                        f"'{rule.id}' is defined twice in the same layer; "
                        "the later definition silently wins",
                        layer.level,
                    )
                )
            ids_in_layer.add(rule.id)

            dead = _unreachable(rule)
            if dead:
                findings.append(
                    LintFinding(
                        "unreachable",
                        "high",
                        rule.id,
                        f"'{rule.id}' can never fire: {dead}",
                        layer.level,
                    )
                )

            for problem in _unknown_values(rule):
                findings.append(
                    LintFinding(
                        "unknown-value",
                        "high",
                        rule.id,
                        f"'{rule.id}': {problem}",
                        layer.level,
                    )
                )

            if not rule.enabled:
                findings.append(
                    LintFinding(
                        "disabled",
                        "low",
                        rule.id,
                        "rule is disabled and enforces nothing",
                        layer.level,
                    )
                )

            # Over-broad tool globs on blocking rules.
            tool = rule.when.tool
            if tool in ("*", "**") and rule.effect in ("block", "escalate"):
                findings.append(
                    LintFinding(
                        "over-broad-glob",
                        "medium",
                        rule.id,
                        f"'{rule.effect}' applies to every tool ('{tool}') — "
                        "likely to produce false blocks",
                        layer.level,
                    )
                )

            # A rule with no conditions at all matches everything.
            if rule.effect in ("block", "escalate") and not rule.when.model_dump(exclude_none=True):
                findings.append(
                    LintFinding(
                        "unconditional",
                        "high",
                        rule.id,
                        f"'{rule.effect}' has no conditions and will fire on every request",
                        layer.level,
                    )
                )

            previous = seen.get(rule.id)
            if previous is not None:
                prev_level, prev_scope, prev_rule = previous
                if EFFECT_RANK[rule.effect] < EFFECT_RANK[prev_rule.effect]:
                    if not overridable.get(rule.id, False):
                        findings.append(
                            LintFinding(
                                "illegal-loosening",
                                "critical",
                                rule.id,
                                f"weakens '{prev_rule.effect}' from {prev_level}:"
                                f"{prev_scope} to '{rule.effect}' without an "
                                "'overridable: true' grant upstream — this rule will "
                                "be rejected at resolution",
                                layer.level,
                            )
                        )
                elif rule.effect == prev_rule.effect and rule.when == prev_rule.when:
                    findings.append(
                        LintFinding(
                            "shadowed",
                            "low",
                            rule.id,
                            f"identical to {prev_level}:{prev_scope}; the inherited "
                            "rule already covers it",
                            layer.level,
                        )
                    )
            seen[rule.id] = (layer.level, layer.scope_id, rule)
            overridable[rule.id] = bool(getattr(rule, "overridable", False))

    return findings


def lint_documents(documents: list[PolicyDocument]) -> list[LintFinding]:
    """Lint policy files that are not bound: each one as an org-level layer, in order.

    What `policy validate FILE` and `policy lint FILE...` run — the same checks as
    the bound hierarchy gets, so a file that passes here passes there.
    """
    return lint_policy([PolicyLayer(document=doc) for doc in documents])


def lint_summary(findings: list[LintFinding]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    blocking = [f for f in findings if f.severity in ("critical", "high")]
    return {
        "findings": [f.to_json() for f in findings],
        "counts": counts,
        "total": len(findings),
        # CI should fail on critical/high. Low and medium are advice.
        "passed": not blocking,
        "blocking": [f.to_json() for f in blocking],
    }
