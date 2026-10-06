# Architecture

This document is for someone who has never seen AgentFox and wants to change it. It
describes the product in one page of concepts, traces a tool call through the code, gives
a map of the source tree, and lists the invariants a change must not break. It names
modules and functions rather than line numbers, so it stays true as files grow. If it
disagrees with the code, the code is right; please fix this file in the same PR.

Deeper material: [docs/architecture/high-level-design.md](docs/architecture/high-level-design.md)
(design rationale, deployment topology), [docs/architecture/low-level-design.md](docs/architecture/low-level-design.md)
(class-level detail), [docs/status.md](docs/status.md) (what is built, generated
by probe).

## What AgentFox is

AgentFox is a Python library and a self-hosted control plane that decides, at runtime,
whether an AI agent may make the call it is about to make. It sits on the agent's model and
tool calls (in-process via `agentfox.auto()`, or over HTTP via a gateway), evaluates each call
against declared tools, capability grants, argument provenance, detectors and policy, writes
the decision to a hash-chained audit log, and raises a finding when something was stopped.
Its central idea is that **containment does not depend on detection**: a transfer whose
recipient came out of a retrieved document is refused because of where the value came
from, even when no detector recognised the payload.

The product is organised as four steps, which are also the CLI's panels (`agentfox --help`,
built in [`src/agentfox/apps/cli/layout.py`](src/agentfox/apps/cli/layout.py)) and the website's docs
order:

| Step | Question | Where it lives |
|---|---|---|
| **See** | What agents, tools and MCP servers do I have, and what changed? | `discovery/`, `registry/`, `monitoring/` (`agentfox scan`, `agentfox scan monitors`, `agentfox agents`) |
| **Watch** | What are they doing right now? | `runtime/`, `detection/`, `gateway/` (`agentfox serve`, `agentfox findings`) |
| **Contain** | What may each one do? | `identity/`, `policy/`, `containment/` (`agentfox permit`, `declare`, `policy`) |
| **Prove** | Can I show what happened? | `prove/`, `evaluation/` (`agentfox report`, `agentfox test`) |

## Domain model

```
  Agent ─────────── Identity ────────── Capability grant
  (registry)        (credential)        (tool key, argument limits, max taint)
    │                                         │
    │ asks to call                            │ checked by identity.check_capability
    ▼                                         ▼
  Tool ── impact: read | write | high_impact | irreversible, output_trust
    │
    │ each argument carries provenance (TaintMark):
    │   none < user < retrieved < tool_result < subagent < memory
    ▼
  Enforcer.evaluate ◄── detectors (Detection)      ◄── policy packs → rules (effect, mode)
    │
    ▼
  Decision: verdict (applied) + effective_verdict (if everything enforced) + rules_fired
    ├──► AuditEntry       hash-chained, append-only
    ├──► Finding          deduplicated by fingerprint
    └──► ApprovalRequest  when the verdict is escalate
                               ▲
  ChangeProposal ─────────────┘ the improvement loop proposes grants and declarations;
                                a person approves; applying one is itself audited
```

