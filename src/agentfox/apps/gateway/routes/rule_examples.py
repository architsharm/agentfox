"""Saved examples for a rule, and re-checking them against a proposed version.

* ``GET    /api/rules/{rule_id}/examples``             — the saved examples
* ``POST   /api/rules/{rule_id}/examples``             — save one: ``{decision_id, fires, sample?}``
* ``DELETE /api/rules/{rule_id}/examples/{id}``
* ``POST   /api/rules/{rule_id}/examples/check``       — ``{policy, body?}``: does the rule, in
  that pack's live version or in ``body`` (a proposed version), still do what each expects?

An example names a recorded decision; the dashboard records one by running the text
through the playground first. See `platform/policy/examples.py`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.core.models import Policy, User
from agentfox.platform.policy import (
    PolicyDocument,
    current_binding,
    examples,
    load_version_document,
)

router = APIRouter(prefix="/api/rules", tags=["rule examples"])


@router.get("/{rule_id}/examples")
def get_examples(
    rule_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"examples": [e.to_json() for e in examples.list_examples(session, rule_id)]}


class ExampleIn(BaseModel):
    decision_id: str
    fires: bool
    sample: str = Field("", max_length=2000)


@router.post("/{rule_id}/examples", status_code=201)
def post_example(
    rule_id: str,
    payload: ExampleIn,
    session: Session = Depends(db),
    _user: User = Depends(require("policy")),
) -> dict[str, Any]:
    try:
        example = examples.add_example(
            session, rule_id, payload.decision_id, fires=payload.fires, sample=payload.sample
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return example.to_json()


@router.delete("/{rule_id}/examples/{example_id}")
def remove_example(
    rule_id: str,
    example_id: str,
    session: Session = Depends(db),
    _user: User = Depends(require("policy")),
) -> dict[str, Any]:
    if not examples.delete_example(session, rule_id, example_id):
        raise HTTPException(404, "no such example for this rule")
    return {"deleted": example_id}


class CheckIn(BaseModel):
    policy: str
    #: A proposed version's YAML; the pack's live version when absent.
    body: str | None = None


@router.post("/{rule_id}/examples/check")
def check_examples(
    rule_id: str,
    payload: CheckIn,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    if payload.body:
        try:
            doc = PolicyDocument.from_yaml(payload.body)
        except Exception as exc:  # noqa: BLE001 - any parse failure is the caller's input
            raise HTTPException(400, f"not a policy: {exc}") from exc
    else:
        policy = session.scalar(select(Policy).where(Policy.key == payload.policy))
        live = current_binding(session, policy.id)[1] if policy else None
        if live is None:
            raise HTTPException(404, f"no live policy '{payload.policy}'")
        doc = load_version_document(live)
    results = [c.to_json() for c in examples.check(session, rule_id, doc)]
    return {
        "results": results,
        "passed": sum(r["passed"] for r in results),
        "failed": sum(not r["passed"] for r in results),
    }
