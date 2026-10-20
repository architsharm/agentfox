"""The first-run onboarding: Connect, See structure, Test, Protect, Retest.

Two callers. The dashboard, as the signed-in user, reads and saves progress and
starts test runs. `agentfox init --key` on the user's machine reports the map of
their agent, then stays connected and runs the attacks when asked; it presents
the onboarding key, which can do nothing else.

Distinct from ``GET /api/onboarding`` (routes/onboarding.py), the Get started
checklist, which is computed from live counts and stores nothing.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db
from agentfox.capabilities.onboarding import service
from agentfox.core.models import OnboardingSession, User, utcnow
from agentfox.core.tenancy import bind_session, system_scope

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _mine(session: Session, user: User) -> OnboardingSession:
    row = session.scalar(select(OnboardingSession).where(OnboardingSession.user_id == user.id))
    if row is None:
        row = OnboardingSession(
            user_id=user.id,
            org_id=user.org_id,
            init_key=service.new_init_key(),
            state=dict(service.INITIAL_STATE),
            runs={},
        )
        session.add(row)
        session.flush()
    return row


def _latest(row: OnboardingSession, phase: str) -> dict[str, Any] | None:
    runs = [r for r in (row.runs or {}).values() if r["phase"] == phase]
    return max(runs, key=lambda r: r["createdAt"]) if runs else None


def _test_run(row: OnboardingSession, run: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    return service.to_test_run(
        run, runner_connected=service.runner_fresh(row.runner_seen_at, now), now=now
    )


# --- The dashboard --------------------------------------------------------------


@router.get("/state")
def get_state(session: Session = Depends(db), user: User = Depends(current_user)) -> dict[str, Any]:
    return service.clean_state(_mine(session, user).state)


@router.patch("/state")
def save_state(
    body: dict[str, Any], session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    row = _mine(session, user)
    row.state = service.clean_state(body)
    return row.state


@router.delete("/state")
def reset(session: Session = Depends(db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Start over at step 1. The key survives, so a running `agentfox init` stays valid
    and re-reports its map on its next poll."""
    row = _mine(session, user)
    row.state = dict(service.INITIAL_STATE)
    row.structure = None
    row.structure_at = None
    row.runs = {}
    row.guardrails = None
    return row.state


@router.get("/key")
def get_key(session: Session = Depends(db), user: User = Depends(current_user)) -> dict[str, Any]:
    """This user's setup key, made the first time it is asked for and the same ever
    after. Always retrievable: it can only report a map and test results, so showing
    it again is safe, and a running `agentfox init` keeps working."""
    existed = (
        session.scalar(select(OnboardingSession.id).where(OnboardingSession.user_id == user.id))
        is not None
    )
    return {"value": _mine(session, user).init_key, "createdNow": not existed}


