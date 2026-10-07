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
| **See** | What agents, tools and MCP servers do I have, and what changed? | `capabilities/discovery/`, `platform/registry/`, `capabilities/monitoring/` (`agentfox scan`, `agentfox scan monitors`, `agentfox agents`) |
| **Watch** | What are they doing right now? | `runtime/`, `capabilities/detection/`, `apps/gateway/` (`agentfox serve`, `agentfox findings`) |
| **Contain** | What may each one do? | `platform/identity/`, `platform/policy/`, `capabilities/containment/` (`agentfox permit`, `declare`, `policy`) |
| **Prove** | Can I show what happened? | `platform/ledger/`, `capabilities/compliance/`, `apps/report/`, `capabilities/evaluation/` (`agentfox report`, `agentfox test`) |

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
| **Agent** | Something that makes model and tool calls. Registered explicitly, or recorded as a "shadow" agent the first time it is seen. | `core/models/registry.py` (`Agent`), `platform/registry/service.py` (`observe_agent`, `register_agent`) |
| **Identity, credential** | The non-human identity an agent authenticates as (`nom_agt_…` keys, argon2-hashed). | `core/models/identity.py`, `platform/identity/service.py` (`issue_credential`, `verify_credential`) |
| **Tool, impact** | A callable the agent can invoke. `impact` is the declared blast radius every containment rule reasons over; an undeclared tool is treated as `read` and flagged `tool_known=False`. `output_trust` says whether values copied from its output taint later arguments. | `core/models/registry.py` (`Tool`), `apps/cli/commands/tools.py` (`agentfox declare tool`) |
| **Capability grant** | Permission for one identity to call one tool, with optional argument limits and a provenance ceiling (`--max-taint`). No matching grant means default deny. The one softening: `auto()` in its default mode does not raise for an agent that holds no grants at all, until its first grant. | `core/models/identity.py` (`Capability`), `platform/identity/service.py` (`grant_capability`, `check_capability`), `apps/cli/capability_cli.py` |
| **Provenance / taint** | Where each argument's value came from. Inferred from the conversation (a value copied out of a tool result is `tool_result`) or declared by the caller. `taint_scope` chooses per-session or per-argument reading. | `capabilities/detection/taint.py` (`TaintTracker`, `TaintMark`), `core/vocab.py` (`TAINT_ORDER`, `taint_rank`), `platform/policy/taint_view.py` |
| **Detector, detection** | A check over text on one surface (`input`, `output`, `retrieved`, `tool_result`, `tool_args`, …) that returns scored entities. Run in a budgeted, concurrent pipeline. | `capabilities/detection/base.py` (`Detector`, `BaseDetector`), `capabilities/detection/pipeline.py` (`DetectorPipeline`), `capabilities/detection/detectors/`, `capabilities/detection/adapters/` |
| **Policy, pack, rule, mode** | A policy document (a "pack") is YAML: rules with a `when` condition and an `effect` (`allow` … `escalate`, `block`). Each bound pack is in `observe` (records what it would do) or `enforce` (applies it). Shipped packs: `baseline`, `eu-ai-act-high-risk`, `tool-containment`, `coding-agent`. Versions are immutable. | `platform/policy/model.py` (`PolicyDocument`, `Rule`, `Condition`), `platform/policy/engine.py` (`NativePolicyEngine`, `combine`), `platform/policy/store.py` (`active_policies`, `set_mode`, and `load_version_document`, the one loader for stored versions), `packs/*/policies/*.yaml` |
| **Capability pack** | One business use case or framework as one directory: `pack.yaml` (id, version, maturity, owners, compliance mappings, vocabulary), plus policies, controls, ladder templates, red-team probes, optional checks, golden cases and fixtures. Not to be confused with a policy document, which the CLI also calls a pack. | `platform/packs/` (`PackManifest`, `load_packs`), `packs/`, `capabilities/evaluation/packs.py` (cases, validation) |
| **Check** | A function over one call's context that returns evidence issues and risk codes, registered by the capability that owns it; the Enforcer runs the ones that apply to the surface, in order. A ladder check returns business-ladder decisions instead. | `platform/checks.py` (`@check`, `CheckContext`), `runtime/checks.py`, `capabilities/*/checks.py` |
| **Decision, verdict** | One row per evaluated surface. `verdict` is what was applied; `effective_verdict` is what would have happened with every pack enforcing. Records every policy version in force, so it can be replayed. | `core/models/policy.py` (`Decision`), `runtime/enforcement/result.py` (`EnforcementResult`) |
| **Finding** | A problem a person should look at, deduplicated by fingerprint and counted on recurrence. A refused tool call is a containment finding titled by what refused it. Its `type` is one of the registered finding types. | `core/models/registry.py` (`Finding`), `platform/ledger/findings.py` (`raise_finding`), `platform/ledger/finding_types.py` (the registry), `capabilities/containment/findings.py` (`raise_containment_findings`) |
| **Approval** | A held call waiting for a human; `timeout_action` defaults to deny. Approved, it lets exactly one retry of the same call through, then reads `used`. | `core/models/identity.py` (`ApprovalRequest`), `platform/identity/service.py` (`request_approval`, `resolve_approval`, `redeem_approval`) |
| **Monitor** | A connected source re-checked on a schedule (a GitHub repo, a hosted API spec, a remote MCP server, a deployed agent). Each run is diffed against the last; what appeared becomes a finding, what cleared closes. | `core/models/registry.py` (`Monitor`, `AlertChannel`), `capabilities/monitoring/service.py` (`run_monitor`, `run_due`) |
| **Probe target** | A deployed agent's endpoint that live red-team probes may be sent to, after an explicit, recorded opt-in. | `core/models/evaluation.py` (`ProbeTarget`), `capabilities/evaluation/live_probes.py` (`opt_in`, `run_target`) |
| **Proposal** | A change the platform wants to make (a grant learned from traffic, a declaration, a tuning change), with evidence. Filed → proven → approved → applied → verified, or rolled back. Loosening is never applied automatically. | `core/models/improvement.py` (`ChangeProposal`), `capabilities/improvement/proposals.py`, `capabilities/improvement/traffic.py` (`propose_from_traffic`) |
| **Trace, span** | The execution record of one request: an llm span, guardrail spans, tool spans. | `core/models/audit.py`, `platform/ledger/trace.py` (`start_trace`, `add_span`, `end_trace`) |
| **Audit chain, evidence** | Append-only hash chain over every decision and operator action; evidence packages ship a stdlib-only `verify_chain.py`. | `platform/ledger/chain.py` (`append`, `verify`), `apps/report/evidence.py`, `platform/ledger/operator_log.py` |