| Concept | In plain words | Owned by |
|---|---|---|
| **Agent** | Something that makes model and tool calls. Registered explicitly, or recorded as a "shadow" agent the first time it is seen. | `core/models/registry.py` (`Agent`), `registry/service.py` (`observe_agent`, `register_agent`) |
| **Identity, credential** | The non-human identity an agent authenticates as (`nom_agt_…` keys, argon2-hashed). | `core/models/identity.py`, `identity/service.py` (`issue_credential`, `verify_credential`) |
| **Tool, impact** | A callable the agent can invoke. `impact` is the declared blast radius every containment rule reasons over; an undeclared tool is treated as `read` and flagged `tool_known=False`. `output_trust` says whether values copied from its output taint later arguments. | `core/models/registry.py` (`Tool`), `cli/commands/tools.py` (`agentfox declare tool`) |
| **Capability grant** | Permission for one identity to call one tool, with optional argument limits and a provenance ceiling (`--max-taint`). No matching grant means default deny. The one softening: `auto()` in its default mode does not raise for an agent that holds no grants at all, until its first grant. | `core/models/identity.py` (`Capability`), `identity/service.py` (`grant_capability`, `check_capability`), `cli/capability_cli.py` |
| **Provenance / taint** | Where each argument's value came from. Inferred from the conversation (a value copied out of a tool result is `tool_result`) or declared by the caller. `taint_scope` chooses per-session or per-argument reading. | `detection/taint.py` (`TaintTracker`, `TaintMark`), `core/vocab.py` (`TAINT_ORDER`, `taint_rank`), `policy/taint_view.py` |
| **Detector, detection** | A check over text on one surface (`input`, `output`, `retrieved`, `tool_result`, `tool_args`, …) that returns scored entities. Run in a budgeted, concurrent pipeline. | `detection/base.py` (`Detector`, `BaseDetector`), `detection/pipeline.py` (`DetectorPipeline`), `detection/detectors/`, `detection/adapters/` |
| **Policy, pack, rule, mode** | A policy document (a "pack") is YAML: rules with a `when` condition and an `effect` (`allow` … `escalate`, `block`). Each bound pack is in `observe` (records what it would do) or `enforce` (applies it). Shipped packs: `baseline`, `eu-ai-act-high-risk`, `tool-containment`, `coding-agent`. Versions are immutable. | `policy/model.py` (`PolicyDocument`, `Rule`, `Condition`), `policy/engine.py` (`NativePolicyEngine`, `combine`), `policy/store.py` (`active_policies`, `set_mode`, and `load_version_document`, the one loader for stored versions), `policies_data/*.yaml` |
| **Decision, verdict** | One row per evaluated surface. `verdict` is what was applied; `effective_verdict` is what would have happened with every pack enforcing. Records every policy version in force, so it can be replayed. | `core/models/policy.py` (`Decision`), `runtime/enforcement/result.py` (`EnforcementResult`) |
| **Finding** | A problem a person should look at, deduplicated by fingerprint and counted on recurrence. A refused tool call is a containment finding titled by what refused it. | `core/models/registry.py` (`Finding`), `prove/findings.py` (`raise_finding`), `containment/findings.py` (`raise_containment_findings`) |
| **Approval** | A held call waiting for a human; `timeout_action` defaults to deny. Approved, it lets exactly one retry of the same call through, then reads `used`. | `core/models/identity.py` (`ApprovalRequest`), `identity/service.py` (`request_approval`, `resolve_approval`, `redeem_approval`) |
| **Monitor** | A connected source re-checked on a schedule (a GitHub repo, a hosted API spec, a remote MCP server, a deployed agent). Each run is diffed against the last; what appeared becomes a finding, what cleared closes. | `core/models/registry.py` (`Monitor`, `AlertChannel`), `monitoring/service.py` (`run_monitor`, `run_due`) |
| **Probe target** | A deployed agent's endpoint that live red-team probes may be sent to, after an explicit, recorded opt-in. | `core/models/evaluation.py` (`ProbeTarget`), `evaluation/live_probes.py` (`opt_in`, `run_target`) |
| **Proposal** | A change the platform wants to make (a grant learned from traffic, a declaration, a tuning change), with evidence. Filed → proven → approved → applied → verified, or rolled back. Loosening is never applied automatically. | `core/models/improvement.py` (`ChangeProposal`), `improvement/proposals.py`, `improvement/traffic.py` (`propose_from_traffic`) |
| **Trace, span** | The execution record of one request: an llm span, guardrail spans, tool spans. | `core/models/audit.py`, `prove/audit/trace.py` (`start_trace`, `add_span`, `end_trace`) |
| **Audit chain, evidence** | Append-only hash chain over every decision and operator action; evidence packages ship a stdlib-only `verify_chain.py`. | `prove/audit/chain.py` (`append`, `verify`), `prove/audit/evidence.py`, `prove/audit/operator_log.py` |

## The request path

There is one enforcement code path. Every surface (the `auto()` patches, the gateway, the
SDK, the LangGraph guard, the MCP governor, the coding-agent hook daemon) builds an
`Enforcer` (`runtime/enforcement/enforcer.py`) on a database session and calls one of its
methods. Everything ends in `Enforcer.evaluate()`, which is where a decision is made and
recorded. New surfaces must call these methods, not reimplement them.

### (a) A tool call under `agentfox.auto()`

