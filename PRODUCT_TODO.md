# AgentFox product TODO

A running list as we go. Newest priorities first. `[ ]` open · `[~]` started · `[x]` done.

---

## 1. Onboarding: detect agents correctly and set the first guardrails

- [~] **Agent detection that holds up on real repos.** (2026-10-20: mapper rewritten for the shapes below; all three test repos now map correctly; `tests/capabilities/onboarding/test_mapper.py`.) (2026-10-21: the mapper is now a thin adapter over discovery's scanner (`discovery/repo.scan` + `discovery/agents.py`), the same one `agentfox scan` and connected repos use; its own AST walker is gone. Tool risk and the system a tool touches come from `exposure.classify_tool` + `impact.infer_impact`, not a third classifier. The real airline repo maps to 8 agents, 15 hand-offs, triage first.) `agentfox init` maps with AST rules today (LangChain `create_agent`, `@tool`, `ChatOpenAI(model=)`); it only reports a single agent when a repo has one, and names it after the repo.
  - [x] OpenAI Agents SDK: `Agent(...)` and typed `Agent[Ctx](...)`, `function_tool(fn)`, `function_tool(...)(fn)`, `name_override`, tools from a helper (`tools=build_tools()`).
  - [x] Plain function-calling loops (`chat.completions.create(tools=...)` with JSON schemas), counted only when there's no framework agent.
  - [x] Multi-agent repos: one project, several agents, each with its own name/tools/model, and hand-offs (`handoffs=[...]`, `a.handoffs = [...]`, `.append/.extend`, `handoff(agent=b)`) stored as edges.
  - [x] Models from a constant (`MODEL = "gpt-5.2"`) or config default (`os.getenv("OPENAI_MODEL", "gpt-4o-mini")`).
  - [x] Risk labels: `issue_compensation`, `book_new_flight`, `assign_*`, `add_note` were "read only"/"outside"; now "can do real damage".
  - [x] (2026-10-21) Classifier audit fixed in main's classifiers (names read as words and verb phrases, never substrings): `issue_*` is a verb at the head of a name (`issue_compensation` moves money, no longer "untrusted input"); `start_return` (refund in its description), `list_and_refund` move money; `cancel_*`/`book_*` act irreversibly; `transfer_to_human` hands a chat to a person (not money); `notebook_search` reads; `fetch_and_email_report` talks to the outside; `get_membership_status` / `lookup_relationship_manager` no longer touch "Shipping". The old mapper's two test-encoded bugs (examples/ skipped, a repo-wide model guessed for an agent whose model is chosen at run time) are fixed.
  - [x] (2026-10-21) LangGraph `StateGraph`/supervisor/swarm, CrewAI, AutoGen/AG2, Google ADK, pre-1.0 LangChain and TypeScript OpenAI Agents SDK come with discovery; init's "Missing something?" lists them (`discovery.agents.RECOGNISED`). Still to cover: Claude Agent SDK.
  - [ ] Helper agents used as guardrails (CX's "Relevance Guardrail", "Jailbreak Guardrail") show up as ordinary agents; mark them as guard agents.
  - [x] (2026-10-21) Two repos with a "Triage Agent" are two agents: init never proposes over another repository's draft or disconnected agent (it takes `<repo>-<name>`), and disconnecting one never touches the other (`tests/capabilities/onboarding/test_projects_as_systems.py`).
  - [x] (2026-10-21) The attack-test runner drives LangChain / LangGraph (`invoke` with messages; `{"input"}` chains), OpenAI Agents SDK (`Runner.run_sync`) and plain function-calling loops (the `function` ref discovery reports), and every agent in the project, each with a suite from its own tools. Anything else is reported "can't drive this agent yet", not as a model error.
  - [x] (2026-10-21) The summary is discovery's coverage: code files read (Python and TS/JS), the frameworks found, files that could not be parsed, tools given to no agent, and a note when nothing readable was there.
  - [x] CLI says what it recognised and what it may have missed (2026-10-20): "Recognised: N agents, M tools from K Python files", files it couldn't read, tools found but not given to any agent, then "Missing something?" with the code shapes init reads and "run this again" (keeps guardrails). Test and mock code (`testing/`, `mocks/`, `fixtures/`, `test_*.py`, `conftest.py`) is no longer read as the agent.
  - [ ] Same "recognised / may have missed" summary in the setup card.
  - [ ] Add a missed agent or tool by hand in the dashboard (today: only grant a tool AgentFox already knows; "Register agent" doesn't place it in a project).
  - [x] Tested on 3 real repos (2026-10-20): `marketplace-agent` (1 agent, 5 tools), `itsm-helpdesk-agent` ("Helpdesk Support Agent", 4 tools, was 0), `cx-airline-agent` (6 named agents + 2 guardrail agents with the full hand-off graph, was 1 merged agent). Need a 4th: LangGraph or CrewAI.
  - [x] Name agents from the code (the agent's own `name=`, or a constant), not the folder.
  - [ ] Leftover from before the fix: a merged `python-backend` agent in the local registry; re-run init on the CX repo and delete it.
- [x] **First set of guardrails = observe-only, on the three lines that matter.** (done 2026-10-19: `FIRST_WATCH` in `capabilities/onboarding/service.py`; 11 rules in the agent's own layer, observe mode; the tools found in code are granted so default-deny doesn't block them; re-running init leaves an existing layer alone.) Right after init, turn on watching (not blocking) for:
  - what the **user says** (input),
  - what goes **to the LLM** (prompt/context: personal data, secrets, injected instructions),
  - what goes **to a tool** (tool calls: arguments, risky tools, data from other tools).
  - [x] Say so in the setup card's last step.
  - [x] (2026-10-20) One set for everything that goes to the LLM, the user's message included (`watch.llm_in.*`, which is how pre-flight checks a request anyway), and the LLM's answer is now watched too (`watch.llm_out.*`: personal data, secrets, harmful content). Untouched layers from the earlier init were brought up to date; edited ones are left alone.
  - [ ] Map: the backend's `completion` surface means "the agent says it's done", not an LLM call. It was drawn as "LLM calls"; now the LLM line shows "To the LLM" / "From the LLM" and the done-check isn't drawn. Decide where the done-check belongs on the map.
  - [ ] The OpenAI Responses API (`client.responses.create`) isn't patched by autoguard, so those LLM calls aren't checked at all.
  - [ ] Workspace packs still apply on top: `tool-containment` enforces (destructive SQL/shell) and baseline watches. Decide whether a brand-new workspace should start everything in watch mode.
  - [x] (2026-10-21) Superseded: init no longer grants anything. It proposes agents as drafts (main's `propose_draft`), never changes a live agent outside its project, and access is granted per tool by a person. `POST /api/projects/{project}/approve` adds a project's drafts. Dashboard still to show "Add all" and per-tool grants.
- [x] **Test first, then basic guardrails** (2026-10-20, replaces the watch-only first set): connecting a project starts its 140-attack test with no guardrails. The map's panel shows progress and results per kind of attack. Then one click adds the basic guardrails (prompt attacks in what users send blocked, personal data and secrets in replies hidden, nothing on tools; enforcing, in a pack of their own) and runs the test again, before vs after. After that, setup happens from the map.
  - [x] (2026-10-21) The test runner only drives LangChain agents (`agent.invoke`); OpenAI Agents SDK projects (like the CX repo) fail with a clear error. Add a driver per framework. Done: see the runner item under "Agent detection".
  - [x] (2026-10-21) **Attack test audit fixes** (`capabilities/onboarding/runner.py`, `attacks.py`):
    - Tools are faked at the framework while a suite runs (LangChain `BaseTool._run/_arun` on every tool class, including ones defined mid-run; Agents SDK `FunctionTool.on_invoke_tool`; a function loop's tool functions in every module and dispatch table), so class-based, factory-built, async and external-package tools no longer run for real. A tool that can't be faked (an SDK hosted tool or MCP server, a loop tool that can't be found) means the agent is not run. An audit hook refuses file writes outside temp/cache, deletes, renames and new processes for the suite's duration. Marker-file tests for each kind.
    - "After" checks the project's real policies: input, each tool call, each tool result and the reply go to `POST /api/onboarding/runner/runs/{id}/guard` (`redteam.dry_run_check`: the red-team runner's path, nothing persisted, setup key, that test's agents only) and the verdict is applied (block stops, escalate holds, redact rewrites). The runner's own `_held` / `_strip_instructions` simulation, the string guard ids and `BASIC_TEST_GUARDS` are gone; `/guardrails` only feeds the wizard's display. Old runners are not handed an "after" test.
    - Honest grading: per-type and run-level `gotThrough / stopped / resisted / errored / notRun`, `stoppedBy` (rule, surface, watching), benign controls with `overBlocked` and `falsePositiveRate`, `clean`. Errors are never resisted; a forbidden call before an exception still got through; a canary in an action tool's arguments counts.
    - The suite is domain-neutral: templates over the agent's tool roles (read / action / outside / hand-off), names, argument names and descriptions; faked reads shaped from the tool; sets needing a missing role are reported not run; hand-offs and read tools are never forbidden; no benign-as-jailbreak items. Default size per agent is 84 attacks + 8 controls (was 140, retail-specific).
  - [ ] An "after" test of a project whose agents are drafts is dominated by `capability.denied` (nothing granted yet): every tool call is stopped, and ordinary requests show as over-blocked. That is what live traffic would get today, but say it on the panel, and consider testing after tools are granted.
  - [x] (2026-10-21) Runs are their own rows (`onboarding_runs`), per project with their own map (`onboarding_projects`); a runner says its project when it polls, holds a run under a lease, and a dead runner's run is failed instead of blocking the project; results only append and a finished run refuses more.
  - [ ] A re-run hides the previous "with basic guardrails" numbers until it finishes; keep the last finished one visible.
  - [x] (2026-10-20) Panel cleaned up: just "Attack test", one row per set (name, what it tries, result on the right as before → after), Run and "+" in the header. "+" searches the attack library: four more sets (hidden encodings, other languages, fake authority, bulk actions), graded the same way. Chosen sets are kept per project.
  - [ ] More library sets that need a judge to grade (harmful content, system prompt extraction, off-topic use).
  - [ ] Decide whether the old "Protect" wizard page (`/app/projects/<slug>/protect`) should go; its button is gone from the header.
- [x] **Setup key + tests** (2026-10-20): the key is made on first ask and kept (`createdNow` now true on that first call); clear "can't reach the server" / "sign in again" errors; unit tests (`dashboard/lib/product/onboarding/connect.test.ts`) and backend tests for the key.
- [x] **One view for new signups and "+ Add a project"**: no projects = every page shows its empty cards + the connection card; Skip (first project only) folds it into a slim bar; `/app/onboarding` now leads there.
- [x] **Disconnect a project** (2026-10-20): switcher → "Disconnect <project>…" → `DELETE /api/projects/{project}`. Agents leave the dashboard, own guardrails emptied (new audited version, back to watching), tool permissions revoked, init's declared edges cleared, setup card forgets it. History kept. Re-running init treats it as new (tested live on marketplace-agent).
  - [ ] `agentfox disconnect` on the command line, so the repo side (stopping the runner) is one step too.
  - [x] (2026-10-21) Disconnect acts on the system's members from that repository only, keeps `agents.project` as provenance, keeps hand-offs into other projects, records each agent's live guardrail layers (`agents.guardrails_snapshot`) before emptying them, and `POST /api/agents/{slug}/restore-guardrails` puts them back after a reconnect (watching; blocking again only with `policy_production` and a recorded simulation). Disconnected agents are left out of `/api/agents` (`?include_removed=true` to see them), the policy agent tree and the map's sub-agents/parents.
- [ ] **The setup card's `pip install agentfox` installs 0.4.0 from PyPI, which has no `init --key`** (found 2026-10-20: a user followed it and got "no such option --key"; the old init then created `~/.agentfox/agentfox.db` and `agentfox.toml` in the repo). Publish 0.5 before launch, and until then show the right install for the deployment (e.g. pin `agentfox>=0.5`, or a local/dev install line), plus a clear error if `--key` is missing.
- [x] **Rotate the setup key.** (2026-10-21) The key is an `ApiToken` now: hashed, shown once, 30-day expiry (`onboarding_key_ttl_days`), `POST /api/onboarding/key/rotate`, revocable from the token list, refused once its owner is deactivated or loses the registry role; minting needs the registry role. Dashboard still to show prefix + Rotate.
- [x] **Local accounts**: `/dev/as/admin` (existing workspace) and `/dev/as/fresh` (a brand-new signup workspace); `next dev` only; tokens in `dashboard/.env.local`.

## 2. Map: cohesive, readable, easy to click

- [x] **More cohesive look, clearer sections.** (2026-10-20: user outside; the project in one box; agents as the loop; LLM, tools, documents & memory around each; rails as labelled pills on straight lines.)
  - Earlier idea kept for reference: Make it obvious what each region is: the conversation (user ↔ agent), the agent's brain (LLM, documents & memory), its hands (tools). Possibly faint labelled zones behind each group.
- [x] **Clicking a line is hard.** (done 2026-10-19: 44px hit band on every line, pointer cursor, hover lights the line indigo and opens its badge into "<line> · see guardrails"; bare-line clicks open the panel; "+" badge where nothing is set; badges are buttons, so Tab reaches them.)
  - [ ] A visible keyboard focus style on the line itself, and arrow keys between lines.
- [x] Multi-agent projects on one canvas (2026-10-20): grid of agents, entry agent wired to the user, hand-offs for the active agent, panel switches agents.
  - [ ] With many agents the full view is small; consider a compact "overview" mode (agents only) with click-to-expand.
- [ ] Per-agent LLM chain settings: order, confidence band, thresholds. Needs backend; today these are hard-coded and workspace-wide.

## 3. From the map to setting guardrails (today too much lives in Policies)

- [ ] Everything needed to set up a line's guardrails should be doable from the line's panel without opening Policies:
  - [ ] Turn a check on and choose what happens (block / ask / watch) in one place; today the check (detector) and the action (policy rule) are separate lists.
  - [ ] Show and edit the threshold ("block if prompt injection ≥ 0.7"). `min_score` isn't in the map payload yet.
  - [ ] Add a rule here ("never let `start_return` run over $100") without leaving the map.
  - [ ] Install a classifier model from the panel (today: "Not installed" → Checks page).
- [ ] Decide what Policies is for after this: the workspace-wide library, versions, packs.

## 4. Observability: integrated with init

- [ ] **One step, not two.** `agentfox init` should also turn on tracing (OpenTelemetry or our SDK wrap) for the agents it found, using the same key. No separate setup.
  - [ ] Decide the mechanism: init patches/wraps the LangChain agent at runtime vs. writes a one-line import vs. OTel exporter env vars.
  - [ ] Models page fills in only once real LLM calls are traced (today the demo traffic doesn't report a model).
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

- [x] Onboarding hardening (2026-10-21): first-load race on `onboarding_sessions` fixed (savepoint insert; GETs never write); basic guardrails go through simulate-before-enforce (observe unless the caller has `policy_production` and the rules were simulated); onboarding payloads validated (422, size caps); `agentfox init` keeps results until delivered; model errors name the provider.
- [ ] Judge outage doesn't fail closed. (A first fix on the onboarding branch was taken out on 2026-10-21; it is being redone on its own branch off main.)
- [x] Which checks feed a rule (fixed 2026-10-21). `custom.models` said it finds `CUSTOM` even when a model was registered as `PII`, `INJECTION`…; `/api/detectors` and `/api/features` now add `finds_all` (the registered prefixes). The rule→check join ignored surfaces, so a rule on `reasoning` or `tool_args` listed checks that never run there; it now matches kind AND surface in the backend (`catalog.can_fire` / `checks_for_rule`), custom rules map to the detector that matches their kind, and a detection rule naming no entity reads `finds: "any"`. Exposed as `checks` / `checksOff` / `surfaces` on every rule in the map and as `GET /api/policies/{key}/rules/{rule_id}/checks?agent=` for the rule page.
  - [ ] Dashboard: use those instead of `checksFor()` in `lib/product/checks.ts`.
- [x] Map counted decisions twice (fixed 2026-10-21): the "To the LLM" / "From the LLM" lines are a view. Each decision counts once on the stage owning its surface (reasoning on "From the LLM"), view stages carry `derived: true` and an overlapping `lineStats`, rules there are copies flagged `sharedWith`, and checks there `detectorsSharedWith`. `memory_write` is no longer "sent to the LLM". The map's models are the agent's own edges, seen in the 7-day window (or declared).
  - [ ] Dashboard: read `lineStats` for the LLM line's numbers, and don't count `sharedWith` rules / `detectorsSharedWith` checks again.
- [x] (2026-10-21) Projects are PR #112 systems: a root agent (nothing hands it work; in a cycle, the one that hands off to most, ties by name) and its `delegates_to` closure of any kind, across repositories. `/api/projects` lists them (key = root slug, plus `root`, `members` with depth/relation/repo, `repos`); `/api/projects/{p}/map` draws the closure; a repository name still resolves (to the systems with its agents) and an unknown name is a 404. `agents.project` is provenance only.
- [x] (2026-10-21) `talks_to` / `touches` edges keep their detail and resource kind in `lineage_edges.attrs` (migration `d7a4c2e9f1b6`); `kind` is the delegation relation only. Input boxes are no longer part of an agent's blast radius (`registry.service.lineage`).
- [ ] Red-team runs aren't tied to an agent, so "last test run" on the map is the workspace's last run.
- [ ] `sqlglot` (the `sql` extra) and Presidio (`pii` extra) aren't installed locally; one backend test needs Presidio.

## 6. UI changes, deferred (review of PR #122, 2026-10-21)

The new design stays. These are the UI fixes the review found. They come after the backend fixes, so some items depend on API changes listed under "Needs the backend first".

### Restore what the redesign dropped from main
- [ ] Home (`/app`): the "does anything need me" page (week stats, approvals). Today it redirects to `/app/map`, and the old page sits unused as `LegacyHome`.
- [ ] Agent page summary: Requests / Blocked / Held / Errors linked to runs, the top 3 open issues, the rules that fired most, and owner (with Assign), environment, framework and last active.
- [ ] Lineage and blast radius on the agent page (`AgentMap.tsx`, `/api/agents/{slug}/lineage`). Main had restored this on purpose (e4bf126d).
- [ ] Sub-agents and parents on the map, across projects too (PR #112's drawing; `relationLabel`, `parentLabel` and `drawnSubagents` in `guardrailMap.ts` are now unused).
- [ ] Rules that apply at every step (`map.everywhere`) and "Done check" (completion) rules: shown nowhere on the map today.
- [ ] Per-line traffic stats ("Last N days: X checked · blocked · held") and the inline Block / Ask / Watch / Off control on each rule row.
- [ ] Map panel with nothing selected: the tools summary (allowed / ask / not allowed, "Browse and change access").
- [ ] Nav:
  - Projects list with the Proposed tab and Add all (PR #112).
  - Reports.
  - The "All projects" scope.
  - Features, reachable again.
- [ ] Severity colours that `af-theme.css` neutralised:
  - eval drift vs healthy (`evals/page.tsx`)
  - risky vs safe policy simulation (`PolicyEditor.tsx`)
  - the missed-escalation panel
  - `.card.bad/.warn/.ok`
- [ ] Setup banner: fold main's banner (`SetupBanner.tsx`, `/api/onboarding` checklist) into the setup card, so there's one setup guide, not two.

### Fix
- [ ] Mobile: `af-theme.css:161` fixes the sidebar at 212px, so below 760px the nav links disappear.
- [ ] Redirect loop: `/app/map` goes to `/app/onboarding` when a map is empty or its call fails, and `/app/onboarding` goes straight back to `/app/map`.
- [ ] Attack test panel:
  - It polls `/tests` every 1.5s forever on a project that can't run.
  - A failed run, or one with errors, shows a green 0/N. Show errored and not-run attacks separately, and never green when anything errored.
  - It shows raw provider errors.
  - The same error handling applies to the RetestStep headline and the −X%.
- [ ] Shield mark: show it only when a rule acts on the line. Checks alone only record, and the panel already says so.
- [ ] "Blocks · watching only" → "Would block (watching)".
- [ ] Naming:
  - One name for Output / "Agent reply" / `agent_reply`.
  - The tool panel's empty state says "No policies on this line yet"; change it to "No rules for this tool".
  - The static "live" dot in the sidebar footer.
  - Raw rule IDs in Events.
  - "Activity" vs "Overview".
  - "Jev" shown to users.
- [ ] Events shows only the run's first surface. Sessions and Events filter the latest 100–200 traces on the client. Tools and Models use workspace-wide breakdowns, so they mix in other projects' traffic. Scope all of them on the server by the project's agents, and add a range picker.
- [ ] `af-theme.css` `:root` overrides main's tokens site-wide (`/docs`, `/login`, playground). Scope it to `.shell` or adopt it deliberately everywhere, and align the logo between marketing and the app.
- [ ] `NOMETRIA_DEV_SESSION_TOKEN` / `NOMETRIA_DEV_FRESH_TOKEN` → `AGENTFOX_*` (the rename is otherwise complete). Make dev auto-login on every cookieless GET opt-in.
- [ ] Revert the machine-generated `next-env.d.ts` change.
- [ ] `/api/projects` is fetched three times per page, and `SideNav` calls `router.refresh()` on agent pages.
- [ ] Duplicated check-name maps (`GuardrailMap.tsx` `MODULE_NAME`/`KIND` vs `lib/product/checks.ts`).
- [ ] New-user gate hides Policies / Approvals / Issues / Testing / Evals before the first connect, so a new user can't browse policy packs.
- [ ] Dead code: `LegacyHome`, `projectNav`, `setupBanner.ts`, `useProjectScope.ts`, `AppChrome`'s `banner` prop, 5 unused shadcn components (avatar, badge, select, separator, tooltip), and the unread `agentfox_project` cookie.
- [ ] The orphaned 6-step wizard (`/app/onboarding/[step]`, ~2,600 lines): move its risk-label copy (RISK_HELP / RISK_WHY) into the setup card, then delete it along with its wizard-only endpoints.

### Needs the backend first (see the fix branches)
- [ ] The setup card's install line has no `--server`, so on a hosted deployment it points at localhost. Also pin `agentfox>=0.5` until PyPI has 0.5.
- [ ] The setup key is shown once and has rotation: show its prefix, and add a Rotate button.
- [ ] Agents arriving from `init --key` come in as proposed: the setup card needs an "Add all" step and a tool-access step.
- [~] Projects become PR #112 systems (root agent plus everything it hands work to): the switcher and map read the system. Backend done 2026-10-21; UI to do:
  - [ ] Switcher and `/app/map`: key projects by `project` (= root slug) from `/api/projects`; label with `name` (the root's) and show `repos` / member count; draw `members` (depth, relation) instead of assuming one repo = one project.
  - [ ] Onboarding panel calls (`/api/onboarding/projects/{p}/tests`, `/tests/sets`, `/basic-guardrails`) are still keyed by the repository init connected: pass `repos[0]` from the project, not the root slug (or ask for a resolver on those routes).
  - [ ] Map: use each agent's `depth`/`relation`/`parent`/`repo` and `handoffs[].relation` to draw sub-agents and parents from other repositories (PR #112's `relationLabel`/`parentLabel`), and `roots` when a repository name opened more than one system.
  - [ ] Handle 404 from `/api/projects/{p}/map` (unknown or disconnected project) instead of an empty map; drop a stale `agentfox_project` cookie.
  - [ ] Disconnect dialog: say which agents go (`removed`) and that hand-offs to other projects stay; after reconnecting, offer "Restore guardrails" for agents with `restorable: true` (structure agents and map agents) via `POST /api/agents/{slug}/restore-guardrails` (404 nothing to restore, 409 still disconnected).
  - [ ] Projects page (`/app/projects`): `/api/agents` now leaves out disconnected agents; rejected ones are still listed as live (`status !== "draft"`): filter `rejected` too.
  - [ ] Setup card / init map: tools carry `why`, `impact` and `capabilities` (trifecta flags); agents carry `kind`, `root`, `handoffs[].relation`; frameworks are discovery's names ("OpenAI Agents SDK", "LangGraph"). Show the relation on hand-off lines.
- [ ] Attack results report errored and not-run counts: show them. (2026-10-21) The backend now sends, per run and per `byType` row: `stopped`, `resisted`, `errored`, `notRun`, `controls`, `overBlocked`, plus run-level `falsePositiveRate`, `clean` and `skipped` (`[{type, agent, reason}]`), and `notRunReason` per set. Panel: show "stopped by AgentFox" separately from "resisted" (the before→after drop is today drawn from `gotThrough` only), show errored and not run, and never show a run as clean unless `clean` is true.
- [ ] (2026-10-21) Each result now has `outcome` (got_through / stopped / resisted / errored / not_run; for a control allowed / over_blocked / errored), `agent`, `stoppedBy` (`{surface, rule, verdict, mode, reason, tool, watching}`), `control` and `reason`. The feed keeps `result` in its three old values and adds `outcome`, `agent`, `stoppedBy`. "See all with full traces": add filters for stopped / errored / not run, show the rule that stopped each one, and say "would stop once it blocks" when `stoppedBy.watching`.
- [ ] (2026-10-21) Multi-agent projects: results carry `agent`; group the panel and the trace list by agent.
- [ ] (2026-10-21) Library entries have `notRunReason` (e.g. a read-only agent can't be tested for unsafe tool use): show it instead of "0 attacks".
- [ ] (2026-10-21) Run totals changed: the default suite is 84 attacks per agent (plus 8 controls), not 140; copy that says "140 attacks" must read `total`.
- [ ] (2026-10-21) The wizard's Protect / Retest steps (`ProtectStep.tsx`, `RetestStep.tsx`) still `GET/POST /api/onboarding/guardrails`; those toggles no longer change what the "after" test measures (it checks real policies). Replace Protect with the project's "Add basic guardrails" call, or delete the wizard (see section 2).
- [ ] (2026-10-21) An "after" run handed to an old `agentfox init` fails with "too old to test with your guardrails": surface that error with the upgrade line.
- [ ] Rule "Checked by": use the backend's surface-aware `checks` list instead of the client-side join.
- [ ] Map "To / From the LLM" lines are a view: don't add their counts to other lines.

## Housekeeping

- [x] ~~`agentfox init --path <repo>` writes `agentfox.toml`~~: not a bug; with `--key` init only maps and connects.

- [ ] Leftover test agents `my-agent` and `marketing-copy-bot` show up as projects; delete once confirmed.
- [ ] Marketing site and favicon still use the old fox logo.
- [ ] `/app/map` URL could become `/app/agents` to match the menu.
- [ ] Nothing committed yet (branch `onboarding-phase1`).
