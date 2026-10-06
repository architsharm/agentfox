# AgentFox — Product Requirements Document
## Agent Assurance & Governance for Enterprise AI

| | |
|---|---|
| **Version** | 3.1 — the single canonical PRD |
| **Date** | 2026-08-18, merged 2026-08-29, statuses updated 2026-10-06 |
| **Status** | Approved for build; large parts now shipped — see §12, §13 and [../status.md](../status.md) |
| **History** | This file merges what was previously five separate PRD documents (v1, v2, a "consolidated" draft, this v3 base, and a v4 addendum) into one. Earlier versions are retired, not deleted from history — `git log -- docs/` has them. Keeping one file instead of five was a deliberate cleanup: a reader should never have to figure out which of five PRDs is current. |
| **Positioning** | Horizontal (no vertical beachhead) · SDK-first · vendor-neutral · self-host default |

> **Read this first if you are new.** This document is written to stand alone. It explains what
> enterprises are building, how it fails, what already exists to solve it (open source and
> commercial), what is genuinely missing, and what we are going to build. Sections 1–4 are the
> argument; section 5 is the product; sections 6–11 are the plan; **§12 and §13 are what shipped
> after this document was written**, kept short and pointing at the live-computed sources of truth
> ([../status.md](../status.md), [gap-analysis.md](gap-analysis.md), [failure-modes.md](failure-modes.md))
> rather than re-describing them here, where they would immediately start going stale again.

---

## Table of contents

