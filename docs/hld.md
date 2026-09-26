# High-Level Design (HLD)

**Status: derived documentation, not source of truth.** This document explains the system
architecture in HLD form for engineers, reviewers and prospective adopters who want the
shape of the system before the detail. It is synthesized from the codebase (ground-truthed
by direct inspection, 2026-09-04) and from [docs/PRD.md](PRD.md), which remains the
canonical product document — if the two disagree, re-run the check this document describes
and trust the code. Companion documents: [docs/lld.md](lld.md) (module/class/API/schema
detail), [docs/production-readiness-review.md](production-readiness-review.md) (gaps),
[docs/competitor-analysis.md](competitor-analysis.md) (market position).

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
where genuine, currently-unclaimed differentiation lives (detail in
[competitor-analysis.md](competitor-analysis.md)), while 1–6 are table stakes done well.

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
   `enforcement.py` sets the verdict directly, so it stands whatever mode the packs
   are in.
2. **Every wrapped OSS primitive sits behind one interface.** `Detector`, `PolicyEngine`,
   `EvalRunner`, `RedTeamRunner`, `ModelProvider`, `ActionAnalyser`, `EntitlementEngine`,
   `CatalogSource` — eight seams (`docs/PRD.md` §7.2). When a dependency is acquired,
   archived, or licence-changes underneath the project (this has already happened twice —
   promptfoo→OpenAI, Langfuse→ClickHouse — see [Appendix A](appendix-a-oss-register.md)),
   exactly one adapter file changes, not the calling code.
3. **Self-host, zero egress by default.** `NOMETRIA_ALLOW_EGRESS=false` is the default in
   `deploy/docker-compose.yml`. The `echo` provider makes the entire enforcement path
   demonstrable with no API key, no model weights, and no network call. This is a deliberate
   wedge against SaaS-only competitors (Zenity, OneTrust, Credo AI) as well as a genuine
   requirement for regulated buyers.
4. **Fail-open is a per-policy, per-environment choice, not a hardcoded default.** Because the
   product sits inline on the request path to a model, an outage in the governance layer
   must not become an outage of the agent it governs (`docs/appendix-e-threat-model.md`
   §E.2). `NOMETRIA_FAIL_MODE=open` ships as the container default; hard budget/kill-switch
   gates are the deliberate exceptions.
5. **Computed, not attested.** Compliance-control status (Pillar 6) and failure-mode coverage
   are computed from telemetry (`compliance/status.py`'s `status_rule` predicates,
   `scripts/coverage.py --write`), not hand-maintained claims. `docs/status.md` is
   machine-regenerated for exactly this reason.
6. **Declared gaps over hidden gaps.** Framework-coverage tables list what a mapping does
   *not* cover (Appendix B §B.4); the threat model lists what it explicitly does not defend
   against (Appendix E §E.3); this HLD and its companion LLD apply the same standard.

---

## 3. Logical architecture — five layers, eighteen pillars

The eighteen pillars group into five layers along the lifecycle of one agent action
(`docs/PRD.md` §5):

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
│  src/agentfox/  (the package — 14,895 lines across ~40 modules       │
│  + 14 subpackages: audit, business, cli, compliance, evaluation,     │
│  gateway, guardrails, identity, integrations, policy, providers,     │
│  registry, sdk — see docs/lld.md §1 for the full inventory)          │
└─────────────────────────────────────────────────────────────────────┘
        │ imported by all four of:
        ▼
