"""The enforcement orchestrator — PRD §9.3, the request path.

This is where the six pillars stop being separate modules and become one product.
Every inline surface (gateway proxy, direct guard endpoints, SDK, red-team runner)
goes through this class, which is what makes the guarantees hold uniformly:

    identity resolution (P1-2, P2-1)
      -> taint annotation (P3-4)
      -> budgeted detector pipeline (P3-1/2/3/5, P3-6)
      -> capability check (P2-2)
      -> policy decision (P6-1)
      -> escalation to a human (P2-3)
      -> provider call (X-2)
      -> post-flight on the response (P3-2, P3-9, P4-3)
      -> trace, audit chain, findings (P5-1, P5-2)

Two invariants are enforced here rather than assumed:

* **No block without a reason.** Every verdict carries the rule that produced it and
  a human-readable explanation (principle X-4). A guardrail that blocks silently is
  a bug, not a strict configuration.
* **Observe by default.** Enforcement is something a customer turns on deliberately,
  after simulating it. A tool that starts blocking the moment it is installed gets
  uninstalled the same week (PRD R3).
"""

from __future__ import annotations

import datetime as dt
import json
import functools
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agent_loop import LoopBudget, Step, govern_loop
from .agent_messaging import verify_message
from .answerability import (
    classify_answerability,
    detect_over_refusal,
    get_boundary,
    verify_boundary,
)
from .audit import chain
from .audit.trace import (
    ATTR_AGENT,
    ATTR_REQUEST_MODEL,
    ATTR_SYSTEM,
    ATTR_TAINT,
    ATTR_TOOL_IMPACT,
    ATTR_TOOL_NAME,
    ATTR_VERDICT,
    add_span,
    end_trace,
    start_trace,
)
from .business.graph import BUSINESS_RANK
from .business.graph import combine as combine_business
from .business.ladder import LadderDecision
from .business.ladder import evaluate as evaluate_ladder
from .business.store import load_ladders
from .commitments import adverse_action_risk, check_disclosure, detect_commitments
from .config import get_settings
from .control_flow import Plan
from .control_flow import check_selection as check_tool_selection
from .context_integrity import (
    assemble_context,
    chunk_quality,
    document_quality,
    memory_binding_breach,
    retrieval_drift,
)
from .context_integrity import worst as worst_context_verdict
from .crypto import DecryptionFailed, decrypt_secret
from .entitlement import (
    aggregation_risk,
    filter_retrieval,
    inference_risk,
    record_disclosure,
)
from .data_access import ReferenceTable, ScopeRule
from .data_access import analyse_access as analyse_data_access
from .effects import cascade_risk
from .guardrails import (
    DetectionContext,
    DetectorPipeline,
    TaintTracker,
    redact_content,
)
from .guardrails.actions import analyse_arguments, find_sql_argument
from .guardrails.actions import summarise as summarise_actions
from .guardrails.base import taint_rank
from .guardrails.composition import check_composed_escalation
from .guardrails.taint import _flatten
from .findings import raise_finding, record_detector_health
from .guardrails.tuning import (
    LatencyLedger,
    active_suppressions,
    explain,
    filter_suppressed,
)
from .identity import check_capability, request_approval, verify_credential
from .integrations.correlation import (
    link_trace,
    push_verdict,
    refs_from_env,
    refs_from_headers,
)
from .integrity import assess_integrity
from .sycophancy import check_premises
from .models import (
    AccessScopeRule,
    Agent,
    AgentMessageLog,
    AgentSigningKey,
    Budget,
    Decision,
    DetectionFinding,
    DetectorRun,
    Identity,
    MemoryEntry,
    TaintTag,
    Tool,
    Trace,
    as_aware,
    utcnow,
)
from .policy import EFFECT_RANK, PolicyInput, active_policies, combine, get_engine
from .provenance import assess_provenance
from .providers import CompletionRequest, get_provider
from .register import check_register
from .registry.service import observe_agent, record_edge
from .reliability import (
    BREAKER,
    BudgetVerdict,
    DegradationRecord,
    FallbackLadder,
    ProviderAttempt,
    check_budget,
    raise_budget_finding,
)
from .reliability import Rung as _Rung
from .trajectory import ENTITY as TRAJECTORY_ENTITY
from .trajectory import SCAN_CHARS as TRAJECTORY_SCAN_CHARS
from .trajectory import assess as assess_trajectory


class ProviderUnavailable(RuntimeError):
    """Every provider on the fallback ladder failed or is circuit-open."""


log = logging.getLogger(__name__)

#: F6/F8 post-flight checks are linear in the content they read, and every one of
#: them is a regex or character scan rather than a model call. Measured on this
#: machine: together they cost ~0.7ms on a 1.6KB answer, ~35ms on an 81KB one and
#: ~170ms on 405KB — the last of which would eat most of the 300ms enforcement
#: budget on a single oversized retrieved payload. Capping the scanned prefix bounds
#: the work at ~13ms. A promise or a corruption that appears only after 32KB of text
#: is a case this check honestly does not cover, which is a better failure than a
#: blown budget on the request path.
_SCAN_CHARS = 32_000
_SCAN_CHUNKS = 50
_SCAN_CHUNK_CHARS = 2_000

#: `document_quality` codes meaning the *bytes* are damaged, as opposed to its
#: prose-shape heuristics (`low-text-density`, `lost-word-boundaries`,
#: `hyphenated-line-breaks`). A serialised tool result legitimately trips the shape
#: heuristics — measured: an ordinary 2.2KB JSON payload and a 1.2KB CSV both report
#: `low-text-density` — so only these apply on `tool_result`, where the content is a
#: structure rather than a document. On `retrieved`, where the content really is
#: prose from a corpus, the shape heuristics are the point and all of them run.
_CORRUPTION_CODES = frozenset(
    {"mojibake", "unknown-characters", "control-characters", "empty-extraction"}
)

#: context_integrity's three-value scale onto the `Finding` severity vocabulary.
#: Never `critical`: see `_commitment_checks` on why nothing here self-escalates.
_CONTEXT_SEVERITY = {"warn": "low", "degraded": "medium", "reject": "high"}

#: Verdict severity ordering, shared by every comparison in this module — the same
#: precedence the policy engine itself uses to combine rule effects, not a second
#: copy of it.
_RANK = EFFECT_RANK


class _FallbackVersion:
    """Stands in for a PolicyVersion the fallback does not have.

    `id` is None on purpose. These ids are persisted onto the Decision row as
    the exact set of policy versions in force, which is what makes a decision
    reproducible (X-4). The fallback has no stored version, so inventing an id
    would put a reference to a row that does not exist into the audit record —
    the one place in this product that must not contain a plausible fiction.
    Callers filter it out; a decision made under the fallback records no policy
    version, which is the truth.
    """

    id = None


_FALLBACK_VERSION = _FallbackVersion()


#: Past tense, spelled out. `f"{verdict.capitalize()}ed"` produced "Escalateed"
#: and "Tokenizeed", and there is no rule that turns every one of these into a
#: past participle correctly.
_PAST_TENSE = {
    "block": "Blocked",
    "redact": "Redacted",
    "mask": "Masked",
    "tokenize": "Tokenised",
    "escalate": "Escalated",
    "abstain": "Abstained",
    "allow": "Allowed",
}


def _detection_title(effective: str, applied: str, surface: str, entity_types: list[str]) -> str:
    """What a detection finding is called, and it has to be what HAPPENED.

    This read `f"{effective.capitalize()}ed on {surface}"`, where `effective` is
    what the policy WOULD do rather than what was done. Under an observe-mode
    policy the finding was therefore titled "Blocked on input" for a request
    that was allowed through — a false statement, in the record the product
    exists to keep.

    It matters more now than it did: a deployment with nothing bound falls back
    to the shipped baseline in observe, so an observe-mode finding is the first
    one a new user sees rather than an edge case.

    Same distinction the trace verdict carries: `applied` is what happened,
    `effective` is what the policy asked for, and when they differ the title
    says so rather than picking the more dramatic of the two.
    """
    entities = ", ".join(entity_types)
    if applied == effective:
        return f"{_PAST_TENSE.get(effective, effective.capitalize())} on {surface}: {entities}"
    # Observe: recorded, not acted on. Naming both is what makes the row
    # actionable — it says what would change if this policy were promoted.
    return (
        f"Would have been {_PAST_TENSE.get(effective, effective).lower()} "
        f"on {surface}: {entities}"
    )



#: Which shipped packs apply to a deployment that has configured nothing.
#:
#: Only the default case. Anything an operator binds replaces all of this —
#: `active_policies` is consulted first and the fallback is never reached.
#:
#: `baseline` is unconditional because prompt injection, PII and secrets are not
#: properties of a sector or a jurisdiction; every agent that reads text has
#: them. The rest is chosen from what the operator has ALREADY DECLARED about
#: the agent, never inferred:
#:
#:   risk_tier == "high"  ->  eu-ai-act-high-risk
#:
#: That pack's own header says it is "for agents classified high-risk", so
#: applying it to an agent somebody classified high-risk is responding to their
#: declaration rather than deciding on their behalf. An agent at the default
#: tier gets baseline alone, because silently applying EU AI Act rules to
#: someone who never said they were in scope would be overclaiming.
#:
#: Framework is deliberately NOT a selector. Which content pack is right does
#: not depend on whether the app is built on LangChain or CrewAI — the same
#: injection reaches the same model either way — and a framework-to-policy
#: mapping would be a rule that looks considered and means nothing.
_FALLBACK_FOR_TIER: dict[str, tuple[str, ...]] = {
    "high": ("baseline", "eu-ai-act-high-risk"),
    "unacceptable": ("baseline", "eu-ai-act-high-risk"),
}
_FALLBACK_DEFAULT: tuple[str, ...] = ("baseline",)


@functools.lru_cache(maxsize=8)
def _fallback_policies(risk_tier: str | None = None) -> tuple:
    """The shipped packs for a deployment with nothing bound, forced to observe.

    Cached per tier: this reads YAML off disk and the answer cannot change
    within a process. Cleared by `_fallback_policies.cache_clear()` in tests
    that swap the policies directory.
    """
    from .policy import load_from_dir

    wanted = _FALLBACK_FOR_TIER.get((risk_tier or "").lower(), _FALLBACK_DEFAULT)
    by_key = {}
    try:
        for doc in load_from_dir():
            if doc.key not in wanted:
                continue
            # Every pack ships in observe except tool-containment, which is not
            # a candidate here. Forcing it makes the guarantee independent of
            # anyone editing those files.
            doc.mode = "observe"
            by_key[doc.key] = doc
    except Exception as exc:  # pragma: no cover - a broken install, not a code path
        log.warning("agentfox: could not load the fallback policy: %s", exc)
    # Ordered by `wanted`, so the set in force is deterministic rather than
    # whatever order the directory listing happened to produce.
    return tuple(by_key[k] for k in wanted if k in by_key)



@dataclass
class EnforcementResult:
    verdict: str = "allow"
    effective_verdict: str = "allow"
    mode: str = "observe"
    decision_id: str | None = None
    trace_id: str | None = None
    approval_id: str | None = None
    policy_version_id: str | None = None
    rules_fired: list[dict[str, Any]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    taint: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    degraded: list[str] = field(default_factory=list)
    content: str | None = None  # redacted content, when the verdict is a redaction
    reason: str = ""
    # P3-12/13/14. `explanation` is what an engineer reads instead of "blocked by
    # policy"; `suppressed` records exceptions that fired, because an exception that
    # leaves no trace is a hole rather than a control.
    explanation: dict[str, Any] = field(default_factory=dict)
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    latency_budget: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def escalated(self) -> bool:
        return self.verdict == "escalate"

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "effective_verdict": self.effective_verdict,
            "mode": self.mode,
            "decision_id": self.decision_id,
            "trace_id": self.trace_id,
            "approval_id": self.approval_id,
            "policy_version": self.policy_version_id,
            "rules_fired": self.rules_fired,
            "entities": self.entities,
            "findings": self.findings,
            "taint": self.taint,
            "latency_ms": round(self.latency_ms, 2),
            "degraded": self.degraded,
            "reason": self.reason,
            "explanation": self.explanation,
            "suppressed": self.suppressed,
            "latency_budget": self.latency_budget,
        }