1. `agentfox.auto()` resolves lazily from `src/agentfox/__init__.py` to
   `runtime/autoguard/__init__.py:auto`. It registers the agent (`registry/service.py:register_agent`),
   counts bound policies, and runs `_PATCHERS` (`_patch_openai`, `_patch_anthropic`,
   `_patch_litellm`, `_patch_langchain`), which replace e.g. `openai.resources.chat.completions.Completions.create`
   with a wrapper built by `_sdk_method`.
2. The wrapper calls `_govern` (sync) or `_agovern` (async). A context variable,
   `_IN_AGENTFOX`, stops AgentFox's own model calls from being governed recursively.
3. **Pre-flight.** `_preflight` → `_run_preflight` opens a session (`core/db.py:session_scope`)
   and calls `Enforcer.preflight` (`runtime/enforcement/completion.py`): resolve the agent,
   kill switch/quarantine (`limits.py:_control_verdict`), hard budget (`_budget_gate`),
   answerability (`_answerability_gate`), taint-mark every message, then `evaluate()` per
   message. If the outcome must stop the call under the current mode (`_raises`), `Blocked`
   is raised before the provider is called.
4. The real provider call runs.
5. **Post-flight.** `_postflight` evaluates the response text (`_evaluate_output` →
   `Enforcer.evaluate` on the `output` surface), then reads tool calls out of the response
   (`runtime/autoguard/tool_calls.py:_tool_calls_of`, OpenAI `tool_calls` or Anthropic
   `tool_use`) and hands them to `_govern_tool_calls`.
6. `_govern_tool_calls` registers unseen tools with an inferred impact (`_register_tool`,
   using `integrations/mcp.py:infer_impact`) and calls `Enforcer.guard_tool_call` for each,
   with a `TaintTracker` rebuilt from the request's conversation (`tool_calls.py:_provenance_of`).
7. `guard_tool_call` (`runtime/enforcement/tool_calls.py`) checks the kill switch again,
   marks each argument's provenance (`TaintTracker.taint_arguments`), writes `TaintTag`
   rows and a lineage edge, and calls `evaluate(surface="tool_args", …)`.
8. Inside `evaluate` (`enforcer.py`), in order: the detector pipeline
   (`DetectorPipeline.run`, budgeted by a per-request `LatencyLedger`), suppressions,
   `identity.check_capability`, the content checks from `checks.py`, business ladders and
   action analysis, then a `PolicyInput` evaluated by every bound pack
   (`policy/store.py:active_policies`, `NativePolicyEngine.evaluate`, `combine`). If no
   pack is bound, an in-memory fallback (`rules.py:_fallback_policies`) applies `baseline`
   in observe. A missing grant then overrides the policy result with
   `capability.default_deny` or `capability.constraint_violated`.
9. `evaluate` persists: a `Decision` row; the trace's verdict is raised; a detection finding
   if a detector rule changed the outcome (`_raise_detection_finding`); containment
   findings for a refused tool call (`containment/findings.py:raise_containment_findings`
   → `prove/findings.py:raise_finding`); an `ApprovalRequest` on escalate; a guardrail span;
   and finally `prove/audit/chain.py:append(session, "decision.<verdict>", …)`.
10. Back in `_govern_tool_calls`, a `tool` span records what this process actually did,
    and `Blocked` is raised if the mode says so. In the default `policy` mode, an agent with
    no grants at all is not refused for a missing grant (recorded as would-have-blocked);
    its first grant turns default-deny on.

### (b) `POST /v1/guard/tool_call` on the gateway

1. `gateway/app.py:create_app` builds the FastAPI app (`app` at module bottom; `agentfox serve`
   and `api/index.py` both serve it). Two middlewares run first for `/v1/*` only:
   `degradation_gate` (probes dependencies, applies the fail-open/closed policy, returns 503
   or stamps `X-Nometria-Degraded`) and `admission_gate` (load shedding, 429).
2. The route `guard_tool_call` in `gateway/routes/inline.py` takes a `GuardToolCallRequest`
   body (`agent`, `tool`, `arguments`, `provenance`, `intent`, …). Its dependencies are
   `gateway/deps.py:db` (a session from `core/db.py:get_session`, committed when the
   response is produced) and `agent_credential`, which resolves the bearer key (one that does
   not verify is a 401) and binds the session to that agent's tenant (`core/tenancy.py:bind_session`) and judgment posture.
