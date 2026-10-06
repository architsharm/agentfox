# Competitor Analysis & Positioning

**Date: 2026-09-04; our side of each comparison updated 2026-10-06.** Synthesized from [docs/PRD.md](PRD.md) §1.4 and §4,
[docs/gap-analysis.md](gap-analysis.md) Parts 3 and 5, and the raw research in
docs/research/ (kept outside this repository) (market-reality-check.md, enterprise-infrastructure-analysis.md,
practitioner-evidence.md, practitioner-signal.md). Those research files are background
inputs already synthesized into the PRD and gap-analysis — treat this document, in turn, as
the standalone competitive-positioning read: where the moat is real, where we concede ground
honestly, and who we're actually selling against.

The single most important fact about this analysis: **it is self-correcting in its own
source material.** Earlier drafts of the PRD overclaimed in several places (silent-failure
detection as unique, the audit chain as a headline differentiator, "the governance camp has
no runtime"), and those claims were explicitly retracted once checked against real competitor
docs. That discipline is preserved here — every claim below is either evidence-backed or
flagged as a concession.

For the architecture-level comparison (where each competitor sits, what it can see, and which of our measured results its design can or cannot reach), with corrections to two §4.1/§4.2 claims, see [architecture-differentiation.md](architecture-differentiation.md).

---

## 1. Who we actually compete with

Before any vendor comparison, the most load-bearing finding in the whole research base:

> "6 of 11 independently vetted senior/staff/principal AI engineers (Meta, Apple, Waymo,
> Accenture, Deloitte, Philips, Emirates NBD, Itaú, HP, Nvidia, Amazon) had already
> hand-built a governance/guardrail/validation layer inside their employer before this
> product existed. **We do not primarily compete with vendors. We compete with `git init`.**
> The buyer's alternative is two engineer-quarters of internal work." — `docs/design/PRD.md:76-84`

This reframes every competitor comparison below: the realistic sales conversation is not
"why us over Zenity," it's "why buy this instead of having your platform team build it again,
badly, for the fourth time this year." The named vendors matter for category credibility
(Gartner MQ inclusion, RFP checklists) and for the minority of deals where a competitor is
already in the building — but the volume opportunity is internal-build replacement.

---

## 2. The market landscape — five camps

| Camp | Who | What they own | What they lack (our opening) |
|---|---|---|---|
| **AI-governance platforms** (Gartner MQ, published 16 June 2026, 13 vendors) | IBM watsonx.governance, ServiceNow AI Control Tower, Truyo (Leaders); Credo AI, OneTrust, ModelOp, Airia, Monitaur, Cranium, Relyance, Saidot, SAP (Visionaries/others) | Policy, registry, framework mapping, enterprise trust and installed base | Built for the *model* era — thin-to-absent runtime enforcement, no execution-path evaluation, no per-argument containment |
| **Agent-security pure-plays** | Zenity, Noma, Arthur, WitnessAI, Astrix, Kosmoy | Runtime guardrails, some with real depth (sandboxing, adaptive red-team, network capture) | Thin on compliance framework mapping; several vendor-, model-, or platform-locked |
| **Security suites** | Palo Alto (Prisma AIRS), Cisco AI Defense (absorbed Robust Intelligence + Galileo), Check Point (absorbed Lakera, ~$300M), SentinelOne (absorbed Prompt Security) | Distribution, existing SOC integration, existing MSA relationships with the buyer | Point-security framing bolted onto a network suite, not built agent-native from the ground up |
| **AI observability/eval platforms** | LangSmith, Langfuse, Braintrust, Arize/Phoenix, Fiddler, Patronus, Opik, Galileo (→Cisco) | Tracing, dataset/eval workflows, groundedness scoring — several genuinely better than us at model-based hallucination detection | Show you the trace; **none tell you which step in a multi-agent handoff caused the failure** — and LangSmith's own new gateway stops at PII/secrets + spend caps, nothing on tool calls |
| **Model/platform vendors** | OpenAI Frontier/AgentKit, Microsoft Agent 365 + Entra Agent ID, Anthropic, Google ADK | Identity, permissions, audit, evals bundled with the runtime itself; Microsoft in particular is likely to simply win agent *identity* | Structural conflict of interest as a vendor-neutral compliance claim; will commoditize the identity/audit-plumbing layer, not the harder governance decisions above it |

**The single biggest strategic risk not obviously visible in a vendor list**: catalog/
semantic-layer incumbents (Atlan, Collibra, DataHub, dbt, Cube) already own enterprise
metadata and are actively repositioning around "a context layer for AI agents." The research
base explicitly flags this as **a more serious long-term threat than Zenity or Credo AI**,
because they start from an asset (the metadata) rather than having to build one
(`docs/research/enterprise-infrastructure-analysis.md:299` (kept outside this repository)).

