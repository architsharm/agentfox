"""What the control plane shows someone on their first visit.

An empty dashboard is the most common reason a governance tool gets abandoned: the
evaluator installs it, sees zero of everything, and has no way to tell whether that
means "nothing is wrong" or "nothing is connected". The two look identical, and only
one of them is good news.

So this endpoint answers a single question — *what is the next thing to do?* — and
the UI renders it as a checklist rather than a set of empty charts. Each step reports
whether it is done, from live data rather than a stored flag, so the checklist cannot
drift from reality.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import (
    Agent,
    Decision,
    Finding,
    GithubConnection,
    Handoff,
    KnowledgeBoundary,
    ScanRun,
    SourceRecord,
    Trace,
    utcnow,
)
from ..deps import current_user, db

router = APIRouter(prefix="/api", tags=["platform"])


@router.get("/me")
def me(session: Session = Depends(db), user=Depends(current_user)) -> dict[str, Any]:
    """The signed-in identity, for the account menu.

    A bare 'Sign out' link with nothing else in the account area leaves a multi-user
    product with no visible answer to "who am I, and whose data is this" — this backs
    that answer. `workspace` is the connected GitHub login when there is one (the
    thing a solo/team GitHub account actually reads as a workspace name to a user),
    falling back to the raw org id.
    """
    connection = session.scalar(
        select(GithubConnection).order_by(GithubConnection.created_at.desc())
    )
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "org_id": user.org_id,
        "workspace": connection.github_login if connection else user.org_id,
    }


@router.get("/onboarding")
def onboarding(session: Session = Depends(db), _user=Depends(current_user)) -> dict[str, Any]:
    """Install state as a checklist, computed live.

    Every step is derived from data, never from a stored "completed" flag — a
    checklist that can disagree with the system is worse than none.
    """
    agents = session.scalar(select(func.count()).select_from(Agent)) or 0
    traces = session.scalar(select(func.count()).select_from(Trace)) or 0
    decisions = session.scalar(select(func.count()).select_from(Decision)) or 0
    enforcing = (
        session.scalar(select(func.count()).select_from(Decision).where(Decision.mode == "enforce"))
        or 0
    )
    boundaries = session.scalar(select(func.count()).select_from(KnowledgeBoundary)) or 0
    sources = session.scalar(select(func.count()).select_from(SourceRecord)) or 0
    handoffs = session.scalar(select(func.count()).select_from(Handoff)) or 0
    open_findings = (
        session.scalar(select(func.count()).select_from(Finding).where(Finding.status == "open"))
        or 0
    )
    connections = session.scalar(select(func.count()).select_from(GithubConnection)) or 0
    hosted_api_scans = (
        session.scalar(
            select(func.count()).select_from(ScanRun).where(ScanRun.source_kind == "hosted_api")
        )
        or 0
    )

    steps = [
        {
            "id": "connect",
            "title": "Connect a repo, point at a hosted API, or instrument it — whichever fits",
            "done": connections > 0 or hosted_api_scans > 0,
            "command": "Connect → repo or hosted API → Scan",
            "detail": (
                "Read only: source is parsed, never run; a hosted API is read from its "
                "OpenAPI document, never called. Nothing goes live until you approve it."
            ),
        },
        {
            "id": "instrument",
            "title": "Govern your agent",
            "done": traces > 0,
            "command": "POST /v1/guard/input  (or: import agentfox; agentfox.auto())",
            "detail": (
                "Your agent keeps making its own model calls and asks this service for a "
                "verdict. In Python, one line in your entry point does it. Content "
                "policies watch without blocking; tool grants apply from the first call."
            ),
        },
        {
            "id": "install",
            "title": "Run it yourself, if you want it in your own infrastructure",
            "done": agents > 0,
            # `pip install agentfox` from 0.3.1 on. It was a git+https URL until
            # then, because release.yml published a GitHub Release and nothing to
            # PyPI, so the obvious command failed with "No matching distribution
            # found" for everyone who copied it. The release workflow now uploads
            # via Trusted Publishing. Same line as the README and the site.
            "command": (
                "pip install agentfox"
                " && agentfox init"
            ),
            "detail": (
                "Optional. Everything above already works over HTTP. Install it for the "
                "command line, the Python one-liner, or your own control plane."
            ),
        },
        {
            "id": "review",
            "title": "Review what it found",
            "done": decisions > 0,
            "command": "agentfox findings",
            "detail": "Decisions and findings from real traffic, not from a sample dataset.",
        },
        {
            "id": "boundary",
            "title": "Declare what your agent can answer",
            "done": boundaries > 0,
            "command": "PUT /api/answerability/boundary",
            "detail": (
                "Without a knowledge boundary nothing stops an agent inventing an answer "
                "to a question it has no data for."
            ),
        },
        {
            "id": "sources",
            "title": "Tier your sources",
            "done": sources > 0,
            "command": "register_source(...)",
            "detail": (
                "Groundedness checks the answer against the context and never asks whether "
                "the context was authoritative."
            ),
        },
        {
            "id": "enforce",
            "title": "Turn enforcement on",
            "done": enforcing > 0,
            "command": "agentfox policy enforce baseline",
            "detail": (
                "Promotes prompt injection, PII and safety from observe to enforce. Do it "
                "when the findings look right. Tool containment already enforces."
            ),
        },
    ]

    next_step = next((s for s in steps if not s["done"]), None)
    return {
        "steps": steps,
        "completed": sum(1 for s in steps if s["done"]),
        "total": len(steps),
        "next": next_step,
        # The distinction that makes an empty dashboard readable: connected-and-quiet
        # is good news, not-connected is a to-do, and they must not look the same.
        "connected": traces > 0,
        "counts": {
            "agents": agents,
            "traces": traces,
            "decisions": decisions,
            "enforcing": enforcing,
            "boundaries": boundaries,
            "sources": sources,
            "handoffs": handoffs,
            "open_findings": open_findings,
            "github_connections": connections,
        },
    }


@router.get("/attention")
def attention(
    hours: int = 24, session: Session = Depends(db), _user=Depends(current_user)
) -> dict[str, Any]:
    """What needs a human, ranked. The home page is built from this.

    An inventory answers "what do we have"; nobody opens a dashboard to ask that. They
    open it to ask "is anything wrong right now", and a screen that leads with counts
    makes them do the ranking themselves.
    """
    # Where the dashboard lives. The gateway hands back links the UI renders
    # directly, which couples the API to the UI's routing — stated here rather
    # than spread across three f-strings, so a move is one edit and not a hunt.
    # Every private route sits under this prefix (dashboard/middleware.ts).
    UI = "/app"

    since = utcnow() - dt.timedelta(hours=hours)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    items: list[dict[str, Any]] = []

    findings = list(
        session.scalars(
            select(Finding)
            .where(Finding.status == "open")
            .order_by(Finding.created_at.desc())
            .limit(50)
        )
    )
    agents = {a.id: a.slug for a in session.scalars(select(Agent))}
    for finding in findings:
        items.append(
            {
                "kind": "finding",
                "severity": finding.severity,
                "title": finding.title,
                "type": finding.type,
                "subject": agents.get(finding.subject_id or "", finding.subject_type),
                "at": finding.created_at.isoformat(),
                "href": f"{UI}/findings/{finding.id}",
            }
        )

    # A hand-off past its SLA is a person waiting, which outranks most findings.
    for handoff in session.scalars(select(Handoff).where(Handoff.status == "breached")):
        items.append(
            {
                "kind": "handoff",
                "severity": "high",
                "title": f"Hand-off unacknowledged past its {handoff.owner_role} SLA",
                "type": "handoff_sla_breach",
                "subject": agents.get(handoff.agent_id or "", "agent"),
                "at": handoff.created_at.isoformat(),
                "href": f"{UI}/approvals?tab=escalation",
            }
        )

    shadow = list(session.scalars(select(Agent).where(Agent.registered.is_(False))))
    for agent in shadow:
        items.append(
            {
                "kind": "shadow_agent",
                "severity": "high",
                "title": f"'{agent.slug}' is running and was never registered",
                "type": "shadow_agent",
                "subject": agent.slug,
                "at": agent.first_seen_at.isoformat() if agent.first_seen_at else "",
                "href": f"{UI}/agents",
            }
        )

    items.sort(key=lambda i: (order.get(i["severity"], 9), i["at"]), reverse=False)
    blocked = (
        session.scalar(
            select(func.count())
            .select_from(Decision)
            .where(Decision.verdict == "block", Decision.created_at >= since)
        )
        or 0
    )
    observed_blocks = (
        session.scalar(
            select(func.count())
            .select_from(Decision)
            .where(Decision.mode == "observe", Decision.created_at >= since)
        )
        or 0
    )
    return {
        "window_hours": hours,
        "items": items[:25],
        "total": len(items),
        "counts": {
            "critical": sum(1 for i in items if i["severity"] == "critical"),
            "high": sum(1 for i in items if i["severity"] == "high"),
            "blocked_in_window": blocked,
            "observed_in_window": observed_blocks,
        },
        "quiet": not items,
    }
