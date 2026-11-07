# Business Failure-Mode Analysis — where deployed agents actually break

**The failure-mode catalogue, and the hand-checked score against it.** It measures AgentFox against **how enterprise agents actually fail in production** rather than against vendor feature lists. What is still open is in [gap-analysis.md](gap-analysis.md); the probe-computed view is in [../status.md](../status.md) (generated); an independent, architecture-derived view is [coverage-map.md](coverage-map.md) (generated).

**Status, re-checked against `main` at release 0.5.0 (2026-11-07).** Every status below is a passing test, a code citation, or an import check. Of the 57 catalogued modes, 48 are covered on the live request path, 7 are partial and 2 are absent (F7.7 cross-turn self-contradiction, F8.3 stale index). This hand count is stricter than the generated one in [../status.md](../status.md), whose probe only checks that each mode's code exists; the coverage summary says where the two differ and why. Module paths are relative to `src/agentfox/`.

The F6, F8 and F9 checks (commitments, context integrity, sycophancy, crescendo) and control-flow integrity, which catches an injected *step* rather than a poisoned *value*, record findings and never block on their own; a policy rule on the `action_risk` condition makes them block, which is the observe-first default.

---

## The finding that reframes the roadmap

A study of **10,000+ AI failure events** (ChatSee, published Jul 2026) found:

| Failure class | Share |
|---|---|
| **Resolution / escalation breakdowns** | **31.1%** |
| Execution and action failures | **up 62%** vs Q2-2024 baseline |
| **Hallucination-related** | **< 10%** |

Supporting figures: **88% of organisations had at least one AI agent security incident in 2025**; only **~10% of agent pilots reach production**; **fewer than 25%** of enterprises running multi-agent pilots report confidence in reliability or governance.

Silent-failure detection is aimed at the **smallest** slice of this problem; escalation breakdown (31%) and execution and action failures (fastest-growing) are the large ones. The rest of this document is the failure taxonomy we govern against.

---

## Named incidents worth designing against

| Incident | What happened | What would have caught it |
|---|---|---|
| **AI coding agent wipes 1.9M rows** (2024) | Agent connected to **production instead of staging** and executed deletion tasks "flawlessly from a technical standpoint" | Environment binding on the tool target + destructive-statement analysis |
| **Finance reconciliation agent** | "Confirmed" a transaction matched by **hallucinating the matching record**. Not caught until month-end close | Claim-to-record verification: any asserted fact about a record must resolve against the record |
| **HR onboarding agent** | Sent a welcome email to a candidate who **had not accepted the offer** — hallucinated the acceptance status | Irreversible action gated on **verified** state, not asserted state |
| **M365 Copilot oversharing** | *"a governance failure rather than a security breach — every permission check passed."* One prompt (*"summarise our M&A discussions last quarter"*) surfaces everything the account can read | End-user entitlement propagation + retrieval-scope enforcement |
| **Sales qualification agent** | Hallucinates objection responses **after step four** of the conversation | Turn-depth degradation monitoring |
| **Scheduling agent** | Loops indefinitely when the caller deviates from the expected script | Escalation-failure detection (we have loop breaking, not escalation logic) |

---

## The taxonomy — 8 failure families (F1–F8) plus 5 audit-found modes (F9), 57 in total

Legend: ✅ covered and live on the request path · ◐ partial, real but narrower than the claim · ✗ absent. Verified against the codebase on 2026-11-07 by test citation, code citation or import check.

### F1 — Answerability & abstention
*"If someone asks for future sales, the answer should be 'data not available', not a generated one."*

The research is unambiguous that this is unsolved: **AbstentionBench** (20 datasets, 35k+ unanswerable queries) finds that **reasoning fine-tuning often *degrades* abstention** — newer, more capable models are *worse* at saying "I don't know". And the inverse failure is real too: retrieval noise causes **over-refusal**, where the model refuses questions it could answer.

| # | Failure mode | Example | Status |
|---|---|---|---|
| F1.1 | **Answers an unknowable question** | "What will Q4 2027 revenue be?" → generates a number | ✅ |
| F1.2 | **Answers outside the data coverage window** | Index holds 24 months; asked about 5 years ago | ✅ |
| F1.3 | **Answers for an entity not in scope** | Customer not in the CRM → invents a record | ✅ |
| F1.4 | **Prediction presented as record** | Forecast stated in the same register as an actual | ✅ |
| F1.5 | **Over-refusal** | Refuses something it can and should answer; kills adoption | ✅ |
| F1.6 | **Partial answer presented as complete** | Retrieved 3 of 50 relevant docs, answers as if exhaustive | ✅ |

