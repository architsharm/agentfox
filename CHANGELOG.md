# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Published benchmark numbers do not live here. They live in the result files under
`benchmarks/`, and `scripts/claims.py --check` binds every number quoted in a document to
the file it came from.

## [Unreleased]

Nothing yet.

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
