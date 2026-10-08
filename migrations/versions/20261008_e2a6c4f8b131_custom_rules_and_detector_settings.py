"""customers' own rules, and per-workspace detector switches

Adds two tenant-scoped tables:

* `custom_rules` — a rule a customer writes in their own words: words, patterns,
  topics (to block, or the only ones allowed), or a sequence of tool calls. Each row
  is compiled into a rule of the managed `custom` policy pack, so it is enforced,
  simulated and audited like every shipped rule.
* `detector_settings` — a workspace switching one detector on or off, overriding
  the deployment's `enabled_detectors` for that tenant only. No row means "as the
  deployment configured it".

Re-runnable: every object is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: e2a6c4f8b131
Revises: d4f1b8e6a3c7
Create Date: 2026-10-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a6c4f8b131"
down_revision: str | None = "d4f1b8e6a3c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _common() -> list[sa.Column]:
    return [
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    if not _has_table("custom_rules"):
        op.create_table(
            "custom_rules",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("key", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("kind", sa.String(length=24), nullable=False),
            sa.Column("polarity", sa.String(length=8), nullable=False),
            sa.Column("entries_json", sa.JSON(), nullable=False),
            sa.Column("examples_json", sa.JSON(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("surfaces_json", sa.JSON(), nullable=False),
            sa.Column("agents_json", sa.JSON(), nullable=False),
            sa.Column("case_sensitive", sa.Boolean(), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=200), nullable=False),
            *_common(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "key", name="ux_custom_rules_org_key"),
        )
        op.create_index("ix_custom_rules_key", "custom_rules", ["key"])
        op.create_index("ix_custom_rules_org_id", "custom_rules", ["org_id"])
    if not _has_table("detector_settings"):
        op.create_table(
            "detector_settings",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("updated_by", sa.String(length=200), nullable=False),
            *_common(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "key", name="ux_detector_settings_org_key"),
        )
        op.create_index("ix_detector_settings_key", "detector_settings", ["key"])
        op.create_index("ix_detector_settings_org_id", "detector_settings", ["org_id"])


def downgrade() -> None:
    for table in ("detector_settings", "custom_rules"):
        if _has_table(table):
            op.drop_table(table)
