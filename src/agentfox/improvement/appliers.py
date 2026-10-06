"""How each kind of proposed change is actually made — and unmade.

A proposal is inert until an applier exists for its kind. Each applier answers three
questions, and the service in :mod:`agentfox.improvement.proposals` refuses to move a
proposal whose applier cannot answer all three:

* ``direction`` — does this change tighten or loosen, **computed from the diff and the
  live configuration**, never taken from whoever filed it. A loop that mislabels a
  loosening as a tightening would otherwise walk straight past the one rule the
  contract says cannot be tuned.
* ``apply`` — make the change through the same functions a person would use, so the
  change is recorded the way a person's would be, and return what changed.
* ``revert`` — undo it. A change that cannot be undone is refused at apply time rather
  than discovered at rollback time.

Kinds: ``suppression.revoke`` and ``policy.rule_min_score`` (the threshold loop), and
``capability.grant`` and ``tool.declare`` (the learned-permissions loop in
:mod:`agentfox.improvement.traffic`).

Appliers never touch proposal status or write proposal audit entries; that is the
service's job. They do call the domain functions (``revoke_suppression``,
``save_policy``, ``start_canary``) that record their own domain-level entries.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    AuditEntry,
    ChangeProposal,
    GuardrailFeedback,
    Policy,
    PolicyBinding,
    PolicyCanary,
    PolicyVersion,
    Suppression,
)
from agentfox.improvement import contract

#: Audit action the service records an apply under. Declared here because a revert
#: reads back what its own apply recorded — the chain, not a mutable column, is the
#: record of what was changed.
APPLY_ACTION = "operator.proposal.applied"


class ApplierError(ValueError):
    """The change cannot be computed, applied or reverted as proposed."""


@dataclass(frozen=True)
class Applier:
    kind: str
    #: ``(session, proposal) -> direction``. Computed from the diff and live state.
    direction: Callable[[Session, ChangeProposal], str]
    #: ``(session, proposal, *, actor) -> what changed``. A result carrying
    #: ``{"staged": "canary"}`` means the change is live for a cohort only.
    apply: Callable[..., dict[str, Any]]
    #: ``(session, proposal, *, actor) -> what was restored``.
    revert: Callable[..., dict[str, Any]]
    #: For staged applies: ``"rolling" | "completed" | "rolled_back"``.
    stage_status: Callable[[Session, ChangeProposal], str] | None = None


_REGISTRY: dict[str, Applier] = {}


def register(applier: Applier) -> Applier:
    _REGISTRY[applier.kind] = applier
    return applier


def get_applier(kind: str) -> Applier:
    applier = _REGISTRY.get(kind)
    if applier is None:
        raise ApplierError(
            f"no applier is registered for kind '{kind}'; it can be recommended but not applied"
        )
    return applier


def has_applier(kind: str) -> bool:
    return kind in _REGISTRY


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


def applied_result(session: Session, proposal: ChangeProposal) -> dict[str, Any]:
    """What the most recent apply of this proposal recorded that it changed."""
    entry = session.scalars(
        select(AuditEntry)
        .where(
            AuditEntry.action == APPLY_ACTION,
            AuditEntry.subject_type == "change_proposal",
            AuditEntry.subject_id == proposal.id,
        )
        .order_by(AuditEntry.seq.desc())
        .limit(1)
    ).first()
    if entry is None:
        raise ApplierError(f"proposal {proposal.id} has no recorded apply to revert")
    return dict((entry.payload_json or {}).get("changed") or {})


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# suppression.revoke — tightens
# ---------------------------------------------------------------------------


def _suppression_id(proposal: ChangeProposal) -> str:
    sid = (proposal.diff_json or {}).get("suppression_id") or proposal.target_ref
    if not sid:
        raise ApplierError("suppression.revoke needs diff.suppression_id or target_ref")
    return str(sid)


def _revertible_feedback(session: Session, suppression: Suppression) -> GuardrailFeedback:
    feedback = (
        session.get(GuardrailFeedback, suppression.feedback_id) if suppression.feedback_id else None
    )
    if feedback is None or feedback.label != "false_positive":
        raise ApplierError(
            f"suppression {suppression.id} has no false-positive report behind it, so "
            "revoking it could not be reverted through the suppression workflow; "
            "revoke it by hand instead"
        )
    return feedback


def _suppression_direction(session: Session, proposal: ChangeProposal) -> str:
    # Revoking an exception restores detection. There is no reading of this under
    # which it loosens anything.
    return contract.TIGHTENS


def _suppression_apply(session: Session, proposal: ChangeProposal, *, actor: str) -> dict[str, Any]:
    from agentfox.detection.tuning import revoke_suppression

    suppression = session.get(Suppression, _suppression_id(proposal))
    if suppression is None:
        raise ApplierError(f"unknown suppression '{_suppression_id(proposal)}'")
    if not suppression.active:
        raise ApplierError(f"suppression {suppression.id} is not active; nothing to revoke")
    _revertible_feedback(session, suppression)  # reversible, or not applied at all

    revoke_suppression(
        session,
        suppression.id,
        actor=actor,
        reason=f"change proposal {proposal.id}: {proposal.title or 'revoke suppression'}",
    )
    return {
        "revoked": suppression.id,
        "detector": suppression.detector_key,
        "agent_id": suppression.agent_id,
        "entity_type": suppression.entity_type,
        "expires_at": _aware(suppression.expires_at).isoformat()
        if suppression.expires_at
        else None,
    }


def _suppression_revert(
    session: Session, proposal: ChangeProposal, *, actor: str
) -> dict[str, Any]:
    from agentfox.detection.tuning import apply_suppression

    original = session.get(Suppression, _suppression_id(proposal))
    if original is None:
        raise ApplierError(f"unknown suppression '{_suppression_id(proposal)}'")
    if original.revoked_at is None:
        raise ApplierError(f"suppression {original.id} was never revoked; nothing to restore")
    feedback = _revertible_feedback(session, original)

    expires = _aware(original.expires_at)
    now = dt.datetime.now(dt.UTC)
    remaining_days = max(1, math.ceil((expires - now).total_seconds() / 86400)) if expires else 30
    restored = apply_suppression(
        session,
        feedback_id=feedback.id,
        scope="agent" if original.agent_id else "global",
        ttl_days=remaining_days,
        actor=actor,
        reason=(
            f"reverting change proposal {proposal.id}: restores suppression {original.id} "
            "with its original scope and expiry"
        ),
    )
    # Same scope and the same end date as the one revoked — not a fresh TTL, which
    # would quietly extend an exception nobody re-approved.
    restored.agent_id = original.agent_id
    restored.detector_key = original.detector_key
    restored.entity_type = original.entity_type
    restored.sample_hash = original.sample_hash
    restored.surface = original.surface
    restored.expires_at = original.expires_at
    session.flush()
    return {
        "restored": restored.id,
        "replaces": original.id,
        "agent_id": restored.agent_id,
        "entity_type": restored.entity_type,
        "expires_at": expires.isoformat() if expires else None,
        "already_expired": bool(expires and expires <= now),
    }


register(
    Applier(
        kind="suppression.revoke",
        direction=_suppression_direction,
        apply=_suppression_apply,
        revert=_suppression_revert,
    )
)


# ---------------------------------------------------------------------------
# policy.rule_min_score — either direction
# ---------------------------------------------------------------------------


def _policy_diff(proposal: ChangeProposal) -> tuple[str, str, float]:
    diff = proposal.diff_json or {}
    policy_key = diff.get("policy") or proposal.target_ref
    rule_id = diff.get("rule_id")
    if not policy_key or not rule_id or diff.get("to") is None:
        raise ApplierError("policy.rule_min_score needs diff.policy, diff.rule_id and diff.to")
    try:
        target = float(diff["to"])
    except (TypeError, ValueError) as exc:
        raise ApplierError("diff.to must be a number") from exc
    if not 0.0 <= target <= 1.0:
        raise ApplierError("diff.to must be between 0 and 1")
    return str(policy_key), str(rule_id), target


def _live_policy(session: Session, policy_key: str) -> tuple[Policy, PolicyVersion, PolicyBinding]:
    from agentfox.policy.store import _open_binding_for_version

    policy = session.scalar(select(Policy).where(Policy.key == policy_key))
    if policy is None:
        raise ApplierError(f"unknown policy '{policy_key}'")
    for version in session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version.desc())
    ):
        binding = _open_binding_for_version(session, version.id)
        if binding is not None:
            return policy, version, binding
    raise ApplierError(f"policy '{policy_key}' has no live binding")


def _document(version: PolicyVersion):
    import yaml

    from agentfox.policy.model import PolicyDocument

    return PolicyDocument.model_validate(version.compiled_json or yaml.safe_load(version.body))


def _rule(doc, rule_id: str):
    rule = next((r for r in doc.rules if r.id == rule_id), None)
    if rule is None:
        raise ApplierError(f"policy '{doc.key}' has no rule '{rule_id}'")
    if rule.when.detection is None:
        raise ApplierError(f"rule '{rule_id}' has no detection condition to tune")
    return rule


#: How a scoped change records which agents a rule is limited to, in the rule's
#: ``when.expr``. The engine evaluates it; `rule_agent_restriction` reads it back.
_AGENT_IN = "agent in "
_AGENT_NOT_IN = "agent not in "


def _agents_literal(agents: list[str]) -> str:
    return "(" + ", ".join(repr(a) for a in sorted(agents)) + ",)"


def _parse_agents(text: str) -> set[str]:
    import ast

    try:
        value = ast.literal_eval(text.strip())
    except (ValueError, SyntaxError):
        return set()
    return {str(v) for v in value} if isinstance(value, tuple | list | set) else set()


def rule_agent_restriction(rule) -> tuple[set[str] | None, set[str]]:
    """(agents the rule is limited to or None, agents it excludes), as written by a
    scoped ``policy.rule_min_score`` change into the rule's ``expr``."""
    import re

    allow: set[str] | None = None
    deny: set[str] = set()
    for negated, literal in re.findall(r"agent (not )?in (\([^()]*\))", rule.when.expr or ""):
        if negated:
            deny |= _parse_agents(literal)
        else:
            allow = (allow or set()) | _parse_agents(literal)
    return allow, deny


