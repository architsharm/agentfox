# Low-Level Design (LLD)

**Companion to [docs/hld.md](hld.md).** Where the HLD explains the shape of the system, this
document explains the pieces: module inventory, key classes and methods, the data model, the
API surface, and the internals of the four subsystems most worth understanding in depth
(the enforcer, the detector pipeline, the policy engine, the audit chain). All line counts
and file paths verified against the repository on 2026-09-04; treat any that drift as a cue to
re-run the same `wc -l` / `grep` pass rather than trust this document blindly.

---

## 1. Module inventory — `src/agentfox/`

The package is 14,895 lines split between ~40 flat root modules and 14 subpackages. It is
*not* organized with everything nested under subpackages — several of the largest, most
central modules live at the package root.

### 1.1 Root modules (selected, by size)

| Module | Lines | Responsibility |
|---|---|---|
| `enforcement.py` | 2440 | The `Enforcer` class — every governed surface (gateway, SDK, LangGraph guard) calls into this. See §3. |
| `models.py` | 1490 | SQLAlchemy 2.0 ORM — every persisted entity in the system. See §5. |
| `escalation.py` | 821 | Human hand-off: approval requests, timeout policy, owner/SLA routing (Pillar 11). |
| `autoguard.py` | 793 | `agentfox.auto()` monkey-patch machinery. See §7. |
| `seed.py` | 648 | Demo/offline seed data — agents, policies, controls, obligations, scripted provider replies. |
| `context_integrity.py` | 609 | Pillar 14 — chunk-boundary and retrieval-corruption detection. Wired into `finding.py` and `gateway/routes/provenance.py`. |
| `answerability.py` | 603 | Pillar 7 — knowledge-boundary declaration and pre-generation abstention gate. |
| `provenance.py` | 560 | Pillar 8 — source-authority binding for retrieved content. |
| `attribution.py` | 538 | Pillar 13 — failure attribution across a multi-step/multi-agent execution. |
| `discovery.py` | 524 | Pillar 1 — repo/config-based agent and tool discovery (`agentfox check`). |
| `commitments.py` | 496 | Pillar F6 — commitment/advice/liability-language detection. |
| `entitlement.py` | 464 | Pillar 10 — end-user principal → visible-resource resolution. |
| `effects.py` | 461 | Side-effect / irreversibility classification for tool calls. |
| `integrity.py` / `availability.py` | 427 / 427 | Numeric/temporal/entity integrity checks; admission control + rate limiting (Pillar 15). |
| `data_access.py` | 384 | Data-access scope declarations (Pillar 10 companion). |
| `reliability.py` | 340 | Circuit breaker / fallback around provider calls. |
| `arbitration.py` | 309 | Multi-source conflict resolution (which of several retrieved facts wins). |
| `register.py` | 281 | Compliance risk register (`agentfox compliance risk` — distinct from `commitments.py`'s commitment register; don't conflate the two when reading call sites). |
| `tenancy.py` | 270 | Multi-tenant isolation — session-level `with_loader_criteria` enforcement, not per-query filtering. |
| `tool_contract.py` | 264 | Pillar 18 — semantic tool-contract governance (data access, result fidelity, source arbitration). |
| `config.py` / `db.py` | 259 / 225 | Settings (env-var driven) and engine/session setup. |
| `agent_loop.py` | 222 | Pillar 15 (PL-4) — `LoopGovernor`: alternating-cycle and stalled-run detection across a multi-turn tool-calling loop. Called from `enforcement.py:2367`. As of 2026-09-04, actively being extended (uncommitted diff) to accept a full step-history (`prior_steps`) from callers, not just a per-tool repeat count. |
| `jobs.py` | 178 | Async job-queue interface. **Zero callers outside itself and tests as of 2026-09-04** — a genuinely stub-only module (built, tested, not wired to anything on a live path). |
| `system_log.py` / `operator_log.py` | 132 / 218 | Structured operator-action logging (distinct from the audit chain — these are operational logs, not the tamper-evident record). |
| `session_scan.py` | 124 | `agentfox quickscan`'s local AI-tool-session transcript scan. |
| `ids.py` / `crypto.py` / `finding.py` | 55 / 45 / 40 | ID generation, crypto helpers, the shared `Finding` type used across pillars. |

### 1.2 Subpackages

