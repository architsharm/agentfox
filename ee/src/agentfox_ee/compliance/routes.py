"""Control, framework, risk and board routes. Part of AgentFox Enterprise (BSL 1.1, see ee/LICENSE).

Two things are deliberate here:

* There is **no** PUT, PATCH or DELETE on ``/api/audit/entries``. The absence is the
  control.
* Reading an evidence package writes its own audit entry. Who looked at the evidence
  is audit-relevant, and a governance product that exempts itself from its own
  controls is not credible.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.core.models import (
    Control,
    FrameworkMapping,
    User,
)
from agentfox.platform.ledger import chain
from agentfox_ee.compliance import (
    FRAMEWORK_TITLES,
    all_frameworks,
    board_view,
    classify,
    compute_all,
    controls_for_framework,
    framework_coverage,
    latest_statuses,
    obligation_calendar,
    posture,
    requirements_for_framework,
)
from agentfox_ee.compliance import (
    register as risk_register,
)
from agentfox_ee.compliance import reviews as reviews_svc
from agentfox_ee.compliance.risk import assess

router = APIRouter(prefix="/api", tags=["compliance"])


# ---------------------------------------------------------------------------
# Controls & frameworks
# ---------------------------------------------------------------------------


def _catalog_current(session: Session) -> None:
    """Bring this tenant's stored catalog up to the one this build ships. It was only
    loaded into an empty workspace, so an upgrade that added a control left it "No such
    control" everywhere until someone ran the manual sync."""
    from agentfox.capabilities.compliance.catalog import ensure_catalog_current

    ensure_catalog_current(session)