---

## 3. Our niche

**Positioning statement** (`docs/design/PRD.md` header): *horizontal, SDK-first, vendor-neutral,
self-host by default.* **Unit of adoption**: `pip install agentfox` + a LangGraph decorator —
the self-hosted control plane is what a team graduates to at ~20 agents, not where they
start.

The defensible middle, stated plainly: a **vendor-neutral, agent-native control plane that
unifies runtime security + reliability/evaluation + tamper-evident audit + compliance
mapping** — a combination that a model provider cannot build without a conflict of interest,
a GRC incumbent cannot retrofit onto a policy-and-registry product, and a point-security tool
does not attempt because it stops at the network/content layer.

The sharpest one-line version of the pitch, aimed specifically at the LangSmith/Langfuse
installed base rather than at rip-and-replace prospects (`docs/research/market-reality-check.md:147` (kept outside this repository)):

> *"You already have traces. We turn them into enforcement, tuning and evidence — for what
> your agent does, not just what it says."*

---

## 4. What to highlight — genuinely differentiated, evidence-checked

Two tiers, each graded by how hard the claim would survive a skeptical technical buyer
asking "show me a competitor that already does this."

### 4.1 Genuinely unclaimed (checked against the full competitive field, nothing found)

| Claim | Why it's real | Best competitor comparison point |
|---|---|---|
| **Argument-provenance taint tracking with containment that holds after detection fails** | A tainted value can reach a low-impact tool freely but is structurally blocked from an irreversible one, independent of whether any individual detector fired — the containment is the backstop, not the detector | Zenity's public claim ("intent-based detection... full execution path including tool calls") is the closest anyone gets, and it's still detection-only language, not a stated containment-after-miss guarantee |
| **Answerability enforcement against a declared knowledge boundary, forced *before* generation** | The model never generates a plausible-but-ungrounded answer in the first place — "I don't have that" is a gate, not a post-hoc score | Cleanlab/Vectara/Galileo/Patronus all score confidence *after* generation — genuinely different mechanism, not just a better number |
| **Action semantics — deterministic parsing of generated SQL/artefacts for blast radius** | Statement-level analysis (unbounded DML, tautology WHERE clauses, DDL) against a real SQL parser, not a keyword deny-list | No agent-governance vendor surveyed performs this at the statement level |
| **Failure attribution across a multi-step, multi-agent handoff** | A practitioner (unprompted) called it "a stack trace for agent systems" — pinpoints which step introduced a bad value, not just that the final output was wrong | Absent from LangSmith, Langfuse, and every eval/observability vendor surveyed — they show the trace, not the causal step |

### 4.2 Contested but defensible — real, but a competitor could plausibly claim adjacency

| Claim | The honest caveat |
|---|---|
| Hierarchical policy composition (org → team → agent, one resolved decision) | 2 of 11 practitioners had hand-built exactly this; genuinely no vendor packages it as a product — but it's a reasonable feature for any policy-engine vendor to add |
| Entitlement-aware retrieval, done inline and cross-stack | Knostic addresses the same problem (RSA Innovation Sandbox / Launch Pad finalist, funded) — the differentiation is doing it inline across Azure/Bedrock/Vertex/Snowflake/Salesforce simultaneously, not owning a category no one else is in |
| Control status computed from telemetry, not attested | A claim only an inline platform can make credibly — weakened somewhat now that OpenAI Frontier is also inline |
| Self-host, zero-egress default | Real and valuable against SaaS-only competitors (Zenity, Credo AI, OneTrust are all SaaS-only) — but it's an architecture choice a competitor could make too, not IP |
| Tamper-evident audit chain with an independent, stdlib-only verifier | Genuinely nobody else advertises this combination — but no enterprise RFP leads with "do you have a hash-chained log," so it's a closer for the last mile of a regulated deal, not an opener |
| Approvals that complete the held call | Human-in-the-loop is table stakes. The narrower point: an approval is bound to the agent, tool and arguments it was asked for and redeemed once on retry, and none is granted while the agent is stopped |
| Continuous re-checking of connected sources, and opt-in probing of deployed agents | Re-scanning on a schedule is ordinary posture-management practice, not IP. Ours is narrow: GitHub repositories, OpenAPI specs and remote MCP servers someone connected, plus a fixed probe set sent only to endpoints that opted in |

### 4.3 Explicitly retired claims — do not use these, on record as corrected

The research base's own credibility rests partly on having caught and fixed these:

- **"We're ahead on silent-failure/hallucination detection."** False — Cleanlab TLM, Vectara
  HHEM, Galileo, Patronus Lynx, and RAGAS all do model-based groundedness scoring, and do it
  better than the current lexical scorer. *"We are behind here, not ahead — presenting it as
  a differentiator would fail the first serious technical question."*
