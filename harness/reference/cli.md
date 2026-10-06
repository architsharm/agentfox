---
title: agentfox CLI reference
layer: reference
audience: agents (and humans who want the dense version)
source_of_truth: src/agentfox/cli/ — the code wins if this file disagrees
verified_against: branch claude/cli-consolidate, 2026-10-05 (checked by harness/scripts/check_harness.py)
---

# `agentfox` CLI reference

Entry point: `agentfox = agentfox.cli.main:app` (Typer). In a source checkout without an
installed console script, use `uv run agentfox …` or `python -m agentfox.cli.main …`
(see `harness/scripts/agentfox.sh`, which picks the right one).

## Side-effect legend

| Tag | Meaning | What an agent should do |
|---|---|---|
| **R** | read-only | run freely |
| **R\*** | read-only, but creates the SQLite DB + tables if missing | run freely |
| **W** | writes to the control-plane DB | run when it follows from the user's request |
| **F** | writes files | say where the file went |
| **BLK** | changes whether production traffic is blocked or an agent is stopped | **confirm with the user first** — the harness hook enforces this |
| **FG** | long-running foreground process | run in the background / a preview server, never inline |
| **NET** | makes network calls | only with the user's consent |

`--json` exists **only** on: `agents list`, `scan`, `scan --sessions`, `doctor`,
`findings`, `permit list`, `declare list tools`, `declare list sources`,
`admin auth tokens`, `policy rules check`, `policy catalogue`, `policy compile`,
`policy proposals list`, `policy proposals show`, `policy proposals from-labels`.
Everything else prints Rich tables — parse text, or prefer the HTTP API
(`reference/http-api.md`) when you need structure.

## Shape

`agentfox --help` shows thirteen verbs in six panels. Everything else is a subcommand.

| Panel | Verbs |
|---|---|
| Start | `init`, `demo` |
| See | `scan`, `agents` |
| Watch | `serve`, `findings` |
| Contain | `permit`, `declare`, `policy` |
| Prove | `test`, `report` |
| Operate | `doctor`, `admin` |

`scan`, `serve` and `report` run a default subcommand when the next word is not one of
theirs: `scan [PATH]` is `scan repo`, `serve [--port N]` is `serve api`, bare `report`
is `report status`. The registration layer is `src/agentfox/cli/layout.py`.

Every pre-consolidation name still runs, hidden from `--help`; see **Renamed** at the
end. At a terminal an old name prints a one-line "now called" note on stderr; piped,
in CI and under the MCP server it prints nothing extra. `hooks run`, `hooks daemon` and
`mcp serve` are protocol endpoints in users' configs and never print the note.



## Start, See, Watch, Operate — top level

| Command | Effect | Exit / notes |
|---|---|---|
| `agentfox init [--path/-p .] [--env/-e development] [--demo]` | W, F | Idempotent. DB, the control catalog, and the shipped policy packs, each listed with its real mode (`tool-containment` enforces). `coding-agent` is bound only to agents named in this repo's `.claude/settings.json` hook commands, and skipped when there are none; `hooks install --write` adds its agent. Writes `agentfox.toml`, which settings read from the working directory. |
| `agentfox demo` | W, F, **BLK** | 13-step offline walkthrough. Promotes `baseline` to enforce for step 8, then restores its previous mode. Writes demo data, so use a scratch DB. |
| `agentfox scan [PATH=.] [--json] [--limit/-n 15] [--fail] [--submit/--no-submit]` | R (static AST scan, never imports target code) | Same as `scan repo`. `--fail` → exit 1 if any model call is ungoverned. Use in CI. |
| `agentfox scan --sessions [PATH=.] [--json] [--skip-sessions] [--submit/--no-submit]` | R (reads `~/.claude/projects/**/*.jsonl` unless `--skip-sessions`) | Repo scan + local AI-tool sessions + a live detector check. Always exit 0. Pass `--skip-sessions` unless the user asked for the session scan. |
| `agentfox scan mcp [SERVER] [--config PATH] [--file tools.json \| --seed-fixture] [--json]` | W | No setup: reads `.mcp.json`, `.cursor/mcp.json` or `claude_desktop_config.json` and registers every declared server. Reports where each is declared, what it can reach, config problems (unpinned, plain-http remote, no auth, literal credentials) and the lethal trifecta across one config. Never starts a server. `--file` adds the server's real `tools/list`. |
| `agentfox scan skills [PATH=.] [--persist]` | R (W with `--persist`) | `SKILL.md` files: planted instructions and declared danger. |
| `agentfox scan runtime` | W | Shadow/unowned agents, registry drift, identity posture, delegation cycles. |
| `agentfox serve [--host 127.0.0.1] [--port 8080] [--reload]` | FG | Same as `serve api`. Gateway + API (`/v1/*`, `/api/*`, `/docs`). No `--workers`. |
| `agentfox serve mcp` | FG (stdio) | MCP server over stdin/stdout for Claude Code, Cursor and other clients. 27 read-only tools; nothing that changes enforcement. |
| `agentfox findings [--severity/-s S] [--limit/-n 20] [--json]` | R\* | Newest first. |
| `agentfox doctor [--json]` | R\* | Exit 1 if any check is bad, with or without `--json`. |
| `agentfox --version` | R | Version string. `admin version` lists every component that takes part in a decision. |

