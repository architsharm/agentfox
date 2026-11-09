# Low-Level Design (LLD)

**Subsystem internals:** the enforcer, approvals, the detector pipeline, the audit chain,
`auto()`, LangGraph, the policy engine, the gateway, migrations, deployment artifacts and
monitoring. Read [ARCHITECTURE.md](../../ARCHITECTURE.md) first: it is the one home for the
package layout, the domain model and the request path, and this document does not repeat them.
The design rationale is in [high-level-design.md](high-level-design.md). Modules and functions
are named rather than line numbers, because those drift. If this document and the code
disagree, the code is right.

---

## 1. Package layout — `src/agentfox/`

The layers, the import rules and a row per package with where to start reading are in
ARCHITECTURE.md's [code map](../../ARCHITECTURE.md#code-map).

---

## 2. Tests

The test layout is in ARCHITECTURE.md's [code map](../../ARCHITECTURE.md#code-map) (the
`tests/` row); counts are generated into [`docs/status.md`](../status.md).

---

## 3. The `Enforcer` — `src/agentfox/runtime/enforcement/`

The single code path every integration surface converges on (HLD §5). `Enforcer` is one class
assembled from mixins, one module per stage (the package docstring lists them):

| Module | Methods | Role |
|---|---|---|
| `enforcer.py` | `Enforcer.__init__(session, pipeline=None)`, `resolve(...)`, `evaluate(...)` | Identity resolution, and **`evaluate()`, where every decision is made and recorded**. It checks the kill switch first, then runs the detector pipeline, suppressions, `check_capability`, every registered content check for the surface, the ladder checks (business ladders) and action analysis, resolves the policy hierarchy (`policies_in_force`), combines verdicts, redeems a presented approval (§3.1), and persists the `Decision`, findings, any `ApprovalRequest`, a guardrail span and the audit entry. |
| `completion.py` | `preflight(...)`, `call_provider(...)`, `run_completion(...)`, `_answerability_gate`, `_finish_completion` | **The completion orchestrator.** `preflight` runs kill switch, budget, answerability, taint marking and per-message `evaluate()`, shared by the buffered and streaming paths; `call_provider` wraps the provider in the breaker from `runtime/reliability.py`. |
| `streaming.py` | `run_completion_stream(...)` | The SSE variant: the same gates, chunked. |
| `tool_calls.py` | `guard_tool_call(...)` | The pre-execution tool-call gate: kill switch, argument provenance (`TaintTracker.taint_arguments`), `TaintTag` rows and a lineage edge, loop governance, then `evaluate(surface="tool_args")`. |
| `surfaces.py` | `check_content`, `check_conversation_window`, `guard_memory_write`, `guard_completion`, `guard_reasoning`, `guard_file`, `guard_agent_message` | The other surfaces: retrieved content, multi-turn windows, memory writes, a completion handed in by the caller, model reasoning, files, inter-agent messages. |
| `../checks.py` | `BUILTIN_CHECK_MODULES`, `checks_for(surface, kind)` | The checks `evaluate()` folds into one record come from the registry (`platform/checks.py`), in `order`: `grounding.evidence` (10), `grounding.disclosure` (20), `grounding.commitments` (30), `grounding.context` (40), `containment.control_flow` (50), `grounding.sycophancy` (60), `detection.trajectory` (70); then the ladder check `business.ladders`. |
| `limits.py` | `_control_verdict`, `_budget_gate`, `_charge_budget` | Kill switch / quarantine, and hard spend budgets. |
| `findings.py` | `_raise_detection_finding`, `_record_degradation`, `_persist_detectors` | Detector-run rows, degradation records, detection findings. |
| `background.py`, `summary.py` | | Work after the response once no check is in flight (the classifier's advisory backstop); a short masked preview of the user's message for the runs list. |
| `approvals.py` | `held_call(...)` | What an escalation is filed under: the tool and its arguments, or for a held message `message:<surface>` with a masked excerpt and the content's SHA-256. |
| `rules.py`, `result.py` | `_fallback_policies`; `EnforcementResult`, `PreflightOutcome`, `StreamEvent` | The in-memory fallback when no pack is bound (the built-in packs whose `fallback` names the agent's risk tier, forced to observe); result types. |

**The kill switch is checked inside `evaluate()`, before anything else**, so a killed or
quarantined agent is refused on every surface that reaches a decision (the guard endpoints,
memory writes and agent messages included), not only on completions and tool calls.

**Design note worth carrying into any future refactor**: new surfaces call `preflight`,
`evaluate` or one of the `guard_*` methods; they never reimplement gate logic. `auto()` once
carried a partial copy that drifted from the gateway's, which is why `preflight` is shared.

### 3.1 Approvals and redemption — `platform/identity/service.py`

An escalation files an `ApprovalRequest` (`request_approval`) bound to the agent and to what
`held_call` returned. `resolve_approval` approves or denies it:

- Approving is refused with `AgentStopped` while the agent is killed or quarantined; denying is
  always allowed.
- An approval restarts its clock on approval: it stays redeemable for `REDEEM_WINDOW_MINUTES`
  (30). Unanswered approvals expire (`expire_stale_approvals`) and expiry denies.

A retry presents the approval: `X-AgentFox-Approval` on the proxy routes, `approval_id` in the
`/v1/guard/*` body, or the SDK's `wait_for_approval`, which polls `GET /api/approvals/{id}` with
the agent's own key (an agent may read only its own approvals). Inside `evaluate()`, only when
the call would otherwise escalate, `redeem_approval` checks that the approval is `approved`,
unexpired, for the same agent, tool and canonicalised arguments (or the same content digest
for a held message), then flips it to `used` with a conditional `UPDATE … WHERE status =
'approved'`, so two racing retries cannot both spend it. A redeemed call is allowed with the
`approval.redeemed` rule fired. A retry of the very call a person denied is blocked with the
`approval.denied` rule and their rationale (`denial_of`), and files no new approval; anything
else escalates again and the decision's reason says why the approval was not used. An approval can therefore never make a call more permitted than a
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
  `presidio.py`, `rails.py` (NeMo Guardrails / Guardrails AI), `hub.py` (loading a Guardrails AI
  validator for `rails.guardrails_ai`, telemetry off).
- **`validators/`** — small checks with a settings schema, registered by name and through the
  `agentfox.validators` entry point. `builtin/` holds ports of the Guardrails AI validators by
  family (text, structure, sql, web, lists, disclosure, models, judges). One with no settings can
  run as a `validator.<name>` detector; one with settings runs as a custom rule of kind
  `validator` (`custom.validators`).
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

The tables, their key columns and their invariants are in [Appendix D](data-model.md). Tenant
isolation is applied at the session, not per query (see ARCHITECTURE.md's
[invariants](../../ARCHITECTURE.md#invariants-and-cross-cutting-concerns)).

---

## 6. Audit chain internals — `src/agentfox/platform/ledger/chain.py`

The tamper-evident hash chain, the mechanism behind the "prove what happened" claim:

```
payload_digest = SHA-256(canonical_json(payload))
subject_digest = SHA-256(subject_id or "")
digest (v2)    = SHA-256(canonical_json(["agentfox.audit.v2", seq, occurred_at_iso,
                         actor_type, actor_id, action, subject_type, subject_digest,
                         payload_digest, prev_digest]))
```

v2 covers who acted and on what. Entries written before it used v1,
`SHA-256(seq | occurred_at_iso | action | payload_digest | prev_digest)`, and still verify
under it; the scheme is read off the stored digest (exported as `digest_version`), and a
v1 entry after a v2 one is a break, so a new entry cannot be relabelled v1 to dodge the
actor check.

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
  recomputes the chain from raw entries with no dependency on the application, and checks
  every file against the manifest's SHA-256 list (`agentfox report verify` verifies the
  stored chain in place). With the audit signing key it also checks `manifest.sig` (an
  HMAC over the manifest, so over every file) and the checkpoints; building a package
  first checkpoints its newest entry.

`ee/src/agentfox_ee/evidence/package.py` (Enterprise) builds auditor-ready export packages (a
manifest with a per-file SHA-256, chain-of-custody metadata), optionally scoped to one agent.
`platform/ledger/trace.py` is the execution tracer (`start_trace`/`add_span`/`end_trace`);
`exporters/otel.py` ingests OTLP (JSON or protobuf, optionally gzipped). Traces answer "what happened, in what order"; the chain answers "can I
prove this record hasn't been altered."

---

## 7. `agentfox.auto()` — monkey-patch mechanism

The path one call takes through the patches (pre-flight, provider call, post-flight, tool
calls) is ARCHITECTURE.md's [request path (a)](../../ARCHITECTURE.md#a-a-tool-call-under-agentfoxauto).
This section covers what that trace leaves out.

`frameworks/autoguard/__init__.py`, `auto(agent=None, *, mode="policy", environment=None,
session_id=None, intent=None, register=True, quiet=False, …)`:

1. Detects installed frameworks from `sys.modules` (`autoguard/environment.py`,
   `_FRAMEWORK_MODULES`). Looks for an account key (`autoguard/remote.py`); with one, every
   check is sent to that account's gateway (`/v1/guard/input`, `/output`, `/tool_call`, with
   `in_process`, `waive_ungranted` and `declare` so the gateway applies the same mode rule,
   carve-out and tool registration) instead of a local `Enforcer`; budget charging and the
   conversation-window check are local only.
2. Guesses an agent slug (`default_agent_slug`): env var → entrypoint script name →
   `"default-agent"`, registers it (unless `register=False`) and warms opted-in detectors in
   the background.
3. Streams: tool-call fragments are collected by `_chunk_tool_calls` before they are checked.
4. An output redaction (`redact` / `mask` / `tokenize` on the output surface) is applied, not
   only recorded: `_applied_rewrite` picks the enforcer's `EnforcementResult.content` under the
   same mode rule as a block, and `shapes._rewrite_text` writes it into the client's own
   response object (`choices[0].message.content`; Anthropic text blocks, the first taking the
   whole rewrite and the others emptied; `AIMessage.content`). The recorded conversation turn
   holds the redacted text. A response that cannot be rewritten is refused with `Blocked`; a
   streamed response, whose chunks are already with the caller, raises `Blocked` at the end of
   the stream instead (the gateway's buffered streaming is the way to get redacted streamed
   text).

The default mode is `policy`: `Blocked` is raised only when an enforce-mode policy, the kill
switch or a budget cap stops the call, and an agent holding no grants at all is not refused
for a missing grant until its first grant. `mode="observe"` never raises; `mode="enforce"`
raises on anything a policy would block. Redaction follows the same rule: the enforced verdict
in `policy` mode, the effective verdict in `enforce`, never in `observe`. `off()` reverses
every patch.

---

## 8. LangGraph integration — `src/agentfox/frameworks/langgraph.py`

LangGraph is an optional import; trace identity lives **in graph state**
(`STATE_KEY = "__agentfox__"`) so it survives checkpointing, resumption and time-travel;
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

**A judge outage is a degraded detector.** An LLM judge (`injection.judgment`, `pii.judgment`,
a judge validator, a workspace rule that uses one) that times out, errors or reports
`status="unavailable"` with `cause="outage"` is listed in `degraded` and in
`PipelineResult.judge_outage` with the entity types it would have produced, so both `fail_mode`
sources above treat "unreachable" and "timed out" alike. The judgment posture's `fail_closed` is a
third source, for judges only: when it is on and the decision is enforcing, an enforcing pack with
an enabled, non-allow detection rule on this surface that those entities could fire blocks the call
as `pipeline.judge_outage`. It adds a block and never removes one, so it cannot loosen a closed
deployment or pack. A payload the egress gate refused (`cause="refused"`, e.g. `pii_egress=block`
on text with personal data) or a tier with no key (`not_configured`) is never an outage.

**Saving and promoting are separate.** Saving appends an immutable version and leaves what is in
force unchanged (`save_policy(..., rebind=False)`). Promotion (`POST /api/policies/{key}/mode`,
`agentfox policy enforce`) is the only way to change it, and promoting to `enforce` over HTTP
requires a recorded simulation of exactly that version's rules; demoting to `observe` never
does. The hierarchy is enforced at runtime: `evaluate()` resolves the same layers
`agentfox policy effective` prints.

---

## 10. Gateway composition — `src/agentfox/apps/gateway/`

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
  `degradation_gate` (applies the fail mode, returns 503 or stamps `X-AgentFox-Degraded`) and
  `admission_gate` (load shedding, 429 with `Retry-After`).
- The lifespan warms detectors (`warm_all`).
- Routers, one per file in `routes/`: `inline`, `registry`, `policy`, `evaluation`,
  `governance`, `tuning`, `escalation`, `answerability`, `onboarding`, `onboarding_flow`,
  `provenance`, `entitlement`, `integrations`, `jobs`, `discovery`, `memory`, `messaging`,
  `proposals`, `posture`, `coverage`, `metrics`, `access`, `library`, `custom_rules`,
  `features`, `checks`, `imports`, `protection`, `rule_examples`, `workspace`,
  `platform_hooks` (the `/v1/hooks/*` routes and the connection admin routes), `probes`.
  Unauthenticated by design: `playground`, `waitlist`, and `probes.public_router`
  (`GET /api/public/showcase`). Then each extension's routers (Enterprise: compliance,
  evidence, monitors, access checks).
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

## 11. CLI command tree — `src/agentfox/apps/cli/`

`main.py` registers every command; `layout.py:apply_layout` re-registers them under the
thirteen visible verbs, in the panels ARCHITECTURE.md lists (Start, See, Watch, Contain,
Prove, Operate). Nothing else is reachable at the top level except `demo` (hidden) and two
hidden protocol endpoints that installed configs call, `hooks run` and `mcp serve`. Every
subcommand, checked against the live CLI, is in
[plugins/shared/reference/cli.md](../../plugins/shared/reference/cli.md).

`agentfox serve` runs `uvicorn` on `agentfox.apps.gateway.app:app`, the same app object
`api/index.py` re-exports. `agentfox init` without `--key` sets up a local database; with
`--key` it maps the repository, reports it to the account and stays connected to run the attack
test (`capabilities/onboarding/client.py`). `agentfox up` is the guided setup
(`apps/cli/wizard/`), its answers in `.agentfox/up.json` and credentials in
`.agentfox/agentfox.env`.

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
`alert_channels`, `github_connections.webhook_secret_encrypted`) → **probe targets** → custom
rules, detector settings and custom models → retention runs and control reviews → onboarding
sessions, projects and runs → platform connections.

