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

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Decision, SimulationRun, Trace
from agentfox.policy.engine import NativePolicyEngine
from agentfox.policy.model import PolicyDecision, PolicyDocument, PolicyInput
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
    taint = dict(decision.taint_summary_json or {})
    return PolicyInput(
        agent_slug=trace.agent_slug if trace else None,
        risk_tier=(taint.get("risk_tier") or "limited"),
        environment=trace.environment if trace else "production",
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
    """
    engine = NativePolicyEngine()
    doc = candidate.model_copy(deep=True)
    if force_enforce:
        doc.mode = "enforce"

    query = select(Decision).order_by(Decision.created_at.desc()).limit(limit)
    if since is not None:
        query = query.where(Decision.created_at >= since)
    decisions = list(session.scalars(query))

    if agent_slug:
        trace_ids = {
            t.id for t in session.scalars(select(Trace).where(Trace.agent_slug == agent_slug))
        }
        decisions = [d for d in decisions if d.trace_id in trace_ids]

    diff = SimulationDiff()
    for decision in decisions:
        diff.replayed += 1
        pinput = _policy_input_from_decision(session, decision)
        new: PolicyDecision = engine.evaluate(doc, pinput)

        # Compare against the *effective* historical verdict, not the observed one:
        # in observe mode the recorded verdict is always "allow", which would make
        # every enforcing rule look like a new block.
        old_effective = _effective_of(decision)
        record = {
            "decision_id": decision.id,
            "trace_id": decision.trace_id,
            "agent": pinput.agent_slug,
            "surface": decision.surface,
            "tool": decision.tool_key,
            "was": old_effective,
            "now": new.effective_verdict,
            "rules": [r.rule_id for r in new.rules_fired],
            "reasons": [r.reason for r in new.rules_fired][:3],
        }

        if new.effective_verdict == old_effective:
            diff.unchanged += 1
        elif new.effective_verdict == "block":
            diff.newly_blocked.append(record)
        elif new.effective_verdict == "escalate":
            diff.newly_escalated.append(record)
        elif old_effective in ("block", "escalate") and new.effective_verdict == "allow":
            diff.newly_allowed.append(record)
        else:
            diff.unchanged += 1

    return diff


def _effective_of(decision: Decision) -> str:
    """The verdict a decision would have had under enforcement."""
    rank = {
        "allow": 0,
        "tokenize": 1,
        "mask": 2,
        "redact": 3,
        "abstain": 4,
        "escalate": 5,
        "block": 6,
    }
    best = decision.verdict
    for rule in decision.rules_fired_json or []:
        effect = str(rule.get("effect", "allow"))
        if rank.get(effect, 0) > rank.get(best, 0):
            best = effect
    return best


def record_simulation(
    session: Session,
    candidate: PolicyDocument,
    diff: SimulationDiff,
    run_by: str = "system",
    scope: dict[str, Any] | None = None,
) -> SimulationRun:
    run = SimulationRun(
        policy_id=None,
        candidate_body=candidate.to_yaml(),
        scope_json=scope or {},
        replayed_count=diff.replayed,
        diff_json=diff.to_json(),
        run_by=run_by,
    )
    session.add(run)
    session.flush()
    return run
