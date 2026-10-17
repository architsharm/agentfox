# ADR 0001: Repository structure

**Status:** Accepted, 2026-10-07. Records the decisions in
[structure-proposal.md](../design/structure-proposal.md) §9 and what phases 0 to 5 built on them.

## Context

Two changes had to become cheap: governing another coding agent (a *harness*) and adding a
business use case (payments, support, a compliance framework). Before the restructure, a harness
touched about eight Python files and a use case was spread over six places. Layers leaked through
seven package cycles, "harness" meant three different things, and outside `src/` the benchmark
folders did not match the claims they prove, the two demos were diverged forks of each other and
the dashboard was three sites in one flat tree. The proposal has the evidence and the survey of
how other projects solved the same problems.

## Decision

1. **One distribution, in layers.** `src/agentfox/` stays one Python package, layered
   `core` < `platform` < `capabilities` < `runtime` < `frameworks`, `exporters`, `harnesses`,
   `hooks`, `fixtures` < `apps`. A layer imports only layers below it, and `core` imports nothing
   outside itself. import-linter contracts in `pyproject.toml` enforce this in CI and in
   `just lint`; the few exceptions are named in the contract, not tolerated silently. A uv
   workspace split stays possible later; today it would add release overhead without helping a
   reader.
2. **Capabilities live under `capabilities/`.** Detection, judgment, grounding, containment,
   business, discovery, evaluation, improvement, monitoring and compliance each get one folder.
3. **A harness is a coding agent we govern, and nothing else.** Each one is a folder under
   `src/agentfox/harnesses/<name>/` implementing the `HarnessAdapter` protocol in
   `harnesses/base.py`, tested by the shared conformance suite against payloads captured from
   the real tool. Adapters register through the `agentfox.harnesses` entry point, built-in or not.
4. **Operator plugins live in `plugins/`.** The Claude Code plugin is `plugins/claude-code/`;
   its runtime-neutral parts (AGENTS.md, skills, reference) are `plugins/shared/`, copied into
   each plugin because a plugin cannot load files outside its directory, with
   `scripts/check/plugins.py` failing CI on drift.
5. **Business use cases become packs.** A pack is a directory of data (policies, controls,
   ladders, probes, golden cases, fixtures) plus optional checks registered by decorator, loaded
   from the built-in `packs/`, a project's `.agentfox/packs` or the `agentfox.packs` entry point.
   The Enforcer runs the checks it finds in a check registry instead of a hard-coded tuple.
6. **The repository outside `src/` mirrors the same idea.** One benchmark folder per claim
   family, named as the claim ids in `benchmarks/claims.yaml` (shared helpers in
   `benchmarks/_common`, scripts run as `python -m benchmarks.<family>.<script>`); one demo kit
   shared by the framework demos; scripts split into `gen/`, `check/` and `ops/`; the dashboard
   organised with Next.js route groups so that no URL changes; deploy configuration in
   `deploy/` except where a platform reads a fixed path (`render.yaml` and `api/` at the root).
7. **Deferred until the restructure is done:** new harnesses (Codex first, then Cursor);
   building wheels at deploy time instead of committing them to `api/vendor/` and the demo's
   `vendor/`; the rest of the product rename (the pre-rename environment-variable fallback,
   console script and request headers), because production environments still set them.
   The rename has since been finished: those fallbacks are gone.

## Consequences

- A new harness is one folder and its fixtures; a new use case is one pack directory. Neither
  edits core.
- A wrong import fails CI with the contract it broke, so the layering cannot erode quietly.
- Moving a file between layers is a deliberate act: it either respects the order or adds a
  named exception that someone has to justify.
- Copies exist where a platform forces them (the plugin's shared files, the demo kit inside the
  Vercel-deployed demo, the vendored wheels). Each has a check that fails on drift.
- Every website URL stayed the same through the restructure; old documentation paths that did
  move (`/docs/harness`) redirect permanently.

## Alternatives considered

- **A uv workspace of several distributions** (`agentfox-core`, `agentfox-server`, one per
  harness). Rejected for now: the contributor count does not justify the release overhead.
- **Keeping capabilities at the top of the package.** Rejected: nothing told a reader which
  folders were capabilities and which were platform, so imports went in every direction.
- **Symlinking `plugins/shared` into each plugin.** Rejected: Claude Code dereferences symlinks
  only for a git-hosted marketplace, so a local install would silently lose them.
- **Building the vendored wheels at deploy time now.** Deferred, not rejected: it removes a class
  of merge conflicts and the pre-commit hook, but changes two production deploys mid-restructure.