The Vercel deployment cannot run `alembic upgrade head` through normal channels (HLD §10);
`deploy/neon-catchup-*.sql` are the hand-applied catch-up scripts for that database.

---

## 13. API surface

[Appendix C](api-spec.md) is the one home for credentials, roles, headers and every route (its
route tables are generated by `scripts/gen/api_routes.py --write`). `/v1` is inline enforcement,
wire-compatible with the OpenAI and Anthropic SDKs; `/api` is the control plane the dashboard,
CLI and SDK all use.

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
- `model-server/`: compose files for `agentfox serve models` (CPU and GPU).
- `aws-agentcore-interceptor/`: the AgentCore Gateway REQUEST interceptor Lambda and its SAM
  template; it asks a gateway's `/v1/guard/tool_call` and fails closed by default.

---

## 15. Monitoring and live probes — `ee/src/agentfox_ee/monitoring/` (Enterprise), `capabilities/evaluation/live_probes.py`

**Monitors.** A `Monitor` row watches one source: `github_repo` (`owner/repo`), `hosted_api`
(an OpenAPI URL), `mcp_server` (a registered server's name) or `deployed_agent` (a
`ProbeTarget` id). Monitors are created when a source is connected and scanned, or by hand
(`POST /api/monitors`, `agentfox scan monitors add`). `ee/src/agentfox_ee/monitoring/service.py:run_monitor` runs
one in three steps, the same for every kind:

1. **Observe** — the kind's runner (`register_kind`) re-reads the source: downloads and rescans
   the repository archive (`capabilities/monitoring/github.py`), refetches the spec
   (`capabilities/discovery/openapi.py`, through `guarded_get`), or reads a remote MCP server's
   tool listing (`ee/…/monitoring/mcp_live.py`, through `guarded_post`).
2. **Diff** — `capabilities/monitoring/snapshots.py` (`diff_repo` / `diff_api`) compare the snapshot with `baseline_json`. The
   first run only stores a baseline.
3. **Reconcile** — each new condition (`monitor_lethal_trifecta`, `monitor_new_tool`,
   `monitor_governance_removed`, `monitor_api_destructive_endpoint`, …) is raised through
   `platform.ledger.findings.raise_finding` keyed by the condition, so a recurrence reopens the same
   finding; an open finding whose condition cleared is resolved as automated.

A run that fails never closes a finding and never replaces the baseline. After
`monitor_failure_threshold` (default 3) failures in a row it raises one `monitor_failing`
finding, closed by the next successful run. A run that could not decide (a disabled probe
target, live probes off) is `inconclusive`.

**Scheduling.** The `monitors.run` job runs a tenant's due monitors; each monitor keeps its own
interval (clamped between 5 minutes and 30 days). `platform/jobs/scheduler.py` fills the queue from
per-tenant `JobSchedule` rows; nothing runs unless something triggers the runner:
`/api/internal/jobs/run` (Vercel cron, and `.github/workflows/monitors.yml` every 30 minutes)
or `agentfox admin jobs run-due` on a self-hosted scheduler. A signed GitHub push to the watched
branch queues an immediate rescan of that commit.

