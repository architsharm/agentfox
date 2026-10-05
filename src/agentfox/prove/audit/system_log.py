"""The system-level chain — for operator actions that belong to no tenant.

`operator_log.py`'s own docstring names the piece it deliberately did not build:
`tenancy.system_scope` lifts tenant isolation, so by construction it "has no tenant
whose chain it could be written to". Most `system_scope` uses don't actually have
this problem — resolving a credential ends by binding the session to the tenant it
turned out to belong to, so whatever runs next records into that tenant's own chain,
correctly attributed, no different from any other governed action. That covers
issuing and revoking an operator token: both already know the affected user's
`org_id` before they mint or revoke anything.

What's left is the operation that never resolves to one tenant at all — listing
every token issued across every org is the one concrete example in this codebase
today, and schema migration or whole-log verification would be others if they used
this mechanism. Recording that into whichever tenant the session happened to be
bound to (usually the deployment default, by accident of never being bound to
anything) is exactly the "fake it" `operator_log.py` warned against: it would
misattribute a genuinely cross-tenant read to one arbitrary tenant's history.

This module is the missing chain, not a new storage mechanism: the same
hash-chained `AuditEntry` table `audit.chain` already writes every tenant's
decisions into, reserved under one sentinel `org_id` no real tenant can hold. It
reuses `chain.append`'s own `org_id` override (added alongside this module — see
its docstring) rather than inventing a second append path, which is what keeps this
chain independently hash-verifiable the exact same way every tenant's chain
already is: same digest scheme, same `verify()`, same checkpoint mechanism.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import AuditEntry
from agentfox.core.tenancy import in_system_scope
from agentfox.prove.audit import chain
from agentfox.prove.audit.operator_log import ReasonRequired

#: Reserved. `TenantScoped.org_id` defaults to `"org_default"` and every other value
#: in this codebase comes from deployment config or an authenticated user's own
#: `org_id` — nothing ever sets one to this literal, so entries filed under it can
#: never be confused with, or dilute, a real tenant's chain.
SYSTEM_ORG_ID = "__system__"


class NotInSystemScope(RuntimeError):
    """Raised when a system-chain entry is attempted outside `tenancy.system_scope()`.

    The system chain exists specifically for operations that have already
    deliberately lifted tenant isolation. Recording to it from ordinary request
    handling would be a tenant-isolation bypass wearing an audit trail as cover, not
    a feature — refused rather than silently allowed.
    """


def record(
    session: Session,
    action: str,
    *,
    actor: str,
    reason: str,
    subject_type: str = "",
    subject_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> AuditEntry:
    """Write one entry into the system chain.

    Mirrors `operator_log.record`'s contract (namespaced action, a reason that
    cannot be blank) rather than inventing a second one — the two differ only in
    which chain they write to and why: an operator action always has a tenant to
    attribute to, a system action by definition does not.
    """
    if not in_system_scope():
        raise NotInSystemScope(
            f"'{action}' can only be recorded while tenancy.system_scope() is active "
            "— the system chain is reserved for operations that have already "
            "deliberately lifted tenant isolation, not a general-purpose escape hatch."
        )
    if not action.startswith("system."):
        raise ValueError(f"system actions are namespaced 'system.*', got {action!r}")
    if not (reason or "").strip():
        raise ReasonRequired(
            f"'{action}' is a cross-tenant action and needs a stated reason, the same "
            "as every other operator action."
        )

    return chain.append(
        session,
        action,
        actor_type="operator",
        actor_id=actor,
        subject_type=subject_type,
        subject_id=subject_id,
        payload={"reason": reason.strip(), **(extra or {})},
        org_id=SYSTEM_ORG_ID,
    )


def system_history(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    """Everything recorded to the system chain, newest first.

    Requires `system_scope` for the same reason `record` does: reading this chain
    means reading past the loader-criteria filter that would otherwise hide it
    behind whichever tenant the session happens to be bound to.
    """
    if not in_system_scope():
        raise NotInSystemScope(
            "reading the system chain requires tenancy.system_scope() — otherwise "
            "the ordinary tenant filter hides every row in it."
        )
    rows = session.scalars(
        select(AuditEntry)
        .where(AuditEntry.org_id == SYSTEM_ORG_ID)
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
        }
        for row in rows
    ]


__all__ = ["SYSTEM_ORG_ID", "NotInSystemScope", "record", "system_history"]
