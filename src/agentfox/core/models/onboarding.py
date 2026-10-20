"""First-run onboarding: one row per user, carrying their progress, the map
`agentfox init` reported, the guardrails they chose, and their test runs.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin


class OnboardingSession(Base, TimestampMixin):
    __tablename__ = "onboarding_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("onb"))
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id"), unique=True, index=True
    )
    #: The key `agentfox init --key` presents. It can only report a map and test
    #: results for this one onboarding, so it is kept retrievable rather than hashed:
    #: the screen that shows it must be able to show it again.
    init_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    structure: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    structure_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runner_seen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    guardrails: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: run id -> {phase, status, total, by_type_totals, results[], error, created_at}
    runs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
