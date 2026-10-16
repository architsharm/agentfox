"""Features: the workspace's switches, and each project's changes to them.

* ``GET    /api/features``                         — the workspace's protections and checks
* ``GET    /api/agents/{slug}/features``           — one project's, each with what it inherits
* ``POST   /api/features/protections/{key}``       — set a protection for every project, or one
* ``DELETE /api/agents/{slug}/features/protections/{key}`` — back to the workspace's
* ``POST   /api/features/checks/{key}``            — switch a check for every project, or one
* ``DELETE /api/agents/{slug}/features/checks/{key}``      — back to the workspace's

The rules are in `capabilities/features.py`: a project may always be stricter, and
looser only where the workspace lets projects change that protection.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.apps.gateway.routes.policy import _GRANT_ROLES
from agentfox.capabilities import features
from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection.detector_settings import set_enabled, set_enabled_for_agent
from agentfox.core.models import User

router = APIRouter(prefix="/api", tags=["features"])


@router.get("/features")
def get_features(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return features.features(session)


@router.get("/agents/{slug}/features")
def get_agent_features(
    slug: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    get_agent_or_404(session, slug)
    return features.features(session, slug)


class ProtectionIn(BaseModel):
    #: off | on | low | medium | high. Omit to change only `open_to_projects`.
    level: str | None = None
    #: Only this project; empty: every project.
    agent: str = ""
    #: Every project only: let projects lower or switch off this protection.
    open_to_projects: bool | None = None
    reason: str = Field("", max_length=500)


@router.post("/features/protections/{key}")
def set_protection(
    key: str,
    payload: ProtectionIn,
    session: Session = Depends(db),
    user: User = Depends(require("policy")),
) -> dict[str, Any]:
    actor = user.email or user.id
    try:
        if payload.agent:
            get_agent_or_404(session, payload.agent)
            if payload.level is None:
                raise HTTPException(400, "a project change needs a level")
            features.set_project_protection(
                session, payload.agent, key, payload.level, actor=actor, reason=payload.reason
            )
            return features.features(session, payload.agent)
        if payload.open_to_projects and user.role not in _GRANT_ROLES:
            raise HTTPException(
                403, f"role '{user.role}' may not let projects lower a protection. Ask an admin."
            )
        features.set_workspace_protection(
            session,
            key,
            level=payload.level,
            open_to_projects=payload.open_to_projects,
            actor=actor,
            reason=payload.reason,
        )
        return features.features(session)
    except features.FeatureLocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/agents/{slug}/features/protections/{key}")
def inherit_protection(
    slug: str,
    key: str,
    session: Session = Depends(db),
    user: User = Depends(require("policy")),
) -> dict[str, Any]:
    get_agent_or_404(session, slug)
    try:
        features.set_project_protection(session, slug, key, None, actor=user.email or user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return features.features(session, slug)


class CheckIn(BaseModel):
    enabled: bool
    agent: str = ""
    reason: str = Field("", max_length=500)


@router.post("/features/checks/{key}")
def set_check(
    key: str,
    payload: CheckIn,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    """Switch a check on or off for every project, or for one. Switching on one that
    is not installed is refused: it would look on and check nothing."""
    detector = all_detectors().get(key)
    if detector is None:
        raise HTTPException(404, f"unknown check '{key}'")
    if payload.enabled and not detector.available():
        raise HTTPException(409, f"'{key}' is not installed in this deployment")
    actor = user.email or user.id
    try:
        if payload.agent:
            get_agent_or_404(session, payload.agent)
            set_enabled_for_agent(
                session, payload.agent, key, payload.enabled, actor=actor, reason=payload.reason
            )
            return features.features(session, payload.agent)
        set_enabled(session, key, payload.enabled, actor=actor, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return features.features(session)


@router.delete("/agents/{slug}/features/checks/{key}")
def inherit_check(
    slug: str,
    key: str,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    get_agent_or_404(session, slug)
    set_enabled_for_agent(session, slug, key, None, actor=user.email or user.id, reason="")
    return features.features(session, slug)
