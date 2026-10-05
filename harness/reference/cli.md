---
title: agentfox CLI reference
layer: reference
audience: agents (and humans who want the dense version)
source_of_truth: src/agentfox/cli/ — the code wins if this file disagrees
verified_against: branch claude/improvement-loop-phase0, 2026-09-20 (checked by harness/scripts/check_harness.py)
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

`--json` exists **only** on: `agents list`, `check`, `doctor`, `findings`, `quickscan`,
`auth tokens`, `sources list`, `guardrails check`, `guardrails catalogue`,
`guardrails compile`, `proposals list`, `proposals show`, `proposals from-labels`. Everything else prints Rich tables — parse text, or prefer the
HTTP API (`reference/http-api.md`) when you need structure.

## Onboarding and top level

| Command | Effect | Exit / notes |
|---|---|---|
| `agentfox init [--path/-p .] [--env/-e development] [--demo]` | W, F | Idempotent. DB, the control catalog, and the 4 policy packs, each listed with its real mode (`tool-containment` enforces). Writes `agentfox.toml`, which settings read from the working directory. |
| `agentfox check [PATH=.] [--json] [--limit/-n 15] [--fail] [--submit/--no-submit]` | R (static AST scan, never imports target code) | `--fail` → exit 1 if any model call is ungoverned. Use in CI. |
| `agentfox doctor [--json]` | R\* | Exit 1 if any check is bad, with or without `--json`. |
| `agentfox findings [--severity/-s S] [--limit/-n 20] [--json]` | R\* | Newest first. |
| `agentfox quickstart` | R | Prints the 5-step path. |
| `agentfox quickscan [PATH=.] [--json] [--skip-sessions] [--submit/--no-submit]` | R (reads `~/.claude/projects/**/*.jsonl` unless `--skip-sessions`) | Always exit 0. Pass `--skip-sessions` unless the user asked for the session scan. |
| `agentfox version` | R | Versions of every component that participates in a decision. |
| `agentfox seed [--show-keys]` | W | Demo agents, policies, controls, eval suite. Agent keys are masked unless `--show-keys`; they're only created on first seed. |
| `agentfox demo` | W, F, **BLK** | 13-step offline walkthrough. Promotes `baseline` to enforce for step 8, then restores its previous mode. Writes demo data, so use a scratch DB. |
| `agentfox serve [--host 127.0.0.1] [--port 8080] [--reload]` | FG | Gateway + API (`/v1/*`, `/api/*`, `/docs`). No `--workers`. |
| `agentfox analyse-action STATEMENT [--kind sql\|shell\|http] [--method GET] [--dialect postgres] [--environment production]` | R, offline | Exit 1 if critical. Blast radius / reversibility of a SQL/shell/HTTP artefact. |

`--submit` POSTs a redacted summary to `$NOMETRIA_API_URL/api/discovery/submit`. Never
pass it without the user's explicit consent — it is the only path that sends scan data
anywhere.

## `agents` — registry and kill switch (Pillar 1, PL-3)

| Command | Effect | Notes |
|---|---|---|
| `agents list [--json]` | R\* | Registered + shadow agents. |
| `agents discover` | W | Shadow/unowned agents, registry drift, identity posture, delegation cycles. |
| `agents lineage SLUG [--depth 2]` | W | Blast radius: what the agent can reach. |
| `agents controls` | R\* | Every agent not in the active state. |
| `agents quarantine SLUG [--reason/-r TEXT]` | W, **BLK** | Reversible, audited. Exit 1 on unknown agent. |
| `agents kill SLUG [--reason/-r TEXT]` | W, **BLK** | Stop now. |
| `agents resume SLUG [--reason/-r TEXT]` | W, **BLK** | Back to active. |

## `policy` — authoring, simulation, promotion (Pillars 2, 6, 12)

| Command | Effect | Notes |
|---|---|---|
| `policy list` | R\* | Latest version, mode, rule count. |
| `policy lint` | R\* | Exit 1 on critical/high findings. |
| `policy effective [--agent] [--team] [--user] [--environment ENV]` | R\* | Which rules are in force and where each came from. `--environment` defaults to `NOMETRIA_ENVIRONMENT`. |
| `policy validate FILE` | R, offline | Parse + compile to Rego without saving. Exit 1 if invalid. **Always run before simulate.** |
| `policy simulate --file/-f FILE [--agent] [--since-days 30] [--limit 1000]` | W (records the simulation) | Replays recorded decisions. **Exit 1 if the candidate would newly block production traffic.** |
| `policy enforce KEY` | W, **BLK** | The step that starts blocking. Audited. |
| `policy observe KEY` | W, **BLK** | Demote back to observe. |

## `eval` — CI gating and drift (Pillar 4)

