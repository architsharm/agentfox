"""Persistence model for all six pillars.

Implements Appendix D. Three invariants are enforced here in code rather than by
convention, because they are the ones an auditor tests:

  * ``AuditEntry`` is append-only and hash-chained (P5-2). There is no update or
    delete path anywhere in the codebase.
  * ``PolicyVersion`` is immutable; every ``Decision`` binds the exact version in
    force at decision time (X-4).
  * ``Capability`` narrowing on delegation is validated at write time, not audited
    after the fact (P2-5).

The models live in one module per pillar; this package is their single import
point, so ``from agentfox.core.models import Agent`` names every table the same
way wherever it is defined:

* ``base``        — ``Base``, the tenancy mixins and the tenant-isolation check
* ``registry``    — Pillar 1, discovery and the agent registry
* ``identity``    — Pillar 2, identity, access and authorization
* ``guardrails``  — Pillar 3, runtime guardrails
* ``evaluation``  — Pillar 4, evaluation and reliability
* ``audit``       — Pillar 5, audit, observability and traceability
* ``policy``      — Pillar 6, policy and compliance
* ``improvement`` — the governed improvement loop
* ``public``      — the playground and the waitlist, at the edge of the tenant model
"""

from __future__ import annotations

from agentfox.core.models.audit import (
    AuditCheckpoint,
    AuditEntry,
    EvidencePackage,
    Job,
    LegalHold,
    RetentionPolicy,
    Span,
    Trace,
    TraceLink,
)
from agentfox.core.models.base import (
    TENANT_EXEMPT_TABLES,
    Base,
    TenantExempt,
    TenantScoped,
    TimestampMixin,
    _assert_every_model_is_tenant_scoped,
    _is_exempt,
    as_aware,
    utcnow,
)
from agentfox.core.models.evaluation import (
    SLO,
    Baseline,
    DriftWindow,
    EvalAnnotation,
    EvalCase,
    EvalResult,
    EvalRun,
    EvalSuite,
    RedTeamCampaign,
    RedTeamFinding,
)
from agentfox.core.models.guardrails import (
    AgentMessageLog,
    AgentSigningKey,
    Budget,
    BusinessRule,
    ConversationTurn,
    DetectionFinding,
    DetectorRun,
    DisclosureEvent,
    EndUserPrincipal,
    EscalationPolicy,
    GuardrailFeedback,
    Handoff,
    JudgmentPosture,
    KnowledgeBoundary,
    MemoryEntry,
    ResourceGrant,
    SourceConnection,
    SourceRecord,
    Suppression,
    TaintTag,
)
from agentfox.core.models.identity import (
    AccessScopeRule,
    ApiToken,
    ApprovalRequest,
    Capability,
    Credential,
    DelegationEdge,
    GithubConnection,
    Identity,
    ScanRun,
    User,
)
from agentfox.core.models.improvement import (
    PROPOSAL_OPEN_FINGERPRINT,
    ChangeProposal,
    JobSchedule,
)
from agentfox.core.models.policy import (
    Control,
    ControlStatus,
    Decision,
    FrameworkMapping,
    Obligation,
    Policy,
    PolicyBinding,
    PolicyCanary,
    PolicyVersion,
    RiskAssessment,
    SimulationRun,
)
from agentfox.core.models.public import (
    PlaygroundSandbox,
    WaitlistSignup,
)
from agentfox.core.models.registry import (
    OUTPUT_TRUST_LEVELS,
    Agent,
    AgentControl,
    Finding,
    LineageEdge,
    McpServer,
    McpToolSnapshot,
    Tool,
)

__all__ = [
    "AccessScopeRule",
    "Agent",
    "AgentControl",
    "AgentMessageLog",
    "AgentSigningKey",
    "ApiToken",
    "ApprovalRequest",
    "AuditCheckpoint",
    "AuditEntry",
    "Base",
    "Baseline",
    "Budget",
    "BusinessRule",
    "Capability",
    "ChangeProposal",
    "Control",
    "ControlStatus",
    "ConversationTurn",
    "Credential",
    "Decision",
    "DelegationEdge",
    "DetectionFinding",
    "DetectorRun",
    "DisclosureEvent",
    "DriftWindow",
    "EndUserPrincipal",
    "EscalationPolicy",
    "EvalAnnotation",
    "EvalCase",
    "EvalResult",
    "EvalRun",
    "EvalSuite",
    "EvidencePackage",
    "Finding",
    "FrameworkMapping",
    "GithubConnection",
    "GuardrailFeedback",
    "Handoff",
    "Identity",
    "Job",
    "JobSchedule",
    "JudgmentPosture",
    "KnowledgeBoundary",
    "LegalHold",
    "LineageEdge",
    "McpServer",
    "McpToolSnapshot",
    "MemoryEntry",
    "OUTPUT_TRUST_LEVELS",
    "Obligation",
    "PROPOSAL_OPEN_FINGERPRINT",
    "PlaygroundSandbox",
    "Policy",
    "PolicyBinding",
    "PolicyCanary",
    "PolicyVersion",
    "RedTeamCampaign",
    "RedTeamFinding",
    "ResourceGrant",
    "RetentionPolicy",
    "RiskAssessment",
    "SLO",
    "ScanRun",
    "SimulationRun",
    "SourceConnection",
    "SourceRecord",
    "Span",
    "Suppression",
    "TENANT_EXEMPT_TABLES",
    "TaintTag",
    "TenantExempt",
    "TenantScoped",
    "TimestampMixin",
    "Tool",
    "Trace",
    "TraceLink",
    "User",
    "WaitlistSignup",
    "_is_exempt",
    "as_aware",
    "utcnow",
]

# Every model module is imported above, so the registry is complete: fail the import
# if any of them escapes tenant isolation.
_assert_every_model_is_tenant_scoped()
