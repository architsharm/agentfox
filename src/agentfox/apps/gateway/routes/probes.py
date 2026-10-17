"""Live red-team probes against deployed agents, and the public showcase.

Two routers:

``/api/probes/*`` (authenticated)
    Register a probe target for a registered agent, opt in or out, run it now, and
    read its campaigns. Registering creates a **disabled** target. Opting in is a
    separate call that has to carry the exact warning text from
    ``GET /api/probes/warning``, and records the caller's email with it — so "who
    agreed to send attacks at this endpoint" always has an answer. Writing is the
    ``probes`` family (owner, admin, security): pointing adversarial traffic at a
    running system is a security decision, like silencing a detector.

``GET /api/public/showcase`` (unauthenticated)
    The marketing site's /live page. Reads only the showcase tenant
    (`evaluation.showcase`), returns counts and probe keys and nothing else, is cached
    in process for a minute and rate limited per client address.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps import showcase
from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.apps.gateway.playground_sessions import RateLimiter
from agentfox.capabilities.evaluation import live_probes
from agentfox.core.crypto import EncryptionNotConfigured
from agentfox.core.models import ProbeTarget, RedTeamCampaign, User, as_aware, utcnow

router = APIRouter(prefix="/api/probes", tags=["probes"])
public_router = APIRouter(prefix="/api/public", tags=["public"])

#: Requests per client address per minute for the public showcase. The response is
#: cached, so this bounds request volume rather than database work.
showcase_limiter = RateLimiter(limit=30, window_seconds=60)


def _actor(user: User) -> str:
    return user.email or user.id


def _get_target(session: Session, target_id: str) -> ProbeTarget:
    target = session.get(ProbeTarget, target_id)
    if target is None:
        raise HTTPException(404, "unknown probe target")
    return target


@router.get("/warning")
def warning(_user: User = Depends(current_user)) -> dict[str, Any]:
    """What a person must read before enabling probes, plus the probe library, the
    hard caps and the adapter contract a target endpoint has to speak."""
    return {
        "warning": live_probes.OPT_IN_WARNING,
        "what_this_measures": live_probes.WHAT_THIS_MEASURES,
        "probes": [
            {
                "key": p.key,
                "category": p.category,
                "severity": p.severity,
                "owasp_id": p.owasp_id,
                "description": p.description,
                "expect_blocked": p.expect_blocked,
            }
            for p in live_probes.LIVE_PROBES
        ],
        "caps": {
            "max_probes_per_run": live_probes.MAX_PROBES_PER_RUN_CAP,
            "max_rate_per_minute": live_probes.MAX_RATE_PER_MINUTE_CAP,
            "min_interval_seconds": live_probes.MIN_INTERVAL_SECONDS,
            "max_timeout_seconds": live_probes.MAX_TIMEOUT_SECONDS,
            "min_manual_gap_seconds": live_probes.MIN_MANUAL_GAP_SECONDS,
        },
        "contract": {
            "request": {"message": "str", "probe": {"id": "str", "campaign": "str"}},
            "response": {
                "reply": "str | null",
                "tool_calls": [{"name": "str", "arguments": "object"}],
                "blocked": "bool (optional)",
            },
            "headers": ["X-AgentFox-Probe: <campaign id>", "Authorization (if stored)"],
        },
    }


class TargetCreate(BaseModel):
    agent: str
    adapter: str = "http"
    url: str | None = None
    name: str = ""
    model: str | None = None
    #: Sent as the `Authorization` header to an http target. Stored encrypted.
    auth_header: str | None = None
    forbidden_tools: list[str] = Field(default_factory=list)
    leak_markers: list[str] = Field(default_factory=list)
    probes: list[str] | None = None
    interval_seconds: int | None = None
    max_probes_per_run: int | None = None
    rate_limit_per_minute: int | None = None
    timeout_seconds: float | None = None


@router.get("/targets")
def list_targets(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    rows = session.scalars(select(ProbeTarget).order_by(ProbeTarget.created_at))
    return {"targets": [live_probes.target_json(t) for t in rows]}


@router.post("/targets", status_code=201)
def create_target(
    payload: TargetCreate,
    session: Session = Depends(db),
    user: User = Depends(require("probes")),
) -> dict[str, Any]:
    """Register a target. It is created disabled; nothing is sent until opt-in."""
    try:
        target = live_probes.register_target(
            session,
            agent_slug=payload.agent,
            adapter=payload.adapter,
            url=payload.url,
            name=payload.name,
            model=payload.model,
            auth_header=payload.auth_header,
            config={
                "forbidden_tools": payload.forbidden_tools,
                "leak_markers": payload.leak_markers,
                "probes": payload.probes,
            },
            created_by=_actor(user),
            interval_seconds=payload.interval_seconds,
            max_probes_per_run=payload.max_probes_per_run,
            rate_limit_per_minute=payload.rate_limit_per_minute,
            timeout_seconds=payload.timeout_seconds,
        )
    except live_probes.ProbeTargetError as exc:
        raise HTTPException(422, str(exc)) from exc
    except EncryptionNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        **live_probes.target_json(target),
        "warning": live_probes.OPT_IN_WARNING,
        "next_step": f"POST /api/probes/targets/{target.id}/opt-in with the warning text "
        "as 'acknowledgement' to enable probing",
    }


@router.get("/targets/{target_id}")
def get_target(
    target_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    return live_probes.target_json(_get_target(session, target_id))


class TargetUpdate(BaseModel):
    #: A new URL clears the opt-in: consent was given for the old host.
    url: str | None = None
    forbidden_tools: list[str] | None = None
    leak_markers: list[str] | None = None
    probes: list[str] | None = None
    interval_seconds: int | None = None
    max_probes_per_run: int | None = None
    rate_limit_per_minute: int | None = None
    timeout_seconds: float | None = None


@router.patch("/targets/{target_id}")
def update_target(
    target_id: str,
    payload: TargetUpdate,
    session: Session = Depends(db),
    user: User = Depends(require("probes")),
) -> dict[str, Any]:
    target = _get_target(session, target_id)
    try:
        if payload.url is not None and payload.url != target.url:
            live_probes.update_url(session, target, payload.url, actor=_actor(user))
        config = dict(target.config_json or {})
        for key in ("forbidden_tools", "leak_markers", "probes"):
            value = getattr(payload, key)
            if value is not None:
                config[key] = value
        target.config_json = live_probes._clean_config(config)
        limits = live_probes.clamp_limits(
            interval_seconds=payload.interval_seconds or target.interval_seconds,
            max_probes_per_run=payload.max_probes_per_run or target.max_probes_per_run,
            rate_limit_per_minute=payload.rate_limit_per_minute or target.rate_limit_per_minute,
            timeout_seconds=payload.timeout_seconds or target.timeout_seconds,
        )
    except live_probes.ProbeTargetError as exc:
        raise HTTPException(422, str(exc)) from exc
    for key, value in limits.items():
        setattr(target, key, value)
    session.flush()
    return live_probes.target_json(target)


class OptIn(BaseModel):
    acknowledgement: str


@router.post("/targets/{target_id}/opt-in")
def opt_in(
    target_id: str,
    payload: OptIn,
    session: Session = Depends(db),
    user: User = Depends(require("probes")),
) -> dict[str, Any]:
    target = _get_target(session, target_id)
    try:
        live_probes.opt_in(
            session, target, actor=_actor(user), acknowledgement=payload.acknowledgement
        )
    except live_probes.ProbeTargetError as exc:
        raise HTTPException(422, str(exc)) from exc
    return live_probes.target_json(target)


@router.post("/targets/{target_id}/opt-out")
def opt_out(
    target_id: str, session: Session = Depends(db), user: User = Depends(require("probes"))
) -> dict[str, Any]:
    target = _get_target(session, target_id)
    live_probes.opt_out(session, target, actor=_actor(user))
    return live_probes.target_json(target)


@router.post("/targets/{target_id}/run")
def run_now(
    target_id: str, session: Session = Depends(db), user: User = Depends(require("probes"))
) -> dict[str, Any]:
    """Probe the target now. Same consent and caps as a scheduled run, and refused
    within `MIN_MANUAL_GAP_SECONDS` of the previous run."""
    target = _get_target(session, target_id)
    last = as_aware(target.last_run_at)
    gap = dt.timedelta(seconds=live_probes.MIN_MANUAL_GAP_SECONDS)
    if last is not None and utcnow() - last < gap:
        raise HTTPException(
            429,
            f"this target was probed at {last.isoformat()}; wait "
            f"{live_probes.MIN_MANUAL_GAP_SECONDS // 60} minutes between runs",
        )
    try:
        campaign = live_probes.run_target(session, target, actor_type="user", actor_id=_actor(user))
    except live_probes.ProbeTargetError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"campaign_id": campaign.id, **(campaign.summary_json or {})}


@router.get("/targets/{target_id}/campaigns")
def campaigns(
    target_id: str,
    limit: int = 20,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    target = _get_target(session, target_id)
    rows = [
        c
        for c in session.scalars(
            select(RedTeamCampaign)
            .where(RedTeamCampaign.runner == live_probes.RUNNER)
            .order_by(RedTeamCampaign.created_at.desc(), RedTeamCampaign.id.desc())
            .limit(500)
        )
        if (c.target_json or {}).get("target_id") == target.id
    ][: max(1, min(limit, 100))]
    return {
        "campaigns": [
            {
                "id": c.id,
                "status": c.status,
                "finished_at": (as_aware(c.finished_at) or utcnow()).isoformat()
                if c.finished_at
                else None,
                **(c.summary_json or {}),
            }
            for c in rows
        ]
    }


@public_router.get("/showcase")
def public_showcase(
    request: Request, response: Response, session: Session = Depends(db)
) -> dict[str, Any]:
    """AgentFox probing its own demo agent: recent runs, attacks attempted, contained
    and escaped, findings opened and closed. Unauthenticated and read-only; returns
    ``{"enabled": false}`` on a deployment that does not run the showcase."""
    client = request.client.host if request.client else "unknown"
    if not showcase_limiter.check(client):
        raise HTTPException(429, "Too many requests — this page updates once a minute.")
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=300"
    return showcase.public_summary(session)
