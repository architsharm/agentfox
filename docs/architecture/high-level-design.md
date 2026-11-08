# High-Level Design (HLD)

**The why behind the shape:** principles, the pillars, integration surfaces, fail modes, work
outside the request, the stack and the deployment topology. Derived from the code and from
[the PRD](../design/PRD.md); if they disagree, trust the code. The domain model, the request
path through the code and the code map are in [ARCHITECTURE.md](../../ARCHITECTURE.md);
subsystem internals in [low-level-design.md](low-level-design.md).

---

## 1. What this system is

AgentFox is a **governance and security control plane for AI agents**. It does five jobs:
**discover** the agents, tools, MCP servers and skills a team has; **govern** what each may do
with least-privilege grants; **protect** them at runtime (prompt injection, personal data,
secrets, unsafe actions); **test** them with attack suites; and **prove** what happened with a
verifiable audit trail and compliance evidence. Its lead promise is guardrails that do not block
real customers: everything starts by watching, and a rule blocks only after its effect on recorded
traffic has been simulated.

It runs inline, in the agent's own process (`agentfox.auto()`, a framework adapter) or in front of
it (the gateway, a LiteLLM proxy, a platform's tool webhook), against a control plane (gateway,
API and dashboard) that is self-hosted or AgentFox Cloud. The usual first step is the dashboard's
setup card and `agentfox init --key`, which maps a repository statically, adds its agents and runs
an attack test on the developer's machine before and after the basic guardrails.

The engineering is organised by **pillar**. The first six answer six questions, each pillar's data
flowing into the next (discover is pillar 1; govern is 2 and 12; protect is 3, 9 and 10; test is
4; prove is 5 and 6):

| # | Pillar | Question it answers | Built on |
|---|---|---|---|
| 1 | Discovery & Registry | What agents/tools/MCP servers exist? | ours |
| 2 | Identity, Access & Authorization | What is this agent allowed to touch? | OPA/Rego + ours |
| 3 | Runtime Guardrails & Security | Stop the bad thing before it lands | Presidio, Granite Guardian, NeMo/Guardrails AI + ours |
| 4 | Evaluation & Reliability | Does it actually work, today, in CI? | promptfoo-derived native runner, Garak, PyRIT, Ragas + ours |
| 5 | Audit & Traceability | Show me exactly what happened | OpenTelemetry + ours |
| 6 | Policy & Compliance | Prove we meet the rules that apply to us | ours — almost no OSS exists here |

Twelve further pillars (7–18: Answerability, Provenance, Action Assurance, Entitlement,
Escalation, Failure Attribution, Business/Policy Composition, Context Integrity, Cost &
Reliability, Memory-write governance, Inter-agent messaging security, Tool Contract) sit
underneath and across these six — see §3. The product's own framing is that pillars 7–13 are
where genuine, currently-unclaimed differentiation lives, while 1–6 are table stakes done well.

---

## 2. Architecture principles

These are load-bearing design commitments found consistently enforced in code, not aspiration:

1. **Additive, never a rewrite.** Three integration surfaces (SDK monkey-patch, inline
   proxy, OTel ingestion — §5) all sit *beside* an agent's existing code. The
   content policies start in **observe**: `baseline` and `eu-ai-act-high-risk` both
   ship `mode: observe`, and nothing they detect is blocked until a human runs
   `agentfox policy enforce baseline`. A library that starts refusing production
   traffic because someone added an import is, in the product's own words,
   "indefensible." Tool containment is the deliberate exception: `tool-containment`
   ships `mode: enforce`, and a capability denial is not a policy opinion at all —
   `Enforcer.evaluate()` sets the verdict directly, so it stands whatever mode the packs
   are in.
2. **Every wrapped OSS primitive sits behind one interface.** `Detector`, `PolicyEngine`,
   `EvalRunner`, `RedTeamRunner`, `ModelProvider`, `ActionAnalyser`, `EntitlementEngine`,
   `CatalogSource` — eight seams (`docs/design/PRD.md` §7.2). When a dependency is acquired,
   archived, or licence-changes underneath the project (this has already happened twice —
   promptfoo→OpenAI, Langfuse→ClickHouse — see [Appendix A](../design/oss-register.md)),
   exactly one adapter file changes, not the calling code.
