#!/usr/bin/env python3
"""Compute implementation coverage against PRD v3 — do not hand-maintain it.

A status table written by hand drifts within a week and then quietly lies, which is
exactly the failure mode this product exists to prevent elsewhere. So each capability
declares a *probe* against the actual codebase, and the table is regenerated:

    python scripts/coverage.py            # print
    python scripts/coverage.py --write    # regenerate docs/status.md

A probe is deliberately shallow — it proves the capability is wired, not that it is
good. Depth is the test suite's job; this answers "does it exist at all".
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "agentfox"
TESTS = ROOT / "tests"

BUILT, PARTIAL, ABSENT = "built", "partial", "absent"
MARK = {BUILT: "✅", PARTIAL: "◐", ABSENT: "✗"}


@dataclass
class Probe:
    """One capability and how to detect it."""

    id: str
    name: str
    pillar: str
    #: substrings that must all appear somewhere under src/
    needs: list[str] = field(default_factory=list)
    #: if present, capability is at most `partial` until these appear too
    full: list[str] = field(default_factory=list)
    tests: str = ""
    note: str = ""
    #: Restrict the test count to these files. Name-pattern matching runs across every
    #: file under tests/, so a broad alternation quietly attributes other pillars' tests
    #: to this row — "memory", "document" and "retrieval" alone pulled in nineteen. When
    #: a pillar has its own test file, naming it is both accurate and cheaper to keep
    #: right than an ever-growing pattern.
    test_files: tuple[str, ...] = ()


@dataclass
class Mode:
    """One catalogued failure mode and the marker that proves it is addressed.

    The modes in `failure-modes.md` are the honest scorecard: pillars are how we
    organise the build, families are what actually goes wrong in production. A pillar
    can be "built" while the failure it exists to prevent is still uncovered, which is
    why this table is computed separately rather than derived from the pillar rows.
    """

    id: str
    name: str
    #: substrings that must all appear under src/ for this mode to count as covered
    needs: list[str] = field(default_factory=list)
    #: covered but only in part — the marker exists, the mode is not fully addressed
    partial: bool = False
    note: str = ""


FAMILIES: dict[str, tuple[str, list[Mode]]] = {
    "F1": (
        "Answerability & abstention",
        [
            Mode("F1.1", "Answers an unknowable question", ["def classify_answerability"]),
            Mode("F1.2", "Answers outside the coverage window", ["def _temporal_scope"]),
            Mode("F1.3", "Answers for an out-of-scope entity", ["def _entity_scope"]),
            Mode("F1.4", "Prediction presented as record", ["PREDICTION_MARKERS"]),
            Mode("F1.5", "Over-refusal", ["def detect_over_refusal"]),
            Mode("F1.6", "Partial answer presented as complete", ["def completeness_signal"]),
        ],
    ),
    "F2": (
        "Source authority & provenance",
        [
            Mode("F2.1", "Unauthoritative source", ["def source_tier"]),
            Mode("F2.2", "Stale source", ["def freshness_breach"]),
            Mode("F2.3", "Fabricated citation", ["def detect_fabricated_citations"]),
            Mode("F2.4", "Contradictory sources, silent pick", ["def detect_source_conflict"]),
            Mode("F2.5", "Uncited assertion", ["class GroundednessScorer"]),
            Mode("F2.6", "Source outside declared domain", ["def domain_breach"]),
        ],
    ),
    "F3": (
        "Destructive action",
        [
            Mode("F3.1", "Destructive DML", ["sql.unbounded_mutation"]),
            Mode("F3.2", "DDL / schema change", ["sql.destructive_ddl"]),
            Mode("F3.3", "Unbounded blast radius", ["def _is_tautology"]),
            Mode("F3.4", "Wrong environment", ["def environment_risk"]),
            Mode("F3.5", "Comment / stacked-statement evasion", ["sql.stacked_statements"]),
            Mode("F3.6", "Irreversible act on unverified state", ["def _verified_state_gate"]),
            Mode("F3.7", "Duplicate execution on retry", ["def idempotency_key"]),
            Mode("F3.8", "Composed privilege escalation", ["sql.privilege_change"]),
            Mode("F3.9", "Cascading side effects", ["def cascade_risk"]),
            Mode("F3.10", "Partial completion, no rollback", ["def compensation_plan"]),
        ],
    ),
    "F4": (
        "Entitlement & disclosure",
        [
            Mode("F4.1", "Oversharing via retrieval", ["def filter_retrieval"]),
            Mode("F4.2", "Agent identity ≠ user entitlement", ["class EndUserPrincipal"]),
            Mode("F4.3", "Cross-tenant leakage", ["class TenantScoped", "def _tenant_criteria"]),
            Mode("F4.4", "Aggregation disclosure", ["def aggregation_risk"]),
            Mode("F4.5", "Inference disclosure", ["def inference_risk"]),
            Mode("F4.6", "Purpose limitation breach", ["purpose_limitation"]),
            Mode("F4.7", "MNPI / blackout / legal hold", ["RESTRICTED_CLASSES"]),
            Mode(
                "F4.8",
                "Residency violation",
                ["def filter_retrieval", "residency"],
            ),
        ],
    ),
    "F5": (
        "Escalation & resolution",
        [
            Mode("F5.1", "Failed to escalate", ["def detect_missed_escalation"]),
            Mode("F5.2", "Escalated without context", ["def handoff_completeness"]),
            Mode("F5.3", "Loops instead of escalating", ["def _loop_without_handoff"]),
            Mode("F5.4", "Turn-depth degradation", ["def turn_depth_risk"]),
            Mode("F5.5", "False resolution", ["def detect_false_resolution"]),
            Mode("F5.6", "Dropped hand-off", ["def breached_handoffs"]),
            Mode("F5.7", "Sentiment / urgency blindness", ["def sentiment_signal"]),
        ],
    ),
    "F6": (
        "Commitment, advice & liability",
        [
            Mode("F6.1", "Binding commitment", ["def detect_commitments"]),
            Mode(
                "F6.2",
                "Unlicensed advice",
                ["class SafetyLexiconDetector"],
                partial=True,
                note="lexicon only; no licensed-advice classifier",
            ),
            Mode("F6.3", "Missing AI disclosure", ["def disclosure_required"]),
            Mode("F6.4", "Adverse action without reason", ["def adverse_action_risk"]),
            Mode("F6.5", "Discriminatory outcome", ["def fairness_probe"]),
            Mode("F6.6", "Decision not recorded", ["class Decision"]),
        ],
    ),
    "F7": (
        "Numeric, temporal & entity integrity",
        [
            Mode("F7.1", "Hallucinated record match", ["def detect_unmatched_records"]),
            Mode("F7.2", "Arithmetic / aggregation error", ["def check_arithmetic"]),
            Mode("F7.3", "Wrong period", ["def detect_period_mismatch"]),
            Mode("F7.4", "Unit / currency error", ["def detect_unit_mismatch"]),
            Mode("F7.5", "Entity confusion", ["def detect_entity_confusion"]),
            Mode("F7.6", "Timezone error", ["def detect_timezone_ambiguity"]),
            Mode("F7.7", "Self-contradiction across turns", ["class SelfConsistencyScorer"]),
        ],
    ),
    "F8": (
        "Context & retrieval integrity",
        [
            # These markers were named when the PRD was written and no longer match
            # the implementations, which are in `context_integrity`. Pointing them at
            # the real functions is the difference between a scorecard that measures
            # the product and one that measures a naming convention.
            Mode("F8.1", "Incoherent chunks", ["def chunk_quality"]),
            # Decoder and tokeniser damage is detected where it leaves a trace — U+FFFD,
            # [UNK], latin-1 mojibake. A tokeniser that segments Thai or Khmer badly
            # without emitting any of those is not detected, so this is partial.
            Mode("F8.2", "Tokeniser / script boundary failures", ["_UNKNOWN_TOKEN"], partial=True),
            Mode("F8.3", "Stale index", ["def index_freshness"]),
            Mode("F8.4", "Context-window truncation", ["def assemble_context"]),
            Mode("F8.5", "Memory contamination", ["def memory_binding_breach"]),
            Mode("F8.6", "Retrieval quality drift", ["def retrieval_drift"]),
            Mode("F8.7", "Ingestion corruption", ["def document_quality"]),
        ],
    ),
}


def _src_text() -> str:
    return "\n".join(p.read_text(errors="ignore") for p in SRC.rglob("*.py"))


def _count_tests(pattern: str, files: tuple[str, ...] = ()) -> int:
    if files:
        # Whole-file scoping: every test in a pillar's own file counts, and no test
        # outside it does.
        return sum(
            len(re.findall(r"def test_\w+", (TESTS / name).read_text(errors="ignore")))
            for name in files
            if (TESTS / name).exists()
        )
    if not pattern:
        return 0
    total = 0
    for path in TESTS.rglob("test_*.py"):
        body = path.read_text(errors="ignore")
        # The group around `pattern` is load-bearing: without it an alternation binds
        # looser than the `test_` prefix and every branch after the first is silently
        # missed, which understated half the table.
        total += len(re.findall(rf"def test_\w*(?:{pattern})\w*", body))
    return total


PROBES: list[Probe] = [
    # --- Layer A: Know
    Probe(
        "P1",
        "Registry, shadow discovery, observed lineage",
        "1 Registry",
        ["def observe_agent", "def detect_shadow_agents", "def derive_lineage"],
        ["def sync_connector"],
        "shadow|lineage|inventory",
        "connector-based estate discovery (P1-8) absent",
    ),
    Probe(
        "P1-9",
        "Continuous monitoring of connected sources",
        "1 Registry",
        ["def diff_repo", "def diff_api", "def fetch_tools", "def run_monitor", "def reconcile"],
        ["def queue_finding_alert", "def verify_signature"],
        "",
        "re-checks connected GitHub repositories (on a schedule and on a signed push "
        "webhook), hosted-API specs and remote MCP servers, raises findings from the "
        "difference between runs and closes them when they clear, and alerts to Slack and "
        "the finding webhook. GitHub is the only code host; there is no PagerDuty or "
        "email channel; each job runs a bounded batch of due monitors",
        test_files=(
            "monitoring/test_monitor_runs.py",
            "monitoring/test_monitor_routes.py",
            "monitoring/test_monitor_schema.py",
            "monitoring/test_snapshots.py",
            "cli/test_monitor_cli.py",
        ),
    ),
    Probe(
        "P12",
        "Hierarchical policy, override semantics, lint",
        "12 Policy Composition",
        [
            "class PolicyDocument",
            "def resolve_effective",
            "def lint_policy",
            # One loader turns a stored version into a document, so the runtime and
            # every read-only view agree on what an unloadable version means.
            "def load_version_document",
        ],
        ["def canary_rollout"],
        "policy|hierarchy",
        "non-developer authoring (P12-7) absent",
    ),
    # --- Layer B: Constrain
    Probe(
        "P2",
        "NHI, least privilege, delegation narrowing, approvals",
        "2 Identity",
        ["def check_capability", "def delegate", "def request_approval", "def redeem_approval"],
        ["def link_external_identity"],
        "capability|delegation|approval",
        "an approved retry is redeemed once, for the same agent, tool and arguments. No "
        "live IdP: Entra/Okta integration (P2-8) absent",
    ),
    Probe(
        "P3",
        "Runtime detectors across nine surfaces + taint",
        "3 Guardrails",
        [
            "class InjectionHeuristicDetector",
            "class NativePiiDetector",
            "class SecretsDetector",
            "class TaintTracker",
            "def explain",
            "class LatencyLedger",
            "def record_feedback",
        ],
        ["class GraniteGuardianDetector"],
        "injection|pii|secret|taint|explain|ledger|suppress|precision|latency",
        "model-based detectors wired but need an opt-in weights download",
    ),
    Probe(
        "P9",
        "Action semantics, blast radius, verified-state preconditions",
        "9 Action Assurance",
        [
            "def analyse_sql",
            "class ActionAnalysis",
            "def _verified_state_gate",
            "def idempotency_key",
            "def compensation_plan",
            "def cascade_risk",
        ],
        [],
        "action|blast_radius|destructive|tautolog|unbounded|verified_state|dry_run|"
        "idempotency|compensation|cascade|duplicate|irreversible|effect",
        "cascade analysis is exactly as good as the trigger declarations it is given — "
        "an undeclared webhook stays invisible, and shell analysis remains a deny-list "
        "rather than a parser",
    ),
    Probe(
        "P10",
        "End-user principal, retrieval entitlement filtering",
        "10 Entitlement",
        [
            "class EndUserPrincipal",
            "def filter_retrieval",
            "def over_permission_report",
            "def aggregation_risk",
        ],
        ["def _openfga_list_objects"],
        "entitlement|principal|overshar|disclos|aggregation|inference|clearance",
        "OpenFGA adapter is a declared seam, not an implementation",
    ),
    # --- Layer C: Ground
    Probe(
        "P7",
        "Knowledge boundary, forced abstention",
        "7 Answerability",
        [
            "class KnowledgeBoundary",
            "def classify_answerability",
            "def detect_over_refusal",
            "def verify_boundary",
        ],
        [],
        "answerab|abstain|boundary|refus|completeness|question_type|coverage_window",
    ),
    Probe(
        "P8",
        "Source tiers, freshness, citation binding",
        "8 Provenance",
        [
            "def groundedness",
            "class SourceRecord",
            "def detect_fabricated_citations",
            "def freshness_breach",
        ],
        ["def ingest_catalog"],
        "groundedness|provenance|citation|source|freshness|tier|conflict",
        "catalog ingestion (P8-9: DataHub/OpenMetadata/Unity) absent",
    ),
    Probe(
        "P14",
        "Ingestion and retrieval quality gates",
        "14 Context Integrity",
        [
            "def chunk_quality",
            "def document_quality",
            "def assemble_context",
            "def retrieval_drift",
            "def memory_binding_breach",
        ],
        [],
        "",
        "gates the ingestion and assembly path. Semantic chunk-boundary repair and "
        "automatic re-extraction of a corrupt document are not built — a finding is "
        "reported and the decision to drop the document belongs to the operator",
        test_files=("grounding/test_context_integrity.py",),
    ),
    # --- Layer D: Judge
    Probe(
        "P4",
        "Eval runner, CI gating, drift, silent failure, red team",
        "4 Evaluation",
        ["def gate", "class SilentFailureScorer", "def compute", "def run_campaign"],
        ["def score_sample", "class ModelGroundednessScorer", "def annotation_queue"],
        "gate|silent_failure|drift|campaign|groundedness|ragas",
        "Ragas scorers (I-8) and model-based groundedness (via ModelProvider.judge()) "
        "run from the runner alongside the lexical scorer, and a gate fails on an errored "
        "case rather than skipping it. Red-team probe calls leave no decisions or "
        "findings in the production tables. An annotation queue for human review of "
        "borderline eval "
        "results is not built",
    ),
    Probe(
        "P4-13",
        "Live probing of deployed agents (P4-13) and the public showcase (P4-14)",
        "4 Evaluation",
        ["class LiveProbe", "def opt_in", "def signals_for", "def run_target"],
        ["def public_summary"],
        "",
        "sends a fixed probe library to an agent's own endpoint only after a recorded "
        "opt-in, scores it on observed behaviour (a reversed canary, forbidden tools, leak "
        "markers) and opens a finding when a contained attack escapes. The probe set is "
        "fixed rather than adaptive, and an http target must speak the small JSON contract "
        "the adapter sends. The public showcase is off unless AGENTFOX_SHOWCASE_ENABLED is set",
        test_files=(
            "evaluation/test_live_probes.py",
            "gateway/test_probes_and_showcase.py",
            "monitoring/test_deployed_agent_monitor.py",
        ),
    ),
    Probe(
        "P13",
        "Failure attribution across handoffs",
        "13 Failure Attribution",
        ["def attribute", "def handoff_fidelity", "def goal_drift", "def delegation_graph"],
        [],
        "",
        "attributes a failure to the step that originated the value and measures what "
        "each handoff dropped. Both work on constraints that were written down — an "
        "expectation the human held and never typed is invisible here, and no trace "
        "analysis recovers it",
        test_files=("prove/test_attribution.py",),
    ),
    Probe(
        "P11",
        "Escalation policy and missed-escalation detection",
        "11 Escalation",
        [
            "def request_approval",
            "def detect_missed_escalation",
            "def handoff_completeness",
            "def detect_false_resolution",
            "def breached_handoffs",
        ],
        [],
        "escalation|handoff|missed_escalation|false_resolution|sentiment|abstention|turn_depth",
    ),
    # --- Layer E: Prove
    Probe(
        "P5",
        "Traces, hash chain, evidence packages, SIEM",
        "5 Audit",
        ["def verify", "def build", "def to_cef", "def full_trace"],
        [],
        "chain|evidence|trace|siem",
    ),
    Probe(
        "P6",
        "Control catalog, computed status, risk, obligations",
        "6 Compliance",
        ["def compute_all", "def sync_catalog", "def obligation_calendar"],
        ["def dynamic_risk_score", "class Assessment"],
        "control|framework|compliance|risk",
        "dynamic risk scoring and workflow engine absent (Gartner criteria)",
    ),
    # --- Cross-cutting
    Probe(
        "P15",
        "Circuit breaker, fallback, caps, backpressure",
        "15 Cost & Reliability",
        ["class CircuitBreaker", "class FallbackLadder", "def check_budget"],
        ["def get_admission_controller", "def admission_gate"],
        "reliability|breaker|budget|admission|admit|shed",
        "AdmissionController (P15-6) was fully built and tested but had zero callers "
        "on the live request path; a gateway middleware now gates every /v1/* request "
        "through it before routing, shedding by priority under saturation and leaving "
        "the /api/* control plane out of scope for the same budget. Caps elsewhere "
        "(budgets, breaker thresholds) remain hard stops, not queued backpressure",
    ),
    # --- Platform
    Probe(
        "PL-1",
        "Streaming with inline enforcement",
        "Platform",
        ["def run_completion_stream", "class StreamChunk", "def _stream_openai"],
        [],
        "stream",
    ),
    Probe(
        "PL-2",
        "Database migrations",
        "Platform",
        ["def upgrade_db", "def current_revision"],
        [],
        "migration",
    ),
    Probe(
        "PL-3",
        "Kill switch and quarantine",
        "Platform",
        ["class AgentControl", "def _control_verdict"],
        [],
        "kill|quarantine|control_",
    ),
    Probe(
        "PL-4",
        "Agent loop governance",
        "Platform",
        ["def govern_loop", "class LoopGovernor"],
        [],
        "",
        "governs the run rather than the step: identical re-issued calls, alternating "
        "cycles, and steps producing no new observation. All three are visible without "
        "understanding the task, which is what keeps it deterministic — an agent that "
        "is wrong but varied still looks like an agent working",
        test_files=("runtime/test_platform_runtime.py",),
    ),
    Probe(
        "PL-5",
        "Async workers",
        "Platform",
        ["class JobQueue", "def run_pending", "def enqueue_due", "def recover_stuck"],
        [],
        "",
        "a database-backed queue with retries, backoff, stuck-job recovery and a dead "
        "letter that is public state rather than a log line, filled by per-tenant "
        "schedules and drained by a cron call (Vercel cron, a 30-minute GitHub Actions "
        "runner, or `agentfox admin jobs run-due`). Each drain runs in the calling "
        "process; a Redis or SQS worker belongs behind the same interface and is not built",
        test_files=("jobs/test_scheduler_and_jobs.py",),
    ),
    Probe(
        "PL-6",
        "HA-ready persistence",
        "Platform",
        ["def configure_pool"],
        [],
        "",
        "pooling and pre-ping ship, and SQLite is refused at startup for a multi-worker "
        "deployment rather than surfacing as intermittent latency. Actual scale-out "
        "under load is still untested",
    ),
    Probe(
        "PL-7",
        "Service-level fail-open",
        "Platform",
        ["def service_fallback", "class FailPolicy", "class AdmissionController"],
        [],
        "",
        "fail-open is legitimate and must be visible, bounded and impossible for some "
        "controls. Admission control sheds work rather than governance. What is not "
        "built: distributed state, so the fail-open budget and the rate limit are "
        "per-process and a multi-worker deployment gets N times the declared budget",
        test_files=("runtime/test_availability.py",),
    ),
    # --- Integrations
    # --- Adoption surface: the reason any of the above gets installed at all.
    Probe(
        "PL-9",
        "Authentication and operator tokens",
        "Platform",
        [
            "def authenticate",
            "def issue_token",
            "def header_identity_allowed",
            "def assert_production_secrets",
        ],
        ["def resolve_oidc"],
        "auth|token|credential|header_identity|production_refuses|logout|first_operator",
        "API tokens, the dev-mode gate, a refusal to start outside development on published "
        "secrets, sign-out that revokes the token and a first operator created from the CLI "
        "ship. OIDC/SCIM absent",
    ),
    Probe(
        "P18",
        "Semantic contract: data access, result fidelity, register, source arbitration",
        "18 Tool Contract",
        [
            "def analyse_access",
            "def answers_request",
            "def check_register",
            "def arbitrate",
            "class ConfirmationStep",
        ],
        [],
        "",
        "governs the gap between the request, the rows a tool touched and the answer. "
        "Data-access scoping is exactly as good as the ScopeRule declarations it is "
        "given — an undeclared table is reported, never assumed safe. Register checks "
        "are lexical and licensed per domain; they judge standing, not content, and a "
        "licensed operator turns them off deliberately",
        test_files=(
            "containment/test_data_access.py",
            "grounding/test_tool_contract.py",
            "grounding/test_register.py",
            "grounding/test_arbitration.py",
        ),
    ),
    Probe(
        "PL-10",
        "Operator actions recorded in the decision chain",
        "Platform",
        ["PRIVILEGED", "def unaudited", "class ReasonRequired"],
        ["SYSTEM_ORG_ID", "class NotInSystemScope"],
        "",
        "the registry of privileged operations is declared and the check is structural, "
        "so a new operator surface without an audit call fails the suite. system_scope's "
        "cross-tenant operations now land somewhere real: resolving a token's own org "
        "before recording (system_log.py, chain.append's org_id) fixed a live "
        "misattribution — issuing/revoking a token used to record into whichever tenant "
        "the session defaulted to, with its seq computed from a query system_scope had "
        "left unfiltered — and the one operation with no tenant to attribute to at all "
        "(listing tokens across every org) now writes to a dedicated system-level chain. "
        "The registry that makes operator actions structural has no equivalent yet for "
        "which system_scope call sites must write to that chain — this one is wired by "
        "hand, not enforced by an import-time check",
        test_files=("prove/test_operator_log.py", "prove/test_system_log.py"),
    ),
    Probe(
        "PL-8",
        "Tenant isolation enforced at the session",
        "Platform",
        ["class TenantScoped", "def _tenant_criteria", "def system_scope"],
        [],
        "tenant|tenancy|cross_tenant|isolat",
    ),
    Probe(
        "X-1",
        "One-line auto-instrumentation",
        "Adoption",
        ["def auto", "def _patch_openai", "def _patch_anthropic"],
        ["def _patch_langchain", "def _patch_litellm"],
        "auto|autoguard|one_liner|untouched_app|patch",
    ),
    Probe(
        "X-2",
        "Static repo discovery and zero-effort CLI",
        "Adoption",
        ["def scan_file", "def check", "def doctor"],
        [],
        "scan|discovery|doctor|init_is_idempotent|quickstart|ungoverned",
    ),
    Probe(
        "P16",
        "Business-process guardrails and the guardrail catalogue",
        "16 Business rules",
        [
            "class Ladder",
            "def find_conflicts",
            "def run_verification",
            "CATALOGUE",
            "def compile_document",
            "_EXTRACTORS",
        ],
        ["def compile_with_model"],
        "ladder|band|business|catalogue|guardrail_kind|conflict|verification|compil",
        "policy compilation is deterministic: 86% of a tuned document and 64% of a "
        "held-out one compile with no question. Prose with no parseable structure "
        '("be courteous") is reported as inexpressible rather than guessed at; a '
        "model-assisted path for those sentences is not built",
    ),
    Probe(
        "X-4",
        "Protective controls reachable without writing code",
        "Adoption",
        ["def boundary_set", "def sources_add", "def escalation_set", "def _record_turn"],
        [],
        "reachab|boundary_can_be|corpus_can_be|one_liner_captures|protective_control",
    ),
    Probe(
        "X-3",
        "Control-plane onboarding and attention-first home",
        "Adoption",
        ["def onboarding", "def attention"],
        [],
        "checklist|attention|connected|onboarding",
    ),
    Probe(
        "I-1",
        "LangGraph-native SDK",
        "Integration",
        ["class AgentFoxGuard"],
        [],
        "langgraph|guard_",
    ),
    Probe(
        "I-2",
        "MCP inline governance",
        "Integration",
        ["def scan_mcp_server", "class McpGovernor", "def _check_drift"],
        [],
        "mcp|drift|undeclared|poison",
    ),
    Probe(
        "I-3",
        "FastAPI middleware and dependency",
        "Integration",
        ["class AgentFoxMiddleware", "def guard", "def install"],
        [],
        "fastapi|middleware|dependency_governs|one_line_install|governed_route",
    ),
    Probe(
        "I-4",
        "LangSmith correlation",
        "Integration",
        ["def refs_from_headers", "def _push_langsmith", "def resolve_external"],
        [],
        "correlat|langsmith|traceparent",
    ),
    Probe("I-5", "OpenTelemetry", "Integration", ["def ingest_otlp"], [], "otlp"),
    Probe(
        "I-6",
        "Langfuse correlation",
        "Integration",
        ["def link_trace", "def _push_langfuse", "def deep_link"],
        [],
        "correlat|langfuse|reverse_lookup",
    ),
    Probe(
        "I-7",
        "Prometheus export",
        "Integration",
        ["def render_metrics"],
        ["def push_to_gateway"],
        "metric|prometheus|scrape|observe_mode_is_reported",
    ),
    Probe(
        "I-8",
        "Ragas scorer adapter",
        "Integration",
        ["class RagasSample", "def score_dataset", "def ragas_available"],
        [],
        "ragas|faithfulness|vocabulary|implementation|dataset_report",
    ),
    Probe(
        "I-10",
        "LiteLLM routing",
        "Integration",
        ["class LiteLLMProvider"],
        [],
        "litellm",
    ),
    Probe(
        "I-11",
        "Azure / Bedrock / Vertex providers",
        "Integration",
        ["class BedrockProvider", "class AzureOpenAIProvider", "class VertexProvider"],
        [],
        "azure|bedrock|vertex|enterprise_provider|system_prompts_are_lifted",
    ),
]


def evaluate(probe: Probe, blob: str) -> tuple[str, int]:
    tests = _count_tests(probe.tests, probe.test_files)
    if not probe.needs or not all(n in blob for n in probe.needs):
        return ABSENT, tests
    if probe.full and not all(n in blob for n in probe.full):
        return PARTIAL, tests
    if probe.note and not probe.full:
        return PARTIAL, tests
    return BUILT, tests


def evasion_score_line() -> str:
    """Measured recall against the adversarial corpus, not asserted.

    A detector's quality is the one thing a probe genuinely cannot see — `grep` finds
    the class, not whether it works — so this runs the corpus.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from agentfox.detection import all_detectors
        from agentfox.detection.base import DetectionContext
        from tests.corpus.injection import ATTACKS, BENIGN

        detector = all_detectors()["injection.heuristic"]
        context = DetectionContext(surface="tool_result", taint_source="tool_result")

        def fires(text: str) -> bool:
            return bool(detector.detect(text, context).detections)

        caught = sum(1 for case in ATTACKS if fires(case.text))
        false_positives = sum(1 for case in BENIGN if fires(case.text))
        return (
            f"| **Injection recall, regression corpus** | **{caught / len(ATTACKS):.0%}** — "
            f"{caught}/{len(ATTACKS)} adversarial, {false_positives} false positive(s) on "
            f"{len(BENIGN)} benign. Our own test strings, so a regression check, not a recall "
            f"estimate; held-out and external numbers are in benchmarks/REPORT.md |"
        )
    except Exception as exc:  # pragma: no cover - reporting must not break the report
        return f"| **Injection recall, regression corpus** | not measured ({exc}) |"


