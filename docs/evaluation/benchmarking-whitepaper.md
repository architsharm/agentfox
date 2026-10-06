# AgentFox: A Governance Control Plane for AI Agents, and What We've Proven About It

**Date:** 2026-08-29, updated 2026-08-31 · **Status:** first edition, revised — added PII detection (§4.2), destructive-action/blast-radius (§4.4), and entitlement (§4.5) benchmark results once those datasets were built; F1 answerability is intentionally not cited with a benchmark number here (see §4.6) because its strongest measured category doesn't clear this document's own 65%-precision-and-recall bar — full numbers, not filtered, are in [`benchmarks/answerability/README.md`](../../benchmarks/answerability/README.md).

**How to read this document:** it's organized around the product, not around benchmark runs. For every capability, we say what it does, why it matters, how we know it works, and how it differs from what else is on the market. The rule we hold ourselves to throughout: every number we cite as "benchmarked" has a public, licensed dataset and a script anyone can re-run — link included.

---

## 1. What AgentFox is

AgentFox is a control plane that sits in front of AI agents in production — as an inline gateway or a one-line SDK wrapper — and governs what they're allowed to do, catches what they get wrong, and proves what happened afterward. It's built around four things happening at once, on every governed call: **detect** (is this content malicious, off-scope, or unsafe), **enforce** (is this action within the agent's actual entitlements, and is it reversible if wrong), **evaluate** (did the agent's answer hold up — grounded, complete, correctly abstained when it should have), and **prove** (a tamper-evident record of all of the above that an auditor can verify independently, without trusting us).

## 2. The insight that shaped what we built

Most of the market — competitors and the industry conversation both — treats "AI safety" as primarily a prompt-injection problem: can someone jailbreak the model into saying something bad. A study of over 10,000 real AI agent failure events (ChatSee, published July 2026) says that's not where production agents actually break: **hallucination-related failures are under 10%** of the total, while **resolution and escalation breakdowns are 31.1%** — the single largest category — and **execution/action failures are up 62%** year over year. Named incidents back this up directly: an AI coding agent that wiped 1.9M rows because it was pointed at production instead of staging; Microsoft 365 Copilot surfacing an entire M&A conversation to someone with valid read permissions but no reason to see it — described by its own investigators as "a governance failure rather than a security breach... every permission check passed."

That's the thesis this product is built on, and it shows up directly in what we built: strong prompt-injection detection because it's real and worth having (Sections 3–4), but built alongside — not instead of — entitlement-aware disclosure control, destructive-action blast-radius analysis, and escalation governance, the categories the failure data says actually dominate.

## 3. What makes AgentFox different (the USPs)