| Subpackage | Lines | Key files | Responsibility |
|---|---|---|---|
| **`audit/`** | 1728 | `chain.py` 399, `evidence.py` 560, `trace.py` 329, `otel.py` 160, `siem.py` 233 | Pillar 5 — hash chain, evidence packages, OTel-based tracing. See §6. |
| **`business/`** | 2505 | `compile.py` 1010, `catalogue.py` 583, `ladder.py` 396, `graph.py` 314, `store.py` 159 | Turns written business rules ("refunds under $10 auto-approve") into executable guardrails; merges conflicting rules from multiple authors. |
| **`cli/`** | 3665 | `main.py` 1304, `controls_cli.py` 508, `demo.py` 504, `onboarding.py` 421, `business_cli.py` 388, `auth_cli.py` 216, `quickscan.py` 187, `submit.py` 115 | The `agentfox` binary. See §11. |
| **`compliance/`** | 1189 | `status.py` 516, `risk.py` 380, `catalog.py` 250 | Pillar 6 — control catalog, framework mapping, computed status, risk register. |
| **`evaluation/`** | 3166 | `redteam.py` 780, `silent_failure.py` 438, `runner.py` 366, `scorers.py` 350, `gating.py` 309, `drift.py` 288, `ragas_adapter.py` 241, `adapters.py` 189, `model_groundedness.py` 127 | Pillar 4 — native eval runner, promptfoo/Ragas adapters, CI regression gate, drift detection, red-team. |
| **`gateway/`** | 7171 | `app.py` 402, `auth.py` 276, `deps.py` 122, `playground_sessions.py` 196, `routes/` (17 files, 6170 lines) | The FastAPI app — inline proxy + control-plane API. See §10. |
| **`guardrails/`** | 4944 | `pipeline.py`, `base.py`, `actions.py`, `composition.py`, `normalize.py`, `taint.py`, `tuning.py`, `detectors/` (1139), `adapters/` (751) | Pillar 3 — the detector pipeline. See §4. |
| **`identity/`** | 571 | `service.py` 532 | Pillar 2 — non-human identity, delegation, approvals. |
| **`integrations/`** | 1692 | `mcp.py` 439, `langgraph.py` 393, `correlation.py` 360, `fastapi.py` 235, `prometheus.py` 226 | Framework/observability integrations. See §8. |
| **`policy/`** | 1999 | `hierarchy.py` 354, `canary.py` 294, `engine.py` 291, `store.py` 287, `opa.py` 231, `model.py` 256, `simulate.py` 185 | Pillar 6/12 — policy authoring, evaluation, versioning, canary rollout. See §9. |
| **`providers/`** | 1046 | `enterprise.py` 366, `remote.py` 299, `base.py` 192, `echo.py` 146 | The `ModelProvider` seam. |
| **`registry/`** | 961 | `service.py` 779, `control.py` 139 | Pillar 1 — agent registry, observed lineage, kill switch/quarantine. |
| **`sdk/`** | 481 | `__init__.py` 481 | The `AgentFox` client class (local + remote modes). |
| `compliance_data/`, `policies_data/` | — | `controls.yaml`, `obligations.yaml`, `baseline.yaml`, `eu-ai-act-high-risk.yaml`, `tool-containment.yaml` | Static data, not code — read by `compliance/catalog.py` and `policy/store.py` respectively. |

---

## 2. Test coverage map

46 `test_*.py` files, 16,214 lines, under `tests/` — one file per subsystem, tracking the
module inventory above almost 1:1: `test_enforcement_and_api.py`, `test_autoguard.py`,
`test_guardrails.py`, `test_evasion.py`, `test_policy_and_identity.py`,
`test_policy_compiler.py`, `test_policy_canary.py`, `test_hierarchy.py`,
`test_audit_and_evidence.py`, `test_registry_and_compliance.py`, `test_entitlement.py`,
`test_escalation.py`, `test_evaluation.py`, `test_mcp_governance.py`,
`test_memory_and_agent_messaging.py`, `test_business_guardrails.py`, `test_composition.py`,
`test_context_integrity.py`, `test_correlation.py`, `test_data_access.py`,
`test_action_assurance.py`, `test_answerability.py`, `test_arbitration.py`,
`test_attribution.py`, `test_availability.py`, `test_commitments.py`,
`test_discovery_submission.py`, `test_effects.py`, `test_hosted_api_integration.py`,
`test_integrations.py`, `test_onboarding.py`, `test_operator_log.py`,
`test_platform_runtime.py`, `test_playground.py`, `test_provenance_integrity.py`,
`test_quickscan.py`, `test_reachability.py`, `test_register.py`, `test_reliability.py`,
`test_session_scan.py`, `test_system_log.py`, `test_tenancy.py`, `test_tool_contract.py`,
`test_tranche0.py`, `test_tuning.py`, `test_auth.py`, plus `tests/corpus/injection.py` (a
fixture corpus, not a test file). **No frontend (`dashboard/`) test files exist anywhere in
the repo** — this is a real gap.