def _and_expr(existing: str | None, clause: str) -> str:
    return f"({existing}) and {clause}" if existing else clause


def split_rule_for_agents(doc, rule_id: str, agents: list[str], target: float):
    """Scope a cut-off change to some agents without touching the others.

    The rule keeps its cut-off for everyone else (``agent not in (...)`` is added to
    its ``expr``), and a copy limited to those agents carries the new one. Rules match
    on AND, so the two together fire exactly where the original did, except for the
    named agents' detections between the old and new cut-off. Returns the copy.
    """
    rule = _rule(doc, rule_id)
    clone = rule.model_copy(deep=True)
    clone.id = f"{rule.id}.for.{'.'.join(sorted(agents))}"
    if any(r.id == clone.id for r in doc.rules):
        raise ApplierError(
            f"policy '{doc.key}' already has '{clone.id}'; retune that rule directly"
        )
    clone.when.expr = _and_expr(rule.when.expr, _AGENT_IN + _agents_literal(agents))
    clone.when.detection.min_score = target
    clone.description = (
        f"{rule.description or rule.id} — cut-off raised for {', '.join(sorted(agents))} "
        "from their labelled false positives"
    ).strip()
    rule.when.expr = _and_expr(rule.when.expr, _AGENT_NOT_IN + _agents_literal(agents))
    doc.rules.insert(doc.rules.index(rule) + 1, clone)
    return clone


