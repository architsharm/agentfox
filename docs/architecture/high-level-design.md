# High-Level Design (HLD)

**Status: derived documentation, not source of truth.** This document explains the system
architecture in HLD form for engineers, reviewers and prospective adopters who want the
shape of the system before the detail. It is synthesized from the codebase (ground-truthed
by direct inspection, last re-checked 2026-10-06) and from [docs/design/PRD.md](../design/PRD.md), which remains the
canonical product document — if the two disagree, re-run the check this document describes
and trust the code. Companion documents: [docs/architecture/low-level-design.md](low-level-design.md) (module/class/API/schema
detail), [docs/design/production-readiness-review.md](../design/production-readiness-review.md) (gaps),
[docs/design/competitor-analysis.md](../design/competitor-analysis.md) (market position).

---

## 1. What this system is

AgentFox is a **governance and assurance layer for AI agents that runs inline, enforces
policy, and proves what happened** — installed as a library into an agent's own process
(`pip install agentfox` + `agentfox.auto()`, or a LangGraph decorator), not procured as a
platform a team integrates against from the outside. A self-hosted control plane (gateway +
API + dashboard) is what a team graduates to once it has enough agents that "check the logs"
stops working — not the starting point.

It answers six questions, each owned by a **pillar**, each pillar's data flowing into the
next:

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
   are computed from telemetry (`capabilities/compliance/status.py`'s `status_rule` predicates,
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
│  src/agentfox/  (the package — subpackages only: core, jobs,         │
│  discovery, registry, runtime, containment, grounding, detection,    │
│  policy, business, identity, prove, evaluation, improvement,         │
│  monitoring, gateway, cli, hooks, integrations, sdk, providers —     │
│  see low-level-design.md §1 and ARCHITECTURE.md's code map)          │
└─────────────────────────────────────────────────────────────────────┘
        │ imported by all four of:
        ▼
┌───────────────┐  ┌────────────────────┐  ┌──────────────────┐  ┌───────────────────┐
│  CLI           │  │  Gateway process    │  │  Client library   │  │  Dashboard          │
│  `agentfox`    │  │  FastAPI app        │  │  agentfox.auto()  │  │  (Next.js)          │
│  binary        │  │  (gateway/app.py)   │  │  or AgentFoxGuard │  │                     │
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

**"Stateless, scales out horizontally" needs one scope note.** True for throughput — no
process holds request-scoped state across calls, so N replicas serve N times the traffic.
Not yet true for the admission controller and in-process budget/rate limiters
(`runtime/availability.py`, `apps/gateway/app.py`'s `admission_gate` middleware): that state lives in each
process's own memory, not a shared store (Postgres or a cache), so a horizontally-scaled
deployment gets N times the *declared* admission threshold and N times the declared budget —
each replica enforces its own local view rather than a cluster-wide one. Confirmed
2026-09-04. Same shape as the `fail_mode=open` per-process caveat traceability.md's PL-7 row
already documents for budgets specifically; this note makes it explicit that it also applies
to admission control. Moving this to shared state is real, non-trivial work (Effort: L); until
then, "scales out horizontally" should be read as "scales out for throughput, single-process
for admission/budget enforcement accuracy."

**Dashboard tech stack**: Next.js 15 (App Router), React 19, TypeScript 5.7. No CSS
framework and no client-state library — plain CSS and hand-built components
(`dashboard/components/`). Server Components fetch server-to-server against
`AGENTFOX_API_URL` (`NOMETRIA_API_URL` is still read as a fallback); the one deliberate client-side exception is the unauthenticated
`/playground` route, which calls the gateway directly from the visitor's browser.

---

## 5. Integration surfaces

Three ways to adopt, explicitly designed to be additive and to meet a team where it already is
(`docs/design/PRD.md` §7.1):

| Surface | How it's used | What it gives you | Cost to adopt |
|---|---|---|---|
| **SDK / `agentfox.auto()`** | `import agentfox; agentfox.auto()` — detects installed frameworks from `sys.modules` (LangGraph, LangChain, LlamaIndex, CrewAI, AutoGen, FastAPI, Flask, Django, MCP, Ragas, LiteLLM) and monkey-patches the OpenAI, Anthropic, LiteLLM, and LangChain `BaseChatModel` call sites | Every model call traced, evaluated, audited, and every tool call in a response authorised before the caller runs it — no code changes beyond the one import | One line |
| **LangGraph decorators** (`AgentFoxGuard`) | `guard.model_node(...)`, `guard.retrieval_node(...)`, `guard.tool_node(...)` wrap existing graph nodes | Same enforcement, plus tool-call gating *before* the wrapped function body runs, and indirect-injection scanning on retrieval output specifically | Named **the primary adoption path** — 11/11 surveyed senior AI engineers use LangGraph |
| **Inline gateway proxy** | Point an OpenAI/Anthropic client's `base_url` at the gateway's `/v1/chat/completions` or `/v1/messages` | Works for non-Python stacks and teams that can't touch application code at all | Config change only |
| **OTel ingestion** (`POST /v1/traces`) | Passive, zero-integration — the gateway just observes spans already being emitted | Pillars 1 (discovery) and 5 (audit) for free, no enforcement | Zero code change, but no blocking capability |

The SDK and LangGraph paths converge on one call: both eventually call
`Enforcer.preflight()` (`src/agentfox/runtime/enforcement/completion.py`), and every surface
(the gateway, the SDK, the MCP governor, the coding-agent hook daemon) ends in
`Enforcer.evaluate()`. This matters architecturally: there is exactly one enforcement code
path, not two parallel implementations that could silently drift (a bug that was fixed once,
not designed in from the start).

---

## 6. Request path

The sequence a single model call goes through, end to end (`docs/design/PRD.md` §7.3, verified
against `runtime/enforcement/`'s `preflight`/`evaluate`/`call_provider` methods and
`apps/gateway/routes/inline.py`'s `chat_completions` handler):

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
the same policy/audit spine. See [docs/architecture/low-level-design.md](low-level-design.md) §3 for the method-level trace through
`runtime/enforcement/`.

### 6.1 Held calls and approval redemption

An escalation files an `ApprovalRequest` bound to the agent and the exact call: the tool and
its canonicalised arguments, or for a held message its content digest. The proxy answers
**428** with the approval id; the agent (or the SDK's `wait_for_approval`) polls the approval
with its own key, and a person decides it in the dashboard or with `agentfox permit approvals`.
Approving is refused while the agent is killed or quarantined. The retry presents the approval
(`X-Nometria-Approval`, or `approval_id` on `/v1/guard/*`), and `evaluate()` redeems it only for
the same agent, tool and arguments, unexpired, and only once: the approval moves to `used` in a
conditional update, so two racing retries cannot both spend it. Anything else escalates again.
An unanswered approval expires, and expiry denies.

### 6.2 Fail modes

| What fails | Handling |
|---|---|
| A detector times out or errors | Recorded on its `detector_runs` row; the decision is taken under the fail mode, and a long-lasting degradation converts to closed (`runtime/availability.py`) |
| A dependency is down for `/v1/*` | `degradation_gate`: 503 under `fail_mode=closed`, otherwise served and stamped `X-Nometria-Degraded` |
| A bound policy version no longer validates | Loaded through `platform/policy/store.py:load_version_document`; a missing protected rule is restored from the shipped pack, anything else raises `UnloadablePolicyVersion`. The other packs still run, and a `policy.unloadable` rule is recorded: an observe-bound pack never blocks, an enforce-bound one blocks if the deployment or the pack says `closed` |
| A tenant-isolation, entitlement, data-access or audit-chain check cannot run | Never fails open (`NEVER_OPEN` in `runtime/availability.py`) |
| The process is started outside development with published secrets | Refuses to start (`InsecureConfigurationError`), see §10 |
| A monitor run, probe target or alert channel fails | Recorded and retried on schedule; never treated as "nothing there" (§7) |

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

- **Monitors** (`capabilities/monitoring/`). A `Monitor` watches one connected source: a GitHub repository,
  a hosted API's OpenAPI spec, a remote MCP server's tool listing, or a deployed agent (live
  probes). Each run re-reads the source, diffs it against the previous run's snapshot, raises
  findings for what appeared (a new tool or MCP server, removed governance, a lethal trifecta, a
  new destructive endpoint) and closes those whose condition cleared. The first run only stores
  a baseline. A failed run never closes anything or replaces the baseline; three failures in a
  row (`monitor_failure_threshold`) raise one `monitor_failing` finding. Monitors are created
  when a source is connected and scanned, or by hand (`agentfox scan monitors`,
  `/api/monitors`).
- **Live probes** (`capabilities/evaluation/live_probes.py`). Opt-in red-team probes against a deployed
  agent's endpoint, for the question offline red-teaming cannot answer: does the agent that is
  running now still contain what it contained last week? A target is created disabled; opting
  in records who agreed and the warning they read. Probes go only to the host registered at
  opt-in, through the vetted outbound client, under hard per-target and per-job caps. An escape
  opens a finding; a later contained run closes it. The public `/live` showcase runs the same
  thing against the demo agent in its own tenant, and is off unless `AGENTFOX_SHOWCASE_ENABLED`
  is set.
- **Scheduled jobs** (`platform/jobs/`). Per-tenant `JobSchedule` rows fill the queue (canary
  advancement, compliance recompute, drift, escalation scan, learned-permission proposals,
  monitors, probes); the runner recovers stuck jobs and drains what is due. Nothing periodic
  runs unless something calls the runner: without a configured cron secret the endpoint
  answers 503, and on a self-hosted install `agentfox admin jobs run-due` belongs in the host's
  own scheduler.
- **Alerting.** Findings a run opens, reopens or closes go to the signed finding webhook
  (`core/webhooks.py`) and, if configured, to Slack (the deployment's channel and a tenant's own
  `hooks.slack.com` webhook, stored encrypted). Both are sent only after the transaction commits
  and only with `allow_egress` on.

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
| Rails / structured validation | NeMo Guardrails (NVIDIA), Guardrails AI and its Hub validators — all optional | `capabilities/detection/adapters/rails.py`, `capabilities/detection/adapters/hub.py` |
| Evaluation | Native runner (primary), Ragas adapter (optional) | promptfoo demoted to reference-only after its acquisition by OpenAI, Mar 2026 |
| Red-teaming | 22 native probes (OWASP LLM Top 10 / MITRE ATLAS mapped), Garak (NVIDIA) and PyRIT (Microsoft) as optional wrapped runners | `capabilities/evaluation/redteam.py` |
| SQL/action analysis | sqlglot (MIT, zero-dependency) | `capabilities/detection/actions.py` |
| Tracing | OpenTelemetry + OpenLLMetry semantic conventions; OTLP ingest as JSON or protobuf, optionally gzipped | `platform/ledger/trace.py`, `exporters/otel.py` |
| Auth (credentials) | argon2-cffi (password/credential hashing), `cryptography` (Fernet, at-rest encryption of connected-integration tokens) | Core deps, not optional — same reasoning as each other |
| Model providers | `echo` (offline default), OpenAI, Anthropic, Azure OpenAI, Bedrock, Vertex, LiteLLM | `platform/providers/` — the `ModelProvider` seam (§2) |
| Frontend | Next.js 15, React 19, TypeScript 5.7 | No CSS framework, no state-management library |
| Deployment | Docker Compose (self-host, default), Vercel serverless (`api/`, hosted trial path) | See §10 for the architectural risk in running both |
| Observability export | Prometheus (`/metrics`, unauthenticated by design), SIEM export (OTLP/JSONL/CEF/LEEF/webhook) | `exporters/prometheus.py`, `exporters/siem.py` |
| Scheduling & alerting | In-process job queue persisted in the database; triggered by a cron call or `agentfox admin jobs run-due`; signed finding webhook and Slack incoming webhooks | `platform/jobs/`, `capabilities/monitoring/`, `core/webhooks.py` — no external queue backend |
| Outbound fetches | httpx through `core/outbound.py` (address vetting, pinned connection, size caps) | Used by monitors, live probes, hosted-API discovery and provenance fetches |

---

## 9. What's proprietary vs. wrapped OSS

The project's own stated engineering split target is **~20% integrating OSS primitives, ~80%
building the governance logic on top** — the logic that turns a raw detection/policy primitive
into an actual governance *decision* (`docs/README.md`, Appendix A §A.5):

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
runtime egress by default, explicitly "the default and only MVP deployment mode"
(`docs/architecture/low-level-design.md` §14 has the full compose file breakdown). This is the deployment the product's
compliance and self-host-vs-SaaS competitive claims are actually built for.

**Secondary path — Vercel serverless (`api/`), for a hosted trial/demo:** `api/index.py`
re-exports the gateway app; dependencies install from a **git-committed prebuilt wheel**
(`api/vendor/agentfox-<version>-py3-none-any.whl`) because Vercel's Root Directory for this
function is `api/`, so a relative import against `../src` doesn't ship. **This is an
architecturally significant risk, not a packaging footnote**: the wheel must be rebuilt
and committed after every change to `src/agentfox` that the hosted path should reflect.
It went stale once (dated 2026-08-28 while `enforcement.py`, `autoguard.py` and others
had changed), and history shows it caused a real incident (`551c220 revert(demo): restore
last known-good vendored wheel — production DB migration gap`). Since commit `6863b8b` the
risk is controlled rather than open: a pre-commit hook (`scripts/check/rebuild_vendored_wheels.py`)
rebuilds both vendored wheels whenever `src/agentfox/` changes, and CI's
`vendored-wheel-freshness` job fails any push that changes `src/agentfox/` without them.

A related consequence: the serverless deployment cannot run `alembic upgrade head` through
normal channels. The wheel now ships the migrations (`agentfox/_migrations`), but nothing on
Vercel runs them, so each schema change reaches the hosted database as a hand-applied
catch-up script (`deploy/neon-catchup-*.sql`). This is a deployment-model limitation, not a
code defect, and any future schema change needs the same treatment or an alternative.

**Both paths refuse to start on published secrets.** Outside a development environment
(`AGENTFOX_ENVIRONMENT` other than `development`/`dev`/`test`/`testing`/`local`), `create_app()`
raises `InsecureConfigurationError` if `AGENTFOX_SERVICE_AUTH_SECRET` or
`AGENTFOX_AUDIT_SIGNING_KEY` is unset or still a value published in this repository: the first
would let anyone mint an owner token, the second would let anyone forge audit checkpoints. The
compose file will not start without both, and the image no longer seeds demo data on boot; the
first operator is created with `agentfox admin users create`.

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
- Business-platform coverage — Microsoft Copilot Studio, Power Platform, Salesforce
  Agentforce are explicitly out of scope today (this cedes real ground to Zenity).
- Network-level agent discovery (as opposed to code/config-based discovery).
- Non-text modalities.

---

## 12. Where to go next

- **The code map and one tool call traced through the code**: [ARCHITECTURE.md](../../ARCHITECTURE.md)
- **Module-by-module detail, class signatures, DB schema, API endpoints**: [docs/architecture/low-level-design.md](low-level-design.md)
- **What is built, partial and absent**: [docs/status.md](../status.md)
- **Is this actually production-ready, and what's missing**: [docs/design/production-readiness-review.md](../design/production-readiness-review.md)
- **How this compares to the market**: [docs/design/competitor-analysis.md](../design/competitor-analysis.md)
- **The optional judgment tiers, and what they send off the machine**: [docs/architecture/judgment-tiers.md](judgment-tiers.md), [docs/architecture/judgment-egress.md](judgment-egress.md)
- **The full product reasoning this HLD condenses**: [docs/design/PRD.md](../design/PRD.md)