Current test and line counts are in [`docs/status.md`](status.md), which `scripts/coverage.py --write` regenerates from the source tree; they are not restated here because they go stale.

---

## 3. The `Enforcer` class — `src/agentfox/enforcement.py` (2440 lines)

This is the single code path every integration surface converges on (HLD §5). Class and
method signatures, by call order:

| Method | Line | Role |
|---|---|---|
| `Enforcer.__init__(session)` | — | Binds to a SQLAlchemy session; stateless otherwise |
| `resolve(...)` | — | Resolves agent/identity/environment from request context |
| `preflight(...)` | 1591 | **The orchestrator.** Runs steps 2–6 of the request path (HLD §6) — control verdict, budget gate, answerability gate, taint tagging, per-message `evaluate()` — shared by both buffered and streaming call paths |
| `_control_verdict(...)` | — | Kill-switch / quarantine check (`registry/control.py`) |
| `_budget_gate(...)` | 1744 | Hard budget-cap enforcement — rejects before any provider spend |
| `_answerability_gate(...)` | — | Pillar 7 pre-generation abstention check |
| `evaluate(...)` | 324 | Runs the detector pipeline (Pillar 3) on one message, tracks the worst verdict across the conversation |
| `check_content(...)` | 826 | Standalone content check outside the full preflight (used by `retrieval_node` for indirect-injection scanning) |
| `guard_tool_call(...)` | 854 | Pre-execution tool-call gate — capability/argument/taint checks, loop-governance (`agent_loop.govern_loop`, line ~2367), returns before the wrapped tool body runs |
| `check_conversation_window(...)` | 949 | Multi-turn window analysis (payload-splitting detection) |
| `guard_memory_write(...)` | 1042 | Pillar 16 — memory-write governance (OWASP ASI06) |
| `guard_agent_message(...)` | 1115 | Pillar 17 — inter-agent message security (OWASP ASI07) |
| `call_provider(...)` | 1781 | Invokes the resolved `ModelProvider`, wrapped in the circuit breaker/fallback from `reliability.py` |
| `_finish_completion(...)` | 1892 | Post-flight: output-surface detector pass, provenance binding |
| `run_completion(...)` | 1960 | Buffered (non-streaming) full call |
| `run_completion_stream(...)` | 2038 | SSE streaming variant — the same gate sequence, chunked |
| `_charge_budget(...)` | 2429 | Final budget debit after a completed call |

**Design note worth carrying into any future refactor**: `preflight` is explicitly shared
between the buffered and streaming code paths specifically to avoid the class of bug
`autoguard.py`'s own comments describe having fixed once already (a partial
reimplementation of the same logic that drifted from the gateway's — `autoguard.py:350-352`).
Any new call surface should call `preflight`/`evaluate` directly rather than reimplementing
gate logic locally.

---

## 4. Detector pipeline — `src/agentfox/guardrails/`

`pipeline.py` composes a list of `Detector` implementations (the seam from HLD §2) and runs
them per surface (`input`, `output`, `retrieved`, `tool_result`). Key pieces:

- **`base.py`** — the `Detector` protocol (`detect(content, context) -> Findings`) every
  implementation satisfies.
- **`detectors/`** (1139 lines) — native, dependency-free detectors: `injection.py` (608 —
  the largest single detector, includes the PIGuard+backstop ensemble tuning path),
  `pii.py` (162), `schema.py` (145), `secrets.py` (128), `safety.py` (96).
- **`adapters/`** (751 lines) — wraps optional OSS: `classifiers.py` (361, Granite Guardian /
  restricted-model gate), `embeddings.py` (150), `presidio.py` (121), `rails.py` (119, NeMo/
  Guardrails AI).