@router.get("/structure")
def get_structure(
    session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    row = _mine(session, user)
    return {
        "connected": row.structure is not None,
        # When `agentfox init` last reported its map: lets setup tell a fresh connection
        # from one made before the page was opened.
        "connectedAt": row.structure_at.isoformat() if row.structure_at else None,
        "runnerConnected": service.runner_fresh(row.runner_seen_at, utcnow()),
        "structure": row.structure or service.EMPTY_STRUCTURE,
    }


class EditedStructure(BaseModel):
    structure: dict[str, Any]


@router.put("/structure")
def save_structure(
    body: EditedStructure, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """The user added or removed an agent or tool on See structure. Tests run on this map."""
    row = _mine(session, user)
    s = body.structure
    row.structure = {k: list(s.get(k) or []) for k in ("sources", "agents", "tools", "systems")}
    return {"structure": row.structure}


class StartTest(BaseModel):
    phase: str


@router.post("/tests")
def start_test(
    body: StartTest, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    if body.phase not in ("before", "after"):
        raise HTTPException(400, "phase must be 'before' or 'after'")
    row = _mine(session, user)
    if not row.structure or not row.structure.get("tools"):
        raise HTTPException(409, "Connect an agent with at least one tool first.")
    run = service.new_run(body.phase, row.structure, utcnow())
    row.runs = {**(row.runs or {}), run["id"]: run}
    return _test_run(row, run)


@router.get("/tests")
def latest_test(
    phase: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any] | None:
    run = _latest(_mine(session, user), phase)
    return _test_run(_mine(session, user), run) if run else None


@router.get("/tests/{run_id}")
def get_test(
    run_id: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    row = _mine(session, user)
    run = (row.runs or {}).get(run_id)
    if run is None:
        raise HTTPException(404, "No such test run")
    return _test_run(row, run)


@router.get("/tests/{run_id}/results")
def test_results(
    run_id: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    run = (_mine(session, user).runs or {}).get(run_id)
    if run is None:
        raise HTTPException(404, "No such test run")
    return {"run": run["id"], "phase": run["phase"], "results": service.all_results(run)}


@router.get("/guardrails")
def get_guardrails(
    session: Session = Depends(db), user: User = Depends(current_user)
) -> list[dict[str, Any]]:
    row = _mine(session, user)
    return service.guardrails_for(row.guardrails, row.structure)


@router.post("/guardrails")
def save_guardrails(
    body: list[dict[str, Any]], session: Session = Depends(db), user: User = Depends(current_user)
) -> list[dict[str, Any]]:
    row = _mine(session, user)
    row.guardrails = [
        {"id": g.get("id"), "enabled": bool(g.get("enabled"))} for g in body if isinstance(g, dict)
    ]
    return service.guardrails_for(row.guardrails, row.structure)


# --- `agentfox init --key` --------------------------------------------------------


def runner_session(
    session: Session = Depends(db), authorization: Annotated[str | None, Header()] = None
) -> OnboardingSession:
    key = (authorization or "").removeprefix("Bearer ").removeprefix("bearer ").strip()
    if not key.startswith("afi_"):
        raise HTTPException(
            401, "Send the onboarding key from the Connect screen: Authorization: Bearer afi_…"
        )
    # Authentication is the one unavoidably cross-tenant read: whose key is this?
    with system_scope("onboarding init key", routine=True):
        row = session.scalar(select(OnboardingSession).where(OnboardingSession.init_key == key))
    if row is None:
        raise HTTPException(
            401, "That onboarding key isn't valid. Copy it again from the Connect screen."
        )
    bind_session(session, row.org_id)
    return row


class Connect(BaseModel):
    structure: dict[str, Any]
    #: The repository's name: the project its agents are grouped under.
    project: str | None = None


@router.post("/runner/connect")
def runner_connect(
    body: Connect, session: Session = Depends(db), row: OnboardingSession = Depends(runner_session)
) -> dict[str, Any]:
    s = body.structure
    structure = {k: s.get(k, []) for k in ("sources", "agents", "tools", "systems")}
    # Set it up for real: the agents and tools land in the registry, under Projects.
    row.structure = service.register_structure(session, structure, project=body.project)
    row.structure_at = utcnow()
    row.runner_seen_at = utcnow()
    return {
        "ok": True,
        "agents": len(row.structure["agents"]),
        "tools": len(row.structure["tools"]),
    }


@router.post("/runner/poll")
def runner_poll(
    session: Session = Depends(db), row: OnboardingSession = Depends(runner_session)
) -> dict[str, Any]:
    """Heartbeat, and the next test to run if one is waiting."""
    now = utcnow()
    row.runner_seen_at = now
    if row.structure is None:
        return {"needStructure": True, "job": None}
    queued = sorted(
        (r for r in (row.runs or {}).values() if r["status"] == "queued"),
        key=lambda r: r["createdAt"],
    )
    if not queued:
        return {"needStructure": False, "job": None}
    run = {**queued[0], "status": "running", "startedAt": now.isoformat()}
    row.runs = {**row.runs, run["id"]: run}
    guards = (
        [g["id"] for g in service.guardrails_for(row.guardrails, row.structure) if g["enabled"]]
        if run["phase"] == "after"
        else []
    )
    return {
        "needStructure": False,
        "job": {
            "runId": run["id"],
            "phase": run["phase"],
            "guardrails": guards,
            "structure": row.structure,
        },
    }


class Results(BaseModel):
    results: list[dict[str, Any]] = []
    done: bool = False
    error: str | None = None


@router.post("/runner/runs/{run_id}/results")
def runner_results(
    run_id: str,
    body: Results,
    session: Session = Depends(db),
    row: OnboardingSession = Depends(runner_session),
) -> dict[str, Any]:
    run = (row.runs or {}).get(run_id)
    if run is None:
        raise HTTPException(404, "No such test run")
    now = utcnow()
    row.runner_seen_at = now
    updated = service.add_results(run, body.results, done=body.done, error=body.error, now=now)
    row.runs = {**row.runs, run_id: updated}
    return {"ok": True, "status": updated["status"], "received": len(updated["results"])}
