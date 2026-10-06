"""The tool-call path: the guard itself, the verified-state gate, and the business
ladders and cascade/data-access risks `evaluate()` reads on a tool call.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from sqlalchemy import select

from agentfox.business.graph import BUSINESS_RANK
from agentfox.business.ladder import LadderDecision
from agentfox.business.ladder import evaluate as evaluate_ladder
from agentfox.business.store import load_ladders
from agentfox.containment.data_access import ReferenceTable, ScopeRule
from agentfox.containment.data_access import analyse_access as analyse_data_access
from agentfox.containment.effects import cascade_risk
from agentfox.core.models import AccessScopeRule, Agent, TaintTag, Tool, Trace
from agentfox.core.vocab import taint_rank
from agentfox.detection import TaintTracker
from agentfox.detection.actions import find_sql_argument
from agentfox.registry.service import record_edge
from agentfox.runtime.enforcement.result import EnforcementResult
from agentfox.runtime.enforcement.rules import _fired_rule

log = logging.getLogger("agentfox.runtime.enforcement")


class _ToolCallMixin:
    """Enforcer's tool-call path. Mixed into :class:`Enforcer`, never used alone."""

    def guard_tool_call(
        self,
        *,
        in_process: str = "enforced",
        exempt_rules: frozenset[str] = frozenset(),
        **kwargs: Any,
    ) -> EnforcementResult:
        """Authorise a tool call on the full execution path (P3-4, P2-2, P9).

        ``in_process`` says what the caller will do with the verdict, so a
        containment finding can say whether the call was actually stopped:
        ``"enforced"`` (the default) stops it where an enforce-mode rule did,
        ``"all"`` stops it on any rule that fired (strict ``auto(mode="enforce")``),
        ``"none"`` lets it run (``auto(mode="observe")``). ``exempt_rules`` are rule
        ids the caller lets through regardless. A dry run is always ``"none"``.
        """
        scope = "none" if kwargs.get("dry_run") else in_process
        self._containment_scope = (scope, exempt_rules)
        try:
            return self._guard_tool_call(**kwargs)
        finally:
            self._containment_scope = ("enforced", frozenset())

    def _guard_tool_call(
        self,
        *,
        agent_slug: str,
        tool_key: str,
        arguments: dict[str, Any],
        provenance: dict[str, str] | None = None,
        intent: str | None = None,
        trace: Trace | None = None,
        tracker: TaintTracker | None = None,
        credential: str | None = None,
        prior_tools: list[str] | None = None,
        prior_steps: list[dict[str, Any]] | None = None,
        verified_state: dict[str, Any] | None = None,
        dry_run: bool = False,
        approval_id: str | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Authorise a tool call on the full execution path (P3-4, P2-2, P9).

        ``approval_id`` is a retry of a call a person approved (#12): the same agent,
        tool and arguments run once. A dry run never spends one.

        ``persist=False`` computes the verdict without writing a Decision, its
        findings, taint tags or a lineage edge. The red-team runner uses it: a
        simulated attack is not production traffic, and persisting it put
        ``redteam.sim.*`` calls into findings and into what ``simulate`` replays.
        """
        agent, identity, _ = self.resolve(agent_slug, credential)

        # PL-3: a killed or quarantined agent must not execute tools either, not
        # just be denied new completions. `preflight` already checks this before an
        # agent reaches the model — but an integration that calls `guard_tool_call`
        # directly (McpGovernor, AgentFoxGuard.tool_node, any multi-step agentic
        # loop that already has a tool call decided) bypasses `preflight` entirely,
        # and this check was missing here. Found by benchmarking Tier D excessive-
        # agency scenarios: a quarantined agent's otherwise-valid, in-budget tool
        # call went straight through. Checked before anything else, same as
        # `preflight`, because "we killed this agent" is an operational fact, not a
        # policy outcome that a dry run should soften.
        control = self._control_verdict(agent)
        if control is not None:
            return control

        tracker = tracker or TaintTracker(trace_id=trace.id if trace else None)
        # Read on every call rather than cached on the tracker: a declaration made
        # mid-run (`agentfox declare tool X --output-trust trusted`) applies to the
        # next call, and a withdrawn one stops applying just as promptly.
        tracker.trusted_tools = frozenset(
            self.session.scalars(select(Tool.key).where(Tool.output_trust == "trusted"))
        )
        marks = tracker.taint_arguments(arguments, provenance)
        argument_taint = {path: mark.source for path, mark in marks.items()}
        # F3.8: which arguments were inferred (not caller-declared) from an
        # earlier tool's result, and which tool that was — see composition.py.
        argument_propagated_from = {
            path: mark.propagated_from for path, mark in marks.items() if mark.propagated_from
        }

        if trace and persist:
            for path, mark in marks.items():
                self.session.add(
                    TaintTag(
                        trace_id=trace.id,
                        path=path,
                        source=mark.source,
                        trust=mark.trust,
                        propagated_from=mark.propagated_from,
                    )
                )
        # Lineage is a property of the agent-to-tool relationship, not of whether a
        # trace object happened to be passed in — so it is recorded either way.
        if agent is not None and persist:
            record_edge(self.session, "agent", agent.slug, "tool", tool_key, "calls_tool")

        worst_source = max(argument_taint.values(), key=taint_rank) if argument_taint else "none"
        result = self.evaluate(
            agent=agent,
            identity=identity,
            content=json.dumps(arguments, default=str),
            surface="tool_args",
            trace=trace,
            taint_source=worst_source,
            tool_key=tool_key,
            arguments=arguments,
            argument_taint=argument_taint,
            argument_propagated_from=argument_propagated_from,
            intent=intent,
            prior_tools=prior_tools,
            prior_steps=prior_steps,
            tracker=tracker,
            approval_id=None if dry_run else approval_id,
            persist=persist,
        )

        # P9-7: an irreversible act on a record the agent has not read back from the
        # system of record is the HR-termination failure — the agent acted on a stale
        # or hallucinated view of the world. The check runs after the main evaluation
        # so it composes with, rather than replaces, everything else.
        stale = self._verified_state_gate(result, verified_state)
        if stale is not None and not dry_run:
            result.verdict = "block"
            result.effective_verdict = "block"
            result.rules_fired.append(stale)
            result.reason = stale["reason"]

        # P9-10: a dry run is analysis without execution. The verdict is computed and
        # recorded exactly as it would be, and the caller is told what *would* have
        # happened — which is what makes a policy safe to roll out.
        if dry_run:
            result.taint["dry_run"] = True
            result.verdict = "allow"
        return result

    def _verified_state_gate(
        self, result: EnforcementResult, verified_state: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        capability = (result.taint or {}).get("capability") or {}
        constraints = capability.get("constraints") or {}
        if not constraints.get("requires_verified_state"):
            return None

        max_age = self.settings.verified_state_max_age_seconds
        if not verified_state or not verified_state.get("read_at"):
            reason = (
                "this capability requires the record to be read back from the system "
                "of record before an irreversible act, and no state read was supplied"
            )
        else:
            try:
                read_at = dt.datetime.fromisoformat(str(verified_state["read_at"]))
                if read_at.tzinfo is None:
                    read_at = read_at.replace(tzinfo=dt.UTC)
                age = (dt.datetime.now(dt.UTC) - read_at).total_seconds()
            except ValueError:
                age = float("inf")
            if age <= max_age:
                return None
            reason = (
                f"the state read is {int(age)}s old and the capability requires it to "
                f"be no older than {max_age}s"
            )
        return _fired_rule(
            "action.unverified_state",
            "block",
            reason,
            severity="critical",
            controls=["NOM-RTG-09", "NOM-IAM-03"],
        )

    def _business_ladders(
        self,
        agent: Agent | None,
        surface: str,
        tool_key: str | None,
        arguments: dict[str, Any] | None,
    ) -> list[LadderDecision]:
        """Evaluate the business ladders that apply to this call.

        Only on the tool-argument surface: a ladder bands a number the caller is about
        to act on, and there is no such number on an input or an output. When several
        apply, the strictest wins and the disagreement is a lint finding rather than a
        silent precedence rule — two authors disagreeing is a fact about the
        organisation, not a merge conflict.

        Every deciding ladder is returned, strictest first, because each carries its
        own mode: the strictest *enforcing* ladder is what is applied, and an
        observe ladder stricter than it is only recorded.
        """
        if surface != "tool_args" or not arguments:
            return []
        try:
            ladders = load_ladders(
                self.session, tool=tool_key, agent_id=agent.id if agent else None
            )
        except Exception as exc:  # pragma: no cover - storage must not break the path
            log.warning("business ladders unavailable: %s", exc)
            return []
        if not ladders:
            return []

        request = {"arguments": arguments, "tool": tool_key}
        decisions = [
            evaluate_ladder(ladder, request)
            for ladder in ladders
            if ladder.tool in (None, tool_key)
        ]
        decisions = [d for d in decisions if d.matched or d.undecidable]
        return sorted(decisions, key=lambda d: BUSINESS_RANK.get(d.outcome, 0), reverse=True)

    def _cascade_and_access_risks(
        self, tool_key: str | None, arguments: dict[str, Any] | None
    ) -> dict[str, Any]:
        """P9 cascade risk (`effects.cascade_risk`) and P18 data-access scoping
        (`data_access.analyse_access`) — wired into the live path here, rather than
        living only in their own test files as before. Both are opt-in in the
        precise sense that nothing is declared by default: a `Tool` with no
        `triggers_json` and a database with no `AccessScopeRule` rows make this a
        zero-cost no-op, and an undeclared trigger or an undeclared table stays
        invisible, matching each module's own documented limitation rather than
        overclaiming coverage. Never raises — a governance extra must not break the
        call it exists to police.
        """
        extra: dict[str, Any] = {}
        extra_risks: list[dict[str, Any]] = []
        try:
            if arguments and (sql := find_sql_argument(arguments)):
                scope_rows = self.session.scalars(select(AccessScopeRule)).all()
                rules = [
                    ScopeRule(
                        table=r.table_name,
                        column=r.column or "",
                        principal_key=r.principal_key,
                        restricted_columns=tuple(r.restricted_columns or ()),
                    )
                    for r in scope_rows
                    if not r.is_reference and r.column
                ]
                reference = [
                    ReferenceTable(table=r.table_name) for r in scope_rows if r.is_reference
                ]
                if rules or reference:
                    access = analyse_data_access(
                        sql,
                        principal=None,
                        rules=rules,
                        reference=reference,
                        dialect=self.settings.sql_dialect,
                        strictness=self.settings.data_access_strictness,
                    )
                    extra["access"] = access.to_json()
                    extra_risks.extend(f.to_json() for f in access.findings)

            if tool_key:
                org_tools = self.session.scalars(select(Tool)).all()
                triggers = {t.key: t.triggers_json for t in org_tools if t.triggers_json}
                if triggers:
                    destructive = tuple(t.key for t in org_tools if t.impact == "irreversible")
                    cascade = cascade_risk(tool_key, triggers, destructive=destructive)
                    extra["cascade"] = cascade.to_json()
                    extra_risks.extend(f.to_json() for f in cascade.findings)
        except Exception as exc:  # pragma: no cover - governance extra must not break the call
            log.warning("cascade/access analysis unavailable: %s", exc)
            return {}

        if extra_risks:
            extra["risks"] = extra_risks
        return extra