- **`taint.py`** — `TaintTracker`: tags every message by `source`
  (`user | retrieved | tool_result | subagent | memory`) and `trust`
  (`trusted | untrusted`). This is the mechanism behind the project's most defensible claim
  (argument-provenance taint tracking, HLD §8) — a tainted value can reach a low-impact tool
  freely but is blocked from an irreversible one regardless of whether any individual detector
  fired on it.
- **`composition.py`** — merges findings across surfaces/detectors into one verdict.
- **`actions.py`** — maps a verdict to an enforcement action (block / redact / escalate / allow).
- **`tuning.py`** — threshold tuning against labeled corpora (this is what the benchmark
  scripts in `benchmarks/` exercise).
- **`normalize.py`** — text normalization defeating common evasion (homoglyphs, zero-width
  characters, encoding tricks) before detection runs.

Every `detector_runs` row records its own `status` (`ok | timeout | skipped_budget`) — a
detector that silently fails to run is a recorded, queryable event, not an invisible gap
(this is what backs the "computed, not attested" claim in HLD §2 for Pillar 3 specifically).

---

## 5. Data model — key entities

Full detail: [Appendix D](appendix-d-data-model.md). SQLAlchemy 2.0, `src/agentfox/models.py`
(1490 lines). Every table carries `id`, `created_at`, `updated_at`, `org_id` — multi-tenancy
is enforced structurally at the session level via `with_loader_criteria` (`tenancy.py`), not
by remembering to filter every query by `org_id`.

| Group | Key tables | Notable invariants |
|---|---|---|
| **Registry** (Pillar 1) | `agents`, `tools`, `mcp_servers`/`mcp_tool_snapshots`, `lineage_edges`, `findings` | `lineage_edges` are derived from spans, not hand-configured; `tools.impact` axis is `read \| write \| high_impact \| irreversible` |
| **Identity** (Pillar 2) | `identities`, `credentials`, `capabilities`, `delegation_edges`, `approval_requests` | `credentials` store argon2id hashes only, plaintext appears once in the issuance response; `delegation_edges` enforce child-capability ⊆ parent-capability at write time; `approval_requests.timeout_action` defaults to `deny` |
| **Guardrails** (Pillar 3) | `detector_runs`, `detection_findings`, `taint_tags`, `budgets` | `detector_runs.status` records degradation (§4); `detection_findings` are redacted at capture, never store raw sensitive spans |
| **Evaluation** (Pillar 4) | `eval_suites/cases/scorers/runs/results`, `baselines`, `drift_windows`, `slos`, `redteam_campaigns/findings` | `baselines` hold a per-scorer regression tolerance; `drift_windows` use PSI/KS statistics; red-team findings map to `owasp_id`/`atlas_id` |
| **Audit** (Pillar 5) | `traces`/`spans`, `audit_entries`, `audit_checkpoints`, `evidence_packages`, `retention_policies`, `legal_holds` | See §6 for the hash-chain invariants |
| **Compliance** (Pillar 6) | `policies`/`policy_versions`/`policy_bindings`, `decisions`, `simulation_runs`, `controls`, `framework_mappings`, `control_statuses`, `risk_assessments`, `obligations` | `policy_versions` are immutable; `decisions` always bind the exact policy version in force at decision time; `framework_mappings.review_status` is `draft \| reviewed` — **as of the last audit, all mappings remain `draft`**, with a documented inconsistency about whether draft mappings are excluded from or chip-labeled-and-included in evidence packages |

---

## 6. Audit chain internals — `src/agentfox/audit/chain.py` (399 lines)

The tamper-evident hash chain, the mechanism behind the "prove what happened" claim:

```
payload_digest = SHA-256(canonical_json(payload))
digest          = SHA-256(seq | occurred_at_iso | action | payload_digest | prev_digest)
```

Invariants enforced in code, not just convention:

- **Append-only** — there is no update or delete path for `audit_entries` anywhere in the
  ORM or the API (`appendix-c-api-spec.md` §C confirms: "no `PUT`/`PATCH`/`DELETE` exists").
- **Gapless `seq`** — a missing sequence number is itself detectable evidence of tampering.
- **Chain linkage** — each entry's digest incorporates the previous entry's digest, so
  altering, deleting, inserting, or reordering any entry breaks every digest after it.
