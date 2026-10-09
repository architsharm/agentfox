# Codex CLI fixtures

**These payloads were built, not captured.** No Codex binary has run the AgentFox hook
yet. Each `<kind>.json` follows Codex's generated hook input schema
(`codex-rs/hooks/schema/generated/<event>.command.input.schema.json`, release
`rust-v0.162.0`) and the values Codex's own integration tests assert on
(`codex-rs/core/tests/suite/hooks.rs`); each `source` field says which. The adapter's
capability rows are marked `SOURCE` for the same reason.

Replace them with captured payloads the first time Codex runs through the hook:

1. In a scratch project, add a `.codex/hooks.json` whose command tees stdin to a file
   (`tee -a /tmp/codex-hook.jsonl > /dev/null; echo '{}'`) for `UserPromptSubmit`,
   `PreToolUse` and `PostToolUse`, and trust it with `/hooks`.
2. Run `codex exec "Run the shell command: echo hello"`.
3. Copy each payload into `<kind>.json`, anonymise the home directory to `x`, regenerate
   `<kind>.expected.json`, and review every changed line before committing.
4. Then re-probe the rows in `adapter.py` (deny one sentinel command, allow the rest)
   and move them from `SOURCE` to `LIVE_PROBE`.

- `<kind>.json`: the raw payload the hook receives.
- `<kind>.expected.json`: the `AgentEvent` it must parse to, and the exact stdout, stderr
  and exit code each decision and daemon verdict must render to.

`tests/harnesses/conformance.py` runs every registered adapter against these files;
`tests/harnesses/codex/test_codex.py` runs the end-to-end cases (install, then allowed,
refused, held and post-tool payloads through a real daemon).
