# Compliance crosswalk review: our control catalog against another public mapping

Companion to [control-catalog.md](control-catalog.md). This review checks our framework mappings against the published compliance mappings in Microsoft's MIT-licensed agent governance toolkit (`docs/compliance/*.md`, upstream commit `c767f83`). We wanted a second, independently written mapping to catch errors in ours.

> **Our mappings are still drafts.** Every mapping in `controls.yaml` stays `review_status: draft`. A second vendor's self-assessment is not an auditor, and agreeing with it proves nothing. Where the two disagree, this file says which framework text we checked and what we would do. Nothing here is legal advice.

**What the two documents are.** The two mappings answer different questions, which explains most of the gaps in both directions.

- **Ours** maps 43 platform controls to framework identifiers. Each control has evidence computed from telemetry.
- **Theirs** maps their product's modules to a framework and grades each item Full, Partial or Gap.

So "they map it and we do not" often means they claim a product feature covers an organisational obligation that we deliberately list as a gap.

Their files reviewed:

- `owasp-agentic-top10-architecture.md` and `owasp-asi-policy-mapping.md` (OWASP Top 10 for Agentic Applications 2026, ASI01–ASI10)
- `mcp-owasp-top10-mapping.md` (OWASP MCP Top 10, beta)
- `nist-ai-rmf-alignment.md`
- `eu-ai-act-checklist.md`
- `cis-controls-v81-mapping.md`
- `iso-42001-mapping.md`
- `owasp-llm-top10-mapping.md` (for identifier alignment only)

SOC 2 and MITRE ATLAS are in both catalogs and are not reviewed here.

## Changes made to our catalog in this review

Only clear errors were fixed. Everything else is a recommendation below.

| File | Change | Why |
|---|---|---|
| `src/agentfox/packs/compliance/catalog/controls/controls.yaml` (NOM-RTG-13) | `LLM04 Data & Model Poisoning` became `LLM04 Data and Model Poisoning` | The catalog spelled LLM04 two ways. The OWASP 2025 title is "Data and Model Poisoning". `threats.py` already normalises both spellings, so coverage counts do not change. |
| `docs/design/control-catalog.md` (NOM-RTG-13, NOM-EVL-04 rows, B.4) | Same spelling, and `LLM08 Vector & Embedding` became `Vector and Embedding` | Keeps the human-readable copy in sync with the YAML, which already used "and". |
| `docs/design/control-catalog.md` B.4, OWASP Agentic row | "10 / 15 covered" became "12 / 15 covered" | We map T1–T10, T12 and T13, and the row's own gap list names only T11, T14 and T15. 15 − 3 = 12. |
| `docs/design/control-catalog.md` B.4, OWASP LLM row | "8 / 10 covered" became "9 / 10 mapped, 2 of them partially", plus a note that LLM07 is unmapped | Nine of ten LLM IDs appear in `controls.yaml`. The row named LLM04 and LLM08 as partial but did not mention that LLM07 has no mapping at all. |

No mapping was added or removed. Every addition proposed below needs the review gate in control-catalog.md §B.6 first.

---

## 1. OWASP agentic

**Ours:** the *Agentic AI Threats and Mitigations* taxonomy (T1–T15). **Theirs:** the newer *Top 10 for Agentic Applications (2026)*, ASI01–ASI10. Each side maps a list the other does not, so nothing compares one-to-one.

The biggest finding is that we do not map the 2026 Top 10 at all. The 2026 list is what security buyers will now ask about. The table below is a proposed draft crosswalk from our existing controls to it. Every row needs review before it goes into `controls.yaml`.

