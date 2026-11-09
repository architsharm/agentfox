"""The first-run onboarding: Connect, See structure, Test, Protect, Retest.

Two callers. The dashboard, as the signed-in user, reads and saves progress and
starts test runs. `agentfox init --key` on the user's machine reports the map of
their agent, then stays connected and runs the attacks when asked; it presents
the setup key (``capabilities/onboarding/keys.py``), which acts for the user who
made it and can do nothing but propose agents and report test results.

Reading never writes: a user with no onboarding row yet gets the defaults, and the
row is made on their first write (``capabilities/onboarding/sessions.py``).

Distinct from ``GET /api/onboarding`` (routes/onboarding.py), the Get started
checklist, which is computed from live counts and stores nothing.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import WRITE_ROLES, current_user, db, may_enforce, require
from agentfox.capabilities.onboarding import keys, runs, service, sessions
from agentfox.capabilities.onboarding.attacks import library
from agentfox.capabilities.onboarding.schema import (
    Connect,
    GuardCheck,
    Poll,
    Results,
    Structure,
)
from agentfox.core.db import sqlite_write_lock
from agentfox.core.models import OnboardingRun, OnboardingSession, User, utcnow
from agentfox.core.tenancy import bind_session

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _runner_connected(seen: Any) -> bool:
    return service.runner_fresh(seen, utcnow())


def _show(run: OnboardingRun, *, runner_seen: Any, agent: str | None = None) -> dict[str, Any]:
    now = utcnow()
    return service.to_test_run(
        runs.view(run, now),
        runner_connected=service.runner_fresh(runner_seen, now),
        now=now,
        agent=agent,
    )


def _runner_seen(session: Session, run: OnboardingRun, row: OnboardingSession | None) -> Any:
    if run.project:
        project = sessions.find_project(session, run.project)
        if project is not None:
            return project.runner_seen_at
    return row.runner_seen_at if row else None


# --- The dashboard --------------------------------------------------------------


@router.get("/state")
def get_state(session: Session = Depends(db), user: User = Depends(current_user)) -> dict[str, Any]:
    row = sessions.find(session, user)
    return service.clean_state(row.state if row else None)


@router.patch("/state")
def save_state(
    body: dict[str, Any], session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    row = sessions.ensure(session, user)
    # The setup wizard saves its steps; the projects' chosen attack sets stay.
    row.state = service.clean_state({"tests": (row.state or {}).get("tests"), **body})
    return row.state


@router.delete("/state")
def reset(session: Session = Depends(db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Start over at step 1. The key survives, so a running `agentfox init` stays valid
    and re-reports its map on its next poll."""
    row = sessions.find(session, user)
    if row is None:
        return dict(service.INITIAL_STATE)
    row.state = dict(service.INITIAL_STATE)
    row.structure = None
    row.structure_at = None
    row.guardrails = None
    # The setup wizard's own runs; a project's tests belong to the project.
    for run in runs.for_user(session, user.id):
        if run.project is None:
            session.delete(run)
    return row.state


