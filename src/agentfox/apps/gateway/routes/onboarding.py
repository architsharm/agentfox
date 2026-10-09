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
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import ScalarSelect

from agentfox.apps.gateway.deps import current_user, db
from agentfox.apps.gateway.routes.integrations import LOGIN_TOKEN_NAME
from agentfox.capabilities.protection import layer_key as protection_layer_key
from agentfox.core.models import (
    Agent,
    ApiToken,
    Capability,
    Decision,
    Finding,
    GithubConnection,
    Handoff,
    KnowledgeBoundary,
    Policy,
    PolicyBinding,
    PolicyVersion,
    ScanRun,
    SourceRecord,
    Trace,
    utcnow,
)

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


#: Above this, a count is reported as "at least this many" rather than counted to
#: the end. The checklist needs "is there any"; the numbers beside it are context.
#: A plain count(*) over a tenant's whole decisions table is a sequential read that
#: grows with traffic, and Get started is the page a new user waits on.
COUNT_CAP = 10_000


def _capped(stmt: Select[Any]) -> ScalarSelect[Any]:
    """``count(*)`` of at most ``COUNT_CAP`` rows, as a scalar subquery."""
    limited = stmt.limit(COUNT_CAP).subquery()
    return select(func.count()).select_from(limited).scalar_subquery()


def _count(model: Any, *where: Any) -> ScalarSelect[Any]:
    return select(func.count()).select_from(model).where(*where).scalar_subquery()


def _onboarding_counts(session: Session) -> dict[str, int]:
    """Every number the checklist needs, in one round trip.

    Eleven separate ``count(*)`` statements plus a parse of every bound policy
    document was twelve-plus database round trips; against a remote database
    (Neon from a serverless function) the latency of each one, not the work, was
    what the page waited on. Tenant isolation still applies: the session's
    ``with_loader_criteria`` reaches every entity in the statement, subqueries
    included.
    """
    now = utcnow()
    # "Turn enforcement on" is about baseline, the content policies. Read the
    # binding's mode directly instead of loading and parsing every bound document.
    baseline_enforcing = (
        select(func.count())
        .select_from(PolicyBinding)
        .join(PolicyVersion, PolicyVersion.id == PolicyBinding.policy_version_id)
        .join(Policy, Policy.id == PolicyVersion.policy_id)
        .where(
            Policy.key == "baseline",
            PolicyBinding.mode == "enforce",
            PolicyBinding.effective_from <= now,
            (PolicyBinding.effective_to.is_(None)) | (PolicyBinding.effective_to > now),
        )
        .scalar_subquery()
    )
    row = session.execute(
        select(
            _count(Agent).label("agents"),
            _capped(select(Trace.id)).label("traces"),
            _capped(select(Decision.id)).label("decisions"),
            _capped(select(Decision.id).where(Decision.mode == "enforce")).label("enforcing"),
            baseline_enforcing.label("baseline_enforcing"),
            _count(KnowledgeBoundary).label("boundaries"),
            _count(SourceRecord).label("sources"),
            _count(Handoff).label("handoffs"),
            _count(Finding, Finding.status == "open").label("open_findings"),
            _count(GithubConnection).label("github_connections"),
            _count(ScanRun, ScanRun.source_kind == "hosted_api").label("hosted_api_scans"),
            _count(
                ApiToken,
                ApiToken.revoked_at.is_(None),
                ApiToken.name != LOGIN_TOKEN_NAME,
                (ApiToken.expires_at.is_(None)) | (ApiToken.expires_at > now),
            ).label("api_keys"),
            _count(Capability, Capability.tool_key.not_like("redteam.%")).label("grants"),
            _count(Policy, Policy.key.like(f"{protection_layer_key('')}%")).label("protected"),
        )
    ).one()
    return {k: int(v or 0) for k, v in row._mapping.items()}


@router.get("/onboarding")
def onboarding(session: Session = Depends(db), _user=Depends(current_user)) -> dict[str, Any]:
    """Install state as a checklist, computed live.

    Every step is derived from data, never from a stored "completed" flag — a
    checklist that can disagree with the system is worse than none.

    The steps are the order a developer does it in on the Get started page, and
    each one can be finished there in the browser; ``command`` is the same step
    from the command line, for whoever prefers it.
    """
    c = _onboarding_counts(session)
    traces = c["traces"]

    steps = [
        {
            "id": "agent",
            "title": "Register your agent",
            "done": c["agents"] > 0,
            "command": "agentfox agents register my-agent",
            "detail": "A name for the traffic, an owner, and a risk tier.",
        },
        {
            "id": "key",
            "title": "Create an API key",
            "done": c["api_keys"] > 0,
            "command": "POST /api/tokens",
            "detail": "Your code sends it as a bearer token. It is shown once.",
        },
        {
            "id": "instrument",
            "title": "Send the first request",
            "done": traces > 0,
            "command": "POST /v1/guard/tool_call",
            "detail": (
                "Your agent keeps making its own model calls and asks the gateway for a "
                "verdict before it acts. Content policies watch without blocking; tool "
                "grants apply from the first call."
            ),
        },
        {
            "id": "protect",
            "title": "Grant tools and choose protections",
            "done": c["grants"] > 0 or c["protected"] > 0,
            "command": "agentfox permit grant my-agent <tool>",
            "detail": "Anything not granted is refused. Protections start by watching.",
        },
        {
            "id": "boundary",
            "title": "Declare what your agent can answer",
            "done": c["boundaries"] > 0,
            "command": "agentfox declare boundary my-agent",
            "detail": (
                "Without a knowledge boundary nothing stops an agent inventing an answer "
                "to a question it has no data for."
            ),
        },
        {
            "id": "enforce",
            "title": "Turn enforcement on",
            "done": c["baseline_enforcing"] > 0,
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
        "count_cap": COUNT_CAP,
        "counts": {
            "agents": c["agents"],
            "traces": traces,
            "decisions": c["decisions"],
            "enforcing": c["enforcing"],
            "boundaries": c["boundaries"],
            "sources": c["sources"],
            "handoffs": c["handoffs"],
            "open_findings": c["open_findings"],
            "github_connections": c["github_connections"],
            "hosted_api_scans": c["hosted_api_scans"],
            "api_keys": c["api_keys"],
            "grants": c["grants"],
            "protected_agents": c["protected"],
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

    # Same definition as registry.service.detect_shadow_agents: a scan-proposed draft
    # (and a draft somebody rejected) is unregistered but never ran, so it is waiting
    # for review on the agents page, not "running and never registered".
    shadow = list(
        session.scalars(
            select(Agent).where(
                Agent.registered.is_(False), Agent.status.notin_(("draft", "rejected"))
            )
        )
    )
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
