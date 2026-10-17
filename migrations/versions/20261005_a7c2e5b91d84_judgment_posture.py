"""an admin's judgment posture is a tenant's row, not the process's environment

Adds `judgment_posture`: which judgment tiers a tenant has turned on, what happens to
personal data on the way to a remote one, and whether an outage fails closed.

Until now every one of those was an environment variable. That is the right home for
*whether this deployment may talk to a third party at all* — a decision the person who
runs the process makes and accepts the risk for. It is the wrong home for *whether we
want it on today*, which is a governance decision an admin makes, repeatedly, and which
an auditor later asks to see the history of. An environment variable has no history, no
author and no reason attached, and changing one needs a deploy, so in practice the
answer to "who turned remote judgment on in March" was nobody and no record.

Why a table rather than more settings: `get_settings()` is `lru_cache`'d and
process-global. Making it writable from a request would let one tenant's egress choice
change another tenant's behaviour in the same process, which is the one class of bug
this schema's tenancy rules exist to make impossible. So posture is tenant-scoped like
everything else, and the deployment setting becomes a *ceiling* over it: a row here may
narrow what the deployment permits and may never widen it. `judgment/posture.py`
enforces that on write and clamps it again on read, so a deployment that revokes egress
retroactively narrows every row that was written while it was allowed.

`UNIQUE (org_id)` is the singleton: a tenant has one posture, not a list of them. The
database enforces it rather than the application, because two concurrent writes from
two admins on the same settings page is an ordinary afternoon.

`version` is bumped on every write for the same reason policy and business rules carry
one — an auditor asking what left the building in March needs the posture in force in
March. The row holds only the current value; the audit chain holds the history, under
`operator.judgment_posture.changed` with the before/after pair.

Nothing here turns anything on. A fresh deployment has no row, which means settings
apply exactly as they did before this revision, which is what keeps the published
benchmark numbers comparable.

Re-runnable: every object is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: a7c2e5b91d84
Revises: f1b9c3d47a02
Create Date: 2026-10-05 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c2e5b91d84"
down_revision: str | None = "f1b9c3d47a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def _has_index(table: str, index: str) -> bool:
    return any(i["name"] == index for i in _inspector().get_indexes(table))


def _has_unique(table: str, name: str) -> bool:
    return any(c["name"] == name for c in _inspector().get_unique_constraints(table))


def upgrade() -> None:
    if not _has_table("judgment_posture"):
        op.create_table(
            "judgment_posture",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            # Tier names, not a bitmask: a posture read out of the database by hand
            # during an incident should say "jev" rather than 12.
            sa.Column("tiers", sa.JSON(), nullable=False),
            sa.Column("pii_egress", sa.String(length=16), nullable=False),
            sa.Column("fail_closed", sa.Boolean(), nullable=False),
            sa.Column("backend", sa.String(length=16), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            # One posture per tenant, enforced here rather than in the application,
            # because two admins saving the same settings page at once is ordinary.
            sa.UniqueConstraint("org_id", name="uq_judgment_posture_org"),
        )

    with op.batch_alter_table("judgment_posture", schema=None) as batch_op:
        if not _has_index("judgment_posture", "ix_judgment_posture_org_id"):
            batch_op.create_index("ix_judgment_posture_org_id", ["org_id"], unique=False)


def downgrade() -> None:
    if _has_index("judgment_posture", "ix_judgment_posture_org_id"):
        with op.batch_alter_table("judgment_posture", schema=None) as batch_op:
            batch_op.drop_index("ix_judgment_posture_org_id")
    op.drop_table("judgment_posture")