def min_score_direction(effect: str, current: float, target: float) -> str:
    """Raising ``min_score`` makes a rule fire on fewer detections.

    For a rule that restricts (block, escalate, redact, ...) that loosens. For an
    ``allow`` rule the reading inverts in principle, but whether an allow firing less
    tightens depends on every other rule and the default effect — so it is treated as
    loosening in both directions: a change the loop cannot reason about is a change a
    person decides.
    """
    if math.isclose(current, target):
        return contract.NEUTRAL
    if effect == "allow":
        return contract.LOOSENS
    return contract.LOOSENS if target > current else contract.TIGHTENS


def _policy_direction(session: Session, proposal: ChangeProposal) -> str:
    policy_key, rule_id, target = _policy_diff(proposal)
    _policy, version, _binding = _live_policy(session, policy_key)
    rule = _rule(_document(version), rule_id)
    return min_score_direction(rule.effect, rule.when.detection.min_score, target)


def _policy_apply(session: Session, proposal: ChangeProposal, *, actor: str) -> dict[str, Any]:
    from agentfox.policy.canary import CanaryError, start_canary
    from agentfox.policy.store import save_policy

    diff = proposal.diff_json or {}
    policy_key, rule_id, target = _policy_diff(proposal)
    _policy, prior, binding = _live_policy(session, policy_key)
    doc = _document(prior)
    rule = _rule(doc, rule_id)
    current = float(rule.when.detection.min_score)

    expected = diff.get("from")
    if expected is not None and not math.isclose(float(expected), current):
        raise ApplierError(
            f"rule '{rule_id}' has drifted: live min_score is {current}, the proposal was "
            f"computed against {expected}. Refile against the live policy."
        )
    if math.isclose(current, target):
        raise ApplierError(f"rule '{rule_id}' already has min_score {target}; nothing to change")

    scoped = [str(a) for a in (diff.get("agents") or [])]
    if scoped:
        # Only the agents the labels came from get the new cut-off.
        split_rule_for_agents(doc, rule_id, scoped, target)
    else:
        rule.when.detection.min_score = target
    doc.scope = binding.scope_json or doc.scope
    _policy_row, new_version = save_policy(
        session,
        doc,
        author=actor,
        notes=f"change proposal {proposal.id}: {rule_id} min_score {current} -> {target}",
        bind_mode=binding.mode,
        level=binding.level or "org",
        scope_id=binding.scope_id or "*",
        compose=binding.compose or "extend",
    )
    result: dict[str, Any] = {
        "policy": policy_key,
        "rule_id": rule_id,
        "from": current,
        "to": target,
        "prior_version_id": prior.id,
        "prior_version": prior.version,
        "new_version_id": new_version.id,
        "new_version": new_version.version,
        "agents": scoped or ["*"],
        "staged": None,
    }
    if diff.get("stage") == "canary":
        options = diff.get("canary") or {}
        try:
            canary = start_canary(
                session,
                policy_key,
                candidate_version=new_version.version,
                steps=options.get("steps"),
                min_sample=int(options.get("min_sample", 20)),
                started_by=actor,
            )
        except CanaryError as exc:
            raise ApplierError(f"could not stage canary: {exc}") from exc
        result["staged"] = "canary"
        result["canary_id"] = canary.id
    return result


