"""Two first calls for a new agent racing to create its identity (onboarding attack test).

Before: eight concurrent guard checks each inserted an identity for the same agent;
all but one hit the unique (org, principal) constraint and the check failed, so the
attack test reported "AgentFox couldn't check this attack".
"""

from __future__ import annotations

from sqlalchemy import func, select

from agentfox.core.models import Agent, Identity
from agentfox.platform.identity import service
from agentfox.platform.identity.service import ensure_identity


def test_losing_the_insert_race_returns_the_winners_identity(seeded, monkeypatch):
    agent = seeded.scalar(select(Agent).limit(1))
    winner = ensure_identity(seeded, agent)

    # The racing call looked before the winner's row was visible to it.
    real_scalar = seeded.scalar
    calls = {"n": 0}

    def scalar(stmt, *a, **k):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_scalar(stmt, *a, **k)

    monkeypatch.setattr(seeded, "scalar", scalar)
    found = service.ensure_identity(seeded, agent)
    monkeypatch.undo()

    assert found.id == winner.id
    principal = f"agent:{agent.slug}"
    assert (
        seeded.scalar(
            select(func.count()).select_from(Identity).where(Identity.principal == principal)
        )
        == 1
    )
