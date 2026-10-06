---
description: Check the plugin markdown against the live CLI, repo paths and docs map
allowed-tools: Bash(uv run python scripts/check_plugins.py*) Bash(python* scripts/check_plugins.py*)
---
From the repo root, run `uv run python scripts/check_plugins.py`. If it reports
drift, fix each item in the plugin file it names (a shared file in `plugins/shared/`, then
`--write` to refresh the copies), following `plugins/STRUCTURE.md`: code
wins, and each fact has one home. Then re-run until it passes. Report what changed.
