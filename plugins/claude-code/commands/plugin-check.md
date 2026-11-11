---
description: Check the plugin markdown against the live CLI, repo paths and docs map
---
<!-- No allowed-tools on purpose. This is a maintainer command, run by hand from a checkout
     of the AgentFox repo, so a standing grant saves one approval and costs a broad one: any
     pre-approval here has to wildcard after `uv run` or an interpreter, which is exactly the
     shape this product tells other people not to ship. The user approves the call. -->

From the repo root, run `uv run python scripts/check/plugins.py`. If it reports
drift, fix each item in the plugin file it names (a shared file in `plugins/shared/`, then
`--write` to refresh the copies), following `plugins/STRUCTURE.md`: code
wins, and each fact has one home. Then re-run until it passes. Report what changed.