| ASI 2026 | Their claim | Our candidate controls | Recommended action |
|---|---|---|---|
| ASI01 Agent Goal Hijack | Full | NOM-RTG-01 (injection detection), NOM-RTG-04 (intent and argument provenance) | Add to the proposed `owasp-agentic-2026` framework |
| ASI02 Tool Misuse and Exploitation | Full | NOM-IAM-02, NOM-RTG-04, NOM-RTG-09 | Add |
| ASI03 Identity and Privilege Abuse | Full | NOM-IAM-01, NOM-IAM-02, NOM-IAM-05 | Add |
| ASI04 Agentic Supply Chain | Partial | NOM-DSC-05, NOM-EVL-06 | Add, marked partial: we monitor MCP drift but produce no SBOM |
| ASI05 Unexpected Code Execution | Full | Partly NOM-RTG-09, which parses generated SQL, shell and API calls before they run. Our catalog lists T11 (RCE) as out of scope and has no sandbox. `code.insecure` and the `agent-integrity` pack ship in watch mode. | Map as partial (RTG-09). State that sandboxing is out of scope. |
| ASI06 Memory and Context Poisoning | Partial | NOM-RTG-13 | Add |
| ASI07 Insecure Inter-Agent Communication | Full | NOM-IAM-08 | Add |
| ASI08 Cascading Agent Failures | Full | NOM-RTG-08 (runaway loops), NOM-RTG-09 (cascade analysis), NOM-DSC-04 | Add |
| ASI09 Human-Agent Trust Exploitation | Partial | NOM-IAM-03, NOM-RTG-10. Approvals are bound to the exact arguments; `benchmarks/toolkit_corpus/` measured a forged and a swapped approval, and both were held | Add |
| ASI10 Rogue Agents | Full | NOM-DSC-02, NOM-EVL-02. The kill switch and quarantine exist in code but have no control (see §4) | Add once a kill-switch control exists |

**Rows we map that they do not:**

- T1–T15 as a whole. Recommended action: keep it alongside the 2026 list, since some buyers still cite T-numbers.

**Disagreements and inconsistencies:**

- **Our framework label against our own mapping.** The label says "T1–T15" (`controls.yaml` frameworks, `threats.yaml`, control-catalog §B.1), but NOM-IAM-08 maps `T16 Insecure Inter-Agent Protocol Abuse`. T16 is not in the T1–T15 list the label names. Recommended action: find the OWASP publication that defines T16. Then either widen the label and its source, or drop T16 and rely on T12. Not changed here because we could not confirm the source.
- **"Full" coverage claims.** Their summary rates seven of ten "Full" (`owasp-agentic-top10-architecture.md:31-42`). Their own LLM mapping says that for 6 of 10 risks, the detection modules exist but are not wired into enforcement (`owasp-llm-top10-mapping.md`, Executive Summary). Recommended action: none for us. It is the reason we compute status from telemetry instead of asserting it.

## 2. OWASP MCP Top 10 (beta)

We do not map the MCP Top 10. They do: 7 Covered, 3 Partial (`mcp-owasp-top10-mapping.md:25-38`). The list is still in beta, so a mapping now will need rework when it is final.

| MCP risk | Their claim | Our candidate controls | Recommended action |
|---|---|---|---|
| MCP01 Token Mismanagement and Secret Exposure | Partial | NOM-RTG-03 (secrets), NOM-AUD-05 (redaction at capture) | Draft once the list is final |
| MCP02 Privilege Escalation via Scope Creep | Covered | NOM-IAM-02, NOM-IAM-05 | Draft |
| MCP03 Tool Poisoning | Covered | NOM-DSC-05 | Draft |
| MCP04 Software Supply Chain Attacks | Covered | NOM-DSC-05, NOM-EVL-06 | Draft, marked partial |
| MCP05 Command Injection and Execution | Covered | NOM-RTG-09 (generated SQL, shell and API calls parsed before they run) | Draft, marked partial; no sandbox |
| MCP06 Intent Flow Subversion | Partial | NOM-RTG-01, NOM-RTG-04 | Draft |
| MCP07 Insufficient Authentication and Authorization | Covered | NOM-IAM-01, NOM-IAM-04 | Draft |
| MCP08 Lack of Audit and Telemetry | Covered | NOM-AUD-01, NOM-AUD-02 | Draft |
| MCP09 Shadow MCP Servers | Partial | NOM-DSC-02 covers agents, not servers | Gap until servers are inventoried as such |
| MCP10 Context Injection and Over-Sharing | Covered | NOM-IAM-07 (entitlement), NOM-RTG-02 | Draft |