3. **Self-host, zero egress by default.** `AGENTFOX_ALLOW_EGRESS=false` is the default in
   `deploy/docker-compose.yml`. The `echo` provider makes the entire enforcement path
   demonstrable with no API key, no model weights, and no network call. This is a deliberate
   wedge against SaaS-only competitors (Zenity, OneTrust, Credo AI) as well as a genuine
   requirement for regulated buyers. Everything that sends data out (hosted judgment tiers,
   the finding webhook, Slack alerts, remote providers) checks the same setting.
4. **Fail-open is a per-policy, per-environment choice, not a hardcoded default.** Because the
   product sits inline on the request path to a model, an outage in the governance layer
   must not become an outage of the agent it governs (`docs/architecture/threat-model.md`
   §E.2). `AGENTFOX_FAIL_MODE=open` ships as the container default; hard budget/kill-switch
   gates are the deliberate exceptions. A policy pack may declare its own `fail_mode`, and
   either source saying `closed` closes it: this governs a degraded detector pipeline and a
   bound policy version that no longer loads alike (§6.2).
5. **Computed, not attested.** Compliance-control status (Pillar 6) and failure-mode coverage
   are computed from telemetry (`ee/src/agentfox_ee/compliance/status.py`'s `status_rule` predicates,
   `scripts/gen/coverage.py --write`), not hand-maintained claims. `docs/status.md` is
   machine-regenerated for exactly this reason.
6. **Declared gaps over hidden gaps.** Framework-coverage tables list what a mapping does
   *not* cover (Appendix B §B.4); the threat model lists what it explicitly does not defend
   against (Appendix E §E.3); this HLD and its companion LLD apply the same standard.

---

## 3. Logical architecture — five layers, eighteen pillars

The eighteen pillars group into five layers along the lifecycle of one agent action
(`docs/design/PRD.md` §5):

```
 A. KNOW        1  Discovery & Registry        12 Policy/Business-rule Composition
 B. CONSTRAIN   2  Identity & Access            3 Guardrails        9 Action Assurance   10 Entitlement
 C. GROUND      7  Answerability                8 Provenance       14 Context Integrity
 D. JUDGE       4  Evaluation & Reliability    13 Failure Attribution   11 Escalation
 E. PROVE       5  Audit & Traceability         6 Compliance
 cross-cutting 15  Cost & Reliability          16 Memory-write governance   17 Inter-agent
                   messaging security          18 Tool Contract
```

**A (Know)** establishes ground truth about what exists and what the rules are, before any
request is evaluated. **B (Constrain)** bounds what an agent may do — this is where the
project's most defensible IP sits (argument-provenance taint tracking, SQL blast-radius
analysis, entitlement-scoped retrieval). **C (Ground)** decides whether the agent should
answer at all, and from what. **D (Judge)** happens both inline (silent-failure sampling) and
out-of-band (CI eval gates, red-team campaigns). **E (Prove)** is the durable record: an
independently-verifiable audit chain and compliance evidence, generated as a byproduct of
normal operation rather than assembled after the fact for an audit. The four cross-cutting
pillars (15–18) don't belong to one stage — cost/reliability wraps every provider call, memory-
write and inter-agent-message governance are newer additions (closing OWASP Agentic ASI06/
ASI07) that intercept two request shapes the original six-pillar/request-path model didn't
originally name.

---

## 4. Component architecture

Four deployable units, one shared Python package:

```
┌─────────────────────────────────────────────────────────────────────┐
│  src/agentfox/  (one package in layers: core < platform <           │
│  capabilities < runtime < frameworks, harnesses, hooks, exporters   │
│  < apps; see low-level-design.md §1 and ARCHITECTURE.md's code map) │
│  + ee/src/agentfox_ee/  (AgentFox Enterprise, plugged in through    │
│  the agentfox.extensions entry point; never imported by the core)   │
└─────────────────────────────────────────────────────────────────────┘
        │ imported by all four of:
        ▼
┌───────────────┐  ┌────────────────────┐  ┌──────────────────┐  ┌───────────────────┐
│  CLI           │  │  Gateway process    │  │  Client library   │  │  Dashboard          │
│  `agentfox`    │  │  FastAPI app        │  │  agentfox.auto()  │  │  (Next.js)          │
│  binary        │  │  (apps/gateway/app) │  │  or AgentFoxGuard │  │                     │
│  (Typer);      │  │  serves BOTH the    │  │  monkey-patches   │  │  Client of the API, │
│                │  │  inline proxy       │  │  the agent's own  │  │  no privileged      │
│  wraps every   │  │  (/v1/*) and the    │  │  process in-place │  │  back-channel       │
│  subsystem     │  │  control-plane API  │  │  (autoguard/)     │  │  (principle X-5)    │
│                │  │  (/api/*) from one  │  │                    │  │                     │
│                │  │  process — a        │  │  Calls the SAME    │  │  Its route handlers │
│                │  │  deployment choice, │  │  Enforcer.preflight│  │  proxy mutations to │
│                │  │  not an             │  │  as the gateway    │  │  the gateway with   │
│                │  │  architectural one  │  │  (no reimplement-  │  │  session-cookie auth│
│                │  │  (stateless,        │  │  ation drift)      │  │  (lib/product/      │
│                │  │  scales out         │  │                    │  │  proxy.ts)          │
│                │  │  horizontally)      │  │                    │  │                     │
└───────────────┘  └────────┬───────────┘  └────────────────────┘  └──────────┬──────────┘
                             │                                                  │ HTTP, server-
                             │ SQLAlchemy 2.0                                   │ to-server, plus
                             ▼                                                  │ one client-side
                    ┌──────────────────┐   ┌───────────────┐                   │ exception
                    │  Postgres 16      │   │  OPA sidecar   │◄──────────────────┘
                    │  (or SQLite       │   │  (optional —   │
                    │  offline/local)   │   │  native policy │
                    │                   │   │  engine is the │
                    │                   │   │  default and   │
                    │                   │   │  falls back to │
                    │                   │   │  it if OPA is  │
                    │                   │   │  unreachable)   │
                    └──────────────────┘   └───────────────┘
```

**A fifth deployment shape exists**: `api/index.py` re-exports the identical
`agentfox.apps.gateway.app:app` object as a Vercel serverless function, for a hosted demo/trial
path that doesn't require self-hosting Postgres. This is not a separately designed API — see
§10 for why it is nonetheless a real architectural risk.

**"Stateless, scales out horizontally" is true for throughput only.** Admission control and
the budget and rate limiters (`runtime/availability.py`, the `admission_gate` middleware) keep
their state in each process, so N replicas enforce N times the declared threshold and budget.
Moving that state to a shared store is open work ([gap-analysis.md](../design/gap-analysis.md)).

---

## 5. Integration surfaces

Several ways to adopt, each additive and each meeting a team where it already is. How to use
each one is in the [product tour](../product-tour.md); this table is the design view:

