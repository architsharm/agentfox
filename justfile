# One command per job. `just ci` runs what .github/workflows/ci.yml runs, in the same
# configuration, so a green `just ci` means a green pull request (Docker build aside;
# see `docker-smoke`). Install just with `brew install just`, `cargo install just` or
# `uvx --from rust-just just`; every recipe is plain shell, so CONTRIBUTING.md lists
# the same commands for anyone without it.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Pinned to the version in ci.yml: `ruff format` output changes between releases.
ruff := "uvx ruff@0.15.7"

# The import contracts in pyproject's [tool.importlinter], at ci.yml's pinned version.
imports := "PYTHONPATH=src uvx --from import-linter==2.15 lint-imports"

# Exactly CI's extras. Not --all-extras: it pulls transitive versions that break tests.
extras := "--extra pii --extra classifiers --extra otel --extra postgres --extra sql --extra dev"

# List the recipes.
default:
    @just --list

# Create .venv with the extras CI tests against.
setup:
    uv sync {{extras}}

# The whole Python suite, as CI runs it.
test *args:
    uv run pytest -q {{args}}

# Stop at the first failure, skipping tests/e2e and tests/repo. The full suite is
# ~3,200 tests and takes most of 20 minutes serially (each test builds its own
# database), so pass the directory you changed: `just test-fast tests/platform/policy`.
test-fast *args:
    uv run pytest -q -x --ignore=tests/e2e --ignore=tests/repo {{args}}

# Ruff rules, formatting and the import contracts (layers), at CI's pinned versions.
lint:
    {{ruff}} check .
    {{ruff}} format --check .
    {{imports}}

# Apply ruff's fixes and formatting.
fmt:
    {{ruff}} check --fix .
    {{ruff}} format .

# The drift checks: docs, reference, published numbers and the demo kit copy against the code.
check:
    uv run python scripts/check_plugins.py
    uv run python scripts/check/demo_kit.py
    uv run python scripts/api_routes.py --check
    uv run python scripts/docs_reference.py --check
    uv run python scripts/claims.py --check

# Regenerate every generated file the checks above compare against.
regen:
    uv run python scripts/api_routes.py --write
    uv run python scripts/docs_reference.py --write
    uv run python scripts/coverage.py --write

# Dashboard: clean install, vitest, and a type check (the type check is not in CI).
dashboard:
    cd dashboard && npm ci && npm test && npx tsc --noEmit --incremental false

# Fail if src/agentfox/ changed against BASE without the vendored wheels (CI's rule).
wheel-freshness base="origin/main":
    #!/usr/bin/env bash
    set -euo pipefail
    changed="$(git diff --name-only "{{base}}"...HEAD)"
    if echo "$changed" | grep -q '^src/agentfox/' \
       && ! echo "$changed" | grep -qE '^(api|demo/redteam-live-lang)/vendor/.*\.whl$'; then
        echo "src/agentfox/ changed but the vendored wheels were not rebuilt: run 'just wheels'"
        exit 1
    fi
    echo "vendored wheels: fresh relative to {{base}}"

# Everything CI runs except the Docker build.
ci: lint test check dashboard wheel-freshness

# Rebuild both vendored wheels (api/ and the live demo deploy these, not src/).
wheels:
    uv build --wheel --out-dir api/vendor
    uv build --wheel --out-dir demo/redteam-live-lang/vendor

# CI's docker-smoke job: build deploy/Dockerfile up to the `deps` stage.
docker-smoke:
    docker build -f deploy/Dockerfile --target deps .

# Gateway and control-plane API on 127.0.0.1:8080.
serve *args:
    uv run agentfox serve {{args}}

# The offline walkthrough, against a throwaway database so it never touches yours.
demo:
    AGENTFOX_DATABASE_URL="sqlite:///${TMPDIR:-/tmp}/agentfox-demo.db" uv run agentfox init
    AGENTFOX_DATABASE_URL="sqlite:///${TMPDIR:-/tmp}/agentfox-demo.db" uv run agentfox demo
