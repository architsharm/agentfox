# Gap Analysis — Enterprise Readiness & Competitive Position

**Date:** 2026-08-18, updated 2026-08-29 · **Scope:** AgentFox Control Plane (grown from 18.7k LOC/178 tests to 50k+ LOC/1,131 tests over that window; those are dated figures, and current counts are in [status.md](status.md))
**Question:** what stops us selling this to an enterprise, and where do we stand against the field?

**2026-08-29 update:** a full grep/execution-verified re-audit (same discipline as the original —
every status below is a passing test or a direct code citation, not an inference) found most
Tier 0/1 items now closed, several Tier 2/3 items now real, and a recurring pattern worth its own
label: **stub-only** — a module that is genuinely built and individually tested but has **zero
callers on the live request path**. That's a materially better state than "absent" but a worse
one than "done," and several items below carry that marker instead of a flat ✅. One more finding
from this pass, outside the original scope but directly relevant: an internal
`docs/PRD.md` itself contained a stale claim ("no LangGraph integration" — since corrected there directly)
contradicted by 34 passing tests against a real `AgentFoxGuard` implementation — a reminder that
this document, not other planning docs, should be treated as the source of truth, and that it in
turn needs re-verification whenever claimed as evidence for something new.

**A second, independent correction, scoped to Part 2 specifically:** the five PRD variants that
existed on 2026-08-18 (`PRD.md`, `PRD-v2.md`, `PRD-consolidated.md`, `PRD-v3-consolidated.md`,
`PRD-v4-addendum.md`) have since been consolidated into a single `PRD.md` — the version cited
throughout this update. Checking Part 2's "this invalidates parts of the PRD" claim against that
consolidated PRD found most of it was **already fixed same-day** in the version written
2026-08-18, before this document's own market-move research even shipped. Part 2 below has been
corrected in place to show exactly what was already fixed, what's a genuine gap, and what's just
missing — the "stub-only" pattern in this note is the same *category* of finding: work that
exists but isn't where the summary claims it is.

---

## Verdict

We built a **technically differentiated core with a genuine wedge** — taint-based tool containment, a tamper-evident audit chain with an independent verifier, silent-failure detection, and control status computed from telemetry rather than attested. Three of those four are things **no competitor advertises**.

As of 2026-08-18 we also had something that **could not be deployed in front of a production agent, and could not pass an enterprise security review.** As of the 2026-08-29 re-audit, most of that specific blocker set is closed — see the Tier 0/1 tables below — though the procurement bar (SOC 2, ISO 27001, pentest, a filled-out SIG questionnaire) remains almost entirely organisational work, not engineering.

Three findings dominated the picture at the time; their current status:

1. **The gateway silently broke streaming.** ~~`stream: true` is ignored~~ — **now fixed and verified**: `gateway/routes/inline.py` implements real SSE streaming (`_stream_openai`, `_stream_anthropic`) for both OpenAI- and Anthropic-shaped requests.
2. **Our competitive research was already stale when we shipped.** Still true and unchanged by engineering work — **promptfoo → OpenAI** and **Lakera → Check Point** remain live platform-risk facts; see Part 2, unchanged from the original audit and still requiring a product decision (Part 7).
3. **Gartner published the first Magic Quadrant for AI Governance Platforms on 16 June 2026.** Re-verified 2026-08-29 against the current codebase: we now qualify on more of the eight inclusion criteria than before (evidence collection and audit trail were already strong; dynamic risk scoring, workflow/approvals, and interoperability all moved from "0 refs" to real-but-partial), but still fall short of full qualification — see the updated Tier 2 table.

The gap is not in the moat. The gap is, and remains, in everything that surrounds a moat and turns it into a product an enterprise can buy — though as of this update that surrounding gap is meaningfully smaller than it was.

