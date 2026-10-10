"""the customer's own access-control service, asked before a tool call runs

Adds the tenant-scoped `external_authorizers` table: an HTTP endpoint (the customer's
RBAC service, an OPA or Cedar server) that decides whether the end user an agent acts
for may make a tool call. `auth_secret_encrypted` holds an optional credential,
encrypted with `core.crypto` like every other stored secret.

Re-runnable: the table is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: f7c3d9a2e815
Revises: e2a8c5f1b964
Create Date: 2026-10-11 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7c3d9a2e815"
down_revision: str | None = "e2a8c5f1b964"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("external_authorizers"):
        return
    op.create_table(
        "external_authorizers",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("tools_json", sa.JSON(), nullable=False),
        sa.Column("agents_json", sa.JSON(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("fail_mode", sa.String(length=8), nullable=False),
        sa.Column("on_deny", sa.String(length=12), nullable=False),
        sa.Column("require_principal", sa.Boolean(), nullable=False),
        sa.Column("cache_seconds", sa.Integer(), nullable=False),
        sa.Column("auth_header", sa.String(length=100), nullable=False),
        sa.Column("auth_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "key", name="ux_external_authorizers_org_key"),
    )
    op.create_index("ix_external_authorizers_key", "external_authorizers", ["key"])
    op.create_index("ix_external_authorizers_org_id", "external_authorizers", ["org_id"])


def downgrade() -> None:
    if _has_table("external_authorizers"):
        op.drop_table("external_authorizers")
