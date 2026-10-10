"""agent circuit breaker

Adds `agent_controls.breaker_json`: an agent's circuit breaker settings and state, so
an agent whose calls start failing its checks in a burst is paused (or flagged) without
someone watching, and resumes on its own once a few calls pass.

Re-runnable: `init_db()` adds this column at startup on an existing database (see
`_ADDITIVE_COLUMNS`), so the column may already be there.

Revision ID: e2a8c5f1b964
Revises: c6e1a4b8d257
Create Date: 2026-10-11 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a8c5f1b964"
down_revision: str | None = "c6e1a4b8d257"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("agent_controls")}
    if "breaker_json" not in columns:
        op.add_column("agent_controls", sa.Column("breaker_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_controls", "breaker_json")
