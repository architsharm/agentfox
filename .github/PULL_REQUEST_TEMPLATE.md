# What this changes

Say what breaks without it.

# Checks

[CONTRIBUTING.md](../blob/main/CONTRIBUTING.md) has the detail. `just ci` runs everything CI
runs; these are the Python checks, and a red one will not merge:

```bash
uvx ruff@0.15.7 check . && uvx ruff@0.15.7 format --check .
pytest -q
python scripts/gen/api_routes.py --check
python scripts/gen/docs_reference.py --check
python scripts/check/claims.py --check
python scripts/check/plugins.py
```

- [ ] `ruff check` and `ruff format --check` pass at CI's pinned version.
- [ ] `pytest -q` passes.
- [ ] `scripts/gen/api_routes.py --check` passes, or Appendix C was regenerated with it.
- [ ] `scripts/gen/docs_reference.py --check` passes, or the docs reference was regenerated with
      `--write`, if the CLI, the API or a docs page changed.
- [ ] `scripts/check/claims.py --check` passes. If a published number moved, the benchmark was
      re-run and its result file is in this PR. Numbers are not edited by hand.
- [ ] `scripts/check/plugins.py` passes, if `plugins/` or the CLI changed (`--write`
      refreshes the Claude Code plugin's copies of `plugins/shared/`).
- [ ] If `src/agentfox/` changed, the vendored wheels in `api/vendor/` and
      `demo/redteam-live-lang/vendor/` were rebuilt in the same commit. The pre-commit
      hook does this for you (`uvx pre-commit install`); CI fails the push otherwise,
      because `api/` and the live demo deploy the wheel, not an editable install.
- [ ] A test that would have caught the bug, if this is a fix.

# Anything a reviewer should know

Behaviour that changed, a limit that moved, or a decision you were unsure about.
