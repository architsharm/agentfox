# Failproof AI vs AgentFox: docs structure and product gaps

Date: 2026-10-07. Source: every page of https://docs.befailproof.ai (80 guide and reference pages + 106 generated API endpoint pages, read from `llms-full.txt`), the rendered site, and the FailproofAI GitHub org. Compared against `dashboard/app/docs/**`, `dashboard/lib/docs.ts`, the live https://useagentfox.com/docs, and `src/agentfox/`.

Short version: our docs are not thin — they are long, honest, and reference pages are generated from code. They read "average" because they are organised by *surface* (guides / web app / reference) instead of by *job*, every page is a long essay, there is no search, no screenshots, and UI and CLI are documented in separate places. On product, Failproof is ahead on harness breadth, one-command setup, policy distribution, fleet rollout, and the find-failure-to-policy loop. We are ahead on what the controls actually guarantee (grants, taint, MCP integrity, tamper-evident evidence, compliance, licence).

---

## 1. How their docs are structured

### Information architecture = the product loop

Top tabs: **Start · Trace Agents · Find failures · Prevent failures · Admin · Integrations and reference**.

The tabs *are* the product thesis, stated on the home page as one line:

> Session → Audit → Finding → Issue → Policy (↘ Alert for recurrence)

Every page sits on that line. A reader always knows which stage they are in and what comes next. The home page is just five cards (set up / ask the assistant / see what the agent did / find failures / prevent recurrence) and one "do the whole loop once" card.

Sidebar groups inside tabs are verb phrases: "Understand every run", "Plug in your agent", "Evaluate agents", "Find and manage failures", "Get a policy", "Ship a policy", "Operate Failproof AI".

Ours (`dashboard/lib/docs.ts`): Start · Guides (16) · Web app (11) · Reference (6) · Operate (5). "Web app" duplicates the guides from a different angle (e.g. `guides/approvals` and `app/approvals`, `guides/tuning` and `app/policies`), so the same job is documented twice and neither page is complete.

Notably, our own quickstart already has a loop — **See → Watch → Contain → Prove** — but the IA doesn't use it.

### Page template (almost every task page)

1. H1 + one-sentence description (doubles as the `llms.txt` summary).
2. One paragraph: what it is / when to use it.
3. **`<Tabs>` Dashboard | CLI** — the same task done both ways on the same page. The dashboard tab has numbered steps + a screenshot with alt text; the CLI tab has a copy-paste block. When the CLI can't do it, the tab says so ("Dashboard CRUD is not exposed by the current Cloud CLI").
4. A "what you can do / use this when" bullet list.
5. `<Warning>` / `<Tip>` / `<Note>` callouts for the one mistake people make.
6. A `<Check>` step or "Check it arrived" section: the command that proves it worked.
7. A `<Card>` linking to the next stage of the loop.

Pages are short: median ~3 KB of source. The long ones are reference (CLI, policy authority, Jev providers).

Ours: also consistent ("When to use this → steps → Troubleshooting → Limits"), but long. The quickstart is **3,819 words over 10 steps with zero images**; theirs is ~900 words with two paths. Our guides run 259–871 lines of TSX each.

### Two-tier integration docs

Each framework gets:
- a **quickstart** (Install → Instrument → Check it arrived, under 1.5 KB), then
- a **full guide** (what gets recorded, streaming, span naming, session control, options, human-in-the-loop, *Common problems*).

Plus a single "Instrument your agent" page with a `<CodeGroup>` of `pip install` lines per framework, showing it's the same three lines everywhere.

### Onboarding: agent-first

Quickstart tab 1 is **"Use the skill"**: `npx skills add FailproofAI/skills`, then paste a prompt — "Set up Failproof AI for this project, connect this machine, install the right hooks and policies, and verify that a session arrives." The manual path is tab 2. The quickstart also opens with "Which path is yours?" (harness vs. custom agent) before any command.

### Reference section

- **CLI reference** as tables: command → what it does; flags grouped by purpose (configuration, policy, delivery); a full **environment variable** table; "pause or remove a machine safely".
- A second CLI (`fp`) for Cloud, with a syntax line, global options, and per-command flag tables.
- **HTTP API**: one hand-written page (auth, org selection, status-code meanings, `X-Request-Id`), then **one generated page per endpoint** (106) grouped by tag, plus downloadable `openapi.json`. Endpoint descriptions explain *why* ("Needs only `issues:read`, deliberately: signalling that you have picked something up must not require write").
- **Events and configuration**: event families, reserved fields, local file layout.
- **Troubleshooting**: one page, accordion per *symptom* ("No sessions appear in Cloud", "The machine does not receive policies", "A policy blocks valid work", "An error shows a ref"), each with Dashboard/CLI/Daemon tabs, ending with exactly what to send support.
- **Failure behavior**: its own page — what happens when the daemon is down (fail closed), when a pack won't load (narrow deny), and why `UserPromptSubmit` instructs instead of denying.
- **Harness capability matrix**: per harness, which events actually block vs. are observational. Honest and specific.
- **Admin**: keys + a full **permission catalog** and presets, users/orgs, usage, settings reference table with defaults.
- **Self-hosting**: prerequisites, deployment sequence, required vs optional services table, production readiness checklist, break-glass CLI.