## 3. NIST AI RMF 1.0

The two documents work at different levels of detail.

- **Theirs** grades the 19 *categories* (GOVERN 1–6, MAP 1–5, MEASURE 1–4, MANAGE 1–4) but calls them "subcategories" (`nist-ai-rmf-alignment.md:62`).
- **Ours** maps 25 *subcategories* (for example MEASURE 2.7). The framework has 72 subcategories in all.

**Categories they cover and we have no subcategory for:**

| Category | Their claim | Our position | Recommended action |
|---|---|---|---|
| GOVERN 5 (engagement with relevant AI actors) | Full, under a different title (see below) | Organisational | Leave unmapped and add to our `gaps` list |
| GOVERN 6 (third-party software and data) | Full, under a different title | We have NOM-DSC-05 and NOM-EVL-06 | Propose GOVERN 6.1 on both |
| MAP 3 (benefits and costs) | Partial | Not a platform function | Leave unmapped |
| MEASURE 3 (tracking risks over time) | Full | NOM-EVL-02 (drift) and NOM-GOV-04 (continuous control status) track risk over time | Propose MEASURE 3.1 on both |
| MEASURE 4 (feedback on measurement efficacy) | Partial | Our learned-permissions and label feedback loop is close | Review before mapping |
| MANAGE 1 (risks prioritised and responded to) | Full | Runtime blocking and escalation are a response | Propose MANAGE 1.3 on NOM-RTG-04 and NOM-IAM-03 |
| MANAGE 3 (third-party risks managed) | Full | NOM-DSC-05, NOM-EVL-06 | Propose MANAGE 3.1 |

**Subcategories we map that they cannot match at their level:** all 25. Recommended action: none; ours is the finer grain.

**Disagreements:**

| Item | Finding | Recommended action |
|---|---|---|
| Their GOVERN 4, 5 and 6 headings | Their doc titles GOVERN 4 "Organizational Practices with Third-Party Entities", GOVERN 5 "Risk Management Processes Are Defined and Implemented" and GOVERN 6 "Policies and Procedures Aligned with Applicable Requirements" (`nist-ai-rmf-alignment.md:202, 235, 256`). In AI RMF 1.0, GOVERN 4 is organisational risk culture, GOVERN 5 is engagement with AI actors, and GOVERN 6 is third-party software and data. Their "Full" ratings for GOVERN 4–6 are graded against the wrong text. | None for us. Do not borrow their GOVERN 4–6 evidence. |
| Our GOVERN 1.5 on NOM-IAM-01 and NOM-IAM-02 | GOVERN 1.5 is ongoing monitoring and periodic review of the risk-management process. An identity lifecycle and default-deny access are a weak fit. | Review: MANAGE 2.4 or MAP 4.1 may fit better |
| Our MANAGE 2.2 on 13 controls | MANAGE 2.2 (mechanisms to sustain the value of deployed systems) is used as a catch-all for runtime guardrails | Review. MANAGE 2.4 (supersede, disengage or deactivate a system) fits blocking and the kill switch more directly. |
| Our MEASURE 2.11 (fairness and bias) on NOM-RTG-05 | A safety lexicon screens harmful content. It does not evaluate fairness. | Review. They rate fairness a gap, and we probably should too. |

## 4. EU AI Act

Both documents are about the final Regulation (EU) 2024/1689. Theirs is an article checklist (`eu-ai-act-checklist.md`, 11 articles, "0 fully covered"). Ours maps 19 articles.

**Articles they assess and we do not map:**

| Article | Their claim | Recommended action |
|---|---|---|
| Art. 4 AI literacy | Gap, out of scope | Add to our `gaps` list as organisational, so the gap is stated rather than silent |
| Art. 14(4)(e) stop mechanism (we map Art. 14 generally) | Partial, kill switch | We have a kill switch and quarantine in code, verified by the `cb8` containment scenario, but **no control in the catalog**. Propose a control (or extend NOM-RTG-10) mapped to Art. 14(4)(e), NIST MANAGE 2.4 and ASI10. |
| Art. 5 prohibited practices | Says the toolkit "can detect and block" them via policy rules | Do not follow. Art. 5 prohibits a system's purpose, which a content rule cannot decide. Leave unmapped. |

