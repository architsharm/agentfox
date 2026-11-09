"""Which policies apply, how verdicts rank, and how a fired rule is written down."""

from __future__ import annotations

import logging
from typing import Any

from agentfox.core.vocab import CAPABILITY_REFUSAL_RULE_IDS, EFFECT_RANK, VERDICT_RANK
from agentfox.platform.policy.store import fallback_policies

log = logging.getLogger("agentfox.runtime.enforcement")


#: Verdict severity ordering, shared by every comparison in this module — the same
#: precedence the policy engine itself uses to combine rule effects, not a second
#: copy of it.
_RANK = EFFECT_RANK


class _FallbackVersion:
    """Stands in for a PolicyVersion the fallback does not have.

    `id` is None on purpose. These ids are persisted onto the Decision row as
    the exact set of policy versions in force, which is what makes a decision
    reproducible. The fallback has no stored version, so inventing an id
    would put a reference to a row that does not exist into the audit record —
    the one place in this product that must not contain a plausible fiction.
    Callers filter it out; a decision made under the fallback records no policy
    version, which is the truth.
    """

    id = None


_FALLBACK_VERSION = _FallbackVersion()


# Which shipped policies apply to a deployment that has configured nothing is pack
# data: a built-in capability pack's `fallback` block names the agent risk tiers its
# policies protect when nothing is bound (`platform/packs:fallback_policy_packs`).
#
# Only the default case. Anything an operator binds replaces all of this —
# `active_policies` is consulted first and the fallback is never reached.
#
# `baseline` declares every tier ("*") because prompt injection, PII and secrets are
# not properties of a sector or a jurisdiction; every agent that reads text has them.
# The rest is chosen from what the operator has ALREADY DECLARED about the agent,
# never inferred: the `eu-ai-act` pack declares `high` and `prohibited`, the classes
# its own policy is written for, so applying it to an agent somebody classified
# high-risk is responding to their declaration rather than deciding on their behalf.
# An agent at the default tier gets baseline alone, because silently applying EU AI
# Act rules to someone who never said they were in scope would be overclaiming.
#
# Framework is deliberately NOT a selector. Which content pack is right does not
# depend on whether the app is built on LangChain or CrewAI — the same injection
# reaches the same model either way — and a framework-to-policy mapping would be a
# rule that looks considered and means nothing.


# Lives with the policy store, so the Policies page (`capabilities/protection/applied`)
# lists exactly what the enforcer applies; the name here is kept for its callers and
# for the tests that clear its cache.
_fallback_policies = fallback_policies


#: Which of two verdicts is the stronger claim, for picking between the
#: layers of one file. Ordinary verdict comparison is scattered across the
#: engine; this is the one place that needs only "which is worse". Defined in
#: core.vocab so a layer below the runtime can read it too.
_VERDICT_RANK = VERDICT_RANK


#: Risk codes whose condition a shipped policy pack already has a rule for, mapped to
#: that rule's id. The codes in `effects.py` and `data_access.py` are hyphenated for
#: historical reasons; every rule id in the product is dotted, and a decision that
#: printed both spellings of one rule (`cascade.reaches_destructive` next to
#: `cascade-reaches-destructive`) looked like two findings and read like a bug. The
#: codes themselves are unchanged: `when: action_risk:` in the packs still matches on
#: them, and so does anything reading `taint.action`.
RISK_CODE_RULE_IDS = {
    "cascade-reaches-destructive": "cascade.reaches_destructive",
    "cascade-reaches-notification": "cascade.reaches_notification",
    "cascade-cycle": "cascade.cycle",
    "cascade-too-deep": "cascade.blast_radius",
    "unscoped-table": "access.unscoped_table",
    "undeclared-table": "access.undeclared_table",
}


#: Every rule id that means "this call was refused at the capability layer". The
#: synthetic fallback below checks the whole set, so a pack that already said it in
#: its own words is not echoed under a second id. Defined in core.vocab.
_CAPABILITY_REFUSAL_RULE_IDS = CAPABILITY_REFUSAL_RULE_IDS


def _fired_rule(
    rule_id: str,
    effect: str,
    reason: str,
    *,
    severity: str | None = None,
    controls: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
    mode: str = "enforce",
) -> dict[str, Any]:
    """One entry in `rules_fired` for a synthetic (non-policy-authored) rule —
    the shape a dozen-plus call sites in this module built by hand. Optional keys
    are omitted rather than set to ``None`` so each entry carries only the keys its
    call site supplies.

    ``mode`` says whether *this rule's* effect was applied or only recorded. It
    defaults to ``enforce`` because a synthetic rule is a fact about the call rather
    than a policy opinion: the absence of a grant, a destructive statement, a killed
    agent, a grant that asks for a person. Those set the verdict whatever mode the
    packs are bound in. The call sites that are gated on the decision's mode pass it
    explicitly.
    """
    rule: dict[str, Any] = {"rule_id": rule_id, "effect": effect, "reason": reason, "mode": mode}
    if severity is not None:
        rule["severity"] = severity
    if controls is not None:
        rule["controls"] = controls
    if evidence is not None:
        rule["evidence"] = evidence
    return rule