| Surface | How it's used | What it gives you | Cost to adopt |
|---|---|---|---|
| **SDK / `agentfox.auto()`** | `import agentfox; agentfox.auto()` — detects installed frameworks from `sys.modules` (LangGraph, LangChain, LlamaIndex, CrewAI, AutoGen, FastAPI, Flask, Django, MCP, Ragas, LiteLLM) and monkey-patches the OpenAI, Anthropic, LiteLLM, and LangChain `BaseChatModel` call sites | Every model call traced, evaluated, audited, and every tool call in a response authorised before the caller runs it — no code changes beyond the one import | One line |
| **LangGraph decorators** (`AgentFoxGuard`) | `guard.model_node(...)`, `guard.retrieval_node(...)`, `guard.tool_node(...)` wrap existing graph nodes | Same enforcement, plus tool-call gating *before* the wrapped function body runs, and indirect-injection scanning on retrieval output specifically | Named **the primary adoption path** — 11/11 surveyed senior AI engineers use LangGraph |
| **Inline gateway proxy** | Point an OpenAI/Anthropic client's `base_url` at the gateway's `/v1/chat/completions` or `/v1/messages` | Works for non-Python stacks and teams that can't touch application code at all | Config change only |
| **OTel ingestion** (`POST /v1/traces`) | Passive, zero-integration — the gateway just observes spans already being emitted | Pillars 1 (discovery) and 5 (audit) for free, no enforcement | Zero code change, but no blocking capability |
| **Guard API** (`/v1/guard/*`, the TypeScript SDK) | Ask before each tool call or about a piece of content, from any language | The same decision as in process; `auto()` with an account key uses these routes | A call per check |
| **OpenAI Agents SDK** | `agentfox_input_guardrail`, `agentfox_output_guardrail`, `guarded_function_tool` | The SDK's own guardrail objects; a stopped tool call returns a refusal to the model | A few lines |
| **LiteLLM proxy guardrail** | One block in the proxy's `config.yaml` (`frameworks/litellm_guardrail.py`) | Every agent behind the proxy: inputs, each requested tool call (with taint from the conversation) and the reply | Config change only |
| **Platform hooks** (`/v1/hooks/vapi`, `/retell`, `/copilot-studio`; the AgentCore interceptor Lambda) | Point the platform's pre-tool URL at the gateway | Tool calls of hosted voice and agent platforms decided before they run, answered in the platform's format; allowed calls forwarded to the registered tool server | Register a connection |
| **Coding-agent hooks** (Claude Code, Codex) | `agentfox admin hooks install --write` | Each prompt and tool call of the coding agent, through a warm local daemon | One command |
| **MCP governor** | `McpGovernor` or `POST /v1/mcp/call` | Each MCP tool call, with the listing pinned against its reviewed definition | Wrap the client |

