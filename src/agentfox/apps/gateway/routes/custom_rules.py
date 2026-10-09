"""Custom rules and detector switches over HTTP — the dashboard's way to add a rule
in the customer's own words, and to turn a detector on or off for the workspace.

The rules themselves live in `capabilities/detection/custom_store.py`; these routes
validate, authorise and translate. Saving or deleting a rule regenerates the managed
`custom` policy pack, so the rule then appears, and is tuned, like any other.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.custom import (
    CustomListDetector,
    CustomRuleSpec,
    compile_rule,
    rule_id_for,
)
from agentfox.capabilities.detection.custom_models import get_model
from agentfox.capabilities.detection.custom_store import delete_rule, list_rules, save_rule, spec_of
from agentfox.capabilities.detection.detector_settings import set_enabled
from agentfox.core.models import User

router = APIRouter(prefix="/api", tags=["custom rules"])


def _json(row) -> dict[str, Any]:
    spec = spec_of(row)
    return {
        **spec.model_dump(),
        "rule_id": rule_id_for(row.key),
        "entity": spec.entity,
        "version": row.version,
        "created_by": row.created_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/custom-rules")
def get_custom_rules(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"rules": [_json(r) for r in list_rules(session)]}


class CustomRuleIn(CustomRuleSpec):
    #: Seeds the policy rule when the rule is first created; tuned afterwards.
    effect: Literal["block", "escalate", "redact", "allow"] = "block"
    message: str = ""
    on_block: Literal["refuse", "reask"] = "refuse"
    severity: Literal["low", "medium", "high", "critical"] = "medium"


@router.post("/custom-rules", status_code=201)
def post_custom_rule(
    payload: CustomRuleIn, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    spec = CustomRuleSpec(
        **payload.model_dump(exclude={"effect", "message", "on_block", "severity"})
    )
    # A model reporting under CUSTOM owns the rule `custom.<key>` (custom_models.py).
    if get_model(session, spec.key) is not None:
        raise HTTPException(409, f"one of your models is already called '{spec.key}'")
    row, sync = save_rule(
        session,
        spec,
        actor=user.email or user.id,
        effect=payload.effect,
        message=payload.message,
        on_block=payload.on_block,
        severity=payload.severity,
    )
    return {
        "rule": _json(row),
        "policy": {"version": sync.version, "mode": sync.mode, "simulation": sync.simulation},
    }


@router.delete("/custom-rules/{key}")
def remove_custom_rule(
    key: str, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    sync = delete_rule(session, key, actor=user.email or user.id)
    if sync is None:
        raise HTTPException(404, f"no custom rule '{key}'")
    return {"deleted": key, "policy": {"version": sync.version, "mode": sync.mode}}


class TryIn(BaseModel):
    rule: dict[str, Any]
    text: str
    surface: str = "input"


@router.post("/custom-rules/try")
def try_custom_rule(payload: TryIn, _user: User = Depends(current_user)) -> dict[str, Any]:
    """Match one text against a rule that has not been saved. Records nothing."""
    try:
        spec = CustomRuleSpec(**{**payload.rule, "key": payload.rule.get("key") or "draft"})
    except ValidationError as exc:
        raise HTTPException(400, exc.errors()[0]["msg"]) from exc
    compiled = compile_rule(spec)
    if compiled is None:
        raise HTTPException(400, "a sequence rule is checked against a run, not a text")
    result = CustomListDetector().detect(
        payload.text,
        DetectionContext(
            surface=payload.surface
            if payload.surface in compiled.surfaces
            else compiled.surfaces[0],
            extra={"custom_rules": [compiled]},
        ),
    )
    return {
        "matched": bool(result.detections),
        "matches": [
            {
                "start": d.start,
                "end": d.end,
                "score": d.score,
                "sample": d.sample,
                "kind": d.detail.get("kind"),
            }
            for d in result.detections
        ],
    }


class DetectorToggleIn(BaseModel):
    enabled: bool
    reason: str = ""


@router.post("/detectors/{key}")
def toggle_detector(
    key: str,
    payload: DetectorToggleIn,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    """Switch a detector on or off for this workspace. Turning one on that is not
    installed is refused: it would look enabled and check nothing."""
    detector = all_detectors().get(key)
    if detector is None:
        raise HTTPException(404, f"unknown detector '{key}'")
    if payload.enabled and not detector.available():
        raise HTTPException(409, f"'{key}' is not installed in this deployment")
    try:
        row = set_enabled(
            session, key, payload.enabled, actor=user.email or user.id, reason=payload.reason
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"key": key, "enabled": row.enabled}