### Concepts page

One table: Concept | What it means | **What you can achieve**. Ten rows. Then one paragraph, "The reliability loop". Ours (`/docs/concepts`) is 795 lines.

### Recipes

"Audit recipes" — accordions of ready goals (retry loops, incorrect tool use, unsafe data access, task abandonment, cost regression, missed escalation). Copy into the product and run.

### Docs-site features we lack

| Feature | Failproof | AgentFox |
| - | - | - |
| ⌘K search | yes | **none** |
| Screenshots of the UI on task pages | ~every dashboard tab | **0** on quickstart |
| Dashboard/CLI tabs on one page | yes | no — separate "Web app" group |
| "Copy page" as Markdown for LLMs | yes | per-code-block Copy only |
| "Was this page helpful?" | yes | no |
| AI chat over docs | yes | no |
| `llms.txt` / `llms-full.txt` | both | `llms.txt` only |
| Per-endpoint API pages + `openapi.json` | yes | one generated page |
| Translations | 15 languages (69 pages each) | no |
| Changelog / release notes page | via GitHub | no page |
| Troubleshooting by symptom | one page | scattered across install/self-host/policies/python/support |
| Glossary | concepts table | only in-app and `harness/reference/glossary.md` |
| Community links in header (GitHub stars, Discord, Reddit, X) | yes | no |

They use Mintlify, which gives most of this for free.

### Their docs' weaknesses (don't copy)

- The Jev/policy-authority pages are dense, conditional legal-style prose (version-specific behaviours for 1.0.7 vs 1.0.7-beta.2 vs 1.0.8-beta.0). That's a product complexity smell.
- Two CLIs (`failproofai` local, `fp` cloud) with overlapping verbs; many "this CLI can't do that yet" notes.
- Legacy naming still leaks: `AGENTEYE_ENVIRONMENT`, `X-AgentEye-Org`, `X-AgentEye-Signature`, `agenteye-orgctl`. Same disease as our `X-Nometria-*`.
- SDK path gives tracing only — "it does not enforce policies on its own."

---

## 2. How they structure the project

- **One open-source repo** (`FailproofAI/failproofai`, TypeScript + Rust daemon, ~5.2k stars, MIT + Commons Clause). Inside it: `hermes-plugin/`, `openclaw-plugin/`, `pi-extension/`, `fp-cloud-cli/`, `sdk/`, `crates/`, `skills/`, `examples/`, `integration-suite/`, plus a dot-dir per harness (`.claude .codex .cursor .devin .factory .opencode .pi`). They dogfood every harness in their own repo.
- **Policies are a separate repo per pack**: `FailproofAI/policies` (just `failproofai-pack.json`, `failproofai-pack.mjs` and `SHA256SUMS`), `FailproofAI/jev-policies`.
- **`FailproofAI/skills`**: agent skills (`failproofai`, `failproofai-sdk`, `fp-cloud-cli`, `failproofai-policy-author`, `failproofai-policy-publish`, `failproofai-eval-brainstorm`) installable with `npx skills add`.
- **`FailproofAI/hook-contracts`**: "What each agent CLI's hooks actually send today… a release means a vendor's contract moved." A public tracker of vendor hook changes. Cheap and excellent for credibility.
- **Policy hub** website listing official and community packs, auto-crawled from the GitHub topic `failproofai-policies`.
- README: logo, trendshift badges, npm/CI/supply-chain/Discord/Reddit/Docs/License badges, 14 README translations, harness logo grid, animated GIF.

---

## 3. Feature comparison