def _policy_stage_status(session: Session, proposal: ChangeProposal) -> str:
    result = applied_result(session, proposal)
    canary = session.get(PolicyCanary, result.get("canary_id") or "")
    if canary is None:
        raise ApplierError(f"proposal {proposal.id} has no canary")
    return canary.status


def _policy_revert(session: Session, proposal: ChangeProposal, *, actor: str) -> dict[str, Any]:
    from agentfox.policy.canary import rollback_canary
    from agentfox.policy.store import _open_binding_for_version

    result = applied_result(session, proposal)
    prior_id = result.get("prior_version_id")
    new_id = result.get("new_version_id")
    if not prior_id or not new_id:
        raise ApplierError(f"proposal {proposal.id} recorded no versions to revert between")

    canary_id = result.get("canary_id")
    if canary_id:
        canary = session.get(PolicyCanary, canary_id)
        if canary is not None and canary.status == "rolling":
            rollback_canary(session, canary.id, reason=f"change proposal {proposal.id} rolled back")
            return {"rebound_to": prior_id, "canary_rolled_back": canary.id}

    open_on_new = _open_binding_for_version(session, new_id)
    if open_on_new is None:
        if _open_binding_for_version(session, prior_id) is not None:
            return {"rebound_to": prior_id, "already_bound": True}
        raise ApplierError(
            f"policy '{result.get('policy')}' has moved on since this change; refusing to "
            "overwrite a binding this proposal did not create"
        )
    # Versions are immutable, so undoing the change is rebinding the version it
    # replaced — not saving a copy of it as yet another version.
    session.add(
        PolicyBinding(
            policy_version_id=prior_id,
            scope_json=open_on_new.scope_json,
            mode=open_on_new.mode,
            level=open_on_new.level,
            scope_id=open_on_new.scope_id,
            compose=open_on_new.compose,
        )
    )
    open_on_new.effective_to = dt.datetime.now(dt.UTC)
    session.flush()
    return {"rebound_to": prior_id, "unbound": new_id}


