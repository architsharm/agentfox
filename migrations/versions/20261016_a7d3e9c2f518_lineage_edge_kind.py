"""how a delegation edge read from code hands work over

Adds `lineage_edges.kind`: for a `delegates_to` edge a repository scan read from code,
how the parent hands work to the child (handoff, as_tool, delegates or member, see
`discovery.agents.RELATIONS`). NULL for an edge only ever seen in traffic.

Re-runnable: `init_db()` adds this column at startup on an existing database (see
`_ADDITIVE_COLUMNS`), so the column may already be there.

Revision ID: a7d3e9c2f518
Revises: f7c3d9a2e815
Create Date: 2026-10-16 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d3e9c2f518"
down_revision: str | None = "f7c3d9a2e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("lineage_edges")
    return any(c["name"] == "kind" for c in columns)


def upgrade() -> None:
    if not _has_column():
        with op.batch_alter_table("lineage_edges") as batch_op:
            batch_op.add_column(sa.Column("kind", sa.String(length=32), nullable=True))


def downgrade() -> None:
    if _has_column():
        with op.batch_alter_table("lineage_edges") as batch_op:
            batch_op.drop_column("kind")
