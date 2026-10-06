"""PL-10 — the system-level chain.

`operator_log.py` already made the operator's own actions auditable. The piece its
own docstring named and left unbuilt was `tenancy.system_scope`: a cross-tenant
operation that resolves to no single tenant has nowhere honest to record itself.
`system_log.py` is that missing chain, and these tests are about the two ways it
could quietly fail: recording outside `system_scope` (a tenant-isolation bypass
wearing an audit trail as cover), and recording into the wrong chain entirely (the
bug `chain.append`'s `org_id` parameter exists to fix — covered end-to-end here via
`auth_cli.tokens`, the one real call site this module is wired into).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import AuditEntry, User
from agentfox.core.tenancy import system_scope, tenant
from agentfox.platform.ledger.operator_log import ReasonRequired
from agentfox.platform.ledger.system_log import (
    SYSTEM_ORG_ID,
    NotInSystemScope,
    record,
    system_history,
)

ACME, GLOBEX = "org_acme", "org_globex"


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_recording_outside_system_scope_is_refused(isolated_db):
    """The system chain is reserved for operations that already lifted tenant
    isolation deliberately — not a general-purpose escape hatch for anyone who
    forgot to bind a session."""
    with session_scope() as session:
        with pytest.raises(NotInSystemScope):
            record(session, "system.tokens.listed", actor="cli", reason="because")


def test_reading_the_system_chain_outside_system_scope_is_refused(isolated_db):
    with session_scope() as session:
        with pytest.raises(NotInSystemScope):
            system_history(session)


def test_a_blank_reason_is_refused(isolated_db):
    with system_scope("test"), session_scope() as session:
        with pytest.raises(ReasonRequired):
            record(session, "system.tokens.listed", actor="cli", reason="   ")


def test_system_actions_must_be_namespaced(isolated_db):
    with system_scope("test"), session_scope() as session:
        with pytest.raises(ValueError, match="namespaced"):
            record(session, "tokens.listed", actor="cli", reason="because")


# ---------------------------------------------------------------------------
# The chain itself
# ---------------------------------------------------------------------------


def test_a_system_entry_lands_under_the_reserved_org_id(isolated_db):
    with system_scope("test"), session_scope() as session:
        entry = record(session, "system.tokens.listed", actor="cli", reason="audit sweep")
    assert entry.org_id == SYSTEM_ORG_ID
    assert entry.actor_type == "operator"
    assert entry.payload_json["reason"] == "audit sweep"


def test_the_system_chain_is_independently_verifiable(isolated_db):
    """Same guarantee every tenant's chain already has: a pure function over exported
    rows, no access to any tenant's own data required."""
    from agentfox.platform.ledger import chain

    with system_scope("test"), session_scope() as session:
        for i in range(3):
            record(session, "system.tokens.listed", actor="cli", reason=f"sweep {i}")

    with system_scope("verify"), session_scope() as session:
        entries = session.scalars(
            select(AuditEntry).where(AuditEntry.org_id == SYSTEM_ORG_ID)
        ).all()
        result = chain.verify([chain.entry_to_row(e) for e in entries], expect_genesis=True)
    assert result.valid
    assert result.entries_checked == 3


def test_a_real_tenants_chain_never_absorbs_a_system_entry(isolated_db):
    """The sentinel org id must not collide with, or leak into, any real tenant's
    own chain — the whole reason a reserved value was picked over reusing whatever
    the session happened to default to."""
    from agentfox.platform.ledger import chain

    with tenant(ACME), session_scope() as session:
        chain.append(session, action="a.decision", subject_type="t", subject_id="1", payload={})
    with system_scope("test"), session_scope() as session:
        record(session, "system.tokens.listed", actor="cli", reason="sweep")

    with tenant(ACME), session_scope() as session:
        acme_entries = session.scalars(select(AuditEntry)).all()
    assert len(acme_entries) == 1
    assert acme_entries[0].action == "a.decision"


def test_system_history_reads_newest_first(isolated_db):
    with system_scope("test"), session_scope() as session:
        record(session, "system.tokens.listed", actor="cli", reason="first")
        record(session, "system.tokens.listed", actor="cli", reason="second")
        history = system_history(session)
    assert history[0]["reason"] == "second"
    assert history[1]["reason"] == "first"


# ---------------------------------------------------------------------------
# End-to-end through the live CLI call site
# ---------------------------------------------------------------------------


def test_listing_tokens_via_the_cli_records_to_the_system_chain(isolated_db):
    """The one real call site this module is wired into: `agentfox auth tokens` is a
    read across every tenant, with no single tenant to attribute it to."""
    from agentfox.cli.auth_cli import tokens as cli_tokens

    with tenant(ACME), session_scope() as session:
        session.add(User(email="a@acme.example", name="A", role="admin", active=True))
    with tenant(GLOBEX), session_scope() as session:
        session.add(User(email="b@globex.example", name="B", role="admin", active=True))

    cli_tokens(as_json=True)

    with system_scope("verify"), session_scope() as session:
        history = system_history(session)
    entry = next(h for h in history if h["action"] == "system.tokens.listed")
    assert entry["reason"] == "listing operator tokens"


def test_issuing_a_token_for_a_non_default_org_lands_in_that_orgs_own_chain(isolated_db):
    """Regression: `agentfox auth issue` runs the recipient lookup inside
    `system_scope` and, before this fix, never bound the session to the recipient's
    own tenant before minting — so the resulting `operator.credential.issued` entry
    was attributed to whichever tenant the session defaulted to (never `org_other`
    here), and its `seq` was computed from a query `system_scope` had left
    unfiltered across every tenant. Binding the session as soon as the recipient is
    known fixes both."""
    from agentfox.cli.auth_cli import issue as cli_issue

    with tenant("org_other"), session_scope() as session:
        session.add(User(email="ops@other.example", name="Ops", role="admin", active=True))

    cli_issue(email="ops@other.example", name="ci", days=30)

    with tenant("org_other"), session_scope() as session:
        entries = session.scalars(
            select(AuditEntry).where(AuditEntry.action == "operator.credential.issued")
        ).all()
    assert len(entries) == 1
    assert entries[0].org_id == "org_other"
    assert entries[0].seq == 1


def test_revoking_a_token_records_into_its_own_orgs_chain(isolated_db):
    from agentfox.cli.auth_cli import issue as cli_issue
    from agentfox.cli.auth_cli import revoke as cli_revoke
    from agentfox.core.models import ApiToken

    with tenant("org_other"), session_scope() as session:
        session.add(User(email="ops2@other.example", name="Ops2", role="admin", active=True))
    cli_issue(email="ops2@other.example", name="ci", days=30)

    with tenant("org_other"), session_scope() as session:
        token_id = session.scalars(select(ApiToken)).one().id

    cli_revoke(token_id=token_id)

    with tenant("org_other"), session_scope() as session:
        entries = session.scalars(
            select(AuditEntry).where(AuditEntry.action == "operator.credential.revoked")
        ).all()
    assert len(entries) == 1
    assert entries[0].org_id == "org_other"
