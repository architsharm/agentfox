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
    CustomValidatorDetector,
    compile_rule,
    rule_id_for,
)
from agentfox.capabilities.detection.custom_conditions import observed_values
from agentfox.capabilities.detection.custom_models import get_model
from agentfox.capabilities.detection.custom_store import (
    delete_rule,
    get_rule,
    list_rules,
    save_rule,
    spec_of,
)
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


def _require_runnable(compiled) -> None:
    """Refuse a validator rule whose check is not installed on this server."""
    if compiled is not None and compiled.validator is not None:
        if not compiled.validator.available():
            raise HTTPException(
                400,
                f"'{compiled.validator.name}' cannot run here: "
                f"{compiled.validator.unavailable_reason()}",
            )


@router.post("/custom-rules", status_code=201)
def post_custom_rule(
    payload: CustomRuleIn, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    spec = CustomRuleSpec(
        **payload.model_dump(exclude={"effect", "message", "on_block", "severity"})
    )
    # A check that cannot run here would be saved as enforcing and pass everything.
    _require_runnable(compile_rule(spec))
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
    rule_id = rule_id_for(row.key)
    return {
        "rule": _json(row),
        "policy": {"version": sync.version, "mode": sync.mode, "simulation": sync.simulation},
        # What this rule does now: a new rule watches even while Your rules blocks.
        "mode": "observe" if sync.mode != "enforce" or rule_id in sync.watching else "enforce",
    }


@router.delete("/custom-rules/{key}")
def remove_custom_rule(
    key: str, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    sync = delete_rule(session, key, actor=user.email or user.id)
    if sync is None:
        raise HTTPException(404, f"no custom rule '{key}'")
    return {"deleted": key, "policy": {"version": sync.version, "mode": sync.mode}}


@router.get("/custom-rules/{key}/history")
def custom_rule_history(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Every saved version of a rule's words, patterns or condition, with what changed."""
    from agentfox.capabilities.detection.custom_store import history

    if get_rule(session, key) is None:
        raise HTTPException(404, f"no custom rule '{key}'")
    return {"key": key, "versions": history(session, key)}


@router.post("/custom-rules/{key}/versions/{version}/restore", status_code=201)
def restore_custom_rule(
    key: str,
    version: int,
    session: Session = Depends(db),
    user: User = Depends(require("policy")),
) -> dict[str, Any]:
    """Put an earlier version of a rule's definition back, as a new version."""
    from agentfox.capabilities.detection.custom_store import restore_version

    try:
        row, sync = restore_version(session, key, version, actor=user.email or user.id)
    except ValueError as exc:
        raise HTTPException(404 if "no " in str(exc) else 409, str(exc)) from exc
    return {
        "rule": _json(row),
        "policy": {"version": sync.version, "mode": sync.mode, "simulation": sync.simulation},
    }


class TryIn(BaseModel):
    rule: dict[str, Any]
    text: str
    surface: str = "input"
    #: For a condition on a tool: the tool the sample call or result belongs to.
    tool: str | None = None


@router.post("/custom-rules/try")
def try_custom_rule(payload: TryIn, _user: User = Depends(current_user)) -> dict[str, Any]:
    """Match one text against a rule that has not been saved. Records nothing."""
    try:
        spec = CustomRuleSpec(**{**payload.rule, "key": payload.rule.get("key") or "draft"})
    except ValidationError as exc:
        raise HTTPException(400, exc.errors()[0]["msg"]) from exc
    compiled = compile_rule(spec)
    if compiled is None and spec.sequence is not None:
        return _try_sequence(spec, payload.text)
    if compiled is None:
        raise HTTPException(400, "This rule is checked against a run, not a text.")
    tool = payload.tool or (
        spec.condition.tool
        if spec.condition and spec.condition.tool and "*" not in spec.condition.tool
        else None
    )
    detector = CustomValidatorDetector() if compiled.validator is not None else CustomListDetector()
    _require_runnable(compiled)
    result = detector.detect(
        payload.text,
        DetectionContext(
            surface=payload.surface
            if payload.surface in compiled.surfaces
            else compiled.surfaces[0],
            tool_key=tool,
            # A rule scoped to agents is tried as it would run for the first of them;
            # with no agent it would never apply, and every try would say "no match".
            agent_slug=compiled.agents[0] if compiled.agents else None,
            extra={"custom_rules": [compiled]},
        ),
    )
    # A condition also says which value it saw, so the author can tell a near miss
    # ("amount is 450") from a field that is not there at all.
    observed = (
        [v[:80] if isinstance(v, str) else v for v in observed_values(spec.condition, payload.text)]
        if spec.condition
        else []
    )
    return {
        "matched": bool(result.detections),
        "observed": observed,
        "matches": [
            {
                "start": d.start,
                "end": d.end,
                "score": d.score,
                "sample": d.sample,
                "kind": d.detail.get("kind"),
                "reason": d.detail.get("reason"),
            }
            for d in result.detections
        ],
    }


def _try_sequence(spec: CustomRuleSpec, text: str) -> dict[str, Any]:
    """Try a sequence rule on a made-up run: one tool call per line (or separated by
    commas or "->"), each optionally followed by its arguments as JSON."""
    import json
    import re

    from agentfox.capabilities.containment.checks import sequence_hit

    items = re.split(r"\n|->|→" + ("" if "{" in text else "|,"), text)
    calls: list[tuple[str, dict[str, Any]]] = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        name, _, rest = item.partition(" ")
        try:
            arguments = json.loads(rest) if rest.strip().startswith("{") else {}
        except ValueError as exc:
            raise HTTPException(400, f"The arguments after {name} are not JSON.") from exc
        calls.append((name, arguments if isinstance(arguments, dict) else {}))
    if not calls:
        raise HTTPException(400, "Write the calls of a run, one per line.")
    assert spec.sequence is not None
    hit = sequence_hit(spec.sequence, calls)
    return {
        "matched": hit is not None,
        "observed": [],
        "matches": [{"start": 0, "end": 0, "reason": f"{hit[1]} after {hit[0]}"}] if hit else [],
    }


@router.get("/validators")
def get_validators(_user: User = Depends(current_user)) -> dict[str, Any]:
    """Every registered validator: what it checks, its settings, and whether it runs here."""
    from agentfox.capabilities.detection.validators import all_validators

    return {
        "validators": sorted(
            (v.describe() for v in all_validators().values()), key=lambda d: d["label"].lower()
        )
    }


@router.get("/custom-rules/fields")
def custom_rule_fields(
    tool: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """The arguments a tool is known to take, to suggest as a condition's field."""
    from agentfox.platform.registry.service import known_arguments

    return {"tool": tool, "fields": sorted(known_arguments(session, tool) or [])}


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