`--submit` POSTs a redacted summary to `$NOMETRIA_API_URL/api/discovery/submit`. Never
pass it without the user's explicit consent — it is the only path that sends scan data
anywhere.

## `agents` — registry and kill switch (Pillar 1, PL-3)

| Command | Effect | Notes |
|---|---|---|
| `agents list [--json] [--stopped]` | R\* | Registered + shadow agents. `--stopped`: only quarantined/killed agents, with reason and actor. |
| `agents lineage SLUG [--depth 2]` | W | Blast radius: what the agent can reach. |
| `agents quarantine SLUG [--reason/-r TEXT]` | W, **BLK** | Reversible, audited. Exit 1 on unknown agent. |
| `agents kill SLUG [--reason/-r TEXT]` | W, **BLK** | Stop now. |
| `agents resume SLUG [--reason/-r TEXT]` | W, **BLK** | Back to active. |

## `permit` — what an agent, or an end user, may do (P9, P10)

| Command | Effect | Notes |
|---|---|---|
| `permit grant AGENT TOOL [--action/-a CSV] [--limit/-l path=value \| path:op=value] [--max-taint none\|user\|retrieved\|tool_result\|subagent\|memory] [--requires-approval] [--expires-in-days N] [--granted-by WHO] [--yes]` | W | Least privilege, the half of containment that decides whether an action is allowed at all. Confirms before writing and records `capability.granted` on the audit chain. A comparison the policy engine cannot evaluate is refused at grant time, so a grant never looks narrower than it is. |
| `permit list [AGENT] [--json]` | R | Grants with their limits, taint ceiling and expiry. |
| `permit revoke CAPABILITY_ID [--yes]` | W | Accepts the short id the table prints. |
| `permit user RESOURCE PRINCIPAL [--kind group\|subject] [--classes CSV] [--purposes CSV]` | W | An end user's entitlement to a resource. |

## `declare` — the facts containment reasons over (P7, P8, P9, P10, P11, P18)

| Command | Effect | Notes |
|---|---|---|
| `declare tool KEY --impact read\|write\|high_impact\|irreversible [--output-trust trusted\|untrusted] [--name] [--description] [--triggers CSV]` | W | Declare a tool and what it can do — what contains an action when a detector misses. `--output-trust trusted` means values copied from its output do not count as untrusted. Exit 2 on an invalid impact. |
| `declare triggers KEY [--triggers CSV]` | W | Declare downstream side effects for cascade analysis. |
| `declare scope TABLE --column COL [--principal-key id] [--restricted-columns CSV]` | W | Row-ownership column for data-access analysis. |
| `declare reference TABLE` | W | A table that belongs to nobody. |
| `declare boundary AGENT [--systems CSV] [--coverage-months N] [--answerable CSV] [--out-of-scope CSV] [--mode observe\|enforce]` | W (**BLK** with `--mode enforce`) | What the agent may answer from. |
| `declare source KEY [--tier/-t unverified] [--owner] [--domain] [--sla-hours N] [--updated ISO\|now] [--title]` | W | Tiers: `system_of_record`, `approved`, `unverified`, `external`. |
| `declare import-sources FILE.json` | W | Bulk `declare source`. |
| `declare escalation [--agent] [--turn-depth N] [--repeated-failure N] [--sla-minutes 60] [--owner support] [--mode observe]` | W | When a conversation must reach a human. |
| `declare principal SUBJECT [--groups/-g CSV] [--clearances CSV] [--residency] [--display]` | W | The human an agent acts for. |
| `declare list [tools\|sources] [--json]` | R\* | Declared tools (impact, triggers) and sources (tier, freshness). `--json` needs a kind. |

