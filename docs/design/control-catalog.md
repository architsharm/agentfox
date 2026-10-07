# Appendix B — Control Catalog & Framework Mapping

Companion to [PRD §13](PRD.md#13-compliance-framework-coverage) and requirement **P6-2**. This is the "map once, satisfy many" content set: 43 platform controls with 317 mappings across seven frameworks.

The machine-readable form is `src/agentfox/packs/compliance/catalog/controls/controls.yaml` (controls, framework list and mappings) plus `src/agentfox/packs/compliance/catalog/controls/obligations.yaml` (the dated obligation calendar), loaded by the compliance engine. **This document is the human-readable source of truth; the YAML carries the same content and must stay in sync.** `agentfox admin catalog validate` checks the YAML's internal consistency: unique keys, known frameworks and status rules, and that the obligation calendar parses.

> ⚠️ **Status of these mappings.** They are *informed engineering drafts* produced from the framework texts, intended to make the product's control story concrete and testable. They are **not legal advice and have not been reviewed by compliance counsel or a certification body.** Before any mapping is shown to a customer's auditor it must go through the review gate in §B.6. This caveat ships in the product UI too, on every framework view.

---

## B.1 Frameworks covered

| Key | Framework | Version / basis | Nature |
|---|---|---|---|
| `eu-ai-act` | EU Artificial Intelligence Act | Reg. (EU) 2024/1689, post-omnibus timeline as of Aug 2026 | Legally binding, phased |
| `nist-ai-rmf` | NIST AI Risk Management Framework | AI RMF 1.0 + Generative AI Profile (NIST-AI-600-1) | Voluntary (US baseline) |
| `iso-42001` | ISO/IEC 42001 | :2023, Annex A controls | Certifiable management system |
| `soc2` | SOC 2 | AICPA Trust Services Criteria (2017, rev. 2022) | Attestation |
| `owasp-llm` | OWASP Top 10 for LLM Applications | 2025 | Taxonomy |
| `owasp-agentic` | OWASP Agentic AI Threats & Mitigations | T1–T15 threat taxonomy | Taxonomy |
| `mitre-atlas` | MITRE ATLAS | Adversarial Threat Landscape for AI Systems | Threat matrix |

**Why these seven:** EU AI Act is the demand pump (deadline-driven); NIST AI RMF is what US buyers ask you to map to; ISO 42001 is what enterprises increasingly require *of vendors*; SOC 2 is the Tier-A reason to buy (it unblocks *their* upmarket sales); OWASP and ATLAS are the languages the security buyer already speaks, and mapping detections into them is worth more than a proprietary severity scheme.

---

## B.2 Control families

| Prefix | Family | Pillar | Controls |
|---|---|---|---|
| `NOM-DSC` | Discovery & Inventory | 1 | 5 |
| `NOM-IAM` | Identity & Access | 2 | 8 |
| `NOM-RTG` | Runtime Guardrails | 3 | 13 |
| `NOM-EVL` | Evaluation & Reliability | 4 | 6 |
| `NOM-AUD` | Audit & Traceability | 5 | 5 |
| `NOM-GOV` | Governance & Compliance | 6 | 6 |
| | | | **43** |

Each control declares: `id`, `title`, `objective`, `pillar`, `implemented_by` (the FR that delivers it), `evidence_sources` (what telemetry proves it operating — this is what makes **P6-4 continuous monitoring** possible rather than attestation-based), `status_rule` (how `effective`/`degraded`/`failing` is computed), and `mappings`.

---

## B.3 The catalog

### NOM-DSC — Discovery & Inventory (Pillar 1)

| ID | Control | Implements | Evidence source | EU AI Act | NIST AI RMF | ISO 42001 | SOC 2 | OWASP LLM | OWASP Agentic | ATLAS |
|---|---|---|---|---|---|---|---|---|---|---|
| **NOM-DSC-01** | A complete, current inventory of every AI agent in the environment is maintained. | P1-1 | `Agent` records; gateway traffic correlation | Art. 11 (technical documentation) | MAP 1.1, GOVERN 1.6 | A.6 (lifecycle), A.4 (resources) | CC3.2 | — | T13 Rogue Agents | — |
| **NOM-DSC-02** | Agents operating outside the governed inventory are detected and reported. | P1-2 | `Finding[type=shadow_agent]` | Art. 26 (deployer obligations) | MAP 1.1, MANAGE 4.1 | A.9 (use of AI systems) | CC7.2 | — | T13 Rogue Agents | — |
| **NOM-DSC-03** | Every agent has a named accountable owner, business purpose and assigned risk tier. | P1-4 | `Agent.owner`, `.purpose`, `.risk_tier` | Art. 9, Art. 26 | GOVERN 2.1, MAP 1.1 | A.3 (internal organisation) | CC1.3, CC3.2 | — | — | — |
| **NOM-DSC-04** | Dependencies between agents, models, tools, data sources and sub-agents are mapped from observed behaviour. | P1-3 | `LineageEdge` derived from spans | Art. 11, Art. 15 | MAP 2.1, MAP 4.1 | A.6, A.10 (third parties) | CC3.2, CC9.2 | LLM03 Supply Chain | T12 Agent Communication Poisoning | — |
| **NOM-DSC-05** | Third-party tool/MCP surfaces are inventoried and monitored for schema drift and instruction injection. | P1-5 | `McpToolSnapshot` diffs; `Finding[type=tool_poisoning]`; scheduled `Monitor` runs (`mcp_server`, `github_repo`, `hosted_api`) raising `Finding[type=monitor_*]` | Art. 15, Art. 25 | MAP 4.1, MEASURE 2.7 | A.10 | CC9.2 | LLM03 Supply Chain | T2 Tool Misuse | AML.T0053 LLM Plugin Compromise |

### NOM-IAM — Identity & Access (Pillar 2)

| ID | Control | Implements | Evidence source | EU AI Act | NIST AI RMF | ISO 42001 | SOC 2 | OWASP LLM | OWASP Agentic | ATLAS |
|---|---|---|---|---|---|---|---|---|---|---|
| **NOM-IAM-01** | Every agent holds a unique, governed non-human identity with a lifecycle (issue, rotate, revoke, expire). | P2-1 | `Identity`, `Credential` events | Art. 15 (cybersecurity) | GOVERN 1.5, MANAGE 2.2 | A.3, A.9 | CC6.1, CC6.2, CC6.3 | — | T9 Identity Spoofing | AML.T0055 Unsecured Credentials |
| **NOM-IAM-02** | Agent access to tools and actions is least-privilege and default-deny, enforced on every call. | P2-2 | `Decision` records with policy version | Art. 15 | MANAGE 2.2, GOVERN 1.5 | A.9 | CC6.1, CC6.3 | LLM06 Excessive Agency | T3 Privilege Compromise | — |
| **NOM-IAM-03** | High-impact actions require documented human approval before execution. | P2-3 | `ApprovalRequest` + resolution; redemption (`status=used`, `approval.redeemed` on the decision) — one call per approval, bound to agent, tool and arguments, refused while the agent is stopped | **Art. 14 (human oversight)** | GOVERN 3.2, MANAGE 2.3 | A.9 | CC5.2 | LLM06 Excessive Agency | T10 Overwhelming HITL | — |
| **NOM-IAM-04** | Control-plane access is authenticated, role-based, and provisioned/de-provisioned through the identity system. | P2-4 | `User` (role), `ApiToken` issue and revoke on the audit chain; sign-out revokes the token; startup refused on a published service secret | Art. 26 | GOVERN 2.1 | A.3 | CC6.1, CC6.2, CC6.6 | — | — | — |
| **NOM-IAM-05** | Delegated (sub-agent) authority is narrowed, never widened, and the chain is recorded. | P2-5 | `DelegationEdge` w/ capability diff | Art. 14, Art. 15 | MANAGE 2.2 | A.9 | CC6.3 | LLM06 Excessive Agency | T3 Privilege Compromise | — |
| **NOM-IAM-06** | Policy changes are simulated against recorded traffic and reviewed before enforcement. | P2-7 | `SimulationRun` diff report; promotion to enforce refused without a recorded simulation of that version | Art. 17 (QMS) | MANAGE 4.1, GOVERN 1.2 | A.6 | **CC8.1 (change mgmt)** | — | — | — |
| **NOM-IAM-07** | The end-user principal is propagated through the agent into retrieval; content the principal is not entitled to is withheld before generation and the withholding is recorded; restricted classes require an explicit clearance rather than a grant; and over-permissioned retrieval is measured continuously. | P10-1, P10-2, P10-3, P10-4, P10-6, P10-7, P10-8, P10-9 | `disclosure_events`, `end_user_principals` | Art. 10 — data governance, Art. 15 | MAP 4.1, MANAGE 2.2 | A.5, A.8 | CC6.1, CC6.3 | LLM02 Sensitive Information Disclosure, LLM06 Excessive Agency | — | — |
| **NOM-IAM-08** | Inter-agent messages are evaluated on their own surface (not folded into tool results), signed and verified where the transport is ours, and rejected on replay; unsigned traffic is reported, not silently trusted. | P17-1 | `AgentMessageLog`, `AgentSigningKey` | Art. 15 | MANAGE 2.2 | A.9 | CC6.1, CC6.3 | — | **T12 Agent Communication Poisoning**, T16 Insecure Inter-Agent Protocol Abuse | — |

### NOM-RTG — Runtime Guardrails (Pillar 3)

| ID | Control | Implements | Evidence source | EU AI Act | NIST AI RMF | ISO 42001 | SOC 2 | OWASP LLM | OWASP Agentic | ATLAS |
|---|---|---|---|---|---|---|---|---|---|---|
| **NOM-RTG-01** | Prompt-injection and jailbreak attempts are detected and blocked on all untrusted input surfaces, including indirect (retrieved/tool) content. | P3-1 | `DetectorRun` (incl. `tool_args`), `Decision[verdict=block]`; live-probe campaigns | **Art. 15 (robustness & cybersecurity)** | MEASURE 2.7, MANAGE 2.2 | A.6 | CC6.6, CC7.2 | **LLM01 Prompt Injection** | T6 Intent Breaking & Goal Manipulation | **AML.T0051** LLM Prompt Injection; AML.T0054 LLM Jailbreak |
| **NOM-RTG-02** | Personal and sensitive data is detected and redacted or blocked in both directions. | P3-2 | `DetectionFinding[entity=PII]` | **Art. 10 (data governance)**; GDPR Art. 5, 32 | MEASURE 2.10, MANAGE 2.2 | **A.7 (data for AI)** | CC6.7 | **LLM02 Sensitive Information Disclosure** | — | AML.T0057 LLM Data Leakage |
| **NOM-RTG-03** | Credentials and secrets are detected and prevented from transiting prompts, outputs or tool arguments. | P3-3 | `DetectionFinding[entity=SECRET]` | Art. 15 | MEASURE 2.7 | A.7 | CC6.1, CC6.7 | LLM02 | — | AML.T0055 Unsecured Credentials |
| **NOM-RTG-04** | Tool invocations are authorised against intent and argument provenance, not text alone; tainted arguments cannot reach high-impact tools unapproved. | P3-4 | `Decision` w/ taint context | Art. 14, Art. 15 | MANAGE 2.2 | A.9 | CC6.3 | LLM01, **LLM06 Excessive Agency** | **T2 Tool Misuse**, T6 | AML.T0053 |
| **NOM-RTG-05** | Model input and output are screened against a documented content-safety policy. | P3-5 | `DetectorRun[safety]` scores | Art. 15, Art. 50 | MEASURE 2.6, MEASURE 2.11 | A.6 | CC7.2 | LLM09 Misinformation | T7 Misaligned & Deceptive Behaviors | — |
| **NOM-RTG-06** | Enforcement operates within a documented latency budget; degradation is detected and recorded rather than silently skipped. | P3-6, P3-7 | `DetectorRun.duration_ms`, `Finding[type=budget_breach]`; `Decision` rules `policy.unloadable` (a bound policy version that no longer loads, handled under the fail mode) | Art. 15 | MEASURE 2.5 | A.6 | CC7.2, **A1.1 (availability)** | — | T4 Resource Overload | — |
| **NOM-RTG-07** | Model output conforms to its declared schema/contract; violations are repaired, retried or blocked. | P3-9 | `DetectorRun[schema]` | Art. 15 | MEASURE 2.5 | A.6 | CC7.2 | **LLM05 Improper Output Handling** | — | — |
| **NOM-RTG-08** | Consumption (calls, tokens, spend, recursion depth) is bounded per agent, and runaway loops are broken. | P3-10 | `Budget` counters, `Finding[type=loop]` | Art. 15 | MANAGE 2.2 | A.4 | A1.1 | **LLM10 Unbounded Consumption** | **T4 Resource Overload** | — |
| **NOM-RTG-09** | SQL, shell and API artefacts generated by an agent are parsed deterministically before execution; operation class, blast radius and reversibility are established, unbounded and destructive operations are refused, and irreversible acts require a verified read from the system of record. | P9-1, P9-2, P9-3, P9-4, P9-5, P9-6, P9-7, P9-10 | `decisions`, `findings` | Art. 15, Art. 14 — human oversight | MANAGE 2.2, MEASURE 2.6 | A.6, A.8 | CC7.2, CC8.1 | LLM06 Excessive Agency | — | — |
| **NOM-RTG-10** | Each agent declares the conditions under which it must hand off to a human; conversations that met a condition and did not escalate are detected after the fact; hand-offs carry complete context, have a named owner and an SLA, and resolution claims are checked against what the conversation actually shows. | P11-1, P11-2, P11-3, P11-4, P11-5, P11-6, P11-7 | `handoffs`, `findings` | Art. 14 — human oversight, Art. 50 | MANAGE 4.1, GOVERN 3.2 | A.9 | CC2.2 | LLM06 Excessive Agency | — | — |
| **NOM-RTG-11** | Each agent declares the systems of record it reaches, the time range they cover, the entity scopes in play and the question types it can answer. Questions outside that boundary are answered from a template without reaching the model, answers are verified against the boundary after generation, and refusals of answerable questions are detected as a counter-metric. | P7-1, P7-2, P7-3, P7-4, P7-6, P7-7 | `knowledge_boundaries`, `decisions` | Art. 13 — transparency, Art. 15 | MEASURE 2.3, MANAGE 4.1 | A.6 | CC7.2 | LLM09 Misinformation | — | — |
| **NOM-RTG-12** | Retrieved sources carry a tier, an owner, a freshness SLA and a domain; answers are checked for fabricated citations, silent source conflicts and uncited material claims; and numeric, temporal and entity integrity is verified deterministically against the evidence actually retrieved. | P8-1, P8-2, P8-3, P8-4, P8-5 | `source_records`, `findings` | Art. 13 — transparency, Art. 15 | MEASURE 2.5, MEASURE 2.9 | A.6, A.7 | PI1.1, CC7.2 | LLM09 Misinformation, LLM08 Vector and Embedding Weaknesses | — | — |
| **NOM-RTG-13** | Writes into an agent's long-term memory are validated by the detector pipeline before they commit and carry provenance/taint; unverified entries expire rather than persisting indefinitely. | P14-7 | `MemoryEntry`, `Decision[surface=memory_write]` | Art. 15 | MEASURE 2.7, MANAGE 2.2 | A.6, A.9 | CC6.6, CC6.7 | LLM04 Data & Model Poisoning | **T1 Memory Poisoning** | AML.T0020 Poison Training Data |

### NOM-EVL — Evaluation & Reliability (Pillar 4)

| ID | Control | Implements | Evidence source | EU AI Act | NIST AI RMF | ISO 42001 | SOC 2 | OWASP LLM | OWASP Agentic | ATLAS |
|---|---|---|---|---|---|---|---|---|---|---|
| **NOM-EVL-01** | Agent changes are evaluated against a versioned dataset before release; regressions block deployment. | P4-1 | `EvalRun`, gate result in CI (an errored case fails the gate) | **Art. 15 (accuracy)**, Art. 17 (QMS) | **MEASURE 2.3**, MANAGE 4.1 | **A.6 (lifecycle)** | **CC8.1** | — | — | — |
| **NOM-EVL-02** | Production behaviour is continuously sampled, scored, and monitored for drift against a baseline. | P4-2 | `DriftWindow`, online `EvalResult` | **Art. 72 (post-market monitoring)** | **MANAGE 4.1**, MEASURE 2.4 | A.6 | CC7.2 | — | — | AML.T0031 Erode ML Model Integrity |
| **NOM-EVL-03** | Plausible-but-incorrect outputs (silent failures) are detected and surfaced. | P4-3 | `EvalResult[scorer∈silent_failure]` | Art. 15, Art. 72 | MEASURE 2.3, MEASURE 2.9 | A.6 | CC7.2 | **LLM09 Misinformation** | **T5 Cascading Hallucination**, T7 | — |
| **NOM-EVL-04** | The system is adversarially tested on a recurring basis and results tracked as posture over time. | P4-4 | `RedTeamCampaign` results, incl. scheduled live probes of deployed agents (`runner=live`, `Finding[type=live_probe_escape]`) | **Art. 15 (cybersecurity)**, Art. 55 (GPAI systemic risk) | **MEASURE 2.7**, MANAGE 2.2 | A.6 | CC7.1 | LLM01, LLM04 Data & Model Poisoning | T1 Memory Poisoning | **AML.T0043** Craft Adversarial Data |
| **NOM-EVL-05** | Reliability targets are declared, measured, and error-budget burn is reported. | P4-7 | `SLO` status series | Art. 15, Art. 72 | MEASURE 2.5, MANAGE 4.1 | A.6 | A1.1 | — | — | — |
| **NOM-EVL-06** | Model/provider substitutions are evaluated comparatively before adoption. | P4-8, X-2 | Cross-model `EvalRun` | Art. 15, Art. 25 | MEASURE 2.3, MAP 4.1 | A.10 | CC8.1 | LLM03 Supply Chain | — | — |

### NOM-AUD — Audit & Traceability (Pillar 5)

| ID | Control | Implements | Evidence source | EU AI Act | NIST AI RMF | ISO 42001 | SOC 2 | OWASP LLM | OWASP Agentic | ATLAS |
|---|---|---|---|---|---|---|---|---|---|---|
| **NOM-AUD-01** | The complete execution path of every agent invocation is recorded — prompts, retrievals, tool calls and arguments, delegations, decisions, errors. | P5-1 | `Trace`, `Span` | **Art. 12 (record-keeping / automatic logging)** | MEASURE 1.1, MANAGE 4.1 | A.6 | CC7.2 | — | **T8 Repudiation & Untraceability** | — |
| **NOM-AUD-02** | Governance-relevant events are recorded in an append-only, tamper-evident log whose integrity is independently verifiable. | P5-2 | `AuditEntry` chain + `AuditCheckpoint` | **Art. 12**, Art. 19 (log retention) | GOVERN 1.2, MEASURE 1.1 | A.6 | **CC7.2, CC7.3** | — | **T8 Repudiation & Untraceability** | — |
| **NOM-AUD-03** | Evidence for a stated scope and period can be exported in a complete, verifiable package with chain-of-custody. | P5-3, P5-7 | `EvidencePackage` + manifest | **Art. 12, Art. 18 (documentation keeping)**, Art. 26 | GOVERN 1.2 | A.8 (information for interested parties) | CC7.3 | — | — | — |
| **NOM-AUD-04** | Governance events are exported to the organisation's existing security monitoring without requiring adoption of a new system of record. | P5-4 | SIEM export receipts | Art. 26, **Art. 73 (serious incident reporting)** | MANAGE 4.1 | A.6 | **CC7.4 (incident response)** | — | — | — |
| **NOM-AUD-05** | Recorded content is minimised and redacted at capture; retention is bounded per data class; legal hold suspends deletion. | P5-5 | `RetentionPolicy`, `LegalHold` | **Art. 10**, Art. 19; GDPR Art. 5(1)(c),(e) | MANAGE 2.2 | **A.7** | CC6.7, **C1.1 (confidentiality)** | LLM02 | — | — |

### NOM-GOV — Governance & Compliance (Pillar 6)

| ID | Control | Implements | Evidence source | EU AI Act | NIST AI RMF | ISO 42001 | SOC 2 | OWASP LLM | OWASP Agentic | ATLAS |
|---|---|---|---|---|---|---|---|---|---|---|
| **NOM-GOV-01** | Governance rules exist as versioned, reviewable code that drives both runtime enforcement and reporting. | P6-1 | `Policy`, `PolicyVersion` | Art. 17 (QMS) | **GOVERN 1.1, GOVERN 1.2** | **A.2 (AI policy)** | CC5.2, CC8.1 | — | — | — |
| **NOM-GOV-02** | Platform controls are mapped to applicable regulatory and standards frameworks and maintained as those change. | P6-2, P6-8 | `Control`, `FrameworkMapping` versions | Art. 17 | GOVERN 1.1 | A.2, A.8 | CC2.1, CC3.1 | — | — | — |
| **NOM-GOV-03** | Each agent is risk-assessed and classified (incl. EU AI Act risk category), with mitigations and residual risk recorded and reviewed. | P6-3 | `RiskAssessment` | **Art. 9 (risk management system)**, Art. 6 (classification), Art. 27 (FRIA) | **MAP 1.5, MAP 5.1**, GOVERN 1.3 | **A.5 (impact assessment)** | CC3.2, CC3.4 | — | — | — |
| **NOM-GOV-04** | Control effectiveness is monitored continuously from operational telemetry, not periodic attestation. | P6-4 | `ControlStatus` series | Art. 17, Art. 72 | **MANAGE 4.1**, MEASURE 1.1 | A.6 | **CC4.1 (monitoring)** | — | — | — |
| **NOM-GOV-05** | Applicable regulatory obligations and their deadlines are tracked against the agent inventory. | P6-5 | `Obligation` scope + status | Art. 6, Art. 50, Art. 111 (phasing) | GOVERN 1.1 | A.2 | CC2.1 | — | — | — |
| **NOM-GOV-06** | Aggregate AI risk posture is reported to executive/board level on a defined cadence. | P6-6 | Board view snapshots | Art. 17, Art. 26 | **GOVERN 2.1, GOVERN 4.1** | A.3 | **CC2.2, CC4.2** | — | — | — |

---

## B.4 Coverage summary

| Framework | Controls touching it | Notable gaps we do **not** claim to cover |
|---|---|---|
| EU AI Act | 43 / 43 | Conformity assessment procedure (Art. 43), CE marking, notified-body interaction, registration in the EU database (Art. 49), FRIA *content* (Art. 27) — we provide inputs, not the filing. |
| NIST AI RMF | 43 / 43 | Organisational culture/workforce items under GOVERN 3–4 that are not technical. |
| ISO/IEC 42001 | 43 / 43 | Clauses 4–10 management-system requirements (context, leadership, competence, internal audit, management review) — an AIMS programme, not a platform. |
| SOC 2 | 43 / 43 | The customer's own entity-level controls; our platform supports their evidence, it is not their SOC 2. |
| OWASP LLM Top 10 | 8 / 10 covered | **LLM04** Data & Model Poisoning and **LLM08** Vector & Embedding Weaknesses are partially addressed (we detect downstream symptoms, we do not secure the training or embedding pipeline). |
| OWASP Agentic T1–T15 | 10 / 15 covered | T11 Unexpected RCE (sandbox concern — §2.3 non-goal), T14 Human Attacks on Multi-Agent, T15 Human Manipulation are out of scope. |
| MITRE ATLAS | 8 techniques mapped | Training-time and model-supply-chain techniques are out of scope. |

**Being explicit about gaps is a feature.** A compliance product that claims total coverage fails its first serious audit conversation. Every framework view in the product renders this gap list alongside the coverage claim.

---

## B.5 Status computation (P6-4)

Control status is computed, not attested:

| Status | Rule |
|---|---|
| `effective` | Control's evidence sources are present, fresh (within the control's window), and its `status_rule` predicate passes across the scope. |
| `degraded` | Evidence present but the predicate is failing for some scope members, or evidence is stale. |
| `failing` | Predicate fails across the scope, or a hard signal fires (e.g. NOM-AUD-02 chain verification fails). |
| `not_implemented` | No evidence source is producing data (feature not enabled). |
| `not_applicable` | Scoped out by the customer with a recorded justification and approver. |

