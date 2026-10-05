"""A machine-readable catalogue of every guardrail kind the product can enforce.

Two problems this solves, and they are the same problem seen from opposite ends.

**Ours.** Fifteen pillars accumulated over this build, each with its own configuration
surface, and no single place that says what kinds of guardrail exist. The audit found
three complete engines nobody could switch on; a registry makes that visible, because
a kind whose `inputs` are never supplied is inert by construction and the catalogue
says so on its face.

**Theirs.** A customer arrives with a policy document — a refunds SOP, a disclosure
standard, a data-handling rule agreed with Legal — and someone has to turn prose into
enforcement. Without a catalogue that person reads the source. With one they answer
three questions: which *kind* of guardrail is this, what does it need to know, and what
should it do when it fires. The entry carries a parameter schema and an authoring
example, so the answer compiles.

The catalogue is deliberately data rather than code. It is exported as JSON so an
authoring assistant — a form, a script, or a model with review — can propose an
instance without importing this package, and `suggest()` does the deterministic half
of that mapping today.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: How the guardrail decides. This distinction is the architectural one: the two
#: families compose by different algebras and must not be flattened into one list.
DETERMINISTIC = "deterministic"  # a parser or comparison; same input, same verdict
LEXICAL = "lexical"  # pattern matching over text; tunable, fallible
STATISTICAL = "statistical"  # scores and thresholds; needs calibration
PROCEDURAL = "procedural"  # runs something and branches on the result
STRUCTURAL = "structural"  # a property of the system, not of a request

#: What a guardrail is *for*, in business terms rather than pillar numbers. This is the
#: vocabulary a policy author uses, which is the point.
INTENTS = (
    "prevent_disclosure",
    "prevent_destructive_action",
    "require_human",
    "require_evidence",
    "refuse_to_answer",
    "constrain_spend",
    "ensure_quality",
    "ensure_compliance",
    "detect_attack",
    "observe_only",
)


@dataclass
class GuardrailKind:
    """One kind of guardrail, described well enough to instantiate without reading code."""

    id: str
    name: str
    intent: str
    nature: str
    #: The question it answers, in one line, from the business's point of view.
    decides: str
    #: What the request must carry for this to do anything. A guardrail whose inputs
    #: are never supplied is inert — the failure the audit found three times.
    inputs: list[str] = field(default_factory=list)
    #: Verdicts it can produce.
    effects: list[str] = field(default_factory=list)
    #: JSON-schema-ish parameter shape for an instance.
    params: dict[str, Any] = field(default_factory=dict)
    #: A worked authoring example, in the YAML an operator would write.
    example: str = ""
    #: Scenario ids from `scripts/probe/taxonomy.py` this kind addresses.
    scenarios: list[str] = field(default_factory=list)
    #: Where it runs: input | retrieval | tool_args | output | conversation | offline.
    stage: str = "output"
    #: Words in a policy document that suggest this kind. Used by `suggest()`.
    signals: list[str] = field(default_factory=list)
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


CATALOGUE: list[GuardrailKind] = [
    # ---------------------------------------------------------------- business shapes
    GuardrailKind(
        id="threshold_ladder",
        name="Threshold ladder",
        intent="require_human",
        nature=DETERMINISTIC,
        decides="Which of several outcomes applies, based on where a number falls.",
        inputs=["a numeric field on the request", "an explicit unit or currency"],
        effects=["allow", "verify", "escalate", "block", "redact"],
        params={
            "field": "dotted path, e.g. arguments.amount",
            "unit": "USD | EUR | GBP | JPY | *_CENTS | count | days",
            "bands": "ordered; each has `upto` (inclusive) and an outcome; the last omits `upto`",
        },
        example=(
            "kind: threshold_ladder\n"
            "key: refund-approval\n"
            "tool: payments.refund\n"
            "field: arguments.amount\n"
            "unit: USD\n"
            "bands:\n"
            "  - upto: 10\n"
            "    outcome: allow\n"
            "  - upto: 100\n"
            "    outcome: verify\n"
            "    verify: {check: risk.refund_check, on_fail: escalate}\n"
            "  - outcome: escalate\n"
            "    approver_role: finance"
        ),
        stage="tool_args",
        signals=[
            "under",
            "over",
            "less than",
            "more than",
            "between",
            "threshold",
            "limit",
            "up to",
            "exceeds",
            "auto-approve",
            "tier",
            "band",
        ],
        note="Bands are half-open by construction, so the boundary bug that hand-written "
        "rules produce is not expressible.",
        scenarios=["L4.6"],
    ),
    GuardrailKind(
        id="verification_step",
        name="Verification step",
        intent="require_evidence",
        nature=PROCEDURAL,
        decides="Whether a check passes before the action proceeds.",
        inputs=["a callable check or tool", "a definition of what passing means"],
        effects=["allow", "escalate", "block"],
        params={
            "check": "tool key to invoke",
            "expect": "what the result must satisfy; omitted means truthy",
            "on_fail": "escalate | block | redact",
            "on_error": "what to do when the check itself fails — defaults to escalate",
        },
        example=(
            "verify:\n"
            "  check: risk.refund_check\n"
            "  expect: {risk_score: {op: lt, value: 0.7}}\n"
            "  on_fail: escalate\n"
            "  on_error: escalate"
        ),
        stage="tool_args",
        signals=["validate", "verify", "check with", "confirm", "cross-reference", "look up"],
        note="Fails closed: a check that could not run is not a check that passed.",
    ),
    GuardrailKind(
        id="approval_requirement",
        name="Human approval",
        intent="require_human",
        nature=DETERMINISTIC,
        decides="Whether a named role must approve before the action proceeds.",
        inputs=["an approver role", "a timeout policy"],
        effects=["escalate"],
        params={"approver_role": "role that may approve", "timeout_action": "deny | allow"},
        example="- id: large-transfer\n  effect: escalate\n  when: {tool: payments.transfer}",
        stage="tool_args",
        signals=["approval", "sign-off", "authorise", "human review", "four eyes", "manager"],
        scenarios=["L4.6"],
    ),
    # ---------------------------------------------------------------- disclosure
    GuardrailKind(
        id="entitlement_filter",
        name="Entitlement filter",
        intent="prevent_disclosure",
        nature=DETERMINISTIC,
        decides="Which retrieved content the person asking is allowed to see.",
        inputs=["the end-user principal", "resource grants"],
        effects=["redact", "block"],
        params={"engine": "native | openfga", "default": "deny"},
        example=(
            "agentfox permit user 'hr/*' hr-team --classes pii_sensitive\n"
            "agentfox declare principal alice@acme.com --groups all-staff"
        ),
        stage="retrieval",
        signals=[
            "need to know",
            "entitled",
            "may only see",
            "restricted to",
            "clearance",
            "confidential",
            "role-based",
            "outside",
            "never disclose",
            "not disclose",
            "only staff",
            "only members",
            "salary",
            "hr only",
        ],
        scenarios=["L5.4"],
    ),
    GuardrailKind(
        id="pii_detection",
        name="Personal data detection",
        intent="prevent_disclosure",
        nature=LEXICAL,
        decides="Whether the text carries personal data, and what to do about it.",
        inputs=["text on any surface"],
        effects=["allow", "tokenize", "mask", "redact", "block"],
        params={"entities": "which classes to detect", "redaction": "mask | tokenize"},
        example=(
            "- id: pii-out\n  effect: redact\n"
            "  when: {surface: [output], detection: {entity_prefix: PII}}"
        ),
        stage="output",
        signals=[
            "personal data",
            "pii",
            "gdpr",
            "ssn",
            "card number",
            "customer data",
            "credit card",
            "phone number",
            "email address",
            "date of birth",
            "passport",
            "social security",
            "personally identifiable",
            "personal information",
            "home address",
        ],
        scenarios=["L1.8", "L5.1"],
    ),
    GuardrailKind(
        id="secret_detection",
        name="Credential detection",
        intent="prevent_disclosure",
        nature=LEXICAL,
        decides="Whether a credential is present in text.",
        inputs=["text on any surface"],
        effects=["redact", "block"],
        params={},
        example="- id: secrets\n  effect: block\n  when: {detection: {entity_prefix: SECRET}}",
        stage="output",
        signals=["api key", "credential", "token", "password", "secret"],
        scenarios=["L1.7", "L5.2", "L5.3"],
    ),
    GuardrailKind(
        id="aggregation_floor",
        name="Aggregation k-anonymity",
        intent="prevent_disclosure",
        nature=DETERMINISTIC,
        decides="Whether an aggregate covers enough records to not identify anyone.",
        inputs=["the number of contributing records"],
        effects=["redact", "block", "escalate"],
        params={"k": "minimum contributors, default 5"},
        example="k_anonymity_threshold: 5",
        stage="output",
        signals=["aggregate", "anonymis", "k-anonymity", "small group", "headcount"],
        scenarios=["L5.5"],
    ),
    # ---------------------------------------------------------------- action safety
    GuardrailKind(
        id="action_analysis",
        name="Generated-action analysis",
        intent="prevent_destructive_action",
        nature=DETERMINISTIC,
        decides="What a generated SQL, shell or HTTP artefact would actually do.",
        inputs=["the artefact, in a recognised argument name"],
        effects=["allow", "escalate", "block"],
        params={"dialect": "SQL dialect", "environment": "bound at decision time"},
        example=(
            "- id: no-unbounded-writes\n  effect: block\n  when: {action_risk: 'sql.unbounded_*'}"
        ),
        stage="tool_args",
        signals=[
            "delete",
            "drop",
            "truncate",
            "destructive",
            "production database",
            "blast radius",
            "irreversible",
        ],
        scenarios=["L4.1", "L4.2", "L4.3", "L4.4", "L4.11"],
    ),
    GuardrailKind(
        id="verified_state_precondition",
        name="Verified-state precondition",
        intent="require_evidence",
        nature=DETERMINISTIC,
        decides="Whether the record was read back from the system of record recently enough.",
        inputs=["a state-read token carrying a timestamp"],
        effects=["block"],
        params={"max_age_seconds": "how fresh the read must be"},
        example="grant_capability(..., constraints={'requires_verified_state': True})",
        stage="tool_args",
        signals=[
            "confirm before",
            "re-read",
            "current state",
            "verify the record",
            "stale",
            "up to date",
        ],
        scenarios=["L4.5"],
    ),
    GuardrailKind(
        id="capability_scope",
        name="Tool capability scope",
        intent="prevent_destructive_action",
        nature=DETERMINISTIC,
        decides="Whether this identity may call this tool with these arguments.",
        inputs=["an agent identity", "capability grants"],
        effects=["allow", "escalate", "block"],
        params={
            "actions": "permitted verbs",
            "constraints": "per-argument limits",
            "max_taint": "worst provenance an argument may have",
        },
        example=(
            "grant_capability(session, identity, 'payments.refund', "
            "constraints={'amount': {'lte': 500}})"
        ),
        stage="tool_args",
        signals=["may only call", "allowed to", "not permitted", "scope", "least privilege"],
        scenarios=["L4.6", "L4.7"],
    ),
    # ---------------------------------------------------------------- answer quality
    GuardrailKind(
        id="knowledge_boundary",
        name="Knowledge boundary",
        intent="refuse_to_answer",
        nature=DETERMINISTIC,
        decides="Whether the question is answerable from what this agent can reach.",
        inputs=["a declared boundary: systems, coverage window, question types"],
        effects=["abstain"],
        params={
            "systems_of_record": "[]",
            "coverage_months": "int",
            "answerable_types": "fact | aggregate | prediction | opinion | procedure",
        },
        example="agentfox declare boundary support-triage --systems CRM --answerable fact,aggregate",
        stage="input",
        signals=[
            "do not answer",
            "out of scope",
            "data not available",
            "cannot know",
            "forecast",
            "we don't hold",
        ],
        scenarios=["L5.7", "L0.9"],
    ),
    GuardrailKind(
        id="source_authority",
        name="Source authority and freshness",
        intent="require_evidence",
        nature=DETERMINISTIC,
        decides="Whether the answer came from a source good enough to answer from.",
        inputs=["retrieved chunks carrying a source id", "registered source tiers"],
        effects=["allow", "escalate", "block"],
        params={
            "required_tier": "system_of_record | approved | unverified | external",
            "max_age_hours": "freshness SLA",
        },
        example="agentfox declare source price-book --tier system_of_record --sla-hours 24",
        stage="output",
        signals=[
            "authoritative",
            "system of record",
            "source of truth",
            "up-to-date",
            "approved source",
            "must cite",
        ],
        scenarios=["L2.1", "L2.2", "L2.3"],
    ),
    GuardrailKind(
        id="citation_binding",
        name="Citation binding",
        intent="require_evidence",
        nature=LEXICAL,
        decides="Whether cited documents actually support the claims made.",
        inputs=["retrieved chunks", "citations in the answer"],
        effects=["escalate", "block"],
        params={},
        example="- id: no-fabricated-cites\n  effect: block\n  when: {surface: [output]}",
        stage="output",
        signals=["cite", "reference", "provenance", "attribution", "evidence"],
        scenarios=["L2.4", "L2.5"],
    ),
    GuardrailKind(
        id="numeric_integrity",
        name="Numeric and entity integrity",
        intent="ensure_quality",
        nature=DETERMINISTIC,
        decides="Whether the figures, periods, units and entities are internally consistent.",
        inputs=["the answer; optionally the records and entity list it drew on"],
        effects=["escalate"],
        params={},
        example="assess_integrity(question=..., answer=..., records=..., entities=...)",
        stage="output",
        signals=["reconcile", "must match", "fiscal year", "currency", "rounding", "totals"],
        scenarios=["L5.14", "L5.15", "L5.16", "L5.17", "L0.2", "L0.3"],
    ),
    GuardrailKind(
        id="output_schema",
        name="Output contract",
        intent="ensure_quality",
        nature=DETERMINISTIC,
        decides="Whether the response conforms to the declared shape.",
        inputs=["a JSON schema"],
        effects=["block", "escalate"],
        params={"schema": "JSON Schema subset"},
        example="nom.complete(messages, schema={'type':'object','required':['order_id']})",
        stage="output",
        signals=["must return", "format", "json", "schema", "structure"],
        scenarios=["L0.6", "L0.5"],
    ),
    # ---------------------------------------------------------------- attack
    GuardrailKind(
        id="injection_detection",
        name="Prompt-injection detection",
        intent="detect_attack",
        nature=LEXICAL,
        decides="Whether content is trying to redirect the agent's instructions.",
        inputs=["text, plus its provenance"],
        effects=["allow", "redact", "escalate", "block"],
        params={"min_score": "float", "surfaces": "which surfaces to check"},
        example=(
            "- id: injection\n  effect: block\n"
            "  when: {detection: {entity_prefix: INJECTION}, taint_exceeds: user}"
        ),
        stage="input",
        signals=["injection", "jailbreak", "prompt attack", "override", "untrusted content"],
        scenarios=["L1.1", "L1.2", "L1.3", "L1.4", "L1.5"],
    ),
    GuardrailKind(
        id="taint_ceiling",
        name="Provenance ceiling",
        intent="prevent_destructive_action",
        nature=DETERMINISTIC,
        decides="Whether an argument's origin is trustworthy enough for this tool.",
        inputs=["argument provenance"],
        effects=["escalate", "block"],
        params={"max_taint": "none | user | retrieved | tool_result | subagent | memory"},
        example="grant_capability(..., max_taint='user')",
        stage="tool_args",
        signals=["from the web", "user-supplied", "untrusted", "third-party content"],
        scenarios=["L4.7", "L6.5"],
    ),
    # ---------------------------------------------------------------- process
    GuardrailKind(
        id="escalation_policy",
        name="Escalation conditions",
        intent="require_human",
        nature=LEXICAL,
        decides="When a conversation must be handed to a person.",
        inputs=["recorded conversation turns"],
        effects=["escalate"],
        params={
            "turn_depth": "int",
            "repeated_failure": "int",
            "sentiment_below": "float",
            "regulated_topics": "[]",
            "sla_minutes": "int",
        },
        example="agentfox declare escalation --agent support-triage --turn-depth 6 --sla-minutes 30",
        stage="conversation",
        signals=[
            "escalate",
            "hand off",
            "transfer",
            "human agent",
            "supervisor",
            "complaint",
            "frustrated",
        ],
        scenarios=["L7.1", "L7.2", "L7.3", "L7.4", "L7.5", "L7.6"],
    ),
    GuardrailKind(
        id="spend_budget",
        name="Spend and call budget",
        intent="constrain_spend",
        nature=DETERMINISTIC,
        decides="Whether this agent has any budget left.",
        inputs=["a budget scope with limits"],
        effects=["block"],
        params={
            "max_calls": "int",
            "max_tokens": "int",
            "max_cost_usd": "float",
            "window": "rolling window",
        },
        example="Budget(scope_type='agent', scope_id=..., max_cost_usd=50)",
        stage="input",
        signals=["budget", "spend", "cost", "cap", "quota", "per day", "limit spend"],
        scenarios=["L8.3"],
    ),
    GuardrailKind(
        id="rate_of_change",
        name="Loop and repetition containment",
        intent="constrain_spend",
        nature=DETERMINISTIC,
        decides="Whether the agent is repeating itself without progress.",
        inputs=["the prior tool sequence"],
        effects=["block", "escalate"],
        params={"max_repeats": "int"},
        example="(automatic; prior_tools is carried on every tool call)",
        stage="tool_args",
        signals=["loop", "repeat", "stuck", "runaway"],
        scenarios=["L3.1"],
    ),
    # ---------------------------------------------------------------- structural
    GuardrailKind(
        id="tenant_isolation",
        name="Tenant isolation",
        intent="prevent_disclosure",
        nature=STRUCTURAL,
        decides="Which tenant's data a request may touch. Not configurable by design.",
        inputs=["an authenticated principal"],
        effects=[],
        params={},
        example="(automatic; enforced at the session for every ORM statement)",
        stage="offline",
        signals=["multi-tenant", "customer isolation", "data separation"],
        note="Structural rather than a rule: it cannot be switched off per policy, which "
        "is the point.",
        scenarios=["L9.1"],
    ),
    GuardrailKind(
        id="audit_chain",
        name="Tamper-evident audit",
        intent="ensure_compliance",
        nature=STRUCTURAL,
        decides="Whether the decision record has been altered since it was written.",
        inputs=[],
        effects=[],
        params={"checkpoint_interval": "int"},
        example="(automatic; verify with `agentfox report verify`)",
        stage="offline",
        signals=["audit", "tamper", "immutable", "evidence", "regulator"],
        scenarios=["L9.4", "L9.7"],
    ),
]

BY_ID = {kind.id: kind for kind in CATALOGUE}


def suggest(instruction: str, limit: int = 3) -> list[tuple[GuardrailKind, float]]:
    """Which guardrail kinds a written instruction probably needs.

    Deterministic signal matching, not a model. It is the cheap half of turning prose
    into policy and it is honest about being a starting point — the operator still
    chooses, and a wrong suggestion costs a glance rather than a silent
    misconfiguration. A model-assisted path can layer on top and should still land the
    author in this same review step.
    """
    text = (instruction or "").lower()
    scored: list[tuple[GuardrailKind, float]] = []
    for kind in CATALOGUE:
        hits = [s for s in kind.signals if s in text]
        if not hits:
            continue
        # Longer signals are more specific, so weight by phrase length.
        score = sum(len(s.split()) for s in hits) / (len(kind.signals) or 1)
        scored.append((kind, round(score, 3)))
    scored.sort(key=lambda pair: -pair[1])
    return scored[:limit]


def by_intent(intent: str) -> list[GuardrailKind]:
    return [k for k in CATALOGUE if k.intent == intent]


def inert_kinds() -> list[GuardrailKind]:
    """Kinds that do nothing until the caller supplies something.

    The audit found three complete engines nobody could switch on. Naming them makes
    the dependency visible instead of leaving it to be discovered in production.
    """
    return [k for k in CATALOGUE if k.inputs and k.nature != STRUCTURAL]


def to_json() -> dict[str, Any]:
    return {
        "version": 1,
        "natures": [DETERMINISTIC, LEXICAL, STATISTICAL, PROCEDURAL, STRUCTURAL],
        "intents": list(INTENTS),
        "kinds": [kind.to_json() for kind in CATALOGUE],
    }