**Fourth finding, added after a second pass on real deployment failures** — see the companion
[failure-modes.md](failure-modes.md), also updated 2026-08-29. Benchmarking against vendor
feature lists was the wrong lens. Measured against how enterprise agents *actually* fail, we
covered **1 of 50 failure modes outright** on 2026-08-18; a re-audit now finds **40 of 57 ✅**
against a taxonomy that grew to 57 catalogued modes (a seventh family, F8 context/retrieval
integrity, was added from the PRD), 3 partial, **11 built-but-not-wired** (all of F6 plus all of
F8 except F8.3 — F8 has the same "built, not called from a live request" problem as F6, just
less visible since it's reachable through a separate opt-in endpoint), and, as of 2026-08-30
(F3.8 composed privilege escalation built — see failure-modes.md), 2 genuinely still
absent (F7.7, F8.3). A separate, independent audit also found **5 more failure modes no
version of this taxonomy had ever catalogued** — see failure-modes.md's F9. A study of 10,000+
failure events found **<10% are hallucination-related**, while **31.1% are escalation/resolution
breakdowns** and execution/action failures are **up 62%** — those two categories (F5 escalation,
F3 action semantics) are now among the most-covered families in the taxonomy, not the least.
Read that document for the current state: it changed what to build first, and most of what it
called for has now been built.

---

## Method

- **Code audit** — capability checks run against the repository and the running system; every claim below is grep- or execution-verified and marked accordingly.
- **Market research** — 8 web searches and 3 deep fetches across agent-security, AI-governance and eval/observability vendor guides, the Gartner MQ, and enterprise procurement literature (sources at the end).
- Anything I could not verify is marked **unverified** rather than asserted.

---

## Part 1 — What we actually have (audited)

### Genuinely built and tested

| Capability | Evidence |
|---|---|
| PII / secrets / injection detection, input + output + tool args + tool result + retrieved | 5 surfaces, live-verified on each |
| **Taint tracking** — argument provenance, inferred or declared, propagated into tool calls | `test_taint_contains_an_irreversible_tool` |
| Tool-scoped least privilege, default-deny, argument-level constraints, provenance ceiling | `check_capability`, 6 tests |
| Delegation narrowing enforced at write time (tool pattern, actions, taint, approval) | 4 tests incl. glob-widening rejection |
| **Tamper-evident audit chain** — mutation, deletion, insertion/reorder, checkpoint forgery all detected | 8 tests + standalone verifier run outside the repo |
| Evidence package with stdlib-only `verify_chain.py`, draft mappings excluded | verified by extracting the zip and running it under system Python |
| **Silent-failure ensemble** — 6 signal families, discriminates confident-and-wrong from refusal | 8 tests |
| CI regression gate with direction-aware scorers, JUnit + SARIF | `test_gate_respects_scorer_direction` |
| Policy-as-code, immutable versions, observe→enforce promotion, Rego compilation | 12 tests |
| **Policy simulation** against recorded traffic, exits non-zero on new blocks | `test_policy_simulation_reports_a_diff` |
| Control status **computed** from telemetry; chain break forces `failing` | `test_broken_chain_makes_the_audit_control_fail_hard` |
| 43 controls × 7 frameworks with **declared gaps** per framework | `test_every_framework_has_a_gap_list` |
| Latency: 2–6 ms added on the heuristic path | `test_enforcement_stays_inside_the_latency_budget` |

### Verified absent (2026-08-18 baseline)

Every one of these returned zero matches in the codebase at the time:

`streaming` · `rate limiting` · `cursor pagination` · `kill switch / quarantine` · `multi-tenant org_id filtering` · `cloud connectors (Bedrock/Azure/Vertex/Salesforce)` · `ITSM (ServiceNow/Jira)` · `async job queue / scheduler` · `secrets manager (Vault/KMS)` · `bias / fairness testing` · `model registry / SR 11-7` · `dynamic risk scoring` · `framework instrumentation (LangChain/LlamaIndex callbacks)` · `DB migrations (Alembic)` · `notifications (Slack/PagerDuty/SMTP)`

SSO/SAML: 2 references — a seam, not an integration. Questionnaires: 2 references — a JSON column, not a workflow engine.

**2026-08-29 re-verification — what changed and what didn't:**

| Item | Now | Evidence |
|---|---|---|
| streaming | ✅ real | `gateway/routes/inline.py`: `_stream_openai`, `_stream_anthropic`, `StreamingResponse` for OpenAI- and Anthropic-shaped requests. Previously the doc's own headline finding ("silently dropped") — now false. |
| DB migrations (Alembic) | ✅ real | Alembic wired, migrations applied against prod Neon DB |
| kill switch / quarantine | ✅ real | Per-agent kill switch shipped, tested |
| multi-tenant org_id filtering | ✅ real, stronger than "filtering" | `src/agentfox/tenancy.py` enforces isolation structurally via session-level `with_loader_criteria`, not per-query filters — closes what was previously called "the single leak that ends the company" |
| rate limiting | ◐ partial, now wired | `gateway/app.py`'s `admission_gate` middleware now calls `availability.py::AdmissionController` on every `/v1/*` request — the inline surface an agent actually floods — before routing. `/api/*` (the operator control plane 1.3 below was originally about) is deliberately out of scope for the same budget: it is authenticated, low-volume, and sharing one budget risked an inline burst shedding the dashboard along with it |
| async job queue / scheduler | ✅ real (2026-09-16) | `jobs_db.py` runs evidence, red-team, eval, compliance, drift, canary and threshold-proposal jobs. It recovers stuck jobs and retries with exponential backoff. `scheduler.py` creates per-tenant default schedules, and the cron (`/api/internal/jobs/run`, GET or POST) queues due work on each run. Before this the cron sent GET to a POST-only route with the wrong secret name, so it never ran. |
| cloud connectors (Bedrock/Azure/Vertex/Salesforce) | ◐ partial, different shape than expected | `providers/enterprise.py` ships `AzureOpenAIProvider`/`BedrockProvider`/`VertexProvider`/`LiteLLMProvider` as outbound LLM-API connectors, tested — but these are model-provider connectors, not the estate-discovery connectors (Salesforce/ServiceNow/M365) the Gartner MQ criterion actually means. Salesforce remains absent either way. |
| framework instrumentation (LangChain/LangGraph callbacks) | ◐ real for LangGraph specifically | `integrations/langgraph.py` (`AgentFoxGuard`, 386 lines), verified via 34 passing tests in `tests/test_tranche0.py`. LlamaIndex/CrewAI/Claude Agent SDK still absent as instrumentation SDKs (only present as static-scan detection strings) |
| bias / fairness testing | ◐ narrow | `commitments.py::fairness_probe`/`FairnessResult` — one disparate-impact-style probe, not a named LL144/DSA audit workflow |
| dynamic risk scoring | ◐ real but categorical | `compliance/risk.py::classify()` computes a live prohibited/high/limited/minimal class from capability/tool/data signals, with `RiskAssessment`/`next_review_at`/`signed_off_by` — not a continuous numeric score per the literal Gartner bar, but no longer static or 0-refs |
| notifications (Slack/PagerDuty/SMTP) | ✗ still absent | unchanged |
| secrets manager (Vault/KMS) | ✗ still absent | Fernet-at-rest encryption exists for tokens/credentials; no external KMS/Vault |
| model registry / SR 11-7 | ✗ still absent | drift monitoring exists; no inventory/validation/challenge workflow |
| ITSM (ServiceNow/Jira) | ✗ still absent | unchanged |
| cursor pagination | ✗ still absent | unchanged |

---

## Part 2 — The market moved under us

**Update — 2026-08-29.** The table below still holds as a list of real market events. But
"this invalidates parts of the PRD and Appendix A" needs a correction: it's ambiguous
about *which* PRD, and that ambiguity matters. There were, on 2026-08-18, five PRD
documents in `docs/` (`PRD.md`, `PRD-v2.md`, `PRD-consolidated.md`,
`PRD-v3-consolidated.md`, `PRD-v4-addendum.md`). **The version that mattered —
`PRD-v3-consolidated.md`, dated the same day as this document — already incorporated
four of the six events below**, apparently from the same research pass that produced
this document. The four older variants have since been retired and their content folded
into a single `docs/PRD.md`, which is what the citations below point to. Presenting the
market-move finding as an open invalidation, without naming which PRD was stale, reads
as a bigger unresolved gap than what's actually left. Here is what's genuinely still
open, event by event:

| Event | Date | Status against `PRD.md` (current consolidated PRD) |
|---|---|---|
| **promptfoo → OpenAI** | 9 Mar 2026 | ✅ **Already corrected.** [`appendix-a-oss-register.md:19`](appendix-a-oss-register.md) downgrades it `REUSE ★ → REFERENCE ⚠`, dated 2026-08-18, with the note *"a model provider now owns our CI-eval substrate."* [`PRD.md:233`](PRD.md) already reads *"Dropped from the critical path; optional adapter only."* Nothing left to fix here — this row can be closed. |
| **OpenAI Frontier launched** | 5 Feb 2026 | 🟠 **Partially reflected — two specific lines still need qualifying.** The consolidation table at [line 234](PRD.md) already calls it *"bigger platform-risk event than AgentKit."* But the camps table at **line 342** still asserts model providers are *"not a compliance product"* — directly contradicted by line 234's own description of Frontier shipping compliance controls a few lines earlier. And [**line 722**](PRD.md)'s claim that computing status from telemetry is *"a claim only an inline platform can make"* is weakened by the fact that Frontier is itself now an inline, provider-run platform. Neither claim is fully false — AgentFox's cross-vendor-neutrality argument ([line 390](PRD.md)) still holds against a single-provider platform — but both need a qualifying clause, not silence. |
| **Lakera → Check Point** (~$300M) | Q4 2025 | ✅ **Already corrected.** Every reference already reads "Check Point (+Lakera)," correctly placed under Security suites. The "point tool to out-flank" framing this row worries about only ever existed in the oldest, now-retired PRD draft. |
| **Galileo → Cisco** | late 2025 | ✅ **Already corrected.** The PRD already reads "Galileo (Cisco)" throughout, folded into Security suites. |
| **Weights & Biases → CoreWeave** | 2025 | 🟡 **Genuinely missing — a completeness gap, not an invalidation.** It's in [`appendix-a-oss-register.md:90`](appendix-a-oss-register.md)'s changelog only. The PRD's actual competitive tables — the consolidation table ([line 229-238](PRD.md)) and Pillar 4's OSS/Commercial columns ([line 636-637](PRD.md), which lists Galileo, Cleanlab, Braintrust, Arize, Fiddler, Patronus) — never mention it. The PRD never made a claim about W&B's independence, so there's nothing to retract; it just needs adding. |
| **Microsoft Entra Agent ID + Agent 365** | GA through 2026 | ✅ **Already the correct strategic response.** The PRD states plainly: *"Microsoft Entra Agent ID will win agent identity"* ([line 387](PRD.md)), backed by a concrete requirement `P2-8` ([line 477](PRD.md)) and risk-register entry `R3` ([line 1087](PRD.md)). |

**Net correction:** of six events, **four were already fixed same-day** in the version
of the PRD that mattered, **one is a completeness gap** (add the W&B row), and **one is a
real, narrow contradiction inside the PRD's own text** (lines 342 and 722 need qualifying
against the PRD's own line 234). "This invalidates parts of the PRD" overstated the
residual problem — what's left is two sentences to edit and one row to add, not a
structural rethink.

**A second, related correction to this document's own Part 3.** Part 3 below criticizes
the PRD for modelling *"two camps"* where the real market has four. But that "two camps"
language only ever existed in the oldest, now-retired PRD draft. The PRD already models
**five camps** (§4.1, [line 334](PRD.md)) — Observability & eval, Agent security,
Security suites, AI governance platforms, and **Model providers** as a fifth camp,
specifically to capture OpenAI Frontier and Microsoft Entra. That's a finer breakdown
than even this document's own four-camp table in Part 3, which omits "Model providers"
entirely — despite this same Part 2 treating Frontier and Entra as the two most critical
consolidation events. Part 3's camps table is the one that's under-counting, not the PRD.

**Consequence, revised:** the "agent-native security is still forming and open" premise
was already being corrected in the PRD in step with these events, not left stale. The
real lesson isn't "the PRD is behind the market" — it's that a same-day fix in one PRD
revision doesn't automatically retire the concern in every document that cites the old
picture, including this one, and that the fix can get lost when several PRD variants
exist side by side (as they did until the post-2026-08-18 consolidation into a single
`PRD.md`). Three of the five camps are consolidating into incumbents with distribution;
that structural read still stands.

---

## Part 3 — The competitive field, as it actually stands

Four camps, not two. Our PRD modelled two.

| Camp | Players | Runtime enforcement | Compliance depth | Where we lose |
|---|---|---|---|---|
| **Agent-security pure-plays** | Zenity, Noma, Arthur, WitnessAI, Astrix | Strong | Thin | Estate-scale discovery, business-platform coverage, adaptive red team, maturity |
| **Security suites** | Palo Alto (Prisma AIRS), Cisco AI Defense, Check Point (+Lakera), SentinelOne (+Prompt Security) | Strong, network-integrated | Medium | Distribution, SOC integration, existing MSA |
| **AI governance platforms** (Gartner MQ) | IBM, ServiceNow, Truyo (Leaders); Airia, Credo AI, ModelOp, Monitaur, OneTrust (Visionaries); Holistic AI; Cranium, Relyance, Saidot, SAP | Mostly none — *Gartner notes most lack runtime enforcement* | Deep | Workflow engine, assessments, connectors, analyst recognition, installed base |
| **Eval / observability** | Braintrust, Arize, Fiddler, LangSmith, Patronus, Opik | N/A | N/A | Eval UX depth, datasets, experiment tooling, human review |

### What individual competitors have that we do not

| Competitor | Their capability | Our status |
|---|---|---|
| ServiceNow AI Control Tower | ~30 discovery integrations; MCP gateway; per-agent **kill switches** | ✗ none |
| Kosmoy | Kernel-enforced sandboxing, per-task credentials, kill switch, 4 cloud registries, air-gap K8s | ✗ none |
| Zenity | Inline step-level prevention *inside Copilot Studio*; low-code/Copilot agent coverage; Gartner "company to beat" | ✗ none |
| Noma | Adaptive red-team engine; per-agent identity + tool-level policy; self-host; $132M raised | ◐ static 11-probe suite |
| WitnessAI | Network-level capture of desktop apps and IDEs; PII **tokenisation**; warn/route/redact | ◐ tokenise yes, network capture no |
| Cisco AI Defense | Model validation, algorithmic red teaming, network-enforced guardrails, DefenseClaw sandbox | ✗ none |
| Astrix / Microsoft Entra | NHI lifecycle, secret rotation automation, Conditional Access, access packages, ITSM/SIEM/SOAR | ◐ NHI yes; no IdP, no SOAR |
| Credo AI | Policy Packs incl. NYC LL144; CE-marking support; Forrester Leader | ◐ 2 packs, all DRAFT |
| IBM watsonx.governance | AI Factsheets, SR 11-7 model-risk workflows, FedRAMP GovCloud | ✗ none |
| OneTrust | ~14,000-org installed base; third-party AI vendor risk; automated control mapping | ✗ none |
| Holistic AI | Published jailbreak audits; bias auditing; NYC LL144 / EU DSA audit heritage | ✗ none |
| LangSmith | Datasets with splits, pairwise comparison, experiments; $39/seat public pricing | ◐ basic suites |
| Almost all | **AWS / Azure Marketplace listing** (procurement path) | ✗ none |

---

## Part 4 — Gap register

Severity: 🔴 blocks the sale · 🟠 loses the bake-off · 🟡 competitive drag.
Effort: S ≤ 1wk · M 2–4wk · L 1–2mo · XL 3mo+ (single engineer).

### Tier 0 — Production blockers (the product cannot go inline)

Status as of 2026-08-29: **five of seven closed, two stub-only** (real, tested, zero live callers).

| # | Gap | Sev | Effort | 2026-08-18 evidence | 2026-08-29 status |
|---|---|---|---|---|---|
| 0.1 | **Streaming (SSE) unsupported and silently dropped** | 🔴 | M | verified: `stream:true` → non-streaming JSON | ✅ closed — real SSE streaming in `gateway/routes/inline.py` |
| 0.2 | **No DB migrations** — `create_all()` only; a deployed instance cannot be upgraded | 🔴 | S | verified absent | ✅ closed — Alembic wired and applied against prod |
| 0.3 | **No kill switch / quarantine** — cannot stop a misbehaving agent; every competitor has one | 🔴 | S | verified absent | ✅ closed — per-agent kill switch shipped and tested |
| 0.4 | **Agent tool-calling loop not governed** — proxy forwards `tools`/`tool_calls` but does not enforce across the multi-turn loop | 🔴 | M | 2 refs only | ✅ closed (2026-09-16) — `gateway/routes/inline.py::_govern_tool_loop` reconstructs the tool-calling run from the request body on both proxy routes (`/v1/chat/completions`, `/v1/messages`, streaming included) and scores it with `agent_loop.govern_loop` under the configured `NOMETRIA_LOOP_*` budgets. A stopped verdict returns the route's existing `agentfox_policy_violation` body under the shipped `loop.runaway` rule (NOM-RTG-08) and records a trace plus an `agent_loop_stopped` finding. Correlated by `X-Nometria-Session`; a request with no session header, or no tool calls, is unaffected. |
| 0.5 | **Everything synchronous** — evidence build, red-team, compliance compute run in-request | 🔴 | M | no queue/scheduler | ✅ closed (2026-09-16) — evidence and red-team requests run their own job and return 202 `queued_for_retry` when the first attempt fails. Recurring work runs through `scheduler.py` schedules drained by the cron. |
| 0.6 | **No HA / scale validation**; SQLite default is single-writer; NFR-3 never tested | 🔴 | M | acknowledged in traceability | ✅ closed — `db.py::configure_pool` supports pooled/HA deployment, live on Neon |
| 0.7 | No graceful degradation path if the control plane is down (fail-open exists per-detector, not per-service) | 🟠 | S | — | ✅ closed (2026-09-16) — `gateway/app.py::degradation_gate` probes the four dependencies a `/v1/*` request needs (detector pipeline, policy engine including a remote OPA, database beyond the request's own session, configured model provider) and applies `service_fallback`/`DegradationLedger` under `NOMETRIA_FAIL_MODE`, constructed through `FailPolicy` so the `NEVER_OPEN` rule still binds. Fail-closed returns 503 `agentfox_service_degraded`; fail-open serves, records, stamps `X-Nometria-Degraded`, and converts to closed past its budget. Visible on `GET /api/health` and `GET /api/reliability`. |

**Net, updated 2026-09-16:** Tier 0 is closed. Streaming and migrations closed earlier; 0.5 closed with the deferred job queue (PL-5); **0.4 and 0.7 closed this cycle**, each wired onto the live request path with tests that drive the real FastAPI app rather than the library. The "built the library, didn't plug it in" pattern this row used to describe is now closed across Tier 0 and — for nine of eleven detectors — in [failure-modes.md](failure-modes.md)'s F6/F8 as well. Two things stay deliberately unwired with stated reasons (F6.5, F8.4); that judgement should be re-read rather than reversed by default.

### Tier 1 — Procurement blockers (cannot pass a security review)

Status as of 2026-08-29: **four closed, one stub-only, four still organisational** (SOC 2/ISO/pentest/DPA are not code problems and were never going to close from engineering work alone). **Update, 2026-08-30:** 1.3's `AdmissionController` is no longer stub-only — it is wired live, on the inline surface rather than literally "the control plane" this row names; see its own row for the distinction.

| # | Gap | Sev | Effort | 2026-08-18 note | 2026-08-29 status |
|---|---|---|---|---|---|
| 1.1 | **No real SSO (OIDC/SAML) or SCIM** — dev identity header in production code path | 🔴 | M | 40–60% of a SIG questionnaire is answerable from SOC 2 + SSO evidence | ◐ partial — dev header now refused outside development mode, real API-token auth shipped (`gateway/deps.py`/`gateway/auth.py`); OIDC still only a schema seam (`User.external_id`), no live IdP integration, SCIM 0 matches |
| 1.2 | **Multi-tenancy not enforced** — `org_id` column exists, 0 queries filter on it | 🔴 | M | a single leak here ends the company | ✅ closed, and closed the strong way — `tenancy.py`'s session-level `with_loader_criteria` enforces isolation structurally, not via per-query filters that could be individually forgotten |
| 1.3 | **No rate limiting / quota** on the control plane | 🔴 | S | verified absent | ◐ partial, not stub-only anymore — `AdmissionController` is now wired live on `/v1/*` (`gateway/app.py::admission_gate`), which is where an overloaded or misbehaving agent actually generates load; the control plane (`/api/*`) this row names specifically is operator-authenticated and was left out of the same budget deliberately — still genuinely unquota'd if that's the literal surface meant here |
| 1.4 | **Signing key and provider keys in env vars** — no Vault/KMS/CSFLE | 🔴 | M | undermines our own NFR-7 claim | ◐ partial — Fernet encryption at rest for tokens/credentials now real (`config.py:token_encryption_key`, `*_encrypted` model columns); still no external KMS/Vault |
| 1.5 | **No SOC 2 Type II / ISO 27001** for us as a vendor | 🔴 | XL (org) | *most enterprise buyers require SOC 2 Type II before signing* | ✗ unchanged — organisational, not an engineering task |
| 1.6 | No third-party penetration test, VDP, or security.txt | 🔴 | M (org) | standard questionnaire item | ✗ unchanged |
| 1.7 | No DPA, sub-processor register, DR/backup, RTO/RPO, incident-response commitments | 🔴 | M (org) | — | ✗ unchanged |
| 1.8 | Dashboard is read-only and unauthenticated beyond a header | 🟠 | M | no approve/suppress/assign from UI | ✅ closed — dashboard now has real auth, write actions (approve/suppress/assign), and a full app's worth of pages built out this session |
| 1.9 | No audit log of *control-plane* logins/sessions (we audit agents, not operators) | 🟠 | S | ironic for an audit product | ✅ closed — `operator_log.py`: a `PRIVILEGED` registry plus a structural `unaudited()` check that fails the test suite if a new privileged surface ships unaudited, writing into the same hash-chained log as agent audit events |

### Tier 2 — Gartner MQ inclusion criteria (category table stakes)

Gartner's inclusion bar required all of the following **GA by 1 April 2026**: AI discovery and registry; compliance risk management; policy management and enforcement; **dynamic risk scoring**; evidence collection; **interoperability**; **workflow and approvals**; complete audit trail.

Status as of 2026-08-29: **still short of full qualification, but every "0 refs" item moved to real-but-partial.**

| # | Criterion | 2026-08-18 status | 2026-08-29 status | Sev | Effort |
|---|---|---|---|---|---|
| 2.1 | **Dynamic risk scoring** — continuous, signal-driven score per agent | ✗ static classification only, 0 refs | ◐ real but categorical — `compliance/risk.py::classify()` computes `proposed_class` (prohibited/high/limited/minimal) from live capability/tool/data signals with a re-assessment cycle (`next_review_at`, `signed_off_by`); still not a continuous numeric score per the literal Gartner bar | 🟠 | M |
| 2.2 | **Interoperability** — connectors to the estate (Bedrock, Azure AI, Vertex, Salesforce, ServiceNow, M365) | ✗ 0 refs; gateway + OTel only | ◐ model-provider connectors real (`providers/enterprise.py`: Azure/Bedrock/Vertex/LiteLLM, tested); business-platform connectors (Salesforce/ServiceNow/M365) still 0 refs — this criterion means estate connectors, not LLM API connectors, so the gap is narrower but not closed | 🔴 | L |
| 2.3 | **Workflow and approvals** — assessments, review cycles, attestations, task routing | ◐ runtime approvals only; no workflow engine | ◐ stronger — risk assessment cycle real (`risk.py`), escalation/handoff task routing real (`escalation.py`: `EscalationPolicy`, `Handoff`); still no *general* cross-domain workflow engine, task routing exists specifically for escalation | 🟠 | L |
| 2.4 | Discovery and registry at **estate scale** | ◐ inline + OTel; no agentic-platform enumeration | ◐ unchanged — `discovery.py` is still a static repo/OpenAPI scan, no agentic-platform enumeration (Bedrock console, Copilot Studio catalog) | 🟠 | L |
| 2.5 | Evidence collection | ✅ strong — arguably best-in-class | ✅ confirmed, unchanged | — | — |
| 2.6 | Complete audit trail | ✅ strong — genuinely differentiated | ✅ strengthened — now also covers operator/control-plane actions via `operator_log.py`, same hash chain | — | — |
| 2.7 | **Findings do not auto-escalate to a human** — no owner routing, SLA, or deadline | 🟠 | ✅ closed — `escalation.py`'s `EscalationPolicy.owner_role`/`sla_minutes`, `breached_handoffs()`, `detect_missed_escalation()`; 36 tests | — | — |

### Tier 3 — Competitive parity

Status as of 2026-08-29: **3 closed, 6 real-but-partial, 7 still genuinely absent or organisational.**

| # | Gap | 2026-08-18 status | 2026-08-29 status | Sev | Effort |
|---|---|---|---|---|---|
| 3.1 | Business-platform agents (M365 Copilot, Copilot Studio, Power Platform, Salesforce Agentforce) | absent | ✗ still absent — 0 refs to any of these platform names | 🟠 | XL |
| 3.2 | Adaptive / generative red teaming (ours is 11 static probes) | absent | ✅ closed (2026-09-16) — a native adaptive campaign engine (`evaluation/adaptive.py`, `agentfox redteam run --adaptive`) mutates a blocked probe and retries under a per-probe budget, steering from the failure, and generates probes from *this deployment's* own grants, tool impacts and bound policies. It reports a **posture delta** against the last comparable campaign rather than a pass rate, because a pass rate here would be a robustness claim the engine cannot support. Garak/PyRIT still wrap in as optional external runners. Found two real bugs on first run: a nested-argument blind spot in action assurance (fixed) and glob-grant overbreadth. | 🟠 | L |
| 3.3 | Framework instrumentation SDKs — LangChain/LangGraph callbacks, LlamaIndex, CrewAI, Claude Agent SDK | absent | ◐ LangGraph, MCP, and FastAPI real and tested (`integrations/langgraph.py`, 34 passing tests in `tests/test_tranche0.py`; `integrations/mcp.py`, `integrations/fastapi.py`); LlamaIndex/CrewAI only appear as static-scan detection strings, not instrumentation SDKs; no Claude Agent SDK integration | 🟠 | M |
| 3.4 | Entra Agent ID / Okta / Ping integration for NHI | absent | ◐ unchanged — NHI lifecycle itself is real and self-contained (`identity/service.py`, 532 lines) but 0 refs to any external IdP | 🟠 | M |
| 3.5 | FinOps — token cost attribution, budgets, chargeback | absent | ◐ budgets and cost tracking real (`reliability.py::check_budget/charge`, `Budget` model with `max_cost_usd`/`cost_usd`/`tokens`); no chargeback/cost-report-by-team endpoint | 🟠 | M |
| 3.6 | Bias / fairness testing (NYC LL144, EU DSA) — a named Holistic AI strength | absent | ◐ narrow — `commitments.py::fairness_probe`, one disparate-impact-style probe; no named LL144/DSA audit workflow | 🟠 | L |
| 3.7 | Model risk management / SR 11-7 workflows — required in financial services | absent | ✗ still absent — only a stylistic comment reference in `evaluation/drift.py`; no model inventory/validation/challenge workflow | 🟠 | L |
| 3.8 | Third-party / vendor AI risk assessment — OneTrust's wedge | absent | ✗ still absent | 🟡 | M |
| 3.9 | Memory & RAG governance (poisoning, retention, right-to-erasure in vector stores) | absent | ✅ substantially built — `MemoryEntry` model with `taint_source`/`expires_at`/`revoked_at`/`verified_by`, `gateway/routes/memory.py::revoke_entry`, enforcement runs the detector pipeline on memory writes; 16 tests cover poisoning/redaction/revocation. No formal retention-policy engine, but deletion (`revoke_entry`) is real | 🟠→closed | — |
| 3.10 | Sandboxed execution / per-task credentials | absent, explicit non-goal | ✗ still absent, still deliberate — `guardrails/actions.py:355` explicitly documents shell containment as "a backstop, not a sandbox" | 🟡 | XL — *explicit non-goal; revisit* |
| 3.11 | Network-level discovery (desktop apps, IDEs) | absent | ✗ still absent | 🟡 | XL |
| 3.12 | AWS / Azure Marketplace listing | absent | ✗ still absent — organisational | 🟠 | M (org) |
| 3.13 | Analyst engagement (Gartner MQ, Forrester Wave) | absent | unverifiable — organisational | 🟠 | L (org) |
| 3.14 | Eval UX depth — dataset splits, pairwise comparison, human review queues, experiment tracking | absent | ✗ still basic — no splits/pairwise/review-queue/experiment-tracking hits beyond a literal `split="production"` | 🟡 | L |
| 3.15 | **All 257 framework mappings are DRAFT** — our own gate excludes them from evidence packages | 🔴 gap | ◐ review mechanism now real and tested (`compliance/catalog.py::review_mapping()`, draft mappings still excluded from evidence per `test_draft_mappings_excluded_from_evidence`) — some real mappings have been reviewed as part of this session's work, but full legal sign-off across all 210 current mappings remains an organisational/domain-expert task, not a code gap | 🔴→◐ | L (needs qualified reviewer) |
| 3.16 | No published pricing or self-serve tier — every Tier-A motion in the PRD assumes PLG | absent | ✗ still absent — organisational | 🟠 | M |

---

## Part 5 — Where we are genuinely ahead (defend these)

These are real, tested, and largely unclaimed by the field:

1. **Argument-provenance taint tracking.** Zenity's "intent-based detection examines the full execution path including tool calls" is the closest public claim; nobody else advertises argument-level provenance with a capability ceiling. Our containment holds *after* detection fails — that is the durable defence.
2. **Tamper-evident audit with an independent verifier.** No competitor advertises a hash-chained log shipping a stdlib-only verifier an auditor can run without the vendor. For regulated buyers this is a differentiator you can demonstrate in 60 seconds.
3. **Silent-failure detection.** Galileo and Braintrust do evals; nobody frames *governing correctness* as part of the governance product. Gartner's own read is that the governance camp lacks runtime — we have runtime **and** correctness.
4. **Control status computed from telemetry, not attested.** The governance camp collects attestations. We compute, and a broken chain forces `failing`.
5. **Declared gaps per framework.** Publishing what we do *not* cover is unusual and disproportionately credible in an audit conversation.
6. **Policy simulation before enforcement** — replays real traffic, exits non-zero on new blocks.
7. **Self-host default, zero egress, offline-capable.** Zenity is SaaS-only; Credo AI is SaaS-only; OneTrust is SaaS-only. For regulated buyers this is a live wedge.

**Strategic read:** Gartner explicitly notes most governance platforms lack runtime enforcement, and the security pure-plays lack compliance depth. **Our original thesis is still correct.** We are losing on the surrounding product, not on the idea.

**Added 2026-08-29 — new items earned since the original list:** entitlement-aware disclosure control (F4), destructive-action blast-radius analysis (F3), answerability/abstention (F1), source authority/citation binding (F2), and escalation governance with owner+SLA routing (F5) are now real, tested, and — per [failure-modes.md](failure-modes.md) — cover 40 of 57 modes in the taxonomy that actually predicts production failures. None of the four camps in Part 3 advertises this combination. This is now as defensible a claim as the original four items, and arguably more commercially legible: it maps directly to named incidents (the 1.9M-row wipe, the Copilot oversharing pattern) rather than to abstract architecture properties. **Caveat before selling F6 or F8 (context integrity) as covered: don't, but the two are no longer identical.** F6 (`commitments.py`/`register.py`) is built and individually tested but genuinely wired into nothing — confirmed 2026-09-04 by tracing its actual exported functions (not just the ambiguous word "register"), zero real call sites outside its own module and tests. F8 has moved partway: `context_integrity.py`'s `chunk_quality`/`document_quality` are reachable via a real, callable route (`POST /provenance/context-check`) as of the current codebase — a caller can genuinely exercise this today — but it's still not on the automatic inline gateway path, so a normal chat/completion request gets none of it automatically. See failure-modes.md's `◐-unwired` status for the precise per-mode breakdown. Neither is a shipped, automatic control yet; F8 is closer than F6.

---

## Part 6 — The enterprise procurement bar

What a Tier-B/C buyer will require before signing, and our status. Updated 2026-08-29 — **8 of 14 now unmet** (was 11 of 14). The remaining gaps are almost entirely organisational (certifications, legal documents, SLAs), not engineering work; the items that *were* engineering work are now closed.

| Requirement | 2026-08-18 | 2026-08-29 |
|---|---|---|
| SOC 2 Type II report | ✗ | ✗ unchanged — organisational |
| ISO 27001 certification | ✗ | ✗ unchanged — organisational |
| SIG Lite / SIG Core questionnaire response | ✗ no completed questionnaire | ✗ still no completed response |
| Third-party penetration test report | ✗ | ✗ unchanged — organisational |
| SSO (SAML/OIDC) + MFA + SCIM | ✗ | ◐ auth hardened — real API-token auth, dev header refused outside dev mode; OIDC still only a schema seam, no live SSO/SCIM |
| RBAC with least privilege | ✅ (6 roles, enforced, tested) | ✅ confirmed unchanged — `ALL_ROLES = {owner, admin, security, compliance, developer, auditor}`, `WRITE_ROLES` matrix enforced |
| Data residency / regional hosting | ◐ self-host yes; no managed regions | ◐ unchanged |
| Encryption at rest + in transit, key management | ◐ transport yes; no KMS/CSFLE | ◐ stronger — Fernet-encrypted credentials/tokens at rest now real; still no external KMS/Vault |
| DPA, sub-processors, GDPR/DPIA support | ✗ | ✗ unchanged — organisational |
| BC/DR, RTO/RPO, backup/restore | ✗ | ✗ unchanged — organisational, 0 refs to RTO/RPO in code |
| Uptime SLA + support tiers | ✗ | ✗ unchanged — organisational |
| Audit log of administrative actions | ◐ agents audited, operators not | ✅ closed — `operator_log.py`'s structural `unaudited()` check fails the test suite if a new privileged surface ships unaudited |
| Vulnerability management + patch SLA | ✗ | ✗ unchanged — organisational |
| AWS/Azure Marketplace (procurement path) | ✗ | ✗ unchanged — organisational |

**8 of 14 are unmet**, all of them organisational (certifications, third-party audits, legal documents, SLA commitments) rather than code gaps — closing them requires a compliance/legal motion, not another engineering sprint.

---

## Part 7 — Recommendation (updated 2026-08-29)

**The original four-phase sequencing has mostly played out. Here's the honest status of each phase, and what's actually left.**

- **Phase A — Make it deployable (Tier 0).** ✅ **substantially done.** Streaming, migrations, kill switch, and HA are real and verified. Agent-loop governance (`agent_loop.py`) and per-service graceful degradation (`availability.py`'s admission controller, wired into `gateway/app.py`'s middleware) are now both **wired into the live path**, not stub-only — confirmed 2026-09-04. Async workers (`jobs.py`) remain genuinely **stub-only**: a real, tested in-process queue interface with zero callers, deliberately not wired into a Redis/SQS implementation until scale demands it.
- **Phase B — Make it buyable (Tier 1).** ◐ **mostly done.** Multi-tenancy enforcement, operator audit log, and a writable/authenticated dashboard are closed. Rate limiting is stub-only (same pattern as Phase A). SSO/SCIM and KMS remain partial. The SOC 2 clock still hasn't been started — it's organisational, not engineering, and remains the longest pole by far.
- **Phase C — Qualify for the category (Tier 2).** ◐ **meaningfully advanced, not complete.** Dynamic risk scoring and escalation task-routing are now real (moved off "0 refs"). The finding→HITL escalation gap (2.7) is fully closed. Estate-scale connectors (Salesforce/ServiceNow/M365) and a general workflow/approvals engine remain the honest gaps — what exists today is real but narrower than the Gartner MQ criterion asks for.
- **Phase D — Differentiate on real failure modes, not competitor features.** ✅ **done, and it's now the strongest part of the story** — with one honest asterisk. Per [failure-modes.md](failure-modes.md), all four families named here (entitlement-aware data access, action semantics/blast radius, answerability & abstention, source authority) plus escalation governance (F5) are built, tested, and **live on the request path** — 40 of 57 failure modes now covered vs. 1 of 50 when this phase was proposed. The asterisk: a seventh family, context/retrieval integrity (F8), turned out to have the same built-but-unwired problem as F6 below. Sandboxing and business-platform coverage remain deliberately skipped, unchanged from the original call.

**What's actually left, in priority order:**

1. **Wire the remaining stub-only modules.** Updated 2026-09-04: `agent_loop.py` and `availability.py`'s admission controller are now both wired into the live path (the former including a step-history-aware wiring through both the gateway's `/v1/guard/tool_call` and the LangGraph SDK, not just a per-tool repeat count). `context_integrity.py` moved partway — reachable via a real `POST /provenance/context-check` route, but still not on the automatic inline gateway path. What's left: **`jobs.py`** (fully stub, no callers at all) and **F6's `commitments.py`/`register.py`** (confirmed fully stub-only by tracing their actual exported functions, not just a grep for "register" — zero real call sites outside their own modules and tests). The logic exists and is tested for five failure modes (F6.1-F6.5); it just isn't called from anywhere a live request passes through. This is still the highest-leverage remaining item, just a smaller one than it was.
2. **Start the SOC 2 / ISO 27001 / pentest clock.** Still the longest pole, still entirely organisational, still unstarted.
3. **Close the two remaining genuinely absent failure modes** (F7.7 cross-turn self-contradiction, F8.3 stale index) — real, scoped, moderate-effort builds, not XL. F3.8 composed privilege escalation, previously third on this list, was built 2026-08-30 (`guardrails/composition.py`) — see failure-modes.md.
4. **Build the five modes an independent audit found that this taxonomy never catalogued** — failure-modes.md's F9 (invalid logical inference, sycophancy, non-English quality parity, crescendo manipulation, context stuffing), each with a concrete detection design that reuses already-wired infrastructure.
5. **Decide on Salesforce/ServiceNow/M365 estate connectors** — the one remaining Tier 2 gap that's a real, if large, build rather than organisational work or a wiring fix.

Two decisions from the original document remain genuinely unresolved:

1. **Reclassify promptfoo.** Still provider-owned (OpenAI). Not revisited this pass — still open.
2. **Vertical or horizontal.** Still unresolved, and it still determines whether the next build cycle includes SR 11-7 (financial services) or deeper bias-auditing workflows (HR/employment) — both remain real gaps either way (3.6, 3.7).

---

## Sources

Vendor and market research: [Arthur — Best AI Agent Security Platforms 2026](https://www.arthur.ai/column/best-ai-agent-security-platforms-2026) · [Kosmoy — Best AI Agent Governance Platforms 2026](https://www.kosmoy.com/resources/blog/best-ai-agent-governance-platforms-2026/) · [Kosmoy — Best AI Governance Platforms 2026 (9 vendors + Gartner MQ)](https://www.kosmoy.com/resources/blog/best-ai-governance-platforms-2026/) · [Modulos — AI governance tools buyer's guide](https://www.modulos.ai/best-ai-governance-platforms/) · [MarkTechPost — LLM observability & evaluation platforms 2026](https://www.marktechpost.com/2026/08/09/top-llm-observability-and-evaluation-platforms-in-2026-langfuse-langsmith-braintrust-arize-and-more-compared/) · [Braintrust — AI observability buyer's guide](https://www.braintrust.dev/articles/best-ai-observability-tools-2026)

Gartner: [Magic Quadrant for AI Governance Platforms](https://www.gartner.com/en/documents/8006369) · [IBM — recognised as a Leader](https://www.ibm.com/new/announcements/ibm-recognized-as-a-leader-in-gartner-magic-quadrant-for-ai-governance-platforms)

Acquisitions: [OpenAI to acquire Promptfoo](https://openai.com/index/openai-to-acquire-promptfoo/) · [Promptfoo — joining OpenAI](https://www.promptfoo.dev/blog/promptfoo-joining-openai/) · [CNBC — OpenAI buys Promptfoo](https://www.cnbc.com/2026/03/09/open-ai-cybersecurity-promptfoo-ai-agents.html) · [Check Point acquires Lakera](https://www.checkpoint.com/press-releases/check-point-acquires-lakera-to-deliver-end-to-end-ai-security-for-enterprises/) · [CSO Online — Check Point/Lakera](https://www.csoonline.com/article/4058653/check-point-acquires-lakera-to-build-a-unified-ai-security-stack.html)

Platform risk: [OpenAI Frontier guide](https://www.digitalapplied.com/blog/openai-frontier-enterprise-ai-agent-platform-guide) · [Microsoft Entra Agent ID](https://learn.microsoft.com/en-us/entra/agent-id/what-is-microsoft-entra-agent-id) · [Entra ID Governance for agents](https://learn.microsoft.com/en-us/entra/id-governance/agent-id-governance-overview) · [What's new in Agent 365 — June 2026](https://techcommunity.microsoft.com/blog/agent-365-blog/whats-new-in-agent-365-%E2%80%93-june-2026/4535107)

Procurement: [Konfirmity — SOC 2 customer security questionnaire](https://www.konfirmity.com/blog/soc-2-customer-security-questionnaire) · [Workstreet — security compliance questionnaires](https://www.workstreet.com/blog/security-compliance-questionnaires) · [Copla — vendor security assessment questionnaires](https://copla.com/blog/third-party-risk-management/guide-to-vendor-security-and-risk-assessment-questionnaires/)
