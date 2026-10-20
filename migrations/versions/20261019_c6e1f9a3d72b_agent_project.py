"""an agent belongs to a project

Adds `agents.project`: the repository `agentfox init` mapped the agent from. The map
shows one project at a time. NULL for an agent registered any other way, which the
dashboard groups under the default project.

Re-runnable: `init_db()` adds this column at startup on an existing database (see
`_ADDITIVE_COLUMNS`), so the column may already be there.

Revision ID: c6e1f9a3d72b
Revises: b5d2e8f4a617
Create Date: 2026-10-19 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6e1f9a3d72b"
down_revision: str | None = "b5d2e8f4a617"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("agents")
    return any(c["name"] == "project" for c in columns)


def upgrade() -> None:
    if not _has_column():
        with op.batch_alter_table("agents") as batch_op:
            batch_op.add_column(sa.Column("project", sa.String(length=120), nullable=True))
            batch_op.create_index("ix_agents_project", ["project"])


def downgrade() -> None:
    if _has_column():
        with op.batch_alter_table("agents") as batch_op:
            batch_op.drop_index("ix_agents_project")
            batch_op.drop_column("project")