3. The handler builds `Enforcer(session)`, resolves the agent, opens a trace
   (`prove/audit/trace.py:start_trace`) and calls `Enforcer.guard_tool_call` with the
   caller's declared `provenance`. From here it is steps 7–9 above, unchanged.
4. The result is serialised with `gateway/verdicts.py:with_verdict_aliases` (which adds the
   applied/would-be verdict names) and returned: `verdict`, `effective_verdict`,
   `rules_fired`, `decision_id`, and `approval_id` when escalated.

The drop-in proxy routes (`/v1/chat/completions`, `/v1/messages`, same file) follow
`Enforcer.run_completion` / `run_completion_stream`, which wrap the same `preflight`, a
provider call through `providers/` with the circuit breaker in `runtime/reliability.py`,
and the same post-flight.

## Code map

All paths are under `src/agentfox/` unless they start at the repo root.

| Package | What lives there | Start reading at |
|---|---|---|
| `core/` | Settings (`AGENTFOX_*` env, `agentfox.toml`), engine and sessions, ORM models for every table, tenancy, ids, the shared vocabulary (surfaces, taint order, effect ranks, comparators), outbound URL safety, finding webhooks. Imports nothing outside `core`. | `config.py:Settings`, `db.py:get_sessionmaker`, `models/`, `tenancy.py`, `vocab.py` |
| `fixtures/` | The deterministic demo world (agents, tools, grants, policies, an eval suite) that `agentfox demo`, the playground and the tests seed. | `seed.py:seed` |
| `runtime/` | The request path. `enforcement/` is the `Enforcer` split into mixins (`enforcer`, `tool_calls`, `surfaces`, `completion`, `streaming`, `checks`, `limits`, `findings`, `rules`, `result`); `autoguard/` is `auto()`; plus availability (fail modes, admission), reliability (breaker, fallback) and loop governance. | `enforcement/__init__.py` docstring, `enforcement/enforcer.py:evaluate`, `autoguard/__init__.py:auto` |
| `detection/` | Detectors and the pipeline that runs them; taint tracking; text normalisation; `prefilter.py`, which skips a regex on text that cannot match it; action analysis (SQL/shell semantics); composed-escalation checks; tuning and suppressions; `judgment/`, the optional model tiers and the routing table that limits what each may decide. | `base.py`, `pipeline.py`, `taint.py`, `detectors/`, `judgment/capability.py` |
| `policy/` | The YAML policy model, the native engine and the OPA adapter, storage and binding, the stored-version loader (`load_version_document`, `UnloadablePolicyVersion`), hierarchy and lint, simulation, canaries. | `model.py`, `engine.py`, `store.py` |
| `identity/` | Non-human identities, credentials, capability grants and their constraints, delegation, approvals. | `service.py:check_capability` |
| `containment/` | What an agent may do beyond the grant: control-flow integrity, data-access scoping, effects that outlive a call, inter-agent message signing, escalation governance, containment findings. | `findings.py`, `control_flow.py` |
| `grounding/` | What an answer may say: answerability and abstention, provenance and source authority, entitlement filtering, commitments, numeric/temporal integrity, context integrity, tool contracts, sycophancy. | `answerability.py`, `entitlement.py` |
| `discovery/` | Static scanning: repositories, OpenAPI specs, local coding-assistant sessions, exposure (the lethal trifecta), threat coverage. | `repo.py`, `exposure.py` |
| `registry/` | The agent registry, observed lineage, kill switch and quarantine, skills scanning. | `service.py`, `control.py` |
| `prove/` | Audit chain, traces, evidence packages, SIEM/OTLP, operator and system logs, compliance catalog and status, findings, the one-page report, failure attribution. | `audit/chain.py`, `findings.py`, `report.py` |
| `evaluation/` | Eval runner and scorers, CI gating, drift, silent-failure sampling, red team (native probes, adaptive campaigns, Garak/PyRIT adapters), live probes of deployed agents and the public showcase, Ragas. | `runner.py`, `gating.py`, `redteam.py`, `live_probes.py` |
| `improvement/` | The governed improvement loop: proposals, the loops that file them, appliers that make and undo each change, learned permissions from traffic. | `contract.py`, `proposals.py`, `traffic.py` |
| `business/` | Business rules as guardrails: threshold ladders, compiling written policy into rules, merging rules from many authors, the guardrail catalogue. | `ladder.py`, `compile.py` |
| `gateway/` | The FastAPI app: inline `/v1/*` enforcement and the `/api/*` control plane the dashboard calls; auth, RBAC, playground sandboxes. One router per file in `routes/`. | `app.py:create_app`, `routes/inline.py`, `deps.py` |
| `cli/` | The `agentfox` binary (Typer). Command bodies live in `commands/` and the `*_cli.py` modules; `layout.py` decides the visible tree. | `main.py`, `layout.py`, `commands/` |
| `hooks/` | Coding-agent hooks (Claude Code): a thin per-call client, a warm daemon on a Unix socket that calls the `Enforcer`, the harness contract, and the per-event capability table. | `daemon.py`, `client.py`, `capability.py` |
| `integrations/` | LangGraph guard (`AgentFoxGuard`), MCP governor (`McpGovernor`) and the read-only MCP server, FastAPI middleware, LangSmith/Langfuse correlation, Prometheus. | `langgraph.py`, `mcp.py`, `mcp_server.py` |
| `sdk/` | The explicit Python SDK: `AgentFox`, `AgentSession`, `@fox.tool(impact=…)`, local or remote mode. | `__init__.py` |
| `providers/` | The `ModelProvider` seam: `echo` (offline default), OpenAI, Anthropic, Azure, Bedrock, Vertex, LiteLLM. | `base.py`, `echo.py` |
| `jobs/` | Work outside the request: an in-process queue with retries and a dead letter, its persisted store, handlers, a scheduler. Driven by the cron endpoint or `agentfox admin jobs run-due`. | `queue.py`, `scheduler.py` |
| `monitoring/` | Continuous monitoring of connected sources: run, diff against the last snapshot, raise and close findings, Slack alerts; GitHub push webhooks queue a rescan. | `service.py`, `snapshots.py`, `alerts.py` |
| `policies_data/`, `compliance_data/` | Shipped YAML: the four policy packs; controls, obligations and threats. | — |
| `src/nometria/` | Deprecated compatibility shim: `import nometria` resolves to the same `agentfox` modules. | — |