- **Checkpoint signing** — `audit_checkpoints` periodically sign the chain state; the signing
  key is deliberately kept **outside the application database** (customer-held in a self-host
  deployment), so a full DB compromise alone cannot forge a checkpoint.
- **Independent, stdlib-only verification** — the verifier (exercised by `agentfox audit
  verify` and, per the gap-analysis audit, tested standalone outside the repo) recomputes the
  chain from raw entries with no dependency on the application's own trust — this is what
  makes the tamper-evident claim demonstrable in under a minute rather than merely asserted.

`audit/evidence.py` (560 lines) builds auditor-ready export packages: a manifest with a
per-file SHA-256, plus chain-of-custody metadata. `audit/trace.py` (329 lines) is the
separate OpenTelemetry-based execution tracer (`start_trace`/`add_span`/`end_trace`) —
traces and the audit chain are related but distinct: traces answer "what happened, in what
order, with what latency"; the audit chain answers "can I prove this record hasn't been
altered."

---

## 7. `agentfox.auto()` — monkey-patch mechanism

`src/agentfox/__init__.py` (45 lines) lazily re-exports `auto`, `off`, `state`, `Blocked`
from `agentfox.autoguard` via module `__getattr__`, so a bare `import agentfox` touches no
DB and makes no client calls — side-effect-free until `auto()` is actually called.

`autoguard.py` (793 lines), `auto(agent=None, *, mode="observe", environment=None,
session_id=None, register=True, quiet=False)` at line 674:

1. Detects installed frameworks from `sys.modules` against `_FRAMEWORK_MODULES` (langgraph,
   langchain, llama_index, crewai, autogen, fastapi, flask, django, mcp, ragas, litellm).
2. Guesses an agent slug (`default_agent_slug`): env var → entrypoint script name →
   `"default-agent"` fallback.
3. Calls `init_db()` + `register_agent()` (unless `register=False`).
4. Runs the patcher tuple `_PATCHERS = (_patch_openai, _patch_anthropic, _patch_litellm,
   _patch_langchain)` at line 666 — each monkey-patches its target call site
   (`openai.resources.chat.completions.Completions.create`,
   `anthropic.resources.messages.Messages.create`, `litellm.completion`,
   `langchain_core....BaseChatModel.invoke`), wrapping the original in `_govern()` (line 326),
   which calls the **same** `Enforcer.preflight()` the gateway uses (§3) — not a parallel
   reimplementation.
5. A `contextvars.ContextVar` `_IN_AGENTFOX` (line 54) prevents the platform's own internal
   LLM calls (e.g. an LLM-judge scorer inside the eval subsystem) from recursively governing
   themselves — without this, an eval run would try to enforce policy on its own scoring
   calls.
6. Post-flight reads the tool calls out of the response (`_tool_calls_of`: OpenAI/LiteLLM
   `tool_calls`, Anthropic `tool_use`, LangChain `AIMessage.tool_calls`; `_chunk_tool_calls`
   reassembles streamed ones) and runs each through `Enforcer.guard_tool_call` on the call's
   trace (`_govern_tool_calls`). Provenance comes from a `TaintTracker` rebuilt from the
   request's conversation (`_provenance_of`); unseen tools are upserted with
   `infer_impact` and `impact_source="inferred"` (`_register_tool`). A refused call raises
   `Blocked` in place of the response. In `policy` mode a refusal that is only capability
   default-deny is not raised for an agent with no grants at all.

The default mode is `policy`: `Blocked` is raised only when an enforce-mode policy, the kill
switch or a budget cap stops the call, and the shipped `baseline` observes. `mode="observe"`
never raises; `mode="enforce"` raises on anything a policy would block. This is the concrete
mechanism behind HLD principle #1. `off()` (line 752)
reverses every patch (used primarily by the test suite).

---

## 8. LangGraph integration — `src/agentfox/integrations/langgraph.py` (393 lines)

Module docstring states the design commitments directly: LangGraph is an optional import
(the module loads without it installed); trace identity lives **in graph state**
(`STATE_KEY = "__nometria__"`) so it survives checkpointing, resumption, and time-travel;
escalation maps to LangGraph's own `interrupt()` primitive where available rather than
inventing a second pause mechanism; enforcement failures always raise, never return a
silently-ignorable sentinel.

`class AgentFoxGuard` (line 89) — constructed with `agent`, `environment`, `intent`, an
optional shared `session`, `raise_on_escalate`:

| Method | Line | Behaviour |
|---|---|---|
| `state_of(state)` / `trace_id(state)` | — | Reads governance sub-state out of dict- or object-shaped graph state |
| `model_node(fn=None, *, messages_key="messages", schema=None)` | 138 | Decorator — runs `Enforcer.preflight()` on inbound messages before the node executes; writes `trace_id`/`last_verdict`/`observability` back into graph state; stops on block/escalate; otherwise runs the node and evaluates its output on the `"output"` surface, substituting redacted content back into the result if needed |
| `retrieval_node(fn=None, *, source="retrieved")` | 211 | Runs the node, then scans its output on the `"retrieved"` surface via `Enforcer.check_content()` — the indirect-prompt-injection path, described in the docstring as "the highest-severity realistic attack on an agent and the one a model-era input filter never sees" |
| `tool_node(fn=None, *, tool, provenance=None)` | 241 | Calls `Enforcer.guard_tool_call()` **before** the wrapped function body runs — a denied call never executes. Threads `prior_tools`/`prior_steps` state for loop detection (`agent_loop.LoopGovernor`, §1.1). **As of 2026-09-04, this method is being actively extended** (uncommitted) to pass a full step history (`{tool, arguments, observation}` per step) instead of just a tool-name list, so the loop governor can detect alternating A/B/A/B cycles and stalled (no-new-observation) runs, not only per-tool repeat counts — matching a parallel change in `gateway/routes/inline.py`'s `GuardToolCallRequest` |
| `_stop(result)` | 287 | If `result.escalated` and `raise_on_escalate`: calls LangGraph's `interrupt()` if importable, else raises `ApprovalRequired`. If `result.blocked`: raises `PolicyViolation` |

Both `PolicyViolation` (line 49) and `ApprovalRequired` (line 61) are also re-exported from
`agentfox.sdk`, not from this module — worth checking for a single canonical import path if
this is ever cleaned up.

State-shape helper functions (`_read`, `_normalise`, `_stringify`, `_extract_text`,
`_replace_text`, `_with_governance`, `_result_from`) make the guard tolerant of dict,
dataclass, or Pydantic-model graph state, and of LangChain message objects vs. plain dicts.

---

## 9. Policy engine — `src/agentfox/policy/`

| File | Lines | Role |
|---|---|---|
| `engine.py` | 291 | Native deterministic policy evaluator — the default `PolicyEngine` implementation |
| `opa.py` | 231 | OPA/Rego adapter — falls back to the native engine if the OPA sidecar is unreachable |
| `hierarchy.py` | 354 | Hierarchical policy composition/resolution — multiple policy layers (org → team → agent) resolve to one decision |
| `store.py` | 287 | Immutable policy versioning — every edit creates a new `policy_versions` row, never mutates one in place |
| `canary.py` | 294 | Canary rollout: a new policy version can be bound to a fraction of traffic with health gates and automatic rollback on regression |
| `model.py` | 256 | Pydantic models for policy documents |
| `simulate.py` | 185 | `POST /api/policies/simulate` — runs a candidate policy against recent traffic and returns `{newly_blocked, newly_allowed, newly_escalated, unchanged}` without actually enforcing it |

Policy documents themselves are static YAML under `src/agentfox/policies_data/`
(`baseline.yaml`, `eu-ai-act-high-risk.yaml`, `tool-containment.yaml`), loaded by
`policy/store.py` and turned into versioned, bindable `Policy`/`PolicyVersion` rows.

---

## 10. Gateway composition — `src/agentfox/gateway/`

`app.py` (402 lines), `create_app()`:

- Builds **one** FastAPI app serving both `/v1/*` (inline proxy) and `/api/*`
  (control-plane) — a deployment choice the module docstring states explicitly: "keeps the
  self-host story to a single container ... the gateway is stateless so it scales out
  horizontally."
- Middleware: CORS (localhost:3000 + optional configured playground origin) and an
  `admission_gate` middleware scoped only to `/v1/*` — load-shedding via
  `availability.get_admission_controller()`, returns HTTP 429 before routing when saturated.