| Area | Failproof | AgentFox | Verdict |
| - | - | - | - |
| Harnesses with runtime hooks | 12 (Claude Code, Codex, Copilot CLI, Cursor, OpenCode, Pi, Factory, Devin, Antigravity, Goose, Hermes, OpenClaw) + capability matrix | **1** (`hooks/harness.py`: `claude` only); Cursor/Codex/Gemini get only `AGENTS.md` text | **Big gap** |
| Framework SDKs | Python + TS; LangChain/LangGraph, CrewAI, LlamaIndex, Pydantic AI, Vercel AI SDK; trace only | Python `auto()` patches OpenAI, Anthropic, LiteLLM, LangChain; LangGraph guard, FastAPI, MCP; CrewAI/LlamaIndex/AutoGen detect-only; **enforces** | We enforce, they trace; they cover more frameworks |
| Setup | `failproofai config`: daemon + hooks for every detected CLI + Cloud in one command; `config --status` | `init`, `demo`, `serve`, `doctor`, `admin hooks` | Gap: no single "wire everything I find" command |
| Policy authoring | JS/TS functions, `allow / instruct / deny` | YAML rules, `allow / block / escalate / redact`, hierarchy, lint, OPA, compile from prose | Ours is more auditable; **we have no "instruct" (continue + steer)** |
| Policy events | PreToolUse, PostToolUse, PermissionRequest, UserPromptSubmit, **Stop / SubagentStop gates** (`require-commit/push/pr/ci-green-before-stop`) | Six surfaces (input, output, tool_args, tool_result, memory_write, agent_message) | **No completion gates** |
| Policy distribution | Packs as GitHub releases, SHA256-pinned, `policies show` before install, `--category/--policy/--all`, `defaultEnabled`, `publish --init`, community hub | Packs bundled in the wheel (`policies_data/`) | **Gap**; we already have digest pinning (MCP) to reuse |
| Testing a policy | Backtest vs real traffic ("working calls it would have interrupted"), `fp policies test --command … --expect deny` | `policy simulate`, canary, `test rule` | Parity; tell it better |
| Rollout | Fleet of machines, per-machine deployments, numbered generations, `fleet diff/rollback`, observe→enforce per machine | Observe/enforce modes, canary, org/team/agent/user hierarchy | **No machine fleet** for coding agents on laptops |
| Fail-safety | Fail closed when daemon down; narrow deny when a pack won't load; documented | `fail_mode` in policy reference | Parity; needs its own page |
| Semantic second opinion | Jev reviews "reviewable" policies; hard vs reviewable authority | Judgment tiers (Jev, hosted LLM, self-hosted LLM, panel, router) | Comparable; **ours is undocumented publicly** |
| Find failures | Cloud audits (goal, scope, cadence, agent contracts, reference URLs), findings → issues (resolve/close/archive semantics, reopen on recurrence), alerts (threshold / SQL / eval / per-event; email, Slack, webhook) | Findings, monitoring alerts to Slack/webhook, proposals from false positives | **No issue workflow, no audit with a stated goal** |
| Finding → policy | "Generate policy" from an issue, with a candidacy check ("no policy" = needs an alert or a person) | `policy compile` from prose; learned permissions | Close; theirs is wired into triage |
| Local offline audit | Scans history of 12 CLIs, local dashboard on :8020, scheduled email report | `scan runtime` / local sessions, `scan skills` | Partial parity; under-documented |
| Observability | Sessions, live events, trace view, models/tools/hooks/errors pages, SQL queries, dashboards, sentiment | Traces, OTel/Langfuse/LangSmith/SIEM export | Deliberately not our game |
| Evals | Hosted Python evals, LLM judges, Jev classifiers, versioning, backfill, own-worker SDK | Suites, CI gate, online scoring, drift, red team, garak/PyRIT, Ragas, live probes | Different focus; ours is stronger on red team |
| NL assistant | In-app chat + `fp agent ask` | Read-only MCP server for AI clients | Gap in UX; reposition MCP server as "ask your assistant" |
| Keys / RBAC | Permission catalog, presets (`read-only`, `standard`, `admin`, `machine`), rotate/disable | Operators, API tokens | Probably a gap; at minimum a docs gap |
| Tamper-evident evidence, compliance, grants, taint, MCP rug-pull defence, RAG entitlement | **None** | Yes | **Our moat — lead with it** |
| Licence | MIT + Commons Clause | Apache-2.0 | Ours |

---

## 4. What we have wrong, ranked

### Product

