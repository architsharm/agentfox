"""lineage edges say what they mean in `attrs`; a disconnected agent keeps a snapshot

Two additive columns.

* ``lineage_edges.attrs`` (JSON): what an edge read from code says besides its
  relation. ``kind`` is how a delegation hands work over (``handoff`` | ``as_tool`` |
  ``delegates`` | ``member``); `agentfox init` also wrote two unrelated things there:
  for ``talks_to`` (input -> agent) a truncated "how it reaches the agent" detail, for
  ``touches`` (tool -> resource) the resource's kind. Those move to
  ``attrs = {"detail": ...}`` and ``attrs = {"resource_kind": ...}`` and ``kind`` is
  cleared on those rows.
* ``agents.guardrails_snapshot`` (JSON): the agent's own guardrail layers (policy
  key -> live version, mode, rule count) as they were when its project was
  disconnected, so connecting it again can offer to put them back.

Re-runnable: `init_db()` adds both columns at startup on an existing database (see
`_ADDITIVE_COLUMNS`), so each is added only when missing; rows are moved only while
``kind`` still holds the old value.

Downgrade moves the two values back into ``kind`` (truncated to its 32 characters, as
before) and drops both columns; the snapshots are lost.

Revision ID: d7a4c2e9f1b6
Revises: b9e4c2a7d153
Create Date: 2026-10-21 16:00:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "d7a4c2e9f1b6"
down_revision: str | None = "b9e4c2a7d153"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: relation -> the attrs key its old `kind` value moves to.
MOVED = {"talks_to": "detail", "touches": "resource_kind"}

edges_t = sa.table(
    "lineage_edges",
    sa.column("id", sa.String),
    sa.column("relation", sa.String),
    sa.column("kind", sa.String),
    sa.column("attrs", sa.JSON),
)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def upgrade() -> None:
    if "attrs" not in _columns("lineage_edges"):
        with op.batch_alter_table("lineage_edges") as batch_op:
            batch_op.add_column(sa.Column("attrs", sa.JSON(), nullable=True))
    if "guardrails_snapshot" not in _columns("agents"):
        with op.batch_alter_table("agents") as batch_op:
            batch_op.add_column(sa.Column("guardrails_snapshot", sa.JSON(), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(edges_t.c.id, edges_t.c.relation, edges_t.c.kind, edges_t.c.attrs).where(
            edges_t.c.relation.in_(list(MOVED)), edges_t.c.kind.is_not(None)
        )
    ).all()
    for row in rows:
        attrs = _json(row.attrs)
        attrs.setdefault(MOVED[row.relation], row.kind)
        bind.execute(
            edges_t.update().where(edges_t.c.id == row.id).values(attrs=attrs, kind=None)
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "attrs" in _columns("lineage_edges"):
        rows = bind.execute(
            sa.select(edges_t.c.id, edges_t.c.relation, edges_t.c.attrs).where(
                edges_t.c.relation.in_(list(MOVED))
            )
        ).all()
        for row in rows:
            value = _json(row.attrs).get(MOVED[row.relation])
            if value:
                bind.execute(
                    edges_t.update()
                    .where(edges_t.c.id == row.id)
                    .values(kind=str(value)[:32])
                )
        with op.batch_alter_table("lineage_edges") as batch_op:
            batch_op.drop_column("attrs")
    if "guardrails_snapshot" in _columns("agents"):
        with op.batch_alter_table("agents") as batch_op:
            batch_op.drop_column("guardrails_snapshot")