- Routers included: `inline`, `registry`, `policy`, `evaluation`, `governance`, `tuning`,
  `escalation`, `answerability`, `onboarding`, `provenance`, `entitlement`, `integrations`,
  `discovery`, `memory`, `messaging`, `playground` (the **only** router without a
  `current_user` dependency — unauthenticated by design, per HLD §4's client-side exception).
- App-level routes defined directly (not in a router module): `/api/health`, `/api/version`,
  `/api/detectors`, `/api/reliability`, `/metrics` (Prometheus, unauthenticated), `/api/providers`.
  A one-off `/api/_migrate_policy_canaries` raw-DDL stopgap (HLD §9) used to live here; it was
  removed once later migrations superseded it (re-running it would have rewound
  `alembic_version` to `a1b2c3d4e5f6`).
- `routes/` holds 17 files, 6170 lines total — one module roughly per router listed above.
  `routes/inline.py` is the request-path entry point: `chat_completions` (line 273, `/v1/chat/
  completions`) and `messages` (line 356, `/v1/messages`) both build an `Enforcer(session)`
  and call `preflight(...)` (§3, §6 of the HLD).

`auth.py` (276 lines) — agent-key (`nom_agt_…`, argon2id) and API-token (`nom_api_…`)
resolution; `deps.py` (122 lines) — the `current_user` FastAPI dependency most routers
require; `playground_sessions.py` (196 lines) — rate-limited (`RateLimiter(limit=8,
window_seconds=3600)` for session creation, `limit=40, window_seconds=60` for actions)
unauthenticated demo sessions.

---

## 11. CLI command tree — `src/agentfox/cli/main.py` (1304 lines)

`app = typer.Typer(name="agentfox", ...)`. Top-level verbs (`main.py:93-173`): `version`,
`seed`, `demo`, `serve` (runs `uvicorn.run("agentfox.gateway.app:app", ...)` — **the exact
same app object `api/index.py` re-exports**, HLD §9).

Subcommand groups (`app.add_typer`, plus `_register_*` calls from their own modules,
`main.py:63-74`):

| Group | Representative subcommands |
|---|---|
| `agents` | `list`, `discover`, `lineage`, `quarantine`, `kill`, `resume`, `controls` |
| `policy` | `list`, `lint`, `effective`, `simulate`, `enforce`, `observe`, `validate` |
| `eval` | `run`, `gate`, `baseline`, `drift`, `online` |
| `audit` | `verify`, `checkpoint` |
| `evidence` | `export` |
| `compliance` | `sync`, `compute`, `status`, `frameworks`, `risk`, `obligations`, `board` |
| `redteam` | `run`, `probes` |
| `scan` | `mcp` |
| `tools` | `set-triggers` |
| `access` | `declare-scope`, `declare-reference` |
| `db` | `upgrade`, `downgrade`, `current` |
| (registered separately) | onboarding, quickscan, auth, controls, business command sets |

---

## 12. Database migrations — `migrations/versions/`

26 Alembic revisions (dated 2026-08-18 through 2026-09-04; head `b3f8e29a71c4`, the deferred job queue, i.e. spanning this project's own
build timeline). Rough evolution order: baseline schema → tracing/observability links →
policy hierarchy/agent controls → guardrail feedback/suppressions → per-tenant audit chain →
escalation policy handoffs → source records → business rules → knowledge boundary →
entitlement principals/grants → **a cluster of four "org-scoped uniqueness was global"
hardening migrations** (control-key, more-tenant-scoped-uniqueness, cascade/access-scoping,
lineage-edge-uniqueness — direct evidence of the multi-tenancy hardening effort) → GitHub integration →
hosted-API integration → source-content validation/connections → seed-data flag →
inter-agent-message security → memory-write governance → policy canary rollout → eval
annotation queue.

Notably, revision `a1b2c3d4e5f6` (policy canary) is the exact revision ID hardcoded into
`gateway/app.py`'s since-removed `/api/_migrate_policy_canaries` stopgap (§10) — direct
confirmation that endpoint existed because that specific migration couldn't be applied to a
deployed environment through normal means.

---

## 13. API surface

Full detail: [Appendix C](appendix-c-api-spec.md). Base `http://localhost:8080` self-hosted;
`/api` = control plane, `/v1` = inline enforcement (OpenAI/Anthropic wire-compatible). Three
credential types: agent key, API token, session cookie. Six roles (`owner`, `admin`,
`security`, `compliance`, `developer`, `auditor`) — `auditor` can read and verify but never
mutate anything.

| Surface | Representative endpoints |
|---|---|
| Inline (`/v1`) | `POST /v1/chat/completions`, `POST /v1/messages`, `POST /v1/guard/input\|output\|tool_call`, `POST /v1/traces` (OTLP/HTTP ingest) |
| Registry (`/api`) | `/api/agents`, `/agents/{id}/lineage\|posture`, `/api/tools`, `/api/mcp-servers`, `/mcp-servers/{id}/scan`, `/api/findings` |
| Identity | `/api/identities`, `/{id}/credentials\|rotate\|revoke\|capabilities`, `/api/approvals`, `/api/users`, `/api/roles` |
| Policy | `/api/policies`, `/{id}/versions\|bind`, `/api/policies/simulate`, `/api/policies/validate` |
| Evaluation | `/api/eval/suites\|cases`, `/cases/from-trace`, `/api/eval/runs`, `/api/eval/gate` (CI entry point), `/api/eval/drift\|slos\|compare`, `/api/redteam/campaigns` |
| Audit & evidence | `/api/traces`, `/{id}/replay`, `/api/audit/entries` (append-only, no mutation verb exists), `/api/audit/verify`, `/api/audit/checkpoints`, `/api/evidence`, `/api/export/siem`, `/api/retention`, `/api/legal-holds` |
| Compliance | `/api/controls`, `/api/frameworks`, `/api/compliance/status`, `/api/risk/assessments`, `/api/obligations`, `/api/board`, `/api/compliance/packs/{key}/import` |
| Platform | `/api/health`, `/api/version`, `/api/detectors`, `/api/providers` |

Conventions: RFC 7807 `problem+json` errors; cursor pagination (max 500 per page);
`Idempotency-Key` honoured; per-token rate limiting (`429` + `Retry-After`); **every
mutating call writes an `AuditEntry`, including evidence-package reads** — "who looked at
the evidence is itself audit-relevant."

---

## 14. Deployment artifacts — `deploy/`

Three files only, no Kubernetes manifests anywhere in the repo.

- **`docker-compose.yml`** — `db` (postgres:16-alpine), `opa` (openpolicyagent/opa:0.70.0,
  optional), `gateway` (port 8080), `dashboard` (port 3000). Env defaults:
  `NOMETRIA_ALLOW_EGRESS=false`, `NOMETRIA_DEFAULT_PROVIDER=echo`,
  `NOMETRIA_DEFAULT_POLICY_MODE=observe`, `NOMETRIA_FAIL_MODE=open`, and a hardcoded
  `NOMETRIA_AUDIT_SIGNING_KEY: change-me-before-any-real-deployment` with an explicit
  change-this comment.
- **`Dockerfile`** (gateway) — `python:3.12-slim`, installs
  `agentfox[postgres,otel,classifiers]`, bakes in ML detector weights at build time
  (Granite Guardian, PIGuard, protectai deberta injection classifier, sentence-transformers
  MiniLM) plus an optional gated tier (Llama Guard 3-8B, requires an `HF_TOKEN` build secret,
  runtime-gated behind `NOMETRIA_ACCEPT_RESTRICTED_MODEL_LICENSES=1`). **Contains two `COPY`
  instructions that reference paths not present in the repository**: `COPY compliance
  ./compliance` and `COPY policies ./policies` — verified directly against the filesystem
  on 2026-09-04, neither `compliance/` nor `policies/` exists at the repo root; the actual
  YAML data already ships via the preceding `COPY src ./src` at
  `src/agentfox/compliance_data/` and `src/agentfox/policies_data/`. As written, this build
  step targets a path that doesn't exist in the current tree.
- **`Dockerfile.dashboard`** — `node:22-alpine`, standard Next.js standalone-output
  multi-stage build, runs `node server.js`.

---

## 15. See also

- [docs/hld.md](hld.md) — architecture shape, principles, integration surfaces
- [docs/appendix-a-oss-register.md](appendix-a-oss-register.md) — full OSS licence/health register
- [docs/appendix-b-control-catalog.md](appendix-b-control-catalog.md) — 43 controls × 7 frameworks
- [docs/appendix-c-api-spec.md](appendix-c-api-spec.md) — full API specification
- [docs/appendix-d-data-model.md](appendix-d-data-model.md) — full data model
- [docs/appendix-e-threat-model.md](appendix-e-threat-model.md) — full threat model
