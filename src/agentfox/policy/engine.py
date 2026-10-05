"""Native policy evaluator (P6-1, P2-2, P3-4).

Deterministic (X-4): same input + same policy version -> same decision, every time.
That property is what makes replay (P5-6), simulation (P2-7) and evidence
reproducibility (P5-7) possible, so it is a hard constraint rather than a nicety —
nothing here may consult the clock, a random source, or a network.

The OPA adapter (``opa.py``) implements the same :class:`PolicyEngine` protocol and
is verified against this one in the test suite, which is how "swappable" stays true.
"""

from __future__ import annotations

import fnmatch
from typing import Any, Protocol

from agentfox.detection.base import taint_rank
from agentfox.policy.model import (
    COMPARATORS,
    EFFECT_RANK,
    Condition,
    FiredRule,
    PolicyDecision,
    PolicyDocument,
    PolicyInput,
    Rule,
)


class PolicyEngine(Protocol):
    name: str

    def evaluate(self, policy: PolicyDocument, pinput: PolicyInput) -> PolicyDecision: ...


def _get_path(data: Any, path: str) -> Any:
    """Dotted/bracket path lookup: ``body.items[0].amount``."""
    current = data
    for part in path.replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _rule_entities(rule: Rule) -> tuple[list[str], list[str]]:
    """What a rule's detection condition names: (exact types, family prefixes).

    Mirrors `_matches_detection` below rather than paraphrasing it — exact types
    compare by equality, prefixes by `startswith` — so the explanation can never
    disagree with the engine about which detection a rule was testing. A rule with
    no detection condition returns two empty lists, read downstream as "no entity
    constraint" rather than "matches nothing".
    """
    detection = getattr(rule.when, "detection", None)
    if detection is None:
        return [], []
    exact = [str(detection.entity).upper()] if detection.entity else []
    prefixes = [str(detection.entity_prefix).upper()] if detection.entity_prefix else []
    return exact, prefixes


