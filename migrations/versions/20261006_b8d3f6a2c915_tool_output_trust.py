"""a tool can declare that its output is trusted

Adds `tools.output_trust` (`untrusted` | `trusted`).

Every tool result has been treated as content an attacker may have written, which is
right for `fetch_url` and wrong for a read of the operator's own CRM: a support bot
that copies a customer's email address out of `read_customer_record` into
`send_email` had that argument marked `tool_result`, and the irreversible send was
escalated or blocked on every benign conversation. `trusted` is the operator saying
the output comes from a system of record they control, so values copied from it do
not taint the arguments they land in (guardrails/taint.py).

`untrusted` is the server default, so every existing row keeps exactly the behaviour
it had, which is what keeps the published benchmark numbers comparable.

Re-runnable: the column is added only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: b8d3f6a2c915
Revises: a7c2e5b91d84
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d3f6a2c915"
down_revision: str | None = "a7c2e5b91d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("tools", "output_trust"):
        with op.batch_alter_table("tools") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "output_trust",
                    sa.String(length=16),
                    nullable=False,
                    server_default="untrusted",
                )
            )


def downgrade() -> None:
    if _has_column("tools", "output_trust"):
        with op.batch_alter_table("tools") as batch_op:
            batch_op.drop_column("output_trust")
