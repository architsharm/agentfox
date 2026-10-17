"""a waitlist row belongs to nobody, so it is the one table outside tenancy

Adds `waitlist_signups`: someone who asked to be told when the hosted service
exists. Until now the pricing page's "join the waitlist" was a `mailto:`, which is
not a waitlist — it is a hope that somebody remembers to keep a list in their inbox.

Why this table has no `org_id` when every other one does: the signup happens *before*
the person has an org. Scoping it would mean inventing a tenant for somebody who has
not signed up for anything, or filing every stranger under the deployment's own org,
which is a tenant boundary that means nothing. `models.TENANT_EXEMPT_TABLES` names it
explicitly so the omission is a decision on the record rather than a missing mixin,
and `tenancy.assert_tenant_safe` refuses any other table that tries the same thing.

`email` is UNIQUE, which is the whole idempotency story: a double-clicked submit, a
browser retry or a resubmitted form joins the list once. It is stored lowercased and
stripped by the endpoint, so `Ada@Example.com ` and `ada@example.com` are one person
and the database, not the application, is what guarantees it.

Nothing here sends mail and nothing calls out. A signup is a row.

Re-runnable: every object is created only if it is missing, because `init_db()`'s
create_all can leave a database holding this revision's schema while its recorded
revision is still the previous one.

Revision ID: f1b9c3d47a02
Revises: c4a71e8b2d16
Create Date: 2026-09-25 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1b9c3d47a02"
down_revision: str | None = "c4a71e8b2d16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def _has_index(table: str, index: str) -> bool:
    return any(i["name"] == index for i in _inspector().get_indexes(table))


def upgrade() -> None:
    if not _has_table("waitlist_signups"):
        op.create_table(
            "waitlist_signups",
            sa.Column("id", sa.String(length=40), nullable=False),
            # 320 is the longest address SMTP will carry: 64 local + @ + 255 domain.
            sa.Column("email", sa.String(length=320), nullable=False),
            # Which list. Present from the first migration rather than added later,
            # so a second waitlist is a new value here and not a new table.
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("company", sa.String(length=200), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            # No org_id, deliberately — see this revision's docstring.
        )

    with op.batch_alter_table("waitlist_signups", schema=None) as batch_op:
        for name, columns, unique in (
            # The unique one is load bearing: it is what makes a repeat submit
            # idempotent rather than a second row nobody notices.
            ("ix_waitlist_signups_email", ["email"], True),
            # "everyone waiting for hosted cloud" is the only query this table has.
            ("ix_waitlist_signups_source", ["source"], False),
        ):
            if not _has_index("waitlist_signups", name):
                batch_op.create_index(name, columns, unique=unique)


def downgrade() -> None:
    with op.batch_alter_table("waitlist_signups", schema=None) as batch_op:
        batch_op.drop_index("ix_waitlist_signups_source")
        batch_op.drop_index("ix_waitlist_signups_email")
    op.drop_table("waitlist_signups")
