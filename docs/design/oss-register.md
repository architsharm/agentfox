# Appendix A — OSS Dependency Register

Companion to [the PRD](PRD.md)'s [§7.4 OSS decisions](PRD.md#74-oss-decisions). Every project surveyed, with licence, health, verdict, the pillar it serves, and — critically — **our exposure** if it changes status.

**Scan date:** Aug 2026. **Re-verify quarterly.** Two projects on this list changed status within the preceding twelve months, which is the whole reason the adapter seam in [the PRD's §7.2 The swappable seam](PRD.md#72-the-swappable-seam) exists.

Legend — **Verdict:** `REUSE` wrap it · `REUSE ★` best-in-class pick · `REUSE ⚠` usable but licence-restricted · `REFERENCE` study, do not depend · `ADOPT` taxonomy, not code.
**Exposure:** what breaks for us if the project dies, changes licence, or is acquired.

---

## A.1 Critical path — permissive, active, wrapped

| Project | Maintainer | Licence | Health | Pillar | Verdict | What we use it for | Our exposure | Fallback |
|---|---|---|---|---|---|---|---|---|
| **Presidio** | Microsoft | MIT | Active ★ | 3 | **REUSE ★** | PII detection, anonymisation, de-identification. De-facto OSS standard; extensible recognisers. | **Low.** Behind `Detector`. | Native regex/NER recogniser set already ships as the offline path (`PiiDetector` degrades without Presidio installed). |
| **Open Policy Agent (OPA)** | CNCF | Apache-2.0 | Active ★ | 2, 6 | **REUSE ★** | Policy decision engine (Rego). Tool-scoped least privilege, policy-as-code runtime. | **Low.** Behind `PolicyEngine`. | Native Python evaluator ships as the default; OPA is the scale/expressiveness upgrade. Cedar is a drop-in second option. |
| **OpenTelemetry** (+ OpenLLMetry) | CNCF / Traceloop | Apache-2.0 | Active ★ | 5 | **REUSE ★** | Span/trace wire format and semantic conventions; the audit spine's transport. | **Very low.** Industry standard; multi-vendor governance. | None needed. |
| **promptfoo** | ~~promptfoo~~ **OpenAI** (acq. 9 Mar 2026) | MIT | Active, **provider-owned** | 4 | **REFERENCE ⚠** *(downgraded 2026-08-18)* | Eval + red-team harness with CI gating. **Acquired by OpenAI and embedded into OpenAI Frontier.** Remains open source under its current licence, and OpenAI committed to continuing it. | **Reclassified.** The code risk is low — it sits behind `EvalRunner` and the native runner is the default. The *strategic* risk is the one this register exists to catch: a model provider now owns our CI-eval substrate, which is the same conflict that put Invariant/mcp-scan in A.3. | Native runner (already primary). |
| **Garak** | NVIDIA | Apache-2.0 | Active | 4 | **REUSE** | LLM vulnerability scanner — injection, jailbreak, data leakage, toxicity probes. | **Low.** Behind `RedTeamRunner`. | Built-in offline probe suite. |
| **PyRIT** | Microsoft | MIT | Active | 4 | **REUSE** | Orchestrated, automated red-teaming of GenAI. | **Low.** Behind `RedTeamRunner`. | Built-in probe suite. |
| **Giskard** | Giskard | Apache-2.0 | Active | 4 | **REUSE** | LLM testing/scan — vulnerabilities, bias, hallucination; framework-agnostic. | **Low.** Optional. | — |
| **Granite Guardian** | IBM | Apache-2.0 | Active | 3, 4 | **REUSE ★** | Safety/risk classifier (harm, jailbreak, RAG hallucination). **The cleanest licence in the classifier group — true Apache-2.0 weights.** Default safety classifier. | **Low.** Behind `Detector`; weights not bundled. | Heuristic lexicon classifier (offline default). |
| **NeMo Guardrails** | NVIDIA | Apache-2.0 | Active | 3 | **REUSE** | Programmable rails (Colang) — topical, jailbreak, dialogue, fact-check; composes checks. | **Low.** Adapter; our pipeline is primary. | Native pipeline. |
| **Guardrails AI** | Guardrails AI | Apache-2.0 (core) | Active | 3 | **REUSE** | I/O validation, structured output, Hub validators, auto-correction. | **Medium on Hub validators** — the core is Apache-2.0 but **individual Hub validators carry their own licences**; check per-validator before shipping any of them. | Native JSON-schema/format validator. |
| **Cedar** | AWS | Apache-2.0 | Active | 2 | **REUSE** | Fine-grained authz language; formally verified; sub-ms. | **Low.** Kept as a `PolicyEngine` seam, not currently on the path. | OPA / native. |
| **Casbin** | community | Apache-2.0 | Active | 2 | **REUSE** | ACL/RBAC/ABAC across many languages. | **Low.** Optional for control-plane RBAC. | Native role matrix (current). |
| **Helicone** | Helicone | Apache-2.0 | Active | 5 | **REUSE** | Proxy request logging, cost tracking, rate limiting. | **Low.** Optional export target. | Native. |

## A.2 Adopt as language, not code

| Project | Maintainer | Licence | Pillar | Verdict | Use |
|---|---|---|---|---|---|
| **OWASP LLM Top 10** | OWASP | Open | 3, 6 | **ADOPT** | Canonical risk taxonomy for LLM threats. Every detector maps to an LLM-Top-10 ID. |
| **OWASP Agentic Top 10** | OWASP | Open | 3, 6 | **ADOPT** | Agent-specific threats (tool misuse, excessive agency, memory poisoning, identity spoofing). Our containment controls map here. |
| **MITRE ATLAS** | MITRE | Open | 3 | **ADOPT** | Adversarial ML threat matrix. Detections map to ATLAS technique IDs so SOCs can correlate. |

Mapping detections to a taxonomy the buyer already trusts is worth more than a proprietary severity scheme. See [Appendix B](control-catalog.md).

## A.3 Reference only — do not depend

| Project | Maintainer | Licence | Status | Why excluded | What we take from it |
|---|---|---|---|---|---|
| **LLM Guard** | Protect AI (Palo Alto) | MIT | **Archived 9 Jul 2026** | Repo and its HF models archived. Excellent design; dead dependency. Also now owned by a competitor. | The **scanner taxonomy** — 15 input + 20 output scanners — used as a coverage checklist for our detector set. |
| **Rebuff** | Protect AI | Apache-2.0 | Stale | Effectively unmaintained; Protect AI → Palo Alto. | Multi-layer injection detection pattern, especially **canary tokens** — reimplemented natively. |
| **Vigil** | community | Apache-2.0 | Low activity | Not maintained enough for a critical path. | Injection scanner heuristics. |
| **promptfoo** | **OpenAI** (acquired 9 Mar 2026) | MIT | Provider-owned | Now inside OpenAI Frontier, a competing enterprise agent platform. Same category of conflict as Invariant→Snyk. Still permissively licensed and still usable — but it must not be the *default* path, and we must not describe it as neutral. | Optional adapter only; native runner stays the default. Re-verify each release. |
| **Invariant Guardrails / mcp-scan** | **Snyk** (acquired) | Apache-2.0 | Snyk-owned | The most agent/MCP-native OSS guardrails — and therefore the **most dangerous to build differentiation on**, because Snyk is building this category. | `mcp-scan` invoked as an **external CLI tool** in P1-5. Never a library dependency. |
| **systemprompt-core** | systempromptio | **BSL-1.1** | Active | Business Source Licence — *source-available, not open source.* Usage restrictions today; converts to Apache after a delay. **No BSL on any path in a commercial product without legal review.** | MCP governance runtime patterns (authn/authz, rate limiting) as design reference. |
| **Microsoft Agent Governance Toolkit** | Microsoft | MIT | Active | Competitor-adjacent framing (Agent 365); adopting it undercuts X-2 neutrality. | Its **OWASP Agentic Top-10 coverage map** across 15+ frameworks, as a coverage reference. |
| **OpenAI Guardrails** | OpenAI (AgentKit) | MIT | Active | Open-source but OpenAI-centric. Building on it contradicts neutrality (X-2) and is precisely the provider-bundling risk in PRD R2. | Config ergonomics; a reminder of what a provider will bundle for free. |
| **Langfuse** | Langfuse (ClickHouse) | MIT core | **Acquired Jan 2026** | Core is MIT and self-hostable, but the company is inside ClickHouse and some features sit behind a commercial EE tier. | Supported as an **export target** (P5-4). Never our system of record. |

## A.4 Licence-restricted — opt-in only

| Project | Licence | Restriction | Our handling |
|---|---|---|---|
| **Llama Guard 4 / Prompt Guard 2** | Llama Community | **Not OSI-approved.** Adds an Acceptable-Use Policy and a >700M-MAU clause. Usable by most startups, but it is a restricted licence and needs commercial legal review. | Adapter exists; **not installed by default**; requires `AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1`. Granite Guardian is the default. |
| **ShieldGemma** | Gemma Licence | Same category — restricted, not permissive. | Same handling. |

**Rule:** nothing restricted, archived, BSL, or competitor-owned sits on the default critical path. A customer must not inherit a licence obligation by running `docker compose up`.

**Opting in to Llama Guard on a self-hosted stack.** `deploy/docker-compose.yml` ships with `safety.restricted` out of the enabled detector list and the licence flag at `"0"`, and the published gateway image never carries the gated weights. After the legal review above: accept Meta's licence for `meta-llama/Llama-Guard-3-8B` on Hugging Face, build the gateway image yourself with that account's token (`HF_TOKEN=hf_... docker compose -f deploy/docker-compose.yml build gateway`, which bakes the weights in), add `safety.restricted` to `AGENTFOX_ENABLED_DETECTORS`, and set `AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1`.

## A.5 Coverage by pillar

Directly from the catalog's coverage map — and it *is* the strategy:

| Pillar | OSS coverage | Our split |
|---|---|---|
| 3 · Runtime guardrails (injection, PII, toxicity, tool-call) | ██████████ Well covered | Wrap ~70% / build ~30% (taint tracking, containment) |
| 4 · Evaluation & reliability (red-team, eval, regression) | ███████░░░ Good primitives | Wrap ~40% / build ~60% (**silent-failure detection has no OSS equivalent**) |
| 2 · Identity & authorization (policy engines, RBAC/ABAC) | ██████░░░░ Engines yes, agent-native no | Wrap the engine / build the agent capability model |
| 5 · Audit & traceability | ████░░░░░░ Tracing yes; immutable/evidence no | Wrap OTel / **build the evidentiary layer** |
| 1 · Discovery & registry | ██░░░░░░░░ Thin, and what exists is competitor-owned | Build |
| 6 · Policy & compliance mapping | ░░░░░░░░░░ Essentially none | **Build — the moat** |

Target engineering split: **~20% integrating OSS, ~80% on the build column.**

## A.6 Obligations on us

1. `THIRD_PARTY_NOTICES.md` maintained with every dependency and its licence text pointer (Apache-2.0 §4(d)).
2. Restricted-licence adapters gated behind explicit acknowledgement; never a default install.
3. Quarterly re-verification of licence file + last-commit date for every A.1 entry. Status changes go in this appendix's changelog.
4. No BSL, no archived, no competitor-owned project on a default code path.

### Changelog

| Date | Change |
|---|---|
| 2026-08-17 | Initial register from the OSS build-vs-reuse catalog scan. |
| 2026-08-18 | **promptfoo reclassified REUSE ★ → REFERENCE ⚠** — acquired by OpenAI 9 Mar 2026 and embedded into OpenAI Frontier. Moved off the critical path per the A.6 rule. Also noted: Lakera → Check Point (~$300M), Galileo → Cisco, Weights & Biases → CoreWeave. The original scan missed all four. |
