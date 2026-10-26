"""onboarding: hashed setup keys, a row per test run, a map per project

Three changes to what `b5d2e8f4a617` set up.

* The setup key `agentfox init --key` presents (``afi_…``) was kept in plaintext in
  ``onboarding_sessions.init_key`` and never expired. It becomes an ``api_tokens`` row
  like an operator token: hashed (``sha256$…``, as ``platform/identity/keyhash``
  stores keys), prefix-narrowed, expiring (30 days from this upgrade), revocable.
  Each existing key is moved there, so a running `agentfox init` keeps working, and
  ``init_key`` then holds the token's id instead of the key.
* Test runs move out of the ``onboarding_sessions.runs`` JSON into
  ``onboarding_runs``, one row each. Finished runs are copied as they were, with the
  map of the row they lived on; a run still queued or running is copied as failed
  (its runner would not find it under the new lease rules anyway). ``runs`` is then
  emptied; the column stays so code from before this revision can still insert.
* ``onboarding_projects``: each project's own map, so a second `agentfox init` in
  another repository no longer replaces it. Seeded from each row's latest map.

Re-runnable: tables are created only when missing (``init_db()`` may already have
made them), keys are moved only while ``init_key`` still holds one, and runs are
copied only when their id is not there yet.

Downgrade drops the two tables (test history is lost) and gives every row a fresh
plaintext key (the hashed ones cannot be turned back), revoking the setup-key
tokens: after a downgrade each user's `agentfox init` needs the new key.

Revision ID: b9e4c2a7d153
Revises: c6e1f9a3d72b
Create Date: 2026-10-21 10:00:00.000000
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "b9e4c2a7d153"
down_revision: str | None = "c6e1f9a3d72b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETUP_KEY_NAME = "agentfox init setup key"
PREFIX_LENGTH = len("afi_") + 8
TTL_DAYS = 30

sessions_t = sa.table(
    "onboarding_sessions",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("org_id", sa.String),
    sa.column("init_key", sa.String),
    sa.column("structure", sa.JSON),
    sa.column("structure_at", sa.DateTime(timezone=True)),
    sa.column("runner_seen_at", sa.DateTime(timezone=True)),
    sa.column("runs", sa.JSON),
)
tokens_t = sa.table(
    "api_tokens",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("name", sa.String),
    sa.column("key_prefix", sa.String),
    sa.column("key_hash", sa.String),
    sa.column("expires_at", sa.DateTime(timezone=True)),
    sa.column("revoked_at", sa.DateTime(timezone=True)),
    sa.column("org_id", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
runs_t = sa.table(
    "onboarding_runs",
    sa.column("id", sa.String),
    sa.column("org_id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("project", sa.String),
    sa.column("phase", sa.String),
    sa.column("status", sa.String),
    sa.column("guards", sa.JSON),
    sa.column("sets", sa.JSON),
    sa.column("structure", sa.JSON),
    sa.column("total", sa.Integer),
    sa.column("totals", sa.JSON),
    sa.column("results", sa.JSON),
    sa.column("error", sa.Text),
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("finished_at", sa.DateTime(timezone=True)),
    sa.column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
projects_t = sa.table(
    "onboarding_projects",
    sa.column("id", sa.String),
    sa.column("org_id", sa.String),
    sa.column("project", sa.String),
    sa.column("structure", sa.JSON),
    sa.column("structure_at", sa.DateTime(timezone=True)),
    sa.column("runner_seen_at", sa.DateTime(timezone=True)),
    sa.column("connected_by", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _when(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _create_tables() -> None:
    have = _tables()
    if "onboarding_projects" not in have:
        op.create_table(
            "onboarding_projects",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("project", sa.String(length=120), nullable=False),
            sa.Column("structure", sa.JSON(), nullable=False),
            sa.Column("structure_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("runner_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("connected_by", sa.String(length=40), nullable=True),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "project", name="ux_onboarding_projects_org"),
        )
        op.create_index("ix_onboarding_projects_org_id", "onboarding_projects", ["org_id"])
    if "onboarding_runs" not in have:
        op.create_table(
            "onboarding_runs",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("user_id", sa.String(length=40), nullable=False),
            sa.Column("project", sa.String(length=120), nullable=True),
            sa.Column("phase", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("guards", sa.JSON(), nullable=True),
            sa.Column("sets", sa.JSON(), nullable=False),
            sa.Column("structure", sa.JSON(), nullable=False),
            sa.Column("total", sa.Integer(), nullable=False),
            sa.Column("totals", sa.JSON(), nullable=False),
            sa.Column("results", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_onboarding_runs_org_id", "onboarding_runs", ["org_id"])
        op.create_index("ix_onboarding_runs_user_id", "onboarding_runs", ["user_id"])
        op.create_index(
            "ix_onboarding_runs_org_project", "onboarding_runs", ["org_id", "project", "status"]
        )


def _hash_keys(bind: Any, now: dt.datetime) -> None:
    rows = bind.execute(
        sa.select(sessions_t.c.id, sessions_t.c.user_id, sessions_t.c.org_id, sessions_t.c.init_key)
    ).all()
    for row in rows:
        raw = row.init_key or ""
        if not raw.startswith("afi_"):
            continue
        token_id = "tok_" + secrets.token_hex(8)
        bind.execute(
            tokens_t.insert().values(
                id=token_id,
                user_id=row.user_id,
                name=SETUP_KEY_NAME,
                key_prefix=raw[:PREFIX_LENGTH],
                key_hash="sha256$" + hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=now + dt.timedelta(days=TTL_DAYS),
                revoked_at=None,
                org_id=row.org_id,
                created_at=now,
                updated_at=now,
            )
        )
        bind.execute(
            sessions_t.update().where(sessions_t.c.id == row.id).values(init_key=token_id)
        )


def _move_runs(bind: Any, now: dt.datetime) -> None:
    have = {r.id for r in bind.execute(sa.select(runs_t.c.id)).all()}
    projects = {
        (r.org_id, r.project)
        for r in bind.execute(sa.select(projects_t.c.org_id, projects_t.c.project)).all()
    }
    rows = bind.execute(sa.select(sessions_t)).all()
    for row in rows:
        structure = _json(row.structure) or {}
        project = structure.get("project")
        if project and (row.org_id, project) not in projects:
            projects.add((row.org_id, project))
            bind.execute(
                projects_t.insert().values(
                    id="onp_" + secrets.token_hex(8),
                    org_id=row.org_id,
                    project=str(project)[:120],
                    structure=structure,
                    structure_at=row.structure_at,
                    runner_seen_at=row.runner_seen_at,
                    connected_by=row.user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        runs = _json(row.runs) or {}
        if not runs:
            continue
        for run in runs.values():
            if not isinstance(run, dict) or not run.get("id") or run["id"] in have:
                continue
            active = run.get("status") in ("queued", "running")
            bind.execute(
                runs_t.insert().values(
                    id=str(run["id"])[:40],
                    org_id=row.org_id,
                    user_id=row.user_id,
                    project=run.get("project"),
                    phase=run.get("phase") or "before",
                    status="failed" if active else (run.get("status") or "failed"),
                    guards=run.get("guards"),
                    sets=run.get("sets") or [],
                    structure=structure,
                    total=int(run.get("total") or 0),
                    totals=run.get("totals") or {},
                    results=run.get("results") or [],
                    error="Interrupted by an upgrade. Run the test again."
                    if active
                    else run.get("error"),
                    started_at=_when(run.get("startedAt")),
                    finished_at=now if active else _when(run.get("finishedAt")),
                    lease_expires_at=None,
                    created_at=_when(run.get("createdAt")) or now,
                    updated_at=now,
                )
            )
            have.add(run["id"])
        bind.execute(sessions_t.update().where(sessions_t.c.id == row.id).values(runs={}))


def upgrade() -> None:
    _create_tables()
    if "onboarding_sessions" not in _tables():
        return
    bind = op.get_bind()
    now = dt.datetime.now(dt.UTC)
    _hash_keys(bind, now)
    _move_runs(bind, now)


def downgrade() -> None:
    bind = op.get_bind()
    have = _tables()
    if "onboarding_sessions" in have:
        for row in bind.execute(sa.select(sessions_t.c.id, sessions_t.c.init_key)).all():
            if not (row.init_key or "").startswith("afi_"):
                bind.execute(
                    sessions_t.update()
                    .where(sessions_t.c.id == row.id)
                    .values(init_key="afi_" + secrets.token_urlsafe(24))
                )
    if "api_tokens" in have:
        bind.execute(
            tokens_t.update()
            .where(tokens_t.c.name == SETUP_KEY_NAME, tokens_t.c.revoked_at.is_(None))
            .values(revoked_at=dt.datetime.now(dt.UTC))
        )
    if "onboarding_runs" in have:
        op.drop_table("onboarding_runs")
    if "onboarding_projects" in have:
        op.drop_table("onboarding_projects")
