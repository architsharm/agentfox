"""per-tenant audit chain

Tenant isolation made a single global hash chain untenable: verifying tenant A's chain
would require reading tenant B's entries, and A's evidence package would carry B's
digests. `seq` therefore becomes unique per (org_id, seq) and each tenant owns a chain
starting at 1.

Existing single-tenant deployments are unaffected — every row already carries
`org_default`, so the existing chain simply becomes that tenant's chain, unchanged and
still verifiable.

Revision ID: 00da42ce9385
Revises: 5aeb5ff1a175
Create Date: 2026-08-19 11:39:21.427998
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '00da42ce9385'
down_revision: str | None = '5aeb5ff1a175'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('audit_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_entries_seq'))
        batch_op.create_index(batch_op.f('ix_audit_entries_seq'), ['seq'], unique=False)
        batch_op.create_unique_constraint('uq_audit_org_seq', ['org_id', 'seq'])



def downgrade() -> None:
    with op.batch_alter_table('audit_entries', schema=None) as batch_op:
        batch_op.drop_constraint('uq_audit_org_seq', type_='unique')
        batch_op.drop_index(batch_op.f('ix_audit_entries_seq'))
        batch_op.create_index(batch_op.f('ix_audit_entries_seq'), ['seq'], unique=1)

