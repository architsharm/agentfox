"""first-run onboarding, one row per user

Adds the tenant-scoped `onboarding_sessions` table: a user's progress through the
five onboarding steps, the map `agentfox init --key` reported, the guardrails they
picked, and their before/after test runs. `init_key` is the key that command
presents; it can only report a map and test results for this one row.

Re-runnable: the table is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: b5d2e8f4a617
Revises: a7d3e9c2f518
Create Date: 2026-10-16 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5d2e8f4a617"
down_revision: str | None = "a7d3e9c2f518"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("onboarding_sessions"):
        return
    op.create_table(
        "onboarding_sessions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("init_key", sa.String(length=64), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("structure", sa.JSON(), nullable=True),
        sa.Column("structure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runner_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guardrails", sa.JSON(), nullable=True),
        sa.Column("runs", sa.JSON(), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_onboarding_sessions_user_id", "onboarding_sessions", ["user_id"], unique=True)
    op.create_index("ix_onboarding_sessions_init_key", "onboarding_sessions", ["init_key"], unique=True)
    op.create_index("ix_onboarding_sessions_org_id", "onboarding_sessions", ["org_id"])


def downgrade() -> None:
    if _has_table("onboarding_sessions"):
        op.drop_table("onboarding_sessions")
