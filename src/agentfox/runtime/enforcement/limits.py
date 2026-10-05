"""Gates that stop an agent regardless of content: the kill switch and spend budgets."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from agentfox.core.models import Agent, Budget, Trace
from agentfox.prove.audit import chain
from agentfox.runtime.agent_loop import LoopBudget, Step, govern_loop
from agentfox.runtime.enforcement.result import EnforcementResult
from agentfox.runtime.enforcement.rules import _fired_rule
from agentfox.runtime.reliability import BudgetVerdict, check_budget, raise_budget_finding

log = logging.getLogger("agentfox.runtime.enforcement")


class _LimitsMixin:
    """Enforcer's kill switch and budget gates. Mixed into :class:`Enforcer`, never used alone."""

    def _budget_gate(self, agent: Agent | None, trace: Trace) -> EnforcementResult | None:
        """P15-3. A breach is a governed event with an audit entry and a finding —
        not an HTTP 429 that disappears into a load balancer log."""
        if agent is None:
            return None
        verdict: BudgetVerdict = check_budget(self.session, "agent", agent.id)
        if not verdict.exceeded:
            return None

        raise_budget_finding(self.session, "agent", agent.id, verdict)
        result = EnforcementResult(
            verdict="block",
            effective_verdict="block",
            mode="enforce",
            trace_id=trace.id,
            reason=verdict.reason,
            rules_fired=[
                _fired_rule(
                    "budget.exhausted",
                    "block",
                    verdict.reason,
                    severity="high",
                    controls=["NOM-RTG-08"],
                )
            ],
        )
        chain.append(
            self.session,
            "budget.exhausted",
            actor_type="agent",
            actor_id=agent.slug,
            subject_type="agent",
            subject_id=agent.id,
            payload=verdict.to_json(),
        )
        return result

    def _control_verdict(self, agent: Agent | None) -> EnforcementResult | None:
        """PL-3 kill switch / quarantine. Checked before anything else."""
        if agent is None:
            return None
        from agentfox.core.models import AgentControl

        control = self.session.scalar(select(AgentControl).where(AgentControl.agent_id == agent.id))
        if control is None or control.state == "active":
            return None

        reason = (
            f"Agent is {control.state}"
            + (f": {control.reason}" if control.reason else "")
            + (f" (by {control.actor})" if control.actor else "")
        )
        return EnforcementResult(
            verdict="block",
            effective_verdict="block",
            mode="enforce",
            reason=reason,
            rules_fired=[
                _fired_rule(
                    f"agent.{control.state}",
                    "block",
                    reason,
                    severity="critical",
                    controls=["NOM-DSC-02"],
                )
            ],
        )

    def _budget_state(
        self,
        agent: Agent | None,
        trace: Trace | None,
        tool_key: str | None,
        prior_tools: list[str],
        prior_steps: list[dict[str, Any]] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {"exceeded": False, "loop_detected": False}
        if tool_key and prior_steps is not None:
            # PL-4: the real loop governor (agent_loop.LoopGovernor) — three
            # detectors (identical re-issued calls, alternating cycles, no new
            # observation) instead of "the same tool three times in a row", which
            # misses an A-B-A-B alternation entirely since neither tool repeats
            # consecutively. Falls through to the naive counter below only when a
            # caller has no step history to give it yet (see the `elif`).
            replay = [
                Step(
                    tool=s.get("tool", ""),
                    arguments=s.get("arguments") or {},
                    observation=s.get("observation"),
                )
                for s in prior_steps
            ] + [Step(tool=tool_key, arguments=arguments or {}, observation=None)]
            verdict = govern_loop(
                replay,
                budget=LoopBudget(
                    max_steps=self.settings.loop_max_steps,
                    max_repeats=self.settings.loop_max_repeats,
                    max_cycle_length=self.settings.loop_max_cycle_length,
                    max_steps_without_progress=self.settings.loop_max_steps_without_progress,
                ),
            )
            state["loop_detected"] = verdict.stopped
            state["loop_reason"] = verdict.reason
            state["loop_evidence"] = verdict.evidence
            state["repeat_count"] = prior_tools.count(tool_key)
            state["depth"] = len(prior_tools)
        elif tool_key and prior_tools:
            # A tool called repeatedly in one execution path is the runaway-loop
            # shape (OWASP LLM10 / Agentic T4). Kept as the fallback for a caller
            # that only supplies prior_tools (no step history yet) — same graceful
            # degradation as check_conversation_window.
            repeats = prior_tools.count(tool_key)
            state["repeat_count"] = repeats
            state["loop_detected"] = repeats >= 3
            state["depth"] = len(prior_tools)

        if agent is None:
            return state
        budget = self.session.scalar(
            select(Budget).where(Budget.scope_type == "agent", Budget.scope_id == agent.id)
        )
        if budget is None:
            return state
        exceeded = []
        if budget.max_calls is not None and budget.calls >= budget.max_calls:
            exceeded.append("calls")
        if budget.max_tokens is not None and budget.tokens >= budget.max_tokens:
            exceeded.append("tokens")
        if budget.max_cost_usd is not None and budget.cost_usd >= budget.max_cost_usd:
            exceeded.append("cost")
        if budget.max_depth is not None and len(prior_tools) >= budget.max_depth:
            exceeded.append("depth")
        state.update(
            {
                "exceeded": bool(exceeded),
                "exceeded_dimensions": exceeded,
                "calls": budget.calls,
                "tokens": budget.tokens,
                "cost_usd": round(budget.cost_usd, 6),
            }
        )
        return state

    def _charge_budget(self, agent: Agent | None, response) -> None:
        if agent is None:
            return
        budget = self.session.scalar(
            select(Budget).where(Budget.scope_type == "agent", Budget.scope_id == agent.id)
        )
        if budget is None:
            return
        budget.calls += 1
        budget.tokens += sum(response.usage.values())
        budget.cost_usd += response.cost_usd
        self.session.flush()