**Built and live:** `src/agentfox/capabilities/grounding/answerability.py`, run on the request path by the enforcer (`runtime/enforcement/`) — a declared knowledge boundary per agent (systems of record, time range, entity scope, answerable question types), a pre-flight answerability classifier that routes unanswerable questions to templated abstention before generation, and a post-flight check that the answer stayed inside the declared boundary. All six modes have passing tests and run on a live request, not just in isolation.

This is a control almost nobody in the competitive set ships, and it's now real, not aspirational. It is directly sellable: *"your agent will say 'I don't have that' instead of inventing it."*

### F2 — Source authority & provenance
*"How do we know it didn't use an unverified source?"*

Our `groundedness` scorer checks the **answer against the retrieved context**. It never asks whether that **context was authoritative**. An agent that faithfully grounds an answer in a deprecated 2019 wiki page scores 1.0.

| # | Failure mode | Example | Status |
|---|---|---|---|
| F2.1 | **Unauthoritative source** | Answers a pricing question from a personal OneNote, not the price book | ✅ |
| F2.2 | **Stale source** | Policy changed last week; index is a month old | ✅ |
| F2.3 | **Fabricated citation** | Cites a document that does not contain the claim | ✅ |
| F2.4 | **Contradictory sources, silent pick** | Two docs disagree; agent picks one, never says so | ✅ |
| F2.5 | **Uncited assertion** | Material claim with no source at all | ✅ |
| F2.6 | **Source outside the agent's declared domain** | Support agent answering from the finance corpus | ✅ |

**Built and live:** `src/agentfox/capabilities/grounding/provenance.py`, run on the request path (`capabilities/grounding/checks.py`) via `assess_provenance(...)` — every retrieved chunk carries a source tier (system-of-record / approved / unverified / external), freshness, and owner. Policy is expressed as e.g. *"financial figures may only be sourced from tier-1 systems of record less than 24h old."* Citation binding checks that each material claim maps to a chunk that actually supports it, catching fabricated citations and silent picks between contradictory sources — this turns the old groundedness-only scorer into an enforceable control, not just a lab metric. Remaining seam, not a gap in the table above: `P8-9`, ingesting third-party catalog/lineage metadata (DataHub, OpenMetadata, Unity Catalog) so source tier and ownership can be *derived* rather than hand-declared per agent.

### F3 — Destructive & irreversible actions
*"How do we know the prompt can cause destructive changes to the DB?"*

Our containment is **argument-level** on **declared tools** (`amount < 1000`). It has nothing to say about a **generated artefact** — SQL, a script, an API body — whose destructiveness lives in its *structure*, not its arguments.

The research is specific about how to do this correctly: **deterministic parsing, not an LLM checking the SQL**, with **zero false negatives**, and **comments stripped first** — because `SELECT * FROM users -- ; DROP TABLE users` defeats naive keyword matching.

| # | Failure mode | Example | Status |
|---|---|---|---|
| F3.1 | **Destructive DML** | `DELETE FROM orders` with no `WHERE` | ✅ |
| F3.2 | **DDL / schema change** | `DROP TABLE`, `TRUNCATE`, `ALTER` | ✅ |
| F3.3 | **Unbounded blast radius** | `UPDATE` matching 1.2M rows | ✅ |
| F3.4 | **Wrong environment** | Ran against prod, not staging — *the 1.9M-row incident* | ✅ |
| F3.5 | **Comment/stacked-statement evasion** | `-- ; DROP TABLE` | ✅ |
| F3.6 | **Irreversible act on unverified state** | Welcome email on a hallucinated acceptance | ✅ |
| F3.7 | **Duplicate execution on retry** | Same refund issued twice | ✅ |
| F3.8 | **Composed privilege escalation** | Read tool + write tool chained into something neither permits | ✅ |
| F3.9 | **Cascading side effects** | One write fires webhooks/automations | ✅ |
| F3.10 | **Partial completion, no rollback** | Multi-step action half-applied | ✅ |