## The request path

There is one enforcement code path. Every surface (the `auto()` patches, the gateway, the
SDK, the LangGraph guard, the MCP governor, the coding-agent hook daemon) builds an
`Enforcer` (`runtime/enforcement/enforcer.py`) on a database session and calls one of its
methods. Everything ends in `Enforcer.evaluate()`, which is where a decision is made and
recorded. New surfaces must call these methods, not reimplement them.

### (a) A tool call under `agentfox.auto()`

1. `agentfox.auto()` resolves lazily from `src/agentfox/__init__.py` to
   `frameworks/autoguard/__init__.py:auto`. It registers the agent (`platform/registry/service.py:register_agent`),
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
   (`frameworks/autoguard/tool_calls.py:_tool_calls_of`, OpenAI `tool_calls` or Anthropic
   `tool_use`) and hands them to `_govern_tool_calls`.
6. `_govern_tool_calls` registers unseen tools with an inferred impact (`_register_tool`,
   using `platform/registry/impact.py:infer_impact`) and calls `Enforcer.guard_tool_call` for each,
   with a `TaintTracker` rebuilt from the request's conversation (`tool_calls.py:_provenance_of`).
7. `guard_tool_call` (`runtime/enforcement/tool_calls.py`) checks the kill switch again,
   marks each argument's provenance (`TaintTracker.taint_arguments`), writes `TaintTag`
   rows and a lineage edge, and calls `evaluate(surface="tool_args", …)`.
8. Inside `evaluate` (`enforcer.py`), in order: the detector pipeline
   (`DetectorPipeline.run`, budgeted by a per-request `LatencyLedger`), suppressions,
   `identity.check_capability`, every registered content check for the surface
   (`runtime/checks.py:checks_for` over `platform/checks.py`; evidence, disclosure,
   commitments, context, control flow, sycophancy, trajectory), the ladder checks (business
   ladders) and action analysis, then a `PolicyInput` evaluated by every bound pack
   (`platform/policy/store.py:active_policies`, `NativePolicyEngine.evaluate`, `combine`). If no
   pack is bound, an in-memory fallback (`rules.py:_fallback_policies`) applies `baseline`
   in observe (the packs whose `pack.yaml` declares a `fallback` for the agent's risk
   tier: `baseline`, plus `eu-ai-act` for high and prohibited). A missing grant then
   overrides the policy result with
   `capability.default_deny` or `capability.constraint_violated`.
9. `evaluate` persists: a `Decision` row; the trace's verdict is raised; a detection finding
   if a detector rule changed the outcome (`_raise_detection_finding`); containment
   findings for a refused tool call (`capabilities/containment/findings.py:raise_containment_findings`
   → `platform/ledger/findings.py:raise_finding`); an `ApprovalRequest` on escalate; a guardrail span;
   and finally `platform/ledger/chain.py:append(session, "decision.<verdict>", …)`.
