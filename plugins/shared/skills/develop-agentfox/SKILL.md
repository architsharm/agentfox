---
name: develop-agentfox
description: Covers contributing to the AgentFox codebase itself. It sets up the exact dev environment, runs tests, respects the vendored-wheel and migration rules, regenerates generated docs, keeps the plugins in sync, and follows commit conventions. Use when changing anything under src/, dashboard/, migrations/, benchmarks/ or docs/ in this repository.
---

# Develop AgentFox

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

## 1. Environment: use exactly these extras

```bash
uv sync --extra pii --extra classifiers --extra otel --extra postgres --extra sql --extra dev
```

**Never `--all-extras` or `--extra all`.** They pull in `anthropic`, `langchain` and `litellm`
transitively, and `tests/frameworks/autoguard/test_autoguard.py` asserts those are absent. If a cluster of
"missing library" tests fails, run `uv pip list | grep -E 'anthropic|langchain|litellm'`
before suspecting a regression. Demo and `llm-guard` dependencies go in separate venvs.

## 2. Tests

```bash
uv run pytest -q                      # fully offline; every test gets its own SQLite DB
uv run pytest tests/<area> -q         # while iterating, e.g. tests/runtime
(cd dashboard && npm test)            # vitest
uv run ruff check .                   # not enforced in CI, but keep it clean
```

Fixtures live in `tests/conftest.py`: `session`, `seeded`, `enforcer`, `client`, and
`as_user(email)`. Tests must stay offline (NFR-9), with no network and no model weights.

## 3. Rules that have caused production incidents

1. **Vendored wheels.** Two deploys install the package from a locally built wheel,
   in a `vendor/` directory under `api/` and under `demo/redteam-live-lang/`. Those
   directories are build output and are not in the repository — each carries its own
   `.gitignore` of `*` — so the paths are written here in prose rather than as repo
   paths, which is also why scripts/check/plugins.py cannot resolve them. Install the hook with
   `uvx pre-commit install`; it rebuilds them when `src/agentfox/` changes. Without the hook:
   `uv build --wheel --out-dir api/vendor && uv build --wheel --out-dir demo/redteam-live-lang/vendor`.
   CI's `vendored-wheel-freshness` job fails otherwise.
2. **Migrations before code.** A model change needs an Alembic revision in `migrations/`
   (`alembic revision --autogenerate -m "<slug>"`), a tested downgrade, and a deploy that runs
   `agentfox admin db upgrade` before the new wheel ships.
3. **Offline by default.** A new dependency is an optional extra unless it's pure-Python and
   tiny. Check `docs/design/oss-register.md` and update `THIRD_PARTY_NOTICES.md`.

## 4. Docs and plugins: same commit

| You changed | Also update |
|---|---|
| a CLI command or flag (`src/agentfox/apps/cli/`) | `plugins/shared/reference/cli.md`; BLK commands also `plugins/claude-code/scripts/guard_blocking_commands.py` |
| a `AGENTFOX_*` setting | `plugins/shared/reference/config.md` |
| a gateway route | `plugins/shared/reference/http-api.md` (and ideally Appendix C) |
| the policy schema or shipped packs | `plugins/shared/reference/policy-schema.md` |
| fixed a known issue | delete its entry in `plugins/shared/reference/known-issues.md` |
| a requirement's implementation | `docs/design/traceability.md` |
| added a doc anywhere | `plugins/shared/reference/docs-map.md` |
| a benchmark number that a doc quotes | `benchmarks/claims.yaml`; `scripts/check/claims.py --check` fails CI if a quote drifts from its result |

Then run:

```bash
uv run python scripts/check/plugins.py --write
uv run python scripts/gen/coverage.py --write           # regenerates docs/status.md
```

## 5. Commits

Use `type(scope): subject (REQ-ID)`, for example `fix(guardrails): … (P9-11)`. Wheel-only
commits are `rebuild(api)` or `rebuild(demo)`. In the body, give the root cause and what
changed, and end with what you verified ("full pytest suite: N passed").
[reference/glossary.md](../../reference/glossary.md) decodes the IDs.