**Built and live:** `src/agentfox/capabilities/detection/actions.py`, `runtime/enforcement/`, `capabilities/containment/effects.py` — a deterministic action-semantics analyser, using sqlglot AST parsing (not an LLM checking its own SQL), classifies generated SQL into operation, targets, estimated affected rows, reversibility, and environment; detects tautology-as-unbounded-`WHERE`, stacked-statement and comment evasion; enforces environment binding on the tool target; and gates irreversible actions on state read back from the system of record rather than the model's assertion. This is the fastest-growing failure class (+62%) and the one that makes the news — now the most completely covered family bar one mode.

**F3.8 moved to ✅, built on top of infrastructure that already existed for a different purpose.** `sql.privilege_change` in `actions.py` fires on `GRANT`/`REVOKE` statements, which is a real but narrow slice of "privilege escalation" — F3.8's own example is broader: a read tool's output chained into a write/authorization boundary neither tool alone permits (e.g. a read tool surfaces an internal ID that a second, differently-scoped tool then accepts as if it were user-supplied and authorized). The taint tracker (`capabilities/detection/taint.py`, P3-4) already recorded exactly the fact this needed — `TaintMark.propagated_from`, which tool's result a later argument's value was inferred from — it just wasn't being compared against tool scope. `capabilities/detection/composition.py` (P9-11) adds that one comparison: resolve the producing tool's registered `Tool.impact`, compare it against the consuming tool's, and block when a lower-impact tool's output silently feeds a higher-impact one. Wired into the enforcer's evaluation on the live `guard_tool_call` path; `tests/capabilities/detection/test_composition.py` exercises it end to end through `McpGovernor`, including a negative control proving independently supplied arguments aren't falsely flagged. Also a real caveat inside the built modes: F3.9 cascade analysis is only as good as the trigger declarations it is given — an undeclared webhook stays invisible.

### F4 — Entitlement & disclosure
*"The agent has an SDK for information that must not be given."*

The Copilot research puts it exactly right: **"a governance failure rather than a security breach — every permission check passed."** The agent runs with its own service identity and inherits the union of everything it can reach. Nothing checks what **this requesting human** is entitled to.

| # | Failure mode | Example | Status |
|---|---|---|---|
| F4.1 | **Oversharing via retrieval** | Employee asks about salaries; index has HR docs; every ACL passes | ✅ |
| F4.2 | **Agent identity ≠ user entitlement** | Agent's service account is broader than the caller | ✅ |
| F4.3 | **Cross-tenant leakage** | Multi-tenant app, tenant A sees tenant B | ✅ |
| F4.4 | **Aggregation disclosure** | Salary band + headcount of 1 → an individual's salary | ✅ |
| F4.5 | **Inference disclosure** | Model infers a protected attribute never stored | ✅ |
| F4.6 | **Purpose limitation breach** | Support data reused for marketing (GDPR Art. 5) | ✅ |
| F4.7 | **MNPI / blackout / legal hold** | Agent surfaces material non-public information | ◐ |
| F4.8 | **Residency violation** | EU subject data answered from a US context | ✅ |

**Built and live:** `src/agentfox/capabilities/grounding/entitlement.py`, `src/agentfox/core/tenancy.py`, run on the request path — the end-user principal is propagated through the agent to retrieval and tools; responses are checked against what that principal is entitled to see; over-permissioned retrieval (agent could reach more than the caller) is detected; tenant isolation is enforced structurally at the session level via `with_loader_criteria` rather than per-query filters. This remains the single highest-value gap commercially — it is the reason Copilot rollouts stall — and it is now a genuine strength, not a plan. The one declared seam: `P10`'s OpenFGA adapter is a stub, not a live integration.

**F4.7 stays ◐:** the entitlement mechanism itself is generic and works for any named sensitivity class, but only `mnpi` and `pii_sensitive` are exercised by name in tests today — a real legal-hold/blackout-list class hasn't been wired through end to end, so the plumbing exists but the specific class isn't proven live.

### F5 — Escalation & resolution breakdown — **31.1% of all failures**

The largest category by real-world share, and the one that saw the most build-out since the original audit. We went from **zero** coverage to a dedicated 821-line module wired into the live turn-recording path.