Every surface ends in the same `Enforcer.evaluate()`: there is one enforcement code path, not
parallel implementations that could drift. ARCHITECTURE.md's
[request path](../../ARCHITECTURE.md#the-request-path) traces it.

---

## 6. Request path

The conceptual sequence a single model call goes through, with the pillar behind each gate.
The method-level trace is ARCHITECTURE.md's
[request path](../../ARCHITECTURE.md#the-request-path).

```
1. Resolve identity + end-user principal (Pillar 2, 10)
2. Kill-switch / quarantine check (control verdict — hard stop if killed or quarantined,
   on every surface)
3. Hard budget-cap gate (Pillar 15 — 429/reject before any model spend)
4. Knowledge-boundary / answerability gate (Pillar 7) ── should not answer? → templated
   refusal, no model call, no cost incurred
5. Entitlement pre-filter on retrieval (Pillar 10) — results the end-user principal
   isn't entitled to never reach the prompt
6. Taint annotation (Pillar 3/9) — every message tagged by source
   (user | retrieved | tool_result | subagent | memory) and trust
   (trusted | untrusted)
7. Detector pipeline runs per message, budgeted (Pillar 3) — worst verdict tracked
8. Hierarchical policy resolution → decision (Pillar 12, 6)
9. Blocked → stop here, audited.  Escalate → hand off to a human (Pillar 2, 11; §6.1).
   Otherwise: real provider call proceeds (circuit breaker + fallback, Pillar 15)
10. Post-flight: output-surface detector pass (PII/DLP/schema), provenance binding
    (Pillar 8), silent-failure sampling (Pillar 4)
11. Trace + audit-chain entry + SIEM export + control-status signal written
    (Pillar 5, 6) — this happens whether or not the call was blocked
12. Attribution graph updated (Pillar 13) so a later failure can be traced back
    to the step that introduced it
```

Tool calls and retrieval steps go through the equivalent gates
(`Enforcer.guard_tool_call`, `Enforcer.check_content`) rather than `run_completion`, but hit
the same policy/audit spine. The `Enforcer`'s modules are in
[low-level-design.md §3](low-level-design.md#3-the-enforcer--srcagentfoxruntimeenforcement).

### 6.1 Held calls and approval redemption

An escalation files an approval bound to the agent and the exact call, and the retry that
presents it runs once. Redemption, expiry and the race it prevents are in
[low-level-design.md §3.1](low-level-design.md#31-approvals-and-redemption--platformidentityservicepy).

### 6.2 Fail modes

How AgentFox itself degrades when one of its parts cannot do its job. The rule throughout is
that "could not check" is never recorded as "nothing there": every degradation shows up in a
decision, a finding or a refusal. A long-lasting degradation converts to closed
(`runtime/availability.py`). Each row is verified against the code named.

| Failure | What happens | Where |
|---|---|---|
| **A stored policy version no longer validates** (saved before a rule became mandatory, or before a field was tightened) | Every stored version loads through one function. A missing protected rule is restored from the shipped pack, with a warning once per version. Anything else raises `UnloadablePolicyVersion`; the other packs are still evaluated, and the decision records a `policy.unloadable` rule. A pack bound in observe never blocks; one bound in enforce blocks if the deployment's `fail_mode` or the pack's declared `fail_mode` is `closed`, and otherwise the call is allowed with the gap named. Promoting an unloadable version answers 422. | `platform/policy/store.py:load_version_document`, `runtime/enforcement/enforcer.py` |
| **Detectors time out or error** | Recorded per run on `detector_runs.status`. A detector that raised or reported `status="error"` is degraded exactly like one that timed out (and also listed in `errored`), so the decision is taken under the same two fail-mode sources and says so: `pipeline.fail_closed` names each degraded detector and why (`timeout`, `error: <cause>`). | `capabilities/detection/pipeline.py`, `runtime/availability.py` |
| **A monitor run fails** (GitHub down, token revoked, spec unreachable, URL refused by the outbound guard) | The run is recorded `failed` with its error; it closes no finding and keeps the previous baseline. After `monitor_failure_threshold` (default 3) consecutive failures one `monitor_failing` finding opens (medium), and the next successful run closes it. A run that read nothing it understood (an empty spec where there were operations, a repository scan that was inconclusive) is `inconclusive`: baseline kept, nothing closed. | `ee/src/agentfox_ee/monitoring/service.py:run_monitor`, `_record_failure` |
| **A probe target is unreachable or does not speak the contract** | Each probe is scored `error`, never `contained`: errors are counted in the campaign and neither open nor close a finding. A target whose URL host no longer matches the host registered at opt-in, or that resolves to a refused address, is refused before anything is sent. A deleted target fails its monitor run; a target not opted in, or live probes turned off, makes the run `inconclusive`. | `capabilities/evaluation/live_probes.py`, `ee/src/agentfox_ee/monitoring/service.py:_run_deployed_agent` |
| **The cron is not configured** | `/api/internal/jobs/run` answers 503 until `AGENTFOX_CRON_SECRET` or `CRON_SECRET` is set, and nothing periodic runs: no monitors, probes, canary advancement, drift checks or escalation scans. The GitHub Actions workflow without its two secrets says so and exits successfully. The Vercel cron alone fires once a day. Self-hosted deployments run `agentfox admin jobs run-due` from their own scheduler. | `apps/gateway/routes/jobs.py`, `.github/workflows/monitors.yml`, `platform/jobs/scheduler.py` |
| **Slack is configured but egress is off** | Nothing is sent, and the gateway logs once that a channel is configured while `AGENTFOX_ALLOW_EGRESS=false`. A delivery that fails is retried once on a 5xx, timeout or connection error, then logged and dropped; a full queue (500) drops the message; a tenant channel that cannot be decrypted is skipped. None of this fails the run that raised the finding. | `ee/src/agentfox_ee/monitoring/alerts.py` |
| **The GitHub push webhook cannot be verified** | No secret configured: 503 and nothing queued. A bad signature: 401. A verified push whose rescan cannot run after the response (a host that freezes the process) leaves a queued job the next cron run picks up. | `apps/gateway/routes/integrations.py:github_webhook` |
| **The gateway is started without real secrets** | Outside a development environment the process refuses to start while `AGENTFOX_SERVICE_AUTH_SECRET` or `AGENTFOX_AUDIT_SIGNING_KEY` is unset or a published value, naming the variable to set. Failing loudly at boot is the intended mode: running degraded would mean an owner token anyone can mint, or an audit chain anyone can forge. | `core/config.py:assert_production_secrets`, `apps/gateway/app.py:create_app` |
| **A retry presents an approval that does not fit** (used, expired, another agent's, different arguments) | The call escalates again, as it would have without the approval, and the decision's reason says why the approval was not used. An approval is never treated as a broader permission than the call a person saw. | `platform/identity/service.py:redeem_approval` |
| **A retry presents the approval a person denied**, for the same agent, tool and arguments | Blocked, with the `approval.denied` rule and the denier's rationale as the reason. No new approval is filed: a denial is an answer, not a request to ask again. | `platform/identity/service.py:denial_of`, `runtime/enforcement/enforcer.py:_refuse_denied_retry` |
| **A dependency is down for `/v1/*`** | `degradation_gate`: 503 under `fail_mode=closed`, otherwise served and stamped `X-AgentFox-Degraded`. | `apps/gateway/app.py`, `runtime/availability.py` |
| **A tenant-isolation, entitlement, data-access or audit-chain check cannot run** | Never fails open, whatever is configured. | `NEVER_OPEN` in `runtime/availability.py` |

---

## 7. Work outside the request: monitoring, live probes, jobs

The request path (§6) only sees what an agent sends. The rest runs unattended on one job
runner, so that a change nobody routed through the gateway still surfaces as a finding:

```
 Vercel cron (daily) ──────┐
 GitHub Actions (30 min) ──┴─► /api/internal/jobs/run ──┐
                               (cron secret)             ├─► scheduling pass: JobSchedule rows
 agentfox admin jobs run-due ─► same pass, in process ───┘   per tenant ─► jobs queue ─► run due
                                                                                │
 GitHub push ─► /api/integrations/github/webhook ─► monitors.run job ───────────┤
                (X-Hub-Signature-256 verified)       for that commit            ▼
                                     monitors.run · probes.run · canary.advance · drift.check · …
                                                                                │
                                         findings (deduplicated, self-closing) ─┤
                                         finding webhook (signed)  ◄────────────┤
                                         Slack, if configured      ◄────────────┘
```

- **Monitors** (AgentFox Enterprise). A `Monitor` re-reads one connected source (a GitHub
  repository, an OpenAPI spec, a remote MCP server, a deployed agent), diffs it against the last
  run, and raises or closes findings from the difference.
- **Live probes.** Opt-in red-team probes against a deployed agent's endpoint, for the question
  offline red-teaming cannot answer: does the agent running now still contain what it contained
  last week? The public `/live` showcase runs the same thing against the demo agent.

How each run works, its caps and its failure handling:
[low-level-design.md §15](low-level-design.md#15-monitoring-and-live-probes--eesrcagentfox_eemonitoring-enterprise-capabilitiesevaluationlive_probespy).

- **Scheduled jobs** (`platform/jobs/`). Per-tenant `JobSchedule` rows fill the queue (canary
  advancement, drift, escalation scan, learned-permission and tuning proposals, live probes,
  retention, and with Enterprise compliance recompute and monitors); the runner recovers stuck jobs and drains what is due. Nothing periodic
  runs unless something calls the runner: without a configured cron secret the endpoint
  answers 503, and on a self-hosted install `agentfox admin jobs run-due` belongs in the host's
  own scheduler.
- **Alerting.** Findings a run opens, reopens or closes go to the signed finding webhook and, if
  configured, to Slack, after commit and only with `allow_egress` on.

Everything here that fetches a URL a person supplied (a spec, an MCP server, a probe target)
goes through `core/outbound.py` (`guarded_get` / `guarded_post`): http(s) only, every resolved
address vetted and the connection pinned to it, no private or metadata addresses unless the
deployment allows private hosts, bodies read under a size cap.

---

## 8. Technology stack

| Layer | Technology | Notes |
|---|---|---|
| Core package | Python ≥3.11, FastAPI, SQLAlchemy 2.0, Pydantic 2.9, Typer, Alembic | Core deps deliberately minimal — everything that wraps a third-party OSS primitive is an optional extra (`pyproject.toml`), so `pip install agentfox` stays offline-capable |
| Database | SQLite (default, offline/local) or Postgres 16 (`AGENTFOX_DATABASE_URL`) | Alembic revisions in `migrations/versions/`, also shipped in the wheel |
| Policy engine | Native deterministic evaluator (default) or OPA/Rego (optional sidecar, falls back to native if unreachable) | `platform/policy/engine.py`, `platform/policy/opa.py` |
| PII/secrets detection | Native regex/NER, Presidio (Microsoft, MIT) | `capabilities/detection/adapters/presidio.py` |
| Safety/injection classifiers | Native lexicon (default, zero-weights), Granite Guardian (IBM, Apache-2.0), a two-model ensemble (`leolee99/PIGuard` + `protectai/deberta` backstop) | Model weights are an opt-in download, not bundled |
| Rails / structured validation | About seventy Guardrails AI validators ported as native code (Apache-2.0, no install); NeMo Guardrails (NVIDIA) and your own Guardrails AI Guard as optional adapters | `capabilities/detection/validators/`, `capabilities/detection/adapters/rails.py`, `capabilities/detection/adapters/hub.py` |
| Evaluation | Native runner (primary), Ragas adapter (optional) | promptfoo demoted to reference-only after its acquisition by OpenAI, Mar 2026 |
| Red-teaming | 22 native probes (OWASP LLM Top 10 / MITRE ATLAS mapped), Garak (NVIDIA) and PyRIT (Microsoft) as optional wrapped runners | `capabilities/evaluation/redteam.py` |
| SQL/action analysis | sqlglot (MIT, zero-dependency) | `capabilities/detection/actions.py` |
| Tracing | OpenTelemetry + OpenLLMetry semantic conventions; OTLP ingest as JSON or protobuf, optionally gzipped | `platform/ledger/trace.py`, `exporters/otel.py` |
| Auth (credentials) | argon2-cffi (password/credential hashing), `cryptography` (Fernet, at-rest encryption of connected-integration tokens) | Core deps, not optional — same reasoning as each other |
| Model providers | `echo` (offline default), OpenAI, Anthropic, Azure OpenAI, Bedrock, Vertex, LiteLLM | `platform/providers/` — the `ModelProvider` seam (§2) |
| Frontend | Next.js 15 (App Router), React 19, TypeScript 5.7 | No CSS framework, no state-management library. Server Components fetch server-to-server against `AGENTFOX_API_URL`; the one client-side exception is the unauthenticated `/playground`, which calls the gateway from the visitor's browser |
| Deployment | Docker Compose or Render blueprint (self-host), Vercel serverless (`api/`, the AgentFox Cloud gateway) with the dashboard on Render; an optional model server for model-backed detectors (`agentfox serve models`, `deploy/model-server/`) | See §10 for the architectural risk in running both |
| Observability export | Prometheus (`/metrics`, unauthenticated by design), SIEM export (OTLP/JSONL/CEF/LEEF/webhook) | `exporters/prometheus.py`, `exporters/siem.py` |
| Scheduling & alerting | In-process job queue persisted in the database; triggered by a cron call or `agentfox admin jobs run-due`; signed finding webhook, and Slack incoming webhooks (Enterprise) | `platform/jobs/`, `core/webhooks.py`, `ee/src/agentfox_ee/monitoring/alerts.py` — no external queue backend |
| Outbound fetches | httpx through `core/outbound.py` (address vetting, pinned connection, size caps) | Used by monitors, live probes, hosted-API discovery and provenance fetches |

---

## 9. What's proprietary vs. wrapped OSS

The project's own stated engineering split target is **~20% integrating OSS primitives, ~80%
building the governance logic on top** — the logic that turns a raw detection/policy primitive
into an actual governance *decision* ([Appendix A §A.5](../design/oss-register.md#a5-coverage-by-pillar)):

| | Examples | Status |
|---|---|---|
| **Wrapped OSS primitives** | Presidio (PII), Granite Guardian (safety classifier), sqlglot (SQL parsing), OPA/Rego (policy), OpenTelemetry (tracing), Garak/PyRIT (red-team probes) | Swappable behind an adapter interface (§2) — full licence/health register in [Appendix A](../design/oss-register.md) |
| **Proprietary, built here** | Argument-provenance taint tracking; deterministic blast-radius/action-semantics analysis on generated SQL; answerability & abstention against a declared knowledge boundary; end-user entitlement propagation through retrieval and tool calls; escalation-failure counterfactual detection; the tamper-evident audit chain and its independent verifier; the PIGuard+backstop ensemble tuning | This is the moat — none of it exists as an off-the-shelf OSS or commercial primitive today (validated against a live competitive scan) |

Three OSS dependencies have already changed status underneath the project within twelve
months (promptfoo acquired by OpenAI, Langfuse acquired by ClickHouse, LLM Guard archived) —
this is the concrete justification for principle #2 in §2, not a hypothetical risk.

---

## 10. Deployment topology

**Primary, supported path — self-hosted, `docker compose -f deploy/docker-compose.yml up`:**
four services (`db` = Postgres 16, `opa` = optional sidecar, `gateway`, `dashboard`), zero
runtime egress by default ([low-level-design.md §14](low-level-design.md#14-deployment-artifacts--deploy)
has the compose file breakdown). This is the deployment the product's compliance and
self-host-vs-SaaS claims are built for.

**AgentFox Cloud: Vercel serverless (`api/`) plus the dashboard on Render
(`deploy/render.yaml`):** `api/index.py` re-exports the gateway app; dependencies install from a **git-committed prebuilt wheel**
(`api/vendor/agentfox-<version>-py3-none-any.whl`) because Vercel's Root Directory for this
function is `api/`, so a relative import against `../src` doesn't ship. **This is an
architectural risk, not a packaging footnote**: a stale wheel ships stale code, and once caused
a production incident. It is controlled by the vendored-wheel rule in
[ARCHITECTURE.md](../../ARCHITECTURE.md#invariants-and-cross-cutting-concerns) (a pre-commit hook
and a CI freshness job).

A related consequence: the serverless deployment cannot run `alembic upgrade head` through
normal channels. The wheel now ships the migrations (`agentfox/_migrations`), but nothing on
Vercel runs them. `create_app()` calls `init_db()`, which creates new tables on startup, so an
additive change needs nothing more; any other schema change reaches the hosted database as a
hand-applied catch-up script (`deploy/neon-catchup-*.sql`). This is a deployment-model limitation, not a
code defect, and any future schema change needs the same treatment or an alternative.

**Both paths refuse to start on published secrets** outside development: the first would let
anyone mint an owner token, the second forge audit checkpoints. The check is described in
[low-level-design.md §10](low-level-design.md#10-gateway-composition--srcagentfoxappsgateway).

**Scheduled work needs a trigger.** The hosted gateway's job runner is called by a daily Vercel
cron (`api/vercel.json`) and every 30 minutes by `.github/workflows/monitors.yml`; both send
the cron secret. A self-hosted deployment runs `agentfox admin jobs run-due` from its own
scheduler (§7).

---

## 11. Non-goals — explicit boundaries

The project does not build, and does not intend to build (`docs/design/PRD.md` §10.3, §9):

- A model, vector database, agent framework, sandbox runtime, retrieval layer, or identity
  directory — it governs agents built on these, it is not one of them.
- A replacement for LangSmith/Langfuse-style execution tracing — it consumes and enriches
  traces, it doesn't compete on trace UX.
- Sandboxed code execution (that's E2B/Modal/Daytona's job).
- Full business-platform coverage. What exists is narrower: discovery reads the files Copilot
  Studio, Agentforce, Bedrock and other platforms export, and Copilot Studio, Vapi, Retell and
  AgentCore Gateway tool calls are governed through their pre-tool hooks. There is no tenant-wide
  connector to Power Platform or Salesforce, which still cedes ground to Zenity.
- Network-level agent discovery (as opposed to code/config-based discovery).
- Non-text modalities. Voice agents are governed at their tool calls and their call transcripts
  are recorded as text; audio itself is never inspected, and spoken numbers are not yet masked.

---

## 12. Where to go next

- **The code map and one tool call traced through the code**: [ARCHITECTURE.md](../../ARCHITECTURE.md)
- **Module-by-module detail, class signatures, DB schema, API endpoints**: [docs/architecture/low-level-design.md](low-level-design.md)
- **What is built, partial and absent**: [docs/status.md](../status.md)
- **Is this actually production-ready, and what's missing**: [docs/design/gap-analysis.md](../design/gap-analysis.md)
- **How this compares to the market**: [docs/design/competitor-analysis.md](../design/competitor-analysis.md)
- **The optional judgment tiers, and what they send off the machine**: [docs/architecture/judgment-tiers.md](judgment-tiers.md), [docs/architecture/judgment-egress.md](judgment-egress.md)
- **The full product reasoning this HLD condenses**: [docs/design/PRD.md](../design/PRD.md)
