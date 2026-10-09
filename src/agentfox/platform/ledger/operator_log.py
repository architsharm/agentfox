"""The governance layer, governed.

Every control in this system watches the agent. Nothing watches the operator, and the
operator is the one who can turn the controls off.

That asymmetry is not a theoretical concern. `apply_suppression` silences a detector;
an unaudited version of it means the audit log can be defeated by switching off the
thing that would have written to it. `system_scope` lifts tenant isolation, which is
the strongest guarantee this product makes. Issuing a token mints an identity. Changing
a business rule's mode moves it from observe to enforce, or back. Each of those is a
larger act than anything an agent can do at runtime, and each must leave a row.

The mechanism is deliberately the same hash-chained per-tenant log the agent decisions
go into, rather than a separate operator log. A separate log is a log an operator can
be given permission to clear; the same chain means removing an operator action breaks
the digest over every decision that followed it.

Two things make this hold rather than merely exist:

**The registry is declared, and the check is structural.** `PRIVILEGED` names each
operation that must be recorded. `unaudited()` reads the source of those functions and
reports any that do not record, so a new operator surface added without an audit call
fails the test suite rather than being discovered during an incident. This mirrors the
import-time assertion that keeps mapped classes tenant-scoped — the same reasoning, one
layer up.

**A reason is required, not optional.** Every one of these actions is legitimate
sometimes; what an investigation needs is not that it happened but why someone thought
it should. A field that can be left blank is a field that is blank exactly when it
matters, so the recorder refuses the call rather than accepting an empty string.

One privileged operation is deliberately **not** in the registry, and the reason is
structural rather than an oversight. `tenancy.system_scope` lifts tenant isolation, so
by construction it has no tenant whose chain it could be written to — every chain here
belongs to exactly one org, which is what makes them independently verifiable. It logs
at warning level with its stated reason and is greppable, and that is weaker than a
chained entry. Recording cross-tenant operations properly needs a separate
system-level chain, which is a real piece of design and not one to fake by writing the
entry into whichever tenant happened to be bound at the time.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from agentfox.platform.ledger import chain

# --- What counts as an operator action -------------------------------------


@dataclass(frozen=True)
class PrivilegedAction:
    """One operation that must not happen unrecorded."""

    #: Dotted path of the function that performs it.
    target: str
    #: The `action` string it records under.
    action: str
    #: Why this one matters, in the terms an auditor would ask about.
    why: str


PRIVILEGED: tuple[PrivilegedAction, ...] = (
    PrivilegedAction(
        "agentfox.capabilities.detection.tuning.apply_suppression",
        "operator.guardrail.suppressed",
        "silences a detector — the one action that can hide every other action",
    ),
    PrivilegedAction(
        "agentfox.capabilities.detection.tuning.revoke_suppression",
        "operator.guardrail.unsuppressed",
        "restores a detector; the pair has to be reconstructable to know what was "
        "unwatched and for how long",
    ),
    PrivilegedAction(
        "agentfox.capabilities.business.store.save_ladder",
        "operator.business_rule.changed",
        "changes the thresholds that decide what is auto-approved",
    ),
    PrivilegedAction(
        "agentfox.capabilities.business.store.delete_ladder",
        "operator.business_rule.deleted",
        "removes a threshold rule — what it held for approval goes through unchecked",
    ),
    PrivilegedAction(
        "agentfox.capabilities.business.store.set_mode",
        "operator.business_rule.mode_changed",
        "moves a rule between observe and enforce — the same rule, opposite effect",
    ),
    PrivilegedAction(
        "agentfox.platform.identity.operators.issue_token",
        "operator.credential.issued",
        "mints an identity that can act through the gateway",
    ),
    PrivilegedAction(
        "agentfox.platform.identity.operators.create_operator",
        "operator.user.created",
        "creates a person who can be issued credentials — for the first operator of a "
        "self-hosted deployment, the root of every later grant",
    ),
    PrivilegedAction(
        "agentfox.platform.identity.operators.revoke_token",
        "operator.credential.revoked",
        "ends an identity; the gap between issue and revoke is the exposure window",
    ),
    PrivilegedAction(
        "agentfox.capabilities.improvement.proposals.decide",
        "operator.proposal.decided",
        "approves or rejects a change to the governance configuration; for an org-level "
        "loosening, one of the two named people who let a control be weakened",
    ),
    PrivilegedAction(
        "agentfox.capabilities.improvement.proposals.apply_proposal",
        "operator.proposal.applied",
        "changes live configuration — possibly with nobody deciding, which is exactly "
        "when the record of who (or what) did it matters most",
    ),
    PrivilegedAction(
        "agentfox.capabilities.improvement.proposals.rollback_proposal",
        "operator.proposal.rolled_back",
        "undoes a change; reverting a tightening loosens a control again",
    ),
    PrivilegedAction(
        "agentfox.capabilities.detection.custom_store.save_rules",
        "operator.custom_rule.saved",
        "adds or changes a rule that can block, mask or hold traffic",
    ),
    PrivilegedAction(
        "agentfox.capabilities.detection.custom_store.delete_rule",
        "operator.custom_rule.deleted",
        "removes a rule — the protection it gave stops with it",
    ),
    PrivilegedAction(
        "agentfox.capabilities.workspace.apply",
        "operator.workspace.applied",
        "one file can change every policy's rules and modes at once",
    ),
    PrivilegedAction(
        "agentfox.capabilities.protection.save",
        "operator.agent_protection.saved",
        "switching an agent's protection off or down removes rules that guarded it",
    ),
    PrivilegedAction(
        "agentfox.capabilities.protection.scope.apply_for_agents",
        "operator.agent_rule.changed",
        "changes a workspace rule for some agents only; where the rule allows it, that "
        "can loosen it for them",
    ),
    PrivilegedAction(
        "agentfox.capabilities.protection.scope.reset_for_agent",
        "operator.agent_rule.reset",
        "removes an agent's own copy of a rule, which can loosen what it was held to",
    ),
    PrivilegedAction(
        "agentfox.capabilities.detection.detector_settings.set_enabled",
        "operator.detector.toggled",
        "switching a detector off silences it for the whole workspace, like a suppression",
    ),
    PrivilegedAction(
        "agentfox.capabilities.detection.custom_models.save_model",
        "operator.custom_model.saved",
        "registers or changes a model that customer content is sent to, and whose "
        "answers can block, mask or hold traffic",
    ),
    PrivilegedAction(
        "agentfox.capabilities.detection.custom_models.set_model_enabled",
        "operator.custom_model.toggled",
        "switching a model off silences every rule that acted on it",
    ),
    PrivilegedAction(
        "agentfox.capabilities.detection.custom_models.delete_model",
        "operator.custom_model.deleted",
        "removes a model — the protection it gave stops with it",
    ),
    PrivilegedAction(
        "agentfox.capabilities.judgment.posture.save",
        "operator.judgment_posture.changed",
        "decides whether customer payloads leave this machine for a third party — "
        "the one configuration change whose consequence is invisible from the screen "
        "that makes it",
    ),
)

#: Call expressions that count as recording. `record` is the front door; a direct
#: `chain.append` is accepted because several routes already write richer entries and
#: rewriting them to go through here would be churn with no gain.
_RECORDING_CALLS = ("record(", "chain.append(", "operator_log.record(")


def unaudited() -> list[str]:
    """Declared privileged operations whose implementation does not record.

    Source inspection rather than runtime interception, because the failure being
    guarded against is a *new* surface written without an audit call — which a runtime
    check only catches once someone exercises it in production.
    """
    import importlib

    missing: list[str] = []
    for entry in PRIVILEGED:
        module_path, _, function_name = entry.target.rpartition(".")
        try:
            module = importlib.import_module(module_path)
            function = getattr(module, function_name)
            source = inspect.getsource(function)
        except Exception:  # pragma: no cover - a missing target is itself a failure
            missing.append(f"{entry.target} (not importable)")
            continue
        if not any(call in source for call in _RECORDING_CALLS):
            missing.append(entry.target)
    return missing


# --- Recording -------------------------------------------------------------


class ReasonRequired(ValueError):
    """Raised when a privileged action is attempted without a stated reason.

    Deliberately an exception rather than a default. Every one of these actions is
    legitimate sometimes, and what an investigation needs is not that it happened but
    why someone thought it should — so a blank reason has to fail loudly at the point
    of the change, when the person still knows the answer.
    """


def record(
    session: Session,
    action: str,
    *,
    actor: str,
    reason: str,
    subject_type: str = "",
    subject_id: str | None = None,
    before: Any = None,
    after: Any = None,
    extra: dict[str, Any] | None = None,
) -> Any:
    """Write one operator action into the same chain as the agent decisions.

    ``before`` and ``after`` are recorded when the action changes a value, because
    "the threshold was changed" answers nothing an investigation asks. They are passed
    through the chain's own redaction, so recording a credential change does not
    record the credential.
    """
    if not action.startswith("operator."):
        raise ValueError(f"operator actions are namespaced 'operator.*', got {action!r}")
    if not (reason or "").strip():
        raise ReasonRequired(
            f"'{action}' changes how the system governs itself and needs a stated "
            "reason. A field that can be left blank is blank exactly when it matters."
        )

    payload: dict[str, Any] = {"reason": reason.strip(), **(extra or {})}
    if before is not None:
        payload["before"] = before
    if after is not None:
        payload["after"] = after

    return chain.append(
        session,
        action,
        actor_type="operator",
        actor_id=actor,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    )


def operator_history(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    """Everything an operator did, newest first.

    Reads from the shared chain rather than a separate table: a separate operator log
    is a log someone can be given permission to clear, whereas removing a row here
    breaks the digest over every decision recorded after it.
    """
    from sqlalchemy import select

    from agentfox.core.models import AuditEntry

    rows = session.scalars(
        select(AuditEntry)
        .where(AuditEntry.actor_type == "operator")
        .order_by(AuditEntry.seq.desc())
        .limit(limit)
    ).all()
    return [
        {
            "seq": row.seq,
            "at": row.occurred_at.isoformat(),
            "actor": row.actor_id,
            "action": row.action,
            "subject": f"{row.subject_type}:{row.subject_id}" if row.subject_id else "",
            "reason": (row.payload_json or {}).get("reason", ""),
            "before": (row.payload_json or {}).get("before"),
            "after": (row.payload_json or {}).get("after"),
        }
        for row in rows
    ]
