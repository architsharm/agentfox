"""Monitors of connected sources, and where their alerts go.

Monitors are created on their own when a GitHub repository is connected and scanned,
a hosted API's spec is scanned, or an MCP server is registered. These routes list them,
add one by hand, pause, resume, retune or remove one, and run one now. The
`monitors.run` job (`agentfox.monitoring`) is what runs them on schedule.

`/api/alerts/slack` sets the tenant's own Slack incoming webhook for monitor alerts.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import AlertChannel, McpServer, Monitor, ProbeTarget, User
from agentfox.gateway.deps import current_user, db, require
from agentfox.monitoring import alerts
from agentfox.monitoring import service as monitoring
from agentfox.platform.jobs import store as jobs_db
from agentfox.platform.ledger import chain

router = APIRouter(prefix="/api", tags=["monitors"])

_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _actor(user: User) -> str:
    return user.email or user.id


def _get(session: Session, monitor_id: str) -> Monitor:
    monitor = session.get(Monitor, monitor_id)
    if monitor is None:
        raise HTTPException(404, "unknown monitor")
    return monitor


def _audit(session: Session, action: str, monitor: Monitor, user: User, **payload: Any) -> None:
    chain.append(
        session,
        action,
        actor_type="user",
        actor_id=_actor(user),
        subject_type="monitor",
        subject_id=monitor.id,
        payload={"kind": monitor.kind, "target": monitor.target, **payload},
    )


def _validate_target(session: Session, kind: str, target: str) -> dict[str, Any]:
    """Refuse a target the kind could never run, and return config the kind needs."""
    if kind == "github_repo":
        if not _REPO_NAME.match(target):
            raise HTTPException(422, "a github_repo target is 'owner/repo'")
        return {}
    if kind == "hosted_api":
        if not target.startswith(("https://", "http://")):
            raise HTTPException(422, "a hosted_api target is the OpenAPI document's http(s) URL")
        return {}
    if kind == "mcp_server":
        server = session.scalar(select(McpServer).where(McpServer.name == target))
        if server is None:
            raise HTTPException(
                404, f"no MCP server named '{target}' is registered (POST /api/mcp-servers)"
            )
        return {"mcp_server_id": server.id}
    if kind == "deployed_agent":
        target_row = session.get(ProbeTarget, target)
        if target_row is None:
            raise HTTPException(404, f"no probe target '{target}' (POST /api/probes/targets)")
        if not target_row.enabled or not target_row.opted_in_by:
            raise HTTPException(
                409, f"opt the probe target in first: POST /api/probes/targets/{target}/opt-in"
            )
        return {"probe_target_id": target_row.id, "agent": target_row.agent_slug}
    return {}


class MonitorIn(BaseModel):
    kind: str
    target: str
    name: str = ""
    interval_seconds: int | None = Field(default=None, ge=1)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class MonitorPatch(BaseModel):
    name: str | None = None
    interval_seconds: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    config: dict[str, Any] | None = None


@router.get("/monitors")
def list_monitors(
    kind: str | None = None,
    enabled: bool | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Every monitor in the tenant, with its last result and when it next runs."""
    query = select(Monitor).order_by(Monitor.kind, Monitor.target)
    if kind:
        query = query.where(Monitor.kind == kind)
    if enabled is not None:
        query = query.where(Monitor.enabled.is_(enabled))
    return {
        "monitors": [monitoring.monitor_json(m) for m in session.scalars(query)],
        "kinds": {k: spec.description for k, spec in sorted(monitoring.kinds().items())},
    }


@router.post("/monitors", status_code=201)
def create_monitor(
    payload: MonitorIn, session: Session = Depends(db), user: User = Depends(require("monitors"))
) -> dict[str, Any]:
    """Watch a source by hand. The first run stores a baseline; later runs report changes."""
    if payload.kind not in monitoring.kinds():
        raise HTTPException(
            422, f"unknown kind '{payload.kind}'. Known: {', '.join(sorted(monitoring.kinds()))}"
        )
    target = payload.target.strip()
    extra = _validate_target(session, payload.kind, target)
    if monitoring.get_monitor(session, payload.kind, target) is not None:
        raise HTTPException(409, f"{payload.kind} '{target}' is already monitored")
    monitor, _ = monitoring.ensure_monitor(
        session,
        kind=payload.kind,
        target=target,
        name=payload.name,
        config={**payload.config, **extra},
        interval_seconds=payload.interval_seconds,
        created_by=_actor(user),
    )
    monitor.enabled = payload.enabled
    session.commit()
    return monitoring.monitor_json(monitor)