10. Back in `_govern_tool_calls`, a `tool` span records what this process actually did,
    and `Blocked` is raised if the mode says so. In the default `policy` mode, an agent with
    no grants at all is not refused for a missing grant (recorded as would-have-blocked);
    its first grant turns default-deny on.

### (b) `POST /v1/guard/tool_call` on the gateway

1. `apps/gateway/app.py:create_app` builds the FastAPI app (`app` at module bottom; `agentfox serve`
   and `api/index.py` both serve it). Two middlewares run first for `/v1/*` only:
   `degradation_gate` (probes dependencies, applies the fail-open/closed policy, returns 503
   or stamps `X-Nometria-Degraded`) and `admission_gate` (load shedding, 429).
2. The route `guard_tool_call` in `apps/gateway/routes/inline.py` takes a `GuardToolCallRequest`
   body (`agent`, `tool`, `arguments`, `provenance`, `intent`, …). Its dependencies are
   `apps/gateway/deps.py:db` (a session from `core/db.py:get_session`, committed when the
   response is produced) and `agent_credential`, which resolves the bearer key (one that does
   not verify is a 401) and binds the session to that agent's tenant (`core/tenancy.py:bind_session`) and judgment posture.
3. The handler builds `Enforcer(session)`, resolves the agent, opens a trace
   (`platform/ledger/trace.py:start_trace`) and calls `Enforcer.guard_tool_call` with the
   caller's declared `provenance`. From here it is steps 7–9 above, unchanged.
4. The result is serialised with `apps/gateway/verdicts.py:with_verdict_aliases` (which adds the
   applied/would-be verdict names) and returned: `verdict`, `effective_verdict`,
   `rules_fired`, `decision_id`, and `approval_id` when escalated.

The drop-in proxy routes (`/v1/chat/completions`, `/v1/messages`, same file) follow
`Enforcer.run_completion` / `run_completion_stream`, which wrap the same `preflight`, a
provider call through `platform/providers/` with the circuit breaker in `runtime/reliability.py`,
and the same post-flight.

## Code map

All paths are under `src/agentfox/` unless they start at the repo root.

### Layers

The package is layered. A layer imports only the layers below it; packages in the
same layer may import each other. `lint-imports` checks this on every push (CI's lint
job, `just lint`), against the contracts in `pyproject.toml`'s `[tool.importlinter]`.

```
  L5  apps/          cli/  gateway/  mcp_server.py  report/  jobs.py  showcase.py
        │
  L4  frameworks/    sdk/  autoguard/  langgraph.py  fastapi.py  mcp.py      (ingress)
      harnesses/     base.py  claude_code/  (coding agents we govern)        (ingress)
      hooks/         protocol  client  daemon  run  (harness-neutral transport)
      exporters/     correlation.py  otel.py  siem.py  prometheus.py         (egress)
      fixtures/      the demo world
        │
  L3  runtime/       enforcement/ (the Enforcer), availability, reliability, agent loop
        │
  L2  capabilities/  detection/  judgment/  grounding/  containment/  business/
                     discovery/  evaluation/  improvement/  monitoring/  compliance/
      packs/         capability packs: data, plus optional checks (nothing imports them)
        │
  L1  platform/      ledger/  policy/  registry/  identity/  providers/  jobs/
                     packs/ (the pack loader)  checks.py (the check registry)
        │
  L0  core/          config, db, models, tenancy, ids, crypto, outbound, vocab, text
```

`agentfox/__init__.py` (the lazy `auto`, `AgentFox`, `PolicyViolation` … re-exports) and
`agentfox/errors.py` (the exception base every ingress raises) sit outside the layers.