| # | Failure mode | Example | Status |
|---|---|---|---|
| F5.1 | **Failed to escalate** | Kept trying instead of handing to a human | ✅ |
| F5.2 | **Escalated without context** | Human receives a ticket with no history | ✅ |
| F5.3 | **Loops instead of escalating** | Scheduling agent when the caller goes off-script | ✅ |
| F5.4 | **Turn-depth degradation** | Quality collapses after step 4 | ◐ |
| F5.5 | **False resolution** | Marks resolved without resolving | ✅ |
| F5.6 | **Dropped hand-off** | Escalation raised, nobody owns it, no SLA | ✅ |
| F5.7 | **Sentiment/urgency blindness** | Misses a distressed or legally-charged user | ✅ |

**Built and live:** `src/agentfox/capabilities/containment/escalation.py`, wired via `frameworks/autoguard/`'s per-turn recording (retrospective by design — missed-escalation detection can only be judged over a conversation, not a single message) — a per-agent escalation policy (conditions that must trigger hand-off: low confidence, repeated failure, user frustration, out-of-scope, regulated topic), counterfactual detection ("this should have escalated, and didn't"), context-complete hand-off packages, and owner + SLA tracking on the queue. The dashboard's hand-off queue reads from this directly.

**F5.4 stays ◐:** what's measured is a turn-depth-correlated abstention-rate proxy, not an actual quality-trend measurement against ground truth — a real signal, but not the same claim as "we detect the conversation getting worse."

### F6 — Commitment, advice & liability

| # | Failure mode | Example | Status |
|---|---|---|---|
| F6.1 | **Binding commitment** | Promises a refund/discount/SLA the company must honour | ✅ |
| F6.2 | **Unlicensed advice** | Financial, medical or legal advice | ◐ |
| F6.3 | **Missing AI disclosure** | EU AI Act Art. 50 | ✅ |
| F6.4 | **Adverse action, no reason** | Denial without explanation (FCRA/ECOA) | ✅ |
| F6.5 | **Discriminatory outcome** | Screening bias | ◐ |
| F6.6 | **Decision not recorded** | No auditable basis for a regulated decision | ✅ |

**Built and live since 2026-09-16.** `capabilities/grounding/commitments.py` (commitment detection, AI-disclosure checks, adverse-action reasoning) and `capabilities/grounding/register.py::check_register` (specificity licensed by epistemic standing: *"rates will probably ease"* versus an unearned *"3.25%"*) run on the output surface through `commitment_check` and `disclosure_check` in `capabilities/grounding/checks.py`. Their findings feed the same `Finding` → `Decision` → audit-chain record as F2 and F7. The disclosure and adverse-action checks need the caller to supply the channel or the decision record. **F6.2 stays ◐:** register checks are lexical and licensed per domain; there is no licensed-advice classifier. **F6.5 stays ◐ by design:** `fairness_probe` is an aggregate over a decision population with a 30-observation floor, so it runs on the compliance path; one request cannot show disparate impact. F6.6 (the `Decision` record) was always ✅.

### F7 — Numeric, temporal & entity integrity

| # | Failure mode | Example | Status |
|---|---|---|---|
| F7.1 | **Hallucinated record match** | *The reconciliation incident* | ✅ |
| F7.2 | **Arithmetic / aggregation error** | Sum doesn't match the rows cited | ✅ |
| F7.3 | **Wrong period** | Fiscal vs calendar year | ✅ |
| F7.4 | **Unit / currency error** | USD vs EUR, thousands vs millions | ✅ |
| F7.5 | **Entity confusion** | Right answer, wrong customer | ✅ |
| F7.6 | **Timezone error** | Off-by-one day on a deadline | ◐ |
| F7.7 | **Self-contradiction across turns** | Contradicts its own earlier answer | ✗ |

**Built and live:** `src/agentfox/capabilities/grounding/integrity.py`, run on the request path (`capabilities/grounding/checks.py`) via `assess_integrity(...)` — record-match verification against the system of record, arithmetic/aggregation cross-checks, fiscal-vs-calendar period disambiguation, unit/currency normalization, and entity-confusion detection are all live on the enforcement path, not just unit-tested in isolation. *The reconciliation incident* — hallucinating a matching record — is directly covered.

**F7.6 stays ◐:** what's built detects timezone *ambiguity* in the input (is this date unambiguous across zones), not an actual verified date-shift error against a known-correct value — narrower than "catches off-by-one-day deadline errors."