Outside the package:

| Path | What it is |
|---|---|
| `tests/` | Mirrors the package (`tests/runtime/`, `tests/platform/policy/`, …). `tests/e2e/` runs the request path end to end across packages; `tests/repo/` checks the repository itself (claims, docs site, harness, vendored wheels, install layout). |
| `dashboard/` | The Next.js 15 app: the signed-in product (`app/app/`), the marketing site, and the website docs (`app/docs/`, sidebar in `lib/docs.ts`). It is a client of the gateway API with no back channel. Tests with vitest. |
| `benchmarks/` | Every published number: one directory per area with its runner, results and README; `claims.yaml` binds quoted numbers to result files. |
| `harness/` | AgentFox packaged for coding agents: skills, slash commands, subagents, MCP config, reference files checked against the live CLI. Contract in `harness/STRUCTURE.md`. |
| `docs/` | Design and contributor docs; index in [docs/README.md](docs/README.md). User docs are on the website. |
| `scripts/` | Generators and checks: `claims.py`, `docs_reference.py`, `api_routes.py`, `coverage.py`, `rebuild_vendored_wheels.py`, `quickscan.sh`. |
| `migrations/` | Alembic revisions (also shipped inside the wheel as `agentfox/_migrations`). |
| `deploy/` | Dockerfiles, `docker-compose.yml` (the reference self-host), Render and Fly configs, dashboard runbook. |
| `api/` | The Vercel deployment of the gateway: `api/index.py` re-exports `agentfox.gateway.app:app`. It installs from a **wheel committed in `api/vendor/`**, because Vercel's root directory for this function is `api/` and `../src` would not ship. |
| `demo/` | Two live red-team demos (`redteam-live/`, `redteam-live-lang/`); the second also deploys from a vendored wheel. |

## Invariants and cross-cutting concerns