class NativePolicyEngine:
    name = "native"

    def evaluate(self, policy: PolicyDocument, pinput: PolicyInput) -> PolicyDecision:
        fired: list[FiredRule] = []
        for rule in policy.rules:
            if not rule.enabled:
                continue
            if not self._matches(rule.when, pinput):
                continue
            entities, entity_prefixes = _rule_entities(rule)
            fired.append(
                FiredRule(
                    rule_id=rule.id,
                    effect=rule.effect,
                    reason=rule.reason or self._explain(rule, pinput),
                    severity=rule.severity,
                    controls=list(rule.controls),
                    redaction=rule.redaction,
                    mode=policy.mode,
                    entities=entities,
                    entity_prefixes=entity_prefixes,
                )
            )

        effective = policy.default_effect
        for f in fired:
            if EFFECT_RANK[f.effect] > EFFECT_RANK[effective]:
                effective = f.effect  # type: ignore[assignment]

        # Observe mode records the counterfactual but never blocks the caller.
        # This is the R3 mitigation: a customer turns enforcement on deliberately,
        # after simulating it, not by installing us.
        verdict = effective if policy.mode == "enforce" else "allow"

        return PolicyDecision(
            verdict=verdict,
            effective_verdict=effective,
            rules_fired=fired,
            policy_key=policy.key,
            policy_version=policy.version,
            mode=policy.mode,
            engine=self.name,
        )

    # -- condition matching ----------------------------------------------
    def _matches(self, cond: Condition, p: PolicyInput) -> bool:
        if cond.surface and p.surface not in cond.surface:
            return False
        if cond.environment and p.environment not in cond.environment:
            return False
        if cond.agent and not (p.agent_slug and fnmatch.fnmatch(p.agent_slug, cond.agent)):
            return False
        if cond.risk_tier and p.risk_tier not in cond.risk_tier:
            return False
        if cond.tool and not (p.tool_key and fnmatch.fnmatch(p.tool_key, cond.tool)):
            return False
        if cond.tool_impact and p.tool_impact not in cond.tool_impact:
            return False

        if cond.detection and not self._detection_matches(cond, p):
            return False

        if cond.argument:
            value = _get_path(p.arguments, cond.argument.path)
            if value is None:
                return False
            try:
                if not COMPARATORS[cond.argument.op](value, cond.argument.value):
                    return False
            except Exception:
                return False

        if cond.taint_exceeds is not None:
            allowed = taint_rank(cond.taint_exceeds)
            actual = taint_rank(str(p.taint.get("max_source", "none")))
            # Argument-level taint is what matters for a tool call; message-level
            # taint is what matters for a prompt. Take the worst of either.
            for source in (p.taint.get("arguments") or {}).values():
                actual = max(actual, taint_rank(str(source)))
            if actual <= allowed:
                return False

        if cond.capability is not None:
            state = self._capability_state(p.capability)
            if state != cond.capability:
                return False

        if not self._action_matches(cond, p):
            return False

        if cond.budget_exceeded is not None:
            if bool(p.budget.get("exceeded", False)) != cond.budget_exceeded:
                return False

        if cond.loop_detected is not None:
            if bool(p.budget.get("loop_detected", False)) != cond.loop_detected:
                return False

        if cond.intent_declared is not None:
            if bool(p.intent) != cond.intent_declared:
                return False

        if cond.detector_degraded is not None:
            if p.detector_degraded != cond.detector_degraded:
                return False

        if cond.tool_known is not None:
            if p.tool_known != cond.tool_known:
                return False

        if cond.completion_requires:
            # Unmet means "not reported true". A condition the caller did not
            # mention is unmet, not assumed — the whole point of the gate is
            # that an agent claiming to be finished has to have been checked,
            # and a caller that forgets to report `ci_green` has not checked it.
            unmet = [name for name in cond.completion_requires if not p.completion.get(name)]
            if not unmet:
                return False

        if cond.expr and not self._eval_expr(cond.expr, p):
            return False

        return True

    @staticmethod
    def _action_matches(cond: Condition, p: PolicyInput) -> bool:
        """P9 — match on what the artefact does, not on the tool it arrived through."""
        action = p.action or {}
        if cond.action_operation is not None:
            if action.get("operation") not in cond.action_operation:
                return False
        if cond.blast_radius_at_least is not None:
            rank = {"none": 0, "bounded": 1, "unknown": 2, "unbounded": 3, "catastrophic": 4}
            if rank.get(str(action.get("blast_radius")), -1) < rank.get(
                cond.blast_radius_at_least, 99
            ):
                return False
        if cond.action_reversible is not None:
            if action.get("reversible", True) != cond.action_reversible:
                return False
        if cond.action_risk is not None:
            codes = [r.get("code", "") for r in action.get("risks", [])]
            if not any(fnmatch.fnmatch(code, cond.action_risk) for code in codes):
                return False
        return True

    @staticmethod
    def _detection_matches(cond: Condition, p: PolicyInput) -> bool:
        assert cond.detection is not None
        d = cond.detection
        matched = 0
        for det in p.detections:
            entity = str(det.get("entity_type", ""))
            score = float(det.get("score", 0.0))
            if score < d.min_score:
                continue
            if d.entity and entity != d.entity:
                continue
            if d.entity_prefix and not entity.startswith(d.entity_prefix):
                continue
            matched += 1
        return matched >= d.min_count

    @staticmethod
    def _capability_state(capability: dict[str, Any]) -> str:
        """Mirrors ``CapabilityDecision.state``. ``denied`` is reserved for the case
        where no grant exists at all; a grant that exists and was exceeded is
        ``constraint_violated``, so the two get different rules and different
        reasons."""
        if not capability.get("granted", True):
            if capability.get("constraint_violations"):
                return "constraint_violated"
            return "denied"
        if capability.get("requires_approval"):
            return "requires_approval"
        return "granted"

    @staticmethod
    def _eval_expr(expr: str, p: PolicyInput) -> bool:
        """Tiny sandboxed expression escape hatch.

        Deliberately not ``eval`` on arbitrary code: policies are security-relevant
        artefacts, and a policy language that can execute Python is a privilege
        escalation path into the control plane itself.
        """
        allowed: dict[str, Any] = {
            "agent": p.agent_slug,
            "surface": p.surface,
            "tool": p.tool_key,
            "impact": p.tool_impact,
            "risk_tier": p.risk_tier,
            "environment": p.environment,
            "n_detections": len(p.detections),
            "max_score": max((float(d.get("score", 0)) for d in p.detections), default=0.0),
            "prior_tool_count": len(p.prior_tools),
            "taint": str(p.taint.get("max_source", "none")),
        }
        try:
            return bool(eval(expr, {"__builtins__": {}}, allowed))  # noqa: S307
        except Exception:
            return False

    @staticmethod
    def _explain(rule: Rule, p: PolicyInput) -> str:
        """Auto-generated reason when the author did not write one.

        X-4 requires every block to carry an auditable reason; falling back to the
        rule id alone would technically satisfy that and practically fail it.
        """
        bits: list[str] = []
        if rule.when.detection:
            entities = sorted(
                {
                    str(d.get("entity_type"))
                    for d in p.detections
                    if float(d.get("score", 0)) >= rule.when.detection.min_score
                }
            )
            if entities:
                bits.append(f"detected {', '.join(entities[:5])}")
        if rule.when.taint_exceeds:
            bits.append(
                f"argument provenance '{p.taint.get('max_source')}' exceeds "
                f"'{rule.when.taint_exceeds}'"
            )
        if rule.when.argument:
            value = _get_path(p.arguments, rule.when.argument.path)
            bits.append(
                f"{rule.when.argument.path}={value!r} {rule.when.argument.op} "
                f"{rule.when.argument.value!r}"
            )
        if rule.when.tool:
            bits.append(f"tool '{p.tool_key}'")
        if rule.when.capability:
            # A violated constraint already knows the grant, the limit and the value
            # that failed it. Printing "capability constraint_violated" instead would
            # be the boilerplate this rule exists to replace.
            detail = str(p.capability.get("constraint_reason") or "")
            if not detail and rule.when.capability == "denied":
                # Same principle for a missing grant: the capability check already
                # names the agent, the tool and the command that would fix it.
                detail = "; ".join(str(r) for r in p.capability.get("reasons") or [])
            bits.append(detail if detail else f"capability {rule.when.capability}")
        return "; ".join(bits) or f"rule '{rule.id}' matched"