## `policy` — authoring, simulation, promotion (Pillars 2, 6, 12)

| Command | Effect | Notes |
|---|---|---|
| `policy list` · `policy packs` | R\* | Latest version, mode, rule count · the bundled packs. |
| `policy lint [FILE...]` | R\* | The whole bound hierarchy, or the given files. Exit 1 on critical/high findings. |
| `policy effective [--agent] [--team] [--user] [--environment ENV]` | R\* | Which rules are in force and where each came from. `--environment` defaults to `NOMETRIA_ENVIRONMENT`. |
| `policy validate FILE` | R, offline | One file: parse, full lint (unreachable rules, unknown enum values) and compile to Rego, without saving. Exit 1 if invalid or on critical/high findings. **Always run before simulate.** |
| `policy simulate --file/-f FILE [--agent] [--since-days 30] [--limit 1000]` | W (records the simulation) | Replays recorded decisions. **Exit 1 if the candidate would newly block production traffic.** |
| `policy enforce KEY` | W, **BLK** | The step that starts blocking. Audited. |
| `policy observe KEY` | W, **BLK** | Demote back to observe. |
| `policy catalogue [--json]` | R, offline | All 22 business-guardrail kinds. |
| `policy compile FILE [--json] [--apply]` | R (W with `--apply`) | Written policy → executable guardrails. `--apply` saves the threshold ladders in observe mode. |

### `policy rules` — business rules (the no-code path)

| Command | Effect | Notes |
|---|---|---|
| `policy rules suggest "INSTRUCTION"` | R, offline | Which kinds a sentence of policy probably needs. |
| `policy rules explain KIND_ID` | R, offline | Parameters + worked example. |
| `policy rules apply FILE.yaml [--agent] [--mode observe\|enforce]` | W (**BLK** with enforce) | Author or update a rule ladder. |
| `policy rules show [KEY]` · `policy rules graph` | R | Resolved bands · the decision path stage by stage. |
| `policy rules check [--json]` | R | **Exit 1 if two teams' rules conflict.** |

`policy rules catalogue`, `policy rules compile` and `policy rules test` also exist;
they are `policy catalogue`, `policy compile` and `test rule`.

### `policy proposals` — governed changes (improvement loop)

Every change the improvement loop wants to make is a proposal. A proposal moves from
proposed to proven, approved, canary, applied and verified, or ends rejected, rolled back
or superseded. A change that loosens a control is never applied automatically.

| Command | Effect | Notes |
|---|---|---|
| `policy proposals list [--status] [--kind] [--scope] [--json]` | R | Newest first; loosening changes are shown in red. |
| `policy proposals show ID [--json]` | R | Diff, evidence, proof and the decision trail. |
| `policy proposals from-traffic [--agent SLUG] [--since 7d] [--json]` | W | Learned permissions: files `tool.declare` and `capability.grant` proposals from recorded tool calls, with limits read off benign calls. Applies nothing. Also runs daily as the `grants.propose` job. |
| `policy proposals from-labels [--days 30] [--json]` | W | Turns labelled false positives into rule cut-off proposals. Files proposals only and applies nothing. Also runs daily as the `tuning.propose` job. |
| `policy proposals approve ID --actor --note` · `policy proposals reject ID --actor --note` | W | An org-level loosening needs two different approvers. |
| `policy proposals apply ID [--actor] [--automated]` | **BLK** | Changes live configuration, directly or through a canary. `--automated` runs every automation check and refuses loosening changes. |
| `policy proposals rollback ID --actor --reason` | **BLK** | Undoing a tightening loosens a control, so only a person can do it. |
| `policy proposals verify ID --actor --note [--failed]` | W (**BLK** with `--failed`) | Did the applied change do what it promised? `--failed` records the failure and rolls it back, except where that rollback would loosen a control, which stays for a person. |