┌───────────────┐  ┌────────────────────┐  ┌──────────────────┐  ┌───────────────────┐
│  CLI           │  │  Gateway process    │  │  Client library   │  │  Dashboard          │
│  `agentfox`    │  │  FastAPI app        │  │  agentfox.auto()  │  │  (Next.js)          │
│  binary        │  │  (gateway/app.py)   │  │  or AgentFoxGuard │  │                     │
│  Typer, 1304   │  │  serves BOTH the    │  │  monkey-patches   │  │  Client of the API, │
│  lines,        │  │  inline proxy       │  │  the agent's own  │  │  no privileged      │
│  wraps every   │  │  (/v1/*) and the    │  │  process in-place │  │  back-channel       │
│  subsystem     │  │  control-plane API  │  │  (autoguard.py)   │  │  (principle X-5)    │
│                │  │  (/api/*) from one  │  │                    │  │                     │
│                │  │  process — a        │  │  Calls the SAME    │  │  ~60 route handlers │
│                │  │  deployment choice, │  │  Enforcer.preflight│  │  proxy mutations to │
│                │  │  not an             │  │  as the gateway    │  │  the gateway with   │
│                │  │  architectural one  │  │  (no reimplement-  │  │  session-cookie auth│
│                │  │  (stateless,        │  │  ation drift)      │  │  (lib/proxy.ts)     │
│                │  │  scales out         │  │                    │  │                     │
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
`agentfox.gateway.app:app` object as a Vercel serverless function, for a hosted demo/trial
path that doesn't require self-hosting Postgres. This is not a separately designed API — see
§9 for why it is nonetheless a real architectural risk.

**"Stateless, scales out horizontally" needs one scope note.** True for throughput — no
process holds request-scoped state across calls, so N replicas serve N times the traffic.
Not yet true for the admission controller and in-process budget/rate limiters
(`availability.py`, `gateway/app.py`'s `admission_gate` middleware): that state lives in each
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
`NOMETRIA_API_URL`; the one deliberate client-side exception is the unauthenticated
`/playground` route, which calls the gateway directly from the visitor's browser.

---

## 5. Integration surfaces

Three ways to adopt, explicitly designed to be additive and to meet a team where it already is
(`docs/PRD.md` §7.1):

| Surface | How it's used | What it gives you | Cost to adopt |
|---|---|---|---|
| **SDK / `agentfox.auto()`** | `import agentfox; agentfox.auto()` — detects installed frameworks from `sys.modules` (LangGraph, LangChain, LlamaIndex, CrewAI, AutoGen, FastAPI, Flask, Django, MCP, Ragas, LiteLLM) and monkey-patches the OpenAI, Anthropic, LiteLLM, and LangChain `BaseChatModel` call sites | Every model call traced, evaluated, audited — no code changes beyond the one import | One line |
| **LangGraph decorators** (`AgentFoxGuard`) | `guard.model_node(...)`, `guard.retrieval_node(...)`, `guard.tool_node(...)` wrap existing graph nodes | Same enforcement, plus tool-call gating *before* the wrapped function body runs, and indirect-injection scanning on retrieval output specifically | Named **the primary adoption path** — 11/11 surveyed senior AI engineers use LangGraph |
| **Inline gateway proxy** | Point an OpenAI/Anthropic client's `base_url` at the gateway's `/v1/chat/completions` or `/v1/messages` | Works for non-Python stacks and teams that can't touch application code at all | Config change only |
| **OTel ingestion** (`POST /v1/traces`) | Passive, zero-integration — the gateway just observes spans already being emitted | Pillars 1 (discovery) and 5 (audit) for free, no enforcement | Zero code change, but no blocking capability |

The SDK and LangGraph paths converge on one call: both eventually call
`Enforcer.preflight()` (`src/agentfox/enforcement.py:1591`). This matters architecturally —
there is exactly one enforcement code path, not two parallel implementations that could
silently drift (a bug the codebase's own comments note was fixed, not designed in from the
start — `autoguard.py:350-352`).

---

## 6. Request path

The sequence a single model call goes through, end to end (`docs/PRD.md` §7.3, verified
against `enforcement.py`'s `preflight`/`evaluate`/`call_provider` methods and
`gateway/routes/inline.py`'s `chat_completions` handler):

```
1. Resolve identity + end-user principal (Pillar 2, 10)
2. Kill-switch / quarantine check (control verdict — hard stop if quarantined)
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
9. Blocked → stop here, audited.  Escalate → hand off to a human (Pillar 2, 11).
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
the same policy/audit spine. See [docs/lld.md](lld.md) §3 for the method-level trace through
`enforcement.py`.

---

## 7. Technology stack

| Layer | Technology | Notes |
|---|---|---|
| Core package | Python ≥3.11, FastAPI, SQLAlchemy 2.0, Pydantic 2.9, Typer, Alembic | Core deps deliberately minimal — everything that wraps a third-party OSS primitive is an optional extra (`pyproject.toml`), so `pip install agentfox` stays offline-capable |
| Database | SQLite (default, offline/local) or Postgres 16 (`NOMETRIA_DATABASE_URL`) | 25 Alembic revisions to date (`migrations/versions/`) |
| Policy engine | Native deterministic evaluator (default) or OPA/Rego (optional sidecar, falls back to native if unreachable) | `policy/engine.py`, `policy/opa.py` |
| PII/secrets detection | Native regex/NER, Presidio (Microsoft, MIT) | `guardrails/adapters/presidio.py` |
| Safety/injection classifiers | Native lexicon (default, zero-weights), Granite Guardian (IBM, Apache-2.0), a two-model ensemble (`leolee99/PIGuard` + `protectai/deberta` backstop) | Model weights are an opt-in download, not bundled |
| Rails / structured validation | NeMo Guardrails (NVIDIA), Guardrails AI — both optional | `guardrails/adapters/rails.py` |
| Evaluation | Native runner (primary), Ragas adapter (optional) | promptfoo demoted to reference-only after its acquisition by OpenAI, Mar 2026 |
| Red-teaming | 22 native probes (OWASP LLM Top 10 / MITRE ATLAS mapped), Garak (NVIDIA) and PyRIT (Microsoft) as optional wrapped runners | `evaluation/redteam.py` |
| SQL/action analysis | sqlglot (MIT, zero-dependency) | `docs/lld.md` §3 |
| Tracing | OpenTelemetry + OpenLLMetry semantic conventions | `audit/trace.py`, `audit/otel.py` |
| Auth (credentials) | argon2-cffi (password/credential hashing), `cryptography` (Fernet, at-rest encryption of connected-integration tokens) | Core deps, not optional — same reasoning as each other |
| Model providers | `echo` (offline default), OpenAI, Anthropic, Azure OpenAI, Bedrock, Vertex, LiteLLM | `providers/` — the `ModelProvider` seam (§2) |
| Frontend | Next.js 15, React 19, TypeScript 5.7 | No CSS framework, no state-management library |
| Deployment | Docker Compose (self-host, default), Vercel serverless (`api/`, hosted trial path) | See §9 for the architectural risk in running both |
| Observability export | Prometheus (`/metrics`, unauthenticated by design), SIEM export (OTLP/JSONL/CEF/LEEF/webhook) | `integrations/prometheus.py` |

---

## 8. What's proprietary vs. wrapped OSS

The project's own stated engineering split target is **~20% integrating OSS primitives, ~80%
building the governance logic on top** — the logic that turns a raw detection/policy primitive
into an actual governance *decision* (`docs/README.md`, Appendix A §A.5):

| | Examples | Status |
|---|---|---|
| **Wrapped OSS primitives** | Presidio (PII), Granite Guardian (safety classifier), sqlglot (SQL parsing), OPA/Rego (policy), OpenTelemetry (tracing), Garak/PyRIT (red-team probes) | Swappable behind an adapter interface (§2) — full licence/health register in [Appendix A](appendix-a-oss-register.md) |
| **Proprietary, built here** | Argument-provenance taint tracking; deterministic blast-radius/action-semantics analysis on generated SQL; answerability & abstention against a declared knowledge boundary; end-user entitlement propagation through retrieval and tool calls; escalation-failure counterfactual detection; the tamper-evident audit chain and its independent verifier; the PIGuard+backstop ensemble tuning | This is the moat — none of it exists as an off-the-shelf OSS or commercial primitive today (validated against a live competitive scan — see [competitor-analysis.md](competitor-analysis.md)) |

Three OSS dependencies have already changed status underneath the project within twelve
months (promptfoo acquired by OpenAI, Langfuse acquired by ClickHouse, LLM Guard archived) —
this is the concrete justification for principle #2 in §2, not a hypothetical risk.

---

## 9. Deployment topology

**Primary, supported path — self-hosted, `docker compose -f deploy/docker-compose.yml up`:**
four services (`db` = Postgres 16, `opa` = optional sidecar, `gateway`, `dashboard`), zero
runtime egress by default, explicitly "the default and only MVP deployment mode"
(`docs/lld.md` §14 has the full compose file breakdown). This is the deployment the product's
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
risk is controlled rather than open: a pre-commit hook (`scripts/rebuild_vendored_wheels.py`)
rebuilds both vendored wheels whenever `src/agentfox/` changes, and CI's
`vendored-wheel-freshness` job fails any push that changes `src/agentfox/` without them.
The original finding is recorded in [production-readiness-review.md](production-readiness-review.md) §1.2.

A related consequence: because the serverless deployment cannot run `alembic upgrade head`
through normal channels (the deployed wheel doesn't bundle `migrations/`), `gateway/app.py`
carries a manual, owner-role-gated raw-DDL endpoint (`/api/_migrate_policy_canaries`) as a
one-off patch for exactly one migration. This is a deployment-model limitation, not a code
defect — but it means the Vercel path's schema-upgrade story is "patch per table by hand,"
not "run the migration," and any future schema change needs the same treatment or an
alternative solution.

---

## 10. Non-goals — explicit boundaries

The project does not build, and does not intend to build (`docs/PRD.md` §10.3, §9):

- A model, vector database, agent framework, sandbox runtime, retrieval layer, or identity
  directory — it governs agents built on these, it is not one of them.
- A replacement for LangSmith/Langfuse-style execution tracing — it consumes and enriches
  traces, it doesn't compete on trace UX.
- Sandboxed code execution (that's E2B/Modal/Daytona's job).
- Business-platform coverage — Microsoft Copilot Studio, Power Platform, Salesforce
  Agentforce are explicitly out of scope today (this cedes real ground to Zenity; see
  [competitor-analysis.md](competitor-analysis.md) §5).
- Network-level agent discovery (as opposed to code/config-based discovery).
- Non-text modalities.

---

## 11. Where to go next

- **Module-by-module detail, class signatures, DB schema, API endpoints**: [docs/lld.md](lld.md)
- **Is this actually production-ready, and what's missing**: [docs/production-readiness-review.md](production-readiness-review.md)
- **How this compares to the market**: [docs/competitor-analysis.md](competitor-analysis.md)
- **The full product reasoning this HLD condenses**: [docs/PRD.md](PRD.md)
