"""Policy routes (P6-1, P2-7).

The route worth noting is ``/api/policies/simulate``: it replays recorded traffic
against a candidate policy and returns the diff. Promotion to ``enforce`` is a
separate, audited act — the product should make "turn this on" a reviewed change
rather than a toggle, because a false block is how guardrails get disabled for good.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Policy, PolicyCanary, PolicyVersion, User
from agentfox.gateway.deps import current_user, db, require
from agentfox.policy import (
    LEVELS,
    MODES,
    CanaryError,
    PolicyDocument,
    UnloadablePolicyVersion,
    active_canary,
    active_layers,
    canary_health,
    canary_rollout,
    compile_to_rego,
    current_binding,
    effective_for,
    history,
    lint_all,
    lint_documents,
    lint_summary,
    load_version_document,
    policies_in_force,
    record_simulation,
    rollback_canary,
    save_policy,
    set_mode,
    simulate,
    simulation_for,
    start_canary,
)
from agentfox.policy.canary import evaluate_gate
from agentfox.prove.audit import chain

router = APIRouter(prefix="/api/policies", tags=["policy"])


@router.get("")
def list_policies(
    agent: str | None = None,
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    # A policy's real scope lives in its declared `scope.agents` glob (checked by
    # `matches_scope`, honouring the binding's own scope override) and its place in
    # the hierarchy — not a simple FK, since one policy commonly governs many agents
    # by pattern. Reusing `policies_in_force` here means the filter agrees with what
    # actually gets enforced at request time, rather than a second, looser notion
    # of "applies to".
    #
    # A bound version that no longer loads is listed under `unloadable_policies`
    # rather than failing the whole page.
    unloadable: list[UnloadablePolicyVersion] = []
    if agent:
        scoped_policy_ids: set[str] | None = {
            version.policy_id
            for _doc, version, _binding in policies_in_force(
                session, agent_slug=agent, skipped=unloadable
            )
        }
    else:
        scoped_policy_ids = None
        active_layers(session, skipped=unloadable)
    out = []
    for policy in session.scalars(select(Policy).order_by(Policy.key)):
        if scoped_policy_ids is not None and policy.id not in scoped_policy_ids:
            continue
        versions = list(
            session.scalars(
                select(PolicyVersion)
                .where(PolicyVersion.policy_id == policy.id)
                .order_by(PolicyVersion.version.desc())
            )
        )
        latest = versions[0] if versions else None
        # The live binding, whichever version it points at: mid-canary or after a
        # rollback it is an earlier version than the newest one (#65).
        binding, bound = current_binding(session, policy.id)
        out.append(
            {
                "id": policy.id,
                "key": policy.key,
                "name": policy.name,
                "description": policy.description,
                "versions": len(versions),
                "latest_version": latest.version if latest else None,
                "bound_version": bound.version if bound else None,
                "mode": binding.mode if binding else None,
                # The rules of the version in force; the newest version's when unbound.
                "rules": len(((bound or latest).compiled_json or {}).get("rules", []))
                if (bound or latest)
                else 0,
                # A repo-scan proposal (routes/integrations.py) awaiting human review —
                # already created in `observe` mode (never blocks), just not
                # acknowledged yet.
                "proposed": policy.proposed,
            }
        )
    return {"policies": out, "unloadable_policies": [exc.to_json() for exc in unloadable]}


# ---------------------------------------------------------------------------
# Hierarchy (P12)
# ---------------------------------------------------------------------------


@router.get("/effective")
def get_effective(
    agent: str | None = None,
    team: str | None = None,
    user: str | None = None,
    environment: str = "production",
    session: Session = Depends(db),
    _u: User = Depends(current_user),
) -> dict[str, Any]:
    """The policy actually in force for a subject, with per-rule provenance (P12-3)."""
    return effective_for(
        session, agent_slug=agent, environment=environment, team=team, user=user
    ).explain()


@router.get("/lint")
def get_lint(session: Session = Depends(db), _u: User = Depends(current_user)) -> dict[str, Any]:
    """Policy lint (P12-4). `passed` is false when critical/high findings exist."""
    return lint_all(session)


@router.get("/{key}")
def get_policy(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        raise HTTPException(404, f"unknown policy '{key}'")
    versions = history(session, key)
    latest = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version.desc())
    ).first()
    binding, bound = current_binding(session, policy.id)
    return {
        "key": policy.key,
        "name": policy.name,
        "description": policy.description,
        "versions": versions,
        "body": latest.body if latest else "",
        "compiled": latest.compiled_json if latest else {},
        "latest_version": latest.version if latest else None,
        "bound_version": bound.version if bound else None,
        "mode": binding.mode if binding else None,
        "level": binding.level if binding else "org",
        "scope_id": binding.scope_id if binding else "*",
        "compose": binding.compose if binding else "extend",
    }


class PolicyIn(BaseModel):
    body: str
    notes: str = ""
    mode: str | None = None
    #: P12 hierarchy (org -> team -> agent -> user, narrowest wins on ties) — every
    #: save silently defaulted to org/*/extend until this was exposed to the form.
    level: str = "org"
    scope_id: str = "*"
    compose: str = "extend"


@router.post("", status_code=201)
def upsert_policy(
    payload: PolicyIn, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    try:
        doc = PolicyDocument.from_yaml(payload.body)
    except Exception as exc:
        raise HTTPException(400, f"invalid policy: {exc}") from exc

    if payload.level not in LEVELS:
        raise HTTPException(400, f"level must be one of {LEVELS}")
    if payload.compose not in MODES:
        raise HTTPException(400, f"compose must be one of {MODES}")

    # Saving never changes what is in force (#64). It used to bind the YAML's own
    # `mode`, so saving `mode: enforce` enforced with no simulation, and saving the
    # observe starter over an enforcing policy demoted it — while the editor said
    # nothing in force changes until you promote. Promotion (`/{key}/mode`, which
    # requires a recorded simulation to enforce) is now the only way to change it.
    if payload.mode == "enforce":
        if user.role not in {"owner", "admin", "security"}:
            raise HTTPException(
                403, f"role '{user.role}' may author policies but not bind them to enforce"
            )
        raise HTTPException(
            409,
            "saving does not change what is in force: save the version, simulate it "
            "(POST /api/policies/simulate), then promote it with "
            f'POST /api/policies/{doc.key}/mode {{"mode": "enforce", "version": N}}',
        )
    if payload.mode not in (None, "observe"):
        raise HTTPException(400, "mode must be 'observe' or omitted")

    policy, version = save_policy(
        session,
        doc,
        author=user.email,
        notes=payload.notes,
        # A policy with nothing live yet is bound, in observe; one that is live
        # keeps its binding, version and mode until a promotion moves them.
        bind_mode="observe",
        level=payload.level,
        scope_id=payload.scope_id,
        compose=payload.compose,
        rebind=False,
    )
    binding, live = current_binding(session, policy.id)
    chain.append(
        session,
        "policy.version_created",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="policy_version",
        subject_id=version.id,
        payload={
            "policy": policy.key,
            "version": version.version,
            "live_version": live.version if live else None,
            "mode": binding.mode if binding else None,
            "notes": payload.notes,
            "level": payload.level,
            "scope_id": payload.scope_id,
            "compose": payload.compose,
        },
    )
    return {
        "key": policy.key,
        "version": version.version,
        "version_id": version.id,
        # What is in force after the save — unchanged unless nothing was live.
        "live_version": live.version if live else None,
        "mode": binding.mode if binding else None,
        "pending": live is None or live.id != version.id,
    }


@router.post("/validate")
def validate_policy(payload: PolicyIn) -> dict[str, Any]:
    try:
        doc = PolicyDocument.from_yaml(payload.body)
    except Exception as exc:
        return {"valid": False, "error": str(exc)}
    # The same full lint `policy validate FILE` runs: a rule that can never fire, or
    # one naming an unknown value, is not a valid policy (#50, X5).
    lint = lint_summary(lint_documents([doc]))
    if not lint["passed"]:
        return {
            "valid": False,
            "error": "; ".join(f["message"] for f in lint["blocking"]),
            "lint": lint,
        }
    return {
        "valid": True,
        "lint": lint,
        "key": doc.key,
        "rules": len(doc.rules),
        "mode": doc.mode,
        "controls": sorted({c for r in doc.rules for c in r.controls}),
        "rego": compile_to_rego(doc),
    }


class ModeIn(BaseModel):
    mode: str
    #: Make this saved version the live one. Omitted: change the live version's mode.
    version: int | None = None
    #: Hierarchy placement for the promoted binding. Omitted: keep the current one.
    level: str | None = None
    scope_id: str | None = None
    compose: str | None = None


@router.post("/{key}/mode")
def change_mode(
    key: str,
    payload: ModeIn,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
    """Promote or demote a policy, optionally making a saved version live.

    Promoting to ``enforce`` requires a recorded simulation of exactly the rules
    being enforced (``POST /api/policies/simulate`` with that version's body) —
    the server-side half of the editor's simulate-before-promote gate (#64).
    Demoting to ``observe`` never needs one: it can only stop blocking.
    """
    if payload.mode not in ("observe", "enforce"):
        raise HTTPException(400, "mode must be 'observe' or 'enforce'")
    if payload.level is not None and payload.level not in LEVELS:
        raise HTTPException(400, f"level must be one of {LEVELS}")
    if payload.compose is not None and payload.compose not in MODES:
        raise HTTPException(400, f"compose must be one of {MODES}")
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        raise HTTPException(404, f"unknown policy '{key}'")

    _binding, live = current_binding(session, policy.id)
    if payload.version is not None:
        target = session.scalar(
            select(PolicyVersion).where(
                PolicyVersion.policy_id == policy.id, PolicyVersion.version == payload.version
            )
        )
        if target is None:
            raise HTTPException(404, f"policy '{key}' has no version {payload.version}")
    else:
        target = (
            live
            or session.scalars(
                select(PolicyVersion)
                .where(PolicyVersion.policy_id == policy.id)
                .order_by(PolicyVersion.version.desc())
            ).first()
        )
    if target is None:
        raise HTTPException(404, f"policy '{key}' has no versions")

    try:
        simulated = payload.mode != "enforce" or simulation_for(session, target) is not None
    except UnloadablePolicyVersion as exc:
        raise HTTPException(422, str(exc)) from exc
    if not simulated:
        raise HTTPException(
            409,
            f"version {target.version} of '{key}' has not been simulated: replay recent "
            "traffic against it first (POST /api/policies/simulate with its body, or "
            "Simulate in the editor), then promote",
        )

    binding = set_mode(
        session,
        key,
        payload.mode,
        version=payload.version,
        level=payload.level,
        scope_id=payload.scope_id,
        compose=payload.compose,
    )
    if binding is None:
        raise HTTPException(404, f"unknown policy '{key}'")
    chain.append(
        session,
        f"policy.mode_{payload.mode}",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="policy",
        subject_id=key,
        payload={"mode": payload.mode, "version": target.version},
    )
    return {"key": key, "mode": binding.mode, "version": target.version}


class SimulateIn(BaseModel):
    body: str
    agent: str | None = None
    since_days: int = 30
    limit: int = 1000
    persist: bool = True


@router.post("/simulate")
def simulate_policy(
    payload: SimulateIn, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """P2-7 — replay recorded traffic against a candidate policy."""
    try:
        candidate = PolicyDocument.from_yaml(payload.body)
    except Exception as exc:
        raise HTTPException(400, f"invalid policy: {exc}") from exc

    diff = simulate(
        session,
        candidate,
        agent_slug=payload.agent,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=payload.since_days),
        limit=payload.limit,
    )
    result = diff.to_json()
    result["risky"] = diff.risky
    result["recommendation"] = (
        "Review the newly blocked decisions before promoting to enforce — each one is "
        "production traffic that would now fail."
        if diff.risky
        else "No production traffic would newly block; safe to promote to enforce."
    )
    if payload.persist:
        run = record_simulation(
            session,
            candidate,
            diff,
            run_by=user.email,
            scope={"agent": payload.agent, "since_days": payload.since_days},
        )
        result["simulation_id"] = run.id
    return result


# ---------------------------------------------------------------------------
# Canary rollout (P12-6)
# ---------------------------------------------------------------------------


def _canary_json(session: Session, canary: PolicyCanary) -> dict[str, Any]:
    stable = session.get(PolicyVersion, canary.stable_version_id)
    candidate = session.get(PolicyVersion, canary.candidate_version_id)
    out: dict[str, Any] = {
        "id": canary.id,
        "status": canary.status,
        "percent": canary.percent,
        "step_index": canary.step_index,
        "steps": canary.steps,
        "stable_version": stable.version if stable else None,
        "candidate_version": candidate.version if candidate else None,
        "max_block_rate_delta": canary.max_block_rate_delta,
        "max_block_rate_drop": canary.max_block_rate_drop,
        "min_dwell_seconds": canary.min_dwell_seconds,
        "last_advanced_at": _iso(canary.last_advanced_at),
        "min_sample": canary.min_sample,
        "started_by": canary.started_by,
        "started_at": canary.created_at.isoformat() if canary.created_at else None,
        "completed_at": canary.completed_at.isoformat() if canary.completed_at else None,
        "rollback_reason": canary.rollback_reason,
    }
    if canary.status == "rolling":
        out["health"] = canary_health(session, canary)
        gate = evaluate_gate(session, canary)
        out["gate"] = {"action": gate.action, "reason": gate.reason}
    return out


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).isoformat()


class CanaryStartIn(BaseModel):
    candidate_version: int | None = None
    steps: list[int] | None = None
    #: Roll back when the candidate blocks MORE than stable by over this.
    max_block_rate_delta: float = Field(0.15, ge=0.0, le=1.0)
    #: Roll back when the candidate blocks LESS than stable by over this (a loosening).
    #: Defaults to settings.canary_max_block_rate_drop.
    max_block_rate_drop: float | None = Field(None, ge=0.0, le=1.0)
    #: Minimum seconds at each step before advancing. Defaults to
    #: settings.canary_min_dwell_seconds.
    min_dwell_seconds: int | None = Field(None, ge=0)
    min_sample: int = 20


@router.post("/{key}/canary/start", status_code=201)
def start_policy_canary(
    key: str,
    payload: CanaryStartIn,
    session: Session = Depends(db),
    user: User = Depends(require("policy_production")),
) -> dict[str, Any]:
    try:
        canary = start_canary(
            session,
            key,
            candidate_version=payload.candidate_version,
            steps=payload.steps,
            max_block_rate_delta=payload.max_block_rate_delta,
            min_sample=payload.min_sample,
            started_by=user.email,
            max_block_rate_drop=payload.max_block_rate_drop,
            min_dwell_seconds=payload.min_dwell_seconds,
        )
    except CanaryError as exc:
        raise HTTPException(400, str(exc)) from exc
    chain.append(
        session,
        "policy.canary_started",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="policy",
        subject_id=key,
        payload={
            "canary_id": canary.id,
            "stable_version_id": canary.stable_version_id,
            "candidate_version_id": canary.candidate_version_id,
            "steps": canary.steps,
            "max_block_rate_delta": canary.max_block_rate_delta,
            "max_block_rate_drop": canary.max_block_rate_drop,
            "min_dwell_seconds": canary.min_dwell_seconds,
        },
    )
    return _canary_json(session, canary)


@router.get("/{key}/canary")
def get_policy_canary(
    key: str, session: Session = Depends(db), _u: User = Depends(current_user)
) -> dict[str, Any]:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        raise HTTPException(404, f"unknown policy '{key}'")
    canary = active_canary(session, policy.id)
    if canary is None:
        # Most recent one regardless of status, so the UI can show "rolled back
        # 10 minutes ago, here's why" instead of just "nothing running".
        canary = session.scalar(
            select(PolicyCanary)
            .where(PolicyCanary.policy_id == policy.id)
            .order_by(PolicyCanary.created_at.desc())
        )
    if canary is None:
        return {"canary": None}
    return {"canary": _canary_json(session, canary)}


@router.post("/{key}/canary/advance")
def advance_policy_canary(
    key: str, session: Session = Depends(db), user: User = Depends(require("policy_production"))
) -> dict[str, Any]:
    """Check the candidate cohort's health and advance, hold, or auto-roll-back.

    Safe to call repeatedly — a canary without enough traffic yet, or still inside
    its dwell time, simply holds at its current step. The gate is two-way: a
    candidate that blocks more than stable *or less* than stable (a loosening) by
    more than its threshold is rolled back. This is what makes rollback "automated":
    the decision is computed from telemetry every time this is called, never a human
    judgement call. The scheduled `canary.advance` job applies the same gate.
    """
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        raise HTTPException(404, f"unknown policy '{key}'")
    canary = active_canary(session, policy.id)
    if canary is None:
        raise HTTPException(400, f"policy '{key}' has no canary rolling")
    before_status, before_percent = canary.status, canary.percent
    now = dt.datetime.now(dt.UTC)
    decision = evaluate_gate(session, canary, now)
    canary = canary_rollout(session, canary.id, now)
    if canary.status != before_status or canary.percent != before_percent:
        chain.append(
            session,
            "policy.canary_rolled_back"
            if canary.status == "rolled_back"
            else (
                "policy.canary_completed"
                if canary.status == "completed"
                else "policy.canary_advanced"
            ),
            actor_type="user",
            actor_id=user.email or user.id,
            subject_type="policy",
            subject_id=key,
            payload={
                "canary_id": canary.id,
                "status": canary.status,
                "percent": canary.percent,
                "reason": canary.rollback_reason or decision.reason,
            },
        )
    out = _canary_json(session, canary)
    out["decision"] = {"action": decision.action, "reason": decision.reason}
    return out


@router.post("/{key}/canary/rollback")
def rollback_policy_canary(
    key: str, session: Session = Depends(db), user: User = Depends(require("policy_production"))
) -> dict[str, Any]:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        raise HTTPException(404, f"unknown policy '{key}'")
    canary = active_canary(session, policy.id)
    if canary is None:
        raise HTTPException(400, f"policy '{key}' has no canary rolling")
    canary = rollback_canary(session, canary.id, reason=f"manual rollback by {user.email}")
    chain.append(
        session,
        "policy.canary_rolled_back",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="policy",
        subject_id=key,
        payload={"canary_id": canary.id, "reason": canary.rollback_reason},
    )
    return _canary_json(session, canary)


@router.get("/{key}/rego")
def get_rego(
    key: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        raise HTTPException(404, f"unknown policy '{key}'")
    latest = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version.desc())
    ).first()
    try:
        doc = load_version_document(latest)
    except UnloadablePolicyVersion as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "key": key,
        "version": latest.version,
        "rego": compile_to_rego(doc, version=latest.version),
    }
