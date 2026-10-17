"""a deployed agent's endpoint can be probed on a schedule, once someone opts in

Adds `probe_targets`: a registered agent's live endpoint (or an agent governed by
this gateway, run in process) that scheduled red-team probes may be sent to.

A row is created disabled. `enabled`, `opted_in_by`, `opted_in_at` and
`opt_in_acknowledgement` are the record that a named person agreed to send
adversarial input to that target; `registered_host` is the one host that agreement
covers. Campaigns go to the existing `redteam_campaigns` table with
`runner = 'live'`, so no other table changes.

Re-runnable: every object is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: c9e4a7b3d218
Revises: c3e9a7d15f42
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e4a7b3d218"
down_revision: str | None = "c3e9a7d15f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def _has_index(table: str, index: str) -> bool:
    return any(i["name"] == index for i in _inspector().get_indexes(table))


def upgrade() -> None:
    if not _has_table("probe_targets"):
        op.create_table(
            "probe_targets",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("agent_slug", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("adapter", sa.String(length=24), nullable=False, server_default="http"),
            sa.Column("url", sa.String(length=500), nullable=True),
            sa.Column("registered_host", sa.String(length=255), nullable=True),
            sa.Column("model", sa.String(length=64), nullable=True),
            sa.Column("auth_header_ciphertext", sa.Text(), nullable=True),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("opted_in_by", sa.String(length=200), nullable=True),
            sa.Column("opted_in_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opt_in_acknowledgement", sa.Text(), nullable=True),
            sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="86400"),
            sa.Column("max_probes_per_run", sa.Integer(), nullable=False, server_default="12"),
            sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="20"),
            sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_campaign_id", sa.String(length=40), nullable=True),
            sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, columns in (
        ("ix_probe_targets_agent_slug", ["agent_slug"]),
        ("ix_probe_targets_next_due_at", ["next_due_at"]),
        ("ix_probe_targets_org_id", ["org_id"]),
    ):
        if not _has_index("probe_targets", name):
            op.create_index(name, "probe_targets", columns, unique=False)


def downgrade() -> None:
    if _has_table("probe_targets"):
        op.drop_table("probe_targets")