@router.get("/monitors/{monitor_id}")
def get_monitor(
    monitor_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """One monitor, with the findings it raised that are still open."""
    monitor = _get(session, monitor_id)
    return {
        **monitoring.monitor_json(monitor),
        "open_findings": [
            {"id": f.id, "type": f.type, "severity": f.severity, "title": f.title}
            for f in monitoring.owned_findings(session, monitor, status="open")
        ],
    }


@router.patch("/monitors/{monitor_id}")
def update_monitor(
    monitor_id: str,
    payload: MonitorPatch,
    session: Session = Depends(db),
    user: User = Depends(require("monitors")),
) -> dict[str, Any]:
    """Rename, retune the interval, change config, or pause/resume (``enabled``)."""
    monitor = _get(session, monitor_id)
    changes = payload.model_dump(exclude_none=True)
    if "name" in changes:
        monitor.name = changes["name"]
    if "interval_seconds" in changes:
        monitor.interval_seconds = monitoring.clamp_interval(changes["interval_seconds"])
    if "config" in changes:
        monitor.config_json = {**(monitor.config_json or {}), **changes["config"]}
    if "enabled" in changes:
        monitor.enabled = changes["enabled"]
    session.flush()
    _audit(session, "monitor.updated", monitor, user, changes=changes)
    session.commit()
    return monitoring.monitor_json(monitor)


def _set_enabled(session: Session, monitor_id: str, user: User, enabled: bool) -> dict[str, Any]:
    monitor = _get(session, monitor_id)
    monitor.enabled = enabled
    session.flush()
    _audit(session, "monitor.resumed" if enabled else "monitor.paused", monitor, user)
    session.commit()
    return monitoring.monitor_json(monitor)


@router.post("/monitors/{monitor_id}/pause")
def pause_monitor(
    monitor_id: str, session: Session = Depends(db), user: User = Depends(require("monitors"))
) -> dict[str, Any]:
    """Stop scheduled runs. Open findings stay open; nothing is closed while paused."""
    return _set_enabled(session, monitor_id, user, False)


@router.post("/monitors/{monitor_id}/resume")
def resume_monitor(
    monitor_id: str, session: Session = Depends(db), user: User = Depends(require("monitors"))
) -> dict[str, Any]:
    """Resume scheduled runs from the monitor's next due time."""
    return _set_enabled(session, monitor_id, user, True)


@router.delete("/monitors/{monitor_id}")
def delete_monitor(
    monitor_id: str, session: Session = Depends(db), user: User = Depends(require("monitors"))
) -> dict[str, Any]:
    """Stop watching a source. Its findings are kept."""
    monitor = _get(session, monitor_id)
    _audit(session, "monitor.deleted", monitor, user)
    session.delete(monitor)
    session.commit()
    return {"id": monitor_id, "deleted": True}


@router.post("/monitors/{monitor_id}/run")
def run_monitor_now(
    monitor_id: str, session: Session = Depends(db), user: User = Depends(require("monitors"))
) -> dict[str, Any]:
    """Run one monitor now, through the job queue, and return its result."""
    monitor = _get(session, monitor_id)
    job = monitoring.request_run(session, monitor, trigger="manual", requested_by=_actor(user))
    session.commit()
    jobs_db.run_job(session, job)
    session.commit()
    session.refresh(monitor)
    return {"job": jobs_db.job_json(job), "monitor": monitoring.monitor_json(monitor)}


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class SlackIn(BaseModel):
    url: str
    min_severity: str = "medium"


def _slack_row(session: Session) -> AlertChannel | None:
    return session.scalar(select(AlertChannel).where(AlertChannel.kind == "slack"))


@router.get("/alerts/slack")
def get_slack(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Whether this tenant has its own Slack channel, and whether alerts can leave at all."""
    from agentfox.core.config import get_settings

    row = _slack_row(session)
    settings = get_settings()
    return {
        "configured": row is not None and bool(row.url_encrypted),
        "enabled": bool(row and row.enabled),
        "min_severity": row.min_severity if row else None,
        "deployment_channel": bool(settings.slack_webhook_url),
        "egress_allowed": settings.allow_egress,
    }


@router.put("/alerts/slack")
def set_slack(
    payload: SlackIn, session: Session = Depends(db), user: User = Depends(require("alerts"))
) -> dict[str, Any]:
    """Send this tenant's monitor alerts to its own Slack incoming webhook.

    The URL must be ``https://hooks.slack.com/services/…``; it is stored encrypted."""
    from agentfox.core.crypto import EncryptionNotConfigured, encrypt_secret

    if not alerts.is_slack_webhook(payload.url.strip()):
        raise HTTPException(
            422, "url must be a Slack incoming webhook: https://hooks.slack.com/services/…"
        )
    severity = payload.min_severity.strip().lower()
    if severity not in alerts.SEVERITY_RANK:
        raise HTTPException(422, f"min_severity must be one of {', '.join(alerts.SEVERITY_RANK)}")
    try:
        sealed = encrypt_secret(payload.url.strip())
    except EncryptionNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    row = _slack_row(session)
    if row is None:
        row = AlertChannel(kind="slack", created_by=_actor(user))
        session.add(row)
    row.url_encrypted = sealed
    row.min_severity = severity
    row.enabled = True
    session.flush()
    chain.append(
        session,
        "alerts.slack.configured",
        actor_type="user",
        actor_id=_actor(user),
        subject_type="alert_channel",
        subject_id=row.id,
        payload={"min_severity": severity},
    )
    session.commit()
    return {"configured": True, "min_severity": severity}


@router.delete("/alerts/slack")
def delete_slack(
    session: Session = Depends(db), user: User = Depends(require("alerts"))
) -> dict[str, Any]:
    """Stop sending this tenant's alerts to its own Slack channel."""
    row = _slack_row(session)
    if row is None:
        raise HTTPException(404, "no Slack channel is configured")
    chain.append(
        session,
        "alerts.slack.removed",
        actor_type="user",
        actor_id=_actor(user),
        subject_type="alert_channel",
        subject_id=row.id,
    )
    session.delete(row)
    session.commit()
    return {"configured": False}


@router.post("/alerts/slack/test")
def test_slack(
    session: Session = Depends(db), _user: User = Depends(require("alerts"))
) -> dict[str, Any]:
    """Send a test message to every channel this tenant's alerts go to, now."""
    return {"results": alerts.send_test(session)}