**F7.7 stays ✗, and there's a real doc bug attached to it.** Cross-turn self-contradiction detection is genuinely absent — nothing tracks an agent's own prior claims to catch it contradicting itself later. The only marker anywhere near this mode, `SelfConsistencyScorer` (in `evaluation/silent_failure.py`, the offline eval/CI-gate module, not the live enforcement path), checks variance *within* one generation across resampled outputs — a related but different problem (nondeterminism, not cross-turn contradiction). `integrity.py`'s own docstring should be checked for any claim that self-consistency covers this; it doesn't, and that's worth correcting independent of whether F7.7 itself gets built.

### F8 — Context & retrieval integrity *(from `PRD.md` — not in the original 50 modes)*

A recurring pattern across F1, F2 and F7 is that the agent has no access to enterprise semantics: which table is authoritative, what the index's coverage window actually is, whether a chunk is coherent. F8 is where that gets enforced structurally, at ingestion and assembly, rather than re-derived per answer.

| # | Failure mode | Example | Status |
|---|---|---|---|
| F8.1 | **Incoherent chunks** | A chunk boundary splits a sentence or a table mid-row | ✅ |
| F8.2 | **Tokeniser / script boundary failures** | `[UNK]` tokens silently corrupt non-Latin text | ◐ |
| F8.3 | **Stale index** | The source document changed; the index that answers from it did not | ✗ **absent** — no `index_freshness` function exists at all. F2.2's `freshness_breach` checks whether a *source* is stale relative to a policy SLA; nothing checks whether the *index* has fallen behind the source it was built from |
| F8.4 | **Context-window truncation drops evidence** | The cited evidence doesn't fit the budget and silently disappears | ◐ |
| F8.5 | **Memory contamination across sessions** | Session B reads a memory written for session A | ✅ |
| F8.6 | **Retrieval quality drift** | nDCG degrades over time and nobody notices | ✅ |
| F8.7 | **Ingestion corruption** | A corrupt or mojibake'd document is ingested and answered from | ✅ |

**Built and live since 2026-09-16.** `capabilities/grounding/context_integrity.py` runs on the `retrieved`, `tool_result` and `memory_write` surfaces through `context_check` in `capabilities/grounding/checks.py`: chunk quality, document quality and decoder damage, memory binding and retrieval drift against a baseline. `POST /provenance/context-check` still exists for a caller who wants to check content directly. **F8.2 stays ◐:** damage is caught where it leaves a trace (U+FFFD, `[UNK]`, latin-1 mojibake); a tokeniser that segments Thai or Khmer badly without leaving one is not. **F8.4 stays ◐ by design:** `assemble_context` repairs as well as reports and needs the retriever's ranked chunks and real token budget, so it is exposed as `Enforcer.assemble_context` for that caller rather than run inside every evaluation.

**F8.3 has no implementation at all.** It is a narrow, well-scoped gap: an `index_freshness` check comparing the index's last-build timestamp against the source system's last-modified timestamp, raising the same `freshness_breach` class F2.2 already uses, measured at the index layer instead of the per-answer layer.

---

## Coverage summary

| Family | Modes | ✅ | ◐ | ✗ | Share of real-world failures |
|---|---|---|---|---|---|
| F1 Answerability & abstention | 6 | 6 | 0 | 0 | high — drives F2/F7 |
| F2 Source authority | 6 | 6 | 0 | 0 | high |
| F3 Destructive actions | 10 | 10 | 0 | 0 | **fastest-growing (+62%)** |
| F4 Entitlement & disclosure | 8 | 7 | 1 | 0 | **highest commercial value** |
| F5 Escalation breakdown | 7 | 6 | 1 | 0 | **31.1% — largest single class** |
| F6 Commitment & liability | 6 | 4 | 2 | 0 | high severity, low frequency |
| F7 Numeric & entity integrity | 7 | 5 | 1 | 1 | high in finance/ops |
| F8 Context & retrieval integrity | 7 | 4 | 2 | 1 | feeds F1/F2/F7 |
| **Total** | **57** | **48** | **7** | **2** | |

F9's five modes are tracked separately below (F9.2 and F9.4 built, F9.3 partial, F9.1 and F9.5 absent).

