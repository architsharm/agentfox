# Contributing

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems
do not go through pull requests or public issues: see [SECURITY.md](SECURITY.md).

## Setting up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Do not install with `--all-extras`. It pulls transitive versions that break a handful of
tests. The extras this project is tested with are in the CI workflow.

Before changing behaviour, read the [high-level design](docs/architecture/high-level-design.md).
[docs/README.md](docs/README.md) indexes the rest of the design material: requirements, threat
model, traceability and how benchmarks are measured. User-facing documentation is the website's,
and its source is in `dashboard/app/docs/`.

## Before you open a pull request

```bash
pytest -q
python scripts/api_routes.py --check
python scripts/claims.py --check
python harness/scripts/check_harness.py
```

Those last three are not style checks. They fail when the documentation stops matching the
code: the API reference is generated from the running app, every published benchmark number
is bound to the result file it came from, and the agent harness is checked against the live
command line. If one fails, the document is wrong, not the check.

## Two things that will surprise you

**Vendored wheels.** `api/` and `demo/redteam-live-lang/` deploy a prebuilt wheel rather
than an editable install, so a change to `src/agentfox/` that skips the rebuild ships stale
code. A pre-commit hook rebuilds both wheels, and CI fails a push that changed the source
without them:

```bash
uvx pre-commit install
```

**Numbers are evidence, not prose.** Do not edit a benchmark figure in a document. Re-run
the benchmark, commit the result file, and let `scripts/claims.py` confirm the two agree.

## What makes a change easy to accept

Say what breaks without it. Add the test that would have caught the bug. Keep the honesty:
this project publishes the numbers where it loses, and a change that quietly removes a
limit or rounds a result up will be sent back.