**Articles we map that they do not:**

- Art. 17 (quality management)
- Art. 18 (documentation keeping)
- Art. 25 (value chain)
- Art. 27 (FRIA inputs)
- Art. 55 (GPAI systemic risk)
- Art. 72 (post-market monitoring)
- Art. 73 (serious incidents)
- Art. 111 (transitional)

Some of these appear only in their "scope limitations" list. Recommended action: keep all of them, at draft.

**Disagreements:**

| Item | Finding | Recommended action |
|---|---|---|
| Serious-incident reporting article | Their scope table cites **Art. 62** for serious incident reporting (`eu-ai-act-checklist.md:502`). That is the numbering in the Commission's 2021 proposal. In the final Regulation it is **Art. 73**, which is what NOM-AUD-04 maps. | None for us. Ours is correct. |
| Art. 10 (data governance) | They rate it out of scope, because it governs training, validation and testing data sets. We map NOM-RTG-02 (runtime PII), NOM-IAM-07 (entitlement) and NOM-AUD-05 (retention) to it. | **Review; likely remove.** Runtime redaction and entitlement are not Art. 10 data-set governance, and their reading is the more defensible one. Not changed here because removal is a judgement call that belongs to the §B.6 review. |
| Art. 19 / Art. 26(6) six-month log retention | They flag their own 90-day default as a conformity blocker. We map Art. 19 to NOM-AUD-02 and NOM-AUD-05. Our seed sets `audit` retention to 2555 days but `prompt_content` to 90 days (`fixtures/seed.py`), nothing enforces a 180-day floor, and we found no code that deletes by `retain_days`. NOM-AUD-05's status rule only checks that a policy exists. | Decide whether `prompt_content` counts as Art. 12 logs for high-risk agents. If it does, set a 180-day floor for those agents and make NOM-AUD-05 check it. |
| Art. 13 (transparency to deployers) on NOM-RTG-11 and NOM-RTG-12 | Grounding and abstention help users, but Art. 13 is about instructions for use and information the provider gives deployers | Review |

## 5. CIS Controls v8.1

We have no CIS mapping. They map 54 safeguard rows across 14 controls (`cis-controls-v81-mapping.md`).

**Rows where we have real evidence**, recommended as a small, optional mapping (a buyer-asked-for item, not a priority):

| CIS safeguard | Their claim | Our candidate control |
|---|---|---|
| 1.1, 1.3 enterprise asset inventory, active discovery | Full | NOM-DSC-01, NOM-DSC-02 |
| 2.1 software inventory | Full | NOM-DSC-05 (MCP servers and tools) |
| 5.1, 5.3 account inventory, disable dormant accounts | Full | NOM-IAM-01 |
| 6.1, 6.2 access granting and revoking | Full | NOM-IAM-02, NOM-IAM-03 |
| 8.2, 8.5, 8.9 collect, detail and centralise audit logs | Full | NOM-AUD-01, NOM-AUD-02, NOM-AUD-04 |
| 17.4 incident response process | Full | NOM-AUD-04 feeds one; the process itself is the customer's |

**Rows we should not copy:**

- **3.6 Encrypt data on end-user devices**, mapped to agent-to-agent message encryption (`cis-controls-v81-mapping.md:64`). The safeguard is about laptops and phones.
- **10.1 Anti-malware**, mapped to a prompt-injection detector (`:120`).
- Network and physical safeguards: 1.4, 3.9, 13.6.

**Their internal count.** The summary reports 42 safeguards mapped (28 full, 10 partial, 4 gaps) at `:28-31`. The tables below it list 54 rows: 35 full, 13 partial, 4 gaps and 2 not applicable. Recommended action: none for us. Cite their row tables, not their summary.

## 6. ISO/IEC 42001:2023

The two mappings do not overlap.

- **Theirs** covers only the management-system clauses 4–10 and rates most of them Covered, including clause 5 Leadership.
- **Ours** covers only Annex A (A.2–A.10). It lists clauses 4–10 as an explicit gap: "an AIMS programme, not a platform".

