"""spare playground sandboxes

Adds `playground_sandboxes.spare`: a sandbox built ahead of time and not yet handed to
a visitor, so creating one is an UPDATE instead of a few hundred seeding statements.

Re-runnable: `init_db()` adds this column at startup on an existing database (see
`_ADDITIVE_COLUMNS`), so the column may already be there.

Revision ID: c6e1a4b8d257
Revises: b5d9e3f7a412
Create Date: 2026-10-10 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6e1a4b8d257"
down_revision: str | None = "b5d9e3f7a412"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("playground_sandboxes")}


def upgrade() -> None:
    if "spare" not in _columns():
        op.add_column(
            "playground_sandboxes",
            sa.Column("spare", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("playground_sandboxes")}
    if "ix_playground_sandboxes_spare" not in indexes:
        op.create_index("ix_playground_sandboxes_spare", "playground_sandboxes", ["spare"])


def downgrade() -> None:
    op.drop_index("ix_playground_sandboxes_spare", table_name="playground_sandboxes")
    op.drop_column("playground_sandboxes", "spare")
