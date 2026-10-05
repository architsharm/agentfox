"""Pillar 2 — non-human identity, least privilege, delegation, approvals.

Appendix A.5's read of this layer: *"engines yes, agent-native no"*. OPA and Cedar
solve the decision problem; nobody has modelled the thing that actually matters for
agents — an identity whose capabilities are scoped per tool, per action, per
argument value, **and per the provenance of that argument**. That last clause is
what this module adds on top of the engine.

Three properties are enforced here rather than documented:

* **Default deny.** No matching capability means denied, not allowed.
* **Narrowing on delegation.** A sub-agent's capabilities must be a subset of its
  parent's; widening is rejected at write time (P2-5), not audited afterwards.
* **Deny on approval timeout.** An approval that nobody answers fails closed.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import secrets
from dataclasses import dataclass, field
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.prove.findings import auto_resolve, raise_finding
from agentfox.detection.base import taint_rank
from agentfox.core.models import (
    Agent,
    ApprovalRequest,
    Capability,
    Credential,
    DelegationEdge,
    Finding,
    Identity,
    as_aware,
    utcnow,
)
from agentfox.policy.model import COMPARATORS

_hasher = PasswordHasher()

AGENT_KEY_PREFIX = "nom_agt_"
API_KEY_PREFIX = "nom_api_"

#: A credential unused for this long is posture-flagged as stale (P2-1).
STALE_AFTER_DAYS = 30


# ---------------------------------------------------------------------------
# Identity & credentials
# ---------------------------------------------------------------------------


def ensure_identity(session: Session, agent: Agent, principal: str | None = None) -> Identity:
    principal = principal or f"agent:{agent.slug}"
    identity = session.scalar(select(Identity).where(Identity.principal == principal))
    if identity is None:
        identity = Identity(agent_id=agent.id, principal=principal, kind="agent")
        session.add(identity)
        session.flush()
    return identity


def issue_credential(
    session: Session,
    identity: Identity,
    ttl_days: int | None = 90,
    rotated_from: str | None = None,
) -> tuple[Credential, str]:
    """Issue a key. The plaintext exists only in this return value."""
    raw = AGENT_KEY_PREFIX + secrets.token_urlsafe(32).replace("-", "").replace("_", "")[:40]
    credential = Credential(
        identity_id=identity.id,
        key_prefix=raw[: len(AGENT_KEY_PREFIX) + 8],
        key_hash=_hasher.hash(raw),
        expires_at=utcnow() + dt.timedelta(days=ttl_days) if ttl_days else None,
        rotated_from_id=rotated_from,
    )
    session.add(credential)
    session.flush()
    return credential, raw


def verify_credential(session: Session, raw_key: str) -> Identity | None:
    """Resolve a presented key to its identity, or None.

    Lookup is narrowed by prefix so verification is one argon2 call in the common
    case rather than one per stored credential.
    """
    if not raw_key:
        return None
    prefix = raw_key[: len(AGENT_KEY_PREFIX) + 8]
    candidates = session.scalars(select(Credential).where(Credential.key_prefix == prefix)).all()
    for credential in candidates:
        if not credential.active:
            continue
        try:
            _hasher.verify(credential.key_hash, raw_key)
        except VerifyMismatchError:
            continue
        credential.last_used_at = utcnow()
        identity = session.get(Identity, credential.identity_id)
        if identity is None or identity.status != "active":
            return None
        identity.last_used_at = utcnow()
        session.flush()
        return identity
    return None


def rotate_credential(
    session: Session, identity: Identity, overlap_hours: int = 24
) -> tuple[Credential, str]:
    """Issue a replacement and expire the old key after an overlap window.

    Revoking immediately would mean every rotation is an outage, which is how
    rotation policies end up never being applied.
    """
    new_credential, raw = issue_credential(session, identity)
    cutoff = utcnow() + dt.timedelta(hours=overlap_hours)
    for credential in session.scalars(
        select(Credential).where(
            Credential.identity_id == identity.id,
            Credential.id != new_credential.id,
            Credential.revoked_at.is_(None),
        )
    ):
        if credential.expires_at is None or credential.expires_at > cutoff:
            credential.expires_at = cutoff
    new_credential.rotated_from_id = None
    session.flush()
    return new_credential, raw


def revoke_credential(session: Session, credential_id: str) -> bool:
    credential = session.get(Credential, credential_id)
    if credential is None:
        return False
    credential.revoked_at = utcnow()
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


#: Constraint keys that configure the grant rather than naming an argument path.
RESERVED_CONSTRAINTS = frozenset({"requires_verified_state", "dry_run_only"})


@dataclass
class CapabilityDecision:
    granted: bool = False
    requires_approval: bool = False
    matched_capability_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    constraint_violations: list[str] = field(default_factory=list)
    #: A sentence a person can read, naming the grant, the declared limit and the
    #: value that failed it. Empty unless `constraint_violations` is populated.
    constraint_reason: str = ""
    max_taint: str = "none"
    taint_violation: str | None = None
    #: The matched grant's constraints, carried forward so downstream gates (P9-7
    #: verified state) can read them without a second lookup.
    constraints: dict[str, Any] = field(default_factory=dict)

    @property
    def state(self) -> str:
        """``denied`` means *no grant exists*. A grant that exists and was exceeded
        is a different fact and gets a different name, because reporting it as
        default deny tells the caller to go and ask for a permission they already
        hold — and contradicts the grant sitting in the same response.
        """
        if not self.granted:
            return "constraint_violated" if self.constraint_violations else "denied"
        return "requires_approval" if self.requires_approval else "granted"

    def to_json(self) -> dict[str, Any]:
        return {
            "granted": self.granted,
            "requires_approval": self.requires_approval,
            "state": self.state,
            "capability_id": self.matched_capability_id,
            "reasons": self.reasons,
            "constraint_violations": self.constraint_violations,
            "constraint_reason": self.constraint_reason,
            "max_taint": self.max_taint,
            "taint_violation": self.taint_violation,
            "constraints": self.constraints,
        }


def grant_capability(
    session: Session,
    identity: Identity,
    tool_key: str,
    actions: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
    requires_approval: bool = False,
    max_taint: str = "user",
    granted_by: str = "system",
    expires_at: dt.datetime | None = None,
) -> Capability:
    capability = Capability(
        identity_id=identity.id,
        tool_key=tool_key,
        actions=actions or ["*"],
        constraints_json=constraints or {},
        requires_approval=requires_approval,
        max_taint=max_taint,
        granted_by=granted_by,
        expires_at=expires_at,
    )
    session.add(capability)
    session.flush()
    return capability


def revoke_capability(session: Session, capability_id: str) -> Capability | None:
    """Remove a grant. Returns the row that was removed, or None if there was none.

    The row is deleted rather than flagged, so a count of capabilities is a count of
    what an agent may actually do right now — the number `agentfox doctor` reports.
    The history is not lost: the caller writes the removal to the audit chain, which
    is append-only and keeps the full shape of the grant that was withdrawn.
    """
    capability = session.get(Capability, capability_id)
    if capability is None:
        return None
    session.delete(capability)
    session.flush()
    return capability


def _constraint_ok(value: Any, spec: Any) -> tuple[bool, str]:
    """``{"lt": 1000}``, ``{"in": ["USD"]}``, or a bare literal for equality."""
    if not isinstance(spec, dict):
        return (value == spec, f"expected {spec!r}, got {value!r}")
    for op, expected in spec.items():
        fn = COMPARATORS.get(op)
        if fn is None:
            return False, f"unknown constraint operator '{op}'"
        try:
            if not fn(value, expected):
                return False, f"{value!r} fails {op} {expected!r}"
        except Exception:
            return False, f"{value!r} could not be compared with {op} {expected!r}"
    return True, ""


#: How each comparator reads in a sentence a person has to act on. `lt` is not
#: "fails lt 1000" to anyone outside this file.
_LIMIT_PHRASES = {
    "lt": "below {expected}",
    "lte": "at most {expected}",
    "gt": "above {expected}",
    "gte": "at least {expected}",
    "eq": "exactly {expected}",
    "ne": "anything but {expected}",
    "in": "one of {expected}",
    "not_in": "none of {expected}",
    "contains": "text containing {expected}",
    "matches": "text matching {expected}",
}


def _describe_violation(path: str, spec: Any, value: Any) -> str:
    """One clause: what the grant allows on this argument, and what was asked for.

    Always names the limit and the value that failed it, because "constraints
    violated" tells the reader nothing they can fix.
    """
    if not isinstance(spec, dict):
        allowed = f"exactly {spec!r}"
    else:
        allowed = " and ".join(
            _LIMIT_PHRASES.get(op, f"{op} {{expected}}").format(expected=repr(expected))
            for op, expected in spec.items()
        )
    return f"{path} {allowed}, but this call passed {value!r}"


def default_deny_hint(principal: str | None, tool_key: str) -> str:
    """What to do about a default-deny refusal, in commands rather than concepts.

    Default deny is enforced from the first call — there is no observe grace — so the
    refusal itself has to say how to get out of it. The refused call is recorded with
    its arguments and provenance either way, which is what `proposals from-traffic`
    learns from.
    """
    slug = principal.split(":", 1)[1] if principal and principal.startswith("agent:") else None
    agent = slug or "<agent>"
    scoped = f" --agent {slug}" if slug else ""
    return (
        f"To have grants proposed from the calls this agent has made, run "
        f"`agentfox policy proposals from-traffic{scoped}` and approve them; to grant this one "
        f"directly, `agentfox permit grant {agent} {tool_key}`."
    )


def check_capability(
    session: Session,
    identity: Identity | None,
    tool_key: str,
    action: str = "*",
    arguments: dict[str, Any] | None = None,
    argument_taint: dict[str, str] | None = None,
) -> CapabilityDecision:
    """Evaluate least privilege for one tool call (P2-2, NOM-IAM-02).

    Default deny. Argument constraints and argument *provenance* are both checked,
    which is the agent-native part: a capability may permit ``payments.transfer``
    under 1000 USD and still refuse it when the recipient came from a tool result.
    """
    decision = CapabilityDecision()
    arguments = arguments or {}
    argument_taint = argument_taint or {}

    if identity is None:
        decision.reasons.append(
            "no resolved identity for the caller, so it holds no grants (default deny). "
            + default_deny_hint(None, tool_key)
        )
        return decision

    capabilities = session.scalars(
        select(Capability).where(Capability.identity_id == identity.id)
    ).all()
    now = utcnow()
    matches = [
        c
        for c in capabilities
        if fnmatch.fnmatch(tool_key, c.tool_key)
        # SQLite gives a naive datetime back; comparing it to `utcnow` raises, which
        # would turn every *expiring* grant into a crash at decision time.
        and (c.expires_at is None or as_aware(c.expires_at) > now)
        and ("*" in (c.actions or ["*"]) or action in (c.actions or []))
    ]
    if not matches:
        decision.reasons.append(
            f"no capability grants '{tool_key}' (action '{action}') to {identity.principal} "
            f"(default deny). {default_deny_hint(identity.principal, tool_key)}"
        )
        return decision

    # Most specific grant wins: an explicit tool key beats a glob.
    capability = sorted(matches, key=lambda c: ("*" in c.tool_key, -len(c.tool_key)))[0]
    decision.matched_capability_id = capability.id
    decision.max_taint = capability.max_taint
    decision.constraints = dict(capability.constraints_json or {})

    violation_clauses: list[str] = []
    for path, spec in (capability.constraints_json or {}).items():
        # Reserved keys configure the grant itself rather than constraining an
        # argument path; treating `requires_verified_state` as a path would look for
        # an argument by that name and fail every call.
        if path in RESERVED_CONSTRAINTS:
            continue
        value = arguments
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        ok, why = _constraint_ok(value, spec)
        if not ok:
            decision.constraint_violations.append(f"{path}: {why}")
            violation_clauses.append(_describe_violation(path, spec, value))

    if decision.constraint_violations:
        # The grant is real and the caller holds it. What failed is a declared limit
        # on an argument, so the refusal names the grant, the limit and the number.
        decision.constraint_reason = " ".join(
            [
                f"{identity.principal} holds a grant for '{capability.tool_key}', so this "
                f"is not a missing permission."
            ]
            + [f"The grant allows {clause}." for clause in violation_clauses]
        )
        decision.reasons.append(decision.constraint_reason)
        return decision

    worst = max(
        (taint_rank(str(s)) for s in argument_taint.values()),
        default=taint_rank("none"),
    )
    if worst > taint_rank(capability.max_taint):
        offending = [
            p
            for p, s in argument_taint.items()
            if taint_rank(str(s)) > taint_rank(capability.max_taint)
        ]
        decision.taint_violation = (
            f"arguments {offending} carry provenance above the capability's "
            f"max_taint '{capability.max_taint}'"
        )
        decision.granted = True
        decision.requires_approval = True
        decision.reasons.append(decision.taint_violation)
        return decision

    decision.granted = True
    decision.requires_approval = capability.requires_approval
    if decision.requires_approval:
        decision.reasons.append(f"capability '{capability.tool_key}' requires human approval")
    return decision


#: Stands in for a child glob's wildcard when testing containment. Any character
#: that cannot appear in a tool key works; the point is that `*` must not be allowed
#: to match a parent's *literal* segment, or `*` would look "covered by" `tickets.*`.
_WILDCARD_PROBE = ""


def _covers(parent: Capability, child: Capability) -> bool:
    """True when ``parent`` grants at least everything ``child`` does.

    Glob containment is undecidable in general, so this is a sound approximation:
    substituting the child's wildcard with a character the parent's literal segments
    cannot match means a broader child pattern never tests as covered. It errs
    towards rejecting a delegation, which is the correct direction for an
    authority check.
    """
    probe = child.tool_key.replace("*", _WILDCARD_PROBE)
    if not fnmatch.fnmatch(probe, parent.tool_key):
        return False

    child_actions = set(child.actions or ["*"])
    parent_actions = set(parent.actions or ["*"])
    if "*" not in parent_actions and not child_actions <= parent_actions:
        return False

    # A child may not accept more dangerous argument provenance than its parent.
    if taint_rank(child.max_taint) > taint_rank(parent.max_taint):
        return False

    # A child may not drop an approval requirement the parent imposes.
    if parent.requires_approval and not child.requires_approval:
        return False

    return True


def capability_set(session: Session, identity_id: str) -> set[tuple[str, str]]:
    caps = session.scalars(select(Capability).where(Capability.identity_id == identity_id)).all()
    out: set[tuple[str, str]] = set()
    for c in caps:
        for action in c.actions or ["*"]:
            out.add((c.tool_key, action))
    return out


def delegate(
    session: Session,
    parent: Identity,
    child: Identity,
    trace_id: str | None = None,
) -> DelegationEdge:
    """Record a delegation, rejecting any widening of authority (P2-5).

    A child capability is permitted only if some parent capability covers it — the
    child's tool pattern must be *at least as narrow* as the parent's.
    """
    parent_caps = session.scalars(
        select(Capability).where(Capability.identity_id == parent.id)
    ).all()
    child_caps = session.scalars(select(Capability).where(Capability.identity_id == child.id)).all()

    widened: list[str] = []
    for cc in child_caps:
        if not any(_covers(pc, cc) for pc in parent_caps):
            widened.append(f"{cc.tool_key}:{','.join(cc.actions or ['*'])}")

    if widened:
        raise ValueError(
            "delegation would widen authority; child holds capabilities the parent "
            f"does not: {widened}"
        )

    edge = DelegationEdge(
        parent_identity_id=parent.id,
        child_identity_id=child.id,
        capability_diff_json={
            "parent": sorted(f"{t}:{a}" for t, a in capability_set(session, parent.id)),
            "child": sorted(f"{t}:{a}" for t, a in capability_set(session, child.id)),
        },
        trace_id=trace_id,
    )
    session.add(edge)
    session.flush()
    return edge


# ---------------------------------------------------------------------------
# Human-in-the-loop approvals (P2-3)
# ---------------------------------------------------------------------------


def request_approval(
    session: Session,
    *,
    agent_id: str | None,
    tool_key: str | None,
    arguments: dict[str, Any],
    reason: str,
    trace_id: str | None = None,
    decision_id: str | None = None,
    ttl_minutes: int = 30,
    approver_role: str = "security",
) -> ApprovalRequest:
    request = ApprovalRequest(
        decision_id=decision_id,
        trace_id=trace_id,
        agent_id=agent_id,
        tool_key=tool_key,
        arguments_json=arguments,
        reason=reason,
        expires_at=utcnow() + dt.timedelta(minutes=ttl_minutes),
        approver_role=approver_role,
        timeout_action="deny",
    )
    session.add(request)
    session.flush()
    return request


def resolve_approval(
    session: Session,
    approval_id: str,
    approved: bool,
    resolver_user_id: str,
    rationale: str = "",
) -> ApprovalRequest | None:
    request = session.get(ApprovalRequest, approval_id)
    if request is None or request.status != "pending":
        return request
    expires = as_aware(request.expires_at)
    if expires and expires < utcnow():
        request.status = "expired"
        session.flush()
        return request
    request.status = "approved" if approved else "denied"
    request.resolver_user_id = resolver_user_id
    request.resolution_rationale = rationale
    session.flush()
    return request


def expire_stale_approvals(session: Session) -> int:
    """Fail closed: an unanswered approval denies (NOM-IAM-03)."""
    now = utcnow()
    stale = session.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at.is_not(None),
            ApprovalRequest.expires_at < now,
        )
    ).all()
    for request in stale:
        request.status = "expired" if request.timeout_action == "deny" else "approved"
    session.flush()
    return len(stale)


# ---------------------------------------------------------------------------
# Posture (P2-1)
# ---------------------------------------------------------------------------


#: Every finding type identity posture can raise, so a posture that changed can close
#: the finding for the posture it left.
_POSTURE_FINDING_TYPES = ("orphaned_identity", "stale_identity", "over_privileged")


def assess_posture(session: Session) -> list[Finding]:
    """Flag stale, over-privileged and orphaned identities.

    An identity graph nobody prunes is how agents accumulate the permissions that
    make a single injection catastrophic.
    """
    findings: list[Finding] = []
    cutoff = utcnow() - dt.timedelta(days=STALE_AFTER_DAYS)

    for identity in session.scalars(select(Identity)):
        posture = "healthy"
        reasons: list[str] = []

        agent = session.get(Agent, identity.agent_id) if identity.agent_id else None
        if identity.kind == "agent" and (agent is None or agent.status == "retired"):
            posture = "orphaned"
            reasons.append("no active agent owns this identity")

        last_used = identity.last_used_at
        if last_used is not None and last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=dt.UTC)
        if posture == "healthy" and (last_used is None or last_used < cutoff):
            posture = "stale"
            reasons.append(f"unused for more than {STALE_AFTER_DAYS} days")

        caps = session.scalars(
            select(Capability).where(Capability.identity_id == identity.id)
        ).all()
        wildcards = [c for c in caps if c.tool_key.strip() == "*"]
        if wildcards:
            posture = "over_privileged"
            reasons.append("holds an unrestricted '*' tool grant")

        identity.posture = posture
        current_type = (
            None
            if posture == "healthy"
            else (f"{posture}_identity" if posture != "over_privileged" else "over_privileged")
        )
        # A posture that no longer holds closes its finding: an identity that was stale
        # and has since been used is not stale, whatever the queue still says.
        for posture_type in _POSTURE_FINDING_TYPES:
            if posture_type != current_type:
                auto_resolve(
                    session,
                    type=posture_type,
                    subject_type="identity",
                    subject_id=identity.id,
                    note=f"identity {identity.principal} is now {posture}",
                )
        if posture != "healthy":
            finding, _ = raise_finding(
                session,
                type=current_type,
                severity="high" if posture == "over_privileged" else "medium",
                title=f"Identity {identity.principal} is {posture}",
                subject_type="identity",
                subject_id=identity.id,
                evidence={"reasons": reasons, "capabilities": len(caps)},
                control_keys=["NOM-IAM-01", "NOM-IAM-02"],
            )
            findings.append(finding)
    session.flush()
    return findings
