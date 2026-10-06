# Low-Level Design (LLD)

**Companion to [docs/architecture/high-level-design.md](high-level-design.md).** Where the HLD explains the shape of the system, this
document explains the pieces: the package layout, key classes and methods, the data model, the
API surface, and the internals of the subsystems most worth understanding in depth (the
enforcer, approvals, the detector pipeline, the policy engine, the audit chain, monitoring).
[ARCHITECTURE.md](../../ARCHITECTURE.md) is the shorter map and traces one tool call through the
code; read it first. This document names modules and functions rather than line numbers or line
counts, because those drift; current test and line counts are generated into
[`docs/status.md`](../status.md). If this document and the code disagree, the code is right.

---

## 1. Package layout — `src/agentfox/`

Everything lives in subpackages. The package root holds only `__init__.py` (the lazy
`auto`/`off`/`state`/`Blocked` re-exports) and `errors.py` (the exception hierarchy, §3.2).

| Subpackage | Key modules | Responsibility |
|---|---|---|
| **`core/`** | `config.py`, `db.py`, `tenancy.py`, `models/`, `vocab.py`, `outbound.py`, `webhooks.py`, `crypto.py`, `ids.py`, `finding.py` | Settings (`AGENTFOX_*`, `agentfox.toml`) and the startup secret check; engine and session factory; session-level tenant isolation; the ORM (§5); the shared vocabulary (`SURFACES`, `TAINT_ORDER`/`taint_rank`, `EFFECT_RANK`, `COMPARATORS`, `AUTOMATION_ACTOR_TYPE`); vetted outbound HTTP (`guarded_get`/`guarded_post`); the signed finding webhook; at-rest encryption. Imports nothing outside `core`. |
| **`fixtures/`** | `seed.py` | The deterministic demo world `agentfox demo`, the playground and the tests seed. |
| **`jobs/`** | `queue.py`, `store.py`, `scheduler.py`, `handlers.py` | Work outside the request: the in-process reference queue, the persisted `jobs` store with retries and a dead letter, per-tenant `JobSchedule` rows, and the handler table (`monitors.run`, `probes.run`, `escalation.scan`, `canary.advance`, `drift.check`, …). |
| **`discovery/`** | `repo.py`, `exposure.py`, `threats.py`, `openapi.py`, `sessions.py` | Static scanning: repositories, OpenAPI specs, local coding-assistant sessions, lethal-trifecta exposure, threat coverage. |
| **`registry/`** | `service.py`, `control.py`, `skills.py` | The agent registry (`observe_agent`, `register_agent`), observed lineage, kill switch and quarantine, MCP tool-poisoning and skill scanning. |
| **`runtime/`** | `enforcement/` (§3), `autoguard/` (§7), `availability.py`, `reliability.py`, `agent_loop.py` | The request path: the `Enforcer`, `auto()`, fail modes and admission control, the provider circuit breaker and fallback, loop governance. |
| **`containment/`** | `escalation.py`, `effects.py`, `data_access.py`, `control_flow.py`, `agent_messaging.py`, `findings.py` | What an agent may do beyond the grant: escalation governance and hand-offs, effects that outlive a call, data-access scoping, control-flow integrity, inter-agent message signing, containment findings. |
| **`grounding/`** | `answerability.py`, `provenance.py`, `entitlement.py`, `commitments.py`, `integrity.py`, `context_integrity.py`, `arbitration.py`, `register.py`, `tool_contract.py`, `sycophancy.py` | What an answer may say: knowledge boundaries and abstention, source authority, entitlement filtering, commitment and disclosure language, numeric/temporal/entity integrity, context integrity, source arbitration, tool contracts, sycophancy. |
| **`detection/`** | `base.py`, `pipeline.py`, `detectors/`, `adapters/`, `taint.py`, `normalize.py`, `prefilter.py`, `actions.py`, `composition.py`, `trajectory.py`, `files.py`, `tuning.py`, `warmup.py`, `judgment/` | The detector pipeline and everything it reads (§4). `judgment/` holds the optional model tiers and the routing table that limits what each may decide ([judgment-tiers.md](judgment-tiers.md)). |
| **`policy/`** | `model.py`, `engine.py`, `opa.py`, `store.py`, `hierarchy.py`, `simulate.py`, `canary.py`, `taint_view.py`, `coding.py` | Policy documents, the native engine and the OPA adapter, storage, binding and the stored-version loader, hierarchy and lint, simulation, canaries (§9). |
| **`business/`** | `compile.py`, `catalogue.py`, `ladder.py`, `graph.py`, `store.py` | Business rules as guardrails: threshold ladders (each with its own mode), compiling written policy into rules, merging rules from many authors. |
| **`identity/`** | `service.py` | Non-human identities, credentials, capability grants and constraints, delegation, approvals and their redemption (§3.1). |
| **`prove/`** | `audit/` (`chain.py`, `evidence.py`, `trace.py`, `otel.py`, `siem.py`, `operator_log.py`, `system_log.py`), `compliance/` (`catalog.py`, `status.py`, `risk.py`), `findings.py`, `report.py`, `attribution.py` | The audit chain (§6), traces, evidence packages, SIEM/OTLP, operator logs, the control catalog and computed status, findings, the one-page report, failure attribution. |
| **`evaluation/`** | `runner.py`, `scorers.py`, `gating.py`, `drift.py`, `silent_failure.py`, `redteam.py`, `adaptive.py`, `live_probes.py`, `showcase.py`, `ragas_adapter.py`, `adapters.py`, `model_groundedness.py` | Eval runner, CI gating (errored cases fail the gate), drift, silent-failure sampling, offline red team (dry-run, isolated), adaptive campaigns, live probes of deployed agents and the public showcase (§15). |
| **`improvement/`** | `contract.py`, `proposals.py`, `loops.py`, `appliers.py`, `traffic.py` | The governed improvement loop: proposals, the loops that file them, appliers that make and undo each change, learned permissions from traffic. |
| **`monitoring/`** | `service.py`, `snapshots.py`, `alerts.py`, `github.py`, `mcp_live.py` | Continuous monitoring of connected sources: scheduling, diffing runs into findings, Slack alerts, GitHub archive download and push-signature checks, remote MCP tool listings (§15). |
| **`gateway/`** | `app.py`, `auth.py`, `deps.py`, `verdicts.py`, `playground_sessions.py`, `routes/` | The FastAPI app: inline `/v1/*` and the `/api/*` control plane (§10). One router per file in `routes/`. |
| **`cli/`** | `main.py`, `layout.py`, `commands/`, `*_cli.py` | The `agentfox` binary (§11). |
| **`hooks/`** | `daemon.py`, `client.py`, `harness.py`, `protocol.py`, `capability.py`, `baseline.py` | Coding-agent hooks: a thin per-call client, a warm daemon on a Unix socket that calls the `Enforcer`, and the baseline `hooks install` sets up (registers the agent, grants the built-in tools). |
| **`integrations/`** | `langgraph.py`, `mcp.py`, `mcp_server.py`, `fastapi.py`, `correlation.py`, `prometheus.py` | LangGraph guard (§8), MCP governor and the read-only MCP server, FastAPI middleware, LangSmith/Langfuse correlation, Prometheus. |
| **`sdk/`** | `__init__.py` | The explicit SDK: `AgentFox`, `AgentSession`, `@fox.tool(impact=…)` (joins the session's trace), `wait_for_approval`; local or remote mode. |
| **`providers/`** | `base.py`, `echo.py`, `remote.py`, `enterprise.py` | The `ModelProvider` seam: `echo` (offline default), OpenAI, Anthropic, Azure, Bedrock, Vertex, LiteLLM. |
| `policies_data/`, `compliance_data/` | `baseline.yaml`, `eu-ai-act-high-risk.yaml`, `tool-containment.yaml`, `coding-agent.yaml`; `controls.yaml`, `obligations.yaml`, `threats.yaml` | Shipped YAML, read by `policy/store.py` and `prove/compliance/catalog.py`. |

---

## 2. Tests

`tests/` mirrors the package one directory per subpackage (`tests/runtime/`, `tests/platform/policy/`,
`tests/capabilities/monitoring/`, …). Three directories are cross-cutting: `tests/e2e/` runs the request
path end to end across packages, `tests/repo/` checks the repository itself (claims registry,
docs site, harness, vendored wheels, install layout), and `tests/corpus/` holds fixture
corpora rather than tests. The dashboard has its own vitest suite (`npm test` in
`dashboard/`). Counts are in [`docs/status.md`](../status.md), regenerated by
`scripts/coverage.py --write`.

---

## 3. The `Enforcer` — `src/agentfox/runtime/enforcement/`

The single code path every integration surface converges on (HLD §5). `Enforcer` is one class
assembled from mixins, one module per stage (the package docstring lists them):

| Module | Methods | Role |
|---|---|---|
| `enforcer.py` | `Enforcer.__init__(session, pipeline=None)`, `resolve(...)`, `evaluate(...)` | Identity resolution, and **`evaluate()`, where every decision is made and recorded**. It checks the kill switch first, then runs the detector pipeline, suppressions, `check_capability`, the content checks, business ladders and action analysis, resolves the policy hierarchy (`policies_in_force`), combines verdicts, redeems a presented approval (§3.1), and persists the `Decision`, findings, any `ApprovalRequest`, a guardrail span and the audit entry. |
| `completion.py` | `preflight(...)`, `call_provider(...)`, `run_completion(...)`, `_answerability_gate`, `_finish_completion` | **The completion orchestrator.** `preflight` runs kill switch, budget, answerability, taint marking and per-message `evaluate()`, shared by the buffered and streaming paths; `call_provider` wraps the provider in the breaker from `runtime/reliability.py`. |
| `streaming.py` | `run_completion_stream(...)` | The SSE variant: the same gates, chunked. |
| `tool_calls.py` | `guard_tool_call(...)` | The pre-execution tool-call gate: kill switch, argument provenance (`TaintTracker.taint_arguments`), `TaintTag` rows and a lineage edge, loop governance, then `evaluate(surface="tool_args")`. |
| `surfaces.py` | `check_content`, `check_conversation_window`, `guard_memory_write`, `guard_completion`, `guard_reasoning`, `guard_file`, `guard_agent_message` | The other surfaces: retrieved content, multi-turn windows, memory writes, a completion handed in by the caller, model reasoning, files, inter-agent messages. |
| `checks.py` | `_evidence_checks`, `_disclosure_checks`, `_control_flow_checks`, `_sycophancy_checks`, `_commitment_checks`, `_trajectory_checks`, `_context_checks` | The grounding and containment checks `evaluate()` folds into one record. |
| `limits.py` | `_control_verdict`, `_budget_gate`, `_charge_budget` | Kill switch / quarantine, and hard spend budgets. |
| `findings.py` | `_raise_detection_finding`, `_record_degradation`, `_persist_detectors` | Detector-run rows, degradation records, detection findings. |
| `approvals.py` | `held_call(...)` | What an escalation is filed under: the tool and its arguments, or for a held message `message:<surface>` with a masked excerpt and the content's SHA-256. |
| `rules.py`, `result.py` | `_fallback_policies`; `EnforcementResult`, `PreflightOutcome`, `StreamEvent` | The in-memory `baseline` fallback when no pack is bound; result types. |

**The kill switch is checked inside `evaluate()`, before anything else**, so a killed or
quarantined agent is refused on every surface that reaches a decision (the guard endpoints,
memory writes and agent messages included), not only on completions and tool calls.

**Design note worth carrying into any future refactor**: new surfaces call `preflight`,
`evaluate` or one of the `guard_*` methods; they never reimplement gate logic. `auto()` once
carried a partial copy that drifted from the gateway's, which is why `preflight` is shared.

### 3.1 Approvals and redemption — `identity/service.py`

An escalation files an `ApprovalRequest` (`request_approval`) bound to the agent and to what
`held_call` returned. `resolve_approval` approves or denies it:

- Approving is refused with `AgentStopped` while the agent is killed or quarantined; denying is
  always allowed.
- An approval restarts its clock on approval: it stays redeemable for `REDEEM_WINDOW_MINUTES`
  (30). Unanswered approvals expire (`expire_stale_approvals`) and expiry denies.

A retry presents the approval: `X-Nometria-Approval` on the proxy routes, `approval_id` in the
`/v1/guard/*` body, or the SDK's `wait_for_approval`, which polls `GET /api/approvals/{id}` with
the agent's own key (an agent may read only its own approvals). Inside `evaluate()`, only when
the call would otherwise escalate, `redeem_approval` checks that the approval is `approved`,
unexpired, for the same agent, tool and canonicalised arguments (or the same content digest
for a held message), then flips it to `used` with a conditional `UPDATE … WHERE status =
'approved'`, so two racing retries cannot both spend it. A redeemed call is allowed with the
`approval.redeemed` rule fired; anything else escalates again and the decision's reason says why
the approval was not used. An approval can therefore never make a call more permitted than a
person said, and lets exactly one call through. A held proxy request answers **428** with the
approval id and the poll path.

### 3.2 Exceptions — `agentfox/errors.py`

One hierarchy for everything AgentFox raises into a caller's code: `AgentFoxError`, with
`PolicyViolation` (a decision blocked the call) and `ApprovalRequired` (held; carries
`approval_id`). The SDK and the LangGraph guard raise the same classes; `auto()` raises
`agentfox.Blocked` and the MCP governor `McpCallBlocked`, both also `RuntimeError`s. The
FastAPI middleware refuses with an HTTP 403 instead of raising.

---

## 4. Detector pipeline — `src/agentfox/capabilities/detection/`

`pipeline.py` (`DetectorPipeline`) runs the enabled `Detector` implementations concurrently
per surface (`input`, `output`, `retrieved`, `tool_result`, `tool_args`, `memory_write`,
`agent_message`, `reasoning`, …) under a per-request `LatencyLedger` budget. Key pieces:

- **`base.py`** — `Detector` / `BaseDetector` (`key`, `version`, `surfaces`, `_detect`),
  `Detection`. The surface list and `TAINT_ORDER` they use live in `core/vocab.py`.
- **`detectors/`** — native, dependency-free detectors: `injection.py` (lexical, structural and
  contextual signals; runs on `tool_args` too), `pii.py`, `secrets.py`, `safety.py`,
  `schema.py`, and `judgment.py` (the optional judgment tiers as a detector).
- **`adapters/`** — wrappers of optional OSS, each with an `available()` that is false when
  its extra is missing: `classifiers.py` (PIGuard ensemble, Granite Guardian), `embeddings.py`,
  `presidio.py`, `rails.py` (NeMo Guardrails / Guardrails AI), `hub.py` (Guardrails AI Hub
  validators, one detector each).
- **`normalize.py`** — normalisation that defeats evasion before matching: homoglyphs,
  zero-width characters, encodings, letter-spaced words (`despaced`) and text inside markup a
  reader would not see (`hidden_markup`), each scanned as its own view.
- **`prefilter.py`** — a sound pre-check that lets a regex be skipped on text it cannot match.
  `opening_literals(pattern)` derives the lower-cased literals every match must start with;
  `LoweredText.may_match` checks them with `str.__contains__` on a once-lowered copy. It only
  ever skips: a pattern whose opening is not reducible to literals always runs, and non-ASCII
  text always runs every pattern (case folding differs from `str.lower` there). The injection
  detector uses it so a large benign document does not pay one regex pass per pattern.
- **`taint.py`** — `TaintTracker` and `TaintMark`: tags every message and argument by source
  (`none < user < retrieved < tool_result < subagent < memory`). This is the mechanism behind
  the most defensible claim (HLD §9): a tainted value can reach a low-impact tool but is
  refused at an irreversible one whether or not any detector fired.
- **`composition.py`** — composed privilege escalation: one tool's output feeding a
  higher-impact tool's argument.
- **`actions.py`** — action analysis of generated SQL, shell and API calls (operation class,
  blast radius, reversibility).
- **`trajectory.py`** — conversation-level crescendo scoring.
- **`files.py`** — files split into the layers a model reads, each checked with provenance.
- **`tuning.py`** — thresholds and suppressions against labelled corpora.
- **`warmup.py`** — loads opted-in model detectors once per process: the gateway and the hooks
  daemon call `warm_all()` at startup, and `auto()`, the SDK's local mode and `AgentFoxGuard`
  call `warm_in_background()`, so the first real request does not pay the load.

Every `detector_runs` row records its own `status` (`ok | timeout | error | skipped_budget`):
a detector that fails to run is a recorded, queryable event, and a degraded pipeline is handled
under the fail mode (HLD principle #4).

---

## 5. Data model — key entities

Full detail: [Appendix D](data-model.md). SQLAlchemy 2.0 under `src/agentfox/core/models/`
(one module per area: `registry`, `identity`, `guardrails`, `evaluation`, `audit`, `policy`,
`improvement`, `public`). Every tenant table carries `org_id`; isolation is applied at the
session by `core/tenancy.py` (a loader criterion on every ORM statement), not by filtering each
query.

| Group | Key tables | Notable invariants |
|---|---|---|
| **Registry** | `agents`, `agent_controls`, `tools`, `mcp_servers`/`mcp_tool_snapshots`, `lineage_edges`, `findings` | `lineage_edges` are derived from spans; `tools.impact` is `read \| write \| high_impact \| irreversible` |
| **Identity** | `identities`, `credentials`, `capabilities`, `delegation_edges`, `approval_requests`, `users`, `api_tokens`, `github_connections` | Keys and tokens stored as argon2id hashes, shown once; child capability ⊆ parent at write time; an approval is `pending → approved → used` (or `denied`/`expired`), and `used` is final |
| **Guardrails** | `detector_runs`, `detection_findings`, `taint_tags`, `budgets` | `detector_runs.status` records degradation; detection samples are redacted at capture |
| **Evaluation** | `eval_suites/cases/runs/results`, `baselines`, `drift_windows`, `slos`, `redteam_campaigns/findings`, `probe_targets` | Live probe campaigns are `redteam_campaigns` rows with `runner="live"`; a probe target is created disabled |
| **Audit & jobs** | `traces`/`spans`, `audit_entries`, `audit_checkpoints`, `evidence_packages`, `jobs`, `job_schedules` | §6 for the hash chain; a schedule never enqueues while its previous job is pending or running |
| **Policy & compliance** | `policies`/`policy_versions`/`policy_bindings`, `policy_canaries`, `decisions`, `simulation_runs`, `controls`, `framework_mappings`, `control_statuses` | Versions are immutable; saving a version never changes the binding in force; `decisions.policy_version_ids` records every version in force |
| **Monitoring** | `monitors`, `alert_channels` | One monitor per `(org, kind, target)`; `baseline_json` is replaced only by a successful run |

---

## 6. Audit chain internals — `src/agentfox/platform/ledger/chain.py`

The tamper-evident hash chain, the mechanism behind the "prove what happened" claim:

```
payload_digest = SHA-256(canonical_json(payload))
digest          = SHA-256(seq | occurred_at_iso | action | payload_digest | prev_digest)
```

Invariants enforced in code, not just convention:

- **Append-only** — `chain.append` is the only write path for `audit_entries`; there is no
  update or delete path in the ORM or the API.
- **Gapless `seq`** — a missing sequence number is itself detectable evidence of tampering.
- **Chain linkage** — each entry's digest incorporates the previous entry's digest, so
  altering, deleting, inserting, or reordering any entry breaks every digest after it.
- **Checkpoint signing** — `audit_checkpoints` sign the chain state with a key kept **outside
  the application database** (customer-held in a self-host deployment). Outside development
  the process refuses to start while that key still has a published value (§10).
- **Independent, stdlib-only verification** — evidence packages ship a `verify_chain.py` that
  recomputes the chain from raw entries with no dependency on the application
  (`agentfox report verify` verifies the stored chain in place).

`audit/evidence.py` builds auditor-ready export packages (a manifest with a per-file SHA-256,
chain-of-custody metadata), optionally scoped to one agent. `audit/trace.py` is the execution
tracer (`start_trace`/`add_span`/`end_trace`); `audit/otel.py` ingests OTLP (JSON or protobuf,
optionally gzipped). Traces answer "what happened, in what order"; the chain answers "can I
prove this record hasn't been altered."

---

## 7. `agentfox.auto()` — monkey-patch mechanism

`src/agentfox/__init__.py` lazily re-exports `auto`, `off`, `state`, `Blocked` from
`agentfox.runtime.autoguard` via module `__getattr__`, so a bare `import agentfox` touches no
DB and makes no client calls.

`runtime/autoguard/__init__.py`, `auto(agent=None, *, mode="policy", environment=None,
session_id=None, intent=None, register=True, quiet=False, …)`:

1. Detects installed frameworks from `sys.modules` (`autoguard/environment.py`,
   `_FRAMEWORK_MODULES`: langgraph, langchain, llama_index, crewai, autogen, fastapi, …).
2. Guesses an agent slug (`default_agent_slug`): env var → entrypoint script name →
   `"default-agent"`.
3. Registers the agent (unless `register=False`) and warms opted-in detectors in the background.
4. Runs `_PATCHERS = (_patch_openai, _patch_anthropic, _patch_litellm, _patch_langchain)`, each
   replacing its target call site with a wrapper that calls `_govern` (sync) or `_agovern`
   (async), which call the **same** `Enforcer.preflight()` the gateway uses.
5. A `contextvars.ContextVar` `_IN_AGENTFOX` stops AgentFox's own model calls (an LLM-judge
   scorer, say) from being governed recursively.
6. Post-flight reads tool calls out of the response (`autoguard/tool_calls.py:_tool_calls_of`,
   with `_chunk_tool_calls` for streams) and runs each through `Enforcer.guard_tool_call` with a
   `TaintTracker` rebuilt from the conversation (`_provenance_of`); unseen tools are upserted
   with an inferred impact (`_register_tool`). A refused call raises `Blocked` in place of the
   response.

The default mode is `policy`: `Blocked` is raised only when an enforce-mode policy, the kill
switch or a budget cap stops the call, and an agent holding no grants at all is not refused
for a missing grant until its first grant. `mode="observe"` never raises; `mode="enforce"`
raises on anything a policy would block. `off()` reverses every patch.

---

## 8. LangGraph integration — `src/agentfox/frameworks/langgraph.py`

LangGraph is an optional import; trace identity lives **in graph state**
(`STATE_KEY = "__nometria__"`) so it survives checkpointing, resumption and time-travel;
escalation maps to LangGraph's own `interrupt()`; enforcement failures always raise.

`class AgentFoxGuard`, constructed with `agent`, `environment`, `intent`, an optional shared
`session`, `raise_on_escalate`:

| Method | Behaviour |
|---|---|
| `state_of(state)` / `trace_id(state)` | Reads governance sub-state out of dict- or object-shaped graph state |
| `model_node(fn=None, *, messages_key="messages", schema=None)` | Runs `Enforcer.preflight()` on inbound messages before the node; writes `trace_id`/`last_verdict` back into state; stops on block/escalate; evaluates the node's output on the `output` surface, substituting redacted content |
| `retrieval_node(fn=None, *, source="retrieved")` | Runs the node, then scans its output on the `retrieved` surface via `Enforcer.check_content()`: the indirect-injection path |
| `tool_node(fn=None, *, tool, provenance=None)` | Calls `Enforcer.guard_tool_call()` **before** the wrapped body runs, threading `prior_steps` (tool, arguments, observation) so the loop governor sees alternating cycles and stalled runs |
| `_stop(result)` | On escalate with `raise_on_escalate`: calls `interrupt()` inside a running graph, and on resume only an explicit approval lets the node continue (a denial raises `PolicyViolation`); outside a graph raises `ApprovalRequired`. On block raises `PolicyViolation` |

Both exceptions come from `agentfox.errors` (§3.2). `tests/frameworks/test_langgraph_real_graph.py`
runs the guard inside a compiled graph with a checkpointer.

---

## 9. Policy engine — `src/agentfox/platform/policy/`

| Module | Role |
|---|---|
| `model.py` | Pydantic models: `PolicyDocument`, `Rule`, `Condition`, `PolicyInput`; a pack may declare its own `fail_mode` |
| `engine.py` | `NativePolicyEngine` (the default) and `combine` |
| `opa.py` | OPA/Rego adapter; falls back to the native engine if the sidecar is unreachable |
| `store.py` | Loading shipped and project packs, `save_policy`, bindings (`set_mode`, `current_binding`), `policies_in_force`, `active_policies`, `effective_for`, and **the stored-version loader** |
| `hierarchy.py` | `org → team → agent → user` composition (`extend` / `restrict` / `override`), `resolve_effective`, and the lint (`lint_policy`, unreachable rules, unknown values) |
| `simulate.py` | Replays recorded decisions against a candidate (`simulate`), records the run (`record_simulation`), and finds the simulation that covers a version (`simulation_for`, matched by rules fingerprint) |
| `canary.py` | Canary rollout: cohorts pick the stable or candidate version per subject, a two-way health gate, minimum dwell per step, automatic rollback |
| `taint_view.py` | The provenance a rule reasons over, shared by the live path and replay |
| `coding.py` | Which agents the `coding-agent` pack applies to |

**Stored versions load through one function.** `load_version_document(version)` is the only way a
stored `policy_versions` row (`compiled_json` or `body`) becomes a `PolicyDocument`; the store,
the `Enforcer`, canary, simulation, the improvement appliers and the API all call it. It makes
one repair: a version of a pack listed in `PROTECTED_RULES` that lacks a protected rule gets
that rule back from the shipped pack, with a warning logged once per version. Anything else that
fails validation raises `UnloadablePolicyVersion`, which carries the pack key, version, binding
mode and the fail mode the stored document declared. The validator for documents being *saved*
is unchanged, so a new version without a protected rule is refused.

At runtime `policies_in_force(..., skipped=[...])` collects unloadable versions instead of
raising, so the other packs are still evaluated. `Enforcer.evaluate()` then records a
`policy.unloadable` rule for each: a pack bound in `observe` never blocks; a pack bound in
`enforce` blocks if the deployment's `fail_mode` or the pack's own declared `fail_mode` is
`closed`, and otherwise the call is allowed with the gap named in the decision. Read-only views
skip the layer and list it.

**Saving and promoting are separate.** Saving appends an immutable version and leaves what is in
force unchanged (`save_policy(..., rebind=False)`). Promotion (`POST /api/policies/{key}/mode`,
`agentfox policy enforce`) is the only way to change it, and promoting to `enforce` over HTTP
requires a recorded simulation of exactly that version's rules; demoting to `observe` never
does. The hierarchy is enforced at runtime: `evaluate()` resolves the same layers
`agentfox policy effective` prints.

---

## 10. Gateway composition — `src/agentfox/gateway/`

`app.py`, `create_app()`:

- **Refuses to start on published secrets.** The first call is
  `core.config.assert_production_secrets()`: outside a development environment
  (`development`, `dev`, `test`, `testing`, `local`; any other name counts as production), an
  unset or published `AGENTFOX_SERVICE_AUTH_SECRET` or `AGENTFOX_AUDIT_SIGNING_KEY` raises
  `InsecureConfigurationError` before the app is built. It runs in `create_app`, not the
  lifespan, because a serverless host may never run the lifespan.
- Builds **one** FastAPI app serving `/v1/*` (inline) and `/api/*` (control plane), stateless
  so it scales out for throughput.
- Middleware: CORS (localhost:3000 plus an optional playground origin); for `/v1/*` only,
  `degradation_gate` (applies the fail mode, returns 503 or stamps `X-Nometria-Degraded`) and
  `admission_gate` (load shedding, 429 with `Retry-After`).
- The lifespan warms detectors (`warm_all`).
- Routers, one per file in `routes/`: `inline`, `registry`, `policy`, `evaluation`,
  `governance`, `tuning`, `escalation`, `answerability`, `onboarding`, `provenance`,
  `entitlement`, `integrations`, `jobs`, `monitors`, `discovery`, `memory`, `messaging`,
  `proposals`, `posture`, `coverage`, `probes`. Unauthenticated by design: `playground`,
  `waitlist`, and `probes.public_router` (`GET /api/public/showcase`).
- App-level routes: `/`, `/health`, `/api/health`, `/api/version`, `/api/detectors`,
  `/api/reliability`, `/metrics` (Prometheus, unauthenticated), `/api/providers`.

`deps.py`: `db` (a session committed with the response), `current_user`, `require(family)`
(role check per write family), `agent_credential` (binds the tenant from an agent key; **a
presented `nom_agt_` key that does not verify is a 401**, while no credential at all is served
as shadow traffic in the default tenant), and `operator_or_agent` (for the few reads an agent
makes about itself). `auth.py`: agent keys and operator tokens (`nom_api_…`, argon2id,
`revoke_token`). Signing out (`POST /api/auth/logout`) revokes that session's own token, and a
GitHub sign-in retires all but the newest `MAX_LOGIN_SESSIONS` (5) login tokens.
`playground_sessions.py`: sandbox tenants and the in-process `RateLimiter`.

---

## 11. CLI command tree — `src/agentfox/cli/`

`main.py` registers every command; `layout.py:apply_layout` re-registers them under the
visible verbs, grouped into panels (`agentfox --help`): **Start** `init`, `demo` · **See**
`scan`, `agents` · **Watch** `serve`, `findings` · **Contain** `permit`, `declare`, `policy` ·
**Prove** `test`, `report` · **Operate** `doctor`, `admin`. Nothing else is reachable at
the top level except two hidden protocol endpoints that installed configs call,
`hooks run` and `mcp serve`.

| Verb | Representative subcommands |
|---|---|
| `scan` | `repo`, `mcp` (exits 1 on a critical finding), `skills`, `runtime`, `monitors` (`list`, `add`, `pause`, `resume`, `remove`, `run`) |
| `agents` | `list`, `register`, `budget`, `lineage`, `quarantine`, `kill`, `resume` |
| `permit` | `grant`, `list`, `revoke`, `user`, `approvals` (`list`, `show`, `approve`, `deny`) |
| `declare` | `tool`, `triggers`, `scope`, `reference`, `boundary`, `source`, `escalation`, `principal` |
| `policy` | `packs`, `list`, `lint`, `validate` (runs the lint), `effective` (each layer's mode), `simulate`, `enforce`, `observe`, `compile`, `proposals` |
| `test` | `run`, `gate`, `baseline`, `suites`, `online`, `redteam` (exits 1 on an escape), `probes`, `action`, `boundary`, `rule` |
| `report` | `summary`, `status`, `evidence`, `verify`, `risk`, `obligations`, `frameworks`, `board`, `signoff`, `drift` |
| `admin` | `users` (`create`, `list`), `auth`, `db`, `jobs run-due`, `catalog`, `hooks`, `checkpoint`, `seed`, `mcp`, `version` |

`agentfox serve` runs `uvicorn` on `agentfox.gateway.app:app`, the same app object
`api/index.py` re-exports.

---

## 12. Database migrations — `migrations/versions/`

Alembic revisions, also shipped inside the wheel as `agentfox/_migrations`. Rough evolution
order: baseline schema → tracing links → policy hierarchy and agent controls → guardrail
feedback and suppressions → per-tenant audit chain → escalation hand-offs → source records →
business rules → knowledge boundaries → entitlement principals and grants → a cluster of
"org-scoped uniqueness was global" hardening migrations → GitHub and hosted-API integrations →
inter-agent messages → memory writes → policy canaries → eval annotations → the job queue →
the improvement loop → playground sandboxes → the hosted waitlist → judgment posture → tool
output trust → **source monitors** (`monitors`,
`alert_channels`, `github_connections.webhook_secret_encrypted`) → **probe targets**.

The Vercel deployment cannot run `alembic upgrade head` through normal channels (HLD §10);
`deploy/neon-catchup-*.sql` are the hand-applied catch-up scripts for that database.

---

## 13. API surface

Full detail: [Appendix C](api-spec.md), whose route tables are generated by
`scripts/api_routes.py --write`. Base `http://localhost:8080` self-hosted; `/api` = control
plane, `/v1` = inline enforcement (OpenAI/Anthropic wire-compatible). Credentials: agent key,
operator token, session cookie, plus the service secret (dashboard provisioning only) and the
cron secret (`/api/internal/jobs/run` only). Six roles (`owner`, `admin`, `security`,
`compliance`, `developer`, `auditor`); `auditor` can read and verify but never mutate.

| Surface | Representative endpoints |
|---|---|
| Inline (`/v1`) | `POST /v1/chat/completions`, `POST /v1/messages` (428 when held), `POST /v1/guard/input\|output\|tool_call\|memory_write\|agent_message`, `POST /v1/mcp/call`, `POST /v1/traces` (OTLP/HTTP) |
| Registry | `/api/agents`, `/api/tools`, `/api/mcp-servers`, `/api/findings`, `/api/approvals` (`/{id}` readable by the agent's own key, `/{id}/approve\|deny`) |
| Policy | `/api/policies`, `/api/policies/{key}/mode` (enforce needs a recorded simulation), `/api/policies/simulate`, `/api/policies/validate`, `/api/judgment/posture` |
| Evaluation | `/api/eval/*`, `/api/redteam/*`, `/api/probes/targets` (+ `/opt-in`, `/opt-out`, `/run`, `/campaigns`), `/api/probes/warning` |
| Monitoring & jobs | `/api/monitors` (+ `/pause`, `/resume`, `/run`), `/api/alerts/slack` (+ `/test`), `/api/jobs`, `/api/internal/jobs/run` (cron), `/api/integrations/github/webhook` (signed push), `/api/integrations/github/webhook-secret` |
| Audit & evidence | `/api/traces`, `/api/audit/*`, `/api/evidence`, `/api/export/siem` |
| Public | `/api/public/showcase` (rate-limited, read-only), `/api/playground/*`, `/api/waitlist` |
| Platform | `/api/health`, `/api/version`, `/api/detectors`, `/api/providers`, `/metrics` |

Conventions: errors are FastAPI `{"detail": …}` bodies; `/v1/*` returns 429 with
`Retry-After` when admission control sheds load and 503 when degraded under `fail_mode=closed`;
privileged operator actions are recorded on the audit chain (`prove/audit/operator_log.py`
declares them), including evidence downloads.

---

## 14. Deployment artifacts — `deploy/`

- **`docker-compose.yml`** — `db` (postgres:16-alpine), `opa` (openpolicyagent/opa:0.70.0,
  optional), `gateway` (port 8080), `dashboard` (port 3000). The gateway runs with
  `AGENTFOX_ENVIRONMENT=production`, `AGENTFOX_ALLOW_EGRESS=false`,
  `AGENTFOX_DEFAULT_POLICY_MODE=observe` and `AGENTFOX_FAIL_MODE=open`, and compose refuses to
  start until `AGENTFOX_SERVICE_AUTH_SECRET` and `AGENTFOX_AUDIT_SIGNING_KEY` are set
  (`${VAR:?…}`).
- **`Dockerfile`** (gateway) — `python:3.12-slim`; copies `migrations/` and `src/`; can bake in
  ML detector weights at build time. Its `CMD` serves the app and nothing else: it no longer
  seeds demo data on boot (`docker compose exec gateway agentfox admin seed` does, on demand),
  and the first operator is created with `agentfox admin users create`.
- **`Dockerfile.dashboard`** — `node:22-alpine`, Next.js standalone build.
- `render.yaml`, `fly.dashboard.toml`, `README-dashboard.md` — the hosted dashboard; the hosted
  gateway is `api/` on Vercel (HLD §10).

---

## 15. Monitoring and live probes — `src/agentfox/capabilities/monitoring/`, `evaluation/live_probes.py`

**Monitors.** A `Monitor` row watches one source: `github_repo` (`owner/repo`), `hosted_api`
(an OpenAPI URL), `mcp_server` (a registered server's name) or `deployed_agent` (a
`ProbeTarget` id). Monitors are created when a source is connected and scanned, or by hand
(`POST /api/monitors`, `agentfox scan monitors add`). `monitoring/service.py:run_monitor` runs
one in three steps, the same for every kind:

1. **Observe** — the kind's runner (`register_kind`) re-reads the source: downloads and rescans
   the repository archive (`github.py`), refetches the spec (`discovery/openapi.py`, through
   `guarded_get`), or reads a remote MCP server's tool listing (`mcp_live.py`, through
   `guarded_post`).
2. **Diff** — `snapshots.diff_repo` / `diff_api` compare the snapshot with `baseline_json`. The
   first run only stores a baseline.
3. **Reconcile** — each new condition (`monitor_lethal_trifecta`, `monitor_new_tool`,
   `monitor_governance_removed`, `monitor_api_destructive_endpoint`, …) is raised through
   `prove.findings.raise_finding` keyed by the condition, so a recurrence reopens the same
   finding; an open finding whose condition cleared is resolved as automated.

A run that fails never closes a finding and never replaces the baseline. After
`monitor_failure_threshold` (default 3) failures in a row it raises one `monitor_failing`
finding, closed by the next successful run. A run that could not decide (a disabled probe
target, live probes off) is `inconclusive`.

**Scheduling.** The `monitors.run` job runs a tenant's due monitors; each monitor keeps its own
interval (clamped between 5 minutes and 30 days). `jobs/scheduler.py` fills the queue from
per-tenant `JobSchedule` rows; nothing runs unless something triggers the runner:
`/api/internal/jobs/run` (Vercel cron, and `.github/workflows/monitors.yml` every 30 minutes)
or `agentfox admin jobs run-due` on a self-hosted scheduler. A signed GitHub push to the watched
branch queues an immediate rescan of that commit.

**Alerts.** Findings a run opens, reopens or closes go to the deployment's finding webhook
(`core/webhooks.py`) and, when configured, to Slack (`monitoring/alerts.py`): the deployment's
`AGENTFOX_SLACK_WEBHOOK_URL` and a tenant's own `AlertChannel` (encrypted, `https://hooks.slack.com/`
only). Messages are queued on the session and sent after commit by one daemon worker with a
bounded queue; with `allow_egress` off nothing is sent.

**Live probes.** `evaluation/live_probes.py` sends a fixed library of adversarial messages to a
deployed agent and scores what comes back (a reversed canary code, forbidden tool calls, leak
markers). A `ProbeTarget` is created disabled; `opt_in` records who agreed, when, and the
warning text, and creates the target's `deployed_agent` monitor. The `http` adapter posts only
to the host registered at opt-in, through `guarded_post` (no redirects); changing the URL clears
the opt-in. Per-target limits are clamped to hard caps (probes per run, rate, minimum interval,
timeout; plus targets and wall-clock per job), and `AGENTFOX_LIVE_PROBES_ENABLED=false` turns
every target off. Each run is a `redteam_campaigns` row (`runner="live"`); an escape opens a
`live_probe_escape` finding, a later contained run closes it, and an endpoint error is recorded
as `error`, which does neither. `evaluation/showcase.py` runs the same thing against the demo
agent in a dedicated tenant for the public `/live` page, only when
`AGENTFOX_SHOWCASE_ENABLED` is set.

---

## 16. See also

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — the code map and one tool call traced through it
- [docs/architecture/high-level-design.md](high-level-design.md) — architecture shape, principles, integration surfaces
- [docs/design/oss-register.md](../design/oss-register.md) — full OSS licence/health register
- [docs/design/control-catalog.md](../design/control-catalog.md) — 43 controls × 7 frameworks
- [docs/architecture/api-spec.md](api-spec.md) — full API specification
- [docs/architecture/data-model.md](data-model.md) — full data model
- [docs/architecture/threat-model.md](threat-model.md) — full threat model
- [docs/design/production-readiness-review.md](../design/production-readiness-review.md) — gaps and priorities
