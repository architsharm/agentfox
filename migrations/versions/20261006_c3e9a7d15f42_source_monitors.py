"""monitors: connected sources re-checked on a schedule

Adds `monitors` (one row per watched GitHub repository, hosted-API spec or MCP
server, with its interval, last run, and the snapshot the next run is diffed
against), `alert_channels` (a tenant's own Slack incoming webhook, encrypted), and
`github_connections.webhook_secret_encrypted` (the secret GitHub signs push
deliveries with, per connection).

Tracking used to happen only when someone ran a scan. A monitor is what lets the
`monitors.run` job do it unattended.

Re-runnable: each table and the column are added only if missing, because
`init_db()`'s create_all can leave a database holding this revision's schema while
its recorded revision is still the previous one.

Revision ID: c3e9a7d15f42
Revises: b8d3f6a2c915
Create Date: 2026-10-06 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e9a7d15f42"
down_revision: str | None = "b8d3f6a2c915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.engine.reflection.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return _inspector().has_table(table)


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


def upgrade() -> None:
    if not _has_table("monitors"):
        op.create_table(
            "monitors",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("target", sa.String(length=500), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("interval_seconds", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_result_json", sa.JSON(), nullable=False),
            sa.Column("baseline_json", sa.JSON(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=False),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "kind", "target", name="ux_monitors_org_kind_target"),
        )
        with op.batch_alter_table("monitors", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_monitors_kind"), ["kind"], unique=False)
            batch_op.create_index(batch_op.f("ix_monitors_org_id"), ["org_id"], unique=False)
            batch_op.create_index("ix_monitors_due", ["enabled", "next_run_at"], unique=False)

    if not _has_table("alert_channels"):
        op.create_table(
            "alert_channels",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("url_encrypted", sa.Text(), nullable=False),
            sa.Column("min_severity", sa.String(length=16), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "kind", name="ux_alert_channels_org_kind"),
        )
        with op.batch_alter_table("alert_channels", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_alert_channels_org_id"), ["org_id"], unique=False)

    if not _has_column("github_connections", "webhook_secret_encrypted"):
        with op.batch_alter_table("github_connections") as batch_op:
            batch_op.add_column(sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("github_connections", "webhook_secret_encrypted"):
        with op.batch_alter_table("github_connections") as batch_op:
            batch_op.drop_column("webhook_secret_encrypted")
    if _has_table("alert_channels"):
        with op.batch_alter_table("alert_channels", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_alert_channels_org_id"))
        op.drop_table("alert_channels")
    if _has_table("monitors"):
        with op.batch_alter_table("monitors", schema=None) as batch_op:
            batch_op.drop_index("ix_monitors_due")
            batch_op.drop_index(batch_op.f("ix_monitors_org_id"))
            batch_op.drop_index(batch_op.f("ix_monitors_kind"))
        op.drop_table("monitors")