| Package | What lives there | Start reading at |
|---|---|---|
| `core/` | Settings (`AGENTFOX_*` env, `agentfox.toml`), engine and sessions, ORM models for every table, tenancy, ids, the shared vocabulary (surfaces, taint order, effect ranks, comparators), the word tokenizer, outbound URL safety, finding webhooks. | `config.py:Settings`, `db.py:get_sessionmaker`, `models/`, `tenancy.py`, `vocab.py` |
| `platform/ledger/` | The append-only audit chain, traces and spans, operator and system logs, findings and the finding-type registry (title, default severity, description and owner of every type; `raise_finding` checks against it). Everything that records what happened. | `chain.py`, `trace.py`, `findings.py`, `finding_types.py`, `operator_log.py` |
| `platform/policy/` | The YAML policy model, the native engine and the OPA adapter, storage and binding, the stored-version loader (`load_version_document`, `UnloadablePolicyVersion`), hierarchy and lint, simulation, canaries. | `model.py`, `engine.py`, `store.py` |
| `platform/registry/` | The agent and tool registry, observed lineage, kill switch and quarantine, tool impact (`impact.py:infer_impact`, the one place a tool's impact is guessed), delegation-graph attribution. | `service.py`, `control.py`, `impact.py` |
| `platform/identity/` | Non-human identities, credentials, capability grants and their constraints, delegation, approvals; operators and their API tokens (`operators.py`). | `service.py:check_capability`, `operators.py` |
| `platform/providers/` | The `ModelProvider` seam: `echo` (offline default), OpenAI, Anthropic, Azure, Bedrock, Vertex, LiteLLM. | `base.py`, `echo.py` |
| `platform/packs/` | The capability-pack loader: the `pack.yaml` schema (`PackManifest`), discovery from the built-in `packs/`, the `agentfox.packs` entry-point group and `<project>/.agentfox/packs/`, the maturity filter, vocabulary, fallback and control-file lookups, importing packs' `checks/*.py`. Returns paths and manifests; whoever reads a pack's files decides what they mean. | `loader.py`, `model.py` |
| `platform/checks.py` | The check registry: `@check(key, surfaces=, order=, kind=)`, `CheckContext`, `merge_content`. Built-in checks register from their capability modules, others from the `agentfox.checks` entry-point group or a pack. | `checks.py` |
| `platform/jobs/` | Work outside the request: an in-process queue with retries and a dead letter, its persisted store, a scheduler. The handlers that bind job kinds to capabilities are `apps/jobs.py`. Driven by the cron endpoint or `agentfox admin jobs run-due`. | `queue.py`, `store.py`, `scheduler.py` |
| `capabilities/detection/` | Detectors and the pipeline that runs them; taint tracking; text normalisation; `prefilter.py`, which skips a regex on text that cannot match it; action analysis (SQL/shell semantics); composed-escalation and trajectory checks; tuning, suppressions and explanations. | `base.py`, `pipeline.py`, `taint.py`, `detectors/` |
| `capabilities/judgment/` | The optional model tiers and the routing table that limits what each may decide; the egress gate in front of hosted tiers. | `capability.py`, `egress.py`, `posture.py` |
| `capabilities/grounding/` | What an answer may say: answerability and abstention, provenance and source authority, entitlement filtering, commitments, numeric/temporal integrity, context integrity, tool contracts, sycophancy. | `answerability.py`, `entitlement.py` |
| `capabilities/containment/` | What an agent may do beyond the grant: control-flow integrity, data-access scoping, effects that outlive a call, inter-agent message signing, escalation governance, containment findings. | `findings.py`, `control_flow.py` |
| `capabilities/business/` | Business rules as guardrails: threshold ladders (and the ladder check, `checks.py`), compiling written policy into rules with the vocabulary packs declare (`tool_hints`, `roles`), merging rules from many authors, the guardrail catalogue. | `ladder.py`, `compile.py` |
| `capabilities/discovery/` | Static scanning: repositories, OpenAPI specs, skill files, exposure (the lethal trifecta) and the MCP client config files it reads (`exposure.KNOWN_MCP_CONFIGS`), threat coverage. Each harness adapter scans its own local session transcripts into `sessions.py:SessionScanReport`. | `repo.py`, `exposure.py` |
| `capabilities/evaluation/` | Eval runner and scorers, CI gating, drift, silent-failure sampling, red team (native probes, plus packs' `probes/`; adaptive campaigns, Garak/PyRIT adapters), live probes of deployed agents, Ragas, capability-pack cases and validation (`packs.py`). | `runner.py`, `gating.py`, `redteam.py`, `live_probes.py`, `packs.py` |
| `capabilities/improvement/` | The governed improvement loop: proposals, the loops that file them, appliers that make and undo each change, learned permissions from traffic. | `contract.py`, `proposals.py`, `traffic.py` |
| `capabilities/monitoring/` | Continuous monitoring of connected sources: run, diff against the last snapshot, raise and close findings, Slack alerts; GitHub push webhooks queue a rescan. | `service.py`, `snapshots.py`, `alerts.py` |
| `capabilities/compliance/` | The control catalog (read from the compliance packs' `controls/`), computed control status, EU AI Act risk classification (its cues from the `eu-ai-act` pack). | `catalog.py`, `status.py`, `risk.py` |
| `runtime/` | The request path. `enforcement/` is the `Enforcer` split into mixins (`enforcer`, `tool_calls`, `surfaces`, `completion`, `streaming`, `limits`, `findings`, `rules`, `result`); `checks.py` names the modules whose registered checks it runs; plus availability (fail modes, admission), reliability (breaker, fallback), loop governance, and `trace_exporters.py`, the exporters it tells about each trace. | `enforcement/__init__.py` docstring, `enforcement/enforcer.py:evaluate` |
| `frameworks/` | Ingress for application frameworks, each mapping its calls onto the `Enforcer`: `autoguard/` is `auto()`, `sdk/` the explicit SDK (`AgentFox`, `@fox.tool(impact=…)`), the LangGraph guard (`AgentFoxGuard`), FastAPI middleware, the MCP governor (`McpGovernor`). | `autoguard/__init__.py:auto`, `sdk/__init__.py`, `mcp.py` |
| `exporters/` | Egress: LangSmith/Langfuse trace correlation (`correlation.py:TraceCorrelation`, which the runtime emits to), OTLP ingest and export, SIEM, Prometheus. | `correlation.py`, `otel.py` |
| `harnesses/` | The coding agents AgentFox governs, one adapter each behind `base.py:HarnessAdapter`: parse a hook payload into an `AgentEvent`, render a `Decision` (allow, deny, ask, modify, context) into the exact stdout and exit code, install the hooks, find hooked agents, MCP configs and transcripts. Each adapter declares a per-event capability matrix (`EventCaps`) with its evidence; a decision the harness cannot honour is downgraded on purpose and recorded (`base.downgrade`). The registry (`get`, `known`, `all`) loads adapters from the `agentfox.harnesses` entry-point group. Claude Code is `claude_code/`, with payloads captured from the real tool in `fixtures/`. | `__init__.py`, `base.py`, `claude_code/adapter.py` |
| `hooks/` | The harness-neutral hook transport: a thin per-call client, a warm daemon on a Unix socket that calls the `Enforcer`, and `run.py` (`agentfox hooks run`), which goes through the harness registry. | `run.py`, `daemon.py`, `client.py` |
| `fixtures/` | The deterministic demo world (agents, tools, grants, policies, an eval suite) that `agentfox demo`, the playground and the tests seed; the support and payments desks come from the `customer-support` and `payments/refunds` packs' `fixtures/world.yaml`. | `seed.py:seed` |
| `apps/gateway/` | The FastAPI app (`agentfox.apps.gateway.app:app`): inline `/v1/*` enforcement and the `/api/*` control plane the dashboard calls; request authentication, RBAC, playground sandboxes. One router per file in `routes/`. | `app.py:create_app`, `routes/inline.py`, `deps.py` |
| `apps/cli/` | The `agentfox` binary (Typer, `agentfox.apps.cli.main:main`). Command bodies live in `commands/` and the `*_cli.py` modules; `layout.py` decides the visible tree. | `main.py`, `layout.py`, `commands/` |
| `apps/` (the rest) | `mcp_server.py`, the read-only MCP server for AI clients; `report/`, the one-page summary and evidence packages; `jobs.py`, the job handler table; `showcase.py`, the public showcase run. | `mcp_server.py`, `report/summary.py`, `report/evidence.py` |
| `packs/` | The built-in capability packs: `baseline`, `tool-containment`, `coding-agent` and `eu-ai-act` (the four shipped policies), `compliance/catalog` (controls, obligations, threats), `payments/refunds`, `customer-support`; `_template/` is what `agentfox policy packs new` copies. Data, plus optional checks; nothing imports it. | `<pack>/pack.yaml`, `<pack>/README.md` |

Outside the package:

| Path | What it is |
|---|---|
| `tests/` | Mirrors the package (`tests/runtime/`, `tests/platform/policy/`, …). `tests/e2e/` runs the request path end to end across packages; `tests/repo/` checks the repository itself (claims, docs site, plugins, vendored wheels, install layout); `tests/harnesses/conformance.py` runs every registered harness adapter against its captured fixtures. |
| `dashboard/` | The Next.js 15 app, three sites in one tree organised by route groups that do not change a URL: the signed-in product (`app/(product)/app/`, plus `/login`), the marketing site (`app/(marketing)/`; the home page and `app/blog/` sit at the app root so their Open Graph image URLs stay unhashed), and the website docs (`app/docs/`, sidebar in `lib/docs/pages.ts`). `components/` and `lib/` split the same way into `product/`, `marketing/` and `docs/`; `components/ui/` holds primitives used by more than one site, and `lib/generated/` holds the JSON the generators write. It is a client of the gateway API with no back channel. Tests with vitest. |
| `benchmarks/` | Every published number: one directory per claim family, named as its claim ids in `claims.yaml` are prefixed (`containment/`, `agentdojo/`, `injection/`, `generalization/`, …), each with its runner, results and README; `claims.yaml` binds quoted numbers to result files. `_common/` holds the helpers scripts share (database reset, dataset download, PII span scoring). Scripts run as modules from the root: `python -m benchmarks.<family>.<script>`. |
| `plugins/` | AgentFox packaged for an operator's coding agent (to *use* AgentFox, as opposed to `src/agentfox/harnesses/`, which *governs* one). `shared/` holds the runtime-neutral AGENTS.md, skills and reference files checked against the live CLI; `claude-code/` is the Claude Code plugin (manifest, slash commands, subagents, safety hook, MCP config) with committed copies of `shared/`. Contract in `plugins/STRUCTURE.md`. |
| `docs/` | Design and contributor docs (`architecture/`, `design/`, `evaluation/`, `adr/` for decision records); index in [docs/README.md](docs/README.md). User docs are on the website. |
| `scripts/` | `gen/` writes generated files (`api_routes.py`, `docs_reference.py`, `coverage.py`, and `new_harness.py` from `templates/`); `check/` holds the drift checks CI runs (`claims.py`, `plugins.py`, `demo_kit.py`) and the vendored-wheel pre-commit hook; `ops/` is for operating a deployment (`deploy_smoke.py`). `probe/` builds the coverage map and stays put because product code names its scenarios; `quickscan.sh` stays at the top because the README publishes its raw URL for `curl \| bash`. |
| `migrations/` | Alembic revisions (also shipped inside the wheel as `agentfox/_migrations`). |
| `deploy/` | Dockerfiles, `docker-compose.yml` (the reference self-host), the dashboard-only Render and Fly configs, the dashboard runbook, and the hand-applied Neon catch-up SQL. |
| `render.yaml` | The one-click self-host blueprint (database, gateway, dashboard). At the root because Render's deploy button reads only that path. |
| `justfile` | The command surface: `just ci` runs what CI runs; `just new-harness <name>` scaffolds an adapter. |
| `api/` | The Vercel deployment of the gateway: `api/index.py` re-exports `agentfox.apps.gateway.app:app`. It installs from a **wheel committed in `api/vendor/`**, because Vercel's root directory for this function is `api/` and `../src` would not ship. |
| `demo/` | Two live red-team demos (`redteam-live/`, CrewAI; `redteam-live-lang/`, LangChain) sharing one support-tools agent, seed and verification in `demo/kit/`. The second deploys on Vercel from a vendored wheel and a committed copy of the kit (`redteam-live-lang/kit/`), because its Vercel root directory is that folder. |

## Invariants and cross-cutting concerns

**Imports follow the layers** (see [Layers](#layers)); `lint-imports` fails CI otherwise:

- `core` imports nothing in `agentfox` outside `core`. The two session extensions that
  live higher up (monitor alerts, finding webhooks) are named, not imported, in
  `core/db.py:SESSION_EXTENSIONS`.
- `platform` never imports a capability, the runtime or an app. The ledger takes its
  explainer as an argument (`ledger/trace.py:full_trace(explain=…)`) rather than
  importing detection.
- `capabilities` never import the runtime, a framework, an exporter or an app.
- `runtime` never imports a framework, an exporter or an app: it tells the exporters
  named in `runtime/trace_exporters.py:TRACE_EXPORTERS` about each trace.
- `runtime` never imports a check module: it names them in
  `runtime/checks.py:BUILTIN_CHECK_MODULES` and runs what the registry holds.
- Nothing imports `agentfox.packs`: a pack is read by `platform/packs`, and its
  `checks/*.py` are imported by file path. A pack check may import only `core`,
  `platform` and `capabilities` (`agentfox policy packs validate` checks).
- `apps/cli` never imports `apps/gateway`: operator tokens live in
  `platform/identity/operators.py`, which both use.
- Nothing outside `harnesses/` and `hooks/` imports a specific harness adapter
  (`agentfox.harnesses.claude_code`); everyone asks the registry (`harnesses.get`, `all`).

Two edges are known exceptions, listed by name in `pyproject.toml` with what removes
each: evaluation's in-process red-team runner and live-probe adapter build an
`Enforcer` to measure it.


**Tenancy is applied at the session, not the query.** `core/db.py:get_sessionmaker` installs
`core/tenancy.py`, which attaches a loader criterion to every ORM statement. Do not create
another session factory, and do not write raw `text()` SQL against tenant tables. Gateway
code binds the tenant with `bind_session` (see `apps/gateway/deps.py`); with nothing bound, queries
resolve to the deployment's default org, never to every org.

**The audit chain is append-only.** `platform/ledger/chain.py:append` is the only write path for
`AuditEntry`; there is no update or delete anywhere. Every decision appends. Every
privileged operator action must be recorded: `platform/ledger/operator_log.py:PRIVILEGED`
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
judgment tiers, the finding webhook and Slack alerts need egress on, and the admin's posture is clamped by the deployment (`capabilities/judgment/posture.py`, `egress.py`). Fetching a
URL a user typed (a spec, an MCP server, a probe target) goes through `core/outbound.py`
(`guarded_get`, `guarded_post`).

**`import agentfox` has no side effects.** The top-level package re-exports lazily; it must
not open a database or import a client library.

**Settings names.** `AGENTFOX_*` is canonical; `NOMETRIA_*` still works at lower precedence.
Headers still use `X-Nometria-*`. Do not rename either without a compatibility path.

**Published numbers are bound.** [`benchmarks/claims.yaml`](benchmarks/claims.yaml) binds each
quoted figure (in this README, `benchmarks/`, `docs/`, website pages) to the result file it
came from; `scripts/check/claims.py --check` fails on drift, and `retired` figures fail if quoted.
Change a number by re-running the benchmark, never by editing prose.

**Generated files are regenerated, not edited.** `docs/status.md` (`scripts/gen/coverage.py
--write`), the route tables in `docs/architecture/api-spec.md` (`scripts/gen/api_routes.py
--write`), `dashboard/lib/generated/reference/*.json` (`scripts/gen/docs_reference.py --write`, which also
checks every `agentfox …` command shown on a docs page), `docs/design/coverage-map.md`
(`scripts/probe/run.py`). `scripts/check/plugins.py` checks the plugins against the live CLI,
that the Claude Code plugin's copies of `plugins/shared/` match their originals (`--write`
refreshes them), and that every tracked `.md` file is classified in
`plugins/shared/reference/docs-map.md`. `scripts/check/demo_kit.py` checks that
`demo/redteam-live-lang/kit/` is a byte-identical copy of `demo/kit/` (`--write` refreshes
it): edit the kit in `demo/kit/` only.

**Vendored wheels are the deploy.** `api/vendor/` and `demo/redteam-live-lang/vendor/` hold
built wheels. A change under `src/agentfox/` must rebuild both in the same commit; the
pre-commit hook (`scripts/check/rebuild_vendored_wheels.py`) does it, and CI's
`vendored-wheel-freshness` job fails a push that skipped it.

## Where to start for common changes

**Add a detector.** Subclass `BaseDetector` (`capabilities/detection/base.py`) with a `key`, `version`,
`surfaces` and `_detect`; put native ones in `capabilities/detection/detectors/`, wrappers of optional
libraries in `capabilities/detection/adapters/` (with an `available()` that is false when the extra is
missing). Register it in `capabilities/detection/__init__.py` with `register_detector`. It runs only if its
key is in `Settings.enabled_detectors` (`core/config.py`). Policy acts on its entity types
through `detection:` conditions; no new rule kind is needed. Tests go in `tests/capabilities/detection/`.

**Add a policy condition (rule kind).** Add the field to `Condition` and, if it needs new
input, to `PolicyInput` (`platform/policy/model.py`); match it in `NativePolicyEngine._matches`
(`platform/policy/engine.py`) and translate it in `_rego_conditions` (`platform/policy/opa.py`); populate the
input in `Enforcer.evaluate`. Document it in `plugins/shared/reference/policy-schema.md` and the
website's `dashboard/app/docs/reference/policies/page.tsx`. Tests in `tests/platform/policy/`.

**Add a CLI command.** Write the command in the module for its group (`apps/cli/commands/<group>.py`
or the relevant `*_cli.py`) and make sure it is registered in `apps/cli/main.py`. Then place it in
the visible tree in `apps/cli/layout.py:apply_layout`: commands are found by CLI name and
re-registered under one of the thirteen visible verbs (`VISIBLE`); a working name that is not
re-homed there is not reachable. `tests/apps/cli/test_cli_layout.py` enforces the ceiling, the
removed names, and the two protocol endpoints kept at their old paths (`hooks run`,
`mcp serve`). Add a row to `plugins/shared/reference/cli.md` (mark it **BLK** if it changes
whether traffic is blocked, and add a pattern to `plugins/claude-code/scripts/guard_blocking_commands.py`),
then run `scripts/gen/docs_reference.py --write` so the website's CLI reference picks it up.

**Add an HTTP route.** Add it to the router for its family in `apps/gateway/routes/` (use
`deps.db`, and `agent_credential` for `/v1/*` or `current_user`/`require(...)` for `/api/*`).
A new router must be included in `apps/gateway/app.py:create_app`. Regenerate
`scripts/gen/api_routes.py --write` and `scripts/gen/docs_reference.py --write`, and update
`plugins/shared/reference/http-api.md`. If the route is a privileged operator action, record it
(see the audit invariant). Tests in `tests/apps/gateway/` or `tests/e2e/`.

**Add a website docs page.** Create `dashboard/app/docs/<section>/<slug>/page.tsx` using the
blocks in `dashboard/components/docs/blocks.tsx` (copy a sibling page), and add it to
`DOC_NAV` in `dashboard/lib/docs/pages.ts`, the one list the sidebar reads. Every `agentfox …`
command on the page is checked by `scripts/gen/docs_reference.py --check`; a figure on it must be
bound in `benchmarks/claims.yaml`. Run `npm test` in `dashboard/`.

**Add a benchmark or a published number.** Add `benchmarks/<area>/` with its runner, a
`results/` file and a README (method, dataset, licence, limits); link it from
`benchmarks/README.md`. To quote a number anywhere, add a claim to `benchmarks/claims.yaml`
pointing at the result file and every place that quotes it, and run `scripts/check/claims.py
--check`. Read [docs/evaluation/evidence-standards.md](docs/evaluation/evidence-standards.md)
before writing the headline.

**Add a markdown doc.** Classify it in `plugins/shared/reference/docs-map.md` and list it in
[docs/README.md](docs/README.md); `scripts/check/plugins.py` fails otherwise.

**Add a check** (something `evaluate` should look at on every call). Write a function in
the capability that owns the question, taking a `platform/checks.py:CheckContext` and
returning `{evidence_issues, risks, …}`, and decorate it with `@check("<capability>.<name>",
surfaces=[…], order=N)`; its module must be named in `runtime/checks.py:BUILTIN_CHECK_MODULES`
(or registered by an `agentfox.checks` entry point, or shipped in a pack's `checks/`).
Issues become findings, so register any new finding `type` in
`platform/ledger/finding_types.py`. Risks join `action["risks"]`: a policy acts on them
with `action_risk: "<code>"`, so no new rule kind is needed. A check never sets a verdict.
`tests/platform/test_checks.py` pins the built-in order.

**Add a pack** (a business use case or framework). `just new-pack payments/chargebacks`
(or `agentfox policy packs new <id>` into `.agentfox/packs/`) copies
`src/agentfox/packs/_template/`:

1. `pack.yaml`: id, version, maturity (new packs start `incubating`), owners, tags,
   compliance mappings, `vocabulary` (e.g. the compiler's `tool_hints` and `roles`),
   `finding_types` its checks raise, and `fallback` only for a pack that should protect
   an unconfigured deployment. Schema: `agentfox policy packs validate --schema`.
2. `policies/*.yaml` in the policy format; `controls/`, `ladders/` (templates an operator
   applies with `agentfox policy rules apply`), `probes/` (red-team probes, run after the
   built-in library), `checks/*.py` (see "Add a check"), `fixtures/` as needed.
3. `cases/*.yaml`: golden events with the outcome the pack promises (policy, ladder,
   compile, fallback and control cases; `capabilities/evaluation/packs.py`).
4. `README.md`: the risk, what it ships, the remediation.
5. `just test-pack payments/chargebacks` validates it and runs its cases;
   `pytest tests/capabilities/evaluation/test_packs.py` runs every built-in pack's.

A pack is promoted to `stable` (loaded by default) once it has cases, a README and an
owner. Nothing in `src/` changes to add one.

**Add a harness** (a coding agent to govern). One folder, `src/agentfox/harnesses/<name>/`,
beside `claude_code/`; `just new-harness <name>` writes the skeleton:

1. `adapter.py`: a class satisfying `harnesses/base.py:HarnessAdapter` and a module-level
   `ADAPTER`. Map the harness's event names to the canonical kinds (`events`), declare an
   `EventCaps` per event with the evidence for each claim (`Verified`: SOURCE, VENDOR_DOCS or
   LIVE_PROBE, and the version), and render each `Decision` in the shape that event really
   accepts, calling `base.downgrade` first. An event nobody has probed has no `verified` row.
2. `tools.py`: native tool name → canonical name (`tool_map`) and built-in tool impacts.
3. `install.py`: where the harness reads hooks, and an idempotent merge into that file.
4. `fixtures/<kind>.json`: hook payloads **captured from the real tool**, never written by
   hand, with `<kind>.expected.json` beside each (the parsed event, and the exact stdout and
   exit code for each decision).
5. Register it: `[project.entry-points."agentfox.harnesses"]` in `pyproject.toml`, and the
   `BUILTIN` table in `harnesses/__init__.py` for source checkouts. An external package
   registers the same entry point and nothing else.
6. `pytest tests/harnesses` — the conformance suite picks the adapter up from the registry.

Nothing outside `harnesses/` and `hooks/` imports the new folder; callers go through the
registry, and `lint-imports` fails otherwise.

## Known rough edges

Honest and short; the full, generated picture is [docs/status.md](docs/status.md), and the
user-facing version is the website's [limits page](https://useagentfox.com/docs/limits).

- Containment is only as good as the declarations: a destructive tool declared `read` is
  treated as `read` by everything downstream.
- Admission control, rate limits and the fail-open budget are per-process, so N replicas get
  N times the declared budget.
- No live IdP, SSO, OIDC or SCIM; principals and grants are declared in AgentFox.
- `platform/jobs/` is in-process; there is no external queue backend, and scheduled work (monitors,
  probes, canaries) runs only when something calls the runner.
- `auto()` does not cover the OpenAI Responses API, or tools your code calls without the model
  asking.
- The Vercel deployment (`api/`) cannot run Alembic migrations through normal channels.
- The hand-written prose in `docs/architecture/api-spec.md` (outside the generated route
  tables) still uses some `NOMETRIA_*` names; trust the code.
- Two imports still point up a layer, each named with its TODO in `pyproject.toml`'s
  `[tool.importlinter]` (see [Invariants](#invariants-and-cross-cutting-concerns)).
