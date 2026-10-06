"""a registered tool keeps the impact annotations it was reviewed with

Adds `tools.annotations_json` (nullable JSON): the MCP tool annotations that speak to
impact (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) as they
stood when the tool's listing was registered or accepted.

The MCP governor pins a tool's digest and refuses calls once the server lists the tool
differently. The digest covered name, description and input schema only, so a server
could flip `readOnlyHint` to false, or set `destructiveHint`, and calls carried on. A
client that auto-approves read-only tools reads exactly those hints. Including them in
the digest needs the reviewed values on the record.

NULL means "recorded before this column existed": the governor then compares without
annotations and fills the column at the next unchanged listing, so an upgrade does not
hold every annotated tool at once.

Re-runnable: the column is added only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: d4f1b8e6a3c7
Revises: c9e4a7b3d218
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f1b8e6a3c7"
down_revision: str | None = "c9e4a7b3d218"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("tools", "annotations_json"):
        with op.batch_alter_table("tools") as batch_op:
            batch_op.add_column(sa.Column("annotations_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_column("tools", "annotations_json"):
        with op.batch_alter_table("tools") as batch_op:
            batch_op.drop_column("annotations_json")
