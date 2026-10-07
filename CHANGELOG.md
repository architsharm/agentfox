# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Published benchmark numbers do not live here. They live in the result files under
`benchmarks/`, and `scripts/claims.py --check` binds every number quoted in a document to
the file it came from.

## [Unreleased]

### Added

- **Capability packs.** A business use case or framework is one directory with a
  `pack.yaml` (id, version, maturity, owners, compliance mappings, vocabulary) and its
  policies, controls, ladder templates, red-team probes, optional checks, golden cases
  and fixtures. Built in: `baseline`, `tool-containment`, `coding-agent`, `eu-ai-act`,
  `compliance/catalog`, `payments/refunds`, `customer-support`. Your own load from
  `.agentfox/packs/` or an `agentfox.packs` entry point; only `stable` packs load unless
  `pack_maturity` (`AGENTFOX_PACK_MATURITY`) says otherwise.
- `agentfox policy packs list|show|test|validate|new`. Bare `agentfox policy packs` still
  prints the policy files on disk (now also `policy packs files`).
- A finding-type registry: `GET /api/findings/types` and `agentfox findings --types` list
  every type with its title, usual severity, meaning and owner; packs declare their own.
- A check registry: request-path checks register with `@check` from the capability
  that owns them, an `agentfox.checks` entry point or a pack.
- `mcp_tool_added_under_wildcard` finding (high): a registered MCP server added a tool
  that an existing wildcard grant already allows.
- `agentfox doctor` has a `legacy names` line listing every pre-rename `NOMETRIA_*`
  variable still set (in use, or set but not read) and any `nometria.toml` / `[nometria]`
  config in use.

### Removed

- The `nometria` Python package shim and the `nometria` console script. Import from `agentfox` (e.g. `agentfox.frameworks.langgraph`) and run `agentfox`. The `NOMETRIA_*` environment variables, `nometria.toml` and `x-nometria-*` headers are still read.

- The hidden pre-consolidation CLI names. `agentfox --help` shows thirteen verbs, and
  the old top-level names had kept running, hidden, with a "now called" hint. They no
  longer resolve. `agentfox hooks run` and `agentfox mcp serve` stay,
  because installed hook configs and MCP client configs call them. Where each old name
  lives now:

  | Old | New |
  |---|---|
  | `check` · `quickscan` | `scan` · `scan --sessions` |
  | `quickstart` · `version` · `seed` | `init` · `--version` / `admin version` · `admin seed` |
  | `analyse-action` | `test action` |
  | `eval run/gate/baseline/suites/online` · `eval drift` | `test …` · `report drift` |
  | `redteam run` · `redteam probes` | `test redteam` · `test probes` |
  | `audit verify` · `audit checkpoint` | `report verify` · `admin checkpoint` |
  | `evidence export` | `report evidence` |
  | `compliance status/risk/obligations/frameworks/board/review-packet` · `compliance review` | `report …` · `report signoff` |
  | `compliance sync/compute/validate` | `admin catalog …` |
  | `tools declare` · `tools set-triggers` · `tools list` | `declare tool` · `declare triggers` · `declare list tools` |
  | `access declare-scope` · `access declare-reference` | `declare scope` · `declare reference` |
  | `boundary set` · `boundary check` | `declare boundary` · `test boundary` |
  | `sources add` · `sources import` · `sources list` | `declare source` · `declare import-sources` · `declare list sources` |
  | `escalation set` · `escalation scan` | `declare escalation` · `report escalations` |
  | `entitlement principal` · `entitlement grant` · `entitlement report` | `declare principal` · `permit user` · `report entitlement` |
  | `capability grant/list/revoke` | `permit grant/list/revoke` |
  | `guardrails …` · `guardrails test` | `policy rules …` · `test rule` |
  | `proposals …` · `approvals …` | `policy proposals …` · `permit approvals …` |
  | `auth …` · `db …` · `users …` · `hooks …` | `admin auth …` · `admin db …` · `admin users …` · `admin hooks …` |
  | `mcp tools` | `admin mcp tools` |

### Changed