@router.get("/key")
def get_key(
    peek: bool = False,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """This user's setup key. Made the first time it is asked for (or after the last
    one expired or was revoked), and then shown in full that once: ``value`` is null
    on every later call, which returns the key's ``prefix``, ``createdAt`` and
    ``expiresAt`` instead. ``POST /key/rotate`` replaces it.

    ``peek=1`` only reads: it says whether a key exists and never makes one, so the
    setup card can show it on load without opening the page minting a key.

    Minting one needs the registry write role, because what it does is propose agents."""
    token = keys.live_key(session, user)
    if token is not None or peek:
        return keys.describe(token)
    row = sessions.ensure(session, user)
    token, raw = keys.mint(session, user, row, reason="setup key made for `agentfox init`")
    return keys.describe(token, raw)


@router.post("/key/rotate")
def rotate_key(
    session: Session = Depends(db), user: User = Depends(require("registry"))
) -> dict[str, Any]:
    """Revoke this user's setup key and make a new one, shown in full this once. A
    running `agentfox init` with the old key stops being accepted."""
    row = sessions.ensure(session, user)
    token, raw = keys.mint(session, user, row, reason="setup key rotated")
    return keys.describe(token, raw)


@router.get("/structure")
def get_structure(
    session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    row = sessions.find(session, user)
    structure = row.structure if row else None
    return {
        "connected": structure is not None,
        # The agents this init found that still wait to be added: the dashboard keeps
        # asking to add them until someone does (or dismisses the prompt), on any page.
        "pending": _pending(session, structure),
        # When `agentfox init` last reported its map: lets setup tell a fresh connection
        # from one made before the page was opened.
        "connectedAt": row.structure_at.isoformat() if row and row.structure_at else None,
        "runnerConnected": _runner_connected(row.runner_seen_at if row else None),
        "structure": structure or service.EMPTY_STRUCTURE,
    }


def _pending(session: Session, structure: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The agents of the last reported map that are still drafts (proposed, not added)."""
    from sqlalchemy import select

    from agentfox.core.models import Agent

    slugs = [a["slug"] for a in (structure or {}).get("agents", []) if a.get("slug")]
    if not slugs:
        return []
    rows = session.scalars(select(Agent).where(Agent.slug.in_(slugs), Agent.status == "draft"))
    drafts = {a.slug: a for a in rows}
    return [{"slug": s, "name": drafts[s].name or s} for s in slugs if s in drafts]


class EditedStructure(BaseModel):
    structure: Structure


@router.put("/structure")
def save_structure(
    body: EditedStructure, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """The user added or removed an agent or tool on See structure. Tests run on this map."""
    row = sessions.ensure(session, user)
    project = (row.structure or {}).get("project")
    row.structure = body.structure.as_dict()
    if project:
        row.structure["project"] = project
    return {"structure": row.structure}


class StartTest(BaseModel):
    phase: str


@router.post("/tests")
def start_test(
    body: StartTest, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    if body.phase not in ("before", "after"):
        raise HTTPException(400, "phase must be 'before' or 'after'")
    row = sessions.find(session, user)
    if row is None or not row.structure or not row.structure.get("tools"):
        raise HTTPException(409, "Connect an agent with at least one tool first.")
    # An "after" test checks the agents' real policies (`/runner/runs/{id}/guard`);
    # nothing chosen here is simulated.
    run = runs.create(
        session,
        user_id=user.id,
        org_id=user.org_id,
        phase=body.phase,
        structure=row.structure,
        now=utcnow(),
        guards=[],
    )
    return _show(run, runner_seen=row.runner_seen_at)


@router.get("/tests")
def latest_test(
    phase: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any] | None:
    mine = [r for r in runs.for_user(session, user.id) if r.phase == phase]
    if not mine:
        return None
    return _show(
        mine[-1], runner_seen=_runner_seen(session, mine[-1], sessions.find(session, user))
    )


def _visible_run(session: Session, user: User, run_id: str) -> OnboardingRun:
    """A run this user may see: their own, or any of their workspace's projects'."""
    run = session.get(OnboardingRun, run_id)
    if run is None or (run.project is None and run.user_id != user.id):
        raise HTTPException(404, "No such test run")
    return run


@router.get("/tests/{run_id}")
def get_test(
    run_id: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    run = _visible_run(session, user, run_id)
    return _show(run, runner_seen=_runner_seen(session, run, sessions.find(session, user)))


@router.get("/tests/{run_id}/results")
def test_results(
    run_id: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    run = _visible_run(session, user, run_id)
    return {"run": run.id, "phase": run.phase, "results": service.all_results(runs.as_dict(run))}


@router.get("/guardrails")
def get_guardrails(
    session: Session = Depends(db), user: User = Depends(current_user)
) -> list[dict[str, Any]]:
    """The setup wizard's suggested guardrails, as a list to show. No test reads them:
    an "after" test checks the agents' real policies. Kept so the wizard still loads."""
    row = sessions.find(session, user)
    return service.guardrails_for(row.guardrails if row else None, row.structure if row else None)


@router.post("/guardrails")
def save_guardrails(
    body: list[dict[str, Any]], session: Session = Depends(db), user: User = Depends(current_user)
) -> list[dict[str, Any]]:
    """Saves the wizard's toggles. They change what the wizard shows, nothing else."""
    row = sessions.ensure(session, user)
    row.guardrails = [
        {"id": str(g.get("id"))[:120], "enabled": bool(g.get("enabled"))}
        for g in body[:200]
        if isinstance(g, dict)
    ]
    return service.guardrails_for(row.guardrails, row.structure)


# --- A project's attack tests, for the map's panel -------------------------------


def _basic(session: Session, project: str) -> tuple[bool, bool]:
    """(on, enforcing) for the project's basic guardrails: on when every agent has
    them, watching or blocking; enforcing when every agent's block."""
    from agentfox.platform.registry.projects import project_agents

    agents = project_agents(session, project)
    modes = [service.basic_mode(session, a.slug) for a in agents]
    return (
        bool(agents) and all(m is not None for m in modes),
        bool(agents) and all(m == "enforce" for m in modes),
    )


def _previous(
    phase_runs: list[OnboardingRun], seen: Any, agent: str | None = None
) -> dict[str, Any] | None:
    """The latest finished run before ``phase_runs[-1]``, when that one is still going."""
    if not phase_runs or phase_runs[-1].status not in runs.ACTIVE:
        return None
    if runs.stale_reason(phase_runs[-1], utcnow()):
        return None  # shown as failed already: nothing is running
    finished = [r for r in phase_runs[:-1] if r.status in runs.TERMINAL]
    return _show(finished[-1], runner_seen=seen, agent=agent) if finished else None


@router.get("/projects/{project}/tests")
def project_tests(
    project: str,
    agent: str | None = None,
    session: Session = Depends(db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """The project's first test (as it was) and its latest one with the basic
    guardrails, whether those are on (``basicOn``: watching or blocking;
    ``basicEnforcing``: blocking), and whether this project's `agentfox init` is
    connected (only it can run a test).

    ``agent`` (a slug): each run as that agent saw it, its own attacks and results
    only. The test covers every agent in the project; an agent's page shows its own."""
    row = sessions.find(session, user)
    connected = sessions.find_project(session, project)
    seen = connected.runner_seen_at if connected else None
    project_runs = runs.for_project(session, project)
    # The latest test without the basic guardrails (a failed one tried again replaces it).
    before = [r for r in project_runs if r.phase == "before"]
    after = [r for r in project_runs if r.phase == "after"]
    basic_on, basic_enforcing = _basic(session, project)
    return {
        "project": project,
        "first": _show(before[-1], runner_seen=seen, agent=agent) if before else None,
        "withBasic": _show(after[-1], runner_seen=seen, agent=agent) if after else None,
        # While a test runs again, the last one that finished, so its numbers stay on
        # screen until the new ones are in.
        "firstPrevious": _previous(before, seen, agent),
        "withBasicPrevious": _previous(after, seen, agent),
        "basicOn": basic_on,
        "basicEnforcing": basic_enforcing,
        # This project when its own `agentfox init` has connected; else the project
        # this user's latest init reported, as before.
        "connectedProject": project
        if connected is not None
        else ((row.structure or {}).get("project") if row else None),
        "runnerConnected": _runner_connected(seen),
        "sets": service.project_sets(row.state if row else None, project),
        "library": library(connected.structure if connected is not None else None),
    }


@router.get("/runs")
def list_test_runs(
    agent: str | None = None,
    limit: int = 50,
    session: Session = Depends(db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Every attack test the projects' panels ran, latest first (Testing → Attack
    tests). ``agent`` (a slug): only the runs that tested it, each as it saw it.

    There used to be two attack tests that didn't know about each other: the agent
    panel's, which sends the attacks to the real agent, and a different built-in one
    behind Testing's Run button with its own numbers. Testing now lists these runs and
    starts the same test (``POST /agents/{slug}/tests``)."""
    from sqlalchemy import select

    rows = list(
        session.scalars(
            select(OnboardingRun)
            .where(OnboardingRun.project.is_not(None))
            .order_by(OnboardingRun.created_at.desc(), OnboardingRun.id.desc())
            .limit(max(1, min(limit, 200)) * (4 if agent else 1))
        )
    )
    seen: dict[str, Any] = {}
    out = []
    for run in rows:
        names = run.structure.get("agents") if isinstance(run.structure, dict) else None
        agents = [a for a in names or [] if isinstance(a, dict)]
        if agent and not any(agent in (a.get("slug"), a.get("name")) for a in agents):
            continue
        if run.project not in seen:
            connected = sessions.find_project(session, run.project)
            seen[run.project] = connected.runner_seen_at if connected else None
        shown = _show(run, runner_seen=seen[run.project], agent=agent)
        shown["agents"] = [
            {"slug": a.get("slug"), "name": a.get("name")}
            for a in agents
            if not agent or agent in (a.get("slug"), a.get("name"))
        ]
        out.append(shown)
        if len(out) >= limit:
            break
    return {"runs": out}


@router.post("/agents/{slug}/tests")
def start_agent_test(
    slug: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """Run the attack test of the project this agent is in: the same test as the
    agent page's panel, against the real agent through its `agentfox init`."""
    from sqlalchemy import select

    from agentfox.core.models import Agent
    from agentfox.platform.registry.projects import project_of

    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    if agent is None:
        raise HTTPException(404, f"No agent '{slug}'.")
    return start_project_test(project_of(agent), session=session, user=user)


class Sets(BaseModel):
    sets: list[str]


@router.put("/projects/{project}/tests/sets")
def choose_sets(
    project: str, body: Sets, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """The attack sets this project tests with, from the library. At least one."""
    sets = service.clean_sets(body.sets)
    if not sets:
        raise HTTPException(400, "Choose at least one attack set.")
    row = sessions.ensure(session, user)
    state = service.clean_state(row.state)
    row.state = {**state, "tests": {**state.get("tests", {}), project: sets}}
    return {"project": project, "sets": sets}


@router.post("/projects/{project}/tests")
def start_project_test(
    project: str, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """Test the project again, with the guardrails it has now, on its own map."""
    connected = sessions.find_project(session, project)
    if connected is None or not connected.structure:
        raise HTTPException(
            409,
            f"Run `agentfox init` in {project}'s repository first: the tests run there, "
            "on your machine.",
        )
    now = utcnow()
    active = [r for r in runs.for_project(session, project) if r.status in runs.ACTIVE]
    runs.expire(session, active, now)
    if any(r.status in runs.ACTIVE for r in active):
        raise HTTPException(409, "A test is already running for this project.")
    basic, _enforcing = _basic(session, project)
    row = sessions.find(session, user)
    run = runs.create(
        session,
        user_id=user.id,
        org_id=user.org_id,
        phase="after" if basic else "before",
        structure=connected.structure,
        now=now,
        project=project,
        guards=[],
        sets=service.project_sets(row.state if row else None, project),
    )
    return _show(run, runner_seen=connected.runner_seen_at)


@router.post("/projects/{project}/basic-guardrails")
def add_basic_guardrails(
    project: str, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    """Add the basic guardrails to every agent in the project: prompt attacks in what
    users send blocked, personal data and secrets in replies hidden.

    They go live as any policy does: watching, and blocking only when the caller may
    change production policy and these rules have been simulated (the
    ``POST /api/policies/{key}/mode`` gate). ``mode`` says which; ``observe`` means
    simulate and promote them on the Policies page to make them block."""
    from agentfox.platform.registry.projects import project_agents

    agents = project_agents(session, project)
    if not agents:
        raise HTTPException(404, f"No project '{project}'")
    added, mode = service.add_basic_guardrails(
        session,
        [a.slug for a in agents],
        actor=user.email or user.id,
        may_enforce=may_enforce(user),
    )
    return {
        "project": project,
        "added": added,
        "mode": mode,
        "policyKeys": {a: service.basic_key(a) for a in added},
    }


# --- `agentfox init --key` --------------------------------------------------------


@dataclass
class Runner:
    """Who is calling: the setup key's user and their onboarding row."""

    user: User
    row: OnboardingSession


def runner_session(
    session: Session = Depends(db), authorization: Annotated[str | None, Header()] = None
) -> Runner:
    raw = (authorization or "").removeprefix("Bearer ").removeprefix("bearer ").strip()
    if not raw.startswith(keys.KEY_PREFIXES):
        raise HTTPException(
            401,
            "Send your AgentFox key (Settings → API keys in the dashboard): "
            "Authorization: Bearer nom_api_…",
        )
    try:
        _token, user, row = keys.resolve(session, raw, allowed_roles=WRITE_ROLES["registry"])
    except LookupError:
        raise HTTPException(
            401,
            "That key isn't valid any more: it was revoked, replaced, or (an older setup "
            "key) expired. Make a new one in the dashboard (Settings → API keys) and put it "
            "in .agentfox/agentfox.env.",
        ) from None
    except keys.SetupKeyRefused as exc:
        raise HTTPException(403, str(exc)) from None
    bind_session(session, user.org_id)
    return Runner(user=user, row=row)


@router.post("/runner/connect")
def runner_connect(
    body: Connect, session: Session = Depends(db), runner: Runner = Depends(runner_session)
) -> dict[str, Any]:
    row, user = runner.row, runner.user
    now = utcnow()
    actor = user.email or user.id
    # Proposed in the registry, under Projects, for a person to add.
    structure = service.register_structure(
        session, body.structure.as_dict(), project=body.project, actor=actor
    )
    row.structure = structure
    row.structure_at = now
    row.runner_seen_at = now
    project = body.project
    if project:
        connected = sessions.ensure_project(session, project, org_id=user.org_id)
        connected.structure = structure
        connected.structure_at = now
        connected.runner_seen_at = now
        connected.connected_by = user.id
        # A project connected for the first time is tested straight away, as it is.
        if structure["agents"] and structure["tools"] and not runs.for_project(session, project):
            runs.create(
                session,
                user_id=user.id,
                org_id=user.org_id,
                phase="before",
                structure=structure,
                now=now,
                project=project,
                guards=[],
                sets=service.project_sets(row.state, project),
            )
    return {
        "ok": True,
        "agents": len(structure["agents"]),
        "tools": len(structure["tools"]),
        "proposed": [a["slug"] for a in structure["agents"] if a.get("registry") == "proposed"],
        # Each agent's slug by its name, so `agentfox init` (which knows the files; the
        # server keeps no paths) adds the one line under the name the dashboard uses.
        "registered": [
            {"slug": a["slug"], "name": a.get("name")} for a in structure["agents"] if a.get("slug")
        ],
        "skipped": [a["name"] for a in structure["agents"] if a.get("registry") == "skipped"],
    }


@router.post("/runner/poll")
def runner_poll(
    body: Annotated[Poll | None, Body()] = None,
    session: Session = Depends(db),
    runner: Runner = Depends(runner_session),
) -> dict[str, Any]:
    """Heartbeat, and the next test to run if one is waiting."""
    row, user = runner.row, runner.user
    now = utcnow()
    row.runner_seen_at = now
    project = (body.project if body else None) or (row.structure or {}).get("project")
    connected = sessions.find_project(session, project) if project else None
    if connected is not None:
        connected.runner_seen_at = now
    if row.structure is None or (project and connected is None):
        return {"needStructure": True, "job": None}
    run = runs.claim_next(session, user_id=user.id, project=project, now=now)
    if run is None:
        return {"needStructure": False, "job": None}
    if run.phase == "after" and ((body.protocol if body else None) or 1) < RUNNER_PROTOCOL:
        # An older `agentfox init` would simulate guardrails of its own, not check the
        # project's: its "after" would measure something that isn't there.
        run.status, run.error, run.finished_at = "failed", OLD_RUNNER, now
        run.lease_expires_at = None
        return {"needStructure": False, "job": None}
    return {
        "needStructure": False,
        "job": {
            "runId": run.id,
            "phase": run.phase,
            "sets": run.sets,
            # Always empty: kept for older runners. An "after" test checks the
            # project's real policies through `/runner/runs/{id}/guard` (`policies`).
            "guardrails": [],
            "policies": run.phase == "after",
            "structure": run.structure,
        },
    }


#: The runner protocol that checks real policies (`schema.Poll.protocol`).
RUNNER_PROTOCOL = 2
OLD_RUNNER = (
    "This `agentfox init` is too old to test with your guardrails. Update it "
    "(`pip install -U agentfox`), run it again, then start the test again."
)


def _guarded_agents(session: Session, run: OnboardingRun) -> set[str]:
    """The agents a run may have checked: its project's, or (a setup-wizard run) the
    ones its map was registered as."""
    if run.project:
        from agentfox.platform.registry.projects import project_agents

        return {a.slug for a in project_agents(session, run.project)}
    return {a["slug"] for a in (run.structure or {}).get("agents", []) if a.get("slug")}


#: SQLite takes one writer at a time, and a dry run writes inside its rolled-back
#: savepoint (the enforcer observes the agent before deciding). The runner sends its
#: checks several at once, so on SQLite they queue here instead of failing with
#: "database is locked". Postgres runs them side by side.
_SQLITE_DRY_RUN = threading.Lock()


@router.post("/runner/runs/{run_id}/guard")
def runner_guard(
    run_id: str,
    body: GuardCheck,
    session: Session = Depends(db),
    runner: Runner = Depends(runner_session),
) -> dict[str, Any]:
    """Check one surface of one attack against an agent's real policies, persisting nothing.

    For an "after" attack test the runner, on the user's machine, asks this for the
    user's message, each tool call, each tool result and the reply, and applies the
    verdict. It is the red-team runner's dry run (``redteam.dry_run_check``): the real
    enforcement path for the agent's bound policies, inside a savepoint that is rolled
    back, so no decision, trace, finding, taint tag or shadow agent is written.

    Only for a running test of this setup key's (its project's, or the user's own
    setup-wizard test), and only for that test's agents: the key can check, never
    change, and never another project's agents. ``verdict`` is what the policy asks
    for (in observe mode, what it would do once it blocks); ``applied`` what live
    traffic would get now; ``mode`` which. A tool call is judged as live traffic
    judges it: for an agent with no tool allowed yet, default deny is recorded rather
    than applied (``agentfox.auto()``), so it is left out of both and its rule comes
    back with ``liveEnforced: false``.
    """
    from agentfox.capabilities.evaluation.redteam import DRY_RUN_SURFACES, dry_run_check

    run = session.get(OnboardingRun, run_id)
    if run is None or (run.project is None and run.user_id != runner.user.id):
        raise HTTPException(404, "No such test run")
    if run.status != "running":
        raise HTTPException(409, f"This test isn't running ({run.status}).")
    if body.surface not in DRY_RUN_SURFACES:
        raise HTTPException(422, f"surface must be one of {', '.join(DRY_RUN_SURFACES)}")
    if body.agent not in _guarded_agents(session, run):
        raise HTTPException(403, f"'{body.agent}' isn't one of this test's agents.")
    if body.surface == "tool_call" and not body.tool:
        raise HTTPException(422, "A tool_call check names its tool.")

    def check() -> dict[str, Any]:
        try:
            return _check()
        except OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            session.rollback()
            # Said plainly, as a retryable 503, not a bare 500 the runner reads as
            # "check the server is reachable".
            raise HTTPException(
                503,
                "AgentFox's database was busy (database is locked): SQLite takes one "
                "write at a time. Try again.",
            ) from None

    def _check() -> dict[str, Any]:
        return dry_run_check(
            session,
            body.agent,
            surface=body.surface,
            content=body.content,
            tool_key=body.tool,
            arguments=body.arguments,
            message=body.message,
            reads=body.reads,
        )

    if session.get_bind().dialect.name == "sqlite":
        # End this request's own transaction first (the key check records its use),
        # and end the dry run's before letting the next one in: an open transaction
        # holds SQLite's write lock until the request finishes.
        session.commit()
        with _SQLITE_DRY_RUN:
            # The write lock first: the dry run reads, then writes inside its
            # savepoint, and a read snapshot SQLite can't upgrade (the runner's results
            # committed meanwhile) failed at once with "database is locked".
            sqlite_write_lock(session)
            result = check()
            session.commit()
        return result
    return check()


@router.post("/runner/runs/{run_id}/results")
def runner_results(
    run_id: str,
    body: Results,
    session: Session = Depends(db),
    runner: Runner = Depends(runner_session),
) -> dict[str, Any]:
    now = utcnow()
    runner.row.runner_seen_at = now
    run = runs.locked(session, run_id)
    if run is None or (run.project is None and run.user_id != runner.user.id):
        raise HTTPException(404, "No such test run")
    if len(body.results) > (run.total or 0):
        raise HTTPException(422, f"This test has {run.total} attacks; that is more results.")
    if run.project:
        connected = sessions.find_project(session, run.project)
        if connected is not None:
            connected.runner_seen_at = now
    try:
        updated = runs.add_results(
            session,
            run,
            [r.model_dump(exclude_none=True) for r in body.results],
            done=body.done,
            error=body.error,
            now=now,
        )
    except runs.RunFinished:
        session.commit()  # keep the lapsed run's failure
        raise HTTPException(409, f"This test has already finished ({run.status}).") from None
    return {"ok": True, "status": updated.status, "received": len(updated.results or [])}