**Tenancy is applied at the session, not the query.** `core/db.py:get_sessionmaker` installs
`core/tenancy.py`, which attaches a loader criterion to every ORM statement. Do not create
another session factory, and do not write raw `text()` SQL against tenant tables. Gateway
code binds the tenant with `bind_session` (see `gateway/deps.py`); with nothing bound, queries
resolve to the deployment's default org, never to every org.

**The audit chain is append-only.** `prove/audit/chain.py:append` is the only write path for
`AuditEntry`; there is no update or delete anywhere. Every decision appends. Every
privileged operator action must be recorded: `prove/audit/operator_log.py:PRIVILEGED`
declares them, and `tests/platform/ledger/test_operator_log.py` fails if a new operator surface has
no recording call.

**Observe versus enforce.** Packs ship in observe except `tool-containment`, which ships in
enforce. A capability denial is not a policy opinion: `evaluate` sets it directly, whatever
mode the packs are in. Every decision records both the applied `verdict` and the
`effective_verdict`. `auto()` has its own mode (`policy`, `observe`, `enforce`) that decides
whether a refusal is raised in-process.

**No block without a reason.** Every verdict carries the fired rules and a human-readable
reason; findings are titled by what actually refused the call.

**Fail-open and fail-closed are explicit and bounded.** `Settings.fail_mode` (default `open`)
governs what happens when a check cannot run, and a pack's own `fail_mode` can close it too;
a bound policy version that no longer loads is handled the same way (`policy.unloadable`).
`runtime/availability.py` converts a
long-lasting degradation to closed, and its `NEVER_OPEN` controls (tenant isolation,
entitlement filter, data-access scope, audit chain) refuse to be configured open. A degraded
`/v1/*` response is stamped `X-Nometria-Degraded`. Admission and budget state are
per-process.

**Nothing leaves the machine by default.** `Settings.allow_egress` (`AGENTFOX_ALLOW_EGRESS`)
is false; the `echo` provider makes the whole path run with no model or key. Detectors never
download weights during a request: a missing model reports itself unavailable. Hosted
judgment tiers, the finding webhook and Slack alerts need egress on, and the admin's posture is clamped by the deployment (`detection/judgment/posture.py`, `egress.py`). Fetching a
URL a user typed (a spec, an MCP server, a probe target) goes through `core/outbound.py`
(`guarded_get`, `guarded_post`).

**`import agentfox` has no side effects.** The top-level package re-exports lazily; it must
not open a database or import a client library.

**Settings names.** `AGENTFOX_*` is canonical; `NOMETRIA_*` still works at lower precedence.
Headers still use `X-Nometria-*`. Do not rename either without a compatibility path.

**Published numbers are bound.** [`benchmarks/claims.yaml`](benchmarks/claims.yaml) binds each
quoted figure (in this README, `benchmarks/`, `docs/`, website pages) to the result file it
came from; `scripts/claims.py --check` fails on drift, and `retired` figures fail if quoted.
Change a number by re-running the benchmark, never by editing prose.

**Generated files are regenerated, not edited.** `docs/status.md` (`scripts/coverage.py
--write`), the route tables in `docs/architecture/api-spec.md` (`scripts/api_routes.py
--write`), `dashboard/lib/reference/*.json` (`scripts/docs_reference.py --write`, which also
checks every `agentfox …` command shown on a docs page), `docs/design/coverage-map.md`
(`scripts/probe/run.py`). `harness/scripts/check_harness.py` checks the harness against the
live CLI and that every tracked `.md` file is classified in `harness/reference/docs-map.md`.

**Vendored wheels are the deploy.** `api/vendor/` and `demo/redteam-live-lang/vendor/` hold
built wheels. A change under `src/agentfox/` must rebuild both in the same commit; the
pre-commit hook (`scripts/rebuild_vendored_wheels.py`) does it, and CI's
`vendored-wheel-freshness` job fails a push that skipped it.

## Where to start for common changes

**Add a detector.** Subclass `BaseDetector` (`detection/base.py`) with a `key`, `version`,
`surfaces` and `_detect`; put native ones in `detection/detectors/`, wrappers of optional
libraries in `detection/adapters/` (with an `available()` that is false when the extra is
missing). Register it in `detection/__init__.py` with `register_detector`. It runs only if its
key is in `Settings.enabled_detectors` (`core/config.py`). Policy acts on its entity types
through `detection:` conditions; no new rule kind is needed. Tests go in `tests/capabilities/detection/`.

