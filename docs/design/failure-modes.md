# Business Failure-Mode Analysis — where deployed agents actually break

**Companion to [gap-analysis.md](gap-analysis.md).** That document benchmarked us against vendor feature lists. This one benchmarks us against **how enterprise agents actually fail in production** — which turns out to be a very different, and more useful, target.

**Current figures** (tests, lines, failure modes covered) are generated into [../status.md](../status.md); the dated updates below record what was true on their date.

**Update, 2026-08-29:** the taxonomy below was written 2026-08-18 against an 18.7k-LOC codebase that covered 1 of 50 modes. Since then the codebase grew to 50k+ LOC / 1,131 tests, and a grep/execution-verified re-audit (methodology unchanged: every status below is either a passing test, a direct code citation, or an explicit import-graph check — not an inference) found **40 of 50 original modes now ✅, 3 ◐, 5 ◐-unwired, 2 still ✗** (F3.8 composed privilege escalation, F7.7 cross-turn self-contradiction). One status appears for the first time: **◐-unwired** — real, unit-tested logic that is never imported or called from the live enforcement path (`enforcement.py`, `gateway/app.py`, `guardrails/pipeline.py`, or any gateway route reachable on the inline request), so it does nothing for a production request today despite passing its own tests. That is a distinct, worse state than a normal ◐ partial, and it applies to all of F6 (F6.1–F6.5).

Two further corrections on top of that re-audit, done independently and cross-checked against it line by line:

- **F8, added below, is new** — a seventh capability area from `PRD.md`'s taxonomy (context & retrieval integrity) that was never in the original 50 modes. Checking its wiring the same way as F6 found the **same unwired pattern**: the module (`context_integrity.py`) works — coverage-map.md's execution probes call its functions directly and get correct results — but it is reachable in production only via an opt-in `POST /provenance/context-check` endpoint, never automatically on the inline gateway path. It gets the same `◐-unwired` treatment as F6.
- **F9, added below, is genuinely new** — five failure modes that no version of this taxonomy, and no version of `PRD.md`, ever listed. They came from [`coverage-map.md`](coverage-map.md), an audit built from the architecture of a request rather than from this document, specifically to avoid the circularity of only checking what we set out to check. Each gets a concrete detection design, not the one-line "what's needed" prose this document used to carry — this is the actual answer to "what hasn't been picked up yet."

**Update, 2026-08-30:** F3.8 (composed privilege escalation) moved from ✗ to ✅. `guardrails/composition.py` (P9-11) reused the taint tracker's existing `TaintMark.propagated_from` provenance (P3-4, already recorded which tool produced a value — it just wasn't being compared against tool scope) to detect a lower-impact tool's output silently feeding a higher-impact tool's argument. Wired into `enforcement.py::evaluate()` on the live `guard_tool_call` path and exercised end-to-end (not `◐-unwired`) by `tests/capabilities/detection/test_composition.py`, including a negative control. F3 is now fully covered (10/10); F3.8 was the last open mode in the family the audit called its "fastest-growing (+62%)."

