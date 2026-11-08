# AgentFox product TODO

A running list as we go. Newest priorities first. `[ ]` open · `[~]` started · `[x]` done.

---

## 1. Onboarding: detect agents correctly and set the first guardrails

- [~] **Agent detection that holds up on real repos.** init maps through discovery's scanner (`discovery/repo.scan` + `discovery/agents.py`), the same one `agentfox scan` and connected repos use. What is left:
  - [ ] Helper agents used as guardrails (CX's "Relevance Guardrail", "Jailbreak Guardrail") show up as ordinary agents; mark them as guard agents.
  - [ ] Same "recognised / may have missed" summary the CLI prints, in the setup card.
  - [ ] Add a missed agent or tool by hand in the dashboard (today: only grant a tool AgentFox already knows; "Register agent" doesn't place it in a project).
  - [ ] Test on a 4th real repo: LangGraph or CrewAI.
- [ ] **Map: where the done-check belongs.** The backend's `completion` surface means "the agent says it's done", not an LLM call. The LLM line shows "To the LLM" / "From the LLM" and the done-check isn't drawn. Decide where it goes on the map.
- [x] **The OpenAI Responses API (`client.responses.create`) isn't patched by autoguard**, so those LLM calls aren't checked. This is also why `agentfox.auto()` alone does nothing for an OpenAI Agents SDK app: the SDK calls the model through the Responses API, so those apps need `govern()` today. Done (2026-11-08, verified on openai 3.46 / openai-agents 0.24 with the customer_service example); Agents SDK handoffs (`transfer_to_*`) are recorded as hand-offs (subagent span, delegates_to edge), not tool decisions. Plan as written (read against openai 3.41 and openai-agents 0.22.3):
  - Patch `openai.resources.responses.Responses.create` and `AsyncResponses.create`. `responses.stream()`, `with_streaming_response.create` (the Agents SDK's streaming path) and the SDK's non-streaming `responses.create` all call `create`. `responses.parse()` posts directly, so patch it separately.
  - Read the request's `input` (a string or a list of items: messages, `function_call`, `function_call_output`) and `instructions` as the message list; a `function_call_output` is a tool result and counts as `tool_result` taint.
  - Read the output text (`output_text` / `message` items), the tool calls (`function_call` items: `name`, JSON `arguments`, `call_id`) and the usage (`input_tokens` / `output_tokens`). For a stream, read `response.output_text.delta` and `response.function_call_arguments.*` events, or the final `response.completed` event.
  - Write a redaction back into the `message` item's `output_text` part.
  - `previous_response_id` / `conversation` keep history on OpenAI's servers, so the request does not carry the whole conversation. Provenance for earlier turns has to come from the session, or be marked as unknown.
  - Hosted tools (web search, file search, code interpreter) run at OpenAI. Record them from the output items; they can't be stopped before they run.
- [ ] Workspace packs apply on top of a project's own guardrails: `tool-containment` enforces (destructive SQL/shell) and baseline watches. Decide whether a brand-new workspace should start everything in watch mode.
- [ ] **Attack test** (`capabilities/onboarding/runner.py`, `attacks.py`; the map's panel):
  - [ ] An "after" test of a project whose agents are still drafts is dominated by `capability.denied` (nothing granted until the agents are added; "Add all" grants the tools their code hands them). Every tool call is stopped and ordinary requests show as over-blocked. Say so on the panel, or test after the agents are added.
  - [ ] A re-run hides the previous "with basic guardrails" numbers until it finishes; keep the last finished one visible.
  - [ ] More library sets that need a judge to grade (harmful content, system prompt extraction, off-topic use). Grading is mechanical today.
  - [ ] Decide whether the old "Protect" wizard page (`/app/projects/<slug>/protect`) should go; its button is gone from the header.
- [~] **Runtime enforcement for hosted agent platforms** (`routes/platform_hooks.py`, `deploy/aws-agentcore-interceptor/`): Vapi tool calls, Retell custom functions, Copilot Studio threat detection, AgentCore Gateway interceptor.
  - [ ] Dashboard: create and list connections from the agent's page (API only today: `POST/GET/DELETE /api/agents/{slug}/platform-connections`). UI change: owner decides.
  - [ ] Spoken numbers ("four one one one…") in Vapi/Retell call reports are not masked: the PII detectors read digits. Needs the spoken-number normaliser from the voice plan.
  - [ ] ElevenLabs server tools and MCP approval gate; Telnyx, Agora and Smallest AI through the custom-LLM proxy (streaming defaults to `buffered`, which is too slow for voice: default voice agents to `windowed`).
  - [ ] Copilot Studio is preview and fail-open by default on Microsoft's side; tell admins to set "Block the query" on error. Verify the Entra audience on a real tenant (the docs name no claims; the check accepts the endpoint's base URL or a configured app id).
  - [ ] AgentCore: verify the 403 JSON-RPC refusal shape on a real gateway (AWS documents only community examples); optionally scan tool results in the RESPONSE interceptor.
- [ ] **Platforms whose agents live only in the vendor's console**: Sierra, Kore.ai, Webex AI Agent, Five9, NICE CXone, Talkdesk, Parloa, PolyAI. A repository has nothing to read for them (`discovery/platforms.py` covers exported files only). Cover them the way Cekura does: the customer gives an API key (or OAuth for Webex) and we import the agent's prompt, tools and calls from the platform's API. Same for Vapi/Retell/ElevenLabs agents configured only in the dashboard.
- [ ] `agentfox disconnect` on the command line, so the repo side (stopping the runner) is one step with `DELETE /api/projects/{project}`.

## 2. Map: cohesive, readable, easy to click

- [ ] A visible keyboard focus style on the line itself, and arrow keys between lines.
- [ ] With many agents the full view is small; consider a compact "overview" mode (agents only) with click-to-expand.
- [ ] Per-agent LLM chain settings: order, confidence band, thresholds. Needs backend; today these are hard-coded and workspace-wide.

## 3. From the map to setting guardrails (today too much lives in Policies)

- [ ] Everything needed to set up a line's guardrails should be doable from the line's panel without opening Policies:
  - [ ] Turn a check on and choose what happens (block / ask / watch) in one place; today the check (detector) and the action (policy rule) are separate lists.
  - [ ] Show and edit the threshold ("block if prompt injection ≥ 0.7") on the panel. The map payload has `minScore` per rule; today only the rule page (`RuleTuner.tsx`) edits it.
  - [ ] Add a rule here ("never let `start_return` run over $100") without leaving the map.
  - [ ] Install a classifier model from the panel (today: "Install" links to the Checks tab).
- [ ] Decide what Policies is for after this: the workspace-wide library, versions, packs.

## 4. Observability

- [ ] **Is it working?** A health view per project: is the agent sending events, when last, error rate, latency, cost; alert when it goes quiet.
- [ ] **How do we identify an issue?** Define what becomes an Issue automatically: blocked attacks, repeated holds on one tool, error spikes, a tool called that the code never declared, data leaving in replies. Link each to the events/session that caused it.

## 5. Agent audit

- [ ] **Audit an agent's last N days.** Pick an agent and a window; read its sessions and events and report bad patterns:
  - tools called far more than usual, or in risky orders (read customer data → send email),
  - prompts that keep hitting guardrails, near-misses that only watched,
  - personal data seen in replies, cost/latency outliers, loops.
- [ ] Output: a short report with findings, each linked to sessions, and "add a guardrail here" suggestions that open the map.
- [ ] Could run on a schedule and post a summary.

## Backend gaps found along the way

- [ ] **An ordinary request with an email address reads as a prompt attack.** "Email the invoice to finance@acme.example" typed by the user fires `INJECTION.EXFILTRATION` (0.75, the send/email ... to <address> pattern in `detectors/injection.py`), so `injection.direct` would block it once enforcing (found 2026-11-08 in the first-run re-audit; observe mode only flags it). The pattern is a strong signal in documents and tool results (instructions planted there), a weak one in what the user typed. Proposal: on the input surface, exfiltration alone should not make an injection verdict; keep it on tool results and documents. This moves published detector numbers: re-run the held-out, NotInject and head-to-head benchmarks and `claims.py --check` with the change, measured on sets the change was not derived from.
- [ ] **Decision needed.** Libraries are applied as per-agent copies (`agent.<slug>.<policy>`) instead of the existing mechanism, one policy with `scope.agents` (the coding pack, `platform/policy/coding.py`). Copies buy per-agent watch/block and per-agent simulation, but need the "outdated" machinery to stay in sync, and they multiply policies. Middle option: one copy per (library, project), scoped to the project's agents, with one mode per project. Not changed: it is shipped.
- [ ] Red-team runs aren't tied to an agent, so "last test run" on the map is the workspace's last run.
- [ ] **Render blueprint**: `deploy/render.yaml` sets the dashboard's `AGENTFOX_API_URL` from `property: hostport` (no scheme, and `lib/env.ts:apiBase()` adds none), and the gateway block has no `AGENTFOX_TOKEN_ENCRYPTION_KEY`, so connecting GitHub returns 503.
- [ ] **Blocked calls get different status codes**: `/v1/guard/tool_call` returns 200 with a block verdict, `/v1/mcp/call` returns 403. Make them match, or say so in the gateway guide.
- [ ] **Injection classifier reported as timed out while under budget** (253 ms of a 300 ms budget shows `injection.classifier: timeout`). Check the classifier deadline against the request budget in `runtime/enforcement`.
- [ ] **Held calls notify nobody**: approvals have no notification channel (Slack covers only issues), so a held call expires to deny unseen.
- [ ] **Shadow agent raised twice**: `/api/attention` (`routes/onboarding.py`) adds "running and was never registered" on top of the open `shadow_agent` finding.
- [ ] **Agent environment defaults to "production"** (`core/models/registry.py`), so a dev gateway's agents and runs are labelled production.
- [ ] **Limit blocks don't say which value broke the limit**: `capability.constraint_violated` run detail should say e.g. "amount 40 > 25".
- [ ] **The first attack test runs before the agent is added**: `runner_connect` (`routes/onboarding_flow.py`) starts the "before" run while the agent is still proposed. Decide whether to wait for "Add to AgentFox".
- [ ] **A failed "after" run throws away its partial results**: `AttackTests.tsx` shows only a `done` run.
- [ ] **Try it sends `""` for numeric arguments**: `GET /api/agents/{slug}/tools` returns a blank-string skeleton that `TryIt.tsx:argsFor` pre-fills.
- [ ] **`agents list --stopped` lists resumed agents** (`apps/cli/commands/agents.py` prints every `all_controls()` row; resuming keeps the row as "active").
- [ ] **`admin auth` commands print "tenancy: cross-tenant scope entered"**: `apps/cli/auth_cli.py` calls `system_scope(...)` without `routine=True`.
- [ ] **Website docs drift**: the install page shows 43 controls and 3 packs (`init` now prints 44 and 4) and its troubleshooting table still lists the removed `init --path` `FileNotFoundError`; the Access page says grants are always recorded as a group, but an email is recorded as a subject (`entitlement.ts:grantPrincipalKind`).
- [ ] **Load errors read as empty**: `TokenManager.tsx` `load()` ignores `r.ok` (a 401/500 shows "no tokens"); same pattern in `SetupBanner.tsx` and `ConditionFields.tsx`.
- [ ] **Three dead proxy routes** with no client caller: `app/api/agents/[slug]/map`, `app/api/projects/route.ts` (GET), `app/api/traces/[id]`.
- [ ] **Next.js 16.4.0 was flagged as vulnerable**; `dashboard/package-lock.json` still pins it. Re-check the advisory and bump.

## 6. UI changes, deferred (review of PR #122)

**Rule:** nothing here gets built unless the owner picks it. Keep the product lean, and restore only what is genuinely useful. Fixes that are functionality with little or no UI may go ahead; everything else waits here.

### Declined for now: PR #128 (closed unmerged, branch `claude/feature-disconnects`)
Each line is one commit-sized change on that branch, if any comes back.
- [ ] Policies hidden tabs: All rules, Performance, Suggested changes, Checks and Code are reachable only by link (`HIDDEN` in `app/(product)/app/policies/page.tsx`). Judges and the judgment posture moved to Settings → Detection. `links.test.ts` was widened in #122 to accept hidden tabs, so tests can't flag them.
- [ ] Map: mark a rail whose rules only watch ("watching", amber; enforcing/watching counts in its label; a legend entry). A watching rail looks the same as one that blocks. *Recommendation: worth it. It's the honesty problem, and the cost is one small tag.*
- [ ] Severity: high and held orange (`--af-held` #a04407 / #ffa06b) apart from medium amber. Today `k-pill-held` and `--viz-held` use `--af-warn`, so high and medium look identical. *Recommendation: worth it, CSS only.*

### Restore what the redesign dropped from main
- [ ] Home (`/app`): the "does anything need me" page (week stats, approvals). Today it redirects to `/app/map`, and the old page sits unused as `LegacyHome`.
- [ ] Agent page summary: Requests / Blocked / Held / Errors linked to runs, the top 3 open issues, the rules that fired most, and owner (with Assign), environment, framework and last active.
- [ ] Lineage and blast radius on the agent page (`AgentMap.tsx`, `/api/agents/{slug}/lineage`; the component exists but nothing renders it). Main had restored this on purpose (e4bf126d).
- [ ] Sub-agents and parents on the map, across projects and repositories too. The backend sends each agent's `depth`/`relation`/`parent`/`repo`, `handoffs[].relation`, and `roots` when a repository name opened more than one system. PR #112's `relationLabel`, `parentLabel` and `drawnSubagents` in `guardrailMap.ts` are unused.
- [ ] Rules that apply at every step (`map.everywhere`) and "Done check" (completion) rules: shown nowhere on the map today.
- [ ] Per-line traffic stats ("Last N days: X checked · blocked · held") and the inline Block / Ask / Watch / Off control on each rule row.
- [ ] Map panel with nothing selected: the tools summary (allowed / ask / not allowed, "Browse and change access").
- [ ] Severity colours that `af-theme.css` neutralised:
  - eval drift vs healthy (`evals/page.tsx`)
  - risky vs safe policy simulation (`PolicyEditor.tsx`)
  - the missed-escalation panel
  - `.card.bad/.warn/.ok`
- [ ] Setup banner: fold main's banner (`SetupBanner.tsx`, `/api/onboarding` checklist) into the setup card, so there's one setup guide, not two.

### Fix
- [ ] Redirect loop: `/app/map` goes to `/app/onboarding` when a project's map fails or has no agents, and `/app/onboarding` goes straight back to `/app/map`.
- [ ] Attack test panel (`AttackTests.tsx`):
  - It polls `/tests` every 1.5s forever on a project that can't run.
  - A failed run, or one with errors, shows a green 0/N. Show errored and not-run attacks separately, and never green when anything errored.
  - It shows raw provider errors.
  - The same error handling applies to the RetestStep headline and the −X%.
- [ ] Shield mark: show it only when a rule acts on the line. Checks alone only record, and the panel already says so (`guarded()` in `GuardrailMap.tsx` counts detectors).
- [ ] Naming:
  - One name for Output / "Agent reply" / `agent_reply`.
  - The tool panel's empty state says "No policies on this line yet"; change it to "No rules for this tool".
  - The static "live" dot in the sidebar footer (`app/(product)/app/layout.tsx`).
  - Raw rule IDs in Events.
  - "Activity" vs "Overview".
  - "Jev" shown to users (`GuardrailMap.tsx`, `policies/advanced.tsx`).
- [ ] Events shows only the run's first surface. Sessions and Events filter the latest 100–200 traces on the client. Tools and Models use workspace-wide breakdowns, so they mix in other projects' traffic. Scope all of them on the server by the project's agents, and add a range picker.
- [ ] `af-theme.css` `:root` overrides main's tokens site-wide (`/docs`, `/login`, playground). Scope it to `.shell` or adopt it deliberately everywhere, and align the logo between marketing and the app.
- [ ] `NOMETRIA_DEV_SESSION_TOKEN` / `NOMETRIA_DEV_FRESH_TOKEN` in `dashboard/middleware.ts` → `AGENTFOX_*` (the rename is otherwise complete). Make dev auto-login on every cookieless GET opt-in.
- [ ] Revert the machine-generated `next-env.d.ts` change (it imports `./.next-onb/dev/types/...`).
- [ ] `/api/projects` is fetched more than once per page (twice in `app/(product)/app/layout.tsx` alone), and `SideNav` calls `router.refresh()` on agent pages.
- [ ] Duplicated check-name maps (`GuardrailMap.tsx` `MODULE_NAME`/`KIND` vs `lib/product/checks.ts`).
- [ ] New-user gate (`NewProjectGate.tsx`) hides Policies / Approvals / Issues / Testing / Evals before the first connect, so a new user can't browse policy packs.
- [ ] Dead code: `LegacyHome`, `setupBanner.ts`, `useProjectScope.ts`, `AppChrome`'s `banner` prop, 5 unused shadcn components (avatar, badge, select, separator, tooltip), and the `agentfox_project` cookie if nothing reads it.
- [ ] The orphaned 6-step wizard (`/app/onboarding/[step]`, ~2,600 lines): move its risk-label copy (RISK_HELP / RISK_WHY) into the setup card, then delete it along with its wizard-only endpoints.

### Needs the backend first (the backend is done)
- [~] Projects are PR #112 systems (root agent plus everything it hands work to). The switcher and map are keyed by `project` (= root slug). Still to do:
  - [ ] Switcher: label with `name` (the root's) and show `repos` / member count.
  - [ ] Onboarding panel calls (`/api/onboarding/projects/{p}/tests`, `/tests/sets`, `/basic-guardrails`) are keyed by the repository init connected: pass `repos[0]` from the project, not the root slug (or add a resolver on those routes).
  - [ ] Handle 404 from `/api/projects/{p}/map` (unknown or disconnected project) instead of an empty map; drop a stale `agentfox_project` cookie.
  - [ ] Disconnect dialog: say which agents go (`removed`) and that hand-offs to other projects stay. It says "bring it back as new" today. After reconnecting, offer "Restore guardrails" for agents with `restorable: true` via `POST /api/agents/{slug}/restore-guardrails` (404 nothing to restore, 409 still disconnected).
  - [ ] Projects page (`/app/projects`): rejected agents are still listed as live (`status !== "draft"`): filter `rejected` too.
  - [ ] Setup card / init map: tools carry `why`, `impact` and `capabilities` (trifecta flags); agents carry `kind`, `root`, `handoffs[].relation`, `confidence`, `evidence`; frameworks are discovery's names ("OpenAI Agents SDK", "LangGraph"). Show the relation on hand-off lines.
- [ ] Attack results: the backend sends, per run and per `byType` row, `stopped`, `resisted`, `errored`, `notRun`, `controls`, `overBlocked`, plus run-level `falsePositiveRate`, `clean`, `skipped` (`[{type, agent, reason}]`) and `wouldStop`, and `stoppedBy.waitingFor` ("grant" / "blocking") per result. The panel ignores them. Show "stopped by AgentFox" separately from "resisted" (the before→after drop is drawn from `gotThrough` only), show errored and not run, and never show a run as clean unless `clean` is true.
- [ ] Each result has `outcome` (got_through / stopped / resisted / errored / not_run; for a control allowed / over_blocked / errored), `agent`, `stoppedBy` (`{surface, rule, verdict, mode, reason, tool, watching}`), `control` and `reason`. "See all with full traces": add filters for stopped / errored / not run, show the rule that stopped each one, and say "would stop once it blocks" when `stoppedBy.watching`.
- [ ] Multi-agent projects: results carry `agent`; group the panel and the trace list by agent.
- [ ] Library entries have `notRunReason` (e.g. a read-only agent can't be tested for unsafe tool use): show it instead of "0 attacks".
- [ ] The default suite is 84 attacks per agent (plus 8 controls), not 140. The sample walkthrough (`lib/product/onboarding/fixtures.ts`) still says 140; copy should read `total`.
- [ ] The wizard's Protect / Retest steps (`ProtectStep.tsx`, `RetestStep.tsx`) still `GET/POST /api/onboarding/guardrails`; those toggles no longer change what the "after" test measures (it checks real policies). Replace Protect with the project's "Add basic guardrails" call, or delete the wizard (see "Fix").
- [ ] An "after" run handed to an old `agentfox init` fails with "too old to test with your guardrails": surface that error with the upgrade line.
- [ ] Rule "Checked by" and the rule page: use the backend's surface-aware `checks` / `checksOff` (on every map rule, and `GET /api/policies/{key}/rules/{rule_id}/checks?agent=`) instead of `checksFor()` in `lib/product/checks.ts`.
- [ ] Map "To / From the LLM" lines are a view: read `lineStats` for their numbers, and don't count `sharedWith` rules / `detectorsSharedWith` checks again.

## 7. Post-merge audit (2026-10-27): features missed or weakened by recent merges

Main before #122 (`3da75bf6`) compared with main after #129, #130 and #131. Nothing was deleted; the damage is weakened guarantees in the new write paths, plus duplicate "doors" that drift apart.

**Rule:** UI items here are records only. Backend items are fixes the owner can pick.

### Backend: weakened or broken (ranked)
- [ ] **Authorization gap (broken).** `DELETE /api/projects/{p}` needs only `registry`, which developers have, yet it publishes empty agent layers and sets enforcing copies to observe. The direct mode change needs `policy_production`.
  - Verified: a developer got 403 on the mode change, then 200 on DELETE.
  - Fix: require `policy_production`, or refuse when any agent layer enforces and `may_enforce` is false.
- [ ] **Disconnecting removes default-deny.**
  - `revoke_capability` deletes the grant rows, so `holds_any_grant()` turns false and `auto()` exempts capability refusals.
  - The agent's keys and identity stay active, and nothing refuses traffic from `removed` agents.
  - Fix: suspend the identity or revoke the keys on disconnect, and refuse `removed` agents at runtime.
- [ ] **Library and basic-guardrail writes are not audited.** `apply_library`, `update_outdated`, `remove_starter` and `basic_guardrails`, including its `set_mode(enforce)`, write no audit chain entry and are not in `operator_log.PRIVILEGED`.
- [ ] **No simulation gate on new versions of enforcing copies.** `publish_in_current_mode` records a simulation but never gates on it. Callers like `update_outdated`, basic guardrails on an enforcing layer and restore let a `policy`-role user push blocking rules live. Fix: gate on `may_enforce`, or publish in observe and promote.
- [ ] **`judgment_fail_closed` default flipped True → False with no data migration.**
  - The old `posture.save()` wrote True into every posture row, so tenants differ by history.
  - A posture PUT that omits `fail_closed` now turns it off.
  - Production pins `AGENTFOX_JUDGMENT_FAIL_CLOSED=true`. The judge deadline is now a setting (`judgment_llm_timeout_s`, 4 s).
  - Fix: decide what existing rows should be; watch the `pipeline.judge_outage` rate.
- [ ] **The setup key is not bound to the run's project.** Within a tenant, any key can post results into another project's running test (`runner_guard`/`runner_results` in `routes/onboarding_flow.py` check only the user for project runs).
- [ ] **Postgres risk in migration `b9e4c2a7d153` `_move_runs`.** The id is truncated only on insert, and `project`/`phase`/`status` are not truncated at all. Unverified on Postgres; the exposure is legacy branch data only.
- [ ] **Discovery confidence.** Medium- and low-confidence agents reach `propose_from_scan` without their confidence. Carrying it needs a `SubmittedAgent` field, and the payload tests pin the fields that cross the wire.

### Backend: duplicates that replaced instead of extending (owner decisions)
- [ ] **Two registration paths.**
  - `check --submit` → `propose_from_scan`, and `init --key` → `register_structure`.
  - They differ in slugs, ScanRun, trifecta risk tier, edge pruning and scan-proposed policies.
  - Fix: make `register_structure` a mode of `propose_from_scan`.
  - `agentfox up` is no longer a third path: it registers its agent under the scan's name for the same code (`<repo>/<agent>`) and `init`'s `project`, so `propose_from_scan` adopts it (`adopt_proposal`, `fold_duplicate_drafts`) and `register_structure` updates it. Still apart: `register_structure` names drafts `<agent>`, the scan `<repo>/<agent>`, so an `init --key` draft and a scan draft of the same code can still both exist.
- [ ] **Each recorded scan proposes another policy per framework** (`scan-<run>-<framework>`, keyed by run id), so re-recording a changed scan piles up identical proposed policies.
- [ ] **A local SQLite gateway drops some attack-test checks.** On the LangGraph swarm after-test, 4 of 49 checks failed with "database is locked" in `runner_guard` → `dry_run_check` → `ensure_identity` (a write) while results were being saved; `_SQLITE_DRY_RUN` serialises dry runs, not the other writers.
- [ ] **The attack test reads its own copy of the map.** The map lives as JSON in `OnboardingSession`/`OnboardingProject`, and `PUT /api/onboarding/structure` edits only that JSON, so the tested map and the registry drift.
- [ ] **Four delegation-graph walks.** They disagree about removed agents (`scope.delegates` doesn't filter them), so "apply to sub-agents" can write layers to removed agents. Fix: one graph helper.
- [ ] **Basic guardrails duplicate the `baseline` pack.** They are a hard-coded Python pack with different rule ids and thresholds, and two apply routes behave differently. Fix: make it a pack file and keep one route.
- [ ] **The attack test has its own corpus and storage** (`OnboardingRun`) instead of `RedTeamCampaign`/`Finding`, so it produces no findings, control evidence or posture history.
- [ ] **Wizard-only state.** `GET/POST /api/onboarding/guardrails` are display-only toggles, `/api/onboarding/state` duplicates the checklist, and `OnboardingSession.runs` is unused. Remove them with the wizard.

### Tests and docs
- [ ] `test_attack_frameworks.py` always skips in CI: it needs the langchain and agents SDK extras. Fix: a CI or nightly job with those extras.
- [ ] **Stale docs.**
  - No CHANGELOG for #131 (4 s judge deadline, `MALFORMED`, classifier windows, `total_ms`, non-blocking probe).
  - The TypeScript SDK types lack `total_ms`/`would_be_content`.
  - `plugins/shared/reference/cli.md` lacks `init --key/--server`.
  - `http-api.md` lacks projects, libraries, onboarding and `include_removed`.
  - `onboarding_key_ttl_days` is undocumented.
- [ ] Re-run the injection, generalization and head-to-head benchmarks. The published classifier claims predate #131's windowing; the A/B on four held-out sets showed no change, but the published files are not regenerated.

### Dashboard (UI change, recorded only, not to be done without the owner)
- [ ] **Basic guardrails that stay watching show no improvement.** They go live blocking only when nothing in the agent's real traffic would change; otherwise they watch, and watching rules don't count as stopping attacks, so before and after show the same N/N got through. The panel ignores `mode`, `wouldStop`, `stoppedBy.waitingFor` and `basicEnforcing`, the prompt then disappears, and nothing points to Simulate / Start blocking.
- [ ] **Backend fields the UI ignores** (beyond the attack-result fields in §6):
  - `rule.checks`/`checksOff`;
  - `/api/projects` `name/repos`;
  - `restorable` and restore-guardrails;
  - `total_ms`;
  - agent `confidence`/`evidence` from `agentfox init`.
- [ ] **Two severity components disagree:** `kit/SeverityPill` shows high as held/amber and `ui/Severity` (in the bell) shows it red.

## 8. UI test of onboarding and policies (2026-10-31), UI items recorded only

These need a UI decision.
- [ ] **The map's attack test and Testing → Attack tests disagree and don't link to each other.** Map (runs the real agent): 66/84 got through. Testing (gateway rules only): "0 got through · 100%", 22 tried / 18 stopped leaves 4 unaccounted, and its Past runs omit the map runs.
- [ ] **No drill-down on attack results**: map panel category rows and Testing run rows aren't clickable; errored attacks aren't shown anywhere. The per-attack list ("which attacks got through, and what stopped each") exists only in the orphaned wizard (`TestRunParts.tsx`).
- [ ] **Basic guardrails duplicate the Protect wizard's rules** (Input attacks ≈ Jailbreaks & prompt injection, Reply personal data ≈ Personal data in replies, Reply secrets ≈ Secrets & API keys); "Add basic guardrails" is offered after Protect already set them.
- [ ] **Packs still "Install" workspace-wide**: `LibraryPacks.tsx` (Settings → Detection → Packs, and `policies?tab=library`) bypasses the Libraries scope.
- [ ] **An applied library opens the raw policy page**: `policies/[key]/page.tsx` shows `LibraryPage` only on a 404.
- [ ] **Rule save and Tune feedback**: `CustomRule.tsx` shows "Open rule" while you are on that rule; `RuleTuner.tsx` Apply gives no confirmation.
- [ ] **Per-agent rules may be labelled "Every agent here"** (`AppliedRules.tsx` `where()`); recheck.
- [ ] **Map takes 8-12 s to draw** (`GuardrailMapLazy.tsx`); measure in prod first.
- [ ] **"red-team probes" is unexplained jargon** in `(product)/app/coverage/page.tsx` and `ProductMap.tsx`.
- [ ] **Search finds only page names/IDs**, not rules, tools or agents ("refund" finds nothing).
- [ ] **Three install commands**: setup card `pip install "agentfox>=0.5"` + `init --key`, Get started `pip install agentfox`, Welcome `uvx --from git+… agentfox up`.
- [ ] **One area, three names**: sidebar "Traces", page header "Observe", Overview tab "Activity".
- [ ] Rule page "Change" links to the tab you're on; rule "Checked by" lists four detectors for a words rule; "Prevent this" on an already-blocked run; Access table overflows with the limit editor open; search drops its first keystrokes (`CommandSearch.tsx`); the Attack tests dropdown resets after Run; Tool paths rows lack "View run"; an imported rule is named "Gr competitor check" and ToxicLanguage is listed twice; the map canvas is stale after an access change; the Connect-a-project skeletons and install line are cut off.

## Housekeeping

- [ ] Leftover agents in the local registry: test agents `my-agent` and `marketing-copy-bot` show up as projects, and a merged `python-backend` agent from before the mapper fix (re-run init on the CX repo). Delete once confirmed.
- [ ] Marketing site and favicon still use the old fox logo.
- [ ] `/app/map` URL could become `/app/agents` to match the menu.
- [ ] `dashboard/tsconfig.tsbuildinfo` is tracked and changes on every typecheck: ignore it and `git rm --cached` it.
- [ ] Dev only: SQLite "database is locked" under 8 concurrent attack-test guards.
- [ ] **Stale copy found in the docs pass (2026-11-07)**: `/compare` says "All 317" mappings (now 324) and "zero coverage" of Copilot Studio (we answer its threat-detection call); `docs/limits` says there is no annotation queue (`/api/eval/annotations/queue` exists); `init --help` lists the observe packs without `agent-integrity`; `deploy/README-dashboard.md` has old Nometria URLs and a 2026-09-20 status block. UI copy: owner decides.
- [ ] `THIRD_PARTY_NOTICES.md` lacks PIGuard, protectai deberta and sqlglot, and still uses old `guardrails/adapters/` paths.
- [ ] `scripts/gen/coverage.py` probes only `src/`, so `docs/status.md` shows the features moved to `ee/` (P1-9, P6) as absent.
- [ ] `capabilities/containment/effects.py`: `assess_effects` (idempotency key check) and `compensation_plan` are tested but nothing on the request path calls them; only `cascade_risk` is wired.
- [ ] No ADR records the open-core / `ee/` split.