#: Risk codes whose condition a shipped policy pack already has a rule for, mapped to
#: that rule's id. The codes in `effects.py` and `data_access.py` are hyphenated for
#: historical reasons; every rule id in the product is dotted, and a decision that
#: printed both spellings of one rule (`cascade.reaches_destructive` next to
#: `cascade-reaches-destructive`) looked like two findings and read like a bug. The
#: codes themselves are unchanged: `when: action_risk:` in the packs still matches on
#: them, and so does anything reading `taint.action`.
RISK_CODE_RULE_IDS = {
    "cascade-reaches-destructive": "cascade.reaches_destructive",
    "cascade-cycle": "cascade.cycle",
    "cascade-too-deep": "cascade.blast_radius",
    "unscoped-table": "access.unscoped_table",
    "undeclared-table": "access.undeclared_table",
}

#: Every rule id that means "this call was refused at the capability layer". The
#: synthetic fallback below checks the whole set, so a pack that already said it in
#: its own words is not echoed under a second id.
_CAPABILITY_REFUSAL_RULE_IDS = frozenset(
    {"capability.denied", "capability.default_deny", "capability.constraint_violated"}
)


def _fired_rule(
    rule_id: str,
    effect: str,
    reason: str,
    *,
    severity: str | None = None,
    controls: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
    mode: str = "enforce",
) -> dict[str, Any]:
    """One entry in `rules_fired` for a synthetic (non-policy-authored) rule —
    the shape a dozen-plus call sites in this module built by hand. Optional keys
    are omitted rather than set to ``None`` so every call site keeps exactly the
    keys it had before this was factored out.

    ``mode`` says whether *this rule's* effect was applied or only recorded. It
    defaults to ``enforce`` because a synthetic rule is a fact about the call rather
    than a policy opinion: the absence of a grant, a destructive statement, a killed
    agent. Those set the verdict whatever mode the packs are bound in. The two call
    sites that are gated on the decision's mode pass it explicitly.
    """
    rule: dict[str, Any] = {"rule_id": rule_id, "effect": effect, "reason": reason, "mode": mode}
    if severity is not None:
        rule["severity"] = severity
    if controls is not None:
        rule["controls"] = controls
    if evidence is not None:
        rule["evidence"] = evidence
    return rule


@dataclass
class PreflightOutcome:
    """Everything the pre-flight established, shared by the buffered and streaming paths."""

    agent: Agent | None = None
    identity: Identity | None = None
    trace: Trace | None = None
    tracker: TaintTracker | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    result: EnforcementResult = field(default_factory=EnforcementResult)
    stopped: bool = False


@dataclass
class StreamEvent:
    """One event on the enforced stream.

    ``kind`` is one of:
      ``delta``   — content to forward to the caller
      ``blocked`` — enforcement stopped the stream; ``result`` explains why
      ``done``    — the stream completed; ``result`` carries the final verdict
    """

    kind: str = "delta"
    delta: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    result: EnforcementResult | None = None