**Alerts.** Findings a run opens, reopens or closes go to the deployment's finding webhook
(`core/webhooks.py`) and, when configured, to Slack (`ee/src/agentfox_ee/monitoring/alerts.py`): the deployment's
`AGENTFOX_SLACK_WEBHOOK_URL` and a tenant's own `AlertChannel` (encrypted, `https://hooks.slack.com/`
only). Messages are queued on the session and sent after commit by one daemon worker with a
bounded queue; with `allow_egress` off nothing is sent.

**Live probes.** `capabilities/evaluation/live_probes.py` sends a fixed library of adversarial messages to a
deployed agent and scores what comes back (a reversed canary code, forbidden tool calls, leak
markers). A `ProbeTarget` is created disabled; `opt_in` records who agreed, when, and the
warning text, and creates the target's `deployed_agent` monitor. The `http` adapter posts only
to the host registered at opt-in, through `guarded_post` (no redirects); changing the URL clears
the opt-in. Per-target limits are clamped to hard caps (probes per run, rate, minimum interval,
timeout; plus targets and wall-clock per job), and `AGENTFOX_LIVE_PROBES_ENABLED=false` turns
every target off. Each run is a `redteam_campaigns` row (`runner="live"`); an escape opens a
`live_probe_escape` finding, a later contained run closes it, and an endpoint error is recorded
as `error`, which does neither. `apps/showcase.py` runs the same thing against the demo
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
- [docs/design/gap-analysis.md](../design/gap-analysis.md) — what is still open
