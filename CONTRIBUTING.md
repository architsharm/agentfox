# Contributing

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems do
not go through pull requests or public issues: see [SECURITY.md](SECURITY.md).

## Set up

You need [uv](https://docs.astral.sh/uv/), Node 20 for the dashboard, and optionally
[just](https://github.com/casey/just).

```bash
git clone https://github.com/architsharm/agentfox.git && cd agentfox
just setup        # uv sync with exactly the extras CI uses
just test-fast tests/platform/policy   # the tests for what you changed; `just test` for everything
```

Do not install with `--all-extras`: it pulls transitive versions of anthropic, langchain and
litellm that break tests. The extras CI tests against are the ones `just setup` installs.

Then install the pre-commit hook, which rebuilds the vendored wheels when you change the
package (see [below](#vendored-wheels)):

```bash
uvx pre-commit install
```

## The contract: `just ci`

`just ci` runs what [CI](.github/workflows/ci.yml) runs: ruff at CI's pinned version, the
Python suite, the drift checks, the dashboard tests and the vendored-wheel freshness
rule. If it passes locally, the pull request will pass, except for the Docker build
(`just docker-smoke`, which needs Docker).

| Recipe | What it runs |
|---|---|
| `just setup` | `uv sync --extra pii --extra classifiers --extra otel --extra postgres --extra sql --extra dev` |
| `just test` | `uv run pytest -q` |
| `just test-fast` | `uv run pytest -q -x --ignore=tests/e2e --ignore=tests/repo` |
| `just lint` | `uvx ruff@0.15.7 check .`, `uvx ruff@0.15.7 format --check .` (`just fmt` applies them) and the import contracts, `PYTHONPATH=src uvx --from import-linter==2.15 lint-imports` |
| `just check` | `scripts/check/plugins.py`, `scripts/check/demo_kit.py`, `scripts/gen/api_routes.py --check`, `scripts/gen/docs_reference.py --check`, `scripts/check/claims.py --check` |
| `just regen` | rewrites the generated files those checks compare against |
| `just dashboard` | `npm ci`, `npm test` and `tsc --noEmit` in `dashboard/` |
| `just wheels` | rebuilds `api/vendor/` and `demo/redteam-live-lang/vendor/` |
| `just new-harness <name>` | scaffolds `src/agentfox/harnesses/<name>/` from `scripts/templates/harness/` |
| `just serve` / `just demo` | the gateway on :8080; the offline walkthrough on a throwaway database |

Without `just`, each recipe is a plain command in the [`justfile`](justfile); copy it from
there. Everything Python runs through `uv run`, so there is no virtualenv to activate.

## Find your way around

Read [ARCHITECTURE.md](ARCHITECTURE.md) first. It has the domain model, a tool call traced
through the code, a map of every package, the invariants you must not break, and where to
start for the common changes (a detector, a policy condition, a CLI command, an HTTP route, a
docs page, a benchmark). [docs/README.md](docs/README.md) indexes the deeper design material.
User-facing documentation is the website, [useagentfox.com/docs](https://useagentfox.com/docs),
and its source is `dashboard/app/docs/`.

## Where code goes

`src/agentfox/` is layered, and a layer imports only the layers below it
([ARCHITECTURE.md, Layers](ARCHITECTURE.md#layers)). `just lint` runs `lint-imports`,
which fails on an import that points up. To decide where new code goes, ask what it
needs to import:

| It is… | It goes in | It may import |
|---|---|---|
| A setting, a table, a constant several layers share | `core/` | nothing else in `agentfox` |
| Something every capability records or reads: the audit chain, findings, policy, the registry, identities and grants, model providers, the job store | `platform/<package>/` | `core` |
| A check, a scan, an analysis: a detector, a grounding or containment check, an eval, a monitor | `capabilities/<capability>/` | `core`, `platform`, other capabilities |
| Part of how a call is decided | `runtime/` | everything below |
| A way in from an application framework (an SDK, a middleware, a governor) | `frameworks/` | everything below |
| A coding agent AgentFox governs through its hooks | `harnesses/<name>/` (see below) | everything below; nothing else imports it |
| A way out to another system (traces, metrics, a SIEM) | `exporters/` | everything below |
| A command, a route, a report, a job handler: anything that wires capabilities to a user | `apps/` | everything |

Test files mirror the package: `src/agentfox/capabilities/grounding/entitlement.py` is
tested in `tests/capabilities/grounding/`. If a new import would point up a layer, the
code is in the wrong place, or it needs a hook the lower layer calls (see
`runtime/trace_exporters.py`); adding an `ignore_imports` entry to `pyproject.toml`
needs a reason and a TODO saying what removes it.

### Add a harness

A harness is a coding agent AgentFox governs through its hooks (Claude Code today). It is
one folder, `src/agentfox/harnesses/<name>/`, and touches nothing else in `src/`.
`just new-harness <name> "Display Name"` writes the folder from `scripts/templates/harness/`
(an adapter skeleton whose capabilities all start as "cannot", and a fixtures README):

1. **`adapter.py`** implements `harnesses/base.py:HarnessAdapter` and exposes `ADAPTER`:
   `parse` (raw payload → `AgentEvent`), `render` (`Decision` → exact stdout, stderr and exit
   code, after `base.downgrade`), `install`, `hooked_agents`, `mcp_config_paths`,
   `transcripts`. Its capability matrix says, per event, what a reply can do there, with the
   evidence and harness version for each claim. Leave a claim out rather than guess it.
2. **`tools.py`**: the harness's tool names → canonical names, and its built-in tools'
   impacts. **`install.py`**: where it reads hooks, merged idempotently.
3. **`fixtures/<kind>.json`**: hook payloads captured from the real tool (a temporary hook
   that writes its stdin to a file is enough), never hand-written; `<kind>.expected.json`
   beside each records the parsed event and the exact output per decision.
4. **Register** the entry point under `[project.entry-points."agentfox.harnesses"]` in
   `pyproject.toml`, and in `BUILTIN` in `harnesses/__init__.py` for source checkouts.
5. **Run `pytest tests/harnesses`.** The conformance suite finds the adapter in the registry
   and checks parsing, rendering, the capability matrix against `render`, and install
   idempotence and merging.

## Tests

`tests/` mirrors `src/agentfox/`: a change to `src/agentfox/platform/policy/engine.py` is tested in
`tests/platform/policy/`, so `just test-fast tests/platform/policy` is the inner loop. The whole suite is over
3,200 tests and takes most of 20 minutes on a laptop, because every test builds its own
database; run it (`just test`) before you push. Two directories are different:

- `tests/e2e/` runs the request path end to end across packages: the gateway API (through
  the `client` fixture, FastAPI's test client), RBAC, the SDK and security regressions.
- `tests/repo/` tests the repository rather than the package: published claims, the docs
  site, the plugins, the vendored wheels, the installed layout.
- `tests/harnesses/conformance.py` is the harness conformance suite: every adapter in the
  registry, against the payloads captured in its `fixtures/`.

Every test gets its own on-disk SQLite database, with egress off and a fixed signing key
(`tests/conftest.py`). The suite needs no network, no API key and no model weights: the
`echo` provider makes the whole enforcement path run offline. Model-backed detectors report
themselves unavailable until their weights are fetched deliberately (`agentfox doctor`
names the missing ones).

A fix comes with the test that would have caught it.

## Generated files and their checks

These files are produced from the code. Edit the source, regenerate, and commit both; never
edit the output by hand.

| File | Regenerate | Checked by |
|---|---|---|
| route tables in `docs/architecture/api-spec.md` | `uv run python scripts/gen/api_routes.py --write` | `api_routes.py --check` |
| `dashboard/lib/generated/reference/cli.json`, `api.json` | `uv run python scripts/gen/docs_reference.py --write` | `docs_reference.py --check`, which also resolves every `agentfox …` command shown on a docs page |
| `docs/status.md` | `uv run python scripts/gen/coverage.py --write` | regenerated, not checked |
| `docs/design/coverage-map.md` | `uv run python scripts/probe/run.py --md > docs/design/coverage-map.md` | regenerated, not checked |
| `dashboard/lib/generated/coverage.json` | `uv run python scripts/probe/run.py --json > dashboard/lib/generated/coverage.json` | `tests/repo/test_coverage_page_data.py` (every taxonomy scenario is published) |

Two more checks bind prose to evidence:

- **Published numbers.** [`benchmarks/claims.yaml`](benchmarks/claims.yaml) binds every quoted
  benchmark figure to the result file it came from. Change a number by re-running the
  benchmark and committing the result; `claims.py --check` confirms the prose agrees. A
  figure in the README, `benchmarks/`, `docs/` or on the website must be bound.
- **The plugins and the docs map.** `scripts/check/plugins.py` checks that every command
  and path the operator plugins name exists, that every tracked `.md` file is classified in
  [`plugins/shared/reference/docs-map.md`](plugins/shared/reference/docs-map.md), and that
  the Claude Code plugin's copies of `plugins/shared/` (AGENTS.md, skills, reference) match
  their originals. Edit `plugins/shared/`, then `uv run python scripts/check/plugins.py
  --write` refreshes the copies. A new doc gets a row in the docs map and in
  [docs/README.md](docs/README.md).

If one of these fails, the document is wrong, not the check.

## Vendored wheels

`api/` (the Vercel deployment of the gateway) and `demo/redteam-live-lang/` deploy a wheel
committed in their `vendor/` directories, not the source tree. A change under
`src/agentfox/` must rebuild both wheels in the same commit, or production serves stale
code. The pre-commit hook (`scripts/check/rebuild_vendored_wheels.py`) does this for you, and CI's
`vendored-wheel-freshness` job fails a push that skipped it.

`git commit --no-verify` skips the hook. If you use it on a commit that touches
`src/agentfox/`, run `just wheels` and commit the result yourself.

Building the deploys from source instead of committed wheels is planned and not done yet; until it
is, this rule stands.

## Branches, commits and pull requests

- **One branch per pull request.** Start each from an up-to-date `main`. Do not push new
  work to a branch whose pull request has merged: those commits land in no pull request.
- Commit subjects are short and imperative with a conventional prefix where one fits
  (`fix:`, `docs:`, `test:`, `feat:`). The body says what was wrong and why the change is
  right.
- The [pull request template](.github/PULL_REQUEST_TEMPLATE.md) asks what breaks without the
  change. Answer it; it is the first thing a reviewer reads.
- Keep the honesty. This project publishes the numbers where it loses. A change that quietly
  removes a stated limit or rounds a result up will be sent back.
- User-visible changes get a line in [CHANGELOG.md](CHANGELOG.md).

## Docstrings and comments

Going forward:

- A docstring says **what the code does and why**: the invariant it keeps, the failure it
  prevents, the trade-off it makes. That is the part a reader cannot recover from the code.
- **History belongs in git and the CHANGELOG**, not in the source. "This used to…", "found
  by…", dates and incident narratives go in the commit message.
- **No internal tracking codes.** Identifiers such as `P3-4`, `PL-7`, `F8.3` or `I-2` mean
  nothing to a new reader; they belong in [docs/design/PRD.md](docs/design/PRD.md) and
  [docs/design/traceability.md](docs/design/traceability.md), not in `src`. Control
  identifiers that appear in the product's output (`NOM-IAM-02`) are data, not tracking
  codes, and stay.