@router.get("/controls")
def list_controls(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    _catalog_current(session)
    statuses = latest_statuses(session)
    reviews = reviews_svc.latest_reviews(session)
    out = []
    for control in session.scalars(select(Control).order_by(Control.key)):
        mappings = list(
            session.scalars(
                select(FrameworkMapping).where(FrameworkMapping.control_key == control.key)
            )
        )
        status = statuses.get(control.key)
        out.append(
            {
                "key": control.key,
                "title": control.title,
                "objective": control.objective,
                "family": control.family,
                "pillar": control.pillar,
                "implemented_by": control.implemented_by,
                "evidence_sources": control.evidence_sources,
                "status": status.status if status else "not_computed",
                "rationale": status.rationale if status else None,
                "computed_at": _iso(status.computed_at) if status else None,
                "mappings": [
                    {
                        "framework": m.framework,
                        "reference": m.reference,
                        "review_status": m.review_status,
                    }
                    for m in mappings
                ],
                "reviews": {
                    fw: reviews_svc.review_state(r)
                    for (key, fw), r in reviews.items()
                    if key == control.key
                },
            }
        )
    return {"controls": out, "posture": posture(session)}


@router.get("/controls/{key}")
def get_control(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """One control: what it checks, the evidence computed for it, where it is mapped,
    and every attestation made against it."""
    _catalog_current(session)
    control = session.scalar(select(Control).where(Control.key == key))
    if control is None:
        raise HTTPException(404, f"unknown control '{key}'")
    mappings = list(
        session.scalars(select(FrameworkMapping).where(FrameworkMapping.control_key == key))
    )
    latest = reviews_svc.latest_reviews(session)
    frameworks: dict[str, dict[str, Any]] = {}
    for m in mappings:
        entry = frameworks.setdefault(
            m.framework,
            {
                "framework": m.framework,
                "title": FRAMEWORK_TITLES.get(m.framework, m.framework),
                "references": [],
                "review": reviews_svc.review_json(latest.get((key, m.framework))),
            },
        )
        entry["references"].append(m.reference)
    return {
        "key": control.key,
        "title": control.title,
        "objective": control.objective,
        "family": control.family,
        "implemented_by": control.implemented_by,
        "evidence_sources": control.evidence_sources,
        "status_rule": control.status_rule_json,
        "evidence": reviews_svc.control_evidence(session, key),
        "frameworks": sorted(frameworks.values(), key=lambda f: f["title"]),
        "history": [reviews_svc.review_json(r) for r in reviews_svc.review_history(session, key)],
        "outcomes": list(reviews_svc.OUTCOMES),
        "valid_days": reviews_svc.REVIEW_VALID_DAYS,
    }


class ControlReviewIn(BaseModel):
    framework: str
    outcome: str
    note: str = ""


@router.post("/controls/{key}/reviews", status_code=201)
def review_control(
    key: str,
    payload: ControlReviewIn,
    session: Session = Depends(db),
    user: User = Depends(require("control_review")),
) -> dict[str, Any]:
    """Attest one control against one framework. The reviewer is always the caller."""
    try:
        review = reviews_svc.record_review(
            session,
            key,
            payload.framework,
            payload.outcome,
            reviewer=user.email or user.id,
            note=payload.note,
        )
    except reviews_svc.ReviewError as exc:
        raise HTTPException(400, str(exc)) from exc
    return reviews_svc.review_json(review) or {}


@router.post("/controls/sync")
def sync_controls(
    session: Session = Depends(db),
    user: User = Depends(require("compliance")),
) -> dict[str, Any]:
    """Load the static control catalog and obligation calendar from YAML into this
    tenant's control-plane DB. `agentfox admin catalog sync` does the same thing
    from the CLI against whatever DB it's pointed at — this is the same idempotent
    upsert, reachable without shell access to the deployment, so a freshly provisioned
    org isn't stuck at "0 controls, mapped to seven frameworks" with no way to fix it
    from the product itself."""
    from agentfox.capabilities.compliance.catalog import sync_catalog, sync_obligations

    catalog = sync_catalog(session)
    obligations = sync_obligations(session)
    chain.append(
        session,
        "compliance.catalog_synced",
        actor_type="user",
        actor_id=user.email or user.id,
        payload={**catalog, "obligations": obligations},
    )
    return {"catalog": catalog, "obligations": obligations, "posture": posture(session)}


@router.post("/controls/compute")
def compute_controls(
    window_days: int = 30,
    session: Session = Depends(db),
    user: User = Depends(require("compliance")),
) -> dict[str, Any]:
    statuses = compute_all(session, window_days)
    chain.append(
        session,
        "compliance.computed",
        actor_type="user",
        actor_id=user.email or user.id,
        payload={"controls": len(statuses), "window_days": window_days},
    )
    return {
        "computed": len(statuses),
        "posture": posture(session),
        "statuses": [
            {"control_key": s.control_key, "status": s.status, "rationale": s.rationale}
            for s in statuses
        ],
    }


@router.get("/frameworks")
def frameworks(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    _catalog_current(session)
    return {"frameworks": all_frameworks(session)}


@router.get("/frameworks/{key}")
def framework(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """One framework: its requirements, the controls mapped to each with live status
    and attestation, its dated obligations, and its declared gaps."""
    _catalog_current(session)
    if key not in FRAMEWORK_TITLES and not session.scalar(
        select(FrameworkMapping.id).where(FrameworkMapping.framework == key).limit(1)
    ):
        raise HTTPException(404, f"unknown framework '{key}'")
    coverage = framework_coverage(session, key)
    controls = controls_for_framework(session, key)
    coverage["controls"] = controls
    coverage["requirements_detail"] = requirements_for_framework(session, key, controls)
    coverage["posture"] = posture(session, key)
    coverage["obligations_detail"] = [
        o for o in obligation_calendar(session) if o["framework"] == key
    ]
    return coverage


@router.get("/compliance/status")
def compliance_status(
    framework: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    _catalog_current(session)
    return posture(session, framework)


# ---------------------------------------------------------------------------
# Risk & obligations
# ---------------------------------------------------------------------------


@router.get("/risk/register")
def get_register(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"register": risk_register(session)}


@router.get("/risk/classify/{slug}")
def classify_agent(
    slug: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    return classify(session, agent)


class AssessIn(BaseModel):
    eu_ai_act_class: str | None = None
    inherent_risk: str = "medium"
    residual_risk: str = "low"
    answers: dict[str, Any] = Field(default_factory=dict)
    review_months: int = 12
    #: Whether the caller signs the assessment off. The signer is always the
    #: authenticated caller: a sign-off naming someone else is a forged signature.
    sign_off: bool = False
    #: Deprecated and ignored beyond a consistency check — kept so an old client that
    #: sends its own address still works, and one naming someone else is refused.
    signed_off_by: str | None = None


@router.post("/risk/assessments/{slug}", status_code=201)
def create_assessment(
    slug: str,
    payload: AssessIn,
    session: Session = Depends(db),
    user: User = Depends(require("compliance")),
) -> dict[str, Any]:
    agent = get_agent_or_404(session, slug)
    signer = user.email or user.id
    if payload.signed_off_by and payload.signed_off_by.strip().lower() != str(signer).lower():
        raise HTTPException(
            403,
            "an assessment can only be signed off by the authenticated caller; "
            f"'{payload.signed_off_by}' is not you",
        )
    assessment = assess(
        session,
        agent,
        assessor=user.email,
        eu_ai_act_class=payload.eu_ai_act_class,
        inherent_risk=payload.inherent_risk,
        residual_risk=payload.residual_risk,
        answers=payload.answers,
        review_months=payload.review_months,
        signed_off_by=signer if (payload.sign_off or payload.signed_off_by) else None,
    )
    chain.append(
        session,
        "risk.assessed",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
        payload={
            "class": assessment.eu_ai_act_class,
            "residual_risk": assessment.residual_risk,
            "signed_off_by": assessment.signed_off_by,
        },
    )
    return {
        "id": assessment.id,
        "agent": slug,
        "eu_ai_act_class": assessment.eu_ai_act_class,
        "assessor": assessment.assessor,
        "signed_off_by": assessment.signed_off_by,
        "mitigations": assessment.mitigations_json,
        "next_review_at": _iso(assessment.next_review_at),
    }


@router.get("/obligations")
def obligations(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {"obligations": obligation_calendar(session)}


@router.get("/board")
def board(session: Session = Depends(db), _user: User = Depends(current_user)) -> dict[str, Any]:
    return board_view(session)


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).isoformat()
