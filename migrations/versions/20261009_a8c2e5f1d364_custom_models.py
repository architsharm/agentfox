"""a workspace's own classifier models, called over HTTP as a detector

Adds the tenant-scoped `custom_models` table: a classifier endpoint a customer runs
themselves (a fine-tuned or RL-trained model), registered from the Checks screen. The
`custom.models` detector posts text to it and reports labels above its threshold as
detections. `auth_secret_encrypted` holds an optional credential, encrypted with
`core.crypto` like every other stored secret.

Re-runnable: the table is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: a8c2e5f1d364
Revises: f3b7c1d9a254
Create Date: 2026-10-09 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8c2e5f1d364"
down_revision: str | None = "f3b7c1d9a254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("custom_models"):
        return
    op.create_table(
        "custom_models",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("surfaces_json", sa.JSON(), nullable=False),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("entity_prefix", sa.String(length=32), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("fail_mode", sa.String(length=8), nullable=False),
        sa.Column("auth_header", sa.String(length=100), nullable=False),
        sa.Column("auth_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "key", name="ux_custom_models_org_key"),
    )
    op.create_index("ix_custom_models_key", "custom_models", ["key"])
    op.create_index("ix_custom_models_org_id", "custom_models", ["org_id"])


def downgrade() -> None:
    if _has_table("custom_models"):
        op.drop_table("custom_models")
