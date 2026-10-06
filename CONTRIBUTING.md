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
Python suite, the four drift checks, the dashboard tests and the vendored-wheel freshness
rule. If it passes locally, the pull request will pass, except for the Docker build
(`just docker-smoke`, which needs Docker).

| Recipe | What it runs |
|---|---|
| `just setup` | `uv sync --extra pii --extra classifiers --extra otel --extra postgres --extra sql --extra dev` |
| `just test` | `uv run pytest -q` |
| `just test-fast` | `uv run pytest -q -x --ignore=tests/e2e --ignore=tests/repo` |
| `just lint` | `uvx ruff@0.15.7 check .` and `uvx ruff@0.15.7 format --check .` (`just fmt` applies them) |
| `just check` | `check_harness.py`, `api_routes.py --check`, `docs_reference.py --check`, `claims.py --check` |
| `just regen` | rewrites the generated files those checks compare against |
| `just dashboard` | `npm ci`, `npm test` and `tsc --noEmit` in `dashboard/` |
| `just wheels` | rebuilds `api/vendor/` and `demo/redteam-live-lang/vendor/` |
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

## Tests

`tests/` mirrors `src/agentfox/`: a change to `src/agentfox/platform/policy/engine.py` is tested in
`tests/platform/policy/`, so `just test-fast tests/platform/policy` is the inner loop. The whole suite is over
3,200 tests and takes most of 20 minutes on a laptop, because every test builds its own
database; run it (`just test`) before you push. Two directories are different:

- `tests/e2e/` runs the request path end to end across packages: the gateway API (through
  the `client` fixture, FastAPI's test client), RBAC, the SDK and security regressions.
- `tests/repo/` tests the repository rather than the package: published claims, the docs
  site, the harness, the vendored wheels, the installed layout.

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
| route tables in `docs/architecture/api-spec.md` | `uv run python scripts/api_routes.py --write` | `api_routes.py --check` |
| `dashboard/lib/reference/cli.json`, `api.json` | `uv run python scripts/docs_reference.py --write` | `docs_reference.py --check`, which also resolves every `agentfox …` command shown on a docs page |
| `docs/status.md` | `uv run python scripts/coverage.py --write` | regenerated, not checked |
| `docs/design/coverage-map.md` | `uv run python scripts/probe/run.py --md > docs/design/coverage-map.md` | regenerated, not checked |

Two more checks bind prose to evidence:

- **Published numbers.** [`benchmarks/claims.yaml`](benchmarks/claims.yaml) binds every quoted
  benchmark figure to the result file it came from. Change a number by re-running the
  benchmark and committing the result; `claims.py --check` confirms the prose agrees. A
  figure in the README, `benchmarks/`, `docs/` or on the website must be bound.
- **The harness and the docs map.** `harness/scripts/check_harness.py` checks that every
  command and path the agent harness names exists, and that every tracked `.md` file is
  classified in [`harness/reference/docs-map.md`](harness/reference/docs-map.md). A new doc
  gets a row there and in [docs/README.md](docs/README.md).

If one of these fails, the document is wrong, not the check.

## Vendored wheels

`api/` (the Vercel deployment of the gateway) and `demo/redteam-live-lang/` deploy a wheel
committed in their `vendor/` directories, not the source tree. A change under
`src/agentfox/` must rebuild both wheels in the same commit, or production serves stale
code. The pre-commit hook (`scripts/rebuild_vendored_wheels.py`) does this for you, and CI's
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
- **No internal tracking codes in new code.** Identifiers such as `P3-4`, `PL-7`, `F8.3` or
  `I-2` mean nothing to a new reader. Much existing code carries them (they map to
  [docs/design/PRD.md](docs/design/PRD.md) and [docs/design/traceability.md](docs/design/traceability.md));
  do not add more, and drop them when you rewrite a docstring anyway. Control identifiers
  that appear in the product's output (`NOM-IAM-02`) are data, not tracking codes, and stay.