register(
    Applier(
        kind="policy.rule_min_score",
        direction=_policy_direction,
        apply=_policy_apply,
        revert=_policy_revert,
        stage_status=_policy_stage_status,
    )
)


# ---------------------------------------------------------------------------
# capability.grant — loosens (a new grant, or a raised provenance ceiling)
# ---------------------------------------------------------------------------
#
# Filed by the learned-permissions loop (`improvement/traffic.py`) from an agent's
# observed calls. Two shapes, one kind:
#
#   new grant      {"agent", "tool_key", "actions", "constraints", "max_taint",
#                   "requires_approval"}
#   raise ceiling  {"agent", "tool_key", "replaces": <capability id>,
#                   "from_max_taint", "max_taint"}
#
# Both widen what an agent may do, so both are loosenings a person decides; neither
# can be applied by automation at any autonomy level (contract.may_apply_automatically).


def _grant_diff(proposal: ChangeProposal) -> dict[str, Any]:
    diff = dict(proposal.diff_json or {})
    if not diff.get("agent") or not diff.get("tool_key"):
        raise ApplierError("capability.grant needs diff.agent and diff.tool_key")
    from agentfox.detection.base import TAINT_ORDER

    if str(diff.get("max_taint") or "user") not in TAINT_ORDER:
        raise ApplierError(f"diff.max_taint must be one of {list(TAINT_ORDER)}")
    return diff


def _grant_identity(session: Session, slug: str):
    from agentfox.core.models import Agent
    from agentfox.identity import ensure_identity

    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    if agent is None:
        raise ApplierError(f"unknown agent '{slug}'")
    return ensure_identity(session, agent)


def _live_exact_grant(session: Session, identity_id: str, tool_key: str):
    from agentfox.core.models import Capability, as_aware

    now = dt.datetime.now(dt.UTC)
    for capability in session.scalars(
        select(Capability).where(
            Capability.identity_id == identity_id, Capability.tool_key == tool_key
        )
    ):
        expires = as_aware(capability.expires_at)
        if expires is None or expires > now:
            return capability
    return None


def _domain_audit(
    session: Session, action: str, subject_id: str, actor: str, payload: dict
) -> None:
    from agentfox.core.config import get_settings
    from agentfox.prove.audit import chain

    chain.append(
        session,
        action,
        **chain.attribution(automated=actor == get_settings().improvement_actor_id, actor=actor),
        subject_type="capability",
        subject_id=subject_id,
        payload=payload,
    )


def _grant_direction(session: Session, proposal: ChangeProposal) -> str:
    from agentfox.core.models import Capability
    from agentfox.detection.base import taint_rank

    diff = _grant_diff(proposal)
    if not diff.get("replaces"):
        # A grant that did not exist is always a widening, whatever its limits.
        return contract.LOOSENS
    live = session.get(Capability, str(diff["replaces"]))
    current = live.max_taint if live is not None else "none"
    target = str(diff.get("max_taint") or "user")
    if taint_rank(target) > taint_rank(current):
        return contract.LOOSENS
    if taint_rank(target) < taint_rank(current):
        return contract.TIGHTENS
    return contract.NEUTRAL