class Enforcer:
    def __init__(self, session: Session, pipeline: DetectorPipeline | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.pipeline = pipeline or DetectorPipeline()
        self.engine = get_engine()
        # P3-13: one ledger per request, not per call. Reset at the start of each
        # governed completion; a bare `evaluate()` gets a fresh one on demand.
        self._ledger: LatencyLedger | None = None
        # F2/F7: the retrieval set, records and entities the answer was built from.
        # Set by the caller (SDK, LangGraph guard, gateway) before a governed call.
        # Also read by the F6/F8 checks: `channel`/`counterparty` (AI disclosure),
        # `decision` (adverse action), `chunks` (chunk coherence), `principal` and
        # `memory` (memory binding), `retrieval`/`baseline` (retrieval drift).
        self.evidence: dict[str, Any] = {}

    #: F8.4 — context assembly is the caller's step, not ours: it needs the ranked
    #: chunks and the real token budget, and it repairs as well as reports. Exposed
    #: here so whoever performs retrieval can run it (and feed the resulting findings
    #: back through `evidence`) without reaching into `context_integrity` directly.
    assemble_context = staticmethod(assemble_context)

    # ------------------------------------------------------------------
    # Identity & agent resolution
    # ------------------------------------------------------------------

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
        if identity is None:
            identity = self.session.scalar(select(Identity).where(Identity.agent_id == agent.id))
        return agent, identity, is_shadow

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def ledger(self) -> LatencyLedger:
        """The request-level detector budget (P3-13)."""
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
        persist: bool = True,
    ) -> EnforcementResult:
        """One decision on one surface. The single point every guarantee flows through.

        `conversation_window` is the only argument here that is not about *this*
        message: it is the recent user turns, oldest first, ending with this one,
        supplied by `check_conversation_window`. It exists so F9.4's trajectory check
        can run through the same channel as every other check rather than beside it.
        """
        started = time.perf_counter()
        agent_slug = agent.slug if agent else None
        environment = agent.environment if agent else "production"
        trace_id = trace.id if trace else None

        tool = self.session.scalar(select(Tool).where(Tool.key == tool_key)) if tool_key else None
        tool_impact = tool.impact if tool else "read"

        # --- 4. detector pipeline (budgeted, concurrent) -----------------
        context = DetectionContext(
            surface=surface,
            agent_slug=agent_slug,
            trace_id=trace_id,
            tool_key=tool_key,
            tool_impact=tool_impact,
            intent=intent,
            taint_source=taint_source,
            schema=schema,
            prior_tools=prior_tools or [],
        )
        ledger = self.ledger()
        pipeline_result = self.pipeline.run(
            content, context, budget_ms=ledger.allowance_ms(self.pipeline.budget_ms)
        )
        ledger.charge(pipeline_result, surface)

        # P3-14: suppressions are applied here rather than inside the pipeline. A
        # suppression is a governance decision about a detector's output, not a
        # detector concern, and keeping it out of the pipeline means the raw detector
        # result stays honest.
        suppressions = active_suppressions(self.session, agent.id if agent else None)
        suppressed = filter_suppressed(pipeline_result, suppressions, surface=surface)

        detections = [
            {
                "entity_type": d.entity_type,
                "score": d.score,
                "owasp_id": d.owasp_id,
                "atlas_id": d.atlas_id,
            }
            for d in pipeline_result.detections
        ]

        detector_run_ids: list[str] = []
        if persist:
            detector_run_ids = self._persist_detectors(pipeline_result, trace_id, surface)

        # --- capability check (P2-2) -------------------------------------
        capability = {"granted": True, "requires_approval": False, "state": "granted"}
        if tool_key:
            decision = check_capability(
                self.session,
                identity,
                tool_key,
                arguments=arguments or {},
                argument_taint=argument_taint or {},
            )
            capability = decision.to_json()

        # --- P8/F7 evidence integrity (output surface only) ----------------
        # Groundedness asks whether the claim is supported by the text. It does not
        # ask whether the text was authoritative (F2), nor whether 5 + 3 = 9 (F7).
        # Both are properties of the answer's relationship to its evidence, so they
        # run here, where the evidence is in hand.
        evidence = self._evidence_checks(agent, surface, content, intent)
        disclosure = self._disclosure_checks(agent, surface, content, trace_id)
        if disclosure:
            merged_issues = [
                *evidence.get("evidence_issues", []),
                *disclosure.pop("evidence_issues", []),
            ]
            evidence.update(disclosure)
            if merged_issues:
                evidence["evidence_issues"] = merged_issues

        # --- F6 commitments / F8 context integrity ------------------------
        # Same channel as the two checks above, deliberately: one `evidence` dict that
        # lands in `taint_summary`, one `evidence_issues` list that becomes `Finding`
        # rows, one `rules_fired`. The only thing these add is `risks`, which join
        # `action["risks"]` below — the list the policy engine's `action_risk` condition
        # already reasons over, so a policy author can act on them without a schema
        # change. Nothing here sets a verdict on its own.
        pending_risks: list[dict[str, Any]] = []
        for extra in (
            self._commitment_checks(agent, surface, content, intent),
            self._context_checks(surface, content, memory_entry),
            self._control_flow_checks(surface, tool_key),
            self._sycophancy_checks(surface, content, intent),
            self._trajectory_checks(surface, conversation_window),
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

        # --- Business ladders ---------------------------------------------
        # Evaluated separately from policy and combined afterwards, because the two
        # compose by different algebras: rules take the lattice maximum, ladders select
        # exactly one band. Security dominates the combination, so a band that says
        # auto-approve can never loosen a rule that says block.
        ladder_decision = self._business_ladders(agent, surface, tool_key, arguments)

        # --- P9 action assurance ------------------------------------------
        # Argument-level containment governs *the call*; this governs *the artefact*.
        # An agent holding a legitimate `db.query` capability can pass `DROP TABLE` as
        # a well-formed string, and every argument check would pass it.
        action = (
            summarise_actions(
                analyse_arguments(arguments or {}, dialect=self.settings.sql_dialect),
                environment,
            )
            if arguments
            else {}
        )

        # --- P9 cascade risk / P18 data-access scoping, when declared ------
        # Same block as the action-assurance check above, extending the same
        # `action["risks"]`/`action["critical"]` the policy engine already reasons
        # over (`policy/engine.py`'s `action_risk` glob condition) — no policy-layer
        # change needed for either check to actually start firing.
        extras = self._cascade_and_access_risks(tool_key, arguments)
        if extras:
            extra_risks = extras.pop("risks", [])
            action.update(extras)
            if extra_risks:
                action["risks"] = [*action.get("risks", []), *extra_risks]
                action["critical"] = [r for r in action["risks"] if r["severity"] == "critical"]

        # F6/F8 risks reach the policy engine exactly as the P9/P18 ones above do, and
        # deliberately never join `action["critical"]` — that list is hard-blocked a few
        # lines below, which is the one thing these checks must not do. They are capped
        # at `high` at the point of construction so this stays true even if a detector
        # raises its own severity later.
        if pending_risks:
            action["risks"] = [*action.get("risks", []), *pending_risks]

        # --- budgets & loop containment (P3-10, PL-4) ---------------------
        budget = self._budget_state(
            agent, trace, tool_key, prior_tools or [], prior_steps, arguments
        )

        taint_summary = tracker.summary() if tracker else {"max_source": taint_source}
        taint_summary = {
            **taint_summary,
            "arguments": argument_taint or {},
            "tool_impact": tool_impact,
            "risk_tier": agent.risk_tier if agent else "limited",
            "capability": capability,
            "budget": budget,
            "detections": detections,
            "prior_tools": prior_tools or [],
            "detector_degraded": bool(pipeline_result.degraded),
            "arguments_snapshot": arguments or {},
            "action": action,
            "business": ladder_decision.to_json() if ladder_decision else {},
            **evidence,
        }

        # --- 5. policy decision (P6-1) -----------------------------------
        pinput = PolicyInput(
            agent_slug=agent_slug,
            risk_tier=agent.risk_tier if agent else "limited",
            environment=environment,
            surface=surface,
            tool_key=tool_key,
            tool_impact=tool_impact,
            arguments=arguments or {},
            intent=intent,
            detections=detections,
            taint=taint_summary,
            capability=capability,
            budget=budget,
            prior_tools=prior_tools or [],
            detector_degraded=bool(pipeline_result.degraded),
            action=action,
        )

        bound = active_policies(self.session, agent_slug, environment)
        # Nothing bound is not the same as nothing to check.
        #
        # A database that has never been initialised holds no policies, so every
        # content rule was skipped and `auto()` governed exactly nothing while
        # announcing a mode. Adding one line to an existing application is the
        # integration this product leads with, and it produced a no-op.
        #
        # So the shipped baseline applies as a fallback. Deliberately OBSERVE
        # only, and deliberately only `baseline`:
        #
        #   - Observe because silently blocking traffic in an application whose
        #     owner configured nothing is how governance gets ripped out — the
        #     exact failure L8.8 exists to measure. Detections are recorded, so
        #     the findings and traces are real and the banner stops lying, and
        #     nothing is refused that would not have been refused anyway.
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
        used_fallback = False
        if not bound:
            fallback = _fallback_policies(getattr(agent, "risk_tier", None))
            if fallback:
                bound = [
                    (doc, _FALLBACK_VERSION, None)
                    for doc in fallback
                    if doc.matches_scope(agent_slug, environment)
                ]
                used_fallback = bool(bound)
        evaluated = [
            (doc, version, self.engine.evaluate(doc, pinput)) for doc, version, _b in bound
        ]
        merged = combine([d for _doc, _v, d in evaluated]) if evaluated else None

        # X-4: a decision is only reproducible if the *whole* set of versions in force
        # is recorded, not just the one that happened to win.
        # None is filtered, not stored: see _FallbackVersion. A decision made
        # under the fallback records no policy version, because there is none.
        policy_version_ids = [
            version.id for _doc, version, _d in evaluated if version.id is not None
        ]
        policy_version_id = next(
            (
                version.id
                for doc, version, _d in evaluated
                if merged and merged.policy_key == doc.key
            ),
            policy_version_ids[0] if policy_version_ids else None,
        )

        verdict = merged.verdict if merged else "allow"
        effective = merged.effective_verdict if merged else "allow"
        mode = merged.mode if merged else self.settings.default_policy_mode
        rules_fired = [r.to_json() for r in merged.rules_fired] if merged else []

        # A capability denial is not a policy opinion — it is the absence of a grant,
        # and it stands whether or not a policy happened to cover the case. The
        # synthetic rule is only added when no policy already said the same thing,
        # so a customer who wrote the rule explicitly does not see it twice.
        fired_ids = {r.get("rule_id") for r in rules_fired}
        if not capability.get("granted", True):
            verdict = "block"
            effective = "block"
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
        elif capability.get("requires_approval") and effective != "block":
            effective = "escalate"
            if mode == "enforce":
                verdict = "escalate"
            if "capability.approval_required" not in fired_ids:
                rules_fired.append(
                    _fired_rule(
                        "capability.requires_approval",
                        "escalate",
                        "; ".join(capability.get("reasons") or ["approval required"]),
                        severity="medium",
                        controls=["NOM-IAM-03"],
                        mode=mode,
                    )
                )

        # F2/F7: an unauthoritative or arithmetically wrong answer is a finding, not
        # a block. Blocking here would withhold a mostly-correct answer over a
        # currency mismatch, and the failure this addresses is *silent* wrongness —
        # surfacing it is the control.
        for issue in evidence.get("evidence_issues", []):
            raise_finding(
                self.session,
                type=issue["type"],
                severity=issue.get("severity", "medium"),
                title=issue["title"],
                subject_type="agent",
                subject_id=agent.id if agent else None,
                evidence={**issue, "trace_id": trace_id},
                # F2/F7 evidence issues evidence NOM-RTG-12; the F6/F8 issues that
                # now flow through this same loop evidence different controls and
                # say so, rather than being filed under a control they do not
                # support.
                control_keys=issue.get("control_keys") or ["NOM-RTG-12"],
                # One finding per (agent, issue type, issue code, surface): the same
                # integrity failure on every answer is one problem with a count.
                fingerprint_parts=(issue.get("code"), surface),
            )

        # P9: a critical action risk stands on its own, exactly as a capability denial
        # does. It is a fact about what the statement will do, not a policy opinion —
        # and a customer who wrote the rule explicitly does not see it twice.
        for risk in action.get("critical", []):
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
            verdict = "block"
            effective = "block"
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

        # P9-11/F3.8: a read tool's output flowing into a higher-impact tool's
        # argument is a composed escalation neither tool's own scope permits
        # alone — a fact about this call's inputs, not a policy opinion, so it
        # stands on its own exactly like the critical-action-risk check above.
        composition_findings = (
            check_composed_escalation(
                consuming_tool_key=tool_key,
                consuming_tool_impact=tool_impact,
                argument_propagated_from=argument_propagated_from or {},
                tool_impact_lookup=lambda key: self.session.scalar(
                    select(Tool.impact).where(Tool.key == key)
                ),
            )
            if tool_key
            else []
        )
        taint_summary["composition"] = [f.to_json() for f in composition_findings]
        for finding in composition_findings:
            rule_id = f"composition.escalation.{finding.argument_path}"
            if rule_id in fired_ids:
                continue
            verdict = "block"
            effective = "block"
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

        # P3-7: a degraded pipeline means reduced coverage. Fail-closed converts that
        # into a block; fail-open accepts it and records the gap.
        if pipeline_result.degraded and self.settings.fail_mode == "closed" and mode == "enforce":
            verdict = "block"
            effective = "block"
            rules_fired.append(
                _fired_rule(
                    "pipeline.fail_closed",
                    "block",
                    f"detectors degraded ({pipeline_result.degraded}) and fail_mode=closed",
                    severity="medium",
                    controls=["NOM-RTG-06"],
                )
            )

        # The ladder outcome joins here rather than in the rule list, so that its
        # `verify` and `allow` outcomes cannot be swept into the lattice maximum and
        # silently promoted or ignored.
        if ladder_decision is not None and ladder_decision.outcome != "allow":
            combined = combine_business(effective, ladder_decision)
            if combined.verdict != effective:
                effective = combined.verdict
                if mode == "enforce":
                    verdict = combined.verdict
            rules_fired.append(
                _fired_rule(
                    f"business.{ladder_decision.ladder_key}",
                    ladder_decision.outcome,
                    ladder_decision.reason,
                    severity="medium",
                    controls=["NOM-GOV-07"],
                    evidence=ladder_decision.to_json(),
                    mode=mode,
                )
            )

        latency_ms = (time.perf_counter() - started) * 1000
        reason = "; ".join(r.get("reason", "") for r in rules_fired if r.get("reason")) or (
            "no policy rule matched"
        )

        result = EnforcementResult(
            verdict=verdict,
            effective_verdict=effective,
            mode=mode,
            trace_id=trace_id,
            policy_version_id=policy_version_id,
            rules_fired=rules_fired,
            entities=sorted({d["entity_type"] for d in detections}),
            taint=taint_summary,
            latency_ms=latency_ms,
            degraded=pipeline_result.degraded,
            reason=reason,
            suppressed=suppressed,
            latency_budget=ledger.report(),
        )
        result.explanation = explain(
            result,
            pipeline_result,
            content=content,
            surface=surface,
        ).to_json()

        # --- redaction (applied to the content, not just recorded) -------
        if effective in ("redact", "mask", "tokenize") and pipeline_result.detections:
            style = next(
                (
                    r.get("redaction", "mask")
                    for r in rules_fired
                    if r.get("effect") in ("redact", "mask", "tokenize")
                ),
                "mask",
            )
            result.content = redact_content(
                content,
                [
                    d
                    for d in pipeline_result.detections
                    if d.entity_type.startswith(("PII", "SECRET"))
                ],
                mode="tokenize" if style == "tokenize" else "mask",
            )

        if not persist:
            return result

        # --- 9. persist decision, findings, audit ------------------------
        decision_row = Decision(
            trace_id=trace_id,
            agent_id=agent.id if agent else None,
            identity_id=identity.id if identity else None,
            surface=surface,
            tool_key=tool_key,
            verdict=verdict,
            rules_fired_json=rules_fired,
            policy_version_id=policy_version_id,
            policy_version_ids=policy_version_ids,
            detector_run_ids=detector_run_ids,
            taint_summary_json=taint_summary,
            latency_ms=latency_ms,
            mode=mode,
        )
        self.session.add(decision_row)
        self.session.flush()
        result.decision_id = decision_row.id
        # The trace's own verdict is the strongest thing that happened on it.
        #
        # `Trace.verdict` defaults to "allow" and was only ever written by
        # `end_trace`, which is called from the completion path alone — preflight,
        # _finish_completion, run_completion_stream. Nothing on the tool-call path
        # calls it, so a trace whose tool call was blocked or escalated sat in the
        # database, and in the Traces list, reading `allow`.
        #
        # That is the worst direction for this error to run in: tool containment is
        # the control that is supposed to hold after a content filter has been
        # fooled, and every trace it acted on reported that nothing happened.
        #
        # Raised here rather than in `guard_tool_call` because every surface lands
        # on this line — tool_args, memory_write, agent_message and the completion
        # surfaces alike — and raise-only because one trace can carry many
        # decisions: a blocked call followed by three allowed ones is a blocked
        # trace, and last-write-wins would erase it.
        self._raise_trace_verdict(trace, verdict)
        # P3-12: the explanation is built before persistence so the non-persisting
        # path still gets one, which leaves the dispute payload to be completed here —
        # a "file a false positive" link with no decision id is not a route anywhere.
        if result.explanation.get("dispute"):
            result.explanation["dispute"]["payload"]["decision_id"] = decision_row.id
            result.explanation["decision_id"] = decision_row.id

        # A detector catch is invisible outside the trace it happened on unless it
        # actually changed the outcome — surfacing every allowed pass here would
        # flood the queue with routine catches nobody needs to act on. When it
        # *did* change the outcome, an operator reviewing findings gets nothing to
        # go on today but the entity type: `Detection.sample` is already redacted
        # at construction (P5-5), so there is no reason to withhold it a second
        # time behind a blanket "we don't store this" — showing the masked excerpt
        # is strictly more useful than a bare category name, and no less safe.
        if effective != "allow" and pipeline_result.detections:
            self._raise_detection_finding(
                agent=agent,
                trace_id=trace_id,
                decision_id=decision_row.id,
                surface=surface,
                effective=effective,
                applied=verdict,
                reason=reason,
                rules_fired=rules_fired,
                detections=pipeline_result.detections,
            )

        # --- 6. escalation (P2-3) ----------------------------------------
        if effective == "escalate":
            approval = request_approval(
                self.session,
                agent_id=agent.id if agent else None,
                tool_key=tool_key,
                arguments=arguments or {},
                reason=reason,
                trace_id=trace_id,
                decision_id=decision_row.id,
            )
            decision_row.approval_id = approval.id
            result.approval_id = approval.id

        if trace_id:
            add_span(
                self.session,
                trace_id,
                kind="guardrail",
                name=f"guard.{surface}",
                attributes={
                    ATTR_AGENT: agent_slug,
                    ATTR_VERDICT: verdict,
                    ATTR_TAINT: taint_summary.get("max_source"),
                    ATTR_TOOL_NAME: tool_key,
                    ATTR_TOOL_IMPACT: tool_impact,
                    "agentfox.entities": result.entities,
                    "agentfox.rules": [r.get("rule_id") for r in rules_fired],
                    "agentfox.detectors": [r.detector_key for r in pipeline_result.results],
                },
                duration_ms=latency_ms,
            )

        self._record_degradation(agent, surface, pipeline_result)

        chain.append(
            self.session,
            f"decision.{verdict}",
            actor_type="agent",
            actor_id=agent_slug,
            subject_type="decision",
            subject_id=decision_row.id,
            payload={
                "surface": surface,
                "tool": tool_key,
                "verdict": verdict,
                "effective_verdict": effective,
                "mode": mode,
                "policy_version_id": policy_version_id,
                "rules_fired": rules_fired,
                "entities": result.entities,
                "taint": taint_summary.get("max_source"),
                "latency_ms": round(latency_ms, 2),
                "trace_id": trace_id,
            },
        )
        return result

    # ------------------------------------------------------------------
    # Convenience surfaces
    # ------------------------------------------------------------------

    def check_content(
        self,
        agent_slug: str,
        content: str,
        surface: str = "input",
        taint_source: str = "user",
        persist: bool = True,
    ) -> dict[str, Any]:
        """Light single-surface check. Used by the red-team runner."""
        agent = self.session.scalar(select(Agent).where(Agent.slug == agent_slug))
        identity = (
            self.session.scalar(select(Identity).where(Identity.agent_id == agent.id))
            if agent
            else None
        )
        tracker = TaintTracker()
        tracker.mark("$.content", taint_source, content)
        result = self.evaluate(
            agent=agent,
            identity=identity,
            content=content,
            surface=surface,
            taint_source=taint_source,
            tracker=tracker,
            persist=persist,
        )
        return result.to_json()

    def guard_tool_call(
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
    ) -> EnforcementResult:
        """Authorise a tool call on the full execution path (P3-4, P2-2, P9)."""
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
        marks = tracker.taint_arguments(arguments, provenance)
        argument_taint = {path: mark.source for path, mark in marks.items()}
        # F3.8: which arguments were inferred (not caller-declared) from an
        # earlier tool's result, and which tool that was — see composition.py.
        argument_propagated_from = {
            path: mark.propagated_from for path, mark in marks.items() if mark.propagated_from
        }

        if trace:
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
        if agent is not None:
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

    def check_conversation_window(
        self,
        *,
        agent_slug: str,
        session_id: str,
        new_user_text: str,
        window: int = 6,
        trace: Trace | None = None,
    ) -> EnforcementResult:
        """Tier A — payload-splitting / multi-turn jailbreak defense.

        Every other detection path in this file evaluates one message (`evaluate`)
        or one tool call (`guard_tool_call`) in isolation. That is a real, named gap:
        an attacker can split a payload across several turns — each individually
        innocuous — that only reads as an attack once assembled ("payload
        splitting", OWASP LLM01; see also Microsoft's "Crescendo" multi-turn
        jailbreak, arXiv:2404.01833, which escalates gradually rather than splitting
        a single payload but defeats per-message evaluation the same way). Found by
        actually checking: neither `autoguard.py`'s `_govern` (joins one call's own
        `messages` array, but never a previous *separate* call) nor the gateway's
        `preflight` (loops per-message, never joins) re-evaluates content against
        conversation history.

        This closes it using the substrate that already exists for a different
        reason — `ConversationTurn`, written by escalation governance (P11) — by
        joining the last `window` turns' `user_text` with the new message and
        running the same detector pipeline over the assembled text. Requires the
        caller to supply a stable `session_id` across turns (the same requirement
        `record_turn` already has); without one, this degrades to evaluating the
        new message alone, harmlessly.

        **Two different multi-turn attacks are checked here, by two different
        mechanisms.** Joining is the right answer to payload splitting and the wrong
        answer to a crescendo, and `benchmarks/crescendo/` measured the difference
        rather than assuming it: 0 of 13 gradual-escalation conversations were caught
        at any turn index, because joining six innocuous turns produces six innocuous
        turns and there is no hidden string to reassemble. So the same window is also
        handed to the trajectory scorer (F9.4, `trajectory.py`) as a *sequence* rather
        than a join, which measures the slope of a risk-adjacent score instead of the
        content of the concatenation. The joined-text verdict is what this method
        returns; the trajectory finding rides along on `result.taint["trajectory"]`
        and on the `action["risks"]` channel, observe-first — see `_trajectory_checks`.
        """
        from .models import ConversationTurn

        agent, identity, _ = self.resolve(agent_slug)
        prior = list(
            reversed(
                self.session.scalars(
                    select(ConversationTurn)
                    .where(ConversationTurn.session_id == session_id)
                    .order_by(ConversationTurn.turn_index.desc())
                    .limit(window)
                ).all()
            )
        )
        texts = [t.user_text for t in prior if t.user_text] + [new_user_text]
        joined = "\n".join(texts)
        return self.evaluate(
            agent=agent,
            identity=identity,
            content=joined,
            surface="input",
            trace=trace,
            conversation_window=texts,
        )

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

    # ------------------------------------------------------------------
    # Memory write governance (P14, NOM-RTG-13) — closes OWASP ASI06
    # ------------------------------------------------------------------

    def guard_memory_write(
        self,
        *,
        agent_slug: str,
        content: str,
        subject: str | None = None,
        taint_source: str = "user",
        provenance: dict[str, Any] | None = None,
        verified_by: str | None = None,
        ttl_seconds: int | None = None,
        trace: Trace | None = None,
        credential: str | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Authorise a write into an agent's long-term memory before it commits.

        A write into a vector store, a `mem0`-style store, or a LangGraph
        checkpointer is governed the same way a tool call is — the detector
        pipeline runs on the way *in*, not only at retrieval time, so a poisoned
        entry that would be blocked on the way out never gets the chance to
        persist on the way in.

        Provenance is carried on the entry itself so a later retrieval can weight
        or refuse it the way P8 already weights a source tier. An entry nobody
        has verified (``verified_by=None``) defaults **closed**: it decays after
        ``ttl_seconds`` (default: ``settings.memory_unverified_ttl_seconds``)
        rather than persisting indefinitely — the opposite default from
        :class:`Suppression`, deliberately, because an unconfirmed memory has not
        earned the benefit of the doubt a human-authored suppression has.
        """
        agent, identity, _ = self.resolve(agent_slug, credential)
        result = self.evaluate(
            agent=agent,
            identity=identity,
            content=content,
            surface="memory_write",
            trace=trace,
            taint_source=taint_source,
            # F8.5: the entry about to be written, checked against the principal the
            # caller declared in `evidence`. An entry with no subject is the dangerous
            # case rather than the safe one — it was written by someone, about someone,
            # and nothing records who.
            memory_entry={
                "key": str((provenance or {}).get("key") or ""),
                "subject": subject,
                "session": (provenance or {}).get("session"),
                "durable": verified_by is not None,
            },
            persist=persist,
        )
        # Mode-aware, like every other surface (R3: nothing blocks until a
        # policy is promoted to enforce) — `result.verdict`, not the
        # `effective_verdict` counterfactual, is what actually gates the
        # write. Once enforced, a blocked or escalated write does not get to
        # persist at all: that is the entire point of governing the write
        # path rather than only the read path. tokenize/mask/redact still
        # persist, but the *redacted* content (`result.content` is only set
        # when the verdict rewrote it), matching every other surface.
        if persist and result.verdict not in ("block", "escalate", "abstain"):
            expires_at = None
            if verified_by is None:
                ttl = ttl_seconds if ttl_seconds is not None else self.settings.memory_unverified_ttl_seconds
                expires_at = utcnow() + dt.timedelta(seconds=ttl)
            entry = MemoryEntry(
                agent_id=agent.id if agent else None,
                subject=subject,
                content=result.content if result.content is not None else content,
                taint_source=taint_source,
                provenance=provenance or {},
                decision_id=result.decision_id,
                verified_by=verified_by,
                expires_at=expires_at,
            )
            self.session.add(entry)
            self.session.flush()
            result.taint["memory_entry_id"] = entry.id
            result.taint["memory_expires_at"] = expires_at.isoformat() if expires_at else None
        return result

    # ------------------------------------------------------------------
    # Inter-agent message security (P17, NOM-IAM-08) — closes OWASP ASI07
    # ------------------------------------------------------------------

    def guard_agent_message(
        self,
        *,
        sender_slug: str,
        content: str,
        recipient_slug: str | None = None,
        nonce: str | None = None,
        timestamp: float | None = None,
        signature: str | None = None,
        trace: Trace | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Authorise a sub-agent's message to another agent, as another agent's
        untrusted claim rather than as a tool's return value.

        Three checks layer on top of the generic detector pipeline, each mapped
        to the corresponding half of OWASP ASI07:

        * **Agent-card check** — the declared sender must resolve to a
          registered agent, reusing :func:`registry.service.attest_registry`'s
          declared-vs-observed comparison rather than a second attestation
          mechanism. An unregistered sender cannot be vouched for.
        * **Replay protection** — ``(sender, nonce)`` must be unique. A repeat
          fails to insert into ``agent_message_log`` and the message is blocked
          as a replay, full stop, before the detector pipeline even runs.
        * **Signature verification** — where the sender has a registered signing
          key (:mod:`agent_messaging`), the HMAC is checked. Where the transport
          is external (a customer's own A2A/MCP bus) and no signature is
          present, the message is reported **unsigned** rather than silently
          trusted — same "declare the gap, don't hide it" convention P14 uses
          for what it doesn't check.
        """
        agent, identity, _ = self.resolve(sender_slug, None)
        agent_card_match = agent is not None and bool(agent.registered)
        nonce = nonce or ""

        replayed = False
        if persist:
            # A SAVEPOINT, not the whole transaction: a plain `session.rollback()`
            # on the IntegrityError would discard *everything* pending on this
            # session, not just this one failed insert — including, in the
            # request path, the trace/span rows already added ahead of this call.
            try:
                with self.session.begin_nested():
                    self.session.add(
                        AgentMessageLog(
                            sender_slug=sender_slug,
                            recipient_slug=recipient_slug,
                            nonce=nonce,
                            signed=signature is not None,
                            agent_card_match=agent_card_match,
                            trace_id=trace.id if trace else None,
                        )
                    )
                    self.session.flush()
            except IntegrityError:
                replayed = True

        signature_valid: bool | None = None
        if signature is not None and agent is not None and not replayed:
            key_row = self.session.scalar(
                select(AgentSigningKey).where(
                    AgentSigningKey.agent_id == agent.id,
                    AgentSigningKey.revoked_at.is_(None),
                )
            )
            if key_row is None:
                signature_valid = False
            else:
                try:
                    raw_key = decrypt_secret(key_row.key_encrypted)
                    signature_valid = verify_message(
                        raw_key,
                        sender=sender_slug,
                        nonce=nonce,
                        payload=content,
                        timestamp=timestamp or 0.0,
                        signature=signature,
                        validity_seconds=self.settings.agent_message_validity_seconds,
                    )
                except DecryptionFailed:
                    signature_valid = False

        result = self.evaluate(
            agent=agent,
            identity=identity,
            content=content,
            surface="agent_message",
            trace=trace,
            taint_source="subagent",
            persist=persist,
        )

        if replayed:
            result.verdict = "block"
            result.effective_verdict = "block"
            result.reason = f"replayed message: (sender='{sender_slug}', nonce) was already seen"
            result.rules_fired.append(
                _fired_rule(
                    "agent_message.replay", "block", result.reason, controls=["NOM-IAM-08"]
                )
            )
        elif not agent_card_match:
            effect = "escalate" if result.verdict == "allow" else result.verdict
            result.verdict = effect
            result.effective_verdict = effect
            result.rules_fired.append(
                _fired_rule(
                    "agent_message.agent_card_mismatch",
                    effect,
                    f"sender '{sender_slug}' is not a registered agent — "
                    "its agent-card cannot be verified",
                    controls=["NOM-IAM-08"],
                )
            )
        elif signature_valid is False:
            effect = "block" if result.verdict != "block" else result.verdict
            result.verdict = effect
            result.effective_verdict = effect
            result.rules_fired.append(
                _fired_rule(
                    "agent_message.bad_signature",
                    effect,
                    "signature did not verify against the sender's registered signing key",
                    controls=["NOM-IAM-08"],
                )
            )
        elif signature is None:
            result.taint["unsigned"] = True
            result.rules_fired.append(
                _fired_rule(
                    "agent_message.unsigned",
                    "observe",
                    "message arrived unsigned — either the transport is not "
                    "AgentFox's own, or the sender has no registered signing key",
                    controls=["NOM-IAM-08"],
                )
            )

        if persist:
            log_row = self.session.scalar(
                select(AgentMessageLog)
                .where(AgentMessageLog.sender_slug == sender_slug, AgentMessageLog.nonce == nonce)
                .order_by(AgentMessageLog.created_at.desc())
            )
            if log_row is not None:
                log_row.signature_valid = signature_valid
                log_row.decision_id = result.decision_id

        return result

    # ------------------------------------------------------------------
    # Full inline path (gateway)
    # ------------------------------------------------------------------

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

    def _answerability_gate(
        self,
        agent: Agent | None,
        trace: Trace,
        messages: list[dict[str, Any]],
        known_entities: list[str] | None = None,
    ) -> EnforcementResult | None:
        """P7-2/3 — refuse to generate when the question is outside the declared boundary.

        Returns None when there is no boundary, when the question is answerable, or
        when the boundary is in observe mode. The observe case still records the
        counterfactual, so a team can see what enforcement *would* have refused before
        turning it on — which is the only responsible way to ship a control whose
        false positives are refusals.
        """
        boundary = get_boundary(self.session, agent.id if agent else None)
        if boundary is None:
            return None
        question = next(
            (
                _flatten(m.get("content"))
                for m in reversed(messages)
                if str(m.get("role")) == "user"
            ),
            "",
        )
        if not question.strip():
            return None

        verdict = classify_answerability(question, boundary, known_entities=known_entities)
        if verdict.answerable:
            return None

        rule = _fired_rule(
            f"answerability.{verdict.abstention_kind}",
            "abstain",
            verdict.reasons[0].get("reason")
            or f"question is {verdict.question_type}, outside the declared boundary",
            severity="medium",
            controls=["NOM-RTG-11"],
        )
        chain.append(
            self.session,
            action=f"answerability.{verdict.abstention_kind}",
            actor_type="agent",
            actor_id=agent.id if agent else None,
            subject_type="trace",
            subject_id=trace.id,
            payload={"question_type": verdict.question_type, "reasons": verdict.reasons},
        )
        result = EnforcementResult(
            # `abstain` sits between redact and escalate in the lattice: it withholds
            # the answer without treating the user as an adversary.
            verdict="abstain" if verdict.should_abstain else "allow",
            effective_verdict="abstain",
            mode=boundary.mode,
            trace_id=trace.id,
            rules_fired=[rule],
            reason=rule["reason"],
            content=verdict.response,
        )
        result.taint["answerability"] = verdict.to_json()
        return result if verdict.should_abstain else None

    def _answerability_postflight(self, agent: Agent | None, trace: Trace, answer: str) -> None:
        boundary = get_boundary(self.session, agent.id if agent else None)
        if boundary is None or not answer:
            return
        verdict = classify_answerability(answer, boundary)
        for breach in verify_boundary(answer, verdict, boundary):
            raise_finding(
                self.session,
                type="boundary_breach",
                severity="medium",
                title=f"Answer exceeded the declared knowledge boundary: {breach['breach']}",
                subject_type="agent",
                subject_id=agent.id if agent else None,
                evidence={**breach, "trace_id": trace.id},
                control_keys=["NOM-RTG-11"],
                fingerprint_parts=(breach.get("breach"),),
            )
        detect_over_refusal(
            self.session,
            answer=answer,
            verdict=verdict,
            agent_id=agent.id if agent else None,
            trace_id=trace.id,
        )

    def _evidence_checks(
        self, agent: Agent | None, surface: str, content: str, intent: str | None
    ) -> dict[str, Any]:
        """F2 source authority and F7 numeric integrity, on the output surface.

        Both need the evidence the answer was built from, which the caller supplies
        via ``self.evidence``. When nothing is supplied they return quietly rather
        than guessing: an integrity check that invents its own ground truth is worse
        than none.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        chunks = evidence.get("chunks")
        records = evidence.get("records")
        entities = evidence.get("entities")
        if not any((chunks, records, entities, evidence.get("components"))):
            return {}

        context_text = " ".join(str(c.get("text") or "") for c in (chunks or []))
        provenance = assess_provenance(
            self.session, content, chunks, agent_domain=evidence.get("domain")
        )
        integrity = assess_integrity(
            question=intent or evidence.get("question", ""),
            answer=content,
            context=context_text,
            records=records,
            entities=entities,
            components=evidence.get("components"),
        )

        issues: list[dict[str, Any]] = []
        for breach in provenance.breaches:
            issues.append(
                {
                    "type": "source_authority",
                    "severity": "high" if breach["kind"] == "deprecated_source" else "medium",
                    "title": breach["reason"],
                    **breach,
                }
            )
        for fabricated in provenance.fabricated:
            issues.append(
                {
                    "type": "fabricated_citation",
                    "severity": "high",
                    "title": fabricated["reason"],
                    **fabricated,
                }
            )
        for conflict in provenance.conflicts:
            issues.append(
                {
                    "type": "source_conflict",
                    "severity": "medium",
                    "title": conflict["reason"],
                    **conflict,
                }
            )
        for issue in integrity.issues:
            issues.append(
                {
                    "type": "integrity_error",
                    "severity": "high"
                    if issue["kind"] in ("hallucinated_record", "entity_confusion")
                    else "medium",
                    "title": issue["reason"],
                    **issue,
                }
            )
        return {
            "provenance": provenance.to_json(),
            "integrity": integrity.to_json(),
            "evidence_issues": issues,
        }

    def _disclosure_checks(
        self, agent: Agent | None, surface: str, content: str, trace_id: str | None
    ) -> dict[str, Any]:
        """P10 — what this human may see, and what the answer disclosed anyway.

        The pre-filter belongs to whoever performs retrieval, so it is exposed
        separately; this is the post-flight half, which catches the two disclosures no
        access check can — an aggregate over too few people, and an attribute the model
        inferred rather than retrieved.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        principal = evidence.get("principal")
        chunks = evidence.get("chunks") or []
        issues: list[dict[str, Any]] = []
        out: dict[str, Any] = {}

        if principal is not None:
            decision = filter_retrieval(
                self.session,
                principal,
                chunks,
                purpose=evidence.get("purpose"),
            )
            record_disclosure(
                self.session,
                decision,
                trace_id=trace_id,
                agent_id=agent.id if agent else None,
                stage="post",
            )
            out["disclosure"] = decision.to_json()
            for withheld in decision.withheld:
                # A chunk the principal could not see, quoted in the answer, is the
                # oversharing failure itself rather than a near miss.
                text = str(withheld.get("text") or "")
                if text and text[:60] and text[:60] in content:
                    issues.append(
                        {
                            "type": "entitlement_disclosure",
                            "severity": "critical",
                            "title": (
                                f"the answer contains content from "
                                f"'{withheld.get('source')}', which "
                                f"'{decision.principal}' is not entitled to see"
                            ),
                        }
                    )

        aggregate = aggregation_risk(
            content,
            contributors=evidence.get("contributors"),
            k=self.settings.k_anonymity_threshold,
        )
        if aggregate:
            issues.append(
                {
                    "type": "aggregation_disclosure",
                    "severity": "high",
                    "title": aggregate["reason"],
                    **aggregate,
                }
            )

        inferred = inference_risk(content, " ".join(str(c.get("text") or "") for c in chunks))
        if inferred:
            issues.append(
                {
                    "type": "inference_disclosure",
                    "severity": "high",
                    "title": inferred["reason"],
                    **inferred,
                }
            )

        if issues:
            out["evidence_issues"] = [*out.get("evidence_issues", []), *issues]
        return out

    def _control_flow_checks(self, surface: str, tool_key: str | None) -> dict[str, Any]:
        """Did the user's instruction choose this tool, or did something the agent read?

        Taint tracking governs an argument's *value*. The injection it cannot see adds a
        *step*: "also email a copy to attacker@evil.example", whose every argument is
        legitimately user-sourced. The call itself is the payload.

        Gated on the caller declaring a plan or a selector, for the same reason the F6
        disclosure check is gated: an undeclared plan is not evidence of an attack, and a
        checker that fires on missing information is noise. Whoever runs the agent loop
        knows which tools the user's own instruction authorised — the SDK session, the
        LangGraph node or the MCP governor — and supplies it through ``self.evidence``.
        """
        if surface != "tool_args" or not tool_key:
            return {}
        evidence = self.evidence or {}
        declared_plan = evidence.get("plan")
        selected_by = str(evidence.get("selected_by") or "user")
        if not declared_plan and selected_by == "user":
            return {}

        plan = (
            declared_plan
            if isinstance(declared_plan, Plan)
            else Plan(
                intent=str(evidence.get("intent") or ""),
                tools=list(declared_plan or []),
            )
        )
        untrusted = [
            str(chunk.get("text") or "") if isinstance(chunk, dict) else str(chunk)
            for chunk in (evidence.get("untrusted_texts") or evidence.get("chunks") or [])
        ]
        finding = check_tool_selection(
            tool_key, plan=plan, untrusted_texts=untrusted, selected_by=selected_by
        )
        if finding is None:
            return {}
        return {
            "control_flow": {"plan": plan.to_json(), "selected_by": selected_by},
            "evidence_issues": [
                {
                    "type": "control_flow",
                    "severity": finding.severity,
                    "title": finding.detail,
                    "code": finding.code,
                    "control_keys": ["NOM-RTG-04", "NOM-IAM-03"],
                }
            ],
            "risks": [
                {
                    # Capped below `critical` for the same reason F6/F8 are: that list is
                    # hard-blocked in `evaluate()`, and this is observe-first. A policy
                    # rule `action_risk: "control_flow.*"` is how an operator makes it block.
                    "code": finding.code,
                    "severity": "high" if finding.severity == "critical" else finding.severity,
                    "detail": finding.detail,
                    "evidence": finding.to_json(),
                }
            ],
        }

    def _sycophancy_checks(self, surface: str, content: str, intent: str | None) -> dict[str, Any]:
        """F9.2 — the answer adopted a false premise the user asserted.

        Checked against the caller's grounded record, never against the model's opinion of
        it: `evidence["grounded"]` maps a subject to its real value. Without that there is
        no authority to contradict anyone with, so nothing fires — which is also what keeps
        opinions and genuinely ungrounded matters out of it.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        grounded = evidence.get("grounded")
        question = str(evidence.get("question") or intent or "")
        if not grounded or not question:
            return {}

        findings = check_premises(question, content, grounded)
        if not findings:
            return {}
        return {
            "evidence_issues": [
                {
                    "type": "sycophancy",
                    "severity": finding.severity,
                    "title": finding.detail,
                    "code": finding.code,
                    "control_keys": ["NOM-RTG-12"],
                }
                for finding in findings
            ],
            "risks": [
                {
                    "code": finding.code,
                    "severity": "high" if finding.severity == "critical" else finding.severity,
                    "detail": finding.detail,
                    "evidence": finding.to_json(),
                }
                for finding in findings
            ],
        }

    def _commitment_checks(
        self, agent: Agent | None, surface: str, content: str, intent: str | None
    ) -> dict[str, Any]:
        """F6 — the obligations an answer created, on the output surface.

        Built to the shape `_evidence_checks` established: findings are recorded and
        surfaced, and nothing here decides a verdict by itself.

        Two of the four detectors run unconditionally, because they are quiet on
        ordinary traffic rather than because running them is free — `detect_commitments`
        keys on performative verbs ("I guarantee", "your refund has been approved") and
        `check_register` fires only in a regulated domain or on an unhedged claim about
        the future. The other two are gated on the caller declaring the fact they need,
        because inferring it would mean inventing ground truth:

        * **AI disclosure** (F6.3, EU AI Act Art. 50) resolves to *breach* for any
          message on a human-facing channel that does not identify itself as automated.
          That is correct as an obligation and wrong as a default — inferred, it would
          report a breach on essentially every response this product has governed. The
          obligation exists only where there is a human counterparty, and no property of
          the text establishes that, so the caller supplies `evidence["channel"]` /
          `["counterparty"]`.
        * **Adverse action** (F6.4, ECOA/FCRA) is checked against the *decision record*
          rather than the prose, precisely because a message can read as an explanation
          while the record behind it is empty. No record supplied, no check performed.

        `fairness_probe` (F6.5) is deliberately NOT wired here, and should not be. It is
        an aggregate statistic — selection rates by group against the four-fifths rule,
        with a 30-observation floor below which it refuses to report at all — computed
        over a population of decisions. One request cannot exhibit disparate impact, and
        calling it per-request could only ever return the `underpowered` result while
        implying the check had run. It belongs to the compliance/eval path, over a
        decision population, and stays there.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        text = content[:_SCAN_CHARS]
        issues: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        out: dict[str, Any] = {}

        # F6.1 — a commitment is made in the speech act, so this reads the answer and
        # nothing else. `authorised` is the caller's statement that the agent genuinely
        # held the authority; the commitment is still recorded, it simply is not a
        # finding, which is the module's own documented behaviour.
        commitments = detect_commitments(text, authorised=bool(evidence.get("authorised")))
        if commitments:
            out["commitments"] = [c.to_json() for c in commitments]
            for commitment in commitments:
                issues.append(
                    {
                        "type": "binding_commitment",
                        "severity": "high",
                        "title": f"the answer {commitment.why}: {commitment.text!r}",
                        "kind": commitment.kind,
                        "control_keys": ["NOM-RTG-11"],
                    }
                )
                risks.append(
                    {
                        "code": f"commitment.{commitment.kind}",
                        "severity": "high",
                        "detail": f"{commitment.why}: {commitment.text!r}",
                        "evidence": commitment.to_json(),
                    }
                )

        # F6.2 — specificity licensed by epistemic standing. `licensed_domains` is the
        # declaration that makes this workable: an operator that employs clinicians
        # licenses `medical` and the instruction findings stop firing. Standing is
        # declared, never inferred.
        register = check_register(
            text,
            request=intent or str(evidence.get("question") or ""),
            licensed_domains=tuple(evidence.get("licensed_domains") or ()),
        )
        if register.findings:
            out["register"] = register.to_json()
            for finding in register.findings:
                issues.append(
                    {
                        "type": "register_breach",
                        "severity": finding.severity,
                        "title": finding.detail,
                        "code": finding.code,
                        "domain": register.domain,
                        "control_keys": ["NOM-RTG-11"],
                    }
                )
                risks.append(
                    {
                        "code": f"register.{finding.code}",
                        # Capped below `critical` on purpose — a critical entry in
                        # `action["risks"]` is hard-blocked by the action-assurance
                        # branch in `evaluate()`, and F6 is observe-first. The severity
                        # the detector actually assigned is preserved on the finding.
                        "severity": "high" if finding.severity == "critical" else finding.severity,
                        "detail": finding.detail,
                        "evidence": finding.to_json(),
                    }
                )

        # F6.3 — see the docstring: gated on a declared counterparty, never inferred.
        if evidence.get("channel") or evidence.get("counterparty"):
            disclosure = check_disclosure(
                text,
                channel=str(evidence.get("channel") or "chat"),
                counterparty=str(evidence.get("counterparty") or "human"),
                already_disclosed=bool(evidence.get("already_disclosed")),
                exempt=bool(evidence.get("disclosure_exempt")),
            )
            # `ai_disclosure`, not `disclosure`: `_disclosure_checks` already owns that
            # key for the P10 entitlement decision, and the two answer different
            # questions — what this person may see, versus whether they were told they
            # were talking to a machine.
            out["ai_disclosure"] = disclosure.to_json()
            if disclosure.breach:
                issues.append(
                    {
                        "type": "ai_disclosure_missing",
                        "severity": "medium",
                        "title": (
                            "the person was not told they were talking to an AI system: "
                            f"{disclosure.reason}"
                        ),
                        "control_keys": ["NOM-GOV-05"],
                    }
                )
                risks.append(
                    {
                        "code": "disclosure.ai_missing",
                        "severity": "medium",
                        "detail": disclosure.reason,
                        "evidence": disclosure.to_json(),
                    }
                )

        # F6.4 — checked against the recorded decision, which is what has to stand up.
        record = evidence.get("decision") or {}
        outcome = str(record.get("outcome") or "")
        if outcome:
            adverse = adverse_action_risk(
                outcome,
                reasons=[str(r) for r in (record.get("reasons") or [])],
                domain=str(record.get("domain") or evidence.get("domain") or ""),
                text=text,
            )
            out["adverse_action"] = adverse.to_json()
            for detail in adverse.findings:
                issues.append(
                    {
                        "type": "adverse_action",
                        "severity": "high" if adverse.statutory else "medium",
                        "title": detail,
                        "outcome": adverse.outcome,
                        "domain": adverse.domain,
                        "statutory": adverse.statutory,
                        "control_keys": ["NOM-RTG-11"],
                    }
                )
                risks.append(
                    {
                        "code": "adverse_action.statutory"
                        if adverse.statutory
                        else "adverse_action.unexplained",
                        "severity": "high" if adverse.statutory else "medium",
                        "detail": detail,
                        "evidence": adverse.to_json(),
                    }
                )

        if issues:
            out["evidence_issues"] = issues
        if risks:
            out["risks"] = risks
        return out

    def _trajectory_checks(
        self, surface: str, window: list[str] | None
    ) -> dict[str, Any]:
        """F9.4 — whether the *conversation* is escalating, not whether this turn is.

        Built to the shape `_commitment_checks` established, for the same reason: the
        finding is recorded and surfaced on the `action["risks"]` channel, and nothing
        here decides a verdict. See `trajectory.py` for the measurement.

        Why this is the integration point. F9.4 asks for the trajectory score to hang
        off the per-turn recording hook, and notes that F5 ended up fully live while
        F6/F8 did not precisely because F5 had a natural per-turn hook to attach to.
        `check_conversation_window` is that hook on this path: it already runs once per
        user turn, already holds a `session_id` and the recorded history behind it, and
        is already called from `autoguard._govern`'s pre-flight and the gateway
        playground route. Nothing else needed wiring, which is the whole point —
        `docs/failure-modes.md` exists to catch modules that are built and never
        called, and a trajectory scorer reachable only from its own tests would be
        exactly that.

        **Sub-threshold detector activations.** F9.4's first component is a detector
        finding above zero and below the blocking threshold. The per-message run for
        the *current* turn already exists, but the equivalent number for the earlier
        turns in the window is not persisted anywhere — `ConversationTurn.signals_json`
        is written by `escalation.record_turn` and carries escalation's signals, not
        detector scores. So each turn in the window is scored here, through the real
        pipeline, at a measured ~0.4ms per turn. Worth knowing what that buys:
        `benchmarks/crescendo/` measures the shipped detectors returning **exactly
        zero on all 132 turns** of that corpus, so on crescendo traffic this component
        contributes nothing and the drift and reframing components are doing all the
        work. It is kept because it is cheap and because a conversation that mixes
        gradual escalation with clumsier probing is the case where it pays.
        """
        if surface != "input" or not window or len(window) < 3:
            return {}

        # Never let a governance extra break a request, and never let it eat the
        # budget: the per-turn scoring is bounded by the window size (<= 8 short
        # strings) and skipped wholesale if anything goes wrong.
        try:
            detector_scores = self._window_detector_scores(window)
            assessment = assess_trajectory(window, detector_scores=detector_scores)
        except Exception as exc:  # pragma: no cover - defence in depth
            log.debug("agentfox: trajectory scoring skipped: %s", exc)
            return {}

        out: dict[str, Any] = {"trajectory": assessment.to_json()}
        if not assessment.fired:
            return out
        out["evidence_issues"] = [
            {
                "type": "trajectory_drift",
                # High, never critical: a `critical` entry in `action["risks"]` is
                # hard-blocked by the action-assurance branch in `evaluate()`, and
                # F9.4 is observe-first. Same cap, same reason, as F6's findings.
                "severity": "high",
                "title": f"{TRAJECTORY_ENTITY}: {assessment.reason}",
                "entity": TRAJECTORY_ENTITY,
                "control_keys": ["NOM-RTG-06"],
            }
        ]
        out["risks"] = [
            {
                "code": assessment.code,
                "severity": "high",
                "detail": assessment.reason,
                "evidence": assessment.to_json(),
            }
        ]
        return out

    def _window_detector_scores(self, window: list[str]) -> list[float]:
        """Each window turn's per-message detector max score, for F9.4's component one.

        Runs the same pipeline the per-message path runs, one short turn at a time.
        A degraded or erroring run contributes 0.0 rather than failing the check —
        the component is additive, so a missing one under-reports rather than
        inventing a trajectory.

        Capped at `trajectory.SCAN_CHARS` per turn, and that cap is load-bearing
        rather than tidy: this runs the pipeline once *per turn in the window*,
        so an uncapped 250KB turn costs about 2.5 seconds against a 300ms budget.
        The per-message path still sees the whole message; what is bounded here is
        only the proxy feeding the trajectory score.
        """
        context = DetectionContext(surface="input", taint_source="user")
        scores: list[float] = []
        for text in window:
            try:
                scores.append(self.pipeline.run(text[:TRAJECTORY_SCAN_CHARS], context).max_score)
            except Exception:  # pragma: no cover - defence in depth
                scores.append(0.0)
        return scores

    def _context_checks(
        self, surface: str, content: str, memory_entry: dict[str, Any] | None
    ) -> dict[str, Any]:
        """F8 — whether the context was intact, on the surfaces context arrives on.

        The failure this addresses is invisible from the far end of the pipe: a model
        handed a mangled context does not report a mangled context, it answers fluently
        from whatever survived. Groundedness then confirms the answer matches that
        context and nothing anywhere reports a problem. So these run on the way *in* —
        `retrieved` and `tool_result` for content quality, `memory_write` for binding —
        and, unlike the opt-in `POST /provenance/context-check` route, on ordinary
        traffic without the caller asking.

        `assemble_context` is not called here, on purpose. It is the one function in the
        module that also *repairs* (it reorders for salience), and it needs the ranked
        chunk list and the real token budget, both of which belong to whoever performed
        the retrieval. Manufacturing an assembly step inside `evaluate()` would measure a
        fit this code had just invented. It is exposed as `Enforcer.assemble_context` for
        that caller instead.
        """
        if not content and not memory_entry:
            return {}
        evidence = self.evidence or {}
        findings: list[Any] = []
        out: dict[str, Any] = {}

        if surface in ("retrieved", "tool_result") and content:
            quality = document_quality(
                content[:_SCAN_CHARS], source_key=str(evidence.get("source") or "")
            )
            document_findings = [
                f
                for f in quality.findings
                if surface != "tool_result" or f.code in _CORRUPTION_CODES
            ]
            findings.extend(document_findings)
            if document_findings:
                out["document_quality"] = {
                    "score": round(quality.score, 3),
                    "usable": quality.usable,
                    "findings": [f.to_json() for f in document_findings],
                }

            # Chunk coherence needs the chunk boundaries, which only the retriever has —
            # the assembled string on this surface has already lost them. Supplied via
            # the same `evidence["chunks"]` the F2/F7 checks read, so a caller that has
            # wired evidence once gets this for free.
            if chunks := evidence.get("chunks"):
                findings.extend(
                    chunk_quality(
                        [
                            {"text": str(c.get("text") or "")[:_SCAN_CHUNK_CHARS]}
                            if isinstance(c, dict)
                            else str(c)[:_SCAN_CHUNK_CHARS]
                            for c in list(chunks)[:_SCAN_CHUNKS]
                        ]
                    )
                )

            # F8.6 — regression is only visible against a baseline, so this needs one
            # rather than a threshold. Both come from the caller or it does not run.
            current, baseline = evidence.get("retrieval"), evidence.get("baseline")
            if current and baseline and (drift := retrieval_drift(current, baseline)):
                findings.append(drift)

        elif surface == "memory_write":
            # F8.5 — the boundary that matters within one tenant is the *subject* the
            # memory is about, not the tenant that owns the store. Needs a principal to
            # check against; without one there is nothing to compare and it stays quiet.
            principal = evidence.get("principal")
            entries = [dict(e) for e in (evidence.get("memory") or []) if isinstance(e, dict)]
            if memory_entry is not None:
                entries.append(memory_entry)
            if principal and entries:
                findings.extend(
                    memory_binding_breach(
                        entries,
                        principal=str(principal),
                        session_id=evidence.get("session_id"),
                    )
                )

        if not findings:
            return out

        out["context"] = {
            "verdict": worst_context_verdict(findings),
            "findings": [f.to_json() for f in findings],
        }
        # Recorded, and left to policy. `verdict` above is what the *module* would say
        # in isolation (`degraded` maps to abstain, `reject` to block); it is reported
        # rather than applied, because dropping a corrupt document is a decision with a
        # cost that belongs to the operator.
        out["evidence_issues"] = [
            {
                "type": "context_integrity",
                "severity": _CONTEXT_SEVERITY.get(f.severity, "medium"),
                "title": f.detail,
                "code": f.code,
                "surface": surface,
                "control_keys": ["NOM-RTG-13" if surface == "memory_write" else "NOM-RTG-12"],
            }
            for f in findings
        ]
        out["risks"] = [
            {
                "code": f"context.{f.code}",
                "severity": _CONTEXT_SEVERITY.get(f.severity, "medium"),
                "detail": f.detail,
                "evidence": f.to_json(),
            }
            for f in findings
        ]
        return out

    def _business_ladders(
        self,
        agent: Agent | None,
        surface: str,
        tool_key: str | None,
        arguments: dict[str, Any] | None,
    ) -> LadderDecision | None:
        """Evaluate the business ladders that apply to this call.

        Only on the tool-argument surface: a ladder bands a number the caller is about
        to act on, and there is no such number on an input or an output. When several
        apply, the strictest wins and the disagreement is a lint finding rather than a
        silent precedence rule — two authors disagreeing is a fact about the
        organisation, not a merge conflict.
        """
        if surface != "tool_args" or not arguments:
            return None
        try:
            ladders = load_ladders(
                self.session, tool=tool_key, agent_id=agent.id if agent else None
            )
        except Exception as exc:  # pragma: no cover - storage must not break the path
            log.warning("business ladders unavailable: %s", exc)
            return None
        if not ladders:
            return None

        request = {"arguments": arguments, "tool": tool_key}
        decisions = [
            evaluate_ladder(ladder, request)
            for ladder in ladders
            if ladder.tool in (None, tool_key)
        ]
        decisions = [d for d in decisions if d.matched or d.undecidable]
        if not decisions:
            return None
        return max(decisions, key=lambda d: BUSINESS_RANK.get(d.outcome, 0))

    # -- I-4/I-6 observability correlation -------------------------------

    def _correlate(self, trace, correlation) -> None:
        """Record the join key to LangSmith/Langfuse. Never fails the request.

        Correlation is a convenience for the humans debugging later; it must not be
        able to take down the path it is describing.
        """
        try:
            if isinstance(correlation, dict):
                refs = refs_from_headers(correlation)
            elif correlation:
                refs = list(correlation)
            else:
                refs = []
            refs = refs + refs_from_env()
            if refs:
                link_trace(self.session, trace.id, refs)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("correlation link skipped: %s", exc)

    def _push_correlation(self, trace, result, agent_slug: str | None) -> None:
        try:
            push_verdict(
                self.session,
                trace.id,
                verdict=result.verdict,
                effective_verdict=result.effective_verdict,
                rules=[r.get("rule_id", "") for r in result.rules_fired],
                agent_slug=agent_slug,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("correlation push skipped: %s", exc)

    def preflight(
        self,
        *,
        agent_slug: str | None,
        messages: list[dict[str, Any]],
        model: str = "default",
        provider: str | None = None,
        credential: str | None = None,
        environment: str = "production",
        session_id: str | None = None,
        intent: str | None = None,
        trust_map: dict[str, str] | None = None,
        correlation: dict[str, str] | list[Any] | None = None,
        known_entities: list[str] | None = None,
    ) -> PreflightOutcome:
        """Steps 2-6 of the request path, shared by buffered and streaming calls.

        Extracted so that streaming cannot drift from non-streaming enforcement. A
        streaming path that quietly skips a check is exactly the class of defect
        PL-1 exists to remove.
        """
        self.reset_ledger()
        agent, identity, _is_shadow = self.resolve(
            agent_slug, credential, environment=environment, model=model
        )

        # PL-3: a killed or quarantined agent never reaches the model.
        control = self._control_verdict(agent)
        if control is not None:
            trace = start_trace(
                self.session,
                agent_id=agent.id if agent else None,
                agent_slug=agent.slug if agent else agent_slug,
                session_id=session_id,
                environment=environment,
                intent=intent,
                model=model,
                provider=provider or self.settings.default_provider,
            )
            self._correlate(trace, correlation)
            control.trace_id = trace.id
            end_trace(self.session, trace, verdict=control.verdict, status="blocked")
            self._push_correlation(trace, control, agent.slug if agent else agent_slug)
            return PreflightOutcome(
                agent=agent, identity=identity, trace=trace, result=control, stopped=True
            )

        trace = start_trace(
            self.session,
            agent_id=agent.id if agent else None,
            agent_slug=agent.slug if agent else agent_slug,
            session_id=session_id,
            environment=environment,
            intent=intent,
            model=model,
            provider=provider or self.settings.default_provider,
        )

        self._correlate(trace, correlation)

        # P15-3: hard caps, checked before the model call rather than after the spend.
        budget = self._budget_gate(agent, trace)
        if budget is not None:
            end_trace(self.session, trace, verdict="block", status="blocked")
            self._push_correlation(trace, budget, agent.slug if agent else agent_slug)
            return PreflightOutcome(
                agent=agent, identity=identity, trace=trace, result=budget, stopped=True
            )

        # P7: answerability, before generation. Every competitor scores the answer
        # after it exists, which cannot address F1 — by then the number has been
        # invented, and a confident wrong number scored at 0.4 is still a confident
        # wrong number in front of a user.
        abstain = self._answerability_gate(agent, trace, messages, known_entities)
        if abstain is not None:
            end_trace(self.session, trace, verdict=abstain.verdict, status="abstained")
            self._push_correlation(trace, abstain, agent.slug if agent else agent_slug)
            return PreflightOutcome(
                agent=agent, identity=identity, trace=trace, result=abstain, stopped=True
            )

        tracker = TaintTracker(trace_id=trace.id)
        tracker.mark_messages(messages, trust_map)
        for mark in tracker.marks:
            self.session.add(
                TaintTag(
                    trace_id=trace.id,
                    path=mark.path,
                    source=mark.source,
                    trust=mark.trust,
                    propagated_from=mark.propagated_from,
                )
            )

        worst = EnforcementResult()
        redacted_messages = list(messages)

        for i, message in enumerate(messages):
            text = _flatten(message.get("content"))
            if not text.strip():
                continue
            role = str(message.get("role", "user"))
            source = (trust_map or {}).get(str(i)) or {
                "system": "none",
                "developer": "none",
                "assistant": "none",
                "user": "user",
                "tool": "tool_result",
                "function": "tool_result",
            }.get(role, "user")
            surface = {
                "tool_result": "tool_result",
                "retrieved": "retrieved",
                "subagent": "tool_result",
            }.get(source, "input")

            outcome = self.evaluate(
                agent=agent,
                identity=identity,
                content=text,
                surface=surface,
                trace=trace,
                taint_source=source,
                intent=intent,
                tracker=tracker,
            )
            if outcome.content is not None:
                redacted_messages[i] = {**message, "content": outcome.content}
            if self._severity(outcome) >= self._severity(worst):
                worst = outcome

        worst.trace_id = trace.id
        if worst.blocked or worst.escalated:
            end_trace(self.session, trace, verdict=worst.verdict, status="blocked")
            return PreflightOutcome(
                agent=agent,
                identity=identity,
                trace=trace,
                tracker=tracker,
                messages=redacted_messages,
                result=worst,
                stopped=True,
            )

        return PreflightOutcome(
            agent=agent,
            identity=identity,
            trace=trace,
            tracker=tracker,
            messages=redacted_messages,
            result=worst,
        )

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

    def call_provider(
        self,
        request: CompletionRequest,
        *,
        provider: str | None,
        model: str,
        ladder: FallbackLadder | None = None,
        stream: bool = False,
    ):
        """Call a provider with circuit breaking and a degradation ladder (P15-1/2).

        Returns ``(response_or_iterator, DegradationRecord)``. Degradation is recorded
        rather than silently absorbed: an answer served by a smaller model did not come
        from the model the agent was evaluated against, and a baseline that quietly
        covers a different model is worthless.
        """
        preferred = _Rung(provider or self.settings.default_provider, model)
        ladder = ladder or FallbackLadder.parse(self.settings.fallback_chain)
        record = DegradationRecord()
        last_error: Exception | None = None

        for index, rung in enumerate([preferred, *ladder.rungs]):
            key = f"{rung.provider}:{rung.model}"
            if not BREAKER.allows(key):
                record.attempts.append(
                    ProviderAttempt(
                        rung.provider,
                        rung.model,
                        ok=False,
                        error="circuit open — failing fast",
                        breaker_state=BREAKER.state_of(key),
                    )
                )
                continue
            try:
                model_provider = get_provider(rung.provider)
            except KeyError as exc:
                record.attempts.append(
                    ProviderAttempt(rung.provider, rung.model, ok=False, error=str(exc))
                )
                continue

            attempt_request = CompletionRequest(
                messages=request.messages,
                model=rung.model or request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
            )
            try:
                result = (
                    model_provider.stream(attempt_request)
                    if stream
                    else model_provider.complete(attempt_request)
                )
            except Exception as exc:  # noqa: BLE001 - any provider failure trips the breaker
                BREAKER.record_failure(key)
                last_error = exc
                record.attempts.append(
                    ProviderAttempt(
                        rung.provider,
                        rung.model,
                        ok=False,
                        error=str(exc),
                        breaker_state=BREAKER.state_of(key),
                    )
                )
                continue

            BREAKER.record_success(key)
            record.attempts.append(ProviderAttempt(rung.provider, rung.model, ok=True))
            record.served_by = key
            record.degraded = index > 0
            return result, model_provider, record

        raise ProviderUnavailable(
            f"every provider on the ladder failed or is circuit-open: "
            f"{[a.provider + ':' + a.model for a in record.attempts]}"
        ) from last_error

    def _control_verdict(self, agent: Agent | None) -> EnforcementResult | None:
        """PL-3 kill switch / quarantine. Checked before anything else."""
        if agent is None:
            return None
        from .models import AgentControl

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

    def _finish_completion(
        self,
        *,
        agent,
        agent_slug,
        identity,
        trace,
        tracker,
        worst,
        response,
        model,
        model_provider,
        provider_ms,
        intent,
        schema,
        severity=None,
    ) -> tuple[EnforcementResult, Any]:
        """Post-flight, span, budget and trace close — shared by both paths."""
        rank = severity or self._severity
        add_span(
            self.session,
            trace,
            kind="llm",
            name=f"{model_provider.key}.complete",
            attributes={
                ATTR_SYSTEM: model_provider.key,
                ATTR_REQUEST_MODEL: model,
                ATTR_AGENT: agent.slug if agent else agent_slug,
                "gen_ai.usage.input_tokens": response.usage.get("input_tokens", 0),
                "gen_ai.usage.output_tokens": response.usage.get("output_tokens", 0),
                "agentfox.output": response.text,
            },
            duration_ms=provider_ms,
        )

        outbound = self.evaluate(
            agent=agent,
            identity=identity,
            content=response.text,
            surface="output",
            trace=trace,
            taint_source="none",
            intent=intent,
            schema=schema,
            tracker=tracker,
        )
        if outbound.content is not None:
            response.text = outbound.content
        final = outbound if rank(outbound) >= rank(worst) else worst
        final.trace_id = trace.id

        # P7-4/P7-6: post-flight boundary verification and the counter-metric. Both
        # produce findings and neither blocks — an over-refusing agent is uninstalled
        # faster than a hallucinating one, so this side of the control never enforces.
        self._answerability_postflight(agent, trace, response.text)

        self._charge_budget(agent, response)
        end_trace(
            self.session,
            trace,
            verdict=final.verdict,
            status="ok",
            usage=response.usage,
            cost_usd=response.cost_usd,
        )
        self._push_correlation(trace, final, agent.slug if agent else agent_slug)
        return final, (None if final.blocked else response)

    def run_completion(
        self,
        *,
        agent_slug: str | None,
        messages: list[dict[str, Any]],
        model: str = "default",
        provider: str | None = None,
        credential: str | None = None,
        environment: str = "production",
        session_id: str | None = None,
        intent: str | None = None,
        trust_map: dict[str, str] | None = None,
        correlation: dict[str, str] | list[Any] | None = None,
        known_entities: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[EnforcementResult, Any]:
        """The complete request path (PRD §9.3). Returns (result, response|None)."""
        pre = self.preflight(
            agent_slug=agent_slug,
            messages=messages,
            model=model,
            provider=provider,
            credential=credential,
            environment=environment,
            session_id=session_id,
            intent=intent,
            trust_map=trust_map,
            correlation=correlation,
            known_entities=known_entities,
        )
        if evidence is not None:
            self.evidence = evidence
        if pre.stopped:
            return pre.result, None

        agent, identity, trace = pre.agent, pre.identity, pre.trace
        tracker, redacted_messages, worst = pre.tracker, pre.messages, pre.result

        def severity(result: EnforcementResult) -> tuple[int, int]:
            return (_RANK[result.verdict], _RANK[result.effective_verdict])

        # --- 7. provider call --------------------------------------------
        started = time.perf_counter()
        response, model_provider, degradation = self.call_provider(
            CompletionRequest(
                messages=redacted_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            provider=provider,
            model=model,
        )
        provider_ms = (time.perf_counter() - started) * 1000
        worst.taint = {**worst.taint, "degradation": degradation.to_json()}
        return self._finish_completion(
            agent=agent,
            agent_slug=agent_slug,
            identity=identity,
            trace=trace,
            tracker=tracker,
            worst=worst,
            response=response,
            model=model,
            model_provider=model_provider,
            provider_ms=provider_ms,
            intent=intent,
            schema=schema,
            severity=severity,
        )

    # ------------------------------------------------------------------
    # Streaming path (PL-1)
    # ------------------------------------------------------------------

    def run_completion_stream(
        self,
        *,
        agent_slug: str | None,
        messages: list[dict[str, Any]],
        model: str = "default",
        provider: str | None = None,
        credential: str | None = None,
        environment: str = "production",
        session_id: str | None = None,
        intent: str | None = None,
        trust_map: dict[str, str] | None = None,
        correlation: dict[str, str] | list[Any] | None = None,
        known_entities: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        mode: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Enforced streaming completion (PL-1).

        Two modes, and the trade-off between them is real rather than cosmetic:

        ``buffered`` (default)
            Accumulate the whole response, run the full post-flight, then release.
            Output enforcement is *identical* to the non-streaming path — nothing can
            leak — at the cost of first-token latency. This is the correct default
            because a DLP control that only inspects the first 200 characters is not
            a DLP control.

        ``windowed``
            Forward chunks as they arrive while running detectors over a growing
            window. First-token latency is preserved, and the honest caveat is that
            **content already forwarded cannot be recalled** — a block terminates the
            stream but does not un-send what preceded it. Offered for latency-critical
            deployments that accept that trade knowingly, never as a silent default.
        """
        mode = mode or self.settings.streaming_mode
        pre = self.preflight(
            agent_slug=agent_slug,
            messages=messages,
            model=model,
            provider=provider,
            credential=credential,
            environment=environment,
            session_id=session_id,
            intent=intent,
            trust_map=trust_map,
            correlation=correlation,
            known_entities=known_entities,
        )
        if evidence is not None:
            self.evidence = evidence
        if pre.stopped:
            yield StreamEvent(kind="blocked", result=pre.result)
            return

        agent, identity, trace = pre.agent, pre.identity, pre.trace
        tracker, redacted_messages, worst = pre.tracker, pre.messages, pre.result

        request = CompletionRequest(
            messages=redacted_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        started = time.perf_counter()
        stream_iter, model_provider, degradation = self.call_provider(
            request, provider=provider, model=model, stream=True
        )
        accumulated: list[str] = []
        usage: dict[str, int] = {}
        finish_reason: str | None = None
        pending: list[StreamEvent] = []
        last_checked = 0
        window = self.settings.stream_window_chars

        for chunk in stream_iter:
            if chunk.usage:
                usage = chunk.usage
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if not chunk.delta:
                continue
            accumulated.append(chunk.delta)
            event = StreamEvent(kind="delta", delta=chunk.delta)

            if mode == "windowed":
                yield event
                text = "".join(accumulated)
                # Re-check only when enough new content has arrived to be worth the
                # detector pass; every chunk would blow the latency budget.
                if len(text) - last_checked >= window:
                    last_checked = len(text)
                    interim = self.evaluate(
                        agent=agent,
                        identity=identity,
                        content=text,
                        surface="output",
                        trace=trace,
                        taint_source="none",
                        intent=intent,
                        tracker=tracker,
                        persist=False,
                    )
                    if interim.blocked:
                        interim.trace_id = trace.id
                        end_trace(self.session, trace, verdict="block", status="blocked")
                        yield StreamEvent(kind="blocked", result=interim)
                        return
            else:
                pending.append(event)

        provider_ms = (time.perf_counter() - started) * 1000
        from .providers import CompletionResponse

        response = CompletionResponse(
            text="".join(accumulated),
            model=model,
            provider=model_provider.key,
            usage=usage,
        )

        final, released = self._finish_completion(
            agent=agent,
            agent_slug=agent_slug,
            identity=identity,
            trace=trace,
            tracker=tracker,
            worst=worst,
            response=response,
            model=model,
            model_provider=model_provider,
            provider_ms=provider_ms,
            intent=intent,
            schema=schema,
        )

        if mode == "buffered":
            if final.blocked:
                yield StreamEvent(kind="blocked", result=final)
                return
            # Release the (possibly redacted) text. Redaction is why this is not a
            # simple replay of `pending`: post-flight may have rewritten the content.
            text = released.text if released else ""
            if text == "".join(accumulated):
                yield from pending
            else:
                yield StreamEvent(kind="delta", delta=text)
        elif final.blocked:
            # Windowed mode: the tail was blocked after content had already been sent.
            yield StreamEvent(kind="blocked", result=final)
            return

        yield StreamEvent(
            kind="done", finish_reason=finish_reason or "stop", usage=usage, result=final
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _raise_detection_finding(
        self,
        *,
        agent: Agent | None,
        trace_id: str | None,
        decision_id: str,
        surface: str,
        effective: str,
        applied: str,
        reason: str,
        rules_fired: list[dict[str, Any]],
        detections: list,
    ) -> None:
        """The general-Findings counterpart to `_persist_detectors`.

        `DetectionFinding.sample` already carries a redacted excerpt — it just
        never left the trace it was captured on. This dedupes by entity type,
        keeping the highest-scoring sample for each, and reuses whichever
        controls the firing rules already declared rather than inventing a new
        control key for the same decision.
        """
        by_entity: dict[str, Any] = {}
        for detection in detections:
            current = by_entity.get(detection.entity_type)
            if current is None or detection.score > current.score:
                by_entity[detection.entity_type] = detection
        if not by_entity:
            return

        controls = sorted({c for r in rules_fired for c in (r.get("controls") or [])}) or [
            "NOM-RTG-06"
        ]
        entity_types = sorted(by_entity)
        severity = "high" if effective in ("block", "escalate") else "medium"

        # One finding per (agent, surface, verdict, entity set): the same detector firing
        # on the same kind of content is one pattern with a count, and the refreshed
        # evidence always points at the latest decision.
        raise_finding(
            self.session,
            type="guardrail_detection",
            severity=severity,
            title=_detection_title(effective, applied, surface, entity_types),
            subject_type="agent",
            subject_id=agent.id if agent else None,
            fingerprint_parts=(surface, effective, *entity_types),
            evidence={
                "trace_id": trace_id,
                "decision_id": decision_id,
                "surface": surface,
                "verdict": effective,
                "reason": reason,
                "detections": [
                    {
                        "entity_type": d.entity_type,
                        "score": d.score,
                        "sample": d.sample,
                        "owasp_id": d.owasp_id,
                        "atlas_id": d.atlas_id,
                    }
                    for d in by_entity.values()
                ],
            },
            control_keys=controls,
        )

    def _record_degradation(self, agent: Agent | None, surface: str, pipeline_result) -> None:
        """P3-7: a degraded detector is a finding — one per detector, closed on recovery."""
        record_detector_health(
            self.session,
            subject_id=agent.id if agent else None,
            surface=surface,
            pipeline_result=pipeline_result,
        )

    def _persist_detectors(self, pipeline_result, trace_id: str | None, surface: str) -> list[str]:
        ids: list[str] = []
        for run in pipeline_result.results:
            row = DetectorRun(
                trace_id=trace_id,
                detector_key=run.detector_key,
                detector_version=run.version,
                surface=surface,
                duration_ms=run.duration_ms,
                status=run.status,
                score=run.score,
                raw_json=run.raw,
            )
            self.session.add(row)
            self.session.flush()
            ids.append(row.id)
            for detection in run.detections:
                self.session.add(
                    DetectionFinding(
                        detector_run_id=row.id,
                        trace_id=trace_id,
                        entity_type=detection.entity_type,
                        score=detection.score,
                        start=detection.start,
                        end=detection.end,
                        # Already redacted by the detector — see redact_sample().
                        sample=detection.sample[:200],
                        owasp_id=detection.owasp_id,
                        atlas_id=detection.atlas_id,
                    )
                )
        return ids

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
                Step(tool=s.get("tool", ""), arguments=s.get("arguments") or {},
                     observation=s.get("observation"))
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
