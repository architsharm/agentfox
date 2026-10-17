"""a project switching a detector on or off over the workspace's choice

Adds the tenant-scoped `agent_detector_settings` table: one row per project and
detector it changed. No row means the project runs what the workspace runs, so
every existing project behaves exactly as before.

Re-runnable: the table is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: a4d2f8c6e317
Revises: f7c3d9a2e815
Create Date: 2026-10-16 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d2f8c6e317"
down_revision: str | None = "f7c3d9a2e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("agent_detector_settings"):
        return
    op.create_table(
        "agent_detector_settings",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("agent", sa.String(length=200), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "agent", "key", name="ux_agent_detector_settings_org_agent_key"
        ),
    )
    op.create_index("ix_agent_detector_settings_agent", "agent_detector_settings", ["agent"])
    op.create_index("ix_agent_detector_settings_key", "agent_detector_settings", ["key"])
    op.create_index("ix_agent_detector_settings_org_id", "agent_detector_settings", ["org_id"])


def downgrade() -> None:
    if _has_table("agent_detector_settings"):
        op.drop_table("agent_detector_settings")
