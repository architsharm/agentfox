"""The Checks screen's writes: download a detector's model, and register your own.

`GET /api/detectors` (gateway/app.py) is the read. Switching a detector on or off
is `POST /api/detectors/{key}` (custom_rules.py), and the judgment tiers are the
audited `PUT /api/judgment/posture` (posture.py). What is here:

* ``POST /api/detectors/{key}/pull`` downloads an open-source detector's weights in
  a background job, where this server can keep them. Serverless (a read-only file
  system) or without the model libraries it answers 409 with what to run instead.
* ``/api/custom-models`` registers a classifier endpoint the workspace runs itself,
  which the `custom.models` detector then calls (capabilities/detection/custom_models.py).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection import custom_models as cm
from agentfox.capabilities.detection.custom_store import get_rule
from agentfox.capabilities.detection.models import models_for, pull_blocker
from agentfox.core.crypto import EncryptionNotConfigured, encrypt_secret
from agentfox.core.models import Job, User
from agentfox.core.tenancy import bind_session, session_org
from agentfox.platform.jobs import store as jobs_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["checks"])

PULL_KIND = "detectors.pull"


# ---------------------------------------------------------------------------
# Downloading a detector's model
# ---------------------------------------------------------------------------


def latest_pull_jobs(session: Session) -> dict[str, dict[str, Any]]:
    """The most recent download job per detector key, for the status column."""
    out: dict[str, dict[str, Any]] = {}
    for job in session.scalars(
        select(Job)
        .where(Job.org_id == session_org(session), Job.kind == PULL_KIND)
        .order_by(Job.enqueued_at.desc())
        .limit(100)
    ):
        key = str((job.payload_json or {}).get("key") or "")
        if key and key not in out:
            out[key] = jobs_db.job_json(job)
    return out


def _run_pull(job_id: str, org_id: str) -> None:
    """Run the download after the response is sent. Best effort: the job row records
    its own failure, and the cron runner picks up a job this never reached."""
    from agentfox.core.db import session_scope

    try:
        with session_scope() as background:
            bind_session(background, org_id)
            job = background.get(Job, job_id)
            if job is not None:
                jobs_db.run_job(background, job)
    except Exception:  # noqa: BLE001 - the job row records its own failure
        log.warning("detector model download %s could not run", job_id, exc_info=True)


@router.post("/detectors/{key}/pull", status_code=202)
def pull_detector(
    key: str,
    background: BackgroundTasks,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    """Download the model weights this detector loads, in a background job.

    409 with what to run instead when this server cannot keep a model (serverless,
    or the model libraries are not installed). Poll `GET /api/detectors` (its
    `pull_job`) or `GET /api/jobs/{id}` for the outcome; once it is `done`, switch
    the detector on.
    """
    detector = all_detectors().get(key)
    if detector is None:
        raise HTTPException(404, f"unknown detector '{key}'")
    if not models_for(detector):
        raise HTTPException(400, f"'{key}' uses no model; there is nothing to download")
    blocked = pull_blocker(detector)
    if blocked:
        raise HTTPException(409, blocked)
    running = latest_pull_jobs(session).get(key)
    if running and running["status"] in (jobs_db.PENDING, jobs_db.RUNNING):
        return {"key": key, "job": running}
    org_id = session_org(session)
    job = jobs_db.enqueue(
        session,
        PULL_KIND,
        {"key": key, "requested_by": user.email or user.id},
        org_id=org_id,
        requested_by=user.email or user.id,
        max_attempts=2,
    )
    session.commit()
    background.add_task(_run_pull, job.id, org_id)
    return {"key": key, "job": jobs_db.job_json(job)}


# ---------------------------------------------------------------------------
# Your own models
# ---------------------------------------------------------------------------


class CustomModelIn(cm.CustomModelSpec):
    #: Write-only. Omitted keeps the stored one; `clear_secret` removes it.
    auth_secret: str | None = None
    clear_secret: bool = False
    #: Seeds the rule a `CUSTOM` model gets in the `custom` pack; tuned afterwards.
    effect: Literal["block", "escalate", "redact", "allow"] = "block"
    reason: str = ""


@router.get("/custom-models")
def get_custom_models(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return {
        "models": [cm.row_json(r) for r in cm.list_models(session)],
        "prefixes": list(cm.PREFIXES),
        "timeout_ms": {"min": cm.MIN_TIMEOUT_MS, "max": cm.MAX_TIMEOUT_MS},
    }


@router.post("/custom-models", status_code=201)
def post_custom_model(
    payload: CustomModelIn,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    """Register (or update) a classifier endpoint as a detector.

    Refused with 409 when the endpoint is one this deployment may not send content
    to (egress off for a public address; a private address without
    `outbound_allow_private_hosts`; link-local never), and with 503 when a credential
    is given but this deployment cannot encrypt it.
    """
    if get_rule(session, payload.key) is not None:
        raise HTTPException(409, f"a custom rule is already called '{payload.key}'")
    refused = cm.egress_refusal(payload.url)
    if refused:
        raise HTTPException(409, refused)
    ciphertext = None
    if payload.auth_secret:
        if not payload.auth_header:
            raise HTTPException(400, "a credential needs the header it is sent in")
        try:
            ciphertext = encrypt_secret(payload.auth_secret)
        except EncryptionNotConfigured as exc:
            raise HTTPException(
                503,
                "this deployment cannot store credentials (AGENTFOX_TOKEN_ENCRYPTION_KEY "
                "is unset); it fails closed rather than storing one unencrypted",
            ) from exc
    spec = cm.CustomModelSpec(
        **payload.model_dump(exclude={"auth_secret", "clear_secret", "effect", "reason"})
    )
    row = cm.save_model(
        session,
        spec,
        actor=user.email or user.id,
        secret_ciphertext=ciphertext,
        clear_secret=payload.clear_secret,
        effect=payload.effect,
        reason=payload.reason,
    )
    return {"model": cm.row_json(row)}


class ToggleIn(BaseModel):
    enabled: bool
    reason: str = ""


@router.post("/custom-models/{key}/enabled")
def toggle_custom_model(
    key: str,
    payload: ToggleIn,
    session: Session = Depends(db),
    user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    row = cm.set_model_enabled(
        session, key, payload.enabled, actor=user.email or user.id, reason=payload.reason
    )
    if row is None:
        raise HTTPException(404, f"no model '{key}'")
    return {"model": cm.row_json(row)}


@router.delete("/custom-models/{key}")
def remove_custom_model(
    key: str, session: Session = Depends(db), user: User = Depends(require("suppressions"))
) -> dict[str, Any]:
    if not cm.delete_model(session, key, actor=user.email or user.id):
        raise HTTPException(404, f"no model '{key}'")
    return {"deleted": key}


class TestIn(BaseModel):
    text: str
    surface: str = "input"


@router.post("/custom-models/{key}/test")
def test_custom_model(
    key: str,
    payload: TestIn,
    session: Session = Depends(db),
    _user: User = Depends(require("suppressions")),
) -> dict[str, Any]:
    """Send one text to a registered model and show what it would report. Records
    nothing. A model that cannot answer is reported, not raised."""
    row = cm.get_model(session, key)
    if row is None:
        raise HTTPException(404, f"no model '{key}'")
    try:
        model = cm.compile_model(row)
    except ValidationError as exc:
        raise HTTPException(400, exc.errors()[0]["msg"]) from exc
    try:
        labels = cm.call_model(model, payload.text, payload.surface)
    except cm.ModelUnavailable as exc:
        return {"ok": False, "error": str(exc), "labels": [], "detections": []}
    return {
        "ok": True,
        "labels": [{"label": label, "score": score} for label, score in labels],
        "detections": [
            {"entity_type": d.entity_type, "score": d.score, "label": d.detail.get("label")}
            for d in cm.detections_for(model, labels, payload.text)
        ],
    }