def family_rows(blob: str) -> tuple[list[str], int, int, int]:
    """Score the 50 catalogued failure modes. This is the scorecard that matters."""
    rows: list[str] = []
    covered = partial = total = 0
    for key, (title, modes) in FAMILIES.items():
        hit = [m for m in modes if all(n in blob for n in m.needs)]
        full = [m for m in hit if not m.partial]
        part = [m for m in hit if m.partial]
        covered += len(full)
        partial += len(part)
        total += len(modes)
        missing = [m.id for m in modes if m not in hit]
        score = len(full) + 0.5 * len(part)
        mark = MARK[BUILT] if score == len(modes) else MARK[PARTIAL] if score else MARK[ABSENT]
        rows.append(
            f"| **{key}** {title} | {len(modes)} | {len(full)} | {len(part)} | "
            f"{mark} {score:g}/{len(modes)} | {', '.join(missing) or '—'} |"
        )
    return rows, covered, partial, total


def render() -> str:
    blob = _src_text()
    rows, tally = [], {BUILT: 0, PARTIAL: 0, ABSENT: 0}
    partial_ids, absent_ids = [], []
    for probe in PROBES:
        status, tests = evaluate(probe, blob)
        tally[status] += 1
        if status == PARTIAL:
            partial_ids.append(probe.id)
        elif status == ABSENT:
            absent_ids.append(probe.id)
        rows.append(
            f"| `{probe.id}` | {probe.pillar} | {probe.name} | {MARK[status]} {status} | "
            f"{tests or '—'} | {probe.note or ''} |"
        )

    total = sum(tally.values())
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout
        collected = re.search(r"(\d+) tests? collected", out)
        test_total = collected.group(1) if collected else "?"
    except Exception:
        test_total = "?"

    loc = sum(
        len(p.read_text(errors="ignore").splitlines())
        for p in list(SRC.rglob("*.py")) + list(TESTS.rglob("*.py"))
    )

    pct = round(100 * (tally[BUILT] + 0.5 * tally[PARTIAL]) / total)
    frows, fcovered, fpartial, ftotal = family_rows(blob)
    evasion = evasion_score_line()
    fpct = round(100 * (fcovered + 0.5 * fpartial) / ftotal)

    if absent_ids:
        gaps = (
            f"**Reading the gaps.** Absent rows are not oversights — they are the PRD v3 "
            f"roadmap not yet started: {', '.join(f'`{i}`' for i in absent_ids)}. Partial "
            f"rows ({', '.join(f'`{i}`' for i in partial_ids)}) have a real, tested "
            f"foundation with a specific, named piece left — see each row's note."
        )
    else:
        gaps = (
            f"**Reading the gaps.** Nothing is untouched — every tracked capability has at "
            f"least a foundation. What remains is {len(partial_ids)} partial capabilities, "
            f"each with a specific, named piece left rather than a blank slate: "
            f"{', '.join(f'`{i}`' for i in partial_ids)}. See each row's note for what that "
            f"piece is."
        )
    return f"""# Implementation status

**Generated by `python scripts/coverage.py --write` — do not edit by hand.**

A hand-written status table drifts within a week and then quietly lies. Each row below
is a probe against the actual codebase, so this file cannot claim something that is not
there. Probes are shallow by design: they prove a capability is *wired*, not that it is
*good*. Depth is the test suite's job.

| | |
|---|---|
| **Capabilities** | {total} tracked |
| **Built** | {tally[BUILT]} ✅ |
| **Partial** | {tally[PARTIAL]} ◐ |
| **Absent** | {tally[ABSENT]} ✗ |
| **Weighted coverage** | **{pct}%** *(partial counts half)* |
| **Tests** | {test_total} |
| **Lines** | {loc:,} (src + tests) |
| **Failure modes covered** | **{fpct}%** — {fcovered} of {ftotal} outright, {fpartial} partial |
{evasion}

Requirement detail lives in [the PRD](design/PRD.md); requirement→test mapping
in [design/traceability.md](design/traceability.md).

| ID | Pillar | Capability | Status | Tests | Note |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## Failure-family coverage

Pillars are how the build is organised; **families are what actually goes wrong in
production**. A pillar can read "built" while the failure it exists to prevent is still
uncovered, so this table is computed independently rather than derived from the rows
above. The modes come from [design/failure-modes.md](design/failure-modes.md).

| Family | Modes | Covered | Partial | Score | Not yet covered |
|---|---|---|---|---|---|
{chr(10).join(frows)}

{gaps}
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    body = render()
    if args.write:
        (ROOT / "docs" / "status.md").write_text(body)
        print("wrote docs/status.md")
    else:
        print(body)
