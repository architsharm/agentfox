# F3.8 — composed privilege escalation: built

**Status, changed from the original investigation below**: F3.8 was genuinely absent (*"needs data-flow tracking at the orchestration layer, not per-tool argument or per-statement checks"* — `docs/design/failure-modes.md`). It's now built: `src/agentfox/guardrails/composition.py` (P9-11), wired into `enforcement.py::evaluate()` on the live `guard_tool_call` path, tested end-to-end in `tests/test_composition.py`. The investigation that follows is kept as-is because it's *why* the fix looked the way it did — reusing infrastructure that already existed for a different purpose, rather than building a new tracking mechanism.

## What F3.8 actually names

From `docs/design/failure-modes.md`: *"a read tool's output chained into a write/authorization boundary neither tool alone permits — e.g. a read tool surfaces an internal ID that a second, differently-scoped tool then accepts as if it were user-supplied and authorized."* Two **legitimately-called** tools, each individually within its own permission scope, whose composition crosses a boundary neither one enforces alone.

## Why InjecAgent, the dataset originally sourced for this, doesn't test it

Fetched and inspected `data/test_cases_dh_base.json` (510 rows) directly. Every case: a benign tool call's *output* (e.g. an Amazon product review) contains **injected natural-language instructions** trying to manipulate the agent into calling a completely different, attacker-controlled tool it was never asked to use. That's indirect prompt injection driving unauthorized tool *selection* — already substantially covered by this project's `benchmarks/agent_security/` suite — not the "two legitimately-called tools whose combined effect exceeds either one's scope" shape F3.8 names. No public dataset was found that tests this specific composition; the check below was built and tested directly instead, the same way `benchmarks/entitlement/`'s scenario benchmark was.

## What was built

`check_composed_escalation()` in `guardrails/composition.py` compares the *producing* tool's registered `Tool.impact` (read/write/irreversible) against the *consuming* tool's, using the taint tracker's own `TaintMark.propagated_from` — provenance the tracker was already recording (P3-4, for a different purpose: flagging untrusted content in arguments) but that nothing had compared against tool scope before. When a value inferred from a lower-impact tool's result flows into a higher-impact tool's argument, it's blocked — the same "fact about this call, not a policy opinion" treatment `enforcement.py` already gives a critical action risk or a capability denial.

Two taint-mark path conventions carry tool identity today: MCP governance's `mcp.<server>.<tool>` (existing) and a new `tool:<tool_key>#<index>` convention added to the SDK's `tool_result(text, tool=...)` so non-MCP integrations (`agentfox.auto()`, LangGraph, direct SDK use) can opt in too — omit `tool=` and the value is still tainted as before, it just isn't checked against this specific failure mode, since nothing then names which tool produced it.

## Verification

`tests/test_composition.py` — 11 tests: pure-function coverage of the tool-key-recovery parsing (including the MCP taint-path-vs-registered-key format mismatch this surfaced and fixed during development) and the escalation-detection logic itself (flags read→write, doesn't flag same-tool pagination, doesn't flag read→read, skips unregistered origins rather than guessing), plus two end-to-end tests through a real `McpGovernor`: a read tool's internal ID reused by a write tool is blocked with `rule_id: composition.escalation`; the same write tool called with an independently-supplied argument is *not* blocked — the negative control proving the check is about provenance, not about the tool being write-scoped.

Full suite: 1,174 tests passing (1,163 before this change + 11 new).

## What's still open

- **Precision/recall against real-world traffic** — this is a mechanically-verified, correctly-implemented check (proven via unit + integration tests), not something scored against a labeled dataset the way `benchmarks/pii/` or `benchmarks/action_safety/` are, because no such dataset was found to exist for this failure mode (see above). A future pass could hand-author a broader adversarial scenario set (varied tool-name phrasings, near-miss values that shouldn't match, multi-hop compositions across three or more tools) the way `benchmarks/entitlement/`'s PrivacyLens-derived scenarios were built, to get a real recall/precision number rather than a binary "does it work."
- **Multi-hop chains** (tool A → tool B → tool C, where B's output — itself derived from A — feeds C) aren't specifically tested; `infer_source()`'s substring matching should propagate transitively since B's result text would still contain A's original value, but this hasn't been exercised directly.
- **Compliance mapping** — this reuses the existing `NOM-RTG-09` control (P9, action-risk analysis) rather than minting a new, separately-mapped control ID across the 7 compliance frameworks in [`docs/design/control-catalog.md`](../../docs/design/control-catalog.md). That mapping work is real and out of scope for this pass — flagged, not done.