**Part I — The argument**
1. [Executive summary](#1-executive-summary)
2. [Evidence base](#2-evidence-base)
3. [How enterprises build agent infrastructure, and where it breaks](#3-how-enterprises-build-agent-infrastructure-and-where-it-breaks)
4. [Market landscape and honest positioning](#4-market-landscape-and-honest-positioning)

**Part II — The product**
5. [The five layers and fifteen pillars](#5-the-five-layers-and-fifteen-pillars)
6. [Integration surface](#6-integration-surface)
7. [Architecture](#7-architecture)

**Part III — The plan**
8. [Current build state and gap register](#8-current-build-state-and-gap-register)
9. [Roadmap](#9-roadmap)
10. [Metrics, risks and non-goals](#10-metrics-risks-and-non-goals)
11. [Reference index](#11-reference-index)

**Part IV — What shipped after this document was written**
12. [Addendum (2026-08-26 proposal, delivered by 2026-08-29)](#12-addendum-2026-08-26-proposal-delivered-by-2026-08-29)
13. [Addendum (2026-10-06): monitoring, live probing and hardening](#13-addendum-2026-10-06-monitoring-live-probing-and-hardening)

---
---

# Part I — The argument

## 1. Executive summary

### 1.1 What we are building

**A governance and assurance layer for AI agents that runs inline, enforces policy, and proves what happened — installed as a library, not procured as a platform.**

The unit of adoption is `pip install agentfox` plus a LangGraph decorator. The control plane is what a
team graduates to when they have twenty agents, not what they start with.

### 1.2 The thesis, and the evidence for it

Enterprises deploying agents need to answer five operational questions that neither their
observability stack nor their security stack answers:

| Question | Why it is unanswered today |
|---|---|
| **Should this agent answer this at all?** | Prompt engineering is the current answer, and it degrades — reasoning fine-tuning *worsens* abstention ([AbstentionBench](https://arxiv.org/html/2506.09038v1)) |
| **Where did that answer come from, and was the source authoritative?** | Groundedness scorers check the answer against retrieved text; nothing checks whether that text was authoritative or fresh |
| **What will this action actually do to our systems?** | Argument validation cannot see the structure of generated SQL. An agent wiped 1.9M production rows "flawlessly from a technical standpoint" |
| **Is this person entitled to see this?** | Copilot oversharing is *"a governance failure rather than a security breach — every permission check passed"* |
| **When must a human take over, and did they?** | 31.1% of catalogued agent failures are escalation/resolution breakdowns |

### 1.3 The finding that determines our strategy

We analysed the full CVs of **11 vetted senior/staff/principal AI engineers** (Meta, Apple, Waymo,
Accenture, Deloitte, Philips, Emirates NBD, Itaú, HP, Nvidia, Amazon).

> **6 of 11 independently hand-built a governance/guardrail/validation layer inside their employer.**

Six engineers, six companies, four industries, three continents, building the same component,
because nothing off-the-shelf fit their stack.

**Therefore: we do not primarily compete with vendors. We compete with `git init`.** The buyer's
alternative is two engineer-quarters of internal work. That single fact drives every product
decision below — SDK-first, LangGraph-native, and composing with LangSmith/Langfuse rather than
replacing them.

### 1.4 What is genuinely differentiated — and what is not

Stated plainly, because earlier drafts of this document overstated it.

**Genuinely unclaimed** (no OSS project or commercial product surveyed provides these):

1. **Failure attribution across multi-agent handoffs** — *"a stack trace for agent systems"* (a
   practitioner's phrase, unprompted). Absent from LangSmith, Langfuse and every vendor surveyed.
2. **Answerability enforcement against a declared knowledge boundary** — forcing "I don't have that"
   *before generation*, rather than hoping the model complies.
3. **Action semantics** — deterministic parsing of *generated* SQL/artefacts for blast radius,
   environment binding, and verified-state preconditions.
4. **Argument-provenance taint tracking** — containment that holds after detection fails.

**Contested but defensible** (others do it; we do it differently):

5. Hierarchical policy composition — 2/11 built it by hand; **no vendor packages it**
6. Entitlement-aware retrieval — Knostic and Microsoft Purview address it; we do it inline and cross-stack
7. Computed control status from telemetry rather than attestation

**Overstated in earlier drafts — corrected:**

| Earlier claim | Correction |
|---|---|
| "Silent-failure detection — nobody does this" | **Wrong.** Cleanlab TLM, Vectara HHEM, Galileo, Patronus, RAGAS all do it, and better — ours is lexical, theirs is model-based. A practitioner at Deloitte built it in-house too. **We are behind here, not ahead.** |
| "Tamper-evident audit is a key differentiator" | **Overstated.** A practitioner delivered "regulator-grade auditability" to a bank with no hash chain. Zero of 11 engineers were asked for cryptographic audit. Keep it (cheap, true), stop leading with it. |
| "The governance camp has no runtime enforcement" | **Weakening.** LangSmith shipped an LLM Gateway; ServiceNow, Airia and ModelOp/Kong all have runtime paths; two practitioners built runtime enforcement in-house. The capability is not rare — the *packaging* is. |
| "Nobody addresses escalation breakdown" | **Half right.** Practitioners build HITL escalation routinely. Only **detection of *missed* escalation** is unclaimed. Claim narrowed. |

### 1.5 What we have built, honestly

Offline-capable. The volatile figures (passing tests, lines, weighted coverage of the
tracked capabilities, and coverage of the catalogued failure modes) are generated by probe
into [../status.md](../status.md) rather than restated here, because a count typed into this
document goes stale within a week. Coverage is also measured against an independent
scenario taxonomy built from the architecture of a request rather than from our own
failure catalogue, with scenarios verified by executing against the real product and the
harness failing if any claim disagrees with what happens.

**The claim that now leads, because it is the one that survives a successful attack:**
with **every detector disabled**, 8 of 8 attack scenarios are still contained, and on AgentDojo,
with argument provenance inferred from the real tool outputs, 588 of 588 attack pairs are
contained at session-level taint, at a cost of 24 of 97 benign tasks running without escalation. We separately publish our own adaptive-attack
success rate against our detectors (**73% at 50 attempts**), because a vendor that only
publishes the flattering half of that pair should not be believed. See
[`benchmarks/containment/`](../../benchmarks/containment/README.md),
[`benchmarks/agentdojo_e2e/`](../../benchmarks/agentdojo_e2e/README.md) and
[`benchmarks/adaptive/`](../../benchmarks/adaptive/README.md). Computed by probe, not asserted: see
[../status.md](../status.md) and [coverage-map.md](coverage-map.md), regenerated by
`python scripts/gen/coverage.py --write` and `python scripts/probe/run.py --md`.

**No capability row is absent any more.** The built/partial split is in
[../status.md](../status.md), and every partial row carries a written note saying exactly
what is missing — those notes are the honest part of this document, not the percentages.

Working: runtime detectors across nine surfaces with taint tracking and evasion
resistance; tenant isolation enforced at the session with an import-time assertion that
fails the build if a mapped class escapes it; API-token authentication with the dev
header refused outside development; action assurance over a SQL AST; answerability and
forced abstention; provenance and source authority; entitlement and disclosure control;
context integrity from ingestion through assembly; failure attribution and handoff
fidelity; commitment, AI-disclosure and fairness gates; idempotency, compensation and
cascade analysis; business-rule ladders with a policy compiler that turns a written
document into executable rules; hash-chained per-tenant audit with an independent
verifier, now including operator actions; loop governance over the run rather than the
step; declared fail modes; admission control; 43 controls mapped to 7 frameworks;
continuous monitoring of connected repositories, API specs and MCP servers; opt-in red-team
probing of deployed agents (§13).

**Not working, and worth stating plainly:**

* **Organisational, not engineering.** SOC 2, penetration test, DPA/DR/RTO. These are
  programmes with a calendar, and no amount of code shortens them.
* **Needs infrastructure we do not have.** SSO/SCIM needs a live IdP to develop
  against; KMS/Vault needs a deployment; HA scale-out needs load. Each is a declared
  seam rather than an implementation, and a declared seam is not a feature.
* **Deliberately deferred.** Model-based detectors ship but their weights are an opt-in
  download. The code restructure, new coding-agent harnesses and the last of the
  Nometria→AgentFox rename are deferred too (§13.4).
* **Genuinely hard and openly uncovered.** Sycophancy, invalid logical inference, and
  answer quality in languages other than English. A deterministic checker cannot judge
  informal argument, and an LLM judge inherits the failure it is meant to catch. These
  are marked absent in the coverage map rather than papered over.
* **Known limits of what is built.** Cascade analysis is exactly as good as the trigger
  declarations it is given. Data-access scoping is exactly as good as the ScopeRule
  declarations. The fail-open budget and rate limit are per-process, so a multi-worker
  deployment gets N times the declared budget. `system_scope` lifts tenant isolation;
  its cross-tenant operations write to a dedicated system-level chain, wired by hand
  rather than enforced by a structural check.

See §8.

---

## 2. Evidence base

Four independent sources. Where they disagree, the disagreement is noted rather than resolved in our favour.

### 2.1 Practitioner CVs — 11 senior AI engineers (strongest source)

Not a vendor survey. A record of what senior engineers were **paid to build** in production, in
regulated enterprises, 2023–2026.

**Technology frequency (n=11):**

| Tech | Count | Read |
|---|---|---|
| **LangGraph** | **11/11** | Universal. Not *a* framework — *the* framework. |
| FastAPI | 10/11 | Universal serving layer |
| LangChain | 10/11 | Alongside LangGraph |
| Kubernetes + Docker | 10/11 | Universal deployment |
| **MCP / FastMCP** | **9/11** | Effectively standard for tool exposure |
| **LangSmith** | **7/11** | Dominant observability |
| Azure OpenAI / Foundry | 6/11 | Leading enterprise model access |
| OpenTelemetry | 5/11 | |
| **Langfuse** | **4/11** | Second observability; often *alongside* LangSmith |
| AWS Bedrock · Prometheus/Grafana | 4/11 | |
| RAGAS · Ray · GraphRAG/KG · Vertex/Gemini | 3/11 | |
| **A2A** · LiteLLM · MLflow | 2/11 | Emerging, at Fortune-500 scale |

**Several engineers run LangSmith *and* Langfuse *and* OTel *and* Prometheus simultaneously.** That
is not preference — it is none of them covering the whole need.

**Domain spread:** banking/fintech 3 · healthcare 3 · legal 2 · retail/CPG 2 · consulting 2 · plus
recruiting, sales, devtools, autonomous driving, telecom. **Regulated-heavy.**

### 2.2 Incident and failure data

| Finding | Source |
|---|---|
| **31.1%** of failures are resolution/escalation breakdowns; execution/action failures **+62%**; **<10%** hallucination-related (10,000+ events) | [ChatSee via PR Newswire](https://www.prnewswire.com/news-releases/new-research-finds-enterprise-ai-failures-are-shifting-beyond-hallucinations-as-companies-move-from-chatbots-to-agents-302837907.html) |
| **73%** of leaders say agents fail more from **broken context** than broken models | [Context engineering research](https://memeburn.com/why-ai-agents-fail-in-2026-the-context-problem-no-one-talks-about/) |
| **88%** of orgs had ≥1 AI agent security incident in 2025 | [AI incidents H1 2026](https://www.digitalapplied.com/blog/ai-incidents-h1-2026-retrospective-failure-modes-analysis) |
| ~78% of AI failures are "invisible" — plausible but wrong | Bessemer, citing WildChat |
| 89–94% have observability; **52%** run offline evals, **37%** online, **22.8% none** | LangChain State of Agent Engineering (n=1,340) |
| Guardrail deployment pain is **latency and false positives**; *"without violation specificity, tuning becomes guesswork"*; users route around controls into shadow AI | [Obsidian Security](https://www.obsidiansecurity.com/blog/ai-guardrails), [ML6 benchmark](https://www.ml6.eu/en/blog/inside-ai-guardrails-a-benchmark-on-enterprise-llm-security) |
| *"Weak or outdated evaluation datasets cause more failures than the choice of tool"*; what OSS misses is **the organisational layer** — annotation queues, human feedback, surfaces non-engineers can use | [Maxim AI](https://www.getmaxim.ai/articles/challenges-in-managing-high-quality-datasets-for-llm-evaluation/) |
| Reasoning fine-tuning **degrades** abstention — newer models are *worse* at "I don't know" | [AbstentionBench, 20 datasets / 35k queries](https://arxiv.org/html/2506.09038v1) |

**Named incidents we design against:**

| Incident | Mechanism |
|---|---|
| AI coding agent wiped **1.9M rows** — connected to **production instead of staging** | Environment binding + destructive-statement analysis |
| Finance reconciliation agent **hallucinated a matching record** to "confirm" a match; caught at month-end close | Claim-to-record verification |
| HR agent emailed a welcome to a candidate who **had not accepted** — hallucinated state, acted irreversibly | `requires_verified_state` precondition |
| M365 Copilot oversharing — *"every permission check passed"* | End-user entitlement propagation |
| Sales agent hallucinates objection responses **after step four** | Turn-depth degradation detection |

### 2.3 Market and competitive research

Gartner published the **first Magic Quadrant for AI Governance Platforms on 16 June 2026** — 13
vendors; Leaders IBM, ServiceNow, Truyo. Inclusion required all of: AI discovery/registry, compliance
risk management, policy management and enforcement, **dynamic risk scoring**, evidence collection,
**interoperability**, **workflow and approvals**, complete audit trail.

Gartner's own observation: **most vendors lack runtime enforcement** — a critical gap for regulated buyers.

**Consolidation our original research missed** (all verified):

| Event | Date | Consequence for us |
|---|---|---|
| **promptfoo → OpenAI** | 9 Mar 2026 | Our chosen CI-eval runner became provider-owned. **Dropped from the critical path**; optional adapter only. |
| **OpenAI Frontier** launched | 5 Feb 2026 | Enterprise agent platform with identity, permissions, audit and evals built in. Bigger platform-risk event than AgentKit. |
| **Lakera → Check Point** (~$300M) | Q4 2025 | A "point tool to out-flank" is now inside a security suite. |
| **Galileo → Cisco** | 2025 | Cisco AI Defense = Robust Intelligence + Galileo evals + network enforcement. |
| **Langfuse → ClickHouse** | Jan 2026 | Known; EE tier considerations. |
| **Microsoft Entra Agent ID + Agent 365** | through 2026 | Agent identity, lifecycle, entitlement management, Conditional Access — *this is our Pillar 2*, from the identity incumbent. |

### 2.4 Code audit of our own system

Every capability claim below is grep- or execution-verified. Verified **absent** (zero matches):
streaming, rate limiting, kill switch, multi-tenant filtering, cloud connectors, ITSM, async queue,
KMS/Vault, DB migrations, dynamic risk scoring, framework SDKs, SQL parsing, end-user identity
propagation, answerability, escalation-failure detection.

---

## 3. How enterprises build agent infrastructure, and where it breaks

### 3.1 The stack as it actually exists

Reconstructed from the 11 CVs. This is what a real enterprise agent deployment looks like in 2026.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  L7  GOVERNANCE            ← hand-built in 6/11 companies. THE GAP.       │
│      PII, injection, policy, HITL, audit, validation                     │
├──────────────────────────────────────────────────────────────────────────┤
│  L6  OBSERVABILITY & EVAL  LangSmith 7/11 · Langfuse 4/11 · RAGAS 3/11    │
│                            OTel 5/11 · Prometheus 4/11  ← often 3 at once │
├──────────────────────────────────────────────────────────────────────────┤
│  L5  AGENT RUNTIME         LangGraph 11/11 · Ray 3/11 · A2A 2/11          │
├──────────────────────────────────────────────────────────────────────────┤
│  L4  MODEL ACCESS          Azure OpenAI 6 · Bedrock 4 · Vertex 3          │
│                            LiteLLM routing 2/11 · fallback chains         │
├──────────────────────────────────────────────────────────────────────────┤
│  L3  TOOLS & INTEGRATION   MCP/FastMCP 9/11 · REST · internal SDKs        │
├──────────────────────────────────────────────────────────────────────────┤
│  L2  RETRIEVAL             Pinecone/Qdrant/FAISS/pgvector/Azure AI Search  │
│                            hybrid BM25+dense+rerank 4/11 · GraphRAG 3/11  │
├──────────────────────────────────────────────────────────────────────────┤
│  L1  INGESTION             Docling · PyMuPDF · Azure Document Intelligence │
│                            chunking · embeddings   ← quality unmeasured    │
├──────────────────────────────────────────────────────────────────────────┤
│  L0  DATA & SYSTEMS OF     Snowflake/Databricks · Salesforce · ServiceNow  │
│      RECORD                SharePoint · ERP · operational DBs             │
└──────────────────────────────────────────────────────────────────────────┘
```

**Three structural observations:**

1. **L5 is settled, L2/L1 are fragmented, L7 is hand-rolled.** Orchestration converged on LangGraph.
   Retrieval did not converge at all. Governance has no default at all — so people build it.
2. **L6 is doubled up.** Teams run LangSmith *and* Langfuse *and* OTel simultaneously. Each covers a
   slice; nothing covers the whole.
3. **The failure symptoms surface at L7 but the causes live at L0–L2.** An agent gives a wrong answer
   (L7 symptom) because the chunk was incoherent (L1), the source was unauthoritative (L0), or the
   entitlement model was never propagated (L0↔L2). **Guardrails at L7 cannot fix an L1 defect** — they
   can only detect the symptom. This is why "add a guardrail" keeps disappointing.

### 3.2 The seven failure families

Full taxonomy with 50 modes: [failure-modes.md](failure-modes.md). Summarised, with where the cause
actually lives:

| Family | What goes wrong | Cause layer | Our coverage |
|---|---|---|---|
| **F1 Answerability** | Answers an unknowable question ("Q4 2027 revenue"), answers outside coverage window, over-refuses | L0 metadata absent | ✗ 0/6 |
| **F2 Source authority** | Faithfully grounded in a deprecated wiki page; fabricated citation; silent pick between conflicting sources | L0 catalog absent | ◐ 1/6 partial |
| **F3 Destructive action** | Generated `DELETE` with no `WHERE`; prod vs staging; irreversible act on hallucinated state; duplicate on retry | L3/L5 | ✗ 0/10 |
| **F4 Entitlement** | Oversharing via RAG; agent identity ≠ user entitlement; aggregation disclosure; cross-tenant | L0↔L2 | ✗ 0/8 (1 partial) |
| **F5 Escalation** | **31.1% of all failures.** Didn't hand off; looped instead; escalated with no context; false resolution | L5/L7 | ◐ 1/7 partial |
| **F6 Commitment/liability** | Binding promise; unlicensed advice; missing AI disclosure; adverse action without reason | L7 | ◐ 2/6 |
| **F7 Numeric/entity integrity** | Hallucinated record match; wrong period; currency/unit; entity confusion | L0/L7 | ✗ 0/7 |
| **F8 Context & retrieval integrity** *(new)* | Incoherent chunks; `[UNK]` boundary failures on non-Latin scripts; stale index; context-window truncation dropping evidence; memory contamination | **L1/L2** | ✗ 0/7 |

**We cover 1 of ~57 modes outright.** That number is less damning than it looks — the substrate we
built (taint, policy, audit, control status) is what these controls *run on*. But it is the honest
starting point.

### 3.3 Why the data/metadata layer matters more than it appears

A recurring pattern across F1, F2, F7 and F8: **the agent has no access to enterprise semantics.**
It does not know which of seven tables containing "revenue" is authoritative, that "customer" means
different things in Salesforce and the warehouse, that this dashboard was deprecated in March, or
what the coverage window of the index actually is.

You cannot guardrail your way out of missing metadata. What you *can* do — and what nobody does — is:

- **Consume** existing catalog/lineage metadata (DataHub, OpenMetadata, Unity Catalog, Collibra) and
  use it as **policy input**: source tier, freshness SLA, ownership, classification.
- **Derive** what is missing from observed behaviour (we already derive lineage from spans).
- **Enforce** on it: *"financial figures may only be sourced from tier-1 systems of record under 24h old."*

This is what makes Pillars 7, 8 and 14 tractable rather than aspirational: **the metadata mostly
exists, it is just not wired to the agent.** GraphRAG/knowledge-graph adoption (3/11, always at the
hardest problems) is practitioners reaching for the same thing from the retrieval side.

---

## 4. Market landscape and honest positioning

### 4.1 Five camps

| Camp | Players | Strength | Structural weakness |
|---|---|---|---|
| **Observability & eval** | **LangSmith**, **Langfuse**, Braintrust, Arize/Phoenix, Fiddler, Patronus, Opik | Developer-loved; where the traces already are | **Read-path.** Langfuse states it plainly: *"Langfuse's role is observability and validation, not enforcement"* — it recommends pairing with a separate runtime library |
| **Agent security** | Zenity, Noma, Arthur, WitnessAI, Astrix, Knostic | Real runtime enforcement, discovery, posture | Thin on correctness/eval and compliance depth; several SaaS-only |
| **Security suites** | Palo Alto (Prisma AIRS), Cisco AI Defense, **Check Point (+Lakera)**, SentinelOne (+Prompt Security) | Distribution, SOC integration, existing MSA | Suite lock-in; agent-native depth varies |
| **AI governance platforms** | IBM, ServiceNow, Truyo (Gartner Leaders); Airia, Credo AI, ModelOp, Monitaur, OneTrust; Holistic AI | Compliance depth, framework mapping, workflow, installed base | **Gartner: most lack runtime enforcement** |
| **Model providers** | OpenAI Frontier/AgentKit, Anthropic, Google ADK, Microsoft Agent 365/Entra Agent ID | Free, bundled, distribution | Conflict of interest on neutrality; not a compliance product |

### 4.2 Where each camp genuinely fails

Stated as fairly as possible, because our roadmap depends on these being true.

**LangSmith / Langfuse (the incumbents that matter, 7/11 and 4/11):**
- Observation, not enforcement. Langfuse explicitly recommends separate runtime libraries.
- No policy model, no identity/authorization for agents, no compliance mapping.
- Evaluation is **offline/async** — you find out after the fact.
- LangSmith is coupled to the LangChain ecosystem and engineering-centric; non-technical stakeholders
  cannot operate it. Self-hosting is enterprise-tier.
- **The organisational layer is missing** — annotation queues, human review, surfaces a compliance
  lead can use. This is the stated #1 reason eval programmes stall, not the scorers.
- *LangSmith has shipped an LLM Gateway with request-layer policy* — this is real and narrows the gap.
  We should assume it improves.

**Agent-security tools:** no correctness governance (they secure, they do not judge), separate system
from the traces the team already uses, and several cannot self-host.

**Governance platforms:** no runtime; registration-driven discovery; the CISO can use them and the
engineer cannot.

**Model providers:** neutrality conflict; and a customer with Azure OpenAI + Bedrock + Vertex
(common — 6/4/3 in our sample) cannot govern from any single one.

### 4.3 Our position, stated honestly

We are not creating a category. We are proposing that **five specific controls belong together and
belong inline**, and that the packaging — a library that drops into LangGraph — is what has been
missing.

**Our real competitor is internal engineering.** The comparison that matters:

| | Hand-built (the 6/11 path) | AgentFox |
|---|---|---|
| Time to first enforcement | 4–8 engineer-weeks | an afternoon |
| Hierarchical policy | rarely; Derrick's took real effort | built in |
| Compliance mapping | never | 43 controls × 7 frameworks |
| Failure attribution | never | Pillar 13 |
| Maintained as models/frameworks change | by whoever built it, until they leave | by us |
| Cost | ~$150–300k of senior engineering | licence |

### 4.4 Platform risk

Assume providers absorb the commodity middle. **Microsoft Entra Agent ID will win agent identity** —
they own the directory. Our Pillar 2 should **integrate with it**, not compete. Similarly, assume
LangSmith's gateway improves. Our defensibility must live where a provider structurally will not go:
cross-vendor neutrality, compliance evidence, correctness governance, and controls that span L0–L7.

---
---
# Part II — The product

## 5. The five layers and fifteen pillars

Fifteen pillars grouped into five layers by the question they answer. Each states: **what · why (evidence) · what already exists (OSS + commercial) · our status · requirements**.

Status: ✅ built & tested · ◐ partial · ✗ not built.

| Layer | Question | Pillars |
|---|---|---|
| **A — Know** | What exists and what are the rules? | 1 Registry · 12 Policy Composition |
| **B — Constrain** | What may it do? | 2 Identity · 3 Guardrails · 9 Action Assurance · 10 Entitlement |
| **C — Ground** | Should it answer, and from what? | 7 Answerability · 8 Provenance · 14 Context Integrity |
| **D — Judge** | Did it work, and who broke it? | 4 Evaluation · 13 Failure Attribution · 11 Escalation |
| **E — Prove** | Can we demonstrate it? | 5 Audit · 6 Compliance |
| **Cross-cutting** | | 15 Cost & Reliability |

---

## Layer A — Know

### Pillar 1 · Discovery & Agent Registry ✅◐

**What.** A canonical record of every agent — owner, purpose, risk tier, models, tools, MCP servers — created by registration *or* first observation. Lineage derived from observed execution paths, not declared config.

**Why.** *"What agents do we even have?"* is the first CISO question. **Reference:** Gartner MQ inclusion criterion (AI discovery/registry).

| | Options |
|---|---|
| **OSS** | None meaningful. `mcp-scan` (Snyk-owned — external tool only, never a dependency) |
| **Commercial** | ServiceNow AI Control Tower (~30 discovery integrations), Kosmoy (4 cloud registries), OneTrust Agent Detection, Credo AI Agent Registry, Zenity (Copilot/Power Platform) |
| **Their gap** | Registration- or connector-driven. None derive lineage from *observed* behaviour. |

**Our status.** ✅ registry, shadow detection, ownership, framework auto-detection, observed lineage, MCP hygiene, and continuous monitoring of connected sources (`P1-9`, §13.1). ✗ **no cloud connectors** — we see only what crosses our gateway or OTel, plus the repositories, API specs and MCP servers someone connected.

**Requirements.** P1-1…P1-7 as v1. **New:** `P1-8` connector framework (Bedrock, Azure AI Foundry, Vertex, Salesforce, ServiceNow) — Gartner interoperability criterion and the estate-scale gap. `P1-9` continuous monitoring of connected sources (§13.1).

---

### Pillar 12 · Policy Composition & Lifecycle ✅◐

**What.** Hierarchical policy — `org → team → agent → user` — with inheritance, override semantics, effective-policy resolution showing provenance, and lint.

**Why. Evidence: 2/11 built it by hand.** Derrick (Murphy USA, ex-Apple/Cigna/Ally): *"hierarchical policy framework (company → team → user) with inheritance/override rules, context isolation, and tool permissions... **reducing policy misconfigurations by 87%**."* Jeremy (Accenture, ex-Waymo): *"hierarchical policies, Policy-as-Code."*

An enterprise with 40 agents across 8 teams **cannot** manage flat policy. The 87% figure is the tell: flat policy *causes incidents*.

| | Options |
|---|---|
| **OSS** | OPA/Rego, Cedar, Casbin, OpenFGA — all *engines*; none ship an agent policy hierarchy |
| **Commercial** | **No agent-governance vendor packages hierarchical agent policy** |
| **Their gap** | Everyone gives you a decision engine. Nobody gives you the org model. |

**Our status.** ✅ P12-1…P12-6. The `org → team → agent → user` hierarchy is what the runtime
enforces, not only what `policy effective` prints; lint runs in `policy validate`; `policy
effective` shows each layer's mode; canary cohorts work. Saving a version never changes what
is in force, and promoting to enforce over HTTP needs a recorded simulation. Stored versions
load through one loader, and a bound version that no longer loads is handled under the fail
mode and recorded as `policy.unloadable`. ✗ P12-7 non-developer authoring.

| ID | Requirement |
|---|---|
| P12-1 | Four levels `org → team → agent → user`, inheritance by default |
| P12-2 | Override semantics: `extend` · `restrict` (always allowed) · `override` (needs upstream `overridable: true`) |
| P12-3 | **Effective-policy resolution with provenance** — "this rule came from team `finance`, overriding org default". Opacity *is* the misconfiguration cause |
| P12-4 | **Policy lint** in CI — shadowed/unreachable rules, contradictory effects, over-broad globs, levels granting more than their parent |
| P12-5 | Context isolation — a team cannot read or leak another team's rules |
| P12-6 | **Agent canary rollout** by version with health gates and automated rollback *(Siddhant, Derrick)* |
| P12-7 | **Non-developer rule authoring** for the QMS reviewer / compliance lead who owns the rule *(Leo: "without developer intervention")* |

---

## Layer B — Constrain

### Pillar 2 · Identity, Access & Authorization ✅◐

**What.** Non-human identity per agent with full lifecycle, tool-scoped least privilege with argument-level constraints, delegation narrowing, HITL approvals.

**Why.** Agents act with real credentials. **Reference:** OWASP Agentic T3/T9; EU AI Act Art. 14.

| | Options |
|---|---|
| **OSS** | **OPA** (CNCF graduated), **Cedar** (AWS, formally verified), **OpenFGA** (CNCF incubating), Casbin, SpiceDB, Permify |
| **Commercial** | **Microsoft Entra Agent ID + Agent 365** — identity, lifecycle, entitlement management, Conditional Access, access packages, time-bound access. Astrix, Okta, Ping, Noma |
| **Their gap** | Entra will win *identity*. None do **argument-level constraints plus provenance ceilings** — the agent-native part |

**Our status.** ✅ NHI, rotation with overlap, argument constraints, `max_taint` ceiling, delegation narrowing enforced at write time, approvals with deny-on-timeout. An approved retry is redeemed once, for the same agent, tool and arguments; an agent can read its own approvals and the SDK can wait on one; no approval is granted while the agent is stopped. ◐ RBAC done, **no live IdP**.

**Requirements.** P2-1…P2-7 as v1. **New:** `P2-8` **Entra Agent ID / Okta integration** — consume their identity, layer our capability model on top. *Do not compete with the directory.*

---

### Pillar 3 · Runtime Guardrails ✅◐

**What.** Inline detection across nine surfaces — input, output, tool arguments, tool results, retrieved content, memory writes, agent-to-agent messages, completion claims and the model's reasoning — with a hard latency budget and per-policy fail-open/closed.

**Why.** Table stakes. **The real deployment pain is not detection — it is tuning:** *"latency and false positives are the top pain points"*; *"without violation specificity, tuning becomes guesswork"*; users route around controls into shadow AI.

| | Options |
|---|---|
| **OSS** | **Presidio** (MIT, de-facto PII standard), **NeMo Guardrails**, **Guardrails AI** (Apache core; Hub validators have own licences), **Granite Guardian** (IBM, Apache-2.0 weights — cleanest licence), Llama Guard/ShieldGemma (non-OSI, opt-in), LLM Guard (**archived Jul 2026**), Rebuff/Vigil (stale) |
| **Commercial** | Lakera (Check Point), Prompt Security (SentinelOne), Azure AI Content Safety + Prompt Shields, Bedrock Guardrails, WitnessAI, Zenity |
| **Practitioner** | **Aditya hand-built a "four-layer AI safety guardrail"** — Presidio 12 entities + hallucination detection vs Azure AI Search + Content Filter + Prompt Shields; **OWASP LLM Grade A, 29/29, zero false positives** |
| **Their gap** | Detection is commoditised. **Nobody solves tuning** — violation specificity, cumulative latency budgeting, false-positive management |

**Our status.** ✅ injection (lexical + structural + provenance-weighted + **evasion-resistant**:
normalisation feeds every detector, so separators, homoglyphs, fullwidth, leetspeak, base64,
percent- and entity-encoding and eight non-English languages are all handled — checked by a
committed adversarial regression corpus of our own test strings, which is a regression check
rather than a recall estimate (held-out recall is in
[benchmarks/REPORT.md](../../benchmarks/REPORT.md)); letter-spaced overrides, instructions hidden
in markup and persona jailbreaks are caught; a literal prefilter skips patterns that cannot
match, so a 33 KB benign document scans in about 8.5 ms locally; and the heuristic detector runs
on tool arguments too), PII (native + Presidio), secrets, safety lexicon, schema, budgeted concurrent pipeline with degrade-to-observe, per-detector latency telemetry, taint tracking. ✅ **P3-12/13/14 shipped** — violation specificity on every verdict, a request-level latency ledger, and the false-positive loop with expiring scoped suppressions. ◐ model-based detectors wired but their weights are an opt-in download.

**Requirements.** P3-1…P3-11 as v1. **New, aimed at the tuning gap:**

| ID | Requirement |
|---|---|
| P3-12 | **Violation specificity** — every block names detector, rule, matched span, score, and why that threshold |
| P3-13 | **Cumulative latency budgeting across stacked detectors** with a per-agent budget report |
| P3-14 | **False-positive feedback loop** — one-click "this was wrong", feeding per-detector precision and threshold recommendations |

---

### Pillar 9 · Action Assurance ✅◐

**What.** Deterministic analysis of **generated artefacts** — SQL, scripts, API bodies — before execution: operation class, targets, blast radius, reversibility, environment.

**Why.** Our containment is argument-level on *declared* tools. An agent with a legitimate `db.query` tool can pass `DROP TABLE users` as a well-formed string argument. **An AI coding agent connected to production instead of staging wiped 1.9M rows** — "flawlessly from a technical standpoint".

The literature is prescriptive: **deterministic parsing, not an LLM checking the SQL**, targeting **zero false negatives**, **comments stripped first** — `SELECT * FROM users -- ; DROP TABLE users` defeats keyword matching.

| | Options |
|---|---|
| **OSS** | **sqlglot** (MIT, zero-dependency, 31 dialects, full AST) — the pick; sqlparse (BSD, weaker) |
| **Commercial** | DB proxies with read-replica routing; Kosmoy kernel sandboxing; Cisco DefenseClaw — all *isolate*, none *analyse the statement* |
| **Their gap** | **No agent-governance vendor performs statement-level blast-radius analysis.** Genuinely unclaimed. |

**Our status.** ✅ **shipped.** sqlglot parsing with fail-closed on unparseable, operation
classification, stacked-statement rejection, unbounded-mutation and tautological-predicate
detection, blast-radius and reversibility, environment binding, `requires_verified_state`, dry-run,
plus shell deny-list and HTTP collection-mutation analysis. Exposed to policy as
`action_operation` / `blast_radius_at_least` / `action_reversible` / `action_risk` conditions and
to engineers as `agentfox analyse-action`. ◐ idempotency keys (P9-8) absent.

**Requirements.** P9-1 parse via sqlglot, **fail closed** on unparseable · P9-2 operation classification · P9-3 stacked-statement rejection · P9-4 unbounded-mutation detection (no `WHERE`, tautologies) · P9-5 blast-radius estimation · **P9-6 environment binding** · **P9-7 `requires_verified_state`** (read the record back from the SoR before an irreversible act — closes the HR incident) · P9-8 idempotency keys · P9-9 composed-privilege detection · P9-10 dry-run mode.

---

### Pillar 10 · Entitlement & Disclosure Control ✅◐

**What.** Propagate the **end-user principal** through the agent into retrieval and tools; enforce that responses contain only what that human may see; detect over-permissioned retrieval.

**Why. The highest commercial-value gap.** *"A governance failure rather than a security breach — **every permission check passed**."* The agent runs under its own service identity and inherits the union of everything it can reach. One prompt — *"summarise our M&A discussions last quarter"* — surfaces everything the account can read. **This is why Copilot-class rollouts stall.**

| | Options |
|---|---|
| **OSS** | **OpenFGA** (Apache-2.0, CNCF incubating — `ListObjects` pre-filter, `Check` post-filter) — the pick; SpiceDB, Permify, Cedar |
| **Commercial** | **Knostic** (need-to-know for LLMs — closest direct competitor), **Microsoft Purview + SharePoint Advanced Management** (DAG reports, Restricted Content Discovery), Zenity, Securiti |
| **Their gap** | Microsoft's answer works *inside* Microsoft. Knostic is closest but single-purpose. **Nobody does it inline, cross-stack, across Azure + Bedrock + Vertex + Snowflake + Salesforce.** |

**Our status.** ✅ **shipped, F4 fully covered (0.5/8 → 8/8).** End-user principal propagation,
a retrieval pre-filter with default-deny, withholding recorded as the oversharing metric, the
over-permission diagnostic that works before any entitlement model exists, restricted classes
gated on clearance rather than grant, purpose limitation, per-record residency, k-anonymity on
aggregates and inference-disclosure detection. Control `NOM-IAM-07`. ◐ the OpenFGA adapter is a
declared seam, not an implementation.

**Requirements.** P10-1 end-user principal propagation — **everything else depends on this** · P10-2 retrieval **pre-filtering** via OpenFGA `ListObjects` · P10-3 post-filter fallback recording drops (the drop count *is* the oversharing metric) · **P10-4 over-permission detection** — agent reach vs principal entitlement; *valuable even with no entitlement model, as the diagnostic that motivates the work* · P10-5 cross-tenant hard assertion · P10-6 k-anonymity on aggregates · P10-7 purpose limitation (GDPR Art. 5(1)(b)) · P10-8 restricted classes (MNPI, blackout, legal hold) · P10-9 inference-disclosure detection.

---
## Layer C — Ground

### Pillar 7 · Answerability & Abstention ✅

**What.** A declared **knowledge boundary** per agent; pre-flight classification of whether a question is answerable at all; forced templated abstention **before generation**.

**Why.** *"If someone asks for future sales, the answer should be 'data not available', not a generated one."* Prompt engineering is the current answer and it **degrades**: [AbstentionBench](https://arxiv.org/html/2506.09038v1) (20 datasets, 35k+ unanswerable queries) finds **reasoning fine-tuning frequently worsens abstention** — models get *worse* at this as they get more capable. A property that degrades with model upgrades cannot be left to the model.

The inverse failure is real too: retrieval noise causes **over-refusal**, where the model refuses what it could answer.

| | Options |
|---|---|
| **OSS** | AbstentionBench (benchmark, not a control), Ragas `answer_relevancy` (post-hoc score), NeMo Guardrails topical rails (crude topic gating) |
| **Commercial** | Vectara factual-consistency gating, Cleanlab TLM trustworthiness scores — **both post-hoc**; some RAG platforms have "no answer" fallbacks on retrieval-empty |
| **Their gap** | Everything is **post-hoc scoring of a generated answer**. **Nobody refuses to generate based on a declared coverage boundary.** Genuinely unclaimed. |

**Our status.** ✅ **shipped, F1 fully covered.** Declared boundary, deterministic pre-flight
classification, forced abstention before the model call, post-flight boundary verification,
over-refusal detection as a counter-metric, completeness signalling. Control `NOM-RTG-11`;
`abstain` added to the verdict lattice between `redact` and `escalate`.

**Requirements.** P7-1 knowledge-boundary declaration (systems of record, entity types, temporal coverage, freshness SLA, answerable/unanswerable question types, out-of-scope topics) · P7-2 pre-flight classification (temporal scope · question type · entity scope · topic scope; deterministic first, classifier second) · P7-3 **forced abstention without reaching the model** · P7-4 post-flight boundary verification · P7-5 prediction-vs-record register separation · **P7-6 over-refusal detection** (finding, never a block) · P7-7 completeness signalling ("retrieved 3 of 50").

**Verdict-lattice change:** `allow(0) < tokenize(1) < mask(2) < redact(3) < abstain(4) < escalate(5) < block(6)`. `abstain` returns a helpful templated response — above redaction because it *replaces* the answer, below escalation because it needs no human.

---

### Pillar 8 · Provenance & Source Authority ✅◐

**What.** Source tiers, freshness, ownership per retrievable source; provenance carried on every chunk; per-claim citation binding.

**Why.** **The hole in v1.** Our `groundedness` scorer checks the answer against **retrieved context**. It never asks whether that context was **authoritative**. An answer faithfully grounded in a deprecated 2019 wiki page scores **1.0**. That is a lab metric wearing the costume of a control.

**Source tiers:** 1 `system_of_record` · 2 `approved` · 3 `unverified` · 4 `external`.

| | Options |
|---|---|
| **OSS** | **DataHub**, **OpenMetadata** (catalog + lineage + ownership + freshness — the metadata already exists), OpenLineage, Ragas `faithfulness`/`context_precision`, Vectara HHEM (Apache-2.0 hallucination eval model) |
| **Commercial** | Collibra, Alation, Atlan, Databricks Unity Catalog (governance + lineage); Vectara, Cleanlab TLM, Galileo, Patronus Lynx (groundedness scoring) |
| **Their gap** | Catalogs know source authority but **are not wired to the agent**. Groundedness scorers are wired to the agent but **know nothing about source authority**. **Nobody joins the two.** That join is the product. |

**Our status.** ✅ P8-1…P8-8, F2 fully covered: source tiers, owners and freshness SLAs,
deprecation, fabricated-citation detection, conflict disclosure and domain binding (§8.1).
◐ P8-9 catalog ingestion absent; the groundedness scorer is still lexical by default and
*behind* the model-based scorers above.

**Requirements.** P8-1 source registry (tier, owner, `updated_at`, refresh cadence, data classes) · P8-2 chunk provenance carried through the execution path and into the trace · P8-3 tier policy (*"financial figures: tier-1 only, under 24h"*) · P8-4 staleness enforcement · P8-5 **per-claim citation binding** · P8-6 uncited-assertion detection · P8-7 conflict disclosure · P8-8 domain binding. **New:** `P8-9` **catalog ingestion** — consume DataHub/OpenMetadata/Unity Catalog metadata as policy input rather than asking customers to re-declare it.

---

### Pillar 14 · Context & Retrieval Integrity ✅◐

**What.** Govern the ingestion and retrieval pipeline itself — extraction quality, chunk coherence, tokeniser compatibility, retrieval metrics, index freshness, context-window pressure, memory contamination.

**Why.** **73% of leaders say agents fail more from broken context than broken models.** A whole failure family neither earlier PRD had: *the agent answered badly because the document was chunked badly.* Every downstream control is blind to it — including Pillar 8, which tells you *which* source, not whether the chunk was coherent.

Rahul (BSH, ex-HP/Nokia) instrumented exactly this: *"chunking metrics covering **token distribution, boundary coherence, heading coverage, and semantic density per chunk**, combined with retrieval metrics **nDCG@10, recall@k, MRR** against ground-truth query sets"*; *"eliminating **[UNK] token boundary failures on Cyrillic and Greek scripts**"*; *"**GPT-based corruption detection gating each document** before processing"*.

| | Options |
|---|---|
| **OSS** | Ragas (`context_precision`, `context_recall`), TruLens, BEIR/nDCG tooling, Docling, Unstructured.io, LlamaIndex evaluators |
| **Commercial** | Azure Document Intelligence, Vectara, Galileo (some retrieval metrics), Arize/Phoenix (retrieval tracing) |
| **Their gap** | Retrieval *scoring* exists. **Nobody governs ingestion quality as an enforceable control with a policy attached** — no gate that says "this index is unfit to answer from". |

**Our status.** ✅ ingestion and assembly gates: document quality, chunk coherence,
decoder and tokeniser damage, retrieval metrics against a baseline, evidence seated before
ranking with salience reordering, and memory binding. ◐ index freshness (P14-5, failure mode
F8.3) is not built; nor are semantic chunk-boundary repair, automatic re-extraction of a
corrupt document, or a guard against context stuffing that pushes out the system prompt. See
[coverage-map.md](coverage-map.md) L1.9 and L2.

**Requirements.** P14-1 ingestion quality gate (corruption detection, extraction confidence) · P14-2 chunk quality metrics (token distribution, boundary coherence, heading coverage, semantic density) · P14-3 tokeniser/script compatibility (`[UNK]` boundary failures — a silent multilingual killer) · P14-4 retrieval quality metrics (nDCG@10, recall@k, MRR) tracked over time · P14-5 index freshness and coverage — **feeds P7 knowledge boundary and P8 freshness directly** · P14-6 context-budget governance (window pressure, "lost in the middle", truncation that silently drops evidence) · P14-7 memory-contamination detection.

---

## Layer D — Judge

### Pillar 4 · Evaluation & Reliability ✅◐

**What.** Offline evaluation with CI regression gating, online sampling with drift, a scorer library including silent-failure signals, red-team campaigns.

**Why.** 89–94% have observability; only ~52% run offline evals, 37% online, **22.8% none**. But note the corrected framing: **hallucination is <10% of real failures.** This pillar matters — it is not the biggest lever.

**Where teams actually struggle** (and it is not the scorers): *"weak or outdated evaluation datasets cause more failures than the choice of tool itself"*; *"what open-source tools don't handle is **the organisational layer**: annotation queues, human feedback workflows, regression dashboards, and collaboration surfaces that non-engineering stakeholders can actually use."*

| | Options |
|---|---|
| **OSS** | **Ragas** (3/11 use it), **Garak** (NVIDIA), **PyRIT** (Microsoft), Giskard, DeepEval, Phoenix, Opik, promptfoo (**now OpenAI-owned — off our critical path**), Vectara HHEM |
| **Commercial** | **LangSmith** (7/11 — datasets with splits, experiments, pairwise comparison, annotation queues), **Langfuse** (4/11), Braintrust (CI/CD gating), Galileo (Cisco), Arize, Fiddler, Patronus, **Cleanlab TLM** |
| **Their gap** | Evaluation is **offline/async** — you find out after. And the organisational layer is thin everywhere; LangSmith is the strongest and is engineering-centric. |

**Our status.** ✅ runner, CI gate with direction-aware scorers that fails on errored cases, JUnit/SARIF, drift (PSI/KS), SLOs, static and adaptive red-team campaigns whose probe calls leave nothing in the production tables, silent-failure ensemble, Ragas adapter (`P4-9`), and opt-in live probing of deployed agents (`P4-13`, §13.2). ◐ model-based groundedness (`P4-10`) runs through a configured model provider alongside the lexical scorer rather than replacing it; **the default is still lexical and behind Cleanlab/Vectara/HHEM — a weakness, not a strength.** ✗ annotation queue (`P4-11`).

**Requirements.** P4-1…P4-8 as v1. **New:** `P4-9` **Ragas adapter** (their vocabulary, 3/11) · `P4-10` **model-based groundedness** via Vectara HHEM (Apache-2.0) or Granite Guardian, replacing lexical as the default where weights are available · `P4-11` **annotation queue and human review surface** — the stated #1 reason eval programmes stall · `P4-12` **dataset health** (staleness, coverage, drift of the dataset itself) · `P4-13` **live probing of deployed agents** and `P4-14` **public showcase** (§13.2).

---

### Pillar 13 · Failure Attribution ✅◐ — *"a stack trace for agent systems"*

**What.** Three evaluation tiers — agent-level, handoff-level, end-to-end — with blame assignment backwards along the execution path.

**Why. The strongest unclaimed capability in the entire evidence base.** Pranav (SpotDraft, ex-Apollo.io) built exactly this and named it unprompted: *"a **three-tier agentic evaluation framework** spanning agent-level evals (per-subagent correctness and tool use), **integration evals (inter-agent handoffs)**, and end-to-end evals, with structured execution traces enabling **precise failure attribution (a stack trace for agent systems)**."*

And the mechanism it addresses is documented: *"A wrong decision at step 3 shapes context at step 4, which influences step 5. By step 8, no individual step looks wrong in isolation — but the cumulative path was broken from the start. This is the hardest failure mode to debug in production agentic AI."*

| | Options |
|---|---|
| **OSS** | OpenTelemetry (spans, no attribution), OpenInference/OpenLLMetry semconv, Phoenix (trace viz) |
| **Commercial** | LangSmith, Langfuse, Braintrust, Arize — **all show you the trace; none tell you which step caused the failure** |
| **Their gap** | **Nobody does blame assignment.** Universal absence across OSS and commercial. |

**Our status.** ✅ attribution to the step that originated a value (data flow, not
chronology), handoff fidelity (drops and inventions), goal drift and the delegation graph.
◐ both work on constraints that were written down; an expectation nobody typed is invisible.

**Requirements.** P13-1 three tiers (agent · **handoff fidelity** · end-to-end) · P13-2 handoff checks — what was passed, dropped, paraphrased; semantic drift across a handoff is a first-class defect · **P13-3 blame assignment** — walk backwards to the earliest step already wrong · P13-4 error-propagation detection where no single step trips a threshold · P13-5 turn-depth quality curve (the "collapse after step four") · P13-6 regression attribution to the agent/prompt/tool/model that changed.

---

### Pillar 11 · Escalation Governance ✅

**What.** Declared escalation conditions; detection of **missed** escalation; context-complete hand-off; ownership and SLA.

**Why. 31.1% of all catalogued failures** — the largest single class.

**Narrowed claim** (earlier drafts overstated): practitioners *do* build HITL escalation routinely — Rishabh built *"human-in-the-loop decisions with regulator-grade auditability"*; Derrick built *"HITL workflows and escalation pipelines for ambiguous agent actions"*. **What nobody builds is detection of the counterfactual — it met an escalation condition and did not escalate.** That is our claim, and only that.

| | Options |
|---|---|
| **OSS** | LangGraph `interrupt()` (the mechanism, not the policy), Temporal (durable HITL workflows) |
| **Commercial** | Zendesk/Intercom/ServiceNow handoff (channel-specific), Airia, agent platforms with approval steps |
| **Their gap** | Everyone provides the *mechanism* to escalate. **Nobody detects that you should have and didn't.** |

**Our status.** ✅ **shipped, F5 fully covered.** Declared per-agent conditions, missed-escalation
detection with retroactive hand-off, hand-off completeness scoring, SLA breach findings,
false-resolution detection, loop-without-hand-off, turn-depth degradation, sentiment with distress
and legal-threat flags held separate. Control `NOM-RTG-10`; headline metric `missed_rate` measured
against *qualifying* conversations rather than all traffic, which would flatter it. The scan runs
hourly as the `escalation.scan` job and hands off live only where the policy enforces.

**Requirements.** P11-1 escalation policy (`must_escalate_when`: confidence, repeated failure, sentiment, regulated topic, repeated abstention, turn depth, explicit user request) · **P11-2 missed-escalation detection** — the 31% control · P11-3 turn-depth degradation · P11-4 loop-vs-escalate (a broken loop with no hand-off is still a failure) · P11-5 false-resolution detection · P11-6 hand-off completeness · P11-7 ownership and SLA with breach findings.

---

## Layer E — Prove

### Pillar 5 · Audit, Observability & Traceability ✅

**What.** Full execution-path traces on OTel semantics; hash-chained tamper-evident audit log with signed checkpoints; auditor evidence packages with an independent verifier; SIEM export.

**Why.** EU AI Act Art. 12 (record-keeping); OWASP Agentic T8 (Repudiation & Untraceability).

**Positioning correction.** Earlier drafts led with the hash chain as a differentiator. **Overstated** — Rishabh delivered "regulator-grade auditability" to a bank with no hash chain, and zero of 11 engineers were asked for cryptographic audit. It is cheap, correct and demoable in 60 seconds. It is **not** the reason anyone buys.

| | Options |
|---|---|
| **OSS** | **OpenTelemetry** + OpenLLMetry (the wire format), Langfuse (self-hostable traces), Phoenix |
| **Commercial** | LangSmith, Datadog LLM Observability, Arize, Splunk/QRadar for SIEM |
| **Their gap** | Traces are commoditised. The **evidentiary layer** — verifiable export an auditor can check without the vendor — is rare, but rarely demanded. |

**Our status.** ✅ all of it, tested against four tamper modes with a standalone stdlib verifier. Evidence packages can be scoped to one agent; OTLP ingest accepts JSON and protobuf, gzipped or not.

**Requirements.** P5-1…P5-7 as v1. **New:** `P5-8` **bidirectional LangSmith/Langfuse integration** — ingest their runs, correlate our decisions to their trace ids, push verdicts and scores back as feedback. **We do not replace their traces.**

---

### Pillar 6 · Policy & Compliance Management ✅◐

**What.** Control catalog mapped to frameworks; control status **computed from telemetry**; risk register with EU AI Act classification; obligation calendar; board view.

**Why.** Gartner MQ inclusion criteria. **Reference:** EU AI Act phased timeline (Art. 50 transparency live Aug 2026; GPAI Dec 2026; Annex III high-risk Dec 2027).

| | Options |
|---|---|
| **OSS** | **Essentially none.** OSCAL (NIST control format) is the closest primitive |
| **Commercial** | Credo AI (Policy Packs incl. NYC LL144), IBM watsonx.governance, OneTrust, ModelOp, Holistic AI, Monitaur, ServiceNow |
| **Their gap** | They **collect attestations**. We **compute status from telemetry** — a claim only an inline platform can make. That is real and defensible. |

**Our status.** ✅ 43 controls × 7 frameworks, computed status with 9 rule kinds, risk classification, obligations, board view, declared gaps per framework, and an EU AI Act Art. 50 check for an agent claiming to be human. **⚠ all 317 mappings are DRAFT** — they ship in evidence packages chip-labelled `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` until a qualified reviewer signs them (Appendix B §B.6).

**Requirements.** P6-1…P6-8 as v1. **New:** `P6-9` **dynamic risk scoring** (Gartner criterion, currently ✗ — static classification only) · `P6-10` **assessment/workflow engine** (Gartner criterion) · `P6-11` complete the mapping review gate with a qualified assessor.

---

## Cross-cutting

### Pillar 15 · Cost, Reliability & Degradation ✅◐

**What.** Circuit breakers, fallback chains, degradation ladders, hard token/spend caps, backpressure, cost attribution.

**Why. 5/11 built this by hand**, and it sits at *the same inline interception point as enforcement* — building it separately is duplicated plumbing. Aditya: *"circuit breaker for LLM provider outages, **Redis-backpressure request queuing**, provider fallback, **TPM/RPM-aware rate limiting with hard daily caps on token spend**"*. Derrick: *"graceful degradation to **smaller LLMs**, sustaining 2x traffic spikes"*. Savings claimed across the set: 60% infra, ~50%, $84K/yr, 75%, 70–80% token, 30%, 18%.

| | Options |
|---|---|
| **OSS** | **LiteLLM** (routing, fallback, budgets — 2/11), Helicone (Apache-2.0, cost tracking + rate limiting), Portkey gateway |
| **Commercial** | Portkey, Kong AI Gateway, Cloudflare AI Gateway, TrueFoundry |
| **Their gap** | Gateways do routing and cost. **None tie spend to governance** — no "this agent's budget is exhausted, and here is the audit entry for the block". |

**Our status.** ✅ a circuit breaker per provider (P15-1), a fallback ladder that records every
degradation and is empty by default (P15-2), windowed call, token and cost caps checked
pre-flight as governed events (P15-3), a priority-aware admission controller that sheds work
rather than governance (P15-4), and LiteLLM routing (P15-6, shipped as `I-10`). A
fail-open/fail-closed policy per control (`availability.py::service_fallback`) blocks once a
control has been failing open past its budget, and a policy pack's own `fail_mode` is honoured.
◐ no chargeback report by team (P15-5), and the fail-open budget and admission state are
per-process.

**Requirements.** P15-1 circuit breaker per provider/model · P15-2 fallback chain and degradation ladder · P15-3 TPM/RPM limits with hard daily caps · P15-4 backpressure queueing · P15-5 cost attribution per agent/team/user/session/tool · P15-6 **LiteLLM adapter** where teams already run it.

---
## 6. Integration surface

Frequency-ordered from the 11 CVs. **This is measured, not assumed.**

| ID | Integration | Freq | Requirement | Status |
|---|---|---|---|---|
| **I-1** | **LangGraph** | **11/11** | Node/edge hooks, checkpointer-aware state, `interrupt()` for HITL, per-node policy binding | ✅ |
| **I-2** | **MCP / FastMCP** | **9/11** | Inline governance of the `tools/call` path, not only hygiene scanning | ✅ rug pull, undeclared tool, poisoned result |
| **I-3** | **FastAPI** | 10/11 | Middleware + dependency for in-process enforcement | ✅ observe-only middleware, opt-in enforcing dependency |
| **I-4** | **LangSmith** | **7/11** | Bidirectional correlation of decisions to their trace ids | ✅ in-band join key, reverse lookup |
| **I-5** | **OpenTelemetry** | 5/11 | OTLP ingest + export | ✅ |
| **I-6** | **Langfuse** | 4/11 | Ingest traces; push decisions back | ✅ |
| **I-7** | **Prometheus / Grafana** | 4/11 | Metric export into dashboards they already run | ✅ stdlib exposition at `/metrics` |
| **I-8** | **Ragas** | 3/11 | Scorer adapter — their vocabulary | ✅ native offline, delegates when installed |
| **I-9** | **Ray** | 3/11 | Enforcement across Ray actors | ✗ |
| **I-10** | **LiteLLM** | 2/11 | Govern *through* their routing layer rather than compete | ✅ |
| **I-11** | Azure OpenAI · Bedrock · Vertex | 6/4/3 | Provider adapters beyond OpenAI/Anthropic | ✅ Azure inherits the OpenAI wire format; Bedrock and Vertex refuse rather than improvise auth |
| **I-12** | Qdrant · Pinecone · pgvector · Azure AI Search · Elasticsearch · FAISS | fragmented | Retrieval-scope filter adapters (P10-2). **No winner exists — build the seam, not a favourite** | ✗ |
| **I-13** | **Presidio · OPA** | 2/11 · 1/11 | Both **independently chosen** by these engineers — validating our picks | ✅ |
| **I-14** | **DataHub / OpenMetadata / Unity Catalog** | — | Catalog ingestion for source tier, freshness, ownership (P8-9) | ◐ tiers and freshness modelled; ingestion absent |
| **I-15** | **Entra Agent ID / Okta** | — | Consume agent identity rather than compete (P2-8) | ✗ |
| **I-16** | **A2A** | 2/11 | Watch. Emerging at Fortune-500 scale; design P13 handoff checks to extend to it | ✗ |

> **Ten of sixteen integrations ship, covering every surface above 3/11 frequency.** The four
> remaining gaps are deliberate: `I-12` waits on P10 (there is no winner to build against, so we
> build the seam when the entitlement engine needs it), `I-14` waits on a customer who runs a
> catalog, `I-15` is a Tranche 4 procurement item, and `I-9` Ray has no enforcement story that is
> not just the SDK.

---

## 7. Architecture

### 7.1 Three integration surfaces, all additive

1. **SDK (primary)** — `pip install agentfox`, LangGraph-native decorators and node hooks. **This is the adoption path.**
2. **Gateway** — OpenAI/Anthropic-compatible inline proxy for teams that cannot change code, or non-Python stacks.
3. **OTel ingestion** — passive observation; gives Pillars 1 and 5 with zero integration.

### 7.2 The swappable seam

Every wrapped OSS primitive sits behind one interface. This is what makes the OSS register's
"exposure" column honest — swapping an archived or acquired project touches one adapter file.

| Interface | Contract | Implementations |
|---|---|---|
| `Detector` | `detect(content, context) -> Findings` | native heuristics, Presidio, Granite Guardian, NeMo, Guardrails AI |
| `PolicyEngine` | `decide(input) -> Decision` | native, OPA/Rego (Cedar seam) |
| `EvalRunner` | `run(suite, target) -> Results` | native, Ragas *(promptfoo demoted — OpenAI-owned)* |
| `RedTeamRunner` | `probe(target, campaign) -> Findings` | native, Garak, PyRIT, Giskard |
| `ModelProvider` | `complete(request) -> Response` | echo (offline), OpenAI, Anthropic, + Azure/Bedrock/Vertex |
| **`ActionAnalyser`** *(new)* | `analyse(artefact) -> BlastRadius` | sqlglot |
| **`EntitlementEngine`** *(new)* | `visible(principal, resources) -> Set` | OpenFGA, native ACL |
| **`CatalogSource`** *(new)* | `describe(source) -> Tier/Freshness/Owner` | DataHub, OpenMetadata, Unity Catalog |

### 7.3 Request path

```
identity + END-USER PRINCIPAL (P2, P10-1)
  → knowledge-boundary check (P7) ──── abstain? → templated response, no model call
  → entitlement pre-filter on retrieval (P10-2)
  → taint annotation (P3-4)
  → budgeted detector pipeline (P3)
  → hierarchical policy resolution (P12) → decision (P6-1)
  → escalate → human (P2-3, P11)
  → provider call (X-2) with circuit breaker + fallback (P15)
  → post-flight: PII/DLP, schema, provenance binding (P8), silent-failure sampling (P4)
  → trace + audit chain + SIEM + control signals (P5, P6)
  → attribution graph updated (P13)
```

### 7.4 OSS decisions

**On the critical path** (all permissive, active, none provider-owned): Presidio · OPA · OpenTelemetry · Granite Guardian · Garak · PyRIT · Giskard · **sqlglot** (new) · **OpenFGA** (new) · Cedar/Casbin (seams).

**Deliberately off it:** promptfoo (**OpenAI-owned since 9 Mar 2026**) · LLM Guard (archived) · Invariant/mcp-scan (Snyk-owned; external tool only) · systemprompt-core (BSL) · Llama Guard/ShieldGemma (non-OSI, opt-in with explicit acknowledgement) · Langfuse *as storage* (export target only).

Full register with licence, health, verdict and exposure: [Appendix A](oss-register.md).

---
---

# Part III — The plan

## 8. Current build state and gap register

### 8.1 What is built and tested

> **Live figures live in [../status.md](../status.md)**, which is regenerated by
> `python scripts/gen/coverage.py --write` from probes against the actual source tree. A
> hand-written table drifts within a week and then quietly lies, so this section carries
> only the narrative; the numbers below are a snapshot of that file, not a second source
> of truth.

The counts that used to sit here (coverage, failure modes, tests, lines) are in
[../status.md](../status.md). What does not drift: ruff clean, offline-capable (no API key, no
weights, no egress), and the adversarial injection corpus is a regression check on our own
test strings, not a recall measurement.

Built and tested end to end:

- **Layer B/E core** — runtime detectors across 9 surfaces · taint tracking with argument
  provenance · tool-scoped least privilege with argument constraints · delegation narrowing
  at write time · hash-chained audit (4 tamper modes tested, standalone stdlib verifier) ·
  evidence packages · SIEM export.
- **Judge** — evaluation with direction-aware CI gating · silent-failure ensemble · red-team
  harness.
- **Know/Prove** — registry with shadow-agent detection and observed lineage · 43 controls ×
  7 frameworks with computed status · Next.js control plane.
- **Tranche 0 (complete)** — `PL-1` streaming with inline enforcement in both OpenAI and
  Anthropic wire formats · `PL-2` Alembic migrations · `PL-3` kill switch and quarantine ·
  `I-1` LangGraph-native SDK with trace id carried in graph state.
- **Tranche 1** — `P12` hierarchical policy composition (`org → team → agent →
  user`) with `extend`/`restrict`/`override` semantics and a six-code linter · `P15` circuit
  breaker, fallback ladder with recorded degradation, and hard budget caps enforced
  **pre-flight** as governed events (audit entry + deduplicated finding), not as an HTTP 429
  that disappears into a load-balancer log · `I-4`/`I-6` **bidirectional** LangSmith and
  Langfuse correlation — the join key travels in-band on a `traceparent` or vendor header, so
  correlation needs zero configuration and zero installed packages, and `GET
  /api/traces/resolve` answers the direction nobody ships: *their* run id → *our* decision ·
  `P3-12…P3-14` the **tuning surface**: every verdict carries the detector, rule, matched span,
  score and remedy; a request-level latency ledger so stacked detectors cannot quietly overrun
  the SLO; and a false-positive loop producing per-detector precision, threshold recommendations
  — including the honest *"these scores do not separate, no threshold fixes this"* — and scoped,
  **expiring** suppressions whose every hit is recorded on the decision · `I-2` **MCP inline
  governance**: hygiene scanning caught only the server that was already malicious at scan time,
  so the call path is now governed for the three failures that happen at call time — the rug
  pull (schema or description changed after authorisation → blocked), the undeclared tool
  (registered and raised as a finding rather than passing invisibly), and the poisoned result
  (evaluated on `tool_result` and taint-propagated, so a derived argument cannot exceed the
  ceiling for third-party provenance).

**Tranche 1 is complete.**

- **Tranche 2 (in progress)** — `P9` **action assurance**, the first of the three genuinely
  unclaimed capabilities. Everything else here governs the *call*; this governs the *artefact*.
  Deterministic sqlglot parsing (never a model on a deterministic question), **fail closed on
  unparseable**, stacked-statement rejection, unbounded-mutation and tautological-predicate
  detection (`WHERE 1=1` is the shape that gets past "does it have a WHERE clause?"), blast-radius
  and reversibility classification, environment binding, `requires_verified_state` for irreversible
  acts, and dry-run mode. A `db.query` capability no longer authorises `DROP TABLE users`.
- **`P11` escalation governance — F5 closed, 0/7 → 7/7.** The largest single failure family at
  **31.1%**. Everyone ships the *mechanism* to escalate; the claim here is the counterfactual —
  **it met a condition and did not escalate**. That failure is invisible from inside the system:
  a conversation where the agent kept going instead of handing off looks entirely ordinary in the
  telemetry, and the user simply leaves. So detection is a deliberate second pass over completed
  conversations replaying the declared policy, not a runtime check. Also: hand-off context
  completeness (an escalation the human cannot act on is still a failure), SLA breach on dropped
  hand-offs, false-resolution detection, loop-without-hand-off, turn-depth degradation, and
  distress/legal flags kept out of the sentiment average so the one message that mattered is not
  averaged away. Missed escalations raise a **retroactive hand-off**, because recording that a
  person was left waiting and then leaving them waiting is an audit artefact, not a control.
- **`P7` answerability — F1 closed, 0/6 → 6/6.** The distinction that makes this a different
  control: Cleanlab, Vectara, RAGAS, Galileo and Patronus all score an answer *after* it exists,
  which cannot address F1 — by then the number has been invented, and a confident wrong number
  scored at 0.4 is still a confident wrong number in front of a user. A declared knowledge
  boundary (systems of record, coverage window, entity scope, answerable question types) drives
  four deterministic pre-flight checks, and an unanswerable question is answered from a template
  **without a model call**. The refusal names what is missing — *"I hold 24 months and you asked
  about 2019"* — because "I don't know" sends the user away while naming the boundary sends them
  to the right system. Post-flight: boundary verification (F1.4, a record-only agent that drifts
  into forecast) and completeness signalling (F1.6, retrieved 3 of 50 and answered as though
  exhaustive). **Over-refusal (F1.5) is a finding against us and never a block**, because an
  over-refusing agent is uninstalled faster than a hallucinating one; the whole pillar ships
  observe-first with a `POST /check` dry run so a team can replay real traffic before enforcing.
- **`P8` provenance — F2 closed, 1/6 → 6/6.** The gap our own groundedness scorer is blind to by
  construction: it checks the answer against the retrieved context and never asks whether that
  context was authoritative, so an answer faithfully grounded in a deprecated 2019 wiki page
  scores 1.0. Perfect groundedness against the wrong source is *more* dangerous than an ungrounded
  answer, because every quality metric says it is fine. Sources now carry a tier, owner, freshness
  SLA and domain; fabricated citations are split into the blatant case (a document never
  retrieved) and the case that survives review (a real document cited for a figure it does not
  contain); silent source conflicts and uncited material claims are surfaced.
- **F7 numeric, temporal and entity integrity — 1/7 → 7/7.** The failures that survive every other
  control: the answer is grounded, the source authoritative, the action safe, nobody needed to
  escalate — and the number is for the wrong quarter, in the wrong currency, or belongs to a
  different customer with a similar name. All six checks are deterministic, which is the point:
  a probabilistic judge is the wrong instrument for whether 5 + 3 = 9. Fiscal-versus-calendar is
  the expensive one — both parties say "2024", mean ranges that overlap by nine months, and the
  answer looks right to everyone in the room.
- **Integration surfaces — `I-3`, `I-7`, `I-8`, `I-10`, `I-11`.** FastAPI is 10/11 and the
  lowest-cost surface there is: observe-only middleware safe to mount globally, plus an *opt-in*
  enforcing dependency, because a middleware that can 403 a route its author never considered is
  how a governance layer gets removed on the first false positive. Azure OpenAI (6/11) inherits
  the OpenAI wire format rather than copy-pasting it; Bedrock (4/11) and Vertex (3/11) report
  unavailable without their SDKs rather than improvising request signing. Prometheus (4/11) is a
  stdlib-only exposition of numbers computed elsewhere — counts and rates, never content, on an
  unauthenticated `/metrics` like every other one. Ragas (3/11) is a vocabulary adapter that runs
  natively offline and delegates to Ragas where it is installed, naming its implementation on
  every result. LiteLLM (2/11) is governed *through*, not competed with.
- **Adoption surface — `X-1`, `X-2`, `X-3`.** The binding constraint was never capability;
  it was that every integration asked the developer to change how they call the model, and the
  sum of small asks is why governance tooling sits in a proof-of-concept for six months.
  `agentfox.auto()` patches the client libraries in place so an existing codebase is governed by
  one line, in observe mode, with no other file touched. `agentfox check` answers the question
  a platform team has to answer first and nobody has written down — *where does this codebase
  actually talk to a model?* — statically, ranked, ending in one sentence saying what to do next.
  And the control plane now leads with what needs a human rather than an inventory, and
  distinguishes **not connected** from **nothing wrong**, which look identical and mean opposite
  things. `X-4` closes what the audit named as the actual business blocker: **P8 had no HTTP
  surface at all**, P7 and P11 were REST-only, and escalation needed the host application to push
  conversation turns that nothing was pushing — so the largest failure family was covered in code
  and uncovered in practice. Every protective control now has a CLI verb, a dry run and a page,
  and `auto()` captures conversation turns itself.

The honest reading of these numbers is that **the spine is real and the breadth is closing**.
All three genuinely unclaimed capabilities are shipped (`P9`, `P7`, and `P13` with the limit its
status row names). Family-by-family coverage is computed in [../status.md](../status.md); what
shipped after this section was written is in §12 and §13.

### 8.2 Gap register — ranked

**Tier 0 — production blockers** (cannot deploy inline)

| # | Gap | Evidence |
|---|---|---|
| 0.1 | **Streaming silently ignored** — `stream: true` returns non-streaming JSON | verified by execution |
| 0.2 | **No DB migrations** — a deployed instance cannot be upgraded | verified absent |
| 0.3 | **No kill switch / quarantine** | verified absent; every competitor has one |
| 0.4 | ~~No LangGraph integration~~ — **closed.** `I-1` shipped (§6): node/edge hooks, checkpointer-aware state, `interrupt()` for HITL, per-node policy binding — this line contradicted §6's own I-1 status even at the time this document was first written, and stayed uncorrected until the 2026-08-29 merge caught it. See `integrations/langgraph.py`, 34 passing tests in `tests/runtime/test_streaming_kill_switch_and_langgraph.py`. | 34 tests |
| 0.5 | ~~Agent tool-calling loop not governed~~ — **closed.** `PL-4` governs the run rather than the step: identical re-issued calls, alternating cycles, and steps producing no new observation | 18 tests |
| 0.6 | ~~Everything synchronous~~ — **closed as an interface.** `PL-5` `JobQueue` with retries and a public dead letter; a Redis/SQS implementation belongs behind it | 6 tests |
| 0.7 | ~~No HA validation~~ — **partly closed.** SQLite is now refused at startup for a multi-worker deployment rather than surfacing as intermittent latency; Postgres pools and pre-pings. Scale-out under real load is still untested | NFR-3 partly met |

**Tier 1 — procurement blockers** (cannot pass security review)

SSO/SCIM ✗ (API tokens ✅, OIDC seam only) · multi-tenancy ✅ **enforced at the session** ·
authentication ✅ **API tokens, dev header refused outside development** ·
rate limiting ✅ **admission control that sheds work, never governance** · KMS/Vault ✗ ·
SOC 2 Type II ✗ · pen test ✗ · DPA/DR/RTO ✗ · dashboard writable and authenticated ✅ ·
operator audit log ✅ **in the same hash-chained log as the decisions, with a structural
check that a new privileged surface cannot ship unaudited** · startup refusal on published
secrets ✅ (§13.3).
What remains unmet is almost entirely organisational rather than engineering: SOC 2, pen
test and DPA/DR/RTO are programmes, not features, and SSO/SCIM needs a live IdP to develop
against, as KMS/Vault needs a deployment that has one.

**Tier 2 — Gartner MQ inclusion criteria**

dynamic risk scoring ✗ · interoperability/connectors ✗ · workflow & approvals ◐ (runtime only).
Evidence collection ✅ and audit trail ✅ are strong.

**Tier 3 — capability gaps** — Pillar 12's non-developer authoring (P12-7) remains; its canary
and Pillar 15's LiteLLM adapter have shipped. Pillars 7, 9, 10, 13 and 14 are built and probed.

**Tier 4 — found in review, absent from this register when it was written**

The gap register above was assembled from practitioner CVs, incident data and a code
audit. It still missed an entire axis, which review surfaced: the product governed the
*call* and the *output* and never the semantic contract between them. Pillar 18 covers
it — proving a tool's query touched only the caller's rows, checking the result is
about the record that was requested, gating the specificity an answer is entitled to,
and arbitrating between datasources with a confirmation step instead of a silent pick.
Recording the miss matters more than the fix: three independent evidence sources agreed
with each other and were jointly blind to it.

---

## 9. Roadmap

Ordered by **whether anyone can adopt it**, which the CV evidence says is the binding constraint —
not by severity, which was the earlier (wrong) ordering.

### Tranche 0 — be installable at all
`PL-1` streaming · `PL-2` Alembic migrations · `PL-3` kill switch · **`I-1` LangGraph-native SDK**

> I-1 sits in Tranche 0 because 11/11 use LangGraph. A governance product that is not a LangGraph
> primitive is a proxy teams route around. This is the difference between "a tool we evaluated" and
> "a tool we installed".

### Tranche 1 — replace the hand-rolled wrapper *(the 6-of-11 opportunity)* — **complete**
`P12-1…P12-4` hierarchical policy + lint ✅ · `I-4`/`I-6` LangSmith + Langfuse correlation ✅ ·
`I-2` MCP inline governance ✅ · `P15-1…P15-4` circuit breaker, fallback, caps and admission
control ✅ · `P3-12…P3-14` violation specificity, cumulative
latency, false-positive loop ✅

> This is precisely what Aditya, Derrick, Leo, Jeremy, Siddhant and Rishabh built by hand. Shipping it
> means a platform team **deletes code instead of writing it**. That is the wedge.

### Tranche 2 — the controls nobody has
`P9` action assurance ✅ · `P13` failure attribution ✅◐ · `P7` answerability ✅

> All three are genuinely unclaimed across OSS and commercial. P9 is the most demoable
> (`DROP TABLE` blocked live); P13 is the most valuable to a platform team; P7 is the most novel.

### Tranche 3 — depth
`P10` entitlement ✅ · `P14` context integrity ✅ · `P8` provenance ✅ (catalog ingestion still
absent) · `P11` escalation ✅ (pulled forward — largest family) · `P4-9` Ragas adapter ✅ ·
`P4-10` model-based groundedness ◐ · `P4-11` annotation queue ✗ · `P12-6` canary ✅ · `P12-7`
non-developer authoring ✗ · `PL-4…PL-7` loop governance ✅, async ◐, HA ◐, service fail-open ✅ ·
`P1-9` monitoring ✅ · `P4-13/14` live probing and showcase ✅ (added 2026-10-06)

### Tranche 4 — enterprise readiness
Tier 1 procurement (SSO, multi-tenancy, KMS, rate limiting) · Tier 2 Gartner criteria (dynamic risk
scoring, connectors, workflow engine) · SOC 2 programme (start the clock early — it is the longest
pole and it is organisational, not engineering)

### Explicitly not doing
Sandboxing · business-platform coverage (Copilot Studio, Power Platform) · network-level discovery ·
becoming the retrieval layer · building a model, vector DB, or agent framework.

> XL effort, defended by well-funded incumbents, and **absent from the practitioner evidence entirely**
> — not one of 11 engineers mentioned needing them.

---

## 10. Metrics, risks and non-goals

### 10.1 Metrics that matter

| Pillar | Primary metric | Target |
|---|---|---|
| 7 | Unanswerable-question fabrication rate | **0** |
| 7 | **False-abstention rate** *(the counter-metric)* | < 2% |
| 8 | Unauthoritative-answer rate | < 1% of material claims |
| 9 | Destructive-action **false-negative rate** | **0** — non-negotiable |
| 10 | Entitlement-violating disclosure | **0**; over-permission ratio trending down |
| 11 | Missed-escalation rate | < 5% of qualifying conversations |
| 12 | Policy misconfigurations caught by lint | benchmark vs Derrick's 87% |
| 13 | Attribution accuracy on labelled multi-agent failures | > 80% |
| 3 | **False-block rate** *(the adoption killer)* | < 0.5% |
| Platform | Added p95 latency (buffered streaming) | < 150 ms |

**The two counter-metrics are the important ones.** False abstention and false blocks are how this
product gets uninstalled. Both are tracked, both raise findings, and every enforcing pillar ships
**observe-first**.

### 10.2 Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Pillars 7 and 9 make agents useless** — over-abstention and false blocks | Observe-first; counter-metrics with findings; P7-6 over-refusal detection; P9 dry-run |
| R2 | **LangSmith closes the gap** — their gateway already ships request-layer policy | Assume it improves. Defend on cross-vendor neutrality, compliance evidence, and P9/P13 which are not on their roadmap |
| R3 | **Entra Agent ID owns identity** | Integrate (P2-8), do not compete with the directory |
| R4 | **We are behind on groundedness** — ours is lexical, Cleanlab/Vectara/HHEM are model-based | P4-10 adopt HHEM/Granite; stop claiming leadership here |
| R5 | **P10 requires an entitlement model the customer may not have** | Post-filtering works with whatever ACLs exist; P10-4 has standalone diagnostic value |
| R6 | **OSS dependency changes status** — 4 did in 12 months | Adapter seam; quarterly re-verification; nothing archived/BSL/provider-owned on a default path |
| R7 | **Scope** — 15 pillars is a lot | Tranches are hard gates; no new interfaces permitted inside a tranche |
| R8 | **Compliance mappings are DRAFT** | Evidence packages carry them with a `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` chip; needs a qualified assessor |
| R9 | **We build a platform when the market wants a library** | Tranche 0 forces SDK-first; the control plane is the graduation, not the entry |

### 10.3 Non-goals

We do not build: a model · a vector database · an agent framework · a sandbox runtime · a retrieval
layer · an identity directory. We do not replace LangSmith or Langfuse traces. We do not claim
coverage we lack — every framework mapping ships with a declared gap list.

---

## 11. Reference index

**Internal:** [Gap analysis](gap-analysis.md) · [Failure modes](failure-modes.md) ·
[Benchmarking white paper](../evaluation/benchmarking-whitepaper.md) ·
[Appendix A — OSS register](oss-register.md) ·
[Appendix B — Control catalog](control-catalog.md) ·
[Appendix C — API spec](../architecture/api-spec.md) · [Appendix D — Data model](../architecture/data-model.md) ·
[Appendix E — Threat model](../architecture/threat-model.md) · [Traceability](traceability.md)

**Failure & incident data:** [Enterprise AI failures shifting beyond hallucinations (10k+ events)](https://www.prnewswire.com/news-releases/new-research-finds-enterprise-ai-failures-are-shifting-beyond-hallucinations-as-companies-move-from-chatbots-to-agents-302837907.html) · [AI incidents H1 2026](https://www.digitalapplied.com/blog/ai-incidents-h1-2026-retrospective-failure-modes-analysis) · [Why AI agents fail — the context problem](https://memeburn.com/why-ai-agents-fail-in-2026-the-context-problem-no-one-talks-about/) · [Enterprise agent failure modes](https://thoughtminds.ai/blog/enterprise-ai-agent-failure-modes)

**Abstention:** [AbstentionBench](https://arxiv.org/html/2506.09038v1) · [Know Your Limits — abstention survey (TACL)](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00754/131566/Know-Your-Limits-A-Survey-of-Abstention-in-Large) · [The downside of RAG — over-refusal](https://www.bohrium.com/en/blog/research-notes/aaai-2026-retrieval-augmented-models-dont-know/)

**Entitlement / oversharing:** [M365 Copilot oversharing — what IAM teams must fix](https://nhimg.org/community/cybersecurity-beyond-identity/microsoft-365-copilot-oversharing-what-iam-and-data-teams-must-fix/) · [Copilot didn't overshare your data, your permissions did](https://petri.com/copilot-didnt-overshare-your-data-your-permissions-did/) · [Microsoft — mitigate oversharing](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/mitigate-oversharing-to-govern-microsoft-365-copilot-and-agents/4448744)

**Action safety:** [Protecting production SQL from agentic query risks](https://rietta.com/blog/ai-sql-database-data-protection-read-replica/) · [Production text-to-SQL: 9 problems with fixes](https://atalupadhyay.wordpress.com/2026/07/01/building-a-production-ready-text-to-sql-ai-agent-9-problems-with-fixes/) · [AI agent database wipe — lessons](https://www.mindstudio.ai/blog/ai-agent-database-wipe-disaster-lessons/) · [Testing SQL agents](https://langwatch.ai/scenario/testing-guides/sql-agent/)

**Guardrail tuning:** [Obsidian — enforcing safety without slowing innovation](https://www.obsidiansecurity.com/blog/ai-guardrails) · [ML6 — enterprise LLM security benchmark](https://www.ml6.eu/en/blog/inside-ai-guardrails-a-benchmark-on-enterprise-llm-security) · [Airia — what guardrails can and cannot do](https://airia.com/blog/what-guardrails-can-and-cannot-do-setting-realistic-expectations-for-enterprise-ai-safety/)

**Evaluation practice:** [Challenges managing eval datasets](https://www.getmaxim.ai/articles/challenges-in-managing-high-quality-datasets-for-llm-evaluation/) · [Langfuse — LLM evaluation methods](https://langfuse.com/blog/2025-11-12-evals) · [Langfuse — security & guardrails positioning](https://langfuse.com/docs/security-and-guardrails)

**Market:** [Gartner MQ for AI Governance Platforms](https://www.gartner.com/en/documents/8006369) · [Kosmoy — AI governance platforms 2026](https://www.kosmoy.com/resources/blog/best-ai-governance-platforms-2026/) · [Kosmoy — agent governance platforms 2026](https://www.kosmoy.com/resources/blog/best-ai-agent-governance-platforms-2026/) · [Modulos buyer's guide](https://www.modulos.ai/best-ai-governance-platforms/)

**Consolidation:** [OpenAI to acquire Promptfoo](https://openai.com/index/openai-to-acquire-promptfoo/) · [Check Point acquires Lakera](https://www.checkpoint.com/press-releases/check-point-acquires-lakera-to-deliver-end-to-end-ai-security-for-enterprises/) · [Microsoft Entra Agent ID](https://learn.microsoft.com/en-us/entra/agent-id/what-is-microsoft-entra-agent-id) · [Entra ID Governance for agents](https://learn.microsoft.com/en-us/entra/id-governance/agent-id-governance-overview)

**Procurement:** [SOC 2 customer security questionnaire](https://www.konfirmity.com/blog/soc-2-customer-security-questionnaire) · [Security compliance questionnaires](https://www.workstreet.com/blog/security-compliance-questionnaires)

---
---

# Part IV — What shipped after this document was written

## 12. Addendum (2026-08-26 proposal, delivered by 2026-08-29)

A shorter, separate addendum was written 2026-08-26 after reading the OWASP Top 10 for Agentic
Applications 2026 in full and reviewing two competitor dashboards (Decawork, EVO). Its proposals
have since shipped; this section keeps the substance — what was missing, what control closed it,
which OWASP category — without the original's full build narrative, which belongs in git history,
not a living PRD.

### 12.1 P16 — Memory write governance (closes OWASP ASI06)

**Gap identified.** `assess_context()` checked documents and retrieval arriving as call arguments,
but nothing governed the *write* into an agent's long-term memory (a vector store, a `mem0`-style
store, a LangGraph checkpointer) — no content validation before a write committed, no cross-tenant
isolation on the store itself, no provenance weight on a retrieved memory entry, no expiry for an
unverified one.

**Shipped as `NOM-RTG-13`** (not `NOM-RTG-09` as first proposed — that code was already assigned to
P9's critical-action-risk block; see [Appendix B](control-catalog.md)'s changelog for the
correction): a `MemoryWrite` decision surface parallel to `guard_content`/`guard_tool_call`, running
the full detector pipeline on every write before it commits; provenance carried on the entry itself
so retrieval can weight a `tool_result`-tainted memory differently from one the end user typed
directly; `expires_at` defaulting closed on unverified entries; cross-tenant isolation reusing the
existing `TenantScoped` pattern. `MemoryEntry` model + migration, `Enforcer.guard_memory_write()`,
`GET/POST /api/memory`, `POST /v1/guard/memory_write` on the inline gateway.

### 12.2 P17 — Inter-agent communication security (closes OWASP ASI07)

**Gap identified.** Sub-agent output was folded into the `tool_result` surface — agent-to-agent
traffic got the same governance as a tool call, not a governed boundary of its own. No message
signing, no replay protection, no agent-card attestation anywhere in the enforcement path.

**Shipped as `NOM-IAM-08`:** a genuine `agent_message` surface distinct from `tool_result`, so a
sub-agent's output is evaluated as another agent's untrusted claim rather than a tool's return
value; HMAC message signing + verification for AgentFox-mediated agent-to-agent traffic (payload +
declared sender + nonce + timestamp), with unsigned traffic on an external transport reported as a
finding rather than silently passed; anti-replay via a short-term fingerprint cache; agent-card
fields checked against the sender at message time, reusing `attest_registry()`'s existing
declared-vs-observed comparison.

### 12.3 Declared hardening (extends existing pillars, not new ones)

- **ASI04 supply-chain signing** — `scan_mcp_server()` computed a digest for drift comparison but
  never verified a cryptographic signature. Extends `registry/service.py`, not a new pillar.
- **ASI10 behavioral attestation** — `attest_registry()` already did after-the-fact drift detection;
  periodic signed re-attestation is a parameter on existing machinery, not new architecture.
- **ASI05 (unexpected code execution)** — declared explicitly as a non-goal in writing (§10.3):
  AgentFox governs the interface into a tool call, not the agent's own code-execution runtime.

### 12.4 Dashboard UX — the complexity complaint, checked against evidence

A user complaint ("we are over complex... they are much more cleaner") was checked against two
competitor products page-by-page rather than argued about. It held. Fixed directly: table cells
that printed raw backend sentences instead of a one-line summary with detail behind a click (seven
instances across the app); Compliance's six scaffolding elements ahead of any real content, cut to
three; sidebar reduced from 16 flat items to 11 by folding Connect/tokens into Start Here and
merging Guardrails→Policies, Escalation→Approvals, Board view→Compliance as tabs (with redirects so
old links still resolve); inline-expandable rows, countdown-style expiry, a persistent stat strip,
and distinct approval-tag coloring adopted from the two competitor products reviewed.

### 12.5 Current status

Live, computed figures — not restated here because a number copied into a PRD starts going stale
the moment it's written: **[../status.md](../status.md)** (capability and failure-mode coverage,
regenerated by `python scripts/gen/coverage.py --write`), **[gap-analysis.md](gap-analysis.md)**
(enterprise-readiness and competitive position) and **[failure-modes.md](failure-modes.md)** (the
failure taxonomy). The §8.2 Tier 0 production-blocker list is closed, and the procurement bar
(SOC 2, ISO 27001, a completed pentest) remains almost entirely organisational, not engineering.

## 13. Addendum (2026-10-06): monitoring, live probing and hardening

Two capabilities this document never specified, and a round of fixes to what it did. As in §12,
this keeps the requirement and its status; the build narrative is in git history.

### 13.1 P1-9 — Continuous monitoring of connected sources

**Gap identified.** A repository, hosted API or MCP server was checked once, when someone
connected or scanned it. What changed afterwards (a new ungoverned model call, a removed
`auto()`, a new destructive endpoint, an MCP tool whose description changed) was invisible
until the next manual scan.

| ID | Requirement | Status |
|---|---|---|
| P1-9 | Re-check every connected source on its own interval and, for GitHub, on a signed push webhook; raise findings from the difference between runs, close them when they clear, raise one when a monitor keeps failing; alert to Slack and the finding webhook; create the monitor when the source is connected or scanned | ✅ |

Shipped as the `monitoring` package and the `monitors.run` job: `github_repo`, `hosted_api`,
`mcp_server` and `deployed_agent` monitor kinds, `/api/monitors` and `/api/alerts/slack`, and
`agentfox scan monitors`. The job runner is driven by the cron endpoint, a 30-minute GitHub
Actions workflow, or `agentfox admin jobs run-due`. Limits: GitHub is the only code host, and
there is no PagerDuty or email channel.

### 13.2 P4-13 / P4-14 — Live probing of deployed agents, and the public showcase

**Gap identified.** Red-team campaigns (P4-4) score the gateway's verdict on this
configuration, offline. Nothing asked whether the agent running right now still contains the
attacks it contained last week, after a deploy, a prompt change or a model swap.

| ID | Requirement | Status |
|---|---|---|
| P4-13 | Send a fixed probe library to a deployed agent's own endpoint on a schedule, only after a recorded opt-in for that host; score on observed behaviour; open a finding when a contained attack escapes and close it once contained again; hard caps per target and per job, and one switch that turns every target off | ✅ |
| P4-14 | Publish AgentFox probing its own demo agent, from a dedicated tenant, on a public page; off unless the deployment enables it | ✅ (off unless `AGENTFOX_SHOWCASE_ENABLED`) |

Shipped as `evaluation.live_probes` (`/api/probes`, run as the `deployed_agent` monitor kind,
with the `probes.run` job as fallback) and `evaluation.showcase` (`GET /api/public/showcase`,
rendered at `/live`). The probe set is fixed, not adaptive; an http target must answer the
small JSON contract the adapter sends.

### 13.3 Hardening of existing pillars

- **Platform security.** The gateway refuses to start outside development on published or
  default secrets. An invalid agent key is a 401 on every route. The kill switch covers every
  guard surface. Sign-out revokes the token, with at most five live login sessions.
  `agentfox admin users create` creates the first operator on a fresh install; the Docker
  image no longer seeds demo data on boot.
- **Policy (P12).** As in Pillar 12's status above, plus: each business ladder's own mode
  decides whether it acts, and a pack's own `fail_mode` is honoured.
- **Approvals (P2-3).** As in Pillar 2's status above, plus `agentfox permit approvals`; the
  proxy holds a call with HTTP 428.
- **Grounding and evidence.** `agentfox hooks install` registers the agent and grants the
  built-in tools; entitlement disclosure is blocked in enforce mode; label proposals carry a
  replay proof.
- **Detection and gates.** Injection detection on tool arguments; MCP poisoning patterns;
  `agentfox test redteam` and `agentfox scan mcp` exit 1 on an escape or a critical finding.

### 13.4 Deferred, deliberately

- The code restructure in [structure-proposal.md](structure-proposal.md), and with it new
  coding-agent harnesses (Codex first, then Cursor).
- The last of the Nometria→AgentFox rename: the `NOMETRIA_*` environment fallback, the
  `nometria` console script and the `x-nometria-*` headers stay while production depends on them.
- Building the vendored wheels at deploy time instead of committing them.

---

*All framework mappings in this product are engineering drafts, not legal advice, and are excluded
from evidence packages until reviewed by a qualified assessor. Coverage gaps are declared per
framework rather than hidden. Competitor capability claims come from 2026 public sources and shift
quickly — re-verify before positioning against a named vendor.*
