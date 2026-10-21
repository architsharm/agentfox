# AgentFox product TODO

A running list as we go. Newest priorities first. `[ ]` open · `[~]` started · `[x]` done.

---

## 1. Onboarding: detect agents correctly and set the first guardrails

- [~] **Agent detection that holds up on real repos.** (2026-10-20: mapper rewritten for the shapes below; all three test repos now map correctly; `tests/capabilities/onboarding/test_mapper.py`.) `agentfox init` maps with AST rules today (LangChain `create_agent`, `@tool`, `ChatOpenAI(model=)`); it only reports a single agent when a repo has one, and names it after the repo.
  - [x] OpenAI Agents SDK: `Agent(...)` and typed `Agent[Ctx](...)`, `function_tool(fn)`, `function_tool(...)(fn)`, `name_override`, tools from a helper (`tools=build_tools()`).
  - [x] Plain function-calling loops (`chat.completions.create(tools=...)` with JSON schemas), counted only when there's no framework agent.
  - [x] Multi-agent repos: one project, several agents, each with its own name/tools/model, and hand-offs (`handoffs=[...]`, `a.handoffs = [...]`, `.append/.extend`, `handoff(agent=b)`) stored as edges.
  - [x] Models from a constant (`MODEL = "gpt-5.2"`) or config default (`os.getenv("OPENAI_MODEL", "gpt-4o-mini")`).
  - [x] Risk labels: `issue_compensation`, `book_new_flight`, `assign_*`, `add_note` were "read only"/"outside"; now "can do real damage".
  - [ ] Still to cover: LangGraph `StateGraph` nodes, CrewAI `Agent/Task/Crew`, Claude Agent SDK, TypeScript agents.
  - [ ] Helper agents used as guardrails (CX's "Relevance Guardrail", "Jailbreak Guardrail") show up as ordinary agents; mark them as guard agents.
  - [ ] Agent slugs come from names, so two repos with a "Triage Agent" would collide; scope slugs by project.
  - [ ] The attack-test runner loads LangChain agents; check it with OpenAI Agents SDK and raw-loop agents.
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
  - [ ] Decide whether granting found tools should hold irreversible ones for approval instead of allowing them.
- [x] **Test first, then basic guardrails** (2026-10-20, replaces the watch-only first set): connecting a project starts its 140-attack test with no guardrails. The map's panel shows progress and results per kind of attack. Then one click adds the basic guardrails (prompt attacks in what users send blocked, personal data and secrets in replies hidden, nothing on tools; enforcing, in a pack of their own) and runs the test again, before vs after. After that, setup happens from the map.
  - [ ] The test runner only drives LangChain agents (`agent.invoke`); OpenAI Agents SDK projects (like the CX repo) fail with a clear error. Add a driver per framework.
  - [ ] Runs live on the user's onboarding row, so only the project whose `agentfox init` is connected can be tested. One runner per project would remove that.
  - [ ] A re-run hides the previous "with basic guardrails" numbers until it finishes; keep the last finished one visible.
  - [x] (2026-10-20) Panel cleaned up: just "Attack test", one row per set (name, what it tries, result on the right as before → after), Run and "+" in the header. "+" searches the attack library: four more sets (hidden encodings, other languages, fake authority, bulk actions), graded the same way. Chosen sets are kept per project.
  - [ ] More library sets that need a judge to grade (harmful content, system prompt extraction, off-topic use).
  - [ ] Decide whether the old "Protect" wizard page (`/app/projects/<slug>/protect`) should go; its button is gone from the header.
- [x] **Setup key + tests** (2026-10-20): the key is made on first ask and kept (`createdNow` now true on that first call); clear "can't reach the server" / "sign in again" errors; unit tests (`dashboard/lib/product/onboarding/connect.test.ts`) and backend tests for the key.
- [x] **One view for new signups and "+ Add a project"**: no projects = every page shows its empty cards + the connection card; Skip (first project only) folds it into a slim bar; `/app/onboarding` now leads there.
- [x] **Disconnect a project** (2026-10-20): switcher → "Disconnect <project>…" → `DELETE /api/projects/{project}`. Agents leave the dashboard, own guardrails emptied (new audited version, back to watching), tool permissions revoked, init's declared edges cleared, setup card forgets it. History kept. Re-running init treats it as new (tested live on marketplace-agent).
  - [ ] `agentfox disconnect` on the command line, so the repo side (stopping the runner) is one step too.
- [ ] **The setup card's `pip install agentfox` installs 0.4.0 from PyPI, which has no `init --key`** (found 2026-10-20: a user followed it and got "no such option --key"; the old init then created `~/.agentfox/agentfox.db` and `agentfox.toml` in the repo). Publish 0.5 before launch, and until then show the right install for the deployment (e.g. pin `agentfox>=0.5`, or a local/dev install line), plus a clear error if `--key` is missing.
- [ ] **Rotate the setup key.** It's made once per user and can only report a map and test results, but there's no way to replace it if it's pasted somewhere it shouldn't be.
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

- [x] Judge outage doesn't fail closed. (fixed 2026-10-20: `PipelineResult.judge_unavailable`; the enforcer blocks with `pipeline.judge_outage` when a judge tier is on, the posture says deny, and the call is enforcing; `tests/runtime/test_judge_outage.py`.)
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
- [ ] Projects become PR #112 systems (root agent plus everything it hands work to): the switcher and map read the system.
- [ ] Attack results report errored and not-run counts: show them.
- [ ] Rule "Checked by": use the backend's surface-aware `checks` list instead of the client-side join.
- [ ] Map "To / From the LLM" lines are a view: don't add their counts to other lines.

## Housekeeping

- [x] ~~`agentfox init --path <repo>` writes `agentfox.toml`~~: not a bug; with `--key` init only maps and connects.

- [ ] Leftover test agents `my-agent` and `marketing-copy-bot` show up as projects; delete once confirmed.
- [ ] Marketing site and favicon still use the old fox logo.
- [ ] `/app/map` URL could become `/app/agents` to match the menu.
- [ ] Nothing committed yet (branch `onboarding-phase1`).
