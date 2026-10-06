---
title: Docs map — which repo markdown an agent should read, for what
layer: reference
audience: agents (routing), maintainers (classification)
source_of_truth: this file classifies docs; it never restates them
verified_against: branch claude/improvement-loop-phase0, 2026-09-20
---

# Docs map

The harness **never copies** product docs. It points at them. Every markdown file in the
repo falls into exactly one class below. When you add a doc, add a row here in the same
commit; `scripts/check_harness.py` fails if a repo `.md` file is unclassified.

## Class A — canonical: load on demand when the question needs it

| File | Read it when you need | Notes |
|---|---|---|
| `README.md` | the pitch, quickstart, one contained tool call, headline numbers, honest limits | Entry point for humans; numbers bound in `benchmarks/claims.yaml` |
| `ARCHITECTURE.md` | the domain model, one tool call traced through `auto()` and the gateway, the code map, invariants, where to start for a change | Start here before changing code; names functions, not line numbers |
| `docs/product-tour.md` | every integration surface (auto, gateway, LangGraph, MCP, Claude Code hooks), commands grouped by task, demo output, self-hosting | Moved out of the README; the website guides cover the same ground |
| `docs/design/PRD.md` | *why* a feature exists, requirement IDs, roadmap, non-goals | 1,200 lines — jump to §5 pillars, §6 integrations, §9 roadmap, §10.3 non-goals, §12 shipped since |
| `docs/architecture/high-level-design.md` | architecture, request path, deployment topology | Derived from code; code wins |
| `docs/architecture/low-level-design.md` | which module implements what, class internals, CLI tree | Counts drift; code wins |
| `docs/design/traceability.md` | requirement → module → control → test | Hand-maintained |
| `docs/design/failure-modes.md` | how deployed agents fail (F1–F9) and which are covered | Living scorecard |
| `docs/design/gap-analysis.md` | enterprise-readiness gaps, Tier 0–3 | Canonical gap register |
| `docs/architecture/judgment-tiers.md` | what each optional judgment tier (Jev, hosted LLM, local LLM) may decide, and the routing table | Read before enabling a tier |
| `docs/architecture/judgment-egress.md` | what leaves the boundary when a hosted judgment tier is on; the PII block/redact/allow choice | Read before enabling a hosted tier on regulated data |
| `docs/design/production-readiness-review.md` | gaps found re-checking HLD/LLD against the code, and what was fixed since | Dated review; `docs/design/gap-analysis.md` + `git log` for current state |
| `docs/design/competitor-analysis.md` | market landscape and where competitors win; source for the public /compare page | Positioning; cite primary benchmark docs for numbers |
| `docs/evaluation/judgment/*.md` | the judgment-tier study: results (numbers bound in `benchmarks/claims.yaml`), vs-shipping, cascade, safepyramid | Quote numbers from `results.md` only |
| `docs/evaluation/responding-to-the-critique.md` | answering the "AI security is bullshit" argument: what we accept, what we dispute, what we changed | Sales-facing; keep claims checkable |
| `docs/design/control-catalog.md` | NOM-* controls and their framework mappings | All mappings DRAFT; YAML path in the doc is stale |
| `docs/architecture/threat-model.md` | threats to customers' agents and to the product | |
| `docs/design/oss-register.md` | why an OSS project is (not) used, licences | Check before adding a dependency |
| `docs/README.md` | the index of docs/: what each document is for and who it is for | Start here when you do not know which document answers a question |
| `docs/getting-started.md` | a linear first hour for a new user, ending with their own agent governed | Written for a newcomer, not for an agent; each step says what it proves |
| `docs/deployment/systemd.md` | running the Python gateway as a reboot-persistent systemd user service, with separate database, evidence and signing-key storage | Self-hosters on Linux |
| `docs/evaluation/evidence-standards.md` | how to read any number in this repo, and the limits that apply before it | Read before quoting a benchmark |
| `benchmarks/README.md` | which benchmark proves which claim | Index; quote numbers from the linked methodology only |
| `THIRD_PARTY_NOTICES.md` | attribution obligations | Update when adding a dependency |

## Class B — generated: regenerate, never hand-edit

| File | Regenerate with |
|---|---|
| `docs/status.md` | `uv run python scripts/coverage.py --write` |
| `docs/design/coverage-map.md` | `uv run python scripts/probe/run.py --md > docs/design/coverage-map.md` |

Quote coverage numbers only from these, and only after regenerating.

## Class C — drifted: use with caution, verify against code

| File | Known drift | Use instead |
|---|---|---|
| `docs/architecture/api-spec.md` | missing and phantom routes | `harness/reference/http-api.md`, live `/docs` |
| `docs/architecture/data-model.md` | wrong model path | `src/agentfox/core/models/` |

## Class D — task-scoped: read only when working on that thing

| Files | Task |
|---|---|
| `benchmarks/REPORT.md`, `benchmarks/*/README.md` (one per benchmark area) | running or changing that benchmark |
| `benchmarks/data/README.md`, `benchmarks/data_generalization/README.md`, `docs/evaluation/dataset-sourcing.md` | dataset provenance and licensing |
| `demo/redteam-live/README.md`, `demo/redteam-live-lang/README.md` | running or deploying the live demos |
| `CONTRIBUTING.md` | setting up to work on the code: `just setup`/`just ci` (the `justfile` mirrors CI), test layout, generated files and their checks, the vendored-wheel rule, branch and docstring conventions |
| `SECURITY.md` | reporting or triaging a vulnerability, including what is deliberately not one here |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1, verbatim. Reporting contact only; nothing project-specific to read |
| `CHANGELOG.md` | what changed in a release, and the section `.github/workflows/release.yml` turns into release notes |
| `.github/PULL_REQUEST_TEMPLATE.md` | opening a pull request: the four checks that gate it and the vendored-wheel rule |
| `deploy/README-dashboard.md` | deploying the hosted dashboard (Render/Fly/Vercel), its shared secrets and the Neon migration state |

## Class E — human-only: do not load into agent context

| Files | Why |
|---|---|
| `docs/evaluation/benchmarking-whitepaper.md` | Positioning and marketing; an agent should cite primary benchmark docs, not these |

## Harness files (Class H — owned by `harness/`)

Everything under `harness/` is agent-facing by design and follows `harness/STRUCTURE.md`.

## Question → where to look

| Question | First stop | Then |
|---|---|---|
| How do I run X? | `harness/reference/cli.md` | `agentfox X --help` |
| Which env var controls Y? | `harness/reference/config.md` | `src/agentfox/core/config.py` |
| What does this API route take? | `harness/reference/http-api.md` | `src/agentfox/gateway/routes/` |
| Why was this built / is it in scope? | `docs/design/PRD.md` | `docs/design/gap-analysis.md` |
| Where is requirement P9-11 implemented? | `docs/design/traceability.md` | `docs/architecture/low-level-design.md` |
| Is failure mode F3.8 covered? | `docs/status.md` (regenerate first) | `docs/design/failure-modes.md` |
| Which framework clause does control NOM-RTG-04 map to? | `src/agentfox/compliance_data/controls.yaml` | Appendix B |
| What does the loop want to change, and who may decide it? | `harness/skills/operate-improvement-loop/SKILL.md` | `src/agentfox/improvement/contract.py` |
| Why did the tool do something surprising? | `harness/reference/known-issues.md` | source |