- **"Nobody in the governance camp has runtime enforcement."** Eroding, not false-but-stale
  everywhere — LangSmith shipped a gateway, ModelOp partners with Kong, ServiceNow and Airia
  both have runtime paths now.
- **"Entitlement-aware access control is unclaimed."** Wrong — Knostic is a funded, named
  competitor doing exactly this.
- **"Nobody addresses escalation breakdown."** Half right — only *detecting a missed
  escalation* is unclaimed; human-in-the-loop itself is table stakes everywhere.

---

## 5. Where the competition wins — say this out loud before a buyer makes us say it

Conceding ground precisely, with the specific competitor and the specific gap:

| Competitor | Their strength | Our current position |
|---|---|---|
| **ServiceNow AI Control Tower** | ~30 discovery integrations, MCP gateway, per-agent kill switches | We have a kill switch that covers every guard surface, and inline MCP governance; discovery is repo/config-based (now re-checked on a schedule), nowhere near estate-scale connector breadth |
| **Zenity** | Inline step-level prevention *inside Copilot Studio*; Gartner's "company to beat" | We have zero coverage of the low-code/Copilot agent surface — this is a deliberate non-goal today, not an oversight, but it's real ceded ground |
| **Kosmoy** | Kernel-enforced sandboxing, per-task credentials, air-gapped Kubernetes support | We do not sandbox at all — explicitly out of scope (that's E2B/Modal/Daytona's job), but a buyer asking for it gets a "no" |
| **Noma** | Adaptive, learning red-team engine; $132M raised | We ship 22 static probes, an adaptive campaign engine that mutates attacks against this deployment's own grants and policies, and opt-in scheduled probing of deployed agents. Ours reports a change in posture against the last run, not a robustness score, and it does not learn |
| **Credo AI** | Purpose-built Policy Packs (e.g. NYC Local Law 144), CE-marking support for EU AI Act filings | Our one framework pack (EU AI Act high-risk) and all 317 framework mappings remain **DRAFT** — unreviewed by compliance counsel |
| **OneTrust** | ~14,000-organization installed base, third-party AI vendor risk workflows | We have none of this — no vendor-risk module, no comparable market presence |
| **IBM watsonx.governance** | AI Factsheets, SR 11-7 model-risk workflows, FedRAMP GovCloud | We have none of this — if the deal requires SR 11-7 (banking model risk) or FedRAMP, we're not in the conversation today |
| **Cleanlab / Vectara / Galileo / Patronus** | Model-based hallucination/groundedness scoring, benchmarked ahead of our lexical scorer | Acknowledged directly above — don't contest this point in a technical eval |
| **LangSmith** | Dataset splits, pairwise comparison, annotation queues; public **$39/seat** pricing | Our eval-suite tooling is comparably basic; **we have no published pricing at all** |
| **WitnessAI** | Network-level capture of desktop apps and IDEs, not just API traffic | We tokenize PII once content reaches us; we don't capture at the network layer |
| **Astrix + Microsoft Entra Agent ID** | Full NHI lifecycle, Conditional Access, ITSM/SIEM/SOAR integration | We model non-human identity but have no live IdP integration and no SOAR hooks; findings leave only through SIEM export, the finding webhook and (for monitor findings) Slack |
| **Almost every named competitor** | AWS/Azure Marketplace listing | We have none |

**Procurement-bar honesty**: 8 of 14 standard enterprise procurement requirements remain
unmet as of the last audit — SOC 2 Type II, ISO 27001, a pentest report, a filled SIG
questionnaire, DPA/sub-processor register, published DR/RTO/RPO, an uptime SLA, and
marketplace listings. All of these are organisational/legal work, not engineering gaps — see
[docs/production-readiness-review.md](production-readiness-review.md) and gap-analysis.md
Part 6 — but a buyer's security team will ask for all 14, and today's honest answer is "6 of
14, in progress on the rest."

---

## 6. Terminology and UX alignment — already done, worth knowing about