Example `status_rule` for **NOM-RTG-01**: *effective* if ≥ 99% of in-scope agent invocations in the window ran the injection detector, no `budget_breach` findings degraded it to observe-only for > 1% of traffic, and the detector version is not deprecated.

Example for **NOM-AUD-02**: *effective* only if the most recent chain verification over the window returned `valid` with zero gaps. This is a hard signal — a single verification failure sets `failing`, not `degraded`.

---

## B.6 Mapping review gate

Before any mapping in this appendix is presented to a customer's auditor:

1. **Engineering** confirms the `implemented_by` FR actually ships and the `evidence_sources` actually populate.
2. **Compliance counsel / qualified assessor** reviews the framework citation for accuracy and scope.
3. The mapping is marked reviewed on its `framework_mappings` row (`review_status`, `reviewed_by`, `reviewed_at`; `capabilities/compliance/catalog.py:review_mapping`).
4. Unreviewed mappings render in the UI with a `DRAFT — not reviewed` badge and ship inside evidence packages with a `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` chip on each row, instead of being excluded, so reviewers can see exactly what is still outstanding.

**As of 2026-10-06: all mappings are still `DRAFT`.** None have completed step 2.

### Changelog

| Date | Version | Change |
|---|---|---|
| 2026-10-06 | 0.1.0-draft | No new controls. Evidence sources updated where the mechanism changed: approvals redeemed once and refused while an agent is stopped (NOM-IAM-03), token revocation and the startup secret check (NOM-IAM-04), simulation required to promote to enforce (NOM-IAM-06), injection detection on tool arguments and live probes (NOM-RTG-01, NOM-EVL-04), unloadable policy versions under the fail mode (NOM-RTG-06), errored eval cases fail the gate (NOM-EVL-01), scheduled monitors of connected sources (NOM-DSC-05). Family and coverage counts corrected to 43 controls. |
| 2026-08-29 | 0.1.0-draft | Evidence packages now include draft mappings (chip-labeled `DRAFT — UNVERIFIED / NOT LEGAL ADVICE`) instead of excluding them, so reviewers can see exactly what is outstanding. |
| 2026-08-17 | 0.1.0-draft | Initial catalog — 36 controls, 7 frameworks. All mappings DRAFT. |
| 2026-08-18 | 0.1.0-draft | Added NOM-RTG-09 (generated actions analysed before execution, P9) — 37 controls, 266 mappings. |
| 2026-08-19 | 0.1.0-draft | Added NOM-RTG-10 (escalation governed, P11) and NOM-RTG-11 (knowledge boundary, P7) — 39 controls, 280 mappings. |
| 2026-08-19 | 0.1.0-draft | Added NOM-RTG-12 (source authority, P8) and NOM-IAM-07 (entitlement, P10) — 41 controls, 300 mappings. |
| 2026-09-15 | 0.1.0-draft | Added NOM-IAM-08 (inter-agent messages, P17) and NOM-RTG-13 (memory writes, P14) to the machine catalog — both were documented here and cited by `baseline.yaml` but missing from `controls.yaml`. Added the table rows for NOM-IAM-07 and NOM-RTG-09…12 that existed only in the YAML. 43 controls, 317 mappings. |
| 2026-08-26 | 0.1.0-draft | Added NOM-RTG-13 (memory write governance, P14-7, closes OWASP ASI06) and NOM-IAM-08 (inter-agent message security, new P17, closes OWASP ASI07). Originally proposed as NOM-RTG-09 for the memory-write control; corrected to NOM-RTG-13 since NOM-RTG-09 was already assigned (P9, generated-action risk analysis) — see [`docs/design/PRD.md`](PRD.md) §12.1 for the full correction note. |