**Clauses they map and we do not**, with recommended actions:

| Clause | Their claim | Recommended action |
|---|---|---|
| 5.1–5.3 leadership, policy, roles | Covered by approval workflows and YAML policy | Do not follow. Leadership commitment is an organisational act. Keep our gap note. |
| 6.1.2 / 8.2 AI risk assessment, 6.1.3 / 8.3 risk treatment | Covered (under wrong numbers, see below) | Propose mapping NOM-GOV-03 and NOM-RTG-04 as *evidence for* these clauses, not as coverage |
| 6.1.4 / 8.4 AI system impact assessment | Not addressed (they mislabel 8.4) | Propose NOM-GOV-03 (risk and FRIA inputs) as evidence |
| 7.5 documented information | Covered | Propose NOM-AUD-02, NOM-AUD-03 as evidence |
| 9.1 monitoring, measurement, analysis | Covered | Propose NOM-GOV-04, NOM-EVL-02 as evidence |
| 4.x, 7.1–7.4, 9.2, 9.3, 10.x | Mixed | Leave unmapped; keep the gap note |

**Annex A controls we map and they do not:** all of A.2–A.10. Recommended action: keep, at draft.

**Disagreement: their clause numbers.** Their table numbers several clauses in a way that does not match ISO/IEC 42001:2023. We cite identifiers and titles only, not the standard's text.

- Clause 5 has 5.1–5.3, and 5.2 is the AI policy. Their table adds a "5.4 AI policy" (`iso-42001-mapping.md:39`).
- Risk assessment and risk treatment are 6.1.2 and 6.1.3. 6.3 is planning of changes, and there is no 6.4. Their table has "6.3 AI risk assessment" and "6.4 AI risk treatment" (`:51-52`).
- 8.4 is AI system impact assessment. Their table titles 8.4 "AI system development and deployment" (`:79`).

Recommended action: none for us. Anyone reconciling the two documents should key on clause titles, not their numbers.

## 7. OWASP LLM Top 10: identifiers do not line up

Their LLM mapping says it uses the **2023 v1.1** numbering (`owasp-llm-top10-mapping.md`, edition note). Its header cites the 2025 list. Ours uses **2025**. The same ID therefore means different risks in the two documents. For example, their LLM06 Sensitive Information Disclosure is our LLM02, and their LLM07 Insecure Plugin Design is not our LLM07 System Prompt Leakage. Their LLM02 is titled "Unexpected Code Execution" (`:45`), which is not an LLM02 title in either edition.

| Item | Recommended action |
|---|---|
| Comparing the two by ID | Never compare by ID; compare by title |
| LLM07 (2025) System Prompt Leakage | They cover it partially with canary tokens. We map nothing to it, although `injection.heuristic` raises `INJECTION.SYSTEM_PROMPT_LEAK`. Propose adding LLM07 to NOM-RTG-01. Note that `benchmarks/toolkit_corpus/` measured 0/16 on prompt-leakage attacks, so map it as partial. |

## Summary of recommended actions

1. Add the OWASP Top 10 for Agentic Applications (2026) as a framework, using the draft crosswalk in §1.
2. Add a kill-switch / stop control mapped to EU AI Act Art. 14(4)(e), NIST MANAGE 2.4 and ASI10.
3. Review, and likely remove, the EU AI Act Art. 10 mappings on runtime controls.
4. Decide the Art. 19 / 26(6) log-retention floor for high-risk agents, and make NOM-AUD-05's status rule check it.
5. Resolve the T16 label inconsistency.
6. Map LLM07 (partial).
7. Consider NIST GOVERN 6.1, MEASURE 3.1, MANAGE 1.3 and MANAGE 3.1, and drop MEASURE 2.11 from NOM-RTG-05.
8. Optional: a small CIS v8.1 mapping (§5), and ISO clauses 6.1.2–6.1.4, 7.5 and 9.1 as evidence (not coverage).

Every one of these goes through the §B.6 review gate. Until then, the catalog stays draft.
