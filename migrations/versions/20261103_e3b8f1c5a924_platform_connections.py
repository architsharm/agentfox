"""platform_connections: agents on Vapi, Retell and Copilot Studio governed by webhook

One table, ``platform_connections``: an agent that runs on a hosted platform and sends
its tool calls to ``/v1/hooks/<platform>/<id>`` first, with the operator-registered
tool server an allowed call is forwarded to and the encrypted secret that proves a
delivery came from the platform.

Re-runnable: the table is created only when missing (``init_db()`` may already have
made it). Downgrade drops it.

Revision ID: e3b8f1c5a924
Revises: d7a4c2e9f1b6
Create Date: 2026-11-03 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b8f1c5a924"
down_revision: str | None = "d7a4c2e9f1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("platform_connections"):
        return
    op.create_table(
        "platform_connections",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("upstream_url", sa.String(500), nullable=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_connections_agent_id", "platform_connections", ["agent_id"])
    op.create_index("ix_platform_connections_platform", "platform_connections", ["platform"])
    op.create_index("ix_platform_connections_org_id", "platform_connections", ["org_id"])


def downgrade() -> None:
    op.drop_table("platform_connections")