**Update, 2026-09-16 — F6/F8 wired, and two newly-covered modes.** The `◐-unwired` pattern is closed: `Enforcer.evaluate()` now calls `_commitment_checks()` (F6.1–F6.4, output surface) and `_context_checks()` (F8.1, F8.2, F8.5, F8.6, F8.7 on the `retrieved`, `tool_result` and `memory_write` surfaces), folding their findings into the same `evidence_issues` → `Finding` → `Decision` → audit-chain record the F2/F7 checks already use, so verdicts, `rules_fired` and the audit trail behave identically — exercised end-to-end through the real path by `tests/runtime/test_commitment_and_context_wiring.py` (37 tests: each detector, a negative control for each, and proof the default verdict is still `allow`), at a measured cost of +0.17ms on a typical response against the 300ms budget, bounded at ~16ms by a 32KB scan cap. Findings are recorded and surfaced but never block on their own: blocking is reachable only by writing a policy rule against the existing `action_risk` condition (`when: {surface: [output], action_risk: "commitment.*"}`), which is the observe-first stance holding rather than a gap. Two modes stay ◐ by design, not by omission: **F6.5** (`fairness_probe` is an aggregate over a decision population with a 30-observation floor — a single request cannot exhibit disparate impact, so it belongs to the compliance/eval path) and **F8.4** (`assemble_context` repairs as well as reports and needs the retriever's ranked chunks and real token budget, so it is exposed as `Enforcer.assemble_context` for that caller rather than simulated inside `evaluate()`). F8.3 (stale index) is unaffected and remains the one mode with no implementation at all.

Shipped in the same cycle: **F9.4 (crescendo) moves ✗ → ✅** (`trajectory.py`, 10/13 caught with zero control false positives — see its benchmark), **F9.2 (sycophancy) moves ✗ → ✅** (`sycophancy.py`, wired on the output surface, gated on a caller-supplied grounded record), and a mode no version of this taxonomy listed — **control-flow integrity** (`control_flow.py`), which catches an injected *step* rather than a poisoned *value*: a tool call whose every argument is legitimately user-sourced, but whose existence traces to untrusted content the agent read. Both are recorded-not-blocking by default and blockable with one policy rule against `action_risk`, the same channel F6/F8 use.

---

## The finding that reframes the roadmap

A study of **10,000+ AI failure events** (ChatSee, published Jul 2026) found:

| Failure class | Share |
|---|---|
| **Resolution / escalation breakdowns** | **31.1%** |
| Execution and action failures | **up 62%** vs Q2-2024 baseline |
| **Hallucination-related** | **< 10%** |

Supporting figures: **88% of organisations had at least one AI agent security incident in 2025**; only **~10% of agent pilots reach production**; **fewer than 25%** of enterprises running multi-agent pilots report confidence in reliability or governance.

**What this meant for us at the time (2026-08-18):** our Pillar 4 flagship — silent-failure detection — was aimed at the **smallest** slice of the problem, while we had **nothing at all** for the 31% (escalation breakdown) or the fastest-growing category (execution/action). That gap is now substantially closed — see the 2026-08-29 update above and the coverage summary — but the taxonomy itself, and the reasoning for why it's the right one to govern against, hasn't changed.

The rest of this document is the failure taxonomy we should actually be governing.

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

Legend: ✅ covered and live on the request path · ◐ partial, real but narrower than the claim · ◐-unwired real logic, individually tested, but never imported/called from the live enforcement path · ✗ absent (all verified against the codebase, 2026-08-29, by test citation, code citation, or import-graph check).

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

**Built and live:** `src/agentfox/capabilities/grounding/answerability.py`, imported into `enforcement.py` — a declared knowledge boundary per agent (systems of record, time range, entity scope, answerable question types), a pre-flight answerability classifier that routes unanswerable questions to templated abstention before generation, and a post-flight check that the answer stayed inside the declared boundary. All six modes have passing tests and run on a live request, not just in isolation.

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

**Built and live:** `src/agentfox/capabilities/grounding/provenance.py`, imported into `enforcement.py` via `assess_provenance(...)` — every retrieved chunk carries a source tier (system-of-record / approved / unverified / external), freshness, and owner. Policy is expressed as e.g. *"financial figures may only be sourced from tier-1 systems of record less than 24h old."* Citation binding checks that each material claim maps to a chunk that actually supports it, catching fabricated citations and silent picks between contradictory sources — this turns the old groundedness-only scorer into an enforceable control, not just a lab metric. Remaining seam, not a gap in the table above: `P8-9`, ingesting third-party catalog/lineage metadata (DataHub, OpenMetadata, Unity Catalog) so source tier and ownership can be *derived* rather than hand-declared per agent.

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

**Built and live:** `src/agentfox/capabilities/detection/actions.py`, `enforcement.py`, `effects.py` — a deterministic action-semantics analyser, using sqlglot AST parsing (not an LLM checking its own SQL), classifies generated SQL into operation, targets, estimated affected rows, reversibility, and environment; detects tautology-as-unbounded-`WHERE`, stacked-statement and comment evasion; enforces environment binding on the tool target; and gates irreversible actions on state read back from the system of record rather than the model's assertion. This is the fastest-growing failure class (+62%) and the one that makes the news — now the most completely covered family bar one mode.

**F3.8 moved to ✅, built on top of infrastructure that already existed for a different purpose.** `sql.privilege_change` in `actions.py` fires on `GRANT`/`REVOKE` statements, which is a real but narrow slice of "privilege escalation" — F3.8's own example is broader: a read tool's output chained into a write/authorization boundary neither tool alone permits (e.g. a read tool surfaces an internal ID that a second, differently-scoped tool then accepts as if it were user-supplied and authorized). The taint tracker (`guardrails/taint.py`, P3-4) already recorded exactly the fact this needed — `TaintMark.propagated_from`, which tool's result a later argument's value was inferred from — it just wasn't being compared against tool scope. `guardrails/composition.py` (P9-11) adds that one comparison: resolve the producing tool's registered `Tool.impact`, compare it against the consuming tool's, and block when a lower-impact tool's output silently feeds a higher-impact one. Wired into `enforcement.py::evaluate()` on the live `guard_tool_call` path (not `◐-unwired` — `tests/capabilities/detection/test_composition.py` exercises it end-to-end through `McpGovernor`, including a negative control proving independently-supplied arguments aren't falsely flagged). Also a real caveat inside the built modes: F3.9 cascade analysis is only as good as the trigger declarations it is given — an undeclared webhook stays invisible.

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

**Built and live:** `src/agentfox/capabilities/grounding/entitlement.py`, `src/agentfox/core/tenancy.py`, imported into `enforcement.py` — the end-user principal is propagated through the agent to retrieval and tools; responses are checked against what that principal is entitled to see; over-permissioned retrieval (agent could reach more than the caller) is detected; tenant isolation is enforced structurally at the session level via `with_loader_criteria` rather than per-query filters. This remains the single highest-value gap commercially — it is the reason Copilot rollouts stall — and it is now a genuine strength, not a plan. The one declared seam: `P10`'s OpenFGA adapter is a stub, not a live integration.

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

**Built and live:** `src/agentfox/capabilities/containment/escalation.py`, wired via `autoguard.py`'s per-turn recording (retrospective by design — missed-escalation detection can only be judged over a conversation, not a single message) — a per-agent escalation policy (conditions that must trigger hand-off: low confidence, repeated failure, user frustration, out-of-scope, regulated topic), counterfactual detection ("this should have escalated, and didn't"), context-complete hand-off packages, and owner + SLA tracking on the queue. The dashboard's hand-off queue reads from this directly.

**F5.4 stays ◐:** what's measured is a turn-depth-correlated abstention-rate proxy, not an actual quality-trend measurement against ground truth — a real signal, but not the same claim as "we detect the conversation getting worse."

### F6 — Commitment, advice & liability

| # | Failure mode | Example | Status |
|---|---|---|---|
| F6.1 | **Binding commitment** | Promises a refund/discount/SLA the company must honour | ◐-unwired |
| F6.2 | **Unlicensed advice** | Financial, medical or legal advice | ◐-unwired |
| F6.3 | **Missing AI disclosure** | EU AI Act Art. 50 | ◐-unwired |
| F6.4 | **Adverse action, no reason** | Denial without explanation (FCRA/ECOA) | ◐-unwired |
| F6.5 | **Discriminatory outcome** | Screening bias | ◐-unwired |
| F6.6 | **Decision not recorded** | No auditable basis for a regulated decision | ✅ |

**Built but not wired — this whole family needs a distinct call-out.** `src/agentfox/capabilities/grounding/commitments.py` implements real, individually-tested logic for F6.1, F6.3–F6.5 (commitment detection, AI-disclosure checks, adverse-action/ECOA reasoning, `fairness_probe`/`FairnessResult` for disparate impact). F6.2's dedicated implementation is separate and more sophisticated than a keyword lexicon: `src/agentfox/capabilities/grounding/register.py`'s `check_register` — *"specificity licensed by epistemic standing,"* the same mechanism that distinguishes *"rates will probably ease"* from an unearned *"3.25%,"* and explicitly names medicine/law/finance as domains where the line is instruction, not accuracy. Every one of these passes its own unit tests. **Verified by import graph: nothing in `src/agentfox/` imports `commitments.py` or calls `check_register(` anywhere outside `register.py` itself** — not `enforcement.py`, not `guardrails/pipeline.py`, not any gateway route. A production request today gets zero benefit from F6.1–F6.5, despite the modules existing and being correct in isolation. Worse than a normal ◐ partial (partial coverage on a live path), better than ✗ (no logic exists) — the fix is "wire five already-written detectors into the pipeline," not "design and build five new controls." F6.6 (audit chain, via the `Decision` model) is unaffected — it was already wired broadly across the codebase and remains ✅.

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

**Built and live:** `src/agentfox/capabilities/grounding/integrity.py`, imported into `enforcement.py` via `assess_integrity(...)` — record-match verification against the system of record, arithmetic/aggregation cross-checks, fiscal-vs-calendar period disambiguation, unit/currency normalization, and entity-confusion detection are all live on the enforcement path, not just unit-tested in isolation. *The reconciliation incident* — hallucinating a matching record — is directly covered.

**F7.6 stays ◐:** what's built detects timezone *ambiguity* in the input (is this date unambiguous across zones), not an actual verified date-shift error against a known-correct value — narrower than "catches off-by-one-day deadline errors."

**F7.7 stays ✗, and there's a real doc bug attached to it.** Cross-turn self-contradiction detection is genuinely absent — nothing tracks an agent's own prior claims to catch it contradicting itself later. The only marker anywhere near this mode, `SelfConsistencyScorer` (in `evaluation/silent_failure.py`, the offline eval/CI-gate module, not the live enforcement path), checks variance *within* one generation across resampled outputs — a related but different problem (nondeterminism, not cross-turn contradiction). `integrity.py`'s own docstring should be checked for any claim that self-consistency covers this; it doesn't, and that's worth correcting independent of whether F7.7 itself gets built.

### F8 — Context & retrieval integrity *(from `PRD.md` — not in the original 50 modes)*

A recurring pattern across F1, F2 and F7 is that the agent has no access to enterprise semantics: which table is authoritative, what the index's coverage window actually is, whether a chunk is coherent. F8 is where that gets enforced structurally, at ingestion and assembly, rather than re-derived per answer — in principle. In practice it has the same wiring problem as F6.

| # | Failure mode | Example | Status |
|---|---|---|---|
| F8.1 | **Incoherent chunks** | A chunk boundary splits a sentence or a table mid-row | ◐-unwired |
| F8.2 | **Tokeniser / script boundary failures** | `[UNK]` tokens silently corrupt non-Latin text | ◐-unwired |
| F8.3 | **Stale index** | The source document changed; the index that answers from it did not | ✗ **absent** — no `index_freshness` function exists at all. F2.2's `freshness_breach` checks whether a *source* is stale relative to a policy SLA; nothing checks whether the *index* has fallen behind the source it was built from |
| F8.4 | **Context-window truncation drops evidence** | The cited evidence doesn't fit the budget and silently disappears | ◐-unwired |
| F8.5 | **Memory contamination across sessions** | Session B reads a memory written for session A | ◐-unwired |
| F8.6 | **Retrieval quality drift** | nDCG degrades over time and nobody notices | ◐-unwired |
| F8.7 | **Ingestion corruption** | A corrupt or mojibake'd document is ingested and answered from | ◐-unwired |

**Built but not wired, same pattern as F6 — and less visible, because it's reachable at all.** `src/agentfox/capabilities/grounding/context_integrity.py` genuinely works: `coverage-map.md`'s execution probes call `chunk_quality`, `document_quality`, `assemble_context`, `memory_binding_breach` and `retrieval_drift` directly and get correct, specific results (split-sentence detection, mojibake scoring, salience reordering, principal-mismatch detection). But **verified by import graph: `context_integrity.py` is never imported by `enforcement.py` or any automatic gateway middleware.** Its only production reachability is `POST /provenance/context-check` (`gateway/routes/provenance.py`) — an endpoint a caller must separately invoke on their content. A normal chat/completion request through the inline gateway proxy gets **none** of F8's protections automatically. This is a materially more serious version of the F6 problem: F6 is at least architecturally adjacent to where it would be wired (the pipeline that already runs answerability/provenance/integrity checks); F8 sits entirely outside the automatic request path today.

**F8.3 is the one mode across all 57 catalogued modes that doesn't even have a built-but-unwired implementation.** It is a narrow, well-scoped gap regardless of the wiring question: an `index_freshness` check comparing the index's last-build timestamp against the source system's last-modified timestamp, raising the same `freshness_breach` class F2.2 already uses, measured at the index layer instead of the per-answer layer.

---

## Coverage summary

| Family | Modes | ✅ | ◐ | ◐-unwired | ✗ | Share of real-world failures |
|---|---|---|---|---|---|---|
| F1 Answerability & abstention | 6 | 6 | 0 | 0 | 0 | high — drives F2/F7 |
| F2 Source authority | 6 | 6 | 0 | 0 | 0 | high |
| F3 Destructive actions | 10 | 10 | 0 | 0 | 0 | **fastest-growing (+62%)** |
| F4 Entitlement & disclosure | 8 | 7 | 1 | 0 | 0 | **highest commercial value** |
| F5 Escalation breakdown | 7 | 6 | 1 | 0 | 0 | **31.1% — largest single class** |
| F6 Commitment & liability | 6 | 1 | 0 | 5 | 0 | high severity, low frequency |
| F7 Numeric & entity integrity | 7 | 5 | 1 | 0 | 1 | high in finance/ops |
| F8 Context & retrieval integrity | 7 | 0 | 0 | 6 | 1 | feeds F1/F2/F7 |
| **Total** | **57** | **41** | **3** | **11** | **2** | |

**41 of 57 modes were covered live when this table was last counted by hand, on 2026-08-30.** The current figure is computed, not hand-counted: [docs/status.md](../status.md) reports 54 of 57 outright and 2 partial. Where the two disagree, the computed one is right and this table is behind.

The rest of this section is the 2026-08-30 snapshot (was 1 of 50 on 2026-08-18, before F8 existed in this taxonomy; 40 of 57 as of 2026-08-29, before F3.8 was built). Two modes are genuinely absent — F7.7 (cross-turn self-contradiction) and F8.3 (stale index) — real, scoped gaps worth building next, not oversights. Four are honest partials (F4.7 MNPI/legal-hold class untested by name, F5.4 turn-depth proxy rather than true quality-trend detection, F7.6 timezone ambiguity rather than verified date-shift detection). **Eleven — all of F6 except F6.6, and all of F8 except F8.3 — are the `◐-unwired` pattern:** real, individually-tested modules that nothing in the live request path ever calls. That's the highest-leverage remaining fix in this whole document: for eleven of the seventeen non-fully-covered modes, the detection logic already exists and is already correct.

The pillars built earlier (taint containment, audit chain, policy engine, computed control status) turned out to be genuine substrate — F1–F5 and most of F7 were built as detectors, policy conditions, and scorers inside that same architecture, which is why coverage moved this far this fast. The `◐-unwired` pattern in F6 and F8 is the same lesson from the other direction: building the detector was not the hard part; the last step — one import and one call site — kept getting skipped.

---

## The gaps this taxonomy missed — found by an independent audit

[`coverage-map.md`](coverage-map.md) is deliberately built from the architecture of a request (what can go wrong at each layer a message actually passes through) rather than from this document, specifically so scoring ourselves against it isn't circular. It surfaced five failure modes with **zero coverage, built or unbuilt**, that never appeared in F1–F8 at all. These are the actual "not yet picked up" items — not F6/F8's unwired-but-built modes above — and each gets a concrete detection design below.

### F9.1 — Invalid logical inference

*"All A are B, X is B, therefore X is A."* Undistributed middle, affirming the consequent, illicit conversion — an agent reasons its way to a wrong conclusion from premises that were individually true.

**Why an LLM judge doesn't fix this.** Grading reasoning validity with another LLM call inherits the same fallacy the judge is supposed to catch. F7's checkers (arithmetic, aggregation) work *because* they are deterministic and narrow, not because they're smart. The same strategy applies here, at a smaller scope than "judge the argument":

1. **Extract, don't judge.** Reuse the claim-extraction pipeline already built for F2 citation binding and F6.1 commitment detection to pull out claims in a formalizable shape: categorical (`All X are Y`, `Some X are Y`, `No X are Y`, `X is Y`) or simple conditional (`If X then Y`). Extraction is narrower and far less prone to inheriting the reasoning bug than judgment — it is closer to parsing than to reasoning.
2. **Check validity deterministically.** Convert extracted premises/conclusion into set-membership predicates and pattern-match against the small, closed list of known invalid syllogism shapes (undistributed middle, illicit major/minor term, affirming the consequent, denying the antecedent) — a lookup against ~15 canonical invalid forms, not general theorem proving.
3. **Scope tightly, same as F7.** Only fire when premises are explicit and in categorical/conditional form; report nothing rather than guess on informal argument, exactly as F7.2's arithmetic check only fires on an explicit stated total.
4. **Interface:** a new scorer alongside `check_arithmetic` in `integrity.py` (`check_logical_validity`), sharing the extraction step F2/F6 already pay for — and, unlike F6's detectors, worth wiring at build time rather than building-then-forgetting.

### F9.2 — Sycophancy: agrees with a false premise

**Status: ✅ built and live (2026-09-16)** — `sycophancy.py`, called from `Enforcer.evaluate()` on the output surface. It fires only when the caller supplies a grounded record that contradicts the user's asserted premise and the answer neither corrects it nor drops the wrong value; with no grounded record it is silent, which is what keeps opinions out of it. `tests/capabilities/grounding/test_sycophancy.py` and `tests/runtime/test_control_flow_sycophancy_wiring.py`.

The user asserts something false ("As you know, the deadline is Friday" — it's Tuesday); the model builds its answer on the user's version rather than correcting it. Reasoning fine-tuning is documented to make this *worse*, not better (AbstentionBench), so this isn't a problem model upgrades will quietly fix.

**Detection design**, reusing infrastructure that already exists and is already live:

1. **Extract the user-asserted factual claim** from the turn — same extractor as F9.1 and F2's citation binding, run against the user message instead of the model's response.
2. **Check it against grounded sources** using `assess_provenance`'s source-tier machinery, already wired into `enforcement.py`: does a tier-1 source contradict the user's stated value?
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

**Status: ✅ built and live (2026-09-16)** — `trajectory.py`'s `CRESCENDO.TRAJECTORY_DRIFT`, wired into `Enforcer.check_conversation_window` exactly as the design below specifies: a rolling window over sub-threshold detector activations, topic drift and reframing markers, firing on the *slope* rather than any single turn. Measured in [`benchmarks/crescendo/`](../../benchmarks/crescendo/README.md): **10/13 crescendo conversations caught, all before the final turn (median turn 3), with 0/9 benign controls flagged** — against 0/13 before. The three misses are gradual topic drift with no reframing language, which is the honest residual. Adds ~4ms per governed turn. Observe-first, blockable with one policy rule on the `action_risk` channel.

Each individual turn is innocuous; the trajectory across turns is not. Every injection detector scores one message at a time, so a crescendo attack never crosses a per-message threshold.

**Detection design — reuse trajectory scoring already built for a different purpose:**

`escalation.py`/P13 already measure trajectory against a recorded baseline (goal drift for handoff fidelity: *"retained 0.00 of the brief, losing ['limit', 'prohibition']"*), live on the request-recording path via `autoguard.py`. Crescendo detection is the same primitive pointed at a different baseline:

1. At each turn, alongside the existing per-message detector run, record a **risk-adjacent score**: sub-threshold detector activations (findings that scored below the block threshold but above zero), embedding-distance drift from turn 1's topic to the current turn, and reframing markers (*"just hypothetically"*, *"for a story"*, *"as a thought experiment"*) known as crescendo scaffolding.
2. Maintain this as a rolling window (last 5–8 turns) rather than a cumulative score, so a conversation that drifts and then genuinely resolves isn't penalized forever.
3. Fire `CRESCENDO.TRAJECTORY_DRIFT` when the **slope** of the risk-adjacent score over the window crosses a threshold, independent of whether any single turn crossed the per-message block threshold.
4. **Interface:** extends the trajectory-measurement primitive already wired into the per-turn recording path — the same integration point F5 uses, which is exactly why F5 ended up fully live while F6/F8 didn't: it had a natural per-turn hook to attach to.

### F9.5 — Context stuffing to push out the system prompt

Megabytes of filler before the real instruction, diluting or displacing the system prompt's authority. This sits inside F8's territory (context-budget governance), which raises the wiring question directly: building this without first wiring F8 into the live path would be a sixth unwired module in that family, not a seventh.

**Detection design — extend the assembly-stage check `context_integrity.py` already performs, once F8 is wired:**

1. `assemble_context` already tags tokens by provenance via the same taint machinery built for P3-4 (system-authored vs. user-supplied vs. retrieved). Reuse that tagging rather than building new classification.
2. Add a second guarantee alongside "cited evidence is seated before ranking" (F8.4): compute the ratio of system/policy/tool-schema tokens to total assembled context, and flag `CONTEXT.AUTHORITY_DILUTED` when that ratio drops below a floor (e.g. system-prompt share under 2% of the assembled window).
3. Separately, flag `CONTEXT.SINGLE_TURN_STUFFING` when one low-provenance turn (a user message or a single retrieved document) contributes more than a fixed token threshold in one shot.
4. **Sequencing matters here more than for F9.1–F9.4:** this mode's detection logic is cheap to add, but it inherits F8's wiring problem by construction — it belongs in the same commit that wires `context_integrity.py` into `enforcement.py`, not before it.

---

## When AgentFox itself fails — platform failure modes

F1–F9 are how the *governed agent* fails. This section is the other side: how AgentFox
degrades when one of its own parts cannot do its job. The rule throughout is that "could not
check" is never recorded as "nothing there", and that every degradation is either visible in
a decision, a finding or a refusal, never silent. Each row is verified against the code named.

| Failure | What happens | Where |
|---|---|---|
| **A stored policy version no longer validates** (saved before a rule became mandatory, or before a field was tightened) | Every stored version loads through one function. A missing protected rule is restored from the shipped pack, with a warning once per version. Anything else raises `UnloadablePolicyVersion`; the other packs are still evaluated, and the decision records a `policy.unloadable` rule. A pack bound in observe never blocks; one bound in enforce blocks if the deployment's `fail_mode` or the pack's declared `fail_mode` is `closed`, and otherwise the call is allowed with the gap named. Promoting an unloadable version answers 422. | `policy/store.py:load_version_document`, `runtime/enforcement/enforcer.py` |
| **Detectors time out or error** | Recorded per run on `detector_runs.status`; the decision is taken under the same two fail-mode sources and says so. | `detection/pipeline.py`, `runtime/availability.py` |
| **A monitor run fails** (GitHub down, token revoked, spec unreachable, URL refused by the outbound guard) | The run is recorded `failed` with its error; it closes no finding and keeps the previous baseline. After `monitor_failure_threshold` (default 3) consecutive failures one `monitor_failing` finding opens (medium), and the next successful run closes it. A run that read nothing it understood (an empty spec where there were operations, a repository scan that was inconclusive) is `inconclusive`: baseline kept, nothing closed. | `monitoring/service.py:run_monitor`, `_record_failure` |
| **A probe target is unreachable or does not speak the contract** | Each probe is scored `error`, never `contained`: errors are counted in the campaign and neither open nor close a finding. A target whose URL host no longer matches the host registered at opt-in, or that resolves to a refused address, is refused before anything is sent. A deleted target fails its monitor run; a target not opted in, or live probes turned off, makes the run `inconclusive`. | `evaluation/live_probes.py`, `monitoring/service.py:_run_deployed_agent` |
| **The cron is not configured** | `/api/internal/jobs/run` answers 503 until `AGENTFOX_CRON_SECRET` or `CRON_SECRET` is set, and nothing periodic runs: no monitors, probes, canary advancement, drift checks or escalation scans. The GitHub Actions workflow without its two secrets says so and exits successfully. The Vercel cron alone fires once a day. Self-hosted deployments run `agentfox admin jobs run-due` from their own scheduler. | `gateway/routes/jobs.py`, `.github/workflows/monitors.yml`, `jobs/scheduler.py` |
| **Slack is configured but egress is off** | Nothing is sent, and the gateway logs once that a channel is configured while `AGENTFOX_ALLOW_EGRESS=false`. A delivery that fails is retried once on a 5xx, timeout or connection error, then logged and dropped; a full queue (500) drops the message; a tenant channel that cannot be decrypted is skipped. None of this fails the run that raised the finding. | `monitoring/alerts.py` |
| **The GitHub push webhook cannot be verified** | No secret configured: 503 and nothing queued. A bad signature: 401. A verified push whose rescan cannot run after the response (a host that freezes the process) leaves a queued job the next cron run picks up. | `gateway/routes/integrations.py:github_webhook` |
| **The gateway is started without real secrets** | Outside a development environment the process refuses to start while `AGENTFOX_SERVICE_AUTH_SECRET` or `AGENTFOX_AUDIT_SIGNING_KEY` is unset or a published value, naming the variable to set. Failing loudly at boot is the intended mode: running degraded would mean an owner token anyone can mint, or an audit chain anyone can forge. | `core/config.py:assert_production_secrets`, `gateway/app.py:create_app` |
| **A retry presents an approval that does not fit** (used, expired, denied, another agent's, different arguments) | The call escalates again, as it would have without the approval, and the decision's reason says why the approval was not used. An approval is never treated as a broader permission than the call a person saw. | `identity/service.py:redeem_approval` |

---

## What this implies for the build

Highest-leverage items first — note how many of these are wiring, not invention:

1. ~~**Wire F6 and F8 into the live pipeline.**~~ **Done, 2026-09-16** — see the update at the top of this document. Nine of the eleven detectors are now called from `Enforcer.evaluate()`; F6.5 and F8.4 stay deliberately unwired for reasons stated there, and that judgement should be re-read rather than reversed by default.
2. **F7.7 — cross-turn self-contradiction**, and **F8.3 — stale index.** Both are real, scoped, moderate-effort builds — a claim-history store with a contradiction check for F7.7, an `index_freshness` check reusing F2.2's `freshness_breach` shape for F8.3 — not XL efforts.
3. **F9.1–F9.5** — five modes an independent, execution-verified audit found that no version of this taxonomy or the PRD ever listed. F9.1–F9.4 map onto existing, already-wired interfaces (the F2/F6 extraction pipeline, `assess_provenance`, the P13/`autoguard.py` trajectory primitive). F9.5 explicitly depends on wiring F8 first — build it in the same change, not before.
4. **Firm up the remaining partials** (F4.7 named legal-hold class, F5.4 real quality-trend detection, F7.6 verified date-shift vs. ambiguity-only, F8.1/F8.2's damage-marker dependency) — each is a bounded extension of an already-built and already-wired mechanism.

The four-family framing from the original document (F4 entitlement, F3 action semantics, F1 answerability, F2 source authority) is now **built and live**, not planned — those are the differentiators to defend and demo, not the backlog. F5 joined them. F6 and F8 are the cautionary tale sitting right next to that success: proof that "built" and "protects a live request" are not the same claim, and that this document needs to keep checking the difference rather than assume a module's existence.

---

## Sources

[Morningstar/PR Newswire — enterprise AI failures shifting beyond hallucinations (ChatSee, 10k+ events)](https://www.prnewswire.com/news-releases/new-research-finds-enterprise-ai-failures-are-shifting-beyond-hallucinations-as-companies-move-from-chatbots-to-agents-302837907.html) · [AI Incidents H1 2026 retrospective](https://www.digitalapplied.com/blog/ai-incidents-h1-2026-retrospective-failure-modes-analysis) · [Enterprise AI agent failure modes](https://thoughtminds.ai/blog/enterprise-ai-agent-failure-modes) · [AI agent production failures — enterprise lessons](https://www.openempower.com/blog/ai-agent-production-failures-enterprise-lessons-2026)

[M365 Copilot oversharing — what IAM and data teams must fix](https://nhimg.org/community/cybersecurity-beyond-identity/microsoft-365-copilot-oversharing-what-iam-and-data-teams-must-fix/) · [Copilot didn't overshare your data, your permissions did](https://petri.com/copilot-didnt-overshare-your-data-your-permissions-did/) · [Microsoft — mitigate oversharing for Copilot and agents](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/mitigate-oversharing-to-govern-microsoft-365-copilot-and-agents/4448744)

[Protect production SQL databases from agentic query risks](https://rietta.com/blog/ai-sql-database-data-protection-read-replica/) · [Production-ready text-to-SQL: 9 problems with fixes](https://atalupadhyay.wordpress.com/2026/07/01/building-a-production-ready-text-to-sql-ai-agent-9-problems-with-fixes/) · [AI agent database wipe — lessons](https://www.mindstudio.ai/blog/ai-agent-database-wipe-disaster-lessons/) · [Testing SQL agents — safety & query validation](https://langwatch.ai/scenario/testing-guides/sql-agent/)

[AbstentionBench — reasoning LLMs fail on unanswerable questions](https://arxiv.org/html/2506.09038v1) · [Know Your Limits — a survey of abstention in LLMs (TACL)](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00754/131566/Know-Your-Limits-A-Survey-of-Abstention-in-Large) · [The unexpected downside of RAG — over-refusal](https://www.bohrium.com/en/blog/research-notes/aaai-2026-retrieval-augmented-models-dont-know/)