def _grant_apply(session: Session, proposal: ChangeProposal, *, actor: str) -> dict[str, Any]:
    from agentfox.core.models import Capability
    from agentfox.identity import grant_capability

    diff = _grant_diff(proposal)
    identity = _grant_identity(session, str(diff["agent"]))
    tool_key = str(diff["tool_key"])
    max_taint = str(diff.get("max_taint") or "user")

    if diff.get("replaces"):
        capability = session.get(Capability, str(diff["replaces"]))
        if capability is None or capability.identity_id != identity.id:
            raise ApplierError(
                f"grant {diff['replaces']} is gone; this proposal was computed against it. "
                "Refile with `agentfox policy proposals from-traffic`."
            )
        expected = diff.get("from_max_taint")
        if expected is not None and capability.max_taint != expected:
            raise ApplierError(
                f"grant {capability.id} has drifted: its ceiling is now "
                f"'{capability.max_taint}', the proposal was computed against '{expected}'"
            )
        before = capability.max_taint
        capability.max_taint = max_taint
        session.flush()
        _domain_audit(
            session,
            "capability.updated",
            capability.id,
            actor,
            {"change_proposal": proposal.id, "max_taint": {"from": before, "to": max_taint}},
        )
        return {
            "capability_id": capability.id,
            "agent": diff["agent"],
            "tool_key": tool_key,
            "max_taint_from": before,
            "max_taint_to": max_taint,
        }

    existing = _live_exact_grant(session, identity.id, tool_key)
    if existing is not None:
        raise ApplierError(
            f"{diff['agent']} already holds a grant for '{tool_key}' ({existing.id}), made "
            "after this proposal was filed; refusing to add a second one beside it"
        )
    capability = grant_capability(
        session,
        identity,
        tool_key,
        actions=list(diff.get("actions") or ["*"]),
        constraints=dict(diff.get("constraints") or {}),
        requires_approval=bool(diff.get("requires_approval", False)),
        max_taint=max_taint,
        granted_by=f"proposal {proposal.id} ({actor})",
    )
    shape = {
        "principal": identity.principal,
        "tool_key": tool_key,
        "actions": list(capability.actions or ["*"]),
        "constraints": dict(capability.constraints_json or {}),
        "requires_approval": capability.requires_approval,
        "max_taint": capability.max_taint,
    }
    _domain_audit(
        session,
        "capability.granted",
        capability.id,
        actor,
        {**shape, "change_proposal": proposal.id, "granted_by": capability.granted_by},
    )
    return {"capability_id": capability.id, "agent": diff["agent"], **shape}


def _grant_revert(session: Session, proposal: ChangeProposal, *, actor: str) -> dict[str, Any]:
    from agentfox.core.models import Capability
    from agentfox.identity import revoke_capability

    result = applied_result(session, proposal)
    capability_id = result.get("capability_id")
    if not capability_id:
        raise ApplierError(f"proposal {proposal.id} recorded no grant to undo")
    capability = session.get(Capability, capability_id)

    if "max_taint_from" in result:
        if capability is None:
            raise ApplierError(
                f"grant {capability_id} has been revoked since; there is no ceiling to restore"
            )
        if capability.max_taint != result.get("max_taint_to"):
            raise ApplierError(
                f"grant {capability_id}'s ceiling was changed again after this proposal; "
                "refusing to overwrite a change it did not make"
            )
        capability.max_taint = str(result["max_taint_from"])
        session.flush()
        _domain_audit(
            session,
            "capability.updated",
            capability.id,
            actor,
            {
                "change_proposal": proposal.id,
                "reverted": True,
                "max_taint": {"from": result["max_taint_to"], "to": result["max_taint_from"]},
            },
        )
        return {"capability_id": capability.id, "max_taint": result["max_taint_from"]}

    if capability is None:
        # Somebody already withdrew it by hand. The state the revert wants is the
        # state there is; say so rather than fail the rollback.
        return {"capability_id": capability_id, "already_revoked": True}
    shape = {
        "tool_key": capability.tool_key,
        "constraints": dict(capability.constraints_json or {}),
        "max_taint": capability.max_taint,
    }
    revoke_capability(session, capability_id)
    _domain_audit(
        session,
        "capability.revoked",
        capability_id,
        actor,
        {**shape, "change_proposal": proposal.id, "reverted": True},
    )
    return {"revoked": capability_id, **shape}


