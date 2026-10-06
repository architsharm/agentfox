"""The Enforcer: identity resolution and the core `evaluate()` every surface runs.

The other stages live beside this module as mixins, one job each; this class is
where they become one object.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.business.graph import combine as combine_business
from agentfox.containment.findings import (
    detector_verdict,
    is_detector_rule,
    matches_detector_rule,
    raise_containment_findings,
)
from agentfox.core.config import get_settings
from agentfox.core.models import Agent, Decision, Identity, Tool, Trace, as_aware, utcnow
from agentfox.detection import DetectionContext, DetectorPipeline, TaintTracker, redact_content
from agentfox.detection.actions import analyse_arguments
from agentfox.detection.actions import summarise as summarise_actions
from agentfox.detection.composition import check_composed_escalation
from agentfox.detection.tuning import LatencyLedger, active_suppressions, explain, filter_suppressed
from agentfox.grounding.context_integrity import assemble_context
from agentfox.platform.identity import (
    check_capability,
    redeem_approval,
    request_approval,
    verify_credential,
)
from agentfox.platform.policy import (
    PolicyInput,
    UnloadablePolicyVersion,
    combine,
    get_engine,
    policies_in_force,
)
from agentfox.platform.policy.taint_view import policy_taint
from agentfox.platform.registry.service import observe_agent
from agentfox.prove.audit import chain
from agentfox.prove.audit.trace import (
    ATTR_AGENT,
    ATTR_TAINT,
    ATTR_TOOL_IMPACT,
    ATTR_TOOL_NAME,
    ATTR_VERDICT,
    add_span,
)
from agentfox.prove.findings import raise_finding
from agentfox.runtime.enforcement.approvals import held_call
from agentfox.runtime.enforcement.checks import _ChecksMixin
from agentfox.runtime.enforcement.completion import _CompletionMixin
from agentfox.runtime.enforcement.findings import _FindingsMixin
from agentfox.runtime.enforcement.limits import _LimitsMixin
from agentfox.runtime.enforcement.result import EnforcementResult
from agentfox.runtime.enforcement.rules import (
    _CAPABILITY_REFUSAL_RULE_IDS,
    _FALLBACK_VERSION,
    _RANK,
    RISK_CODE_RULE_IDS,
    _fallback_policies,
    _fired_rule,
)
from agentfox.runtime.enforcement.streaming import _StreamingMixin
from agentfox.runtime.enforcement.surfaces import _SurfacesMixin
from agentfox.runtime.enforcement.tool_calls import _ToolCallMixin


def _relies_on_detections(doc: Any, surface: str) -> bool:
    """Does this pack have an enabled detection rule that applies on ``surface``?"""
    return any(
        rule.enabled
        and rule.when.detection is not None
        and (not rule.when.surface or surface in rule.when.surface)
        for rule in doc.rules
    )


@dataclass
class _Evaluation:
    """One `Enforcer.evaluate` call: its inputs, and what each step has worked out.

    The steps run in a fixed order and each reads what earlier steps set, so a field
    is only meaningful once the step that sets it has run.
    """

    # inputs, exactly as `evaluate` received them
    started: float
    agent: Agent | None
    identity: Identity | None
    content: str
    surface: str
    trace: Trace | None
    taint_source: str
    tool_key: str | None
    arguments: dict[str, Any] | None
    argument_taint: dict[str, str] | None
    argument_propagated_from: dict[str, str] | None
    memory_entry: dict[str, Any] | None
    intent: str | None
    schema: dict[str, Any] | None
    prior_tools: list[str] | None
    prior_steps: list[dict[str, Any]] | None
    tracker: TaintTracker | None
    conversation_window: list[str] | None
    completion: dict[str, Any] | None
    persist: bool
    forced_rules: list[dict[str, Any]] | None
    extra_taint: dict[str, Any] | None
    approval_id: str | None

    # _resolve_tool
    agent_slug: str | None = None
    environment: str = "production"
    trace_id: str | None = None
    tool_impact: str = "read"
    tool_known: bool = True
    # _run_detectors
    ledger: Any = None
    pipeline_result: Any = None
    suppressed: Any = None
    detections: list[dict[str, Any]] = field(default_factory=list)
    detector_run_ids: list[str] = field(default_factory=list)
    # _check_capability, _run_content_checks, ladders, _analyse_action, budgets
    capability: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    pending_risks: list[dict[str, Any]] = field(default_factory=list)
    ladder_decisions: list[Any] = field(default_factory=list)
    action: dict[str, Any] = field(default_factory=dict)
    budget: Any = None
    taint_summary: dict[str, Any] = field(default_factory=dict)
    # _evaluate_policies, then every step that raises a verdict
    evaluated: list[Any] = field(default_factory=list)
    unloadable: list[UnloadablePolicyVersion] = field(default_factory=list)
    policy_version_ids: list[str] = field(default_factory=list)
    policy_version_id: str | None = None
    verdict: str = "allow"
    effective: str = "allow"
    mode: str = "observe"
    rules_fired: list[dict[str, Any]] = field(default_factory=list)
    fired_ids: set[Any] = field(default_factory=set)
    # _redeem_approval, _build_result
    held: tuple[str | None, Any] = (None, None)
    redeemed_approval: Any = None
    latency_ms: float = 0.0
    reason: str = ""


class Enforcer(
    _SurfacesMixin,
    _ToolCallMixin,
    _CompletionMixin,
    _StreamingMixin,
    _ChecksMixin,
    _LimitsMixin,
    _FindingsMixin,
):
    """The request path every inline surface goes through (see the package docstring)."""

    def __init__(self, session: Session, pipeline: DetectorPipeline | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.pipeline = pipeline or DetectorPipeline()
        self.engine = get_engine()
        # One ledger per request, not per call. Reset at the start of each
        # governed completion; a bare `evaluate()` gets a fresh one on demand.
        self._ledger: LatencyLedger | None = None
        # The retrieval set, records and entities the answer was built from.
        # Set by the caller (SDK, LangGraph guard, gateway) before a governed call.
        # Also read by the commitment and context checks: `channel`/`counterparty` (AI
        # disclosure), `decision` (adverse action), `chunks` (chunk coherence),
        # `principal` and `memory` (memory binding), `retrieval`/`baseline` (retrieval
        # drift).
        self.evidence: dict[str, Any] = {}

    #: Context assembly is the caller's step, not ours: it needs the ranked
    #: chunks and the real token budget, and it repairs as well as reports. Exposed
    #: here so whoever performs retrieval can run it (and feed the resulting findings
    #: back through `evidence`) without reaching into `context_integrity` directly.
    assemble_context = staticmethod(assemble_context)

    def resolve(
        self,
        agent_slug: str | None,
        credential: str | None = None,
        environment: str = "production",
        model: str | None = None,
        framework: str | None = None,
    ) -> tuple[Agent | None, Identity | None, bool]:
        identity = verify_credential(self.session, credential) if credential else None
        if identity is not None and identity.agent_id and not agent_slug:
            agent = self.session.get(Agent, identity.agent_id)
            if agent is not None:
                # Debounced for the same reason as observe_agent()'s own
                # last_seen_at write (registry/service.py) — an unconditional
                # write here is the same redundant-second-writer hazard when this
                # session and another already-open session both resolve the same
                # agent within one logical call.
                now = utcnow()
                last_seen = as_aware(agent.last_seen_at)
                if last_seen is None or (now - last_seen) > dt.timedelta(seconds=5):
                    agent.last_seen_at = now
                return agent, identity, False

        if not agent_slug:
            return None, identity, False

        agent, is_shadow = observe_agent(
            self.session,
            agent_slug,
            environment=environment,
            model=model,
            framework=framework,
        )
        if identity is None and not credential:
            # Only when no credential was presented: an unauthenticated caller naming
            # a registered agent is governed under that agent's identity, which is
            # the shadow-traffic rule. A credential that was presented and did *not*
            # verify must never be upgraded to the named agent's identity — that
            # would make a wrong key indistinguishable from the right one.
            identity = self.session.scalar(select(Identity).where(Identity.agent_id == agent.id))
        return agent, identity, is_shadow

    def ledger(self) -> LatencyLedger:
        """The request-level detector budget."""
        if self._ledger is None:
            self._ledger = LatencyLedger(budget_ms=self.settings.request_budget_ms)
        return self._ledger

    def reset_ledger(self) -> LatencyLedger:
        self._ledger = LatencyLedger(budget_ms=self.settings.request_budget_ms)
        return self._ledger

    def evaluate(
        self,
        *,
        agent: Agent | None,
        identity: Identity | None,
        content: str,
        surface: str,
        trace: Trace | None = None,
        taint_source: str = "user",
        tool_key: str | None = None,
        arguments: dict[str, Any] | None = None,
        argument_taint: dict[str, str] | None = None,
        argument_propagated_from: dict[str, str] | None = None,
        memory_entry: dict[str, Any] | None = None,
        intent: str | None = None,
        schema: dict[str, Any] | None = None,
        prior_tools: list[str] | None = None,
        prior_steps: list[dict[str, Any]] | None = None,
        tracker: TaintTracker | None = None,
        conversation_window: list[str] | None = None,
        completion: dict[str, Any] | None = None,
        persist: bool = True,
        forced_rules: list[dict[str, Any]] | None = None,
        extra_taint: dict[str, Any] | None = None,
        approval_id: str | None = None,
    ) -> EnforcementResult:
        """One decision on one surface. The single point every guarantee flows through.

        `conversation_window` is the only argument here that is not about *this*
        message: it is the recent user turns, oldest first, ending with this one,
        supplied by `check_conversation_window`. It exists so the trajectory check
        can run through the same channel as every other check rather than beside it.

        `forced_rules` are synthetic rules a surface decided before calling this — an
        agent message's replay or bad-signature refusal, say. They are applied (by
        lattice maximum, whatever the packs' mode) *before* the decision is persisted
        and audited, so the record says what the caller is told. An effect outside
        the lattice (``observe``) is recorded and changes nothing. `extra_taint` is
        merged into the recorded taint summary.

        `approval_id` is a retry presenting a person's approval of this exact call.
        It only ever turns an escalation into an allow, and only when the
        approval is for this agent, tool and arguments, unexpired and unused.

        The steps run in a fixed order, each one a method below: the kill switch,
        the tool's declaration, the detectors, the capability grant, the content
        checks, business ladders, action analysis, budgets, the policies in force,
        then the facts that stand on their own whatever the packs say, fail modes,
        ladder outcomes, forced rules, approval redemption, and finally the record.
        """
        # A killed or quarantined agent is refused on every surface, before
        # anything else runs. Checked here so that it covers every surface that
        # reaches a decision (/v1/guard/input, /output, /memory_write,
        # /agent_message), not only the completion and tool-call paths: the kill
        # switch promises that every governed call is refused.
        control = self._control_verdict(agent)
        if control is not None:
            return control

        call = _Evaluation(
            started=time.perf_counter(),
            agent=agent,
            identity=identity,
            content=content,
            surface=surface,
            trace=trace,
            taint_source=taint_source,
            tool_key=tool_key,
            arguments=arguments,
            argument_taint=argument_taint,
            argument_propagated_from=argument_propagated_from,
            memory_entry=memory_entry,
            intent=intent,
            schema=schema,
            prior_tools=prior_tools,
            prior_steps=prior_steps,
            tracker=tracker,
            conversation_window=conversation_window,
            completion=completion,
            persist=persist,
            forced_rules=forced_rules,
            extra_taint=extra_taint,
            approval_id=approval_id,
        )
        self._resolve_tool(call)
        self._run_detectors(call)
        self._check_capability(call)
        self._run_content_checks(call)
        # Business ladders are evaluated separately from policy and combined
        # afterwards (`_apply_ladders`), because the two compose by different
        # algebras: rules take the lattice maximum, ladders select exactly one band.
        call.ladder_decisions = self._business_ladders(agent, surface, tool_key, arguments)
        self._analyse_action(call)
        # --- budgets & loop containment ---------------------
        call.budget = self._budget_state(
            agent, trace, tool_key, prior_tools or [], prior_steps, arguments
        )
        self._summarise_taint(call)
        self._evaluate_policies(call)
        self._apply_capability(call)
        self._raise_evidence_findings(call)
        self._apply_standing_refusals(call)
        self._apply_fail_modes(call)
        self._apply_ladders(call)
        self._apply_forced_rules(call)
        self._redeem_approval(call)
        result = self._build_result(call)
        if not persist:
            return result
        self._persist_decision(call, result)
        return result

    # ------------------------------------------------------------------
    # The steps of `evaluate`, in the order it runs them
    # ------------------------------------------------------------------

    def _resolve_tool(self, call: _Evaluation) -> None:
        """The tool's declared impact, and whether it was declared at all."""
        agent = call.agent
        call.agent_slug = agent.slug if agent else None
        call.environment = agent.environment if agent else "production"
        call.trace_id = call.trace.id if call.trace else None

        tool_key = call.tool_key
        tool = self.session.scalar(select(Tool).where(Tool.key == tool_key)) if tool_key else None
        # An undeclared tool gets `impact = "read"`, the *least* dangerous value
        # in the vocabulary, because inventing a higher one would be a guess. On
        # its own that would let every impact-based rule above `read` skip the
        # one case where the platform knows least, so the not-knowing is surfaced
        # as its own fact instead, for policy to decide on.
        call.tool_impact = tool.impact if tool else "read"
        call.tool_known = tool is not None if tool_key else True

    def _run_detectors(self, call: _Evaluation) -> None:
        """The detector pipeline (budgeted, concurrent), then suppressions."""
        # --- 4. detector pipeline (budgeted, concurrent) -----------------
        context = DetectionContext(
            surface=call.surface,
            agent_slug=call.agent_slug,
            trace_id=call.trace_id,
            tool_key=call.tool_key,
            tool_impact=call.tool_impact,
            intent=call.intent,
            taint_source=call.taint_source,
            schema=call.schema,
            prior_tools=call.prior_tools or [],
        )
        ledger = self.ledger()
        pipeline_result = self.pipeline.run(
            call.content, context, budget_ms=ledger.allowance_ms(self.pipeline.budget_ms)
        )
        ledger.charge(pipeline_result, call.surface)
        call.ledger = ledger
        call.pipeline_result = pipeline_result

        # Suppressions are applied here rather than inside the pipeline. A
        # suppression is a governance decision about a detector's output, not a
        # detector concern, and keeping it out of the pipeline means the raw detector
        # result stays honest.
        suppressions = active_suppressions(self.session, call.agent.id if call.agent else None)
        call.suppressed = filter_suppressed(pipeline_result, suppressions, surface=call.surface)

        call.detections = [
            {
                "entity_type": d.entity_type,
                "score": d.score,
                "owasp_id": d.owasp_id,
                "atlas_id": d.atlas_id,
            }
            for d in pipeline_result.detections
        ]

        if call.persist:
            call.detector_run_ids = self._persist_detectors(
                pipeline_result, call.trace_id, call.surface
            )

    def _check_capability(self, call: _Evaluation) -> None:
        """Does the identity hold a grant for this tool, within its limits?"""
        # --- capability check -------------------------------------
        call.capability = {"granted": True, "requires_approval": False, "state": "granted"}
        if call.tool_key:
            decision = check_capability(
                self.session,
                call.identity,
                call.tool_key,
                arguments=call.arguments or {},
                argument_taint=call.argument_taint or {},
            )
            call.capability = decision.to_json()

    def _run_content_checks(self, call: _Evaluation) -> None:
        """Evidence integrity, disclosure, and the risk-raising checks, in one channel."""
        agent, surface, content, intent = call.agent, call.surface, call.content, call.intent
        # --- evidence integrity (output surface only) ----------------
        # Groundedness asks whether the claim is supported by the text. It does not
        # ask whether the text was authoritative, nor whether 5 + 3 = 9.
        # Both are properties of the answer's relationship to its evidence, so they
        # run here, where the evidence is in hand.
        evidence = self._evidence_checks(agent, surface, content, intent)
        disclosure = self._disclosure_checks(agent, surface, content, call.trace_id)
        if disclosure:
            merged_issues = [
                *evidence.get("evidence_issues", []),
                *disclosure.pop("evidence_issues", []),
            ]
            evidence.update(disclosure)
            if merged_issues:
                evidence["evidence_issues"] = merged_issues

        # --- commitments / context integrity ---------------------------
        # Same channel as the two checks above, deliberately: one `evidence` dict that
        # lands in `taint_summary`, one `evidence_issues` list that becomes `Finding`
        # rows, one `rules_fired`. The only thing these add is `risks`, which join
        # `action["risks"]` below — the list the policy engine's `action_risk` condition
        # already reasons over, so a policy author can act on them without a schema
        # change. Nothing here sets a verdict on its own.
        pending_risks: list[dict[str, Any]] = []
        for extra in (
            self._commitment_checks(agent, surface, content, intent),
            self._context_checks(surface, content, call.memory_entry),
            self._control_flow_checks(surface, call.tool_key),
            self._sycophancy_checks(surface, content, intent),
            self._trajectory_checks(surface, call.conversation_window),
        ):
            if not extra:
                continue
            extra_issues = extra.pop("evidence_issues", [])
            pending_risks.extend(extra.pop("risks", []))
            evidence.update(extra)
            if extra_issues:
                evidence["evidence_issues"] = [
                    *evidence.get("evidence_issues", []),
                    *extra_issues,
                ]
        call.evidence = evidence
        call.pending_risks = pending_risks

    def _analyse_action(self, call: _Evaluation) -> None:
        """What the call's arguments would do, and the risks that follow from it."""
        arguments = call.arguments
        # --- action assurance ------------------------------------------
        # Argument-level containment governs *the call*; this governs *the artefact*.
        # An agent holding a legitimate `db.query` capability can pass `DROP TABLE` as
        # a well-formed string, and every argument check would pass it.
        action = (
            summarise_actions(
                analyse_arguments(arguments or {}, dialect=self.settings.sql_dialect),
                call.environment,
            )
            if arguments
            else {}
        )

        # --- cascade risk / data-access scoping, when declared ----------
        # Same block as the action-assurance check above, extending the same
        # `action["risks"]`/`action["critical"]` the policy engine already reasons
        # over (`policy/engine.py`'s `action_risk` glob condition) — no policy-layer
        # change needed for either check to actually start firing.
        extras = self._cascade_and_access_risks(call.tool_key, arguments)
        if extras:
            extra_risks = extras.pop("risks", [])
            action.update(extras)
            if extra_risks:
                action["risks"] = [*action.get("risks", []), *extra_risks]
                action["critical"] = [r for r in action["risks"] if r["severity"] == "critical"]

        # Commitment and context risks reach the policy engine exactly as the cascade
        # and data-access ones above do, and deliberately never join
        # `action["critical"]` — that list is hard-blocked later
        # (`_apply_standing_refusals`), which is the one thing these checks must not do.
        # They are capped at `high` at the point of construction so this stays true even
        # if a detector raises its own severity later.
        if call.pending_risks:
            action["risks"] = [*action.get("risks", []), *call.pending_risks]
        call.action = action

    def _summarise_taint(self, call: _Evaluation) -> None:
        """The taint summary every decision records and policy reasons over."""
        agent = call.agent
        ladder_decision = call.ladder_decisions[0] if call.ladder_decisions else None
        taint_summary = (
            call.tracker.summary() if call.tracker else {"max_source": call.taint_source}
        )
        taint_summary = {
            **taint_summary,
            "arguments": call.argument_taint or {},
            "tool_impact": call.tool_impact,
            "risk_tier": agent.risk_tier if agent else "limited",
            "capability": call.capability,
            "budget": call.budget,
            "detections": call.detections,
            "prior_tools": call.prior_tools or [],
            "detector_degraded": bool(call.pipeline_result.degraded),
            "arguments_snapshot": call.arguments or {},
            "action": call.action,
            "business": ladder_decision.to_json() if ladder_decision else {},
            **call.evidence,
        }
        if call.surface == "tool_args":
            # Recorded on the decision, not only read from settings, so a replay
            # reasons about this call the way the live path did (policy/taint_view.py).
            taint_summary["scope"] = self.settings.taint_scope
        call.taint_summary = taint_summary

    def _evaluate_policies(self, call: _Evaluation) -> None:
        """Evaluate every pack in force for this subject and combine their decisions."""
        agent, agent_slug, environment = call.agent, call.agent_slug, call.environment
        # --- 5. policy decision -----------------------------------
        pinput = PolicyInput(
            agent_slug=agent_slug,
            risk_tier=agent.risk_tier if agent else "limited",
            environment=environment,
            surface=call.surface,
            tool_key=call.tool_key,
            tool_impact=call.tool_impact,
            tool_known=call.tool_known,
            arguments=call.arguments or {},
            intent=call.intent,
            detections=call.detections,
            # What policy reasons over: the configured taint scope, and provenance an
            # explicit grant accepts. The record keeps the unmodified summary.
            taint=policy_taint(call.taint_summary, call.capability),
            capability=call.capability,
            budget=call.budget,
            prior_tools=call.prior_tools or [],
            detector_degraded=bool(call.pipeline_result.degraded),
            action=call.action,
            completion=call.completion or {},
        )

        # The hierarchy decides what is in force for this subject — the same
        # resolution `policy effective` prints — so a team-scoped `restrict` binds
        # only that team's agents and a granted `override` really loosens.
        #
        # A bound version that no longer loads (a row older than the validator
        # that now reads it) is collected rather than raised: the other packs are
        # still evaluated, and the gap is handled below under the fail mode, the
        # way a degraded detector pipeline is.
        unloadable: list[UnloadablePolicyVersion] = []
        bound = policies_in_force(
            self.session,
            agent_slug,
            environment,
            # "" rather than None: the agent is known and has no team, so there is
            # nothing to look up.
            team=(agent.owner_team or "") if agent else None,
            skipped=unloadable,
        )
        # Nothing bound is not the same as nothing to check.
        #
        # A database that has never been initialised holds no policies, so without
        # a fallback every content rule would be skipped and `auto()` would govern
        # nothing while announcing a mode — and adding one line to an existing
        # application is the integration this product leads with.
        #
        # So the shipped baseline applies as a fallback. Deliberately OBSERVE
        # only, and deliberately only `baseline`:
        #
        #   - Observe because silently blocking traffic in an application whose
        #     owner configured nothing is how governance gets ripped out.
        #     Detections are recorded, so the findings and traces are real and the
        #     banner is accurate, and nothing is refused that would not have been
        #     refused anyway.
        #   - `baseline` alone because it is the general content pack.
        #     eu-ai-act-high-risk is jurisdiction- and risk-tier specific, and
        #     applying it to everyone by default would be overclaiming on
        #     somebody else's behalf. tool-containment needs no help: capability
        #     default-deny does not depend on a policy binding and already
        #     refuses an ungranted call with zero policies present.
        #
        # In memory, never written: the moment an operator runs `agentfox init`
        # or binds their own, this stops applying and their policies decide. A
        # fallback that seeded itself into the database would be a tool editing
        # the configuration it is supposed to be governed by.
        #
        # Not when a pack is bound but unloadable: something *is* configured, and
        # substituting the observe-only baseline for it would read as governed.
        if not bound and not unloadable:
            fallback = _fallback_policies(getattr(agent, "risk_tier", None))
            if fallback:
                bound = [
                    (doc, _FALLBACK_VERSION, None)
                    for doc in fallback
                    if doc.matches_scope(agent_slug, environment)
                ]
        evaluated = [
            (doc, version, self.engine.evaluate(doc, pinput)) for doc, version, _b in bound
        ]
        merged = combine([d for _doc, _v, d in evaluated]) if evaluated else None

        # A decision is only reproducible if the *whole* set of versions in force
        # is recorded, not just the one that happened to win.
        # None is filtered, not stored: see _FallbackVersion. A decision made
        # under the fallback records no policy version, because there is none.
        policy_version_ids = [
            version.id for _doc, version, _d in evaluated if version.id is not None
        ]
        call.policy_version_id = next(
            (
                version.id
                for doc, version, _d in evaluated
                if merged and merged.policy_key == doc.key
            ),
            policy_version_ids[0] if policy_version_ids else None,
        )
        call.policy_version_ids = policy_version_ids
        call.evaluated = evaluated
        call.unloadable = unloadable

        call.verdict = merged.verdict if merged else "allow"
        call.effective = merged.effective_verdict if merged else "allow"
        call.mode = merged.mode if merged else self.settings.default_policy_mode
        call.rules_fired = [r.to_json() for r in merged.rules_fired] if merged else []

    def _apply_capability(self, call: _Evaluation) -> None:
        """A missing grant blocks and a grant that needs approval escalates."""
        capability, rules_fired = call.capability, call.rules_fired
        # A capability denial is not a policy opinion — it is the absence of a grant,
        # and it stands whether or not a policy happened to cover the case. The
        # synthetic rule is only added when no policy already said the same thing,
        # so a customer who wrote the rule explicitly does not see it twice.
        call.fired_ids = fired_ids = {r.get("rule_id") for r in rules_fired}
        if not capability.get("granted", True):
            call.verdict = "block"
            call.effective = "block"
            if not (fired_ids & _CAPABILITY_REFUSAL_RULE_IDS):
                # Two different refusals, and saying the wrong one is a defect a
                # reader can catch: "no grant exists" versus "the grant you hold
                # declares a limit this call exceeded".
                if capability.get("constraint_violations"):
                    synthetic_id = "capability.constraint_violated"
                    synthetic_reason = capability.get("constraint_reason") or "; ".join(
                        capability.get("reasons") or []
                    )
                else:
                    synthetic_id = "capability.default_deny"
                    synthetic_reason = "; ".join(
                        capability.get("reasons") or ["no capability granted"]
                    )
                rules_fired.append(
                    _fired_rule(
                        synthetic_id,
                        "block",
                        synthetic_reason,
                        severity="high",
                        controls=["NOM-IAM-02"],
                    )
                )
        elif capability.get("requires_approval") and call.effective != "block":
            call.effective = "escalate"
            if call.mode == "enforce":
                call.verdict = "escalate"
            if "capability.approval_required" not in fired_ids:
                rules_fired.append(
                    _fired_rule(
                        "capability.requires_approval",
                        "escalate",
                        "; ".join(capability.get("reasons") or ["approval required"]),
                        severity="medium",
                        controls=["NOM-IAM-03"],
                        mode=call.mode,
                    )
                )

    def _raise_evidence_findings(self, call: _Evaluation) -> None:
        """Integrity issues the content checks found become findings, not blocks."""
        agent = call.agent
        # An unauthoritative or arithmetically wrong answer is a finding, not
        # a block. Blocking here would withhold a mostly-correct answer over a
        # currency mismatch, and the failure this addresses is *silent* wrongness —
        # surfacing it is the control.
        for issue in call.evidence.get("evidence_issues", []):
            raise_finding(
                self.session,
                type=issue["type"],
                severity=issue.get("severity", "medium"),
                title=issue["title"],
                subject_type="agent",
                subject_id=agent.id if agent else None,
                evidence={**issue, "trace_id": call.trace_id},
                # Source-authority and numeric-integrity issues evidence NOM-RTG-12;
                # the commitment and context issues that flow through this same loop
                # evidence different controls and say so, rather than being filed
                # under a control they do not support.
                control_keys=issue.get("control_keys") or ["NOM-RTG-12"],
                # One finding per (agent, issue type, issue code, surface): the same
                # integrity failure on every answer is one problem with a count.
                fingerprint_parts=(issue.get("code"), call.surface),
            )

    def _apply_standing_refusals(self, call: _Evaluation) -> None:
        """Facts that refuse a call on their own, whatever the packs say.

        An entitlement disclosure, a critical action risk and a composed escalation
        are facts about this call, not policy opinions, so each stands alone. A rule
        a pack already fired under the same id is not added twice.
        """
        rules_fired, fired_ids = call.rules_fired, call.fired_ids
        # An answer quoting a chunk the asking human is not entitled to see is
        # the oversharing failure itself, not a quality issue, so unlike the evidence
        # issues above it is preventive: the answer is withheld whenever the decision
        # enforces, and recorded as would-have-blocked when it observes. Gated on the
        # decision's mode like an approval requirement, because a principal declared
        # in observe mode is how an operator dry-runs an entitlement model.
        leaks = [
            i
            for i in call.evidence.get("evidence_issues", [])
            if i["type"] == "entitlement_disclosure"
        ]
        if leaks and "entitlement.disclosure" not in fired_ids:
            call.effective = "block"
            if call.mode == "enforce":
                call.verdict = "block"
            fired_ids.add("entitlement.disclosure")
            rules_fired.append(
                _fired_rule(
                    "entitlement.disclosure",
                    "block",
                    "; ".join(i["title"] for i in leaks),
                    severity="critical",
                    controls=["NOM-IAM-07"],
                    mode=call.mode,
                )
            )

        # A critical action risk stands on its own, exactly as a capability denial
        # does. It is a fact about what the statement will do, not a policy opinion —
        # and a customer who wrote the rule explicitly does not see it twice.
        for risk in call.action.get("critical", []):
            # A risk *code* is how `effects.py` and `actions.py` name a condition;
            # a rule id is how a decision names what fired. For the conditions the
            # shipped packs already have a rule for, they are the same rule and must
            # print under one id — otherwise the same refusal appears twice, once
            # dotted and once hyphenated, and the dedupe below never sees it.
            rule_id = RISK_CODE_RULE_IDS.get(risk["code"], risk["code"])
            if rule_id in fired_ids:
                # Deduped, but the risk knows something the pack's written reason
                # does not — which destructive tool, which table. Keep that on the
                # entry that survives rather than losing it with the duplicate.
                for existing in rules_fired:
                    if existing.get("rule_id") == rule_id and "evidence" not in existing:
                        existing["evidence"] = risk.get("evidence", {})
                        existing["detail"] = risk["detail"]
                continue
            call.verdict = "block"
            call.effective = "block"
            fired_ids.add(rule_id)
            rules_fired.append(
                _fired_rule(
                    rule_id,
                    "block",
                    risk["detail"],
                    severity="critical",
                    controls=["NOM-RTG-09"],
                    evidence=risk.get("evidence", {}),
                )
            )

        # A read tool's output flowing into a higher-impact tool's
        # argument is a composed escalation neither tool's own scope permits
        # alone — a fact about this call's inputs, not a policy opinion, so it
        # stands on its own exactly like the critical-action-risk check above.
        tool_key = call.tool_key
        composition_findings = (
            check_composed_escalation(
                consuming_tool_key=tool_key,
                consuming_tool_impact=call.tool_impact,
                argument_propagated_from=call.argument_propagated_from or {},
                tool_impact_lookup=lambda key: self.session.scalar(
                    select(Tool.impact).where(Tool.key == key)
                ),
            )
            if tool_key
            else []
        )
        call.taint_summary["composition"] = [f.to_json() for f in composition_findings]
        for finding in composition_findings:
            rule_id = f"composition.escalation.{finding.argument_path}"
            if rule_id in fired_ids:
                continue
            call.verdict = "block"
            call.effective = "block"
            fired_ids.add(rule_id)
            rules_fired.append(
                _fired_rule(
                    "composition.escalation",
                    "block",
                    finding.reason,
                    severity="critical",
                    controls=["NOM-RTG-09"],
                    evidence=finding.to_json(),
                )
            )

    def _apply_fail_modes(self, call: _Evaluation) -> None:
        """Degraded detectors and unloadable packs, under the deployment's and packs' fail modes."""
        pipeline_result, rules_fired = call.pipeline_result, call.rules_fired
        # A degraded pipeline means reduced coverage. Fail-closed converts that
        # into a block; fail-open accepts it and records the gap.
        #
        # Two sources, the stricter wins: the deployment-wide `fail_mode`, for an
        # enforcing decision, and each pack's own `fail_mode`. A pack fails closed only
        # where its coverage actually depended on the detectors: it is enforcing, says
        # `closed`, and has an enabled detection rule for this surface.
        closed_packs = (
            [
                doc.key
                for doc, _version, _decision in call.evaluated
                if doc.mode == "enforce"
                and doc.fail_mode == "closed"
                and _relies_on_detections(doc, call.surface)
            ]
            if pipeline_result.degraded
            else []
        )
        deployment_closed = self.settings.fail_mode == "closed" and call.mode == "enforce"
        if pipeline_result.degraded and (deployment_closed or closed_packs):
            call.verdict = "block"
            call.effective = "block"
            source = (
                f"policy {', '.join(closed_packs)} declares fail_mode=closed"
                if closed_packs and not deployment_closed
                else "fail_mode=closed"
            )
            rules_fired.append(
                _fired_rule(
                    "pipeline.fail_closed",
                    "block",
                    f"detectors degraded ({pipeline_result.degraded}) and {source}",
                    severity="medium",
                    controls=["NOM-RTG-06"],
                )
            )

        # The same two sources for a bound policy version that no longer loads: the
        # deployment's `fail_mode`, and the fail_mode the stored pack declared. A
        # pack bound in observe would not have blocked anything, so its absence is
        # recorded and never blocks; an enforcing pack fails closed if either
        # source says closed, and otherwise the call is allowed with the gap named
        # in the decision.
        for missing in call.unloadable:
            closed = missing.binding_mode == "enforce" and (
                self.settings.fail_mode == "closed" or missing.fail_mode == "closed"
            )
            if closed:
                call.verdict = "block"
                call.effective = "block"
            source = (
                "fail_mode=closed"
                if self.settings.fail_mode == "closed"
                else f"policy {missing.key} declares fail_mode={missing.fail_mode}"
            )
            rules_fired.append(
                _fired_rule(
                    "policy.unloadable",
                    "block" if closed else "allow",
                    f"policy {missing.key} v{missing.version} is bound "
                    f"({missing.binding_mode}) but no longer loads, and {source}: "
                    f"{missing.detail[:200]}",
                    severity="high",
                    controls=["NOM-RTG-06"],
                )
            )

    def _apply_ladders(self, call: _Evaluation) -> None:
        """Each business ladder's band joins the verdicts; security still dominates."""
        # The ladder outcome joins here rather than in the rule list, so that its
        # `verify` and `allow` outcomes cannot be swept into the lattice maximum and
        # silently promoted or ignored. Security dominates the combination, so a band
        # that says auto-approve can never loosen a rule that says block.
        #
        # Each ladder's own `mode` decides whether its outcome is applied, not the
        # policy packs' mode: otherwise an observe ladder would escalate as soon as
        # an enforcing pack governed the call, and an enforce ladder would only be
        # recorded when nothing else enforced. Every ladder raises the effective
        # verdict (what enforcement would do); only enforcing ladders raise the
        # applied one.
        for decision in call.ladder_decisions:
            if decision.outcome == "allow":
                continue
            call.effective = combine_business(call.effective, decision).verdict
            if decision.mode == "enforce":
                call.verdict = combine_business(call.verdict, decision).verdict
            call.rules_fired.append(
                _fired_rule(
                    f"business.{decision.ladder_key}",
                    decision.outcome,
                    decision.reason,
                    severity="medium",
                    controls=["NOM-GOV-07"],
                    evidence=decision.to_json(),
                    mode=decision.mode,
                )
            )

    def _apply_forced_rules(self, call: _Evaluation) -> None:
        """Rules the calling surface decided before `evaluate`, by lattice maximum."""
        for forced in call.forced_rules or []:
            rank = _RANK.get(str(forced.get("effect")))
            if rank is not None:
                if rank > _RANK.get(call.verdict, 0):
                    call.verdict = str(forced["effect"])
                if rank > _RANK.get(call.effective, 0):
                    call.effective = str(forced["effect"])
            call.rules_fired.append(forced)
        if call.extra_taint:
            call.taint_summary.update(call.extra_taint)

    def _redeem_approval(self, call: _Evaluation) -> None:
        """A retry presenting a person's approval releases exactly the call they approved."""
        # --- a retry presenting an approval ---------------------------
        # Placed after every rule has had its say, so an approval can only release
        # what was held for a person: a block stays a block.
        call.held = (
            held_call(
                surface=call.surface,
                tool_key=call.tool_key,
                arguments=call.arguments,
                content=call.content,
                detections=call.pipeline_result.detections,
            )
            if call.effective == "escalate"
            else (call.tool_key, call.arguments or {})
        )
        approval_id = call.approval_id
        if approval_id and call.effective == "escalate" and call.persist:
            redeemed, refusal = redeem_approval(
                self.session,
                approval_id,
                agent_id=call.agent.id if call.agent else None,
                tool_key=call.held[0],
                arguments=call.held[1],
            )
            call.redeemed_approval = redeemed
            call.taint_summary["approval"] = {
                "id": approval_id,
                "redeemed": redeemed is not None,
                **({"refused": refusal} if refusal else {}),
            }
            if redeemed is not None:
                call.verdict = "allow"
                call.effective = "allow"
                call.rules_fired.append(
                    _fired_rule(
                        "approval.redeemed",
                        "allow",
                        f"approved by a person ({approval_id}); this call is the one they approved",
                        severity="low",
                        controls=["NOM-IAM-03"],
                    )
                )

    def _build_result(self, call: _Evaluation) -> EnforcementResult:
        """The result the caller gets: verdicts, reason, explanation, redacted content."""
        rules_fired, pipeline_result = call.rules_fired, call.pipeline_result
        call.latency_ms = (time.perf_counter() - call.started) * 1000
        reason = "; ".join(r.get("reason", "") for r in rules_fired if r.get("reason")) or (
            "no policy rule matched"
        )
        if call.approval_id and call.redeemed_approval is None and call.effective == "escalate":
            refused = (call.taint_summary.get("approval") or {}).get("refused")
            if refused:
                reason = f"{reason}; the approval presented was not used: {refused}"
        call.reason = reason

        result = EnforcementResult(
            verdict=call.verdict,
            effective_verdict=call.effective,
            mode=call.mode,
            trace_id=call.trace_id,
            policy_version_id=call.policy_version_id,
            rules_fired=rules_fired,
            entities=sorted({d["entity_type"] for d in call.detections}),
            taint=call.taint_summary,
            latency_ms=call.latency_ms,
            degraded=pipeline_result.degraded,
            reason=reason,
            suppressed=call.suppressed,
            latency_budget=call.ledger.report(),
        )
        result.explanation = explain(
            result,
            pipeline_result,
            content=call.content,
            surface=call.surface,
        ).to_json()

        # --- redaction (applied to the content, not just recorded) -------
        if call.effective in ("redact", "mask", "tokenize") and pipeline_result.detections:
            style = next(
                (
                    r.get("redaction", "mask")
                    for r in rules_fired
                    if r.get("effect") in ("redact", "mask", "tokenize")
                ),
                "mask",
            )
            result.content = redact_content(
                call.content,
                [
                    d
                    for d in pipeline_result.detections
                    if d.entity_type.startswith(("PII", "SECRET"))
                ],
                mode="tokenize" if style == "tokenize" else "mask",
            )
        return result

    def _persist_decision(self, call: _Evaluation, result: EnforcementResult) -> None:
        """Record the decision, its findings, any approval request, the span, the audit entry."""
        agent, surface, trace_id = call.agent, call.surface, call.trace_id
        verdict, effective, rules_fired = call.verdict, call.effective, call.rules_fired
        # --- 9. persist decision, findings, audit ------------------------
        decision_row = Decision(
            trace_id=trace_id,
            agent_id=agent.id if agent else None,
            identity_id=call.identity.id if call.identity else None,
            surface=surface,
            tool_key=call.tool_key,
            verdict=verdict,
            rules_fired_json=rules_fired,
            policy_version_id=call.policy_version_id,
            policy_version_ids=call.policy_version_ids,
            detector_run_ids=call.detector_run_ids,
            taint_summary_json=call.taint_summary,
            latency_ms=call.latency_ms,
            mode=call.mode,
        )
        self.session.add(decision_row)
        self.session.flush()
        result.decision_id = decision_row.id
        # The trace's own verdict is the strongest thing that happened on it.
        #
        # `Trace.verdict` defaults to "allow", and `end_trace` is called from the
        # completion path alone — preflight, _finish_completion,
        # run_completion_stream. Nothing on the tool-call path calls it, so without
        # this a trace whose tool call was blocked or escalated would read `allow`.
        # That is the worst direction for the error to run in: tool containment is
        # the control that is supposed to hold after a content filter has been
        # fooled.
        #
        # Raised here rather than in `guard_tool_call` because every surface lands
        # on this line — tool_args, memory_write, agent_message and the completion
        # surfaces alike — and raise-only because one trace can carry many
        # decisions: a blocked call followed by three allowed ones is a blocked
        # trace, and last-write-wins would erase it.
        self._raise_trace_verdict(call.trace, verdict)
        # The explanation is built before persistence so the non-persisting
        # path still gets one, which leaves the dispute payload to be completed here —
        # a "file a false positive" link with no decision id is not a route anywhere.
        if result.explanation.get("dispute"):
            result.explanation["dispute"]["payload"]["decision_id"] = decision_row.id
            result.explanation["decision_id"] = decision_row.id

        self._raise_decision_findings(call, decision_row)
        self._file_approval_request(call, decision_row, result)

        if trace_id:
            add_span(
                self.session,
                trace_id,
                kind="guardrail",
                name=f"guard.{surface}",
                attributes={
                    ATTR_AGENT: call.agent_slug,
                    ATTR_VERDICT: verdict,
                    ATTR_TAINT: call.taint_summary.get("max_source"),
                    ATTR_TOOL_NAME: call.tool_key,
                    ATTR_TOOL_IMPACT: call.tool_impact,
                    "agentfox.entities": result.entities,
                    "agentfox.rules": [r.get("rule_id") for r in rules_fired],
                    "agentfox.detectors": [r.detector_key for r in call.pipeline_result.results],
                },
                duration_ms=call.latency_ms,
            )

        self._record_degradation(agent, surface, call.pipeline_result)

        chain.append(
            self.session,
            f"decision.{verdict}",
            actor_type="agent",
            actor_id=call.agent_slug,
            subject_type="decision",
            subject_id=decision_row.id,
            payload={
                "surface": surface,
                "tool": call.tool_key,
                "verdict": verdict,
                "effective_verdict": effective,
                "mode": call.mode,
                "policy_version_id": call.policy_version_id,
                "rules_fired": rules_fired,
                "entities": result.entities,
                "taint": call.taint_summary.get("max_source"),
                "latency_ms": round(call.latency_ms, 2),
                "trace_id": trace_id,
            },
        )

    def _raise_decision_findings(self, call: _Evaluation, decision_row: Decision) -> None:
        """A detection finding when a detector changed the outcome; containment findings."""
        agent, surface, rules_fired = call.agent, call.surface, call.rules_fired
        pipeline_result = call.pipeline_result
        # A detector catch is invisible outside the trace it happened on unless it
        # actually changed the outcome — surfacing every allowed pass here would
        # flood the queue with routine catches nobody needs to act on. When it
        # *did* change the outcome, an operator reviewing findings gets nothing to
        # go on today but the entity type: `Detection.sample` is already redacted
        # at construction, so there is no reason to withhold it a second
        # time behind a blanket "we don't store this" — showing the masked excerpt
        # is strictly more useful than a bare category name, and no less safe.
        #
        # Only the detector rules count here. The decision's verdict is the maximum
        # over every rule, so on a call a capability or taint rule refused, a PII
        # rule that merely fired alongside it was titled as the cause — "Blocked on
        # tool_args: PII.EMAIL" for an exfiltration attempt default-deny stopped.
        # What the caller does with the verdict (auto() in observe mode, a dry run)
        # decides whether anything was actually stopped. Recorded on the decision so
        # the report reads the same answer the findings below are titled with.
        scope = getattr(self, "_containment_scope", ("enforced", frozenset()))
        if surface == "tool_args" and scope != ("enforced", frozenset()):
            decision_row.taint_summary_json = {
                **(decision_row.taint_summary_json or {}),
                "in_process": scope[0],
                "exempt_rules": sorted(scope[1]),
            }

        det_effective, det_applied = detector_verdict(rules_fired)
        if surface == "tool_args" and scope[0] == "none":
            det_applied = "allow"  # recorded, and the call ran
        if det_effective != "allow" and pipeline_result.detections:
            self._raise_detection_finding(
                agent=agent,
                trace_id=call.trace_id,
                decision_id=decision_row.id,
                surface=surface,
                effective=det_effective,
                applied=det_applied,
                reason=call.reason,
                rules_fired=[r for r in rules_fired if is_detector_rule(r)],
                detections=[
                    d
                    for d in pipeline_result.detections
                    if matches_detector_rule(d.entity_type, rules_fired)
                ],
            )

        # And the rules that are not detectors get findings of their own, titled by
        # what they are: the agent, the tool, and the actual reason it was stopped.
        if surface == "tool_args" and call.effective != "allow":
            raise_containment_findings(
                self.session,
                agent=agent,
                tool_key=call.tool_key,
                surface=surface,
                rules_fired=rules_fired,
                argument_taint=call.argument_taint,
                argument_propagated_from=call.argument_propagated_from,
                trace_id=call.trace_id,
                decision_id=decision_row.id,
                decision_verdict=call.verdict,
                scope=scope,
            )

    def _file_approval_request(
        self, call: _Evaluation, decision_row: Decision, result: EnforcementResult
    ) -> None:
        """An escalated call files an approval request; a redeemed one links its approval."""
        # --- 6. escalation ----------------------------------------
        if call.effective == "escalate":
            # Filed under what the approver needs to see: the tool and arguments, or
            # for a held message its (masked) content and the digest a retry is
            # matched against.
            approval = request_approval(
                self.session,
                agent_id=call.agent.id if call.agent else None,
                tool_key=call.held[0],
                arguments=call.held[1],
                reason=call.reason,
                trace_id=call.trace_id,
                decision_id=decision_row.id,
            )
            decision_row.approval_id = approval.id
            result.approval_id = approval.id
        elif call.redeemed_approval is not None:
            decision_row.approval_id = call.redeemed_approval.id

    def _raise_trace_verdict(self, trace: Trace | None, verdict: str) -> None:
        """Raise a trace's verdict to `verdict`, never lower it.

        A trace is one request and can carry many decisions. Its verdict answers
        "what is the strongest thing that happened here" — so a blocked call
        followed by three allowed ones leaves the trace blocked, and an allowed
        call can never quietly clear an earlier block.

        `status` moves with it, using the same two words `end_trace` uses, so a
        trace ended by the completion path and one only ever written here agree
        on their vocabulary.

        Deliberately does NOT set `ended_at`: the caller owns the trace's
        lifetime and may still add to it. A trace that nothing ever ended is a
        real thing worth being able to see, and forging an end time here would
        hide it.
        """
        if trace is None:
            return
        if _RANK.get(verdict, 0) <= _RANK.get(trace.verdict or "allow", 0):
            return
        trace.verdict = verdict
        # Spelled out, not derived: "abstain" + "d" is "abstaind". These are the
        # exact words end_trace writes for the same three outcomes.
        status = {"block": "blocked", "escalate": "escalated", "abstain": "abstained"}.get(verdict)
        if status:
            trace.status = status
        self.session.flush()

    def _severity(self, result: EnforcementResult) -> tuple[int, int]:
        return (_RANK[result.verdict], _RANK[result.effective_verdict])