The dashboard's information architecture was deliberately checked against real competitor
products, not designed in isolation. Per `docs/design/PRD.md` §12.4: a user complaint ("we are over
complex... they are much more cleaner") was validated **page-by-page against two competitor
dashboards** (named internally as Decawork and EVO) rather than argued about, and held. Fixes
made directly from that comparison: the sidebar went from 16 flat items to 11 (folding
Connect/tokens into Start Here; merging Guardrails→Policies, Escalation→Approvals, Board
view→Compliance as tabs rather than standalone pages); table cells that printed raw backend
sentences were replaced with one-line summaries; inline-expandable rows, countdown-style
expiry, a persistent stat strip, and distinct approval-tag coloring were adopted from the
same review.

Vocabulary choices lean into the ecosystem's existing terms rather than inventing proprietary
ones: OWASP LLM Top 10 is labeled in-product as *"the industry-standard risk list for LLM
applications,"* MITRE ATLAS as a shared external taxonomy rather than an invented severity
scheme, and the glossary names the underlying OSS detector libraries directly (Presidio,
spaCy, NeMo/Colang, Granite Guardian, garak, pyrit) instead of obscuring them behind
marketing language. This matters competitively in a subtle way: a technical buyer moving
between our dashboard and a competitor's should recognize the vocabulary, not have to relearn
it — friction in a bake-off usually gets attributed to the newer, less-trusted vendor.

---

## 7. Who to sell to (and who not to, yet)

- **The real buyer, per direct practitioner evidence**: internal AI-platform teams told to
  "make it safe for 20 product teams to ship agents" (the Accenture/Waymo/Apollo.io/
  Xcaliber/Murphy USA pattern) — currently writing the equivalent of a hierarchical policy
  framework from scratch, i.e. exactly the `git init` alternative from §1.
- **Two buyers who don't talk to each other**: the engineer (acute, present-tense pain,
  served by no vendor today, rebuilds this every year) and the CISO/GRC buyer (wants
  framework mapping, shows up at procurement, further downstream). The evidence suggests
  the actual sales motion is **top-down-compatible bottom-up**, not pure PLG — *"compliance
  is not the wedge, it's what lets the wedge survive procurement."*
- **Regulated-industry concentration in the evidence base**: banking/fintech, healthcare,
  legal, retail/CPG, consulting, telecom/autonomous-driving — a real signal about where the
  pain is most acute, not just where the PRD's authors happened to know people.
- **Explicitly not our territory today**: low-code/Copilot-agent users (Microsoft Copilot
  Studio, Power Platform, Salesforce Agentforce) — that's Zenity's ground and Microsoft's
  own Purview/Entra stack; going after it without building the coverage first would be a
  losing fight.
- **Open, unresolved strategic question** (carried forward from gap-analysis.md, still
  unresolved): vertical vs. horizontal. Staying horizontal keeps the addressable market
  wide but caps how deep any one framework's coverage goes; picking a vertical (financial
  services → SR 11-7, or HR/employment → bias-auditing depth) would sharpen the pitch to
  exactly the buyers who most need it, at the cost of narrowing everyone else out. This
  decision determines what the next engineering cycle should actually build, and it hasn't
  been made.

---

## 8. Strategic risks beyond feature parity

1. **Platform absorption of the commodity middle.** The research base's own working
   assumption: *"Microsoft Entra Agent ID will win agent identity."* Model and platform
   vendors bundling identity/audit/eval as part of the runtime itself will commoditize the
   layer below the genuinely-hard governance decisions — the product needs to keep moving up
   the stack faster than the platforms move down it.
2. **The catalog/semantic-layer vendors are a slower but possibly bigger threat than any
   named security competitor** (§2) — they already hold the enterprise metadata a governance
   product eventually needs to be useful, and several are repositioning specifically around
   agents.
3. **Consolidation is accelerating, not slowing.** Four competitor-relevant acquisitions in
   roughly a year (promptfoo→OpenAI, Lakera→Check Point, Galileo→Cisco, Langfuse→ClickHouse),
   plus Weights & Biases→CoreWeave. Every one of these either removes a point of comparison
   or turns a former "reference" dependency into a competitor-owned one — this is the direct
   justification for the swappable-adapter architecture described in
   [docs/hld.md](../architecture/high-level-design.md) §2, not a hypothetical.
4. **No published pricing, in a market where at least one direct competitor (LangSmith)
   publishes theirs.** This is a sales-motion gap as much as a competitive one — see
   [docs/production-readiness-review.md](production-readiness-review.md) for the code-level
   framing and gap-analysis.md item 3.16 for the standing recommendation.

---

## 9. Summary — the one-paragraph version

We are not the best in the world at any single thing a competitor also does — Cleanlab beats
our hallucination detection, Zenity beats our Copilot-Studio coverage, ServiceNow beats our
discovery breadth, Credo AI beats our compliance-pack depth, and OneTrust simply has more
customers. What nobody else in the field currently combines is: containment that survives a
missed detection, an abstention gate that fires before generation instead of a confidence
score after, deterministic blast-radius analysis on generated actions, and a stack-trace for
multi-agent failures — running self-hosted, at zero egress, computing its own compliance
posture from telemetry instead of a spreadsheet. That combination is real, checked against
the field, and worth leading with. Everything else in this document is the honest list of
what still has to be built, bought, or certified before that combination is enough to win a
procurement process on its own.