| Command | Effect | Notes |
|---|---|---|
| `eval run SUITE [--provider echo] [--model echo-1] [--agent] [--scorers CSV]` | W | |
| `eval gate SUITE [--provider echo] [--model echo-1] [--baseline RUN_ID] [--min-pass-rate F] [--junit PATH] [--sarif PATH]` | W, F | **Exit 1 on regression.** No `--agent`. |
| `eval baseline RUN_ID [--label main]` | W | |
| `eval drift AGENT [--scorer groundedness]` | R\* | Exit 0 even when drift is detected — read the output. |
| `eval online AGENT [--since-days 7] [--rate F]` | W | Scores sampled production traces. |

The default `echo` provider is offline. Real providers need `NOMETRIA_ALLOW_EGRESS=true` and a key.

## `audit`, `evidence`, `compliance` (Pillars 5, 6)

| Command | Effect | Notes |
|---|---|---|
| `audit verify [--start N] [--end N]` | R\* | **Exit 1 if the chain is broken** — the output names the first bad entry. |
| `audit checkpoint` | W | Signed checkpoint over the chain head. |
| `evidence export [--agent SLUG]... [--from DATE] [--to DATE] [--since-days 30] [--control KEY]... [--requested-by cli]` | W, F | Zip in `NOMETRIA_EVIDENCE_DIR` (default `var/evidence/`) with a bundled `verify_chain.py`. `--from`/`--to` take `YYYY-MM-DD` or a full ISO-8601 timestamp; a bare end date covers that whole day, so `--to 2026-08-17` includes the 17th. Without a range, `--since-days` applies; with only one end given, `--since-days` fills the other. A backwards range or an unparseable date is refused. |
| `compliance review-packet --framework KEY [--out PATH]` | R\* | Everything a qualified reviewer needs to sign off one framework, as markdown. |
| `compliance review CONTROL --framework KEY --reviewer NAME [--reference REF]` | W | Records a named human's sign-off; moves mappings out of DRAFT. Exit 1 if nothing matched. |
| `compliance validate` | R, offline | Catalog consistency: unique keys, known frameworks and rule kinds, obligations parse. Exit 1 on problems. |
| `compliance sync` | W | Load control catalog + obligations from YAML. |
| `compliance compute [--window-days 30]` | W | Recompute control status from telemetry. |
| `compliance status [--framework KEY] [--verbose]` | R\* | Framework keys: `eu-ai-act`, `nist-ai-rmf`, `iso-42001`, `soc2`, `owasp-llm`, `owasp-agentic`, `mitre-atlas`. `--verbose` lists only that framework's controls. |
| `compliance frameworks` | R\* | Coverage and review status per framework. |
| `compliance risk` | R\* | Agent risk register. |
| `compliance obligations` | R\* | Regulatory obligation calendar against the agent inventory. |
| `compliance board` | R\* | Executive risk view. |

All framework mappings are `review_status: draft` and ship chip-labelled
`DRAFT — UNVERIFIED / NOT LEGAL ADVICE`. Never present them as legal conclusions.

## `redteam`, `scan`, `tools`, `access` (Pillars 1, 4, 9, 18)

| Command | Effect | Notes |
|---|---|---|
| `redteam probes` | R, offline | 22 built-in probes + wrapped runners. |
| `redteam run AGENT [--probes CSV] [--adaptive] [--budget N] [--seed N] [--no-deployment-probes]` | W | Probes the agent's real grants and policy bindings. `--adaptive` mutates a blocked probe and retries, and reports a posture delta against the last comparable campaign rather than a pass rate. Never a robustness certificate. Exit 0 always. |
| `scan mcp SERVER (--file tools.json \| --seed-fixture)` | W | Server must be registered. `--file` takes the server's real `tools/list` output; `--seed-fixture` scans the demo tool list. Neither → exit 2. |
| `tools declare KEY --impact read\|write\|high_impact\|irreversible [--name] [--description] [--triggers CSV]` | W | Declare a tool and what it can do — what contains an action when a detector misses. Exit 2 on an invalid impact. |
| `tools list [--json]` | R\* | Every declared tool, its impact tier and declared triggers. |
| `tools set-triggers KEY [--triggers CSV]` | W | Declare downstream side effects for cascade analysis. |
| `access declare-scope TABLE --column COL [--principal-key id] [--restricted-columns CSV]` | W | Row-ownership column for data-access analysis. |
| `access declare-reference TABLE` | W | A table that belongs to nobody. |
| `capability grant AGENT TOOL [--action/-a CSV] [--limit/-l path=value \| path:op=value] [--max-taint none\|user\|retrieved\|tool_result\|subagent\|memory] [--requires-approval] [--expires-in-days N] [--granted-by WHO] [--yes]` | W | Least privilege, the half of containment that decides whether an action is allowed at all. Confirms before writing and records `capability.granted` on the audit chain. A comparison the policy engine cannot evaluate is refused at grant time, so a grant never looks narrower than it is. |
| `capability list [AGENT] [--json]` | R | Grants with their limits, taint ceiling and expiry. |
| `capability revoke CAPABILITY_ID [--yes]` | W | Accepts the short id the table prints. |

