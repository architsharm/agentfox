---
title: Known issues an agent must work around
layer: reference
audience: agents
source_of_truth: this file — delete an entry in the same commit that fixes it
verified_against: branch claude/improvement-loop-phase0, 2026-09-16
---

# Known issues

Each entry: what breaks, how to work around it, where the fix belongs. When you fix one in
`src/`, delete its entry here in the same commit.

## CLI behaviour that surprises agents

1. **`tool-containment` enforces from the first `init`.** This is by design, and `init` now
   says so. Tool calls with tainted arguments, denied capabilities, runaway loops and
   destructive cascades are escalated or blocked from the start. Check with `agentfox policy list`.
2. **`agentfox demo` writes demo agents, findings and an evidence package** into whatever DB
   `NOMETRIA_DATABASE_URL` points at. It restores `baseline`'s mode when it finishes, but
   the data stays. Run it against a scratch DB.
3. **`agentfox admin seed` creates agent keys only on the first seed**, and masks them unless
   `--show-keys` is passed. Never paste a full key back to the user or into a file.

Fixed on 2026-09-15 and removed from this list: the misleading `init` message,
`agentfox.toml` never being read, crashes on a fresh DB, `doctor --json` exit codes,
`scan mcp` silently scanning the fixture, `guardrails compile --apply`, the
`entitlement report` hint, the `compliance status --verbose` filter, the `policy effective`
environment default, and Ctrl-C handling.

## Improvement loop and scheduled work

1. **Canaries now wait an hour between steps by default.** `canary/advance` holds until
   `min_dwell_seconds` has passed. Pass `min_dwell_seconds: 0` when starting a canary in a
   demo or test. Scheduled advancement runs hourly, but only as often as the cron actually
   fires. On a once-a-day cron each step takes at least a day.
2. **A canary now also rolls back when the candidate blocks much less than stable.** A
   deliberate loosening has to raise `max_block_rate_drop` when it starts the canary.
3. **Recording guardrail feedback needs a named person.** `record_feedback` refuses a blank
   actor, and auditors get a 403 from the feedback route.
4. **Threshold proposals are never applied by the loop.** Raising a rule's `min_score` loosens it,
   so `proposals from-labels` only files proposals, each with a replay proof and scoped to the
   agents the labels came from. A person approves and applies each one.
5. **Undoing a tightening needs a person.** `proposals rollback --automated` is refused for a
   change that tightened a control, because reverting it would loosen one.

## `agentfox.auto()` limits

What it governs: OpenAI, Anthropic, LiteLLM and LangChain `invoke` calls, sync and async,
streamed or not. The default mode follows each policy's own mode (`reference/sdk.md`). What
it still doesn't do:

- **Streaming is checked at the end.** A streamed response is checked when it finishes, so
  chunks already delivered can't be recalled. Cutting a stream mid-response needs the gateway
  with `NOMETRIA_STREAMING_MODE=windowed`.
- **Some stream helpers aren't governed.** Anthropic's `messages.stream()`, LangChain
  `stream`/`astream`, and OpenAI `with_raw_response`/`with_streaming_response` aren't wrapped.
- **Stream type checks fail.** The wrapped stream isn't an instance of the SDK's own stream
  classes, so `isinstance` checks against them fail.
- **Redactions don't reach the provider.** A pre-flight redaction is recorded, but the
  in-process call still sends the original text. Use the SDK or the gateway when inbound
  redaction must reach the provider.
- **Fail-closed covers pre-flight only.** `NOMETRIA_FAIL_MODE=closed` refuses a call whose
  pre-flight crashed. A post-flight crash still lets the response through, with a warning.
- **Async paths block briefly.** Database work there is synchronous and blocks the event loop
  for a moment.
- **Opt-in model detectors load in the background in your own process.** The gateway calls
  `warm_all()` at startup; `agentfox.auto()`, `AgentFox(...)` and `AgentFoxGuard(...)` start the
  same warm-up on a background thread. Calls made in the first seconds, before the weights are
  loaded, can still time out; call `agentfox.capabilities.detection.warm_all()` to wait. Warm,
  `injection.classifier` costs about 43ms per short prompt; long prompts still time out.
- **Frameworks are covered through their clients.** CrewAI, LlamaIndex, AutoGen and LangGraph
  are governed only through the clients they call. `agentfox.state().framework_routes()` shows
  which are covered.

## Docs that disagree with the code (code wins)

- Coverage numbers differ across `README.md`, `docs/design/failure-modes.md`, `docs/status.md` and
  `docs/design/coverage-map.md`, because only the last two are generated. Quote only the generated
  ones, and regenerate first.
- `docs/architecture/api-spec.md` route tables are generated (`scripts/gen/api_routes.py`) and
  checked in CI. Its prose sections are hand-written and may lag the code.

Fixed on 2026-09-15: Appendix B's catalog path, control count and missing rows; Appendix C's
phantom routes; Appendix D's model path; the stale-wheel claims in `docs/architecture/high-level-design.md`; and the
migration count in `docs/architecture/low-level-design.md`.
