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
| `README.md` | the pitch, install paths, the CLI cheat sheet, honest limits | Entry point for humans |
| `docs/PRD.md` | *why* a feature exists, requirement IDs, roadmap, non-goals | 1,200 lines — jump to §5 pillars, §6 integrations, §9 roadmap, §10.3 non-goals, §12 shipped since |
| `docs/hld.md` | architecture, request path, deployment topology | Derived from code; code wins |
| `docs/lld.md` | which module implements what, class internals, CLI tree | Counts drift; code wins |
| `docs/traceability.md` | requirement → module → control → test | Hand-maintained |
| `docs/failure-modes.md` | how deployed agents fail (F1–F9) and which are covered | Living scorecard |
| `docs/gap-analysis.md` | enterprise-readiness gaps, Tier 0–3 | Canonical gap register |
| `docs/responding-to-the-critique.md` | answering the "AI security is bullshit" argument: what we accept, what we dispute, what we changed | Sales-facing; keep claims checkable |
| `docs/pricing-and-procurement.md` | draft pricing model and the procurement-readiness checklist | **Draft for a human decision** — do not quote as policy |
| `docs/appendix-b-control-catalog.md` | NOM-* controls and their framework mappings | All mappings DRAFT; YAML path in the doc is stale |
| `docs/appendix-e-threat-model.md` | threats to customers' agents and to the product | |
| `docs/appendix-a-oss-register.md` | why an OSS project is (not) used, licences | Check before adding a dependency |
| `docs/README.md` | the index of docs/: what each document is for and who it is for | Start here when you do not know which document answers a question |
| `docs/getting-started.md` | a linear first hour for a new user, ending with their own agent governed | Written for a newcomer, not for an agent; each step says what it proves |
| `docs/deployment-systemd.md` | running the Python gateway as a reboot-persistent systemd user service, with separate database, evidence and signing-key storage | Self-hosters on Linux |
| `docs/evidence-standards.md` | how to read any number in this repo, and the limits that apply before it | Read before quoting a benchmark |
| `benchmarks/README.md` | which benchmark proves which claim | Index; quote numbers from the linked methodology only |
| `THIRD_PARTY_NOTICES.md` | attribution obligations | Update when adding a dependency |

## Class B — generated: regenerate, never hand-edit

| File | Regenerate with |
|---|---|
| `docs/status.md` | `uv run python scripts/coverage.py --write` |
| `docs/coverage-map.md` | `uv run python scripts/probe/run.py --md > docs/coverage-map.md` |

Quote coverage numbers only from these, and only after regenerating.

## Class C — drifted: use with caution, verify against code

| File | Known drift | Use instead |
|---|---|---|
| `docs/appendix-c-api-spec.md` | missing and phantom routes | `harness/reference/http-api.md`, live `/docs` |
| `docs/appendix-d-data-model.md` | wrong model path | `src/agentfox/models.py` |
| `docs/production-readiness-review.md` | 🔴 1.1, 1.2 and §1.4 fixed since | `docs/gap-analysis.md` + `git log` |

## Class D — task-scoped: read only when working on that thing

| Files | Task |
|---|---|
| `benchmarks/REPORT.md`, `benchmarks/*/README.md` (one per benchmark area) | running or changing that benchmark |
| `benchmarks/data/README.md`, `benchmarks/data_generalization/README.md`, `docs/dataset-sourcing.md` | dataset provenance and licensing |
| `demo/redteam-live/README.md`, `demo/redteam-live-lang/README.md` | running or deploying the live demos |
| `CONTRIBUTING.md` | setting up to work on the code: the extras to install, the checks that must pass, and the two things that surprise people (vendored wheels, numbers bound to result files) |
| `SECURITY.md` | reporting or triaging a vulnerability, including what is deliberately not one here |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1, verbatim. Reporting contact only; nothing project-specific to read |
| `CHANGELOG.md` | what changed in a release, and the section `.github/workflows/release.yml` turns into release notes |
| `.github/PULL_REQUEST_TEMPLATE.md` | opening a pull request: the four checks that gate it and the vendored-wheel rule |
| `deploy/README-dashboard.md` | deploying the hosted dashboard (Render/Fly/Vercel), its shared secrets and the Neon migration state |
| `docs/audit-tracker-pmlanguage.md`, `docs/audit-tracker-designreview.md` | dashboard copy/UX work (open backlogs) |

## Class E — human-only: do not load into agent context

| Files | Why |
|---|---|
| `docs/research/*.md` | Raw research inputs kept for provenance; two files contain real people's career data |
| `docs/competitor-analysis.md`, `docs/benchmarking-whitepaper.md` | Positioning and marketing; an agent should cite primary benchmark docs, not these |
| `docs/audit-tracker.md`, `docs/audit-tracker-newuser.md` | Closed historical trackers |

## Harness files (Class H — owned by `harness/`)

Everything under `harness/` is agent-facing by design and follows `harness/STRUCTURE.md`.

## Question → where to look

| Question | First stop | Then |
|---|---|---|
| How do I run X? | `harness/reference/cli.md` | `agentfox X --help` |
| Which env var controls Y? | `harness/reference/config.md` | `src/agentfox/config.py` |
| What does this API route take? | `harness/reference/http-api.md` | `src/agentfox/gateway/routes/` |
| Why was this built / is it in scope? | `docs/PRD.md` | `docs/gap-analysis.md` |
| Where is requirement P9-11 implemented? | `docs/traceability.md` | `docs/lld.md` |
| Is failure mode F3.8 covered? | `docs/status.md` (regenerate first) | `docs/failure-modes.md` |
| Which framework clause does control NOM-RTG-04 map to? | `src/agentfox/compliance_data/controls.yaml` | Appendix B |
| What does the loop want to change, and who may decide it? | `harness/skills/operate-improvement-loop/SKILL.md` | `src/agentfox/improvement/contract.py` |
| Why did the tool do something surprising? | `harness/reference/known-issues.md` | source |