**Add a policy condition (rule kind).** Add the field to `Condition` and, if it needs new
input, to `PolicyInput` (`policy/model.py`); match it in `NativePolicyEngine._matches`
(`policy/engine.py`) and translate it in `_rego_conditions` (`policy/opa.py`); populate the
input in `Enforcer.evaluate`. Document it in `harness/reference/policy-schema.md` and the
website's `dashboard/app/docs/reference/policies/page.tsx`. Tests in `tests/platform/policy/`.

**Add a CLI command.** Write the command in the module for its group (`cli/commands/<group>.py`
or the relevant `*_cli.py`) and make sure it is registered in `cli/main.py`. Then place it in
the visible tree in `cli/layout.py:apply_layout`: commands are found by CLI name and
re-registered under one of the thirteen visible verbs (`VISIBLE`); a working name that is not
re-homed there is not reachable. `tests/apps/cli/test_cli_layout.py` enforces the ceiling, the
removed names, and the two protocol endpoints kept at their old paths (`hooks run`,
`mcp serve`). Add a row to `harness/reference/cli.md` (mark it **BLK** if it changes
whether traffic is blocked, and add a pattern to `harness/scripts/guard_blocking_commands.py`),
then run `scripts/docs_reference.py --write` so the website's CLI reference picks it up.

**Add an HTTP route.** Add it to the router for its family in `gateway/routes/` (use
`deps.db`, and `agent_credential` for `/v1/*` or `current_user`/`require(...)` for `/api/*`).
A new router must be included in `gateway/app.py:create_app`. Regenerate
`scripts/api_routes.py --write` and `scripts/docs_reference.py --write`, and update
`harness/reference/http-api.md`. If the route is a privileged operator action, record it
(see the audit invariant). Tests in `tests/gateway/` or `tests/e2e/`.

**Add a website docs page.** Create `dashboard/app/docs/<section>/<slug>/page.tsx` using the
blocks in `dashboard/components/docs/blocks.tsx` (copy a sibling page), and add it to
`DOC_NAV` in `dashboard/lib/docs.ts`, the one list the sidebar reads. Every `agentfox …`
command on the page is checked by `scripts/docs_reference.py --check`; a figure on it must be
bound in `benchmarks/claims.yaml`. Run `npm test` in `dashboard/`.

**Add a benchmark or a published number.** Add `benchmarks/<area>/` with its runner, a
`results/` file and a README (method, dataset, licence, limits); link it from
`benchmarks/README.md`. To quote a number anywhere, add a claim to `benchmarks/claims.yaml`
pointing at the result file and every place that quotes it, and run `scripts/claims.py
--check`. Read [docs/evaluation/evidence-standards.md](docs/evaluation/evidence-standards.md)
before writing the headline.

**Add a markdown doc.** Classify it in `harness/reference/docs-map.md` and list it in
[docs/README.md](docs/README.md); `check_harness.py` fails otherwise.

## Known rough edges

Honest and short; the full, generated picture is [docs/status.md](docs/status.md), and the
user-facing version is the website's [limits page](https://useagentfox.com/docs/limits).

- Containment is only as good as the declarations: a destructive tool declared `read` is
  treated as `read` by everything downstream.
- Admission control, rate limits and the fail-open budget are per-process, so N replicas get
  N times the declared budget.
- No live IdP, SSO, OIDC or SCIM; principals and grants are declared in AgentFox.
- `jobs/` is in-process; there is no external queue backend, and scheduled work (monitors,
  probes, canaries) runs only when something calls the runner.
- `auto()` does not cover the OpenAI Responses API, or tools your code calls without the model
  asking.
- The Vercel deployment (`api/`) cannot run Alembic migrations through normal channels.
- The hand-written prose in `docs/architecture/api-spec.md` (outside the generated route
  tables) still uses some `NOMETRIA_*` names; trust the code.
- Much of the source carries internal tracking codes (`P3-4`, `PL-7`, `F8.3`) and history in
  docstrings. They map to [docs/design/PRD.md](docs/design/PRD.md) and
  [docs/design/traceability.md](docs/design/traceability.md); new code should not add more
  (see [CONTRIBUTING.md](CONTRIBUTING.md)).
