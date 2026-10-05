"""a tool's impact says whether a human declared it or a heuristic guessed it

Adds `tools.impact_source`: `declared` or `inferred`.

`agentfox.auto()` now governs the tool calls a model returns, and the first time it
sees a function tool nobody registered it registers one, with an impact guessed from
the tool's name and description (`integrations.mcp.infer_impact`). MCP governance has
always done the same for MCP tools. A guess is better than the alternative — an
unregistered tool is reasoned about as `read`, the least dangerous value there is —
but it is still a guess, and an operator reading the registry has to be able to tell
`send_email: irreversible` that somebody decided from the same line a substring
match produced. `agentfox tools declare` (and `@fox.tool(impact=...)`, and the API)
write `declared`; auto-registration writes `inferred`.

Existing rows default to `declared`: until this revision every way of writing a tool
row except MCP's was an explicit declaration, and a migration cannot tell the MCP ones
apart after the fact.

Re-runnable: the column is added only if missing, because `init_db()`'s create_all
can leave a database holding this revision's schema while its recorded revision is
still the previous one.

Revision ID: e4d1b7a95c20
Revises: a7c2e5b91d84
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4d1b7a95c20"
down_revision: str | None = "a7c2e5b91d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("tools", "impact_source"):
        with op.batch_alter_table("tools", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "impact_source",
                    sa.String(length=16),
                    nullable=False,
                    server_default="declared",
                )
            )


def downgrade() -> None:
    if _has_column("tools", "impact_source"):
        with op.batch_alter_table("tools", schema=None) as batch_op:
            batch_op.drop_column("impact_source")