def combine(decisions: list[PolicyDecision]) -> PolicyDecision:
    """Merge decisions from multiple bound policies. Strongest effect wins."""
    if not decisions:
        return PolicyDecision()
    merged = PolicyDecision(
        verdict="allow",
        effective_verdict="allow",
        mode="observe",
        engine=decisions[0].engine,
    )
    # Which pack's mode governed *this* decision. Taking "enforce if any bound pack
    # is in enforce" describes the deployment, not the decision, and it produced the
    # contradiction an audit found in the public sandbox: a pack bound in observe
    # raised the effective verdict to block, nothing was applied, and the record
    # still said mode `enforce` because a different pack that fired nothing happened
    # to be bound in enforce. The mode reported is the mode of the pack that set the
    # effective verdict; per-rule modes carry the rest (FiredRule.mode).
    governing: PolicyDecision | None = None
    for d in decisions:
        merged.rules_fired.extend(d.rules_fired)
        if EFFECT_RANK[d.verdict] > EFFECT_RANK[merged.verdict]:
            merged.verdict = d.verdict
        if EFFECT_RANK[d.effective_verdict] > EFFECT_RANK[merged.effective_verdict]:
            merged.effective_verdict = d.effective_verdict
            governing = d
        if merged.policy_key is None:
            merged.policy_key = d.policy_key
            merged.policy_version = d.policy_version
    if governing is not None:
        merged.mode = governing.mode
    elif any(d.mode == "enforce" for d in decisions):
        # Nothing fired anywhere, so no pack governed anything. Report the binding,
        # which is the only fact there is.
        merged.mode = "enforce"
    return merged
