"""control attestations, and a record of each retention purge

Adds two tenant-scoped tables:

* `control_reviews`: a named reviewer's attestation of one control against one
  framework (outcome, note, expiry, the evidence they saw, the audit-chain seq).
  Rows are only ever inserted; the newest per (control, framework) is the current one.
* `retention_runs`: one row per pass of the `retention.purge` job, with what each
  data class lost and why a class was skipped (no policy, legal hold, locked).

Re-runnable: each table is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: b5d9e3f7a412
Revises: a8c2e5f1d364
Create Date: 2026-10-09 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5d9e3f7a412"
down_revision: str | None = "a8c2e5f1d364"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table("control_reviews"):
        op.create_table(
            "control_reviews",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("control_key", sa.String(length=32), nullable=False),
            sa.Column("framework", sa.String(length=32), nullable=False),
            sa.Column("outcome", sa.String(length=24), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("reviewer", sa.String(length=120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("audit_seq", sa.Integer(), nullable=True),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_control_reviews_control_key", "control_reviews", ["control_key"])
        op.create_index("ix_control_reviews_framework", "control_reviews", ["framework"])
        op.create_index("ix_control_reviews_org_id", "control_reviews", ["org_id"])
        op.create_index(
            "ix_ctlreview_key_fw_time",
            "control_reviews",
            ["control_key", "framework", "reviewed_at"],
        )
    if not _has_table("retention_runs"):
        op.create_table(
            "retention_runs",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("trigger", sa.String(length=16), nullable=False),
            sa.Column("requested_by", sa.String(length=120), nullable=False),
            sa.Column("results_json", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_retention_runs_org_id", "retention_runs", ["org_id"])


def downgrade() -> None:
    if _has_table("retention_runs"):
        op.drop_table("retention_runs")
    if _has_table("control_reviews"):
        op.drop_table("control_reviews")