## Agent controls — `boundary`, `sources`, `escalation`, `entitlement` (P7, P8, P10, P11)

| Command | Effect | Notes |
|---|---|---|
| `boundary set AGENT [--systems CSV] [--coverage-months N] [--answerable CSV] [--out-of-scope CSV] [--mode observe\|enforce]` | W (**BLK** with `--mode enforce`) | What the agent may answer from. |
| `boundary check AGENT "QUESTION"` | R | Would it abstain, and what would it say? |
| `sources add KEY [--tier/-t unverified] [--owner] [--domain] [--sla-hours N] [--updated ISO\|now] [--title]` | W | Tiers: `system_of_record`, `approved`, `unverified`, `external`. |
| `sources import FILE.json` · `sources list [--json]` | W · R | |
| `escalation set [--agent] [--turn-depth N] [--repeated-failure N] [--sla-minutes 60] [--owner support] [--mode observe]` | W | When a conversation must reach a human. |
| `escalation scan [--hours 24] [--apply]` | R (W with `--apply`) | Conversations that qualified for a human and never got one. |
| `entitlement principal SUBJECT [--groups/-g CSV] [--clearances CSV] [--residency] [--display]` | W | The human an agent acts for. |
| `entitlement grant RESOURCE PRINCIPAL [--kind group\|subject] [--classes CSV] [--purposes CSV]` | W | |
| `entitlement report [--days 7]` | R | Over-permission: agent reach vs. callers' entitlement. |

## `guardrails` — business rules (the no-code path)

| Command | Effect | Notes |
|---|---|---|
| `guardrails catalogue [--json]` | R, offline | All 22 guardrail kinds. |
| `guardrails suggest "INSTRUCTION"` | R, offline | Which kinds a sentence of policy probably needs. |
| `guardrails explain KIND_ID` | R, offline | Parameters + worked example. |
| `guardrails compile FILE [--json] [--apply]` | R (W with `--apply`) | Written policy → executable guardrails. `--apply` saves the threshold ladders in observe mode. |
| `guardrails apply FILE.yaml [--agent] [--mode observe\|enforce]` | W (**BLK** with enforce) | Author or update a rule ladder. |
| `guardrails show [KEY]` · `guardrails graph` | R | Resolved bands · the decision path stage by stage. |
| `guardrails test KEY "V1,V2,..."` | R | Try values against a rule. |
| `guardrails check [--json]` | R | **Exit 1 if two teams' rules conflict.** |

## `proposals` — governed changes (improvement loop)

Every change the improvement loop wants to make is a proposal. A proposal moves from
proposed to proven, approved, canary, applied and verified, or ends rejected, rolled back
or superseded. A change that loosens a control is never applied automatically.

| Command | Effect | Notes |
|---|---|---|
| `proposals list [--status] [--kind] [--scope] [--json]` | R | Newest first; loosening changes are shown in red. |
| `proposals show ID [--json]` | R | Diff, evidence, proof and the decision trail. |
| `proposals from-labels [--days 30] [--json]` | W | Turns labelled false positives into rule cut-off proposals. Files proposals only and applies nothing. Also runs daily as the `tuning.propose` job. |
| `proposals approve ID --actor --note` · `proposals reject ID --actor --note` | W | An org-level loosening needs two different approvers. |
| `proposals apply ID [--actor] [--automated]` | **BLK** | Changes live configuration, directly or through a canary. `--automated` runs every automation check and refuses loosening changes. |
| `proposals rollback ID --actor --reason` | **BLK** | Undoing a tightening loosens a control, so only a person can do it. |
| `proposals verify ID --actor --note [--failed]` | W (**BLK** with `--failed`) | Did the applied change do what it promised? `--failed` records the failure and rolls it back, except where that rollback would loosen a control, which stays for a person. |

## `mcp` — MCP server for agents

| Command | Effect | Notes |
|---|---|---|
| `mcp serve` | FG (stdio) | MCP server over stdin/stdout for Claude Code, Cursor and other clients. 27 read-only tools; nothing that changes enforcement. |
| `mcp tools` | R | Lists the tools with one-line descriptions. |

## `auth`, `db` — operating a deployment

| Command | Effect | Notes |
|---|---|---|
| `auth status` | R | Is the dev `X-Nometria-User` header accepted here? It must not be in production. |
| `auth issue EMAIL [--name/-n] [--days 365]` | W | **Shows the token once.** Never paste it into chat logs or files. |
| `auth tokens [--json]` · `auth revoke TOKEN_ID` | W (audit entry) · W | |
| `db upgrade [--revision head]` · `db current` · `db downgrade REVISION` | W · R · W (**destructive**) | Needs a source checkout (`alembic.ini`, `migrations/`). |
