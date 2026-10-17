"""The workspace as one file: export it, see what applying a file would change, apply it.

* ``GET  /api/workspace/export``      — ``{source}``: YAML of every bound policy, custom rule
  and detector switch (``agentfox policy export`` writes the same file)
* ``POST /api/workspace/plan``        — what applying ``{source}`` would change; saves nothing
* ``POST /api/workspace/apply``       — apply it

The logic is `capabilities/workspace`; this file authorises. Applying needs the
``policy`` role, and ``policy_production`` when the file moves a policy to enforce,
the same split the dashboard's own mode switch uses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import WRITE_ROLES, current_user, db, require
from agentfox.capabilities import workspace
from agentfox.core.models import User

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/export")
def export_workspace(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, str]:
    return {"source": workspace.dump(workspace.export_bundle(session)), "filename": "agentfox.yaml"}


class SourceIn(BaseModel):
    source: str = Field(min_length=1, max_length=2_000_000)


def _parse(source: str) -> workspace.Bundle:
    try:
        return workspace.parse(source)
    except workspace.BundleError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/plan")
def plan_workspace(
    payload: SourceIn, session: Session = Depends(db), _user: User = Depends(require("policy"))
) -> dict[str, Any]:
    return workspace.plan(session, _parse(payload.source)).to_json()


@router.post("/apply")
def apply_workspace(
    payload: SourceIn, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    bundle = _parse(payload.source)
    enforces = workspace.plan(session, bundle).enforces
    if enforces and user.role not in WRITE_ROLES["policy_production"]:
        raise HTTPException(
            403, f"moving {', '.join(enforces)} to enforce needs a production policy role"
        )
    return workspace.apply(session, bundle, actor=user.email or user.id).to_json()