**Where the generated count differs.** [../status.md](../status.md) counts a mode as covered when its code exists. It therefore counts F4.7, F5.4, F6.5, F7.6, F7.7 and F8.4 as covered, where this table does not: F4.7 has no legal-hold or blackout class proven end to end, F5.4 measures an abstention proxy rather than quality per turn, F6.5 is not a per-request check, F7.6 detects timezone ambiguity rather than a verified date shift, F7.7's only marker is an offline self-consistency scorer, and F8.4 is not run automatically. Quote the generated figure as "code exists for", and this table as "covered on the live path".

The pillars built earlier (taint containment, audit chain, policy engine, computed control status) turned out to be genuine substrate: F1–F5 and most of F7 were built as detectors, policy conditions and scorers inside that architecture. F6 and F8 were the cautionary tale: building the detector was not the hard part, and the last step (one call site) was skipped at first.

---

## The gaps this taxonomy missed — found by an independent audit

[`coverage-map.md`](coverage-map.md) is deliberately built from the architecture of a request (what can go wrong at each layer a message actually passes through) rather than from this document, specifically so scoring ourselves against it isn't circular. It surfaced five failure modes that never appeared in F1–F8 at all. Each gets a concrete detection design below; F9.2 and F9.4 are built, F9.3 is partial, and F9.1 and F9.5 are open.

### F9.1 — Invalid logical inference

**Status: ✗ absent.** No reasoning validator exists (coverage-map L0.4).

*"All A are B, X is B, therefore X is A."* Undistributed middle, affirming the consequent, illicit conversion — an agent reasons its way to a wrong conclusion from premises that were individually true.

**Why an LLM judge doesn't fix this.** Grading reasoning validity with another LLM call inherits the same fallacy the judge is supposed to catch. F7's checkers (arithmetic, aggregation) work *because* they are deterministic and narrow, not because they're smart. The same strategy applies here, at a smaller scope than "judge the argument":

1. **Extract, don't judge.** Reuse the claim-extraction pipeline already built for F2 citation binding and F6.1 commitment detection to pull out claims in a formalizable shape: categorical (`All X are Y`, `Some X are Y`, `No X are Y`, `X is Y`) or simple conditional (`If X then Y`). Extraction is narrower and far less prone to inheriting the reasoning bug than judgment — it is closer to parsing than to reasoning.
2. **Check validity deterministically.** Convert extracted premises/conclusion into set-membership predicates and pattern-match against the small, closed list of known invalid syllogism shapes (undistributed middle, illicit major/minor term, affirming the consequent, denying the antecedent) — a lookup against ~15 canonical invalid forms, not general theorem proving.
3. **Scope tightly, same as F7.** Only fire when premises are explicit and in categorical/conditional form; report nothing rather than guess on informal argument, exactly as F7.2's arithmetic check only fires on an explicit stated total.
4. **Interface:** a new scorer alongside `check_arithmetic` in `integrity.py` (`check_logical_validity`), sharing the extraction step F2/F6 already pay for, registered as a check from the start.

### F9.2 — Sycophancy: agrees with a false premise

**Status: ✅ built and live (2026-09-16)** — `capabilities/grounding/sycophancy.py`, registered as `sycophancy_check` on the output surface. It fires only when the caller supplies a grounded record that contradicts the user's asserted premise and the answer neither corrects it nor drops the wrong value; with no grounded record it is silent, which is what keeps opinions out of it. `tests/capabilities/grounding/test_sycophancy.py` and `tests/runtime/test_control_flow_sycophancy_wiring.py`.

