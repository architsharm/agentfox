"""Finding or making the rows onboarding keeps, safely under concurrent first loads.

The dashboard fires several requests at once when a page opens. Selecting, finding
nothing, then inserting let two of them insert the same user's row, and the loser
failed with a unique-constraint 500. Here the insert runs in a savepoint: losing the
race unwinds only that savepoint and the winner's row is read back.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentfox.capabilities.onboarding.service import INITIAL_STATE
from agentfox.core import ids
from agentfox.core.models import OnboardingProject, OnboardingSession, User


def _insert_or_reload(session: Session, make: Any, reload: Any) -> Any:
    try:
        with session.begin_nested():
            row = make()
            session.add(row)
    except IntegrityError:
        row = reload()
        if row is None:  # the conflict was something else
            raise
    return row


def find(session: Session, user: User) -> OnboardingSession | None:
    """The user's onboarding row, if they have one. Reading never creates it."""
    return session.scalar(select(OnboardingSession).where(OnboardingSession.user_id == user.id))


def ensure(session: Session, user: User) -> OnboardingSession:
    """The user's onboarding row, made if this is their first write."""
    row = find(session, user)
    if row is not None:
        return row

    def make() -> OnboardingSession:
        rid = ids.new_id("onb")
        # No setup key yet: `init_key` holds the row's own id until one is made.
        return OnboardingSession(
            id=rid,
            user_id=user.id,
            org_id=user.org_id,
            init_key=rid,
            state=dict(INITIAL_STATE),
            runs={},
        )

    return _insert_or_reload(session, make, lambda: find(session, user))


def find_project(session: Session, project: str) -> OnboardingProject | None:
    return session.scalar(select(OnboardingProject).where(OnboardingProject.project == project))


def ensure_project(session: Session, project: str, *, org_id: str) -> OnboardingProject:
    row = find_project(session, project)
    if row is not None:
        return row
    return _insert_or_reload(
        session,
        lambda: OnboardingProject(project=project, org_id=org_id, structure={}),
        lambda: find_project(session, project),
    )