## `test` — prove it before you ship 

| Command | Effect | Notes |
|---|---|---|
| `test suites` | R\* | Registered eval suites. |
| `test run SUITE [--provider echo] [--model echo-1] [--agent] [--scorers CSV]` | W | |
| `test gate SUITE [--provider echo] [--model echo-1] [--baseline RUN_ID] [--min-pass-rate F] [--junit PATH] [--sarif PATH]` | W, F | **Exit 1 on regression.** No `--agent`. |
| `test baseline RUN_ID [--label main]` | W | |
| `test online AGENT [--since-days 7] [--rate F]` | W | Scores sampled production traces. |
| `test probes` | R, offline | 22 built-in probes + wrapped runners. |
| `test redteam AGENT [--probes CSV] [--adaptive] [--budget N] [--seed N] [--no-deployment-probes]` | W | Probes the agent's real grants and policy bindings. `--adaptive` mutates a blocked probe and retries, and reports a posture delta against the last comparable campaign rather than a pass rate. Never a robustness certificate. Exit 0 always. |
| `test action STATEMENT [--kind sql\|shell\|http] [--method GET] [--dialect postgres] [--environment production]` | R, offline | Exit 1 if critical. Blast radius / reversibility of a SQL/shell/HTTP artefact. |
| `test boundary AGENT "QUESTION"` | R | Would it abstain, and what would it say? |
| `test rule KEY "V1,V2,..."` | R | Try values against a business rule. |

The default `echo` provider is offline. Real providers need `AGENTFOX_ALLOW_EGRESS=true` and a key.

## `report` — what you can show an auditor 

| Command | Effect | Notes |
|---|---|---|
| `report [--agent/-a SLUG]... [--since 7d] [--format/-f md\|html] [--out/-o PATH]` | R\*, W (control status, when absent or a day old) | One page in plain language: inventory, risky combinations, what was contained (by cause, with examples), what observe mode would have stopped, feedback counts, OWASP agentic coverage labelled DRAFT — UNVERIFIED. `--since` takes `24h`, `7d`, `2w`. Exit 2 on a bad format or period. |
| `report status [--framework KEY] [--verbose]` | R\* | Control posture. Framework keys: `eu-ai-act`, `nist-ai-rmf`, `iso-42001`, `soc2`, `owasp-llm`, `owasp-agentic`, `mitre-atlas`. `--verbose` lists only that framework's controls. |
| `report frameworks` | R\* | Coverage and review status per framework. |
| `report risk` | R\* | Agent risk register. |
| `report obligations` | R\* | Regulatory obligation calendar against the agent inventory. |
| `report board` | R\* | Executive risk view. |
| `report verify [--start N] [--end N]` | R\* | **Exit 1 if the audit chain is broken** — the output names the first bad entry. |
| `report evidence [--agent SLUG]... [--from DATE] [--to DATE] [--since-days 30] [--control KEY]... [--requested-by cli]` | W, F | Zip in `AGENTFOX_EVIDENCE_DIR` (default `var/evidence/`) that opens on `SUMMARY.md`/`SUMMARY.html` (the `agentfox report` page for the same scope), with a bundled `verify_chain.py`. `--from`/`--to` take `YYYY-MM-DD` or a full ISO-8601 timestamp; a bare end date covers that whole day, so `--to 2026-08-17` includes the 17th. Without a range, `--since-days` applies; with only one end given, `--since-days` fills the other. A backwards range or an unparseable date is refused. |
| `report review-packet --framework KEY [--out PATH]` | R\* | Everything a qualified reviewer needs to sign off one framework, as markdown. |
| `report signoff CONTROL --framework KEY --reviewer NAME [--reference REF]` | W | Records a named human's sign-off; moves mappings out of DRAFT. Exit 1 if nothing matched. |
| `report entitlement [--days 7]` | R | Over-permission: agent reach vs. callers' entitlement. |
| `report escalations [--hours 24] [--apply]` | R (W with `--apply`) | Conversations that qualified for a human and never got one. |
| `report drift AGENT [--scorer groundedness]` | R\* | Exit 0 even when drift is detected — read the output. |

