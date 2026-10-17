"""Import guardrails written for another tool.

* ``POST /api/import/{tool}/plan`` — what importing would do; saves nothing
* ``POST /api/import/{tool}``      — do it

``agent-governance`` is a policy importer rather than a guardrail one: it turns
agent-governance rule YAML or a policy manifest (with its Rego bundle in ``files``)
into policy documents, saved in observe. Its plan lists every source rule as
translated, translated with a note, or not translatable, and says when the source's
default lets unmatched calls through (`capabilities/detection/importers/agent_governance.py`).

The importer (`capabilities/detection/importers/`) only plans. Applying goes through
the same stores a hand-made change does: custom rules through `save_rules` (one new
version of the `custom` pack, in the mode it is already in), detectors through
`set_enabled`, packs through the library's install — so everything imported is
audited, versioned and tunable exactly like everything else, and new packs arrive
watching.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import db, require
from agentfox.apps.gateway.routes.library import install
from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection.custom_store import RuleSeed, list_rules, save_rules
from agentfox.capabilities.detection.detector_settings import enabled_for, set_enabled
from agentfox.capabilities.detection.importers import ImportPlan, planner
from agentfox.capabilities.detection.importers import agent_governance as policy_import
from agentfox.core.models import User

router = APIRouter(prefix="/api/import", tags=["import"])


class ImportIn(BaseModel):
    source: str = Field(min_length=1, max_length=200_000)
    #: Positions in the plan's items the operator unticked.
    skip: list[int] = Field(default_factory=list)
    #: Files the source refers to, by path: a policy manifest's Rego bundle.
    files: dict[str, str] = Field(default_factory=dict)


def _files(payload: ImportIn) -> dict[str, str]:
    if len(payload.files) > policy_import.MAX_FILES:
        raise HTTPException(413, f"at most {policy_import.MAX_FILES} files")
    if sum(len(v) for v in payload.files.values()) > policy_import.MAX_TOTAL_CHARS:
        raise HTTPException(413, "the files are too large to import in one go")
    return payload.files


def _plan(tool: str, source: str, session: Session) -> ImportPlan:
    plan = planner(tool)
    if plan is None:
        raise HTTPException(404, f"no importer for '{tool}'")
    return plan(source, existing_keys={r.key for r in list_rules(session)})


def _annotate(plan: ImportPlan, session: Session) -> list[dict[str, Any]]:
    """Each item, with what applying it would find: a detector already on or not installed."""
    detectors = all_detectors()
    on = enabled_for(session)
    out = []
    for item in plan.items:
        row = item.to_json()
        if item.kind == "detector":
            detector = detectors.get(item.target)
            row["installed"] = bool(detector and detector.available())
            row["already"] = item.target in on
        out.append(row)
    return out


@router.post("/{tool}/plan")
def plan_import(
    tool: str,
    payload: ImportIn,
    session: Session = Depends(db),
    _user: User = Depends(require("policy")),
) -> dict[str, Any]:
    if tool == policy_import.TOOL:
        return policy_import.plan_json(policy_import.plan(payload.source, _files(payload)))
    plan = _plan(tool, payload.source, session)
    return {**plan.to_json(), "items": _annotate(plan, session)}


@router.post("/{tool}")
def apply_import(
    tool: str,
    payload: ImportIn,
    session: Session = Depends(db),
    user: User = Depends(require("policy")),
) -> dict[str, Any]:
    actor = user.email or user.id
    if tool == policy_import.TOOL:
        translation = policy_import.plan(payload.source, _files(payload))
        if translation.errors:
            raise HTTPException(400, translation.errors[0])
        if not any(doc.rules for doc in translation.documents):
            raise HTTPException(400, "nothing in this policy could be translated")
        return policy_import.apply(session, translation, actor=actor, skip=payload.skip)
    plan = _plan(tool, payload.source, session)
    if plan.errors and not plan.items:
        raise HTTPException(400, plan.errors[0])
    reason = f"imported from {tool}"
    chosen = [item for i, item in enumerate(plan.items) if i not in set(payload.skip)]
    detectors = all_detectors()

    rules = [
        (item.rule, RuleSeed(effect=item.effect or "block", on_block=item.on_block))
        for item in chosen
        if item.kind == "custom_rule" and item.rule is not None
    ]
    sync = save_rules(session, rules, actor=actor, reason=reason)[1] if rules else None

    switched, not_installed = [], []
    for item in chosen:
        if item.kind != "detector":
            continue
        detector = detectors.get(item.target)
        if detector is None or not detector.available():
            not_installed.append(item.target)
            continue
        set_enabled(session, item.target, True, actor=actor, reason=reason)
        switched.append(item.target)

    packs: dict[str, list[str]] = {}
    for item in chosen:
        if item.kind == "pack":
            packs[item.target] = install(session, item.target, actor=actor, reason=reason) or []

    return {
        "rules": [spec.key for spec, _ in rules],
        "custom_policy": {"version": sync.version, "mode": sync.mode, "simulation": sync.simulation}
        if sync
        else None,
        "detectors": switched,
        "not_installed": not_installed,
        "packs": packs,
        "skipped": [item.to_json() for item in chosen if item.kind == "skipped"],
    }