- **Nometria to AgentFox, environment and headers (stage A).** Everything the product
  writes and documents is now `AGENTFOX_*`, `agentfox.toml` / `[agentfox]` and
  `X-AgentFox-*`: the gateway's response headers (`X-AgentFox-Trace`, `-Verdict`,
  `-Effective-Verdict`, `-Applied-Verdict`, `-Would-Be-Verdict`, `-Decision`, `-Mode`,
  `-Latency-Ms`, `-Explain`, `-Streaming`, `-Degraded`), the finding webhook's
  (`X-AgentFox-Event`, `-Delivery`, `-Timestamp`, `-Signature`: **update a webhook
  receiver that verifies `X-Nometria-Signature`**), the FastAPI middleware's, and what the
  SDK, the CLI and the dashboard send. The pre-rename names still work as input:
  `NOMETRIA_*` variables, `NOMETRIA_CONFIG`, `nometria.toml` and a `[nometria]` table are
  read below the new names, and `x-nometria-*` request headers are accepted, with
  `x-agentfox-*` winning when a request carries both. The process logs one startup
  warning naming each legacy setting in use; the dashboard warns once per legacy
  variable. `render.yaml`, `deploy/`, the docs and the plugins use only the new names.
  The self-host blueprint now prompts for `AGENTFOX_AUDIT_SIGNING_KEY` instead of
  generating it, so a blueprint sync can never rotate an existing deployment's key.
  Renaming the hosted deployment: `docs/deployment/vercel-env-rename.md`.
- The shipped policies and the control catalog moved from `policies_data/` and
  `compliance_data/` into the capability packs (`packs/<id>/policies/`,
  `packs/compliance/catalog/controls/`). `compliance_dir` and `policies_dir` still
  override them, and are now unset by default. `agentfox policy packs` and
  `agentfox admin catalog validate` print the new paths.