All framework mappings are `review_status: draft` and ship chip-labelled
`DRAFT — UNVERIFIED / NOT LEGAL ADVICE`. Never present them as legal conclusions.

## `admin` — operating a deployment

| Command | Effect | Notes |
|---|---|---|
| `admin auth status` | R | Is the dev `X-Nometria-User` header accepted here? It must not be in production. |
| `admin auth issue EMAIL [--name/-n] [--days 365]` | W | **Shows the token once.** Never paste it into chat logs or files. |
| `admin auth tokens [--json]` · `admin auth revoke TOKEN_ID` | W (audit entry) · W | |
| `admin users create EMAIL [--role owner] [--name/-n] [--org] [--token]` · `admin users list [--json]` | W (audit entry) · R | First operator on a fresh install, no demo data. `--token` shows a token once. |
| `admin db upgrade [--revision head]` · `admin db current` · `admin db downgrade REVISION` | W · R · W (**destructive**) | Needs a source checkout (`alembic.ini`, `migrations/`). |
| `admin catalog validate` | R, offline | Catalog consistency: unique keys, known frameworks and rule kinds, obligations parse. Exit 1 on problems. |
| `admin catalog sync` | W | Load control catalog + obligations from YAML. |
| `admin catalog compute [--window-days 30]` | W | Recompute control status from telemetry. |
| `admin checkpoint` | W | Signed checkpoint over the audit chain head. |
| `admin seed [--show-keys]` | W | Demo agents, policies, controls, eval suite. Agent keys are masked unless `--show-keys`; they're only created on first seed. |
| `admin version` | R | Versions of every component that participates in a decision. |
| `admin hooks install --agent SLUG [--harness claude] [--path .] [--write]` | R (F with `--write`) | Show, or write, the hook configuration for a harness. |
| `admin hooks status` | R | Is the daemon up, and does a deny on this harness actually stop anything? |
| `admin hooks daemon [--socket PATH]` · `admin hooks run --harness H [--agent]` | FG · stdio | The warm process and the per-call hook. Installed configs call `agentfox hooks run`, which keeps working. |
| `admin mcp tools` | R | Lists the MCP server's tools with one-line descriptions. |

## Renamed

The old names still run (hidden from `--help`).

| Old | New |
|---|---|
| `check` · `quickscan` | `scan` · `scan --sessions` |
| `agents discover` · `agents controls` | `scan runtime` · `agents list --stopped` |
| `quickstart` · `version` · `seed` | `init` · `--version` / `admin version` · `admin seed` |
| `analyse-action` | `test action` |
| `eval run/gate/baseline/suites/online` · `eval drift` | `test …` · `report drift` |
| `redteam run` · `redteam probes` | `test redteam` · `test probes` |
| `audit verify` · `audit checkpoint` | `report verify` · `admin checkpoint` |
| `evidence export` | `report evidence` |
| `compliance status/risk/obligations/frameworks/board/review-packet` · `compliance review` | `report …` · `report signoff` |
| `compliance sync/compute/validate` | `admin catalog …` |
| `tools declare` · `tools set-triggers` · `tools list` | `declare tool` · `declare triggers` · `declare list tools` |
| `access declare-scope` · `access declare-reference` | `declare scope` · `declare reference` |
| `boundary set` · `boundary check` | `declare boundary` · `test boundary` |
| `sources add` · `sources import` · `sources list` | `declare source` · `declare import-sources` · `declare list sources` |
| `escalation set` · `escalation scan` | `declare escalation` · `report escalations` |
| `entitlement principal` · `entitlement grant` · `entitlement report` | `declare principal` · `permit user` · `report entitlement` |
| `capability grant/list/revoke` | `permit grant/list/revoke` |
| `guardrails …` · `guardrails test` | `policy rules …` (`catalogue`, `compile` also at `policy`) · `test rule` |
| `proposals …` | `policy proposals …` |
| `auth …` · `db …` · `hooks …` | `admin auth …` · `admin db …` · `admin hooks …` |
| `mcp serve` · `mcp tools` | `serve mcp` · `admin mcp tools` |