**The one that matters most, and the one we now measure directly.** Every published result on
adversarial robustness — most recently [*The Attacker Moves Second*](https://arxiv.org/abs/2510.09023),
over 90% attack success against twelve defences — says a determined attacker eventually gets past
content detection. We agree, and we publish our own adaptive-attack success rate (§4.0). What we claim
instead is that the *blast radius is bounded when that happens*, and we measure it by deleting the
detection layer entirely: **8/8 attack scenarios contained with zero detector signal**, and on
AgentDojo, with argument provenance inferred from the real tool outputs, **588/588 attack pairs
contained** at session-level taint. That containment has a utility cost we also publish: only 24/97
benign AgentDojo tasks run without escalation at that setting (§4.0). No competitor surveyed
publishes a detector-disabled containment number at all.

The seven capabilities below are how that holds up, each real, tested, and — as far as our own
competitive research could find — not offered together by any single competitor:

1. **Argument-provenance taint tracking.** Every tool-call argument carries where its value actually came from — a user, a retrieved document, another tool's output — and capability checks can be conditioned on that provenance, not just the argument's face value. The closest public competitor claim (Zenity's "intent-based detection examines the full execution path") doesn't go this granular. This is what lets containment hold **after** a content-detector fails — the tool call itself is still checked against what its arguments are actually made of.
2. **A tamper-evident audit chain with a standalone, stdlib-only verifier.** No competitor we found ships a hash-chained audit log an auditor can verify themselves, offline, without trusting our software to tell the truth about itself. Mutation, deletion, reorder, and checkpoint forgery are all independently detectable — a 60-second live demo for a regulated buyer.
3. **Control status computed from telemetry, not attested.** Most of the AI-governance category (per Gartner's own MQ commentary) collects self-reported attestations. Ours computes control status from what actually happened — a broken audit chain forces the audit control to `failing`, automatically, not on a schedule someone remembers to run.
4. **Declared gaps per framework, published rather than hidden.** Every one of 43 controls across 7 compliance frameworks ships with an explicit list of what it does *not* cover. This is unusual, and disproportionately credible in an audit conversation.
5. **Policy simulation before enforcement.** New policy versions replay against real recorded traffic and report what would newly break, before anyone turns enforcement on.
6. **Self-host by default, zero required egress.** The main SaaS governance platforms (Zenity, Credo AI, OneTrust) are SaaS-only. For a regulated buyer that can't send its traffic to a third party, this is a structural, not incremental, difference.
7. **Governing correctness as part of governance, not as a separate eval product.** Silent-failure detection (a 6-signal ensemble that discriminates "confidently wrong" from "correctly abstained") lives in the same enforcement path as the security controls, not bolted on from a separate observability tool.

Section 6 has the fuller competitive-landscape breakdown; the full audit is in [`docs/design/gap-analysis.md`](../design/gap-analysis.md).

## 4. Capability by capability: what it does, what we proved, what's real insight

Each entry below follows the same shape: what the capability does and why it's there, how we know it works, and how it differs from what competitors offer.

### 4.0 Containment when detection fails — the number we lead with

**What it does.** Capability grants, argument-provenance taint ceilings, declared tool impact tiers,
deterministic blast-radius analysis and the kill switch all decide whether an *action* may proceed
without reading the content at all. They are therefore unaffected by a detector miss, which is the
condition every adversarial-robustness paper says to expect.

**Benchmarked, twice, with detection switched off entirely.**
[`benchmarks/containment/`](../../benchmarks/containment/README.md) runs eight structurally different attack
scenarios with `AGENTFOX_ENABLED_DETECTORS=[]` — a total bypass, verified per scenario by re-probing the
payload and recording zero entities: **8/8 contained, 4/4 legitimate controls still allowed**.
[`benchmarks/agentdojo_e2e/`](../../benchmarks/agentdojo_e2e/README.md) executes
[AgentDojo](https://github.com/ethz-spylab/agentdojo)'s ground truth for all 97 user tasks and 949
attack pairs (v1.2.2), records the real tool outputs, and replays every call through the real
`guard_tool_call` path with provenance **inferred** by the shipped tracker. Over the 588 attack pairs
whose injection issues a write or irreversible call:

| Provenance | Benign tasks run without escalation | Attack pairs contained |
|---|---|---|
| Session-level taint (shipped default) | 24/97 (24.7% [17.2, 34.2]) | 588/588 |
| Argument-level taint | 37/97 | 527/588 |
| Argument-level taint, read-only tools exempt | 62/97 | 527/588 |
| Taken from the benchmark's labels (upper bound) | 97/97 | 588/588 |
| None (grants and impact tiers only) | 97/97 | 0/588 |

An earlier version of this benchmark reported every attacker call that acts as contained (42 of the
42) and every legitimate call as allowed (552 of the 552). That run took provenance from the benchmark's labels and counted each task once per
registered AgentDojo version (339 benign calls are unique, not 552), so it measured the policy given
perfect provenance, not the tracker.

**The honest limits, which belong next to the number.** Inferred provenance misses two kinds of
attacker value: identifiers shorter than six characters, which the tracker never matches, and
attacker text embedded inside a longer argument, which never appears verbatim in a tool output. And
59% of AgentDojo's legitimate write and irreversible calls copy a value out of a tool output, so
provenance alone cannot tell them from an attack; they are escalated.
Containment is also exactly as good as the declarations behind it — impact tiers, grants, constraints,
triggers and scopes are operator-declared, and an irreversible tool recorded as `read` is one a tainted
argument can reach. `agentfox doctor` now grades that readiness directly.

### 4.1 Prompt-injection & content-safety detection

**What it does.** A three-layer detector — fast regex heuristics, a fine-tuned classifier ensemble, and local embedding-similarity matching against a curated attack corpus — screens every input, output, tool argument, tool result, and retrieved chunk for injection/jailbreak attempts. Since this edition the heuristic layer also reads two extra views of the text before matching: words written one letter at a time (spaced, dotted, hyphenated or split by zero-width characters) rejoined, and the text inside HTML comments, hidden elements and markdown link titles, which raises `INJECTION.HIDDEN_INSTRUCTION` only when the hidden text both addresses the model and gives it a directive. Persona jailbreaks now need a persona switch and a removed restriction in the same sentence. The results files behind this section were written before that change.

**Benchmarked — yes, most extensively of anything in this document.** Primary dataset [`deepset/prompt-injections`](https://huggingface.co/datasets/deepset/prompt-injections) (662 examples): held-out recall went from **0% → 66.7%** across four rounds of measured changes, at **100% precision held throughout** — zero false positives at every step. That 66.7% is the opt-in configuration (heuristic plus the classifier ensemble, which needs `agentfox[classifiers]` and a one-time weights download); the default install runs the heuristic alone, at **26.7%** held-out recall and the same 100% precision. Generalization measured against four further independent, license-clean datasets the detectors were never tuned against — **with the opt-in classifier ensemble, which is not the shipped default** (5,345 examples total: [`spml`](https://huggingface.co/datasets/reshabhs/SPML_Chatbot_Prompt_Injection), [`yanismiraoui`](https://huggingface.co/datasets/yanismiraoui/prompt_injections), [`notinject`](https://huggingface.co/datasets/leolee99/NotInject), [`trustairlab`](https://huggingface.co/datasets/TrustAIRLab/in-the-wild-jailbreak-prompts)): recall of 85.6% and 98.6% on two of them through the real pipeline (re-measured 2026-09-16), with the honest cost disclosed on the other two (see below). Full methodology and every round: [`benchmarks/REPORT.md`](../../benchmarks/REPORT.md).

**Real insight this surfaced, reported honestly:** the classifier model swap that roughly doubled primary-benchmark recall (`protectai/deberta` → `leolee99/PIGuard`) also cut a dangerous over-defense problem by more than two-thirds — the old model flagged 42.2% of a dedicated benign-but-trigger-word-laden stress-test dataset as attacks; PIGuard alone cut that to 11.5%. But adding a secondary-model ensemble backstop to recover generalization recall on `spml`/`yanismiraoui` gave most of that over-defense fix back (false-positive rate rose to 41.3% on the same stress test). We shipped this as a disclosed, opt-out-able trade-off (`prompt_injection_classifier_secondary_model`), not a hidden cost — a deployment chooses which failure mode it fears more.

**Measured against an attacker who adapts, and published.**
[`benchmarks/adaptive/`](../../benchmarks/adaptive/README.md) implements the protocol from *The Attacker
Moves Second*: the attacker calls our real detector path, reads back the verdict and the entity list, and
steers its next mutation from that feedback. Against the attacks our stack currently stops, using only
human-readable mutations, attack success reaches **73% at a 50-attempt budget** (100% with encoding
operators included). Building it found three real detector defects, all since fixed — separator
collapsing that welded words together, unknown obfuscation producing no signal at all, and two missing
override objects that left two of our own canonical attack payloads undetected. The fixes cost the
attacker attempts rather than stopping the attack: success at a 5-attempt budget roughly halved
(63.2% → 36.8%), while at 50 attempts it barely moved. They also cut benign false positives on the
NotInject over-defense set from **8.6% to 0.3%**, and revealed that a meaningful share of our prior
obfuscation "detections" were curly apostrophes and em-dashes rather than attacks — a trade we
publish rather than hide, because topline recall on two generalization datasets fell when that
spurious signal was removed. We report this because
it is true, because the paper's stronger attacker classes — gradient, reinforcement-learning and human
red-teaming — are *not* implemented here so the real figure should be assumed higher, and because it is
the correct context for §4.0: of those bypasses that named a concrete harmful action, **38/38 were still
contained at the action** (28/28 before the detector fixes). Treat detection as a cost imposed on an attacker, not as a defence.

**Vendor context, not our score:** [Lakera's PINT benchmark](https://github.com/lakeraai/pint-benchmark) reports named-vendor numbers (Lakera Guard 95.2%, AWS Bedrock Guardrails 89.2%, Azure Prompt Shield 89.1%) but its dataset was never public and the repo is now archived — we can't reproduce a PINT score, so we don't claim one. Not directly comparable to our own numbers (different dataset, self-reported); cited only so a reader has market context.

### 4.2 PII detection

**What it does.** Two detectors — a regex-only, jurisdiction-aware engine (US/UK/EU/India) and a wrapper around Microsoft Presidio's NER-based recognizers — scan content for personal data. The two are complementary: regex catches well-structured, format-constrained identifiers (email, IBAN, SSN) at near-parity with Presidio; Presidio's NER model is what catches names and locations in free text, which no regex can.

**Benchmarked against three independent datasets** — synthetic short-sentence text, dense multilingual financial documents, and real European Court of Human Rights case law — after two rounds of fixes driven by reading actual false positives rather than trusting the aggregate percentage (a `US_SSN` score-gate, a taxonomy fix separating a birthdate-specific detector from Presidio's generic date recognizer, and others). We're reporting only the results that clear a 65%/65% precision-and-recall bar here, honestly labeled by which policy configuration reached it — the shipped default policy deliberately trades recall on noisy categories (`PERSON`/`LOCATION`/`DATE_TIME`) for precision, so it doesn't clear this bar on its own, and we're not hiding that:

- **Real ECHR case law (TAB dataset, 127 real judgments), full policy: 83.6% precision / 86.9% recall.** The strongest result of the three — coherent single-language legal prose is closer to what a general-purpose NER model was trained on than templated or dense multilingual synthetic text.
- **Synthetic sentence dataset (presidio-research, 1,500 rows), full policy: 65.2% precision / 75.6% recall.**

Well-structured identifier types (`EMAIL`, `IBAN`, `IP_ADDRESS`) hold 90%+ precision and recall regardless of dataset or language and are not separately broken out here. Full per-dataset numbers, including where the default policy and a multilingual financial-document dataset fall short of this bar and why, are reported without the filter in [`benchmarks/pii/README.md`](../../benchmarks/pii/README.md) — we'd rather a reader see the honest full picture there than infer we're hiding a weaker number by omitting it entirely.

### 4.3 Agent-runtime security — structural attacks a text scanner can't see

**What it does and why it's different.** A stateless text scanner (LLM Guard and everything built on the same pattern) evaluates one string at a time, with no memory of the conversation and no visibility into tool-call structure. This is a real, useful control, but it has no axis at all for state, tool-call structure, or capability enforcement. We built and benchmarked four tiers specifically to cover what that architecture structurally cannot: multi-turn payload splitting, indirect injection via tool output, tool-parameter exploitation, and excessive-agency/privilege escalation.

**Benchmarked — yes, against a real, independently-installed `llm-guard`, not an asserted comparison.**

| Tier | What it tests | AgentFox | LLM Guard |
|---|---|---|---|
| A — multi-turn / payload splitting | "Ignore all previous instructions" split across 3 separate API calls | 2/2 correct — none of the 3 fragments fires alone, only the assembled window | Flags all 3 fragments individually — not multi-turn awareness, just over-triggering |
| B — indirect injection via tool output | 20 cases: hidden instructions, poisoned MCP tool descriptions | 100.0% recall / 66.7% precision | 90.0% recall / 81.8% precision |
| C — tool-parameter exploitation | Wildcard scope, SQL fragments, path traversal in unnamed arguments | 10/10 correct | Cannot participate — scans text, not structured JSON |
| D — excessive agency / privilege escalation | 6 scenarios against real shipped capability grants | 6/6 correct | Cannot participate — no capability model |

Full methodology: [`benchmarks/agent_security/README.md`](../../benchmarks/agent_security/README.md).

**Real insight this surfaced:** a poisoned tool result that a follow-up tool call tries to act on is caught independent of whether the content-level detector fires on the poisoned text at all — the follow-up call is separately gated because its argument's *provenance* (tool output, not user input) triggers a human-oversight escalation on its own. This is the taint-tracking USP from Section 3 made concrete, not just asserted: a stateless scanner has no mechanism to gate a subsequent, separate tool call based on where an earlier piece of content came from.

### 4.4 Destructive-action & blast-radius analysis (database and irreversible-action safety)

**What it does and why it matters.** Deterministic parsing (not an LLM checking its own SQL) of generated database statements and tool calls — classifying operation type, targets, estimated affected rows, reversibility, and environment — with policy expressed on blast radius rather than argument values. This is the control aimed directly at incidents like the 1.9M-row production wipe named in Section 2. Live on the enforcement path (`capabilities/detection/actions.py`, wired into `runtime/enforcement/`): tautology-as-unbounded-`WHERE` detection, comment/stacked-statement evasion, environment binding, state-verification preconditions.

**Benchmarked.** Destructive-SQL classification against [`gretelai/synthetic_text_to_sql`](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql) (Apache-2.0): **100% accuracy, precision and recall** on the held-out split across all four tested categories (real DML/DDL, and adversarial unbounded/tautology variants), ground-truthed against an independent third-party SQL parser rather than the product's own verdict. The generic argument-scope backstop (catches wildcard-scope values and SQL-injection fragments arriving through *unnamed* fields, not just declared SQL fields) scores **89.3% recall / 100% precision** against [payload-box's SQL-injection payload list](https://github.com/payload-box/sql-injection-payload-list) (MIT) after two rounds of directed fixes. Full methodology: [`benchmarks/action_safety/README.md`](../../benchmarks/action_safety/README.md).

**Composed privilege escalation — closed this cycle, not yet independently benchmarked.** A read tool's output feeding a second tool's authorization boundary in a way neither tool alone permits (e.g. an internal ID a read call surfaces, then reused by a write call as if it were user-supplied and authorized) is now detected by reusing the existing argument-provenance taint tracker against each tool's declared impact tier — no dataset exists yet to score precision/recall against this specific failure shape, so it's verified via unit and end-to-end tests rather than a benchmark number. Named plainly rather than rounded off into the benchmarked claim above.

### 4.5 Entitlement & disclosure control

**What it does and why it matters.** Propagates the actual end-user's identity through retrieval and tool calls, and checks that a response only contains what *that specific person* is entitled to see — not what the agent's own service identity can reach. This is the exact failure named in Section 2's Copilot incident: every permission check passing while the wrong human still sees everything. Real and live on the enforcement path (`entitlement.py`, `tenancy.py`), including cross-tenant isolation enforced structurally at the session level rather than per-query.

**Benchmarked — a different, more modest kind of evidence than Sections 4.1–4.4.** Purpose-limitation enforcement (`filter_retrieval`, GDPR Art. 5(1)(b)) scores **100% recall / 0% false-positive rate across 493 real, human-authored [PrivacyLens](https://github.com/SALT-NLP/PrivacyLens) vignettes** — real over-sharing scenario content, but a mechanically-constructed test (grant one purpose, request another) rather than a labeled dataset's own ground truth. A correctly-built purpose check was always going to score this way; the real evidence is that it holds across 493 genuinely varied real-world purpose strings without a collision or a wrapper bug. Full caveat and methodology: [`benchmarks/entitlement/README.md`](../../benchmarks/entitlement/README.md).

### 4.6 Answerability & abstention

**What it does.** A declared knowledge boundary per agent — which systems it can reach, what time range, which question types are answerable — with a pre-flight classifier that routes unanswerable questions to abstention *before* generation, rather than letting the model invent an answer.

**Why this is a real gap in the market, not a manufactured one:** academic research (AbstentionBench, 35k+ unanswerable queries across 20 datasets) finds that reasoning fine-tuning often makes newer models *worse* at knowing when to say "I don't know" — this is getting worse, not better, as models improve on other axes. All 6 named failure modes are unit-tested and live on the enforcement path (`answerability.py`).

### 4.7 Source authority & provenance

**What it does.** Every retrieved chunk carries a source tier (system-of-record / approved / unverified / external), freshness, and owner — turning "the answer is grounded in the retrieved context" (a lab metric every RAG eval tool measures) into "the retrieved context was itself authoritative" (the question that actually matters to a business). Citation binding checks that a material claim maps to a chunk that actually supports it. Real, live (`provenance.py`), all 6 modes unit-tested.

### 4.8 Escalation governance

**What it does.** Per-agent escalation policy (conditions that must trigger human hand-off), counterfactual detection ("this should have escalated and didn't"), context-complete hand-off packages, and owner + SLA tracking on the resulting queue. This is the single largest category from Section 2's failure data (31.1%), and it went from zero coverage to a dedicated 821-line, unit-tested module this cycle. 6 of 7 named failure modes are unit-tested and live.

### 4.9 Commitment, advice & liability (F6) — built, honestly flagged as not yet reachable

**What it exists to do.** Detect binding commitments an agent shouldn't be able to make unilaterally (refunds, SLAs), flag unlicensed financial/medical/legal advice, check EU AI Act Art. 50 disclosure, and run a fairness probe for discriminatory screening outcomes.

**Status, stated plainly:** this section's first edition said nothing in the live enforcement path called this logic. That is no longer true. `commitments.py` and `register.py` now run on the output surface of every governed call, and what they find is recorded as findings and as risks a policy can act on; observe-first, they do not decide a verdict by themselves. An answer that claims to be a person feeds the `eu.art50.impersonation` rule, which escalates (its pack ships in observe). The disclosure and adverse-action checks run only when the caller supplies the channel or the decision record they need, and the fairness probe stays on the compliance path, because one request cannot show disparate impact. None of this is benchmarked here; see [`docs/design/gap-analysis.md`](../design/gap-analysis.md) for build status across modules.

### 4.10 Numeric, temporal & entity integrity

**What it does.** Verifies record matches against the actual system of record (catching hallucinated matches, the class of error behind real finance-reconciliation incidents), checks arithmetic/aggregation against the cited rows, and disambiguates fiscal-vs-calendar periods and units/currency. Live on the enforcement path (`integrity.py`), 5 of 7 named failure modes unit-tested.

### 4.11 Audit chain, evidence packages, and compliance mapping

**What it does.** A different kind of guarantee than the detectors above — not "did we catch the bad thing" but "can what happened be proven, tamper-evidently, to someone who doesn't trust us." A hash-chained audit log, a standalone stdlib-only verifier an auditor can run offline, evidence packages that exclude unreviewed compliance-framework mappings by construction, and control status computed from live telemetry rather than attested.

**Verified adversarially, not just tested.** "Benchmark" isn't quite the right frame for an integrity guarantee; the equivalent rigor is adversarial — mutation, deletion, insertion/reorder, and checkpoint-forgery attempts, all independently detected, verified by extracting a real evidence package and running its verifier under a clean system Python, outside the repo entirely.

### 4.12 Silent-failure / correctness detection

**What it does.** The project's original flagship differentiator: a 6-signal ensemble that discriminates a confidently-wrong answer from a correctly-hedged one, aimed at the failure mode most of the rest of the market's tooling (and most of the "AI safety" conversation) treats as the whole problem. 8 unit tests cover the discrimination logic. Per Section 2's own data, this covers under 10% of real-world failure share — which is precisely why the roadmap put F1–F5 ahead of expanding this further.

### 4.13 Automated red-teaming

**What it does.** A campaign runner (`agentfox test redteam <agent>`) fires a suite of
adversarial probes at a deployed agent's *actual* configuration — real capability
grants, real policy bindings, real detector stack — and reports posture: recall (attacks
caught) and, as of this round, precision (legitimate traffic wrongly blocked) together,
mapped to OWASP LLM Top 10 and MITRE ATLAS. NVIDIA Garak and Microsoft PyRIT wrap in as
optional external scanners; what this adds on top is campaign tracking, posture over
time, and the tie-in to controls that turns a red-team result into compliance evidence
rather than a log line. Probes are a dry run: their tool calls are evaluated without writing
decisions, so they never reach findings or the traffic `policy simulate` replays. The command
exits 1 when an attack got through, so it can gate CI.

**Benchmarked, after closing a structural gap the benchmark itself found.** Every probe
used to only reach `Enforcer.check_content()` — which never exercises capability/
constraint checks, the destructive-action/SQLi backstop, or composed privilege
escalation (§4.4), regardless of how well those layers work. New `tool_call`/`scenario`
probes reach `guard_tool_call()` directly, the same call the real request path makes.
Result, all 22 built-in probes against every seed agent, `enforce` mode: **100% recall,
100% precision** (two of three agents); the third scores 95% precision for a real,
disclosed reason — a stricter EU AI Act Art. 14 policy also bound to that agent
correctly requires human sign-off on an irreversible action regardless of provenance,
not a false positive in this benchmark's usual sense. Full methodology, and five real
bugs/gaps found and fixed while building this (a policy threshold silently discarding
15 already-detected attacks, a real detector gap, two runner bugs):
[`benchmarks/redteam/README.md`](../../benchmarks/redteam/README.md).

## 5. Competitive landscape — where AgentFox sits

Four camps exist in this market, and AgentFox doesn't fit cleanly into any one of them — which is a fair way to describe both its opportunity and its risk:

| Camp | Examples | Runtime enforcement | Compliance depth | What they have that we don't |
|---|---|---|---|---|
| Agent-security pure-plays | Zenity, Noma, Arthur, WitnessAI | Strong | Thin | Estate-scale discovery, adaptive red-team, market maturity |
| Security suites | Palo Alto, Cisco AI Defense, Check Point+Lakera | Strong, network-integrated | Medium | Distribution, SOC integration |
| AI governance platforms (Gartner MQ) | IBM, ServiceNow, Credo AI, OneTrust | Mostly none — Gartner's own finding | Deep | Workflow/assessment engines, analyst recognition, installed base |
| Eval / observability | Braintrust, Arize, LangSmith | N/A | N/A | Eval UX depth, dataset tooling |

Gartner's own read on the governance camp is that it largely lacks runtime enforcement, and the security camp largely lacks compliance depth. AgentFox's bet is the combination — runtime enforcement *and* audit-grade compliance depth, in one product, self-hosted. The full gap register, including where we still fall short of category table stakes (estate-scale connectors, a general workflow engine, third-party certifications), is in [`docs/design/gap-analysis.md`](../design/gap-analysis.md).

## 6. Methodology discipline (the rules every number above follows)

A capability counts as "benchmarked" in this document only if: it's scored against a public, licensed dataset (named and linked, or fetched by a re-runnable script); the scoring runs the real shipping code, not a reimplementation; per-example predictions are saved, not just an aggregate; and negative and inconclusive results are reported alongside positive ones (three appear in Section 4.1 alone).

---

## Appendix — source files

- [`benchmarks/REPORT.md`](../../benchmarks/REPORT.md) — full prompt-injection benchmark methodology, all six rounds.
- [`benchmarks/agent_security/README.md`](../../benchmarks/agent_security/README.md) — the four-tier agent-runtime-security suite, full methodology.
- [`benchmarks/data_generalization/README.md`](../../benchmarks/data_generalization/README.md) — the four generalization datasets: sources, licenses, and datasets considered and rejected.
- [`benchmarks/pii/README.md`](../../benchmarks/pii/README.md) — PII detection, all three datasets, both fix rounds, unfiltered numbers.
- [`benchmarks/action_safety/README.md`](../../benchmarks/action_safety/README.md) — destructive-action/blast-radius, all four datasets.
- [`benchmarks/entitlement/README.md`](../../benchmarks/entitlement/README.md) — the purpose-limitation scenario benchmark and its caveats.
- [`benchmarks/answerability/README.md`](../../benchmarks/answerability/README.md) — F1 answerability/abstention, both rounds of fixes, including the categories that don't clear this document's 65% bar.
- [`benchmarks/README.md`](../../benchmarks/README.md) — index across every capability area, including the two (F2, secrets) investigated and found not benchmarkable, and F3.8 (built this cycle, no dataset exists to score it against).
- [`docs/design/gap-analysis.md`](../design/gap-analysis.md), [`docs/design/failure-modes.md`](../design/failure-modes.md) — full capability-by-capability build status, including what's unit-tested vs. wired to the live request path vs. genuinely absent.