- The dashboard's finding labels come from the registry. `budget_breach` now reads
  "Detector over budget" (it is a detector's latency budget); it read "Budget
  exceeded", which describes `budget_exhausted`.

- The Claude Code operator plugin moved from `harness/` to `plugins/claude-code/`, and its
  runtime-neutral parts (`AGENTS.md`, `skills/`, `reference/`) to `plugins/shared/`. The
  marketplace entry now points at `./plugins/claude-code`; the install command
  (`claude plugin install agentfox@agentfox`) is unchanged. A local clone uses
  `claude --plugin-dir ./plugins/claude-code`. The maintainer command
  `/agentfox:harness-check` is now `/agentfox:plugin-check`, the drift checker is
  `scripts/check_plugins.py`, and the docs page is `/docs/plugin` (`/docs/harness`
  redirects).
- Coding-agent harnesses are adapters behind one interface, `agentfox.harnesses`
  (registered through the `agentfox.harnesses` entry-point group). Claude Code is the only
  one; installed hooks (`agentfox hooks run --harness claude`) behave exactly as before.
- Accepting a changed MCP tool listing is now a two-person change. A changed definition is
  held and filed as an `mcp.tool.accept` change proposal; `McpGovernor.register_tools(...,
  accept_changes=True)` now requires `actor=` (the reviewer) and raises `ValueError`
  without one, and the change applies only when a second, different person approves.
  `POST /api/mcp-servers/{name}/tools` with `accept_changes` counts as the signed-in
  person's approval and needs the role that approves policy proposals. The result carries
  `held`, `accepted`, `awaiting_second_approver` and `proposals`.
- `McpCallBlocked`, raised by the MCP governor, is now an `agentfox.AgentFoxError` like
  every other refusal. It is still a `RuntimeError`.

## [0.3.1] - 2026-09-26

The first release published to PyPI, which is the whole point of it: 0.3.0 was
tagged before `release.yml` had a `pypi` job, so `pip install agentfox` has never
worked and the README's first command has been a `git+https` URL. From this tag
the package is on PyPI and the name is held.

Published through Trusted Publishing — PyPI mints a short-lived token from the
release workflow's OIDC identity, so there is no API token in the repository's
secrets, nothing to rotate, and nothing that keeps working if it leaks.

Also in this release, all of it since 0.3.0:

- A blocked tool call no longer leaves its trace reading `allow`. `Trace.verdict`
  was only ever written by the completion path, so every trace the tool-call path
  refused reported that nothing had happened.
- Twenty Guardrails AI Hub validators wrapped one-per-detector, each with its own
  key, telemetry and suppressions, reporting into this project's entity taxonomy —
  and with that project's own telemetry switched off, because enabling a check
  must not start exporting spans to a third party.
- The vendored gateway wheel carries two fixes it had been missing since 0.3.0.
- The latency probe measures the mechanism rather than the CI runner.

## [0.3.0] - 2026-09-25

The MVP described in the README. The package was declared `0.1.0` while every document
said `MVP v0.3`; they now agree on `0.3.0`, which is what `pyproject.toml`,
`src/agentfox/__init__.py`, `agentfox version` and the API's `/health` all report.

> Note for the maintainer: replace this heading with a release date when you tag
> `v0.3.0`. `.github/workflows/release.yml` refuses to publish unless the tag, the
> `pyproject.toml` version and `__version__` all match.

### Added

- **Containment that does not depend on detection.** Tools are declared with an impact
  tier (`read`, `write`, `high_impact`, `irreversible`), agents hold explicit capability
  grants with argument constraints, and every argument carries the provenance of where it
  came from. An irreversible tool called with an argument that originated in untrusted
  content is refused because of where the value came from, not because anything
  recognised the payload. Measured with every detector switched off; the result is in the
  README.
- **Policy engine** with three shipped packs, `baseline`, `tool-containment` and
  `eu-ai-act-high-risk`, each bindable in `observe` (records what it would have done) or
  `enforce`. `agentfox policy simulate` replays recorded traffic against a candidate
  policy and exits non-zero when the change would newly block production traffic.
- **Detector and scorer pipeline** across six surfaces (`input`, `output`, `tool_args`,
  `tool_result`, `memory_write`, `agent_message`), wrapping permissive OSS primitives as
  optional extras: Presidio for PII, NeMo Guardrails, Guardrails AI, Granite Guardian,
  garak and PyRIT for red-team probes, sqlglot for SQL action assurance. Every verdict
  carries the rule that produced it.
- **Tamper-evident audit chain** with a verifier (`agentfox audit verify`, exits 1 when
  broken) and signed checkpoints (`agentfox audit checkpoint`).
- **Compliance layer**: a control catalog, framework mappings, and evidence packages.
  Mappings ship labelled `DRAFT, UNVERIFIED, NOT LEGAL ADVICE`, because they were
  produced by engineers rather than reviewed by compliance counsel.
- **Ways to run it**: the `auto()` library patch, `agentfox serve` for the gateway and
  control-plane API, an MCP server, a LangGraph integration, and Docker Compose,
  Render and Fly deployment configs under `deploy/`.
- **CLI** covering setup and operation: `init`, `demo`, `serve`, `version`, `doctor`,
  `check`, `scan`, `tools`, `policy`, `agents`, `audit`, `evidence`, `compliance`,
  `eval`, `redteam`, `access`, `proposals`, `db`.
- **Dashboard** (Next.js, `dashboard/`) and a hosted playground that hands every visitor a
  throwaway sandbox running the same enforcement code.
- **Benchmarks** with committed result files: containment under total detector bypass,
  AgentDojo end to end, Crescendo trajectory, and PII. A nightly workflow re-measures the
  offline deterministic ones and fails when a published claim no longer matches.
- **Drift checks that fail CI rather than rot**: `scripts/api_routes.py --check` holds the
  API reference to the running app, `scripts/claims.py --check` holds every published
  number to its result file, and `harness/scripts/check_harness.py` holds the agent
  harness to the live command line.
- **Agent harness** (`harness/`) packaged as a Claude Code plugin.
- **Phase 0 improvement loop**: proposals, findings hygiene, label integrity and a
  scheduler, with scheduled red-teaming shipped disabled so a deployment opts in.
- **Deferred job queue** behind evidence export and red-team campaigns, and Alembic
  migrations, because a deployment that cannot be upgraded is not a deployment.

### Known limits

The README lists these in full and the product measures them rather than hiding them:
detection is a speed bump and not a defence, compliance mappings are draft, containment is
exactly as good as the tool declarations behind it, multi-tenancy is single-org and
enforced at the session, there is no live IdP or SSO, and text is the only modality.
`docs/status.md` reports live coverage computed by probe rather than asserted.