register(
    Applier(
        kind="capability.grant",
        direction=_grant_direction,
        apply=_grant_apply,
        revert=_grant_revert,
    )
)


# ---------------------------------------------------------------------------
# tool.declare — loosens
# ---------------------------------------------------------------------------
#
# An undeclared tool is escalated on every call (`tool.not_declared`) and reasoned
# about as `read`. Declaring it removes that escalation, so it is a loosening whatever
# impact is declared: the impact the loop proposes is a guess from the tool's name, and
# a wrong guess is the hole every impact-based rule falls through. Tool declarations
# are org-wide, so the two-person rule for org-level loosenings applies.

_IMPACTS = ("read", "write", "high_impact", "irreversible")


def _declare_diff(proposal: ChangeProposal) -> dict[str, Any]:
    from agentfox.core.models import OUTPUT_TRUST_LEVELS

    diff = dict(proposal.diff_json or {})
    if not diff.get("tool_key"):
        raise ApplierError("tool.declare needs diff.tool_key")
    if diff.get("impact") not in _IMPACTS:
        raise ApplierError(f"diff.impact must be one of {_IMPACTS}")
    if diff.get("output_trust", "untrusted") not in OUTPUT_TRUST_LEVELS:
        raise ApplierError(f"diff.output_trust must be one of {OUTPUT_TRUST_LEVELS}")
    return diff


def _declare_direction(session: Session, proposal: ChangeProposal) -> str:
    from agentfox.core.models import Tool

    diff = _declare_diff(proposal)
    live = session.scalar(select(Tool).where(Tool.key == diff["tool_key"]))
    if live is not None:
        # Declared by someone else since; applying would change nothing it can claim.
        return contract.NEUTRAL
    return contract.LOOSENS


def _declare_apply(session: Session, proposal: ChangeProposal, *, actor: str) -> dict[str, Any]:
    from agentfox.core.models import Tool
    from agentfox.registry.service import upsert_tool

    diff = _declare_diff(proposal)
    key = str(diff["tool_key"])
    if session.scalar(select(Tool).where(Tool.key == key)) is not None:
        raise ApplierError(f"'{key}' has been declared since this proposal was filed")
    tool = upsert_tool(
        session,
        key,
        name=str(diff.get("name") or key),
        impact=str(diff["impact"]),
        description=str(diff.get("description") or ""),
        output_trust=str(diff.get("output_trust") or "untrusted"),
    )
    _domain_audit(
        session,
        "tool.declared",
        tool.id,
        actor,
        {"tool_key": key, "impact": tool.impact, "change_proposal": proposal.id},
    )
    return {"tool_id": tool.id, "tool_key": key, "impact": tool.impact}


def _declare_revert(session: Session, proposal: ChangeProposal, *, actor: str) -> dict[str, Any]:
    from agentfox.core.models import Tool

    result = applied_result(session, proposal)
    tool = session.get(Tool, result.get("tool_id") or "")
    if tool is None:
        return {"tool_key": result.get("tool_key"), "already_undeclared": True}
    if tool.impact != result.get("impact"):
        raise ApplierError(
            f"'{tool.key}' was redeclared as '{tool.impact}' after this proposal; refusing "
            "to delete a declaration it did not make"
        )
    key = tool.key
    session.delete(tool)
    session.flush()
    _domain_audit(
        session,
        "tool.undeclared",
        result["tool_id"],
        actor,
        {"tool_key": key, "change_proposal": proposal.id, "reverted": True},
    )
    return {"undeclared": key}


register(
    Applier(
        kind="tool.declare",
        direction=_declare_direction,
        apply=_declare_apply,
        revert=_declare_revert,
    )
)


__all__ = [
    "APPLY_ACTION",
    "Applier",
    "ApplierError",
    "applied_result",
    "get_applier",
    "has_applier",
    "min_score_direction",
    "register",
    "registered_kinds",
]
