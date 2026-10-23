"""First-run onboarding.

* ``OnboardingSession``: one row per user, carrying their setup-wizard progress, the
  map their latest `agentfox init` reported and the guardrails they chose.
* ``OnboardingProject``: one row per project (repository) a runner connected, with
  that project's own map and when its runner was last seen.
* ``OnboardingRun``: one row per attack test, with the map it runs on.

The setup key `agentfox init --key` presents is an ``ApiToken`` (hashed, expiring,
revocable, like an operator token) named ``agentfox init setup key``; the session row
only points at it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin


class OnboardingSession(Base, TimestampMixin):
    __tablename__ = "onboarding_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("onb"))
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id"), unique=True, index=True
    )
    #: Which ``ApiToken`` is this user's current setup key (``tok_…``), or this row's
    #: own id while they have none. Never the key itself: the key is stored hashed,
    #: on the token. (Rows written before b9e4c2a7d153 held the plaintext ``afi_…``
    #: key here; that migration, or the first use of such a key, moves it to a token.)
    init_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    structure: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    structure_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runner_seen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    guardrails: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: Unused since b9e4c2a7d153 (runs are ``OnboardingRun`` rows). Kept so a
    #: deployment running this code before that migration can still insert a row.
    runs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OnboardingProject(Base, TimestampMixin):
    """A project a runner connected: its own map, so a second `agentfox init` in another
    repository never replaces it, and when its runner last polled."""

    __tablename__ = "onboarding_projects"
    __table_args__ = (UniqueConstraint("org_id", "project", name="ux_onboarding_projects_org"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("onp"))
    project: Mapped[str] = mapped_column(String(120))
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    structure_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runner_seen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: The user whose setup key connected it last.
    connected_by: Mapped[str | None] = mapped_column(String(40), nullable=True)


class OnboardingRun(Base, TimestampMixin):
    """One attack test. The runner claims it with a lease it renews as it reports;
    a run whose lease lapses is failed rather than left "running" for ever."""

    __tablename__ = "onboarding_runs"
    __table_args__ = (Index("ix_onboarding_runs_org_project", "org_id", "project", "status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    #: Who started it (the setup wizard's runs are the user's own).
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    #: The project's panel it belongs to; None for the setup wizard's runs.
    project: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phase: Mapped[str] = mapped_column(String(16))
    #: queued | running | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    guards: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    sets: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: The map the test runs on, as it was when the test was started.
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total: Mapped[int] = mapped_column(Integer, default=0)
    totals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    results: Mapped[list[Any]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Until when the runner that claimed it holds it; renewed by every report.
    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
