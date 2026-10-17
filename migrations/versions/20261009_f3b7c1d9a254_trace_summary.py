"""a run keeps a short, redacted preview of what the user asked

Adds `traces.summary` (nullable VARCHAR(200)): the latest user message of the run, with
personal data and secrets masked, so the runs list can say what was asked instead of
"User message · Agent reply". NULL for runs recorded before, and for runs with no user
message (tool-only runs).

Re-runnable: the column is added only if it is missing, because `init_db()` adds it
too (`_ADDITIVE_COLUMNS`), so a deployment can run new code before this migration.

Revision ID: f3b7c1d9a254
Revises: e2a6c4f8b131
Create Date: 2026-10-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b7c1d9a254"
down_revision: str | None = "e2a6c4f8b131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("traces", "summary"):
        with op.batch_alter_table("traces") as batch_op:
            batch_op.add_column(sa.Column("summary", sa.String(200), nullable=True))


def downgrade() -> None:
    if _has_column("traces", "summary"):
        with op.batch_alter_table("traces") as batch_op:
            batch_op.drop_column("summary")
