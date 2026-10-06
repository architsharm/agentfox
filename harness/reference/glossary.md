---
title: Glossary and ID conventions
layer: reference
audience: agents reading docs, code comments and commit messages
source_of_truth: docs/design/PRD.md, docs/design/traceability.md, docs/design/failure-modes.md, docs/design/control-catalog.md, src/agentfox/improvement/contract.py
verified_against: branch claude/improvement-loop-phase0, 2026-09-20
---

# Glossary

## Modes and terms

| Term | Meaning |
|---|---|
| **observe** | Record every decision, block nothing. The default everywhere. |
| **enforce** | Blocking is live, per policy (`policy enforce KEY`) and, for `auto()`, per process. |
| **fail open / closed** | What happens when a detector errors or times out: let the request through, or block it. |
| **taint** | Provenance label on content from untrusted sources (retrieved, tool result, sub-agent). It propagates into tool arguments. |
| **shadow agent** | Model traffic the registry doesn't know about. |
| **effective verdict** | What the policy would do, regardless of mode. |
| **evidence package** | Zip for auditors: decisions, audit chain slice, control mappings, and a standalone `verify_chain.py`. |
| **DRAFT chip** | Label on unreviewed framework mappings: `DRAFT — UNVERIFIED / NOT LEGAL ADVICE`. |
| **echo provider** | Offline fake model. It makes everything demonstrable with no key and no network. |
| **proposal** | A change to governance configuration the improvement loop wants to make, carrying its evidence, its proof and every decision taken on it. The loop changes nothing any other way. |
| **direction** | Whether a change **tightens**, **loosens** or is **neutral**. Computed by the applier from the diff and the live configuration, never taken from whoever filed it. A loosening is never applied automatically. |
| **autonomy level** | L0 observe, L1 recommend, L2 one-click, L3 auto-apply, L4 autonomous hygiene. Only L3 and L4 act without a person, only for a change that does not loosen, and a class over its rollback budget drops one level. L3 does not stage the change in observe mode; a kind that stages (a policy canary) does so itself. |
| **canary** | A change live for a cohort only, with a health gate that rolls it back if the candidate blocks much more, or much less, than stable. |
| **freeze** | `NOMETRIA_IMPROVEMENT_FROZEN=true`: the loop still files proposals, but nothing is applied automatically. |

## ID prefixes you'll see in docs, code and commits

| Prefix | Meaning | Where it's defined |
|---|---|---|
| `P<n>` / `P<n>-<m>` | Pillar n / its requirement m. P1 Registry, P2 Identity, P3 Guardrails, P4 Eval, P5 Audit, P6 Compliance, P7 Answerability, P8 Provenance, P9 Action assurance, P10 Entitlement, P11 Escalation, P12 Policy composition, P13 Failure attribution, P14 Context integrity, P15 Cost/reliability, P16 Memory, P17 Inter-agent, P18 Data-access scoping | `docs/design/PRD.md` §5, §12 |
| `PL-<n>` | Platform / production readiness (PL-2 migrations, PL-3 kill switch, PL-5 job queue) | `docs/design/PRD.md`, `docs/design/gap-analysis.md` |
| `I-<n>` | Integration surfaces (I-1 LangGraph, I-2 MCP, I-11 cloud providers, …) | `docs/design/PRD.md` §6 |
| `X-<n>` | Cross-cutting principles (X-3 offline install, X-5 dashboard is only an API client) | `docs/design/PRD.md` |
| `NFR-<n>` | Non-functional requirements (NFR-1 latency, NFR-9 offline) | `docs/design/PRD.md` |
| `F<fam>.<mode>` | Failure modes F1.1–F9.5 (F1 answerability … F8 context integrity) | `docs/design/failure-modes.md` |
| `NOM-<FAM>-NN` | Controls: DSC, IAM, RTG, EVL, AUD, GOV | `src/agentfox/compliance_data/controls.yaml`, Appendix B |
| `R<n>` | PRD risks | `docs/design/PRD.md` §10 |
| Tier 0–3, Tranche 0–4 | Gap-analysis severity tiers, roadmap tranches | `docs/design/gap-analysis.md`, `docs/design/PRD.md` §9 |

## Commit conventions (contributors)

`type(scope): subject (REQ-ID)`. Types: feat, fix, docs, chore, refactor, test, ci, plus
`rebuild(api|demo)` for vendored-wheel-only commits. Bodies explain root cause and end with
what was verified, e.g. "full pytest suite (N passed)".