The user asserts something false ("As you know, the deadline is Friday" — it's Tuesday); the model builds its answer on the user's version rather than correcting it. Reasoning fine-tuning is documented to make this *worse*, not better (AbstentionBench), so this isn't a problem model upgrades will quietly fix.

**Detection design**, reusing infrastructure that already exists and is already live:

1. **Extract the user-asserted factual claim** from the turn — same extractor as F9.1 and F2's citation binding, run against the user message instead of the model's response.
2. **Check it against grounded sources** using `assess_provenance`'s source-tier machinery, already on the request path: does a tier-1 source contradict the user's stated value?
3. **Classify the model's handling**, deterministically: does the response contain a correction/caveat token set (*"actually"*, *"to clarify"*, *"that's not quite right"*, *"I show a different date"*) **and** restate the source-grounded value? If the contradiction exists and neither is present, flag `SYCOPHANCY.PREMISE_UNCORRECTED`.
4. **Precondition, to avoid false positives:** only fires when there is a checkable grounded source — same boundary F2/P8 already enforce. Opinions and genuinely ungrounded matters never trigger it.

### F9.3 — Answer quality degrades in non-English

**Status: ◐ partially closed (2026-09-16)** — the deterministic half is done, exactly as the design below proposed: `integrity.py`'s arithmetic, aggregation, period, deadline, scale, currency and entity checks now read localised number and date formats, taking parity on matched pairs from **6/19 to 19/19** with an English false-positive rate of 0.097% across 4,138 texts ([`benchmarks/multilingual/`](../../benchmarks/multilingual/README.md)). Ambiguous dates are reported, never guessed. **Still open:** the answerability/abstention path is English-only (English 2/3, every other language 1/3), and benign non-English text is flagged by the injection detectors more often than English.

Correct in English, subtly wrong in German — and nothing currently measures this at all; detectors are multilingual for *injection* (4/4 languages caught) but nothing checks whether **answer quality** holds up per language.

**Detection design — reframe as a parity problem, not a quality-grading problem:**

1. Don't build a new "is this answer good in Polish" grader — that's the kind of subjective LLM-judged check this codebase avoids elsewhere. Instead, extend the **existing, live F7 checkers** (arithmetic, date/period, currency/unit, entity match in `integrity.py`) to parse non-English number and date formats (`1.234,56` vs `1,234.56`; `DD.MM.YYYY` vs `MM/DD/YYYY`; non-Latin numerals) so the same checks that already run in English on every live request run correctly in the target languages too.
2. Run the existing eval/red-team suite (P4) in parallel across English and N target languages on matched prompts, and add a **cross-lingual parity scorer**: report divergence in pass rate between English and each other language as a drift signal, the way P4 already reports drift over time (PSI/KS).
3. This turns "is quality worse in German" (hard, subjective) into "do the same deterministic checks fire more often in German because a parser is English-only" (tractable, and each divergence points at a specific parser to fix).

### F9.4 — Gradual multi-turn manipulation (crescendo)

**Status: ✅ built and live (2026-09-16)** — `capabilities/detection/trajectory.py`'s `CRESCENDO.TRAJECTORY_DRIFT`, wired into `Enforcer.check_conversation_window` (`runtime/enforcement/surfaces.py`) exactly as the design below specifies: a rolling window over sub-threshold detector activations, topic drift and reframing markers, firing on the *slope* rather than any single turn. Measured in [`benchmarks/crescendo/`](../../benchmarks/crescendo/README.md): **10/13 crescendo conversations caught, all before the final turn (median turn 3), with 0/9 benign controls flagged** — against 0/13 before. The three misses are gradual topic drift with no reframing language, which is the honest residual. Adds ~4ms per governed turn. Observe-first, blockable with one policy rule on the `action_risk` channel.

Each individual turn is innocuous; the trajectory across turns is not. Every injection detector scores one message at a time, so a crescendo attack never crosses a per-message threshold.

**Detection design — reuse trajectory scoring already built for a different purpose:**

`escalation.py`/P13 already measure trajectory against a recorded baseline (goal drift for handoff fidelity: *"retained 0.00 of the brief, losing ['limit', 'prohibition']"*), live on the request-recording path via `frameworks/autoguard/`. Crescendo detection is the same primitive pointed at a different baseline:

1. At each turn, alongside the existing per-message detector run, record a **risk-adjacent score**: sub-threshold detector activations (findings that scored below the block threshold but above zero), embedding-distance drift from turn 1's topic to the current turn, and reframing markers (*"just hypothetically"*, *"for a story"*, *"as a thought experiment"*) known as crescendo scaffolding.
2. Maintain this as a rolling window (last 5–8 turns) rather than a cumulative score, so a conversation that drifts and then genuinely resolves isn't penalized forever.
3. Fire `CRESCENDO.TRAJECTORY_DRIFT` when the **slope** of the risk-adjacent score over the window crosses a threshold, independent of whether any single turn crossed the per-message block threshold.
4. **Interface:** extends the trajectory-measurement primitive already wired into the per-turn recording path, the same integration point F5 uses.

### F9.5 — Context stuffing to push out the system prompt

**Status: ✗ absent** (coverage-map L1.9).

Megabytes of filler before the real instruction, diluting or displacing the system prompt's authority. This sits inside F8's territory (context-budget governance, P14-6).

**Detection design — extend the assembly-stage check `context_integrity.py` already performs:**

1. `assemble_context` already tags tokens by provenance via the same taint machinery built for P3-4 (system-authored vs. user-supplied vs. retrieved). Reuse that tagging rather than building new classification.
2. Add a second guarantee alongside "cited evidence is seated before ranking" (F8.4): compute the ratio of system/policy/tool-schema tokens to total assembled context, and flag `CONTEXT.AUTHORITY_DILUTED` when that ratio drops below a floor (e.g. system-prompt share under 2% of the assembled window).
3. Separately, flag `CONTEXT.SINGLE_TURN_STUFFING` when one low-provenance turn (a user message or a single retrieved document) contributes more than a fixed token threshold in one shot.
4. **Where it runs:** `assemble_context` is not run on every evaluation (F8.4), so the authority-share check belongs in `context_check`, which is, using the token tags it already has.

---

## When AgentFox itself fails — platform failure modes

F1–F9 are how the *governed agent* fails. How AgentFox degrades when one of its own parts cannot
do its job is in the [high-level design §6.2](../architecture/high-level-design.md#62-fail-modes).

---

## What this implies for the build

Highest-leverage items first:

1. **F7.7 — cross-turn self-contradiction**, and **F8.3 — stale index.** Both are real, scoped, moderate-effort builds: a claim-history store with a contradiction check for F7.7, an `index_freshness` check reusing F2.2's `freshness_breach` shape for F8.3.
2. **F9.1 and F9.5**, and the open half of F9.3 (answerability outside English). F9.1 maps onto the F2/F6 extraction pipeline; F9.5 onto `context_check`.
3. **Firm up the remaining partials** (F4.7 named legal-hold class, F5.4 real quality-trend detection, F6.2 a licensed-advice classifier, F7.6 verified date shift rather than ambiguity, F8.2's damage-marker dependency). Each is a bounded extension of a mechanism already on the request path.

The four-family framing from the original document (F4 entitlement, F3 action semantics, F1 answerability, F2 source authority) is **built and live**, and F5 joined them. Those are the differentiators to defend and demo, not the backlog.

---

## Sources

[Morningstar/PR Newswire — enterprise AI failures shifting beyond hallucinations (ChatSee, 10k+ events)](https://www.prnewswire.com/news-releases/new-research-finds-enterprise-ai-failures-are-shifting-beyond-hallucinations-as-companies-move-from-chatbots-to-agents-302837907.html) · [AI Incidents H1 2026 retrospective](https://www.digitalapplied.com/blog/ai-incidents-h1-2026-retrospective-failure-modes-analysis) · [Enterprise AI agent failure modes](https://thoughtminds.ai/blog/enterprise-ai-agent-failure-modes) · [AI agent production failures — enterprise lessons](https://www.openempower.com/blog/ai-agent-production-failures-enterprise-lessons-2026)

[M365 Copilot oversharing — what IAM and data teams must fix](https://nhimg.org/community/cybersecurity-beyond-identity/microsoft-365-copilot-oversharing-what-iam-and-data-teams-must-fix/) · [Copilot didn't overshare your data, your permissions did](https://petri.com/copilot-didnt-overshare-your-data-your-permissions-did/) · [Microsoft — mitigate oversharing for Copilot and agents](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/mitigate-oversharing-to-govern-microsoft-365-copilot-and-agents/4448744)

[Protect production SQL databases from agentic query risks](https://rietta.com/blog/ai-sql-database-data-protection-read-replica/) · [Production-ready text-to-SQL: 9 problems with fixes](https://atalupadhyay.wordpress.com/2026/07/01/building-a-production-ready-text-to-sql-ai-agent-9-problems-with-fixes/) · [AI agent database wipe — lessons](https://www.mindstudio.ai/blog/ai-agent-database-wipe-disaster-lessons/) · [Testing SQL agents — safety & query validation](https://langwatch.ai/scenario/testing-guides/sql-agent/)

[AbstentionBench — reasoning LLMs fail on unanswerable questions](https://arxiv.org/html/2506.09038v1) · [Know Your Limits — a survey of abstention in LLMs (TACL)](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00754/131566/Know-Your-Limits-A-Survey-of-Abstention-in-Large) · [The unexpected downside of RAG — over-refusal](https://www.bohrium.com/en/blog/research-notes/aaai-2026-retrieval-augmented-models-dont-know/)