1. **One harness.** Every coding-agent shop runs a mix of Claude Code, Codex, Cursor and Copilot. Ship adapters for Codex, Cursor, Copilot CLI and Gemini CLI on the same normalised event model, then publish a capability matrix like theirs (which events block, which are observational). Until then, stop implying broad coding-agent coverage.
2. **No one-command setup.** Add `agentfox setup`: detect installed agent CLIs, wire hooks, pick observe mode, optionally connect to a gateway, then run `agentfox status`. Never enable enforcing policies silently; make choosing a pack an explicit second step, as they do.
3. **No "instruct" verdict.** Blocking is not the only useful outcome. Add a verdict that lets the call through and hands the agent guidance, and document per harness where it is honoured.
4. **No completion gates.** "Don't let the agent say it's done until tests or CI pass, the work is committed, or a PR exists" is the most loved coding-agent policy class. Add Stop and SubagentStop to the Claude adapter and ship a pack.
5. **Packs aren't distributable.** Add `agentfox policy add <owner/repo>[@tag]` using the digest-pinning code we already have for MCP, plus `policy show` before install, `defaultEnabled` and categories. Our packs are **YAML data, not executable JS**, so installing a stranger's pack can't run their code. That's a real security advantage; say so.
6. **No issue workflow.** A finding needs an owner, a thread, and resolve-vs-close semantics that reopen the issue when the pattern recurs. Their resolve/close/archive table is a good spec to copy.
7. **No fleet view for coding agents.** Enterprises want to know which laptops run which policy version: enrolment, machine labels, desired vs reported state, rollback by generation.
8. **Smaller items:**
   - A permission catalog and key presets, including a narrow "machine" key.
   - `X-Request-Id` refs on every error.
   - A public hook-contracts tracker.
   - A skills repo installable with `npx skills add`.

### Docs

1. **Reorganise by job, not surface.** Proposed tabs: **Start · Discover · Contain · Watch · Prove · Reference · Operate**, matching the See/Watch/Contain/Prove loop the quickstart already teaches. Fold the "Web app" group into the task pages as a **Web app | CLI | Python** tab on each.
2. **Split long pages.** Quickstart: under 1,000 words, two paths ("Ask your coding agent" using the harness plugin, and "Manual"), plus a "Which path is yours?" opener. Move the rest into guides.
3. **Two-tier integration pages**: a quickstart (install → one line → check it arrived) plus a full guide for each of Python `auto()`, LangGraph, MCP, the gateway and Claude Code.
4. **Add search (⌘K)** and **screenshots** to every web-app step. These two are the biggest reasons the docs feel average.
5. **New pages:**
   - Troubleshooting by symptom.
   - Failure behavior (fail_mode, detector unavailable, gateway down).
   - Judgment tiers and egress (public version of `docs/architecture/judgment-tiers.md`).
   - Glossary or a concepts table.
   - Changelog page.
   - Migration from `nometria`.
   - Recipes (policy and red-team starters).
6. **Per-endpoint API pages** grouped by tag, plus a published `openapi.json`. Add a hand-written API intro covering auth, status-code meanings and request IDs.
7. **Every page ends with "check it worked"** (the exact command) and a card to the next stage.
8. **Site features:** "Copy page as Markdown", "Was this helpful?", `llms-full.txt`, GitHub link in the header.
9. **What was wrong** (all fixed on 2026-10-07 unless marked open):
   - The MCP guide said `register_tools(tools, accept_changes=True)` accepts a change; the code now needs an `actor`, and the change applies only after a second approver. Fixed.
   - `mcp_tool_added_under_wildcard` was missing from `reference/detectors` and `CHANGELOG.md`. Fixed.
   - `harness/README.md`, `harness/STRUCTURE.md` and the support page said "17 CLI groups"; there are 13. Fixed.
   - `harness/` told people to type `agentfox mcp serve`; they now see `agentfox serve mcp`. The old spelling stays in `.mcp.json` and the coding-agent hook configs (`hooks run`), because those are deliberate hidden aliases that installed configs call.
   - `harness/reference/http-api.md` named `NOMETRIA_WEBHOOK_URL`; it now names `AGENTFOX_WEBHOOK_URL`. Fixed.
   - Open: the harness plugin is at 0.1.0 while the package is 0.3.1.
   - Open: `X-Nometria-*` headers (~68 mentions in the gateway guide) and `NOMETRIA_*` env vars in `render.yaml`, `alembic.ini` and `pyproject.toml`. This waits on the restructure, but it is user-visible.

### Positioning

They sell **reliability** ("find failures, prevent repeats"); we sell **control and proof**. Don't converge. Do borrow their loop framing for ours: *discover → grant → contain → prove*, with one sentence on the docs home page the way they do. Our clearest advantages over them are things their docs explicitly can't claim: enforcement in the SDK path, argument provenance, MCP rug-pull defence, a verifiable ledger, compliance computed from runtime decisions, and Apache-2.0.

---

## 5. Suggested order of work

1. Docs quick wins (≤1 week): fix the stale MCP and harness pages, add search, troubleshooting, failure-behavior and changelog pages, and split the quickstart.
2. IA restructure: job-based tabs with Web app | CLI | Python tabs, and screenshots.
3. Product: `agentfox setup` + `status`; Codex and Cursor adapters + capability matrix; Stop gates + "instruct".
4. Product: remote policy packs (digest-pinned, YAML), then the issue workflow, then the fleet view.
