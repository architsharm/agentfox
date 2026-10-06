"""Policy simulation — "what would this change break?" (P2-7, NOM-IAM-06).

Disproportionately important for adoption, and the reason it is in the MVP rather
than a later phase: the reason security tooling gets configured permissively and
left there is that nobody can predict what tightening a rule will break. Replaying
real recorded traffic against a candidate policy turns a scary change into a
reviewed diff.

It is only possible because Pillar 5 already stores the full execution path with
the detector findings and taint context attached — which is a good illustration of
why the pillars are built together rather than sequentially.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import yaml
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agentfox.core.models import Agent, Decision, Policy, PolicyVersion, SimulationRun, Trace
from agentfox.policy.engine import NativePolicyEngine
from agentfox.policy.model import EFFECT_RANK, PolicyDecision, PolicyDocument, PolicyInput
from agentfox.policy.taint_view import policy_taint


@dataclass
class SimulationDiff:
    replayed: int = 0
    newly_blocked: list[dict[str, Any]] = field(default_factory=list)
    newly_allowed: list[dict[str, Any]] = field(default_factory=list)
    newly_escalated: list[dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "replayed": self.replayed,
            "unchanged": self.unchanged,
            "newly_blocked": self.newly_blocked,
            "newly_allowed": self.newly_allowed,
            "newly_escalated": self.newly_escalated,
            "counts": {
                "newly_blocked": len(self.newly_blocked),
                "newly_allowed": len(self.newly_allowed),
                "newly_escalated": len(self.newly_escalated),
            },
        }

    @property
    def risky(self) -> bool:
        """A change that newly blocks production traffic needs a human to look."""
        return bool(self.newly_blocked)


def _policy_input_from_decision(session: Session, decision: Decision) -> PolicyInput:
    """Reconstruct the evaluator input from what was recorded at decision time.

    Determinism (X-4) is what makes this sound: the stored detections, taint summary
    and arguments are exactly what the engine saw, so re-running a *different* policy
    over them isolates the policy change as the only variable.
    """
    trace = session.get(Trace, decision.trace_id) if decision.trace_id else None
    agent = session.get(Agent, decision.agent_id) if decision.agent_id else None
    taint = dict(decision.taint_summary_json or {})
    return PolicyInput(
        # A decision recorded without a trace (a bare `check()`) still names its agent.
        agent_slug=trace.agent_slug if trace else (agent.slug if agent else None),
        risk_tier=(taint.get("risk_tier") or "limited"),
        environment=trace.environment if trace else (agent.environment if agent else "production"),
        surface=decision.surface,
        tool_key=decision.tool_key,
        tool_impact=str(taint.get("tool_impact", "read")),
        arguments=dict(taint.get("arguments_snapshot") or {}),
        intent=trace.intent if trace else None,
        detections=list(taint.get("detections") or []),
        # The same view the live path gave the engine (scope as recorded, provenance
        # an explicit grant accepted), or a replay would disagree with the decision.
        taint=policy_taint(taint, dict(taint.get("capability") or {})),
        capability=dict(taint.get("capability") or {}),
        budget=dict(taint.get("budget") or {}),
        prior_tools=list(taint.get("prior_tools") or []),
        detector_degraded=bool(taint.get("detector_degraded", False)),
    )


def simulate(
    session: Session,
    candidate: PolicyDocument,
    agent_slug: str | None = None,
    since: dt.datetime | None = None,
    limit: int = 1000,
    force_enforce: bool = True,
) -> SimulationDiff:
    """Replay recorded decisions against ``candidate`` and diff the outcomes.

    ``force_enforce`` evaluates the candidate as if it were enforcing, because the
    question a reviewer is asking is "if I turn this on, what happens?" — comparing
    two observe-mode policies would always show no blocks.

    The candidate is replayed *in place of* its own pack, beside everything else
    that was in force for each decision: rules that fired from other packs, and
    the platform's own refusals (capability default-deny, critical action risks,
    business ladders), still stand. Evaluating the candidate alone reported every
    block another pack made as "newly allowed". Only the rules of the candidate's
    own key — whichever version of it was in force — are replaced.
    """
    engine = NativePolicyEngine()
    doc = candidate.model_copy(deep=True)
    if force_enforce:
        doc.mode = "enforce"

    query = select(Decision).order_by(Decision.created_at.desc()).limit(limit)
    if since is not None:
        query = query.where(Decision.created_at >= since)
    if agent_slug:
        # Matched on the decision's own agent as well as its trace: a decision
        # recorded without a trace (a bare `check()`) was dropped by a trace-only
        # filter. Filtered in the query, so `limit` counts this agent's decisions.
        agent_ids = [a.id for a in session.scalars(select(Agent).where(Agent.slug == agent_slug))]
        trace_ids = select(Trace.id).where(Trace.agent_slug == agent_slug)
        query = query.where(or_(Decision.agent_id.in_(agent_ids), Decision.trace_id.in_(trace_ids)))
    decisions = list(session.scalars(query))

    own_rules = _OwnRules(session, candidate.key)
    diff = SimulationDiff()
    for decision in decisions:
        diff.replayed += 1
        pinput = _policy_input_from_decision(session, decision)
        in_scope = doc.matches_scope(pinput.agent_slug, pinput.environment)
        new: PolicyDecision = (
            engine.evaluate(doc, pinput) if in_scope else PolicyDecision(mode=doc.mode)
        )

        # Compare against the *effective* historical verdict, not the observed one:
        # in observe mode the recorded verdict is always "allow", which would make
        # every enforcing rule look like a new block.
        old_effective = _effective_of(decision)
        replaced = own_rules.rule_ids(decision)
        kept = [r for r in (decision.rules_fired_json or []) if r.get("rule_id") not in replaced]
        new_effective = effective_verdict_of(new.effective_verdict, kept)
        fired_before = {
            str(r.get("rule_id"))
            for r in (decision.rules_fired_json or [])
            if r.get("rule_id") in replaced
        }
        fired_now = [r.rule_id for r in new.rules_fired]
        record = {
            "decision_id": decision.id,
            "trace_id": decision.trace_id,
            "agent": pinput.agent_slug,
            "surface": decision.surface,
            "tool": decision.tool_key,
            "was": old_effective,
            "now": new_effective,
            "rules": fired_now,
            "reasons": [r.reason for r in new.rules_fired][:3],
            # The candidate pack's rules that fired before and do not now.
            "no_longer_fires": sorted(fired_before - set(fired_now)),
        }

        if new_effective == old_effective:
            diff.unchanged += 1
        elif new_effective == "block":
            diff.newly_blocked.append(record)
        elif new_effective == "escalate":
            diff.newly_escalated.append(record)
        elif old_effective in ("block", "escalate"):
            diff.newly_allowed.append(record)
        else:
            diff.unchanged += 1

    return diff


class _OwnRules:
    """Which rule ids, on a recorded decision, came from the candidate's own pack.

    Read from the versions recorded on the decision (`policy_version_ids`), so a
    decision made under v3 has v3's rules replaced, not today's.
    """

    def __init__(self, session: Session, key: str) -> None:
        self.session = session
        policy = session.scalar(select(Policy).where(Policy.key == key))
        self.policy_id = policy.id if policy is not None else None
        self._cache: dict[str, set[str]] = {}

    def rule_ids(self, decision: Decision) -> set[str]:
        if self.policy_id is None:
            return set()
        out: set[str] = set()
        for version_id in decision.policy_version_ids or [decision.policy_version_id]:
            if not version_id:
                continue
            if version_id not in self._cache:
                version = self.session.get(PolicyVersion, version_id)
                ids: set[str] = set()
                if version is not None and version.policy_id == self.policy_id:
                    from agentfox.policy.store import (
                        UnloadablePolicyVersion,
                        load_version_document,
                    )

                    try:
                        ids = {rule.id for rule in load_version_document(version).rules}
                    except UnloadablePolicyVersion:
                        # Still attribute what the stored row names, so a decision
                        # made under it is not silently dropped from the diff.
                        body = version.compiled_json or yaml.safe_load(version.body) or {}
                        ids = {str(rule.get("id")) for rule in body.get("rules", [])}
                self._cache[version_id] = ids
            out |= self._cache[version_id]
        return out


def _effective_of(decision: Decision) -> str:
    """The verdict a decision would have had under enforcement."""
    return effective_verdict_of(decision.verdict, decision.rules_fired_json)


def effective_verdict_of(verdict: str, rules_fired: list[dict[str, Any]] | None) -> str:
    """The strongest of the applied verdict and every fired rule's effect.

    In observe mode the applied verdict is always "allow"; what enforcement would
    have done is the strongest effect any rule fired with.
    """
    best = verdict
    for rule in rules_fired or []:
        effect = str(rule.get("effect", "allow"))
        if EFFECT_RANK.get(effect, 0) > EFFECT_RANK.get(best, 0):
            best = effect
    return best


def rules_fingerprint(doc: PolicyDocument) -> str:
    """What a simulation actually tested: the rules and the default effect.

    Mode, name and version number are deliberately left out — a simulation is
    always run as if enforcing, so the same rules saved in observe are the same
    candidate.
    """
    import json

    return json.dumps(
        {
            "default_effect": doc.default_effect,
            "scope": doc.scope,
            "rules": [rule.model_dump() for rule in doc.rules],
        },
        sort_keys=True,
        default=str,
    )


def simulation_for(session: Session, version: PolicyVersion) -> SimulationRun | None:
    """The most recent recorded simulation of exactly this version's rules, if any.

    The server-side half of "simulate before you enforce" (#64): promoting a
    version to enforce over the API requires one.
    """
    from agentfox.policy.store import load_version_document

    target = rules_fingerprint(load_version_document(version))
    runs = session.scalars(
        select(SimulationRun)
        .where(or_(SimulationRun.policy_id == version.policy_id, SimulationRun.policy_id.is_(None)))
        .order_by(SimulationRun.created_at.desc())
        .limit(500)
    )
    for run in runs:
        try:
            candidate = PolicyDocument.from_yaml(run.candidate_body)
        except Exception:
            continue
        if rules_fingerprint(candidate) == target:
            return run
    return None


def record_simulation(
    session: Session,
    candidate: PolicyDocument,
    diff: SimulationDiff,
    run_by: str = "system",
    scope: dict[str, Any] | None = None,
) -> SimulationRun:
    policy = session.scalar(select(Policy).where(Policy.key == candidate.key))
    run = SimulationRun(
        policy_id=policy.id if policy is not None else None,
        candidate_body=candidate.to_yaml(),
        scope_json=scope or {},
        replayed_count=diff.replayed,
        diff_json=diff.to_json(),
        run_by=run_by,
    )
    session.add(run)
    session.flush()
    return run
