# Third-Party Notices

AgentFox is licensed under Apache-2.0. It incorporates or optionally integrates the
open-source projects below. This file satisfies the attribution requirement in
Apache-2.0 §4(d) and records the licence review behind each decision.

**Maintenance obligation** (Appendix A §A.6): re-verify every critical-path entry's
`LICENSE` file and last-commit date **quarterly**. Two projects on the original scan
changed status within twelve months — one archived, one acquired by a competitor —
which is why the adapter seam exists.

---

## Runtime dependencies (installed by default)

| Project | Licence | Use |
|---|---|---|
| FastAPI | MIT | HTTP framework for the gateway and control-plane API |
| Starlette | BSD-3-Clause | ASGI toolkit under FastAPI |
| Uvicorn | BSD-3-Clause | ASGI server |
| SQLAlchemy | MIT | Persistence layer |
| Pydantic / pydantic-settings | MIT | Schema validation, configuration |
| httpx | BSD-3-Clause | HTTP client (provider adapters, OPA) |
| PyYAML | MIT | Policy and compliance content parsing |
| Typer | MIT | CLI |
| Rich | MIT | Terminal rendering |
| argon2-cffi | MIT | Credential hashing |
| Next.js | MIT | Control-plane UI |
| React | MIT | UI runtime |

## Optional integrations (wrapped OSS primitives)

All permissive. Installed only via an explicit extra — see `pyproject.toml`.

| Project | Maintainer | Licence | Extra | Pillar | Wrapped by |
|---|---|---|---|---|---|
| **Presidio** (analyzer, anonymizer) | Microsoft | MIT | `pii` | 3 | `guardrails/adapters/presidio.py` |
| **Granite Guardian** | IBM | Apache-2.0 | `classifiers` | 3 | `guardrails/adapters/classifiers.py` |
| **NeMo Guardrails** | NVIDIA | Apache-2.0 | `rails` | 3 | `guardrails/adapters/rails.py` |
| **Guardrails AI** (core) | Guardrails AI | Apache-2.0 | `validators` | 3 | `guardrails/adapters/rails.py` |
| **Garak** | NVIDIA | Apache-2.0 | `redteam` | 4 | `evaluation/redteam.py` |
| **PyRIT** | Microsoft | MIT | `redteam` | 4 | `evaluation/redteam.py` |
| **promptfoo** | promptfoo | MIT | external binary | 4 | `evaluation/adapters.py` |
| **Open Policy Agent** | CNCF | Apache-2.0 | container | 2, 6 | `policy/opa.py` |
| **OpenTelemetry** (+ OpenLLMetry conventions) | CNCF / Traceloop | Apache-2.0 | `otel` | 5 | `audit/otel.py` |
| **PostgreSQL** / psycopg | PostgreSQL / LGPL-3.0 | — | `postgres` | — | persistence |

> ⚠️ **Guardrails AI Hub validators.** The Guardrails AI *core* is Apache-2.0, but
> individual Hub validators carry their own, independent licences. None is enabled by
> default; any Hub validator must be licence-checked before it ships.

## Restricted-licence adapters — NOT installed by default

These are **not OSI-approved open source**. The adapters exist but refuse to load
unless `AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1`, and they are excluded from the
`all` extra and from the published container image.

| Project | Licence | Restriction |
|---|---|---|
| **Llama Guard 4 / Prompt Guard 2** | Llama Community Licence | Acceptable-Use Policy; >700M-MAU clause. Usable by most startups, but requires commercial legal review. |
| **ShieldGemma** | Gemma Licence | Acceptable-Use Policy; not permissive. |

**Granite Guardian (Apache-2.0) is the default safety classifier precisely because it
avoids these terms.**

## Standards and taxonomies (adopted as language, not code)

| Source | Terms | Use |
|---|---|---|
| **OWASP Top 10 for LLM Applications** (2025) | Open (CC) | Detection and control taxonomy |
| **OWASP Agentic AI Threats & Mitigations** (T1–T15) | Open (CC) | Agent-specific threat taxonomy |
| **MITRE ATLAS** | Open, MITRE terms | Technique identifiers on detections |
| **NIST AI RMF 1.0** + Generative AI Profile | US Government work | Control mapping |
| **ISO/IEC 42001:2023** | © ISO/IEC — **not redistributed** | Control mapping references Annex A clause identifiers only; the standard text is not reproduced. |
| **EU AI Act** (Reg. (EU) 2024/1689) | EU official text | Control mapping references article numbers only. |
| **AICPA SOC 2 Trust Services Criteria** | © AICPA — **not redistributed** | Mapping references criterion identifiers only. |

> Framework mappings in `compliance/controls.yaml` cite **identifiers and short
> titles only**. No copyrighted standard text is reproduced. The mappings themselves
> are our own drafting and are marked DRAFT until reviewed (Appendix B §B.6).

## Benchmark data (copied unchanged, used as data only)

| Data | Source | Licence | Where | Use |
|---|---|---|---|---|
| Prompt-injection smoke corpus (280 rows), its manifest, hygiene summary and published baseline scores | Microsoft agent-governance-toolkit, `benchmarks/prompt-injection/` at commit `c767f83` | MIT, Copyright (c) Microsoft Corporation | `benchmarks/toolkit_corpus/data/prompt_injection/` | Replayed through our detectors; their scores quoted for comparison |
| Red-team smoke scenarios (24) and their contract schema | same repository, `tests/redteam/benchmark/` at commit `c767f83` | MIT, Copyright (c) Microsoft Corporation | `benchmarks/toolkit_corpus/data/redteam/` | Instantiated and replayed through our enforcement path |

The MIT licence text and copyright notice are kept beside the copied files in
`benchmarks/toolkit_corpus/data/LICENSE`. The files are unmodified; nothing from that
repository is installed or executed. Using the data implies no endorsement by its authors.

## Studied but deliberately NOT used

Recorded because "why not" is a licence decision worth auditing (Appendix A §A.3):

| Project | Reason excluded |
|---|---|
| **LLM Guard** (Protect AI / Palo Alto) | MIT, but **archived 9 Jul 2026**. Its scanner taxonomy informed our detector coverage; no code or dependency taken. |
| **Rebuff**, **Vigil** | Stale / low activity. Multi-layer injection patterns (canary tokens) reimplemented natively. |
| **Invariant Guardrails / mcp-scan** (Snyk) | Acquired by a competitor building this category. `mcp-scan` may be invoked as an **external CLI tool**; never linked as a dependency. |
| **systemprompt-core** | **BSL-1.1** — source-available, not open source; usage restrictions. Reference only. |
| **OpenAI Guardrails** | MIT but provider-centric; adopting it would contradict vendor neutrality (X-2). |
| **Langfuse** | MIT core, but ClickHouse-acquired with an EE tier. Supported as an export target, never as our system of record. |
| **Microsoft Agent Governance Toolkit** | MIT, competitor-adjacent. No code or dependency taken. Its OWASP Agentic coverage map was used as a reference, and two of its test fixtures are copied as benchmark data (see "Benchmark data" above). |

## Attribution

Apache-2.0 projects above are distributed under the Apache License, Version 2.0
(<http://www.apache.org/licenses/LICENSE-2.0>). MIT and BSD projects retain their
original copyright and permission notices in their distributed packages. No modified
copies of any third-party source are vendored into this repository; all integrations
are adapters against published interfaces.

_Last reviewed: 2026-10-09._
