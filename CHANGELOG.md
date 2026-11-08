# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Published benchmark numbers do not live here. They live in the result files under
`benchmarks/`, and `scripts/claims.py --check` binds every number quoted in a document to
the file it came from.

## [Unreleased]

### Added
- **Restore this version.** A pack's or a business rule's History has "Restore this
  version": the old rules go live again as a new version, in the current mode
  (`POST /api/policies/{key}/versions/{version}/restore`,
  `GET /api/business/rules/{key}/history`,
  `POST /api/business/rules/{key}/versions/{version}/restore`).
- **Held calls reach Slack.** With a Slack channel connected (Settings → Alerts), every
  call held for approval is posted with a link to approve or deny it. The Approvals
  page says who is told and links to where to set it up.

### Changed
- **One rule model for business rules.** An approval limit written in New rule is
  listed in Applied rules (in Your rules), its page
  (`/app/policies/rules/business.<key>`) shows its real mode, hits and history, and
  `agentfox policy effective` and `policy list` list and count it.
- **Business rules start blocking through the same gate as libraries.** Start blocking
  replays the last 7 days of calls through the rule and shows what it would have held,
  then confirms; the gateway refuses to enforce without that recorded simulation
  (`POST /api/business/rules/{key}/simulate`). Switch to watching asks first.
- **A denial sticks.** A retry that presents the approval a person denied, for the same
  call, is blocked with the `approval.denied` rule and their reason, instead of
  filing a fresh approval.
- **An approval's reason leads with the rule that held the call**; rules that were only
  watching come after it, labelled "(watching only)".
- **A held call's run shows its answer**: Approved or Denied and by whom, in the run and
  the runs list, and its Approval link opens that approval.
- **Approvals follow the project switcher** like the other pages.
- **The default project** is the one with the most recent traffic among projects with an
  added agent, never a shadow agent. `GET /api/projects` carries `last_seen_at`.
- `agentfox policy effective` (and `GET /api/policies/effective`) default to the
  environment the gateway resolves the agent in, not the CLI's configured one, and the
  CLI prints a title beside each rule id. `agentfox permit approvals list` prints full
  ids and wraps between words.
- **Policy screens say things in words and finish what they start.** On an agent's map,
  a rule change that would loosen a rule its library closes now explains why and offers
  "Allow agents to loosen it, then apply"; clicking a rule on a rail opens its settings
  in place (block/ask/watch/off for this agent, and its threshold, "Block if prompt
  injection ≥ 0.7"); tool limits read "amount under $1,000 · currency USD only", not
  JSON; node names wrap instead of cutting off, at a readable size.
- A Block or Ask chosen in a library that only watches reads "Block · watching" and is
  dimmed, on the map and in Tune; a watching rule's header says "Would block". Blocking
  is red, holding amber; the Blocking mode pill is no longer green.
- Tune: "Apply this change to" starts at the rule's current scope; "Checked by" marks
  checks that are off, have no model downloaded or have no judge on.
- A rule's History reads "Sensitivity changed from Medium to High"; a saved one-rule
  change now notes the value before it (`(was {...})`).
- Library drawers show rule titles, render the description's markdown behind
  "Details", and move control IDs to a details row. The Checks tab names every check
  (no `custom.validators`, no `JEV`, one "Prompt injection (judge)").
- Approval limits and words rules: help text, "Preview" and "Save rule", a readable
  name instead of the slug, no false "Not used" for the sentence that became the allow
  band, and an "Applies to" picker (this agent by default, or every agent). Business
  rules now return the agent they are scoped to (`agent`).
- Libraries: one primary action per card, a "Recommended" tag on Basic guardrails, and
  "Apply to the rest of <project>". Applied rules are grouped by library, with
  Blocking / Watching filters.
- One look across the site and the app (UI audit, 2026-11-08). App links, focus rings
  and checkboxes use the brand rose instead of indigo; every app button is a pill; an
  active filter chip looks like the segmented control; "Blocking" is never green; table
  headers start with a capital; sidebar page names are set in the site's sans.
- One name per area: the traces area is **Activity** everywhere (sidebar, title,
  breadcrumb, back links, Cmd-K); **Testing** for its page title; the agents list is
  **Agents** with **New agent** (a *project* is a connected repository or system).
- App pages say things in words: compliance rationale as sentences, agent display names
  in issue titles and activity rows, issue evidence as plain lines with IDs in a
  copyable details row, hand-offs as "Handed off to …", "Default workspace" instead of
  `org_default`, readable audit-log subjects, control IDs labelled as such.
- Sign-in page: styled token button, wrapping self-hosted command, theme button, and the
  brand wall in the site's palette. The 404 page has the public header and footer.
- Docs: a "Contents" drawer on phones, scrolling tables, `/login` instead of the missing
  `/signup`, and one install path (`pip install -U agentfox`, then
  `agentfox init --key … --server …`).
- Blog: re-shot images against the current UI, one image per post, the dark callout's
  secondary button is visible, and screenshots are dimmed in dark mode.
- Public copy: the footer uses the control-plane line, pricing says what is offline by
  default, the privacy page drops source line numbers, benchmark wording no longer
  contradicts itself (numbers unchanged).
- **A new workspace starts every pack watching, tool containment included.** `agentfox init`
  bound `tool-containment` in enforce, so `intent.undeclared_irreversible` held a normal $50
  transfer with no stated task for a person, against the promise that nothing your users do
  is blocked until you say so. `init` now binds every shipped pack in observe (a second run
  keeps each pack's mode) and says how to start blocking: `agentfox policy enforce
  tool-containment`, or Start blocking in the dashboard after its simulation. A missing
  grant (once the agent holds any), a destructive statement such as `rm -rf ~/` and
  tampering with AgentFox are refused whatever the packs' modes. The pack still declares
  `enforce`: `agentfox up --mode defaults` ("Shipped defaults") now applies it, where it
  left whatever `init` had bound; the demo seed and the benchmarks are unchanged.
- **A guard response's `mode` is the mode of the rule that decided it.** A call held by an
  enforcing rule read `mode: observe` when a watching rule had fired the same effect first,
  or when a grant or a destructive statement decided it with every pack watching.
- **`agentfox.Blocked` reads as one sentence**, naming the rule by its dashboard title
  ("Jailbreaks & prompt injection: … (also: System prompt extraction).") instead of every
  rule's reason joined with ".;". Left uncaught, it prints one line, "AgentFox blocked this
  message: <reason>. Catch agentfox.Blocked to handle it.", instead of a traceback
  (`AGENTFOX_VERBOSE=1` keeps it); every other exception reaches the previous
  `sys.excepthook` untouched. The Python reference shows how to catch it.
- `agentfox init --key` prints the full "Missing something?" list of recognised shapes only
  when it found no agent or no tool; otherwise one line points to the docs.
- `agentfox init --server <url>` with no `--key` reads `AGENTFOX_API_KEY`, so the key
  stays out of `ps` and the shell history. A plain `agentfox init` still sets up this
  machine. (The dashboard's setup card keeps `--key` until a release with this is out.)
- **The playground's "Watching" really watches.** The switch moves every content check in
  the sandbox (the baseline, each sandbox agent's own layer, custom words and topics);
  only the baseline used to flip, so an injection was blocked while "Watching". Watching,
  it shows "would block" and the agent's reply; blocking, it is stopped. Limits on what an
  agent may do apply in both.
- Playground sandboxes are made on the first action, not on page load; the creation limit
  is 30 an hour per visitor (was 8 per proxy address, which on Vercel meant everyone). Over
  it, the answer says when to try again (`Retry-After`, `retry_after_seconds`) and the page
  shows a notice instead of a "Start a new one" button that could not work.
- Playground "why" is one sentence; regulation citations sit behind a disclosure. The
  poisoned-document suggestion stays after the first message. On phones the agent picker
  is one scrolling row and the chat follows it.
- **Attack-test panel:** a headline total ("22 → 9 attacks got through · 12 of 12 normal
  requests still answered"), a legend that says fewer is better, "N not run: why" under its
  set, progress shown as progress on every run, and a note naming any set that got worse
  (results of a live model vary between runs). The action is "Turn on basic guardrails and
  test again", after a line saying the first run was watching only.
- One count for the suite: the run carries `controlsTotal`, and the card and `agentfox
  init` both say "117 attacks + 12 normal requests" (the CLI said 129 "attacks and checks").
- **Testing → Attack tests:** "Attacks" counts attacks only (it counted the normal
  requests too), so stopped + got through adds up; "Score" (recall, counting watching
  catches as stopped) is now "Stopped live"; normal requests answered get their own column.
- **Threat coverage** counts an attack caught only by a watching rule as got through, the
  Testing page's definition, and no longer counts normal requests as attempts.
- **Reports:** the "Projects" tile counted agents and is now "Agents"; High-risk agents
  uses the same counts as Agents by risk; "Requests stopped" is "Requests held or blocked"
  and says it is traffic. The Frameworks headline is the workspace's own figure, not an
  average of framework rows, and Compliance uses the same definition (working of every
  control that applies) instead of "of measured".
- `/live` says how long ago the last run was and shows a "Behind schedule" notice past two
  hours; it says "on an hourly schedule" rather than promising "every hour".
- The CI tab never prints a loopback gateway address in a snippet meant for a CI runner; it
  uses `$AGENTFOX_URL` and says so.

### Fixed
- "Start blocking" on Your rules said "0 would have been stopped" right after a words
  rule had flagged a message: it counted calls newly blocked compared with what a
  watching rule already would have done. It now counts what the pack's own rules
  would stop (`runs_own_would_stop` in a simulation).
- "Your rules" said "2 rules · blocking" while one of them was only watching; it now
  says each rule's state ("1 blocking, 1 watching").
- **After a hand-off, calls are credited to the agent running them.** `agentfox.auto()`
  credited every call to the agent it names, so after the OpenAI Agents SDK triage agent
  handed off, the FAQ agent's own `faq_lookup_tool` was listed as "Blocked: tools the agent
  wasn't given" with a high issue "triage-agent tried to faq_lookup_tool without
  permission". Each model and tool call now goes to the agent the framework is running:
  the Agents SDK's current agent (read as its models are called), a LangGraph supervisor
  or swarm member (the graph namespace it runs in) and a CrewAI agent running its task. The
  agent a system starts with keeps the name `auto()` was given.
- **A call that only would have been blocked is never recorded as blocked.** A tool call
  `auto()` let run (observe mode, or the no-grants carve-out) was stored with verdict
  `block` and listed as Blocked. It is recorded as allowed, in observe, with the rule kept
  as what would have blocked it ("Would block" on the runs list).
- `.github/workflows/monitors.yml`, which drives the hosted job runner and so `/live`, ran
  as a green no-op since it was added: the cron secret was set and the URL was not. It now
  falls back to a repository variable and, upstream, the hosted gateway, and fails when
  half-configured.

### Security
- `docs/screens/setup-key.png` showed a complete API key; it is re-captured with the
  key masked.
- **Cmd-K searches agents, tools, rules and open issues**, not only page names, from one
  `/api/search` index built from list endpoints the app already calls.
- `AGENTFOX_TRUSTED_PROXY_HOPS`: the per-visitor limits on public routes (playground,
  waitlist, showcase) read the visitor's address from `X-Forwarded-For` behind that many
  trusted proxies. Defaults to 1 on Vercel, whose edge overwrites the header, and 0
  elsewhere.
- `GET /api/playground/world`: the playground's agents and prompts without a sandbox.
- The dashboard moves from Next.js 16.4.0 to 16.4.5. 16.4.0 is affected by
  GHSA-2464-fhr4-w9xw (unauthenticated remote code execution in the image optimisation
  API with SVG files), GHSA-673q-mjm6-r5xr (remote code execution in `use cache` functions
  returning typed arrays) and GHSA-p3m5-59mp-jv5r (denial of service with Server Actions).
  Dev-only test tooling (vite, vitest) is updated for its own advisories. `npm audit`
  reports 0 vulnerabilities, and `next build` no longer stops on the security check.

## [0.5.1] - 2026-11-08

The first-run release. A new user's own agent now gets the "wow": `agentfox up` adds
the one line to the right file under the right name, `agentfox.auto()` governs the OpenAI
Agents SDK, LangGraph, CrewAI, AutoGen and pydantic-ai without false alarms on an agent's
own sub-agents and hand-offs, and the attack test's numbers are true. Sign-in adds Google
and Microsoft.

### Added
- Sign in with Google or Microsoft, beside GitHub. Each new identity opens its own
  workspace, keyed on the provider's subject (never the email), through the new
  `POST /api/auth/oauth/provision`. A button shows only when the deployment sets that
  provider's `*_CLIENT_ID` and `*_CLIENT_SECRET`.

### Changed
- **`agentfox up` sets up the agent the entry file runs, and only its system.** The name
  is the agent a run site in that file starts (`agent.run_stream(...)` in AutoGen,
  `agent.run_sync(...)` in pydantic-ai, `Runner.run(...)`, `crew.kickoff()`,
  `graph.invoke()`, on the variable the code holds it in), not the first agent defined
  or one from another file. In a folder of independent examples it sets up one system,
  grants it only its own and its sub-agents' tools, and says how to pick another
  (`agentfox up --agent <name>`, which also moves `auto()` to that agent's file, with the
  best few named). When nothing (a declared script, langgraph.json, a single runnable
  file) singles one out, it starts with the system that has tools of its own and a run
  site, then the most agents and tools, never a tool-less agent beside one with tools.
  The count of separate systems is the number of independent systems, the same on every
  run. Choosing another file at the question re-derives the agent and its tools, a saved
  name included; with `--agent`, `up` says when that file does not run it. A swarm,
  crew or graph the code names only by its variable (`builder = create_swarm(...)`)
  runs under its project's name (`pyproject.toml`, else the folder); its members keep
  theirs. The name is shown before anything changes, and asked in a terminal so it can
  be edited; the plan lists it.
- **One naming scheme.** Agent keys are the code's name as lower-case words joined by
  hyphens, CamelCase included (`GameBuilderCrew` is `game-builder-crew`, no longer
  `gamebuildercrew`), with the file's name added only when two agents share one. `scan`
  lists agents by that key, the one its hand-off lines, `up` and `auto()` use.
- **Findings that were not findings.** An agent run site (`Runner.run(...) — runs an
  agent`) is information, not severity high; it still counts as an ungoverned model
  call. A constant query with placeholders (`execute("... WHERE id = ?", params)`) is no
  longer "SQL built from a string"; f-strings, `%`, `.format()` and `+` still are. A
  remote MCP server over HTTPS with no auth header, or with an OAuth login in its config,
  is information (remote servers sign in with OAuth), not medium; plain http stays.
- **Skills inside virtualenvs and installed packages are not the project's.** `up`,
  `scan` and `scan skills` skip what the repository scan skips (`.venv`, `site-packages`,
  `node_modules` …) and any virtualenv under another name (`pyvenv.cfg`).
- **First-run copy.** A scan after `up` says the next step (run the app, `agentfox
  findings`, `agentfox test redteam <agent>`) instead of "Start watching this agent:
  agentfox up". `up`'s scan lists only the coding agents this project is set up for
  (others are named as "on this machine"). `agentfox doctor` shows the normal defaults of
  a local first run (no traffic yet, development auth, nothing declared, fail-open, an
  optional detector not installed) as information (`i`), not warnings; in staging or
  production they are warnings again. Text that pointed at dashboard pages ("Policies →
  Libraries") on an install without one names the CLI command instead. `init --key`
  shows a crew or swarm as the system that runs its members, not as an agent with an
  unknown model.
- **`auto()`'s start-up banner is three lines**: the agent and mode, what is patched and
  anything that is not governed, and what is blocked. `AGENTFOX_VERBOSE=1` prints the
  full account (`agentfox.state().summary()` returns it). The README's quickstart says
  the prompt-injection classifier is the `agentfox[classifiers]` extra and what runs
  without it.
- The sign-in page is shorter: one line of explanation, one button per provider, the
  token sign-in folded away, and the terms and playground in a footer line.
- **`agentfox up` adds `agentfox.auto()` where your agent starts, and only that.** It
  finds the file that starts the agent under `src/` and in packages, from
  `[project.scripts]` (and Poetry's), the graphs `langgraph.json` loads, a `__main__`
  guard, or a line that runs an agent (`Runner.run`, `crew.kickoff()`,
  `graph.invoke()` …), and adds the line there by default, for any Python agent the
  scan finds (the OpenAI Agents SDK included). The name in the call is the agent the
  entry point starts, the same one `up` registers; an existing unnamed `auto()` is
  flagged.
- **`up`'s defaults match the project.** In a Python agent's repository it no longer
  writes Claude Code / Codex hooks, grants the coding agent its MCP servers' tools,
  starts the hook daemon and the local API, or writes a GitHub workflow: those are
  `--with coding-agents`, `--with view` and `--with ci`. They stay the default in a
  repository set up for a coding agent with no agent of its own. The workflow is never
  written below the repository root, where GitHub would not run it. Enterprise items
  are left off the first run's list and named once at the end. No name question when
  the code names the agent, no per-tool impact review unless asked for.
- **`up` ends with what to do next:** run your app, `agentfox findings`, then
  `agentfox test redteam <agent>`; reviewing impacts and enforcing come after.
- **Hooks call `agentfox` by absolute path**, so a virtualenv install works from the
  coding agent's environment. A hook installed under the bare name is recognised and
  not added twice.
- **`agentfox demo` runs in a database of its own** (`demo.db` beside your
  workspace's), so a real project's `agentfox findings` and `agentfox declare list`
  never show the demo's agents. It ends by saying how to look around that database;
  `--in-workspace` keeps the old behaviour. Reason lines are wrapped, not cut mid-word,
  and the closing lines name only commands this installation has.
- **`AGENTFOX_URL` and `AGENTFOX_API_KEY` everywhere.** `agentfox up`, `scan --submit`,
  the SDK and the LiteLLM guardrail read the names `auto()` and the README use; the
  older `AGENTFOX_API_URL` / `AGENTFOX_API_TOKEN` are still accepted. `up` writes the
  new names.
- `agentfox demo` is listed in `--help` (Start), and `--help` says where the
  coding-agent hooks live.
- `scripts/quickscan.sh` installs the published release from PyPI; `--main` installs
  the current git main.
- An in-process app (`auto()`, the SDK) says a detector cannot run (the classifier
  without `agentfox[classifiers]`) once per installation, not on every run;
  `agentfox doctor` keeps listing it. The gateway and hook daemon still say it on every
  start.

### Fixed
- **LangGraph agents can be checked against an account.** The attack test's checks
  (`init --key`), `agentfox.auto()` in account mode and the SDK's remote client posted
  a tool's arguments as they were; a LangGraph hand-off tool's state holds
  `HumanMessage`s, so checks failed with "Object of type HumanMessage is not JSON
  serializable" and `auto()` crashed the app. LangChain/LangGraph messages are now sent
  as `{role, content, tool_calls, tool_call_id}`, and pydantic models, dataclasses,
  dates and anything else as plain JSON (`core/jsonable.py`).
- **`agentfox up` registers each agent once.** It registers its agent under the name
  the scan gives the same code (`<repo>/<agent>`), with its framework, the tools it is
  handed and the repository `init` maps it from, so the recorded scan lands on it
  instead of proposing a second, production "SHADOW" copy (`lg-supervisor-supervisor`
  beside `supervisor`). A single-agent repository is proposed as its agent, not as its
  directory (`pai-bank`). Drafts an earlier run left beside the agent are folded in and
  dismissed (`agent.draft.merged`). A local `up`'s drafts are proposed for
  development. `agentfox agents list` labels drafts `draft`, not `SHADOW`, and hides
  dismissed or disconnected agents unless `--all`.
- **`agentfox test redteam` attacks the agent `up` set up through its own tools.** `up`
  now declares the tools it grants, and the agent's tool grants are read when it
  declares none. When no own-tool attack can be written, it says why (no tools and no
  grants, only wildcard grants, or no set applies) instead of "Run agentfox init".
- **`agentfox test redteam` has one meaning of "got through".** An attack live traffic
  doesn't stop today, including one only a watching (observe-mode) rule catches, counts
  as got through in the recall line, the per-set table, the verdict and the exit code
  (1, unless `--allow-escapes`). It said "recall 100% … 0 got through", then "11 of 18
  attacks get through today", and exited 0.
- **`agentfox init` keeps the modes your policies are in.** Run after `up` (which puts
  every pack in observe), it put `tool-containment` back to enforce. A pack's declared
  mode is now only its first (`save_policy(keep_mode=True)`); the seed does the same.
- `agentfox report evidence` without AgentFox Enterprise says what it is instead of
  "unexpected extra argument (evidence)".
- `agentfox doctor` printed `pip install 'agentfox'` for `agentfox[classifiers]`: Rich
  read the extra as markup.
- A second project's `up` called the API on :8080 "another serve with its own
  database" when it was the same installation's on the same database; it is reused
  now, and anything else on the port is described as what it is. `agentfox serve`
  says it serves JSON and where the web dashboard is (Cloud or self-hosted).
- A hook daemon killed with SIGTERM or SIGHUP removes its socket; a socket left by one
  killed harder is detected and removed by `agentfox up` and `agentfox admin hooks status`.
- `agentfox init`'s closing steps mention `agentfox demo` and `agentfox up`.
- **`agentfox scan` counts model calls, not agent definitions.** `StateGraph(...)`,
  `builder.compile()`, `Crew(...)` and any `re.compile` in a file importing LangGraph
  were counted as ungoverned model calls (LangGraph's own repository read "2039 of 8
  model call sites are ungoverned"). Definitions are now inventory only, and what runs
  an agent counts as its model call: `Runner.run` / `run_sync` / `run_streamed`, a
  crew's `kickoff`, `invoke` / `stream` on a compiled graph, a chat model reached
  through `.bind_tools()` / `.with_structured_output()` / a chat-model constructor, a
  run method on any variable holding an agent the scan found, and the Agents SDK's
  `run(agent, ...)` in TypeScript. With agents but no such call, the scan says where to
  look instead of "No model calls found".
- **Tools handed over as plain functions are tools.** `TOOLS = [search]` passed to
  `ToolNode` / `.bind_tools()` now shows under "can reach" and is declared by
  `agentfox up`, so "1 tool" on the agent line and the reach count agree. A tool that
  opens whatever path the model gives it (`file_path`, `path`, ...) reads private data.
- **Agents without a model run the framework default.** An Agents SDK or CrewAI agent
  that sets no model shows "default model" in the scan and "OpenAI Agents SDK default"
  on the onboarding map, instead of "unknown model"; `AgentSpec.to_json()` gains
  `default_model`. A model chosen at run time stays unknown, and nothing is declared.
- **Trifectas are per agent system, and the fix names the agent.** Tools of separate
  scripts in one directory are no longer joined into one agent; agents that hand off
  to each other still share one finding. `permit grant` now names the agent's slug.
  Wording: "user data", "contact info", "can read secrets".
- **Tests, docs and benchmarks are left out of a scan by default** (read for secrets
  only); `agentfox scan --include-tests` reports them. A repository of many examples
  lists its agents by directory.
- **`agentfox scan machine` false positives.** Skill docs no longer produce critical
  `shell.destructive` for `rm -f ../out.docx` (a named relative file), for regexes or
  prose between two code blocks (a closing fence used to open a new block), or
  `skill_poisoning` for a skill that quotes "ignore previous instructions" to tell the
  model to refuse it.
- **The attack test no longer shows a pass it isn't.** On the map's panel, a test where
  nothing ran (the agent couldn't be imported) says "Not run" with the reason and the
  fix, instead of a green "0/26". Errored and not-run attacks are counted on each row,
  a number is green only when everything in it ran and nothing got through, and the
  ordinary requests the guardrails must let through are reported ("9 of 11 normal
  requests answered, 2 blocked"). A failed "after" run keeps its partial numbers, a
  re-run keeps the last finished numbers on screen until it is done
  (`firstPrevious` / `withBasicPrevious` on `/api/onboarding/projects/{p}/tests`),
  raw provider errors become sentences (`errorSummary`, `runner.explain_not_run`),
  watching basic guardrails say "would stop N once blocking", and the panel no longer
  polls a project that can't run. Testing → Attack tests counts blocks by watching
  rules as getting through live traffic and shows "—", not a green 0, when no attack ran.
- **`agentfox test redteam` attacks the agent through its own tools.** Probes are
  written from the agent's declared tools by the attack library the dashboard's
  attack test uses (the message, an instruction planted in a record it reads, the
  reply that leaks someone's details, the call to its own action tool, and ordinary
  requests as controls); the generic probes run with `--builtin` or when no tools are
  known. The report separates blocked from "would block (watching)", summarises per
  attack set, and ends with a one-line verdict ("N of M attacks get through today;
  K once the watching rules block. X of Y normal requests answered").
- **Agents SDK agents get the run context their code expects in the attack test.** An
  agent built as `Agent[SomeContext]` (or whose tools and hand-off callbacks are
  annotated `RunContextWrapper[SomeContext]`) is now run with a fresh default
  `SomeContext()` per attack, as the app passes one to `Runner.run`. Before, its
  callbacks failed on `context.context.<field>` and those attacks were reported as the
  agent's errors (11 of 60 on OpenAI's customer-service example; now none). A context
  that can't be built with no arguments is said as such: the attacks that fail on it
  are "not run: needs a run context AgentFox couldn't build (<Type>)", not errors.
- The OpenAI Agents SDK's own trace export is switched off while attack tests run,
  so `[non-fatal] Tracing client error 400` lines no longer leak into `agentfox init`'s
  progress output.
- **`agentfox.auto()` governs the OpenAI Responses API, so an OpenAI Agents SDK app is
  checked with the one line alone.** Found by a new-user walkthrough: the Agents SDK's
  customer_service example with `auto()` added recorded 0 traces and 0 decisions,
  because the SDK calls `client.responses.create`, which was not patched.
  `Responses.create` and `.parse` are patched, sync and async, which covers
  `responses.stream()`, `stream=True` and the `with_streaming_response` /
  `with_raw_response` paths (a raw response is checked when it is parsed). The request's
  `instructions` and `input` are the pre-flight messages; a `function_call_output` item is
  a tool result (`tool_result` taint, checked on the tool-result surface); the `message`
  items' text is the output, and an applied redaction is written back into it; each
  `function_call` item (and a shell, computer or patch action the app executes) is a tool
  call decided before the response is handed back. Tools OpenAI hosts (web search, file
  search, code interpreter, hosted MCP) are recorded as tool spans, not authorised: they
  ran before the response arrived. A request continuing a conversation held by OpenAI
  (`previous_response_id`, `conversation`) records its provenance for earlier turns as
  unknown. The banner no longer says the Responses API is not governed.
- **CrewAI tool calls are checked.** A CrewAI agent writes its tool calls as text
  ("Action: ... / Action Input: ..."), so no model-level patch saw one, and the tool's
  result came back to the model marked `user` taint. `auto()` now patches CrewAI's tool
  entry points where they run (`CrewStructuredTool.invoke` / `ainvoke` for a text call,
  `BaseTool.run` / `arun` and `Tool.run` / `arun` for a native one), as it patches
  LangChain's: each call goes through the tool-call check, a refusal is handed to the
  agent as the tool's result (`tool_refusals="raise"` raises instead), and the result is
  checked as `tool_result` before the agent reads it. Native tool calls in a CrewAI
  agent's model replies are left to that check, so each call is decided once.
- **Hand-offs are recorded as hand-offs, not as tools without a grant.** An Agents SDK
  hand-off (`transfer_to_<agent>`) is a function call, so it was decided as a tool: on
  a first run of the customer_service example it read as "tried to
  transfer_to_seat_booking_agent without permission", and once the agent held any
  grant it was refused. Hand-offs are now known from the SDK's own `Handoff` objects
  (and its default hand-off description), LangGraph's handoff tools
  (`metadata["__handoff_destination"]`) and CrewAI's delegation tools, and are
  recorded as a `subagent` span and a `delegates_to` lineage edge with no tool
  decision, grant or containment finding.
- **An agent's own parts are no longer "tried X without permission".** Found by the
  2026-11-08 re-audit, where the first findings on three examples were false alarms:
  - Agents used as tools (the Agents SDK's `agent.as_tool(...)`, AutoGen's
    `AgentTool` / `TeamTool`) are recorded as a delegation to the sub-agent (relation
    `as_tool`), like a hand-off, instead of decided as an ungranted tool. The names are
    learned from the frameworks' own objects, including a framework imported after
    `auto()` (it is watched as it is imported, so the first request is known).
  - A structured-output tool (pydantic-ai's `final_result` for any `output_type=`, or
    a `ToolOutput(name=...)`) is not a capability: it is not decided, and what it
    carries is checked as the model's output.
  - `agentfox scan` reads the tool name each `as_tool` edge is called by (`tool_name=`,
    else the framework default; AutoGen's `x_tool = AgentTool(x)` passed by name now
    maps too), and `agentfox up` declares those tools and grants them to the agent, so
    default-deny never refuses an orchestrator its own sub-agents.
- **Ordinary delegation is no longer held for approval** (langgraph-supervisor's
  quickstart: "(3x7)+5" had `add` held). A hand-off's own message is the person's
  conversation carried to the next agent, not a tool result, so the expert's
  arguments no longer read as copied from `tool:transfer_to_math_expert`. And impact
  inference no longer reads a computation as a write: `add`, `add_numbers`,
  `merge_lists`, `replace_text` are `read`; `add_user`, `apply_discount`,
  `merge_pull_request` still `write`.
- **Tools checked where they run (LangChain, CrewAI) get argument provenance.** Their
  results are kept per conversation (bounded), so an argument copied out of an earlier
  tool's result is `tool_result` taint and the containment and composition rules apply;
  a model request that quotes a result inside another message (CrewAI's "Observation:")
  has that message marked `tool_result`.

## [0.5.0] - 2026-11-07

### Added

- **LiteLLM proxy guardrail.** One block in a LiteLLM proxy's `config.yaml`
  (`agentfox.frameworks.litellm_guardrail.AgentFoxGuardrail`) checks every agent behind
  the proxy: inputs and tool results before the model, each requested tool call (with
  the conversation, so copied-in arguments are tainted) and the reply after it,
  streamed tool calls included. Refuses when the gateway is unreachable unless
  `fail_open: true`. Guide: `/docs/guides/litellm`.
- **`agentfox.auto()` reports to your AgentFox account when a key is configured.**
  With `AGENTFOX_URL` and `AGENTFOX_API_KEY` set (or `auto(server=, key=)`, or the
  `.agentfox/agentfox.env` that `agentfox init` writes), every check goes to the
  account's gateway and the calls show up on its dashboard; without one, nothing
  changes. Same decisions as in process: the mode rules, the no-grants carve-out,
  argument taint from the conversation, approvals spent on the retry.
- `POST /v1/guard/tool_call` takes `in_process`, `waive_ungranted` and `declare`, so
  a remote caller gets the same containment record, carve-out and tool registration
  as `auto()` in process.

- **Vapi and Retell calls are recorded when they end.** Vapi's `end-of-call-report`
  (sent to the same hook URL) and Retell's `call_ended` / `call_analyzed` (a new
  signed webhook route, `/v1/hooks/retell/{id}/webhook`) become one run per call with
  its conversation turns, under the call's id, so they sit with that call's tool-call
  decisions. Personal data and secrets are masked before anything is stored, and a
  call delivered twice is recorded once. Spoken numbers are not masked yet.
- **A tool call a person approved goes through when the platform retries it.** Vapi,
  Retell, Copilot Studio and AgentCore Gateway never send an approval id back, so an
  approved call used to be held again on every retry. `POST /v1/guard/tool_call` now
  accepts `redeem_approved: true`: with no `approval_id`, it finds an approval granted
  for exactly this agent, tool and arguments, unexpired and unspent, and spends it
  once. The platform hooks and the AgentCore interceptor turn it on; any other caller
  keeps the old behaviour unless it asks.
- **Tool calls from Vapi, Retell, Copilot Studio and AgentCore Gateway are governed
  before they run.** Each platform calls a URL before a tool runs; pointed at
  AgentFox, the call gets `/v1/guard/tool_call`'s decision and an answer in the
  platform's own format.
  - **Vapi** (`/v1/hooks/vapi/{id}`): each call in a `tool-calls` message is decided.
    Refusals come back as an `error` the assistant voices. Allowed calls are forwarded
    to the customer's tool server.
  - **Retell** (`/v1/hooks/retell/{id}`): calls are decided after `X-Retell-Signature`
    verifies (HMAC with the Retell API key, 5-minute replay window). Allowed calls are
    forwarded with Retell's own body and signature.
  - **Copilot Studio**: the external threat detection endpoint
    (`/v1/hooks/copilot-studio/{id}/analyze-tool-execution` and `/validate`) answers
    `blockAction`. It first verifies the Entra app token: the RS256 signature against
    the tenant's keys, plus tenant, issuer, app id, audience and expiry.
  - **AgentCore Gateway**: a REQUEST-interceptor Lambda with a SAM template
    (`deploy/aws-agentcore-interceptor/`). Blocked calls never reach the target.
    Fail-closed by default.

  An operator registers each connection with
  `POST /api/agents/{slug}/platform-connections`; the change is audited and the
  secret is stored encrypted and included in key rotation. The server allowed calls
  are forwarded to is registered there, never taken from the request. It must be
  `https` on a public host, and its address is checked again before each forward,
  with redirects not followed.

- **Discovery finds voice agents and agents built on hosted platforms.** `agentfox scan`,
  `agentfox init` and a connected repository now report:
  - Voice agents written in code: a LiveKit `class X(Agent)` with its `@function_tool`
    methods, a Pipecat `Pipeline` with the functions its LLM service registers, and
    OpenAI's `RealtimeAgent`, each with the model it is built with.
  - Agents of Pydantic AI, Strands, Agno, smolagents, LlamaIndex, Semantic Kernel,
    Microsoft Agent Framework, Haystack, DSPy and the Claude Agent SDK. These were
    already found by shape at medium confidence; they are now high confidence under
    their own name, as are TypeScript agents of Mastra, VoltAgent, Strands and LiveKit.
  - Agents with no code, read from the files a platform exports
    (`discovery/platforms.py`): Vapi assistants and squads, Retell agents and LLMs,
    ElevenLabs agents, Bland pathways, n8n workflows with an AI Agent node, Dify apps,
    Flowise and Langflow flows, Voiceflow projects, Dialogflow CX and ES exports,
    Copilot Studio agents, Agentforce metadata and Agent Script, Bedrock Agents,
    AgentCore runtimes and Lex bots in CloudFormation or Terraform, and Genesys
    Architect bot flows. Each comes with its tools and model where the file names them.

  A platform is named in the stack when code calls its API (Synthflow, Telnyx, Smallest
  AI, Agora, Bedrock Agents and others). A file counts as a platform's agent only when
  it has several of that platform's own keys together. Files in test and fixture
  directories are not read.
- **The share of checks answered without a detector is visible.** Counted per process
  on the request path: `/metrics` has `agentfox_checks_total`,
  `agentfox_checks_degraded_total{detector,cause}`, `agentfox_checks_degraded_ratio`
  (over `degraded_window_seconds`, 60 by default),
  `agentfox_classifier_backstop_shed_total` and `agentfox_inference_abandoned_total`;
  `/api/health` reports them under `degradation.checks` and turns
  `governance_healthy` false while the share is above `degraded_warn_ratio` (5%, with at
  least `degraded_warn_min_checks` checks in the window), and the gateway logs a warning
  once per window saying what `fail_mode` did with those checks (`open` answered them on
  the other detectors' findings; `closed` blocked them).

- **`scan --json` says more about each agent**: its `model` (read from a literal, a
  module constant, an f-string of constants, an `os.getenv` default or a chat-model
  object, and `null` when only running the code would tell), a `ref` (module, name and
  whether it is the agent, a factory or a loop function) for a local runner, and
  `tool_details` (each tool's description and argument names). The report gains
  `unassigned_tools`, the tools found that no agent is handed. None of this is added to
  what `scan --submit` sends.

- **`unicode.tags`, a default detector for text hidden in Unicode tag characters**
  (U+E0000 to U+E007F, "ASCII smuggling"): invisible to a person, read by a model. It
  reports `INJECTION.HIDDEN_TAG_TEXT`, so the baseline injection rules act on it, and
  skips the England, Scotland and Wales flag emoji, the block's one legitimate use (#15).
- **A Fly.io guide for the control-plane UI**, `deploy/FLY.md` (#11).
  `fly.dashboard.toml` now sets `HOSTNAME=0.0.0.0`, as `render.yaml` does.
- **A scanned multi-agent system comes out as its agents.** The repository scan reads
  each agent the code defines, the tools it is handed and which agent hands work to
  which (OpenAI Agents SDK handoffs and `as_tool`, LangGraph supervisors, swarms and
  `StateGraph` agent nodes, CrewAI crews and delegation, AutoGen teams and group chats,
  Google ADK `sub_agents`), statically. `scan --json` gains `agents` and `agent_edges`.
  A repository with two or more agents is proposed as one draft per agent with its own
  tools, joined by declared delegation edges, so the guardrail map shows sub-agents
  ("From code, no calls yet") and the agent that calls each one, and "apply to
  sub-agents" reaches them, before any traffic. The Proposed list groups a system under
  its orchestrator with an "Add all" action. A re-scan updates the drafts in place and
  never turns an agent someone added back into a proposal.
- **`agentfox up`, the guided setup.** One command from a fresh install to a governed
  project: it scans the repository, asks where AgentFox runs (this machine; self-hosted,
  either started here with Docker Compose and a first operator, or an existing server;
  or AgentFox Cloud with an API key), what to cover and how strict to start, then sets up
  the Claude Code and Codex hooks, `agentfox.auto()` in your entry point, the gateway
  environment for any language, the tools it found (impact inferred, never overwriting
  a declaration), your MCP servers, the scan in the dashboard, Enterprise monitoring and
  compliance where available, and the dashboard. It starts in observe by default. Each
  question has a recommended answer (`--yes` takes them all); answers are saved in
  `.agentfox/up.json` and credentials in `.agentfox/agentfox.env` (0600, git-ignored).
  `up` takes `demo`'s place in the Start panel; `agentfox demo` still works.
  Its scan step also reads the AI tools set up on this machine (`agentfox scan
  machine`, skipped with `--skip-machine`) and the repository's own skills, and a
  coding agent configured only at user level is offered too. It can add the AgentFox
  GitHub Action as `.github/workflows/agentfox.yml`, never over an existing one.
- `exposure.declared_mcp_servers()`: the servers a repository's MCP configs declare,
  once each by name, shared by `agentfox scan mcp` and `agentfox up`.

- **Delivery policies for coding agents** (`capabilities/delivery`). The hook now
  also catches an agent that is about to lose work it already got right: a service
  the task needs left attached to the session (including a harness background task),
  a damaged database opened before it was copied with its sidecars, deployed state
  torn down after a successful check, a closed replacement map with no diff check
  after the last write, one answer where every answer was asked for, and a stated
  numeric bar never measured. Each policy reads the task text once and intervenes at
  most once or twice per session. On by default; `AGENTFOX_DELIVERY=off` disables
  them, and `AGENTFOX_DELIVERY=only` runs them without the daemon.
- The Claude Code adapter binds **Stop**, probed live at 2.1.292: a refusal keeps
  the agent working with the reason as its next instruction. Existing installs get
  it by rerunning `agentfox admin hooks install --write`.
- **`messages` (and `trust`) on `/v1/guard/tool_call`.** The conversation that led to the
  call; an undeclared argument's provenance is inferred from it. Without it, or a
  declared `provenance`, nothing is inferred (now documented). The TypeScript SDK's
  `guardToolCall` options take `messages` and `trust`.
- **Built-in validators.** About seventy checks ported from the Guardrails AI validators
  (Apache-2.0) as native code, so none needs a separate install: system-prompt leaks,
  forbidden SQL and unknown columns, unsafe HTML, internal domains, fuzzy word lists,
  drug names, price quotes, format checks, local-model classifiers (jailbreak,
  toxicity, NSFW, bias, gibberish) and LLM judges routed through the judgment tier.
  Pick one under Policies → Add rule → **Use a built-in check**, give it its settings,
  and try it on a sample; it is watched and enforced like any other rule. Ones that
  need no settings can also be switched on as `validator.*` checks.
- Your own validators register through the `agentfox.validators` entry point.
- Importing a Guardrails AI guard maps each validator onto its port with the same
  settings, so `ValidLength`, `RegexMatch` and the rest import instead of being skipped.

### Changed

- **Adding an agent allows the tools its own code hands it.** Every tool `agentfox
  init` or a repo scan found used to start "Not allowed", so the app's own calls were
  refused on the first run and no rule could be tested until each tool was allowed by
  hand. Now a read tool is allowed whatever its arguments came from, and a tool that
  changes something or sends data out is allowed for what the user asked: an argument
  copied out of a tool result or a page is still stopped. A tool the code doesn't hand
  the agent stays refused; a grant someone already made is left as it is.
- **`agentfox scan` names the agents it found** (one line each: framework, model,
  tools, file), single-agent repositories included, and its Next panel leads with one
  command, `agentfox up`, instead of advice to edit code by hand.
- **`agentfox up` instruments framework apps.** A LangGraph, LangChain, CrewAI or
  AutoGen app calls the model through a client `agentfox.auto()` patches, so `up` now
  offers to add it even when the scan counts no direct model call.
- **One key.** "Create a key" on the setup card makes a workspace API key: the key
  `agentfox init` connects with, and the key your app sends its calls with. Old
  `afi_` setup keys keep working at `init`.
- **`agentfox init` connects your app's traffic.** Once connected it saves the key
  in `.agentfox/agentfox.env` (owner-only, git-ignored) and, with your yes, adds
  `agentfox.auto("<agent>")` to the file that runs the agent, so its calls show up
  under Activity.
- **Basic guardrails stop what they find.** They gain a fourth rule, instructions
  hidden in what the agent reads (tool results, documents), where most of the
  onboarding attack test's injections arrive. Adding them runs a simulation against
  the agent's real traffic: with nothing they would change (a new agent), they go
  live blocking, so the test run again shows what they stop; otherwise they watch
  until promoted, as before.

- **The multi-agent scan reads more of the shapes real repositories use.** Typed
  constructors (`Agent[Context](...)`); hand-offs and tools added after an agent is
  built (`a.handoffs = [...]`, `.append`, `.extend`, `+=`, `handoff(agent=x, ...)`),
  including from a separate wiring module; tool lists built by a helper
  (`tools=build_tools()`), `tools or ALL_TOOLS`, `A if c else B`, and a list another
  module defines; tools made by a call (`function_tool(fn)`,
  `function_tool(name_override="x")(fn)`, `StructuredTool.from_function(fn)`), named as
  the code names them, here and in the repo scan's tool sites; an agent `name=` held in
  a module constant; pre-1.0 LangChain (`create_tool_calling_agent` and friends,
  `initialize_agent`, `AgentExecutor`, reported as one agent); and, only when nothing
  else is an agent, a hand-written OpenAI/Anthropic/LiteLLM function-calling loop. On
  OpenAI's customer-service agents demo the scan now finds all 8 agents, their tools and
  15 hand-offs, where it found 2 agents, no tools and no hand-offs. A list the scan
  cannot read adds nothing instead of a tool named after the helper.
- **Test, mock and fixture files are no longer read for agents or tools** (`tests/`,
  `testing/`, `mocks/`, `fixtures/`, `test_*.py`, `*_test.py`, `conftest.py`). The repo
  scan's own findings still cover them.
- **`judgment_fail_closed` defaults to off**, like `fail_mode`, and a workspace may turn
  it on or off. Before, it defaulted on and the deployment ceiling refused to let anyone
  turn it off, though nothing acted on it. Set `AGENTFOX_JUDGMENT_FAIL_CLOSED=true` to
  require it for every workspace.

- **Open core and AgentFox Enterprise.** The repository is now an Apache-2.0 open core
  plus a source-available enterprise package in `ee/` (Business Source License 1.1: free
  in production for one workspace with up to four agents; each release becomes
  Apache-2.0 three years after it ships). Enterprise holds compliance status, reviews
  and sign-off, the risk register and board view, auditor evidence packages, fleet
  monitoring with Slack alerts, and external access checks. Everything else, including
  enforcement, containment, every detector and validator, custom rules, packs, data
  retention and legal holds, stays in the open core, which runs on its own.
- The open core finds the enterprise package through the `agentfox.extensions` entry
  point and never imports it; an import contract enforces that. CI runs the open core's
  suite without `ee/` and both suites with it.
- The dashboard shows enterprise areas only where the deployment has them
  (`/api/version` now reports `edition` and `features`). Retention moved to
  Settings → Retention; the Reports summary reads the new open-core `/api/overview`.
- The `rails.hub.*` detectors, which needed a `pip install` per validator, are replaced
  by the ports. `rails.guardrails_ai` stays for running your own Guard.

### Fixed

- **`agentfox init` no longer stops right after connecting** when it offers to add
  `agentfox.auto()`: the server keeps no file paths, so `init` now finds each agent's
  file in its own map instead of the server's reply.

- **A rule you write can be switched on from the UI.** Policies → Libraries shows
  **Your rules** (the rules you wrote, and your business rules) with the same
  simulate-then-block switch as any library, and "Add a rule". A new rule's
  confirmation, and its own page, link straight there.
- Libraries applied to every agent (Baseline, Tool containment, EU AI Act, Agent
  integrity) get their watch/block switch on the Libraries page.
- One word for one thing: "Start blocking" everywhere (was also "Start enforcing"),
  "Apply a library" on New rule (was "Turn on a ready-made pack"); a watching
  library's drawer says what its rules *would* do.
- With no project chosen, pages show a project with an agent someone added, not a
  scan's proposals.
- **`agentfox test redteam` says what live traffic gets.** An attack stopped only by a
  rule that watches is shown as "would block (watching)" and counted on its own line,
  instead of as blocked; the command refuses an agent that doesn't exist (it used to
  run and file a finding for it) and lists the ones that do.
- **`agentfox doctor` no longer says no model call can leave the machine** when the
  gateway has no provider: that is true of the gateway's own proxy routes, not of the
  calls an app makes itself through `agentfox.auto()` or the SDK.
- **One agent, one name.** The scan, `agentfox init`, `agentfox up` and the
  `agentfox.auto()` line it writes now all name an agent as its code does
  (`support-triage`, not `app-support-triage` in one place and `main` in another), so
  the `permit grant` and other commands the CLI suggests name an agent that exists.
  The repository goes in front only when another repository's agent has the name; an
  existing scan's agents keep their slugs. An unnamed agent in a top-level `main.py`
  is named after the repository. A single-agent repository no longer gets a second,
  phantom agent for its top-level files.

- **`agentfox scan machine` reports what needs a look instead of every skill that ships
  a script.** A skill that bundles scripts is now `low` (an inventory of unread code), not
  `high`; most real skills ship scripts, and at `high` they buried the findings that matter.
  A tool grant is overbroad only when it is `*`, `all`, or a tool whose whole argument is a
  wildcard (`Bash(*)`): `Bash(ls *)` scopes the grant to `ls`, and a comma-joined
  `allowed-tools` string is read grant by grant. "Don't tell the user to ..." is advice on what
  to say, not a planted directive, and an injection phrase that only ever appears in quotes
  (a skill warning about "ignore previous instructions") is reported at `medium`, one step
  lower. The output now ends with what was checked, how many issues need a look, and the next
  command; skills whose only issue is bundled scripts are named on one line.

- **`agentfox up` says the hook daemon started only once it answers.** It printed "started"
  as soon as the process was spawned, so a coding-agent call in the first moment after setup
  ran unchecked. It now waits up to ten seconds and otherwise says the daemon is still
  starting and where its log is.

- **The injection classifier keeps up under concurrency instead of being skipped.**
  With the default detectors (classifier on, score cache off), 16 concurrent clients
  against one gateway process had most checks answered without the classifier: it ran
  past its 250 ms allowance, so the check was degraded, and under the default
  `fail_mode = "open"` it was allowed on the other detectors' findings. Three causes,
  each fixed without raising the allowance. The heavy detector pool (8 threads, each
  blocked while its text waited for the batcher) was the concurrency limit, so half the
  checks queued for a thread first; it is now 4x the light pool. The advisory backstop
  model, which runs after the response, ran its forward passes on the same device in
  turn with the request-path classifier's and slowed them several-fold; one in-process
  inference scheduler now runs every batched pass, request-path work first, the backstop
  only when nothing a request waits on is queued; backstop runs wait for an idle
  gateway, and when that queue is full the oldest is dropped and counted
  (`backstop_shed_total`). Texts whose check had already timed
  out were still scored, delaying the next checks; a pipeline that stops waiting now
  drops its queued texts unscored and releases the thread. A degraded check is still
  degraded: listed in the response's `degraded`, blocked under `fail_mode = "closed"`.
  Measured before/after numbers are in the pull request.

- **An MCP tool listed with `"inputSchema": null` is callable, and accepting it works.**
  github-mcp-server v0.24.0 lists `get_me` that way. The registry recorded the schema as
  `{}` while the call-time pin check digested the raw `null`, so the two never matched:
  the tool was refused with `mcp.schema_drift` from its first call, and accepting the
  listing re-recorded `{}` and left it refused for good. A `null` description had the
  same shape of bug (recorded as the text `"None"`). Registering, filing a change,
  accepting it and checking a call now all read a listing through one canonical form:
  a missing field, JSON `null` and the empty value are the same for the description,
  the input schema and the annotations (and for an impact hint set to `null`). The pin
  is no looser: any other change to the description, schema or impact hints is still
  held. A listed schema can no longer carry the registry's own `x-agentfox-*` markers
  into the record.

- **A detector that errors now follows `fail_mode`, exactly as one that times out.**
  A detector that raised, or reported `status="error"` (a custom model whose endpoint
  was down, for one), was recorded as `errored` and the call was allowed whatever
  `fail_mode` said, even with the deployment and an enforcing pack both set to
  `closed`: only timeouts counted as degraded. An error is now degraded too (and still
  listed in `errored`). Under `closed` it blocks as `pipeline.fail_closed`, whose reason
  names each degraded detector and why (`fm.boom: error: <cause>`, `fm.slow: timeout`).
  Under `open` (the default) the call is allowed and the error is surfaced where a
  timeout is: the decision's `degraded`, `detector_degraded` for rules, and a
  `budget_breach` finding. A custom model set to "Let traffic through" when down adds
  no detection, as before, but a `closed` deployment or pack now blocks its outage as
  it already blocked its timeout. LLM judges already behaved this way and are unchanged. This
  applies to every path that uses the Enforcer: the gateway, the SDK and the
  coding-agent hooks.

- **Libraries on the Policies page go live like any policy.** Applying the basic
  guardrails from the Libraries tab failed outright; it now takes the onboarding card's
  path: watching, and blocking only for a role that may change production policy once
  those exact rules were simulated. "Start blocking" on a library switched its copies to
  blocking with no simulation and for any policy author; it now needs a
  `policy_production` role (either way, as `POST /api/policies/{key}/mode` does) and a
  recorded simulation of each copy's rules, else 409 "simulate first". The new
  `POST /api/policies/libraries/{id}/simulate` replays each agent's recent traffic against
  its copies with the existing simulator, records it, and says per agent what would have
  been blocked, held or hidden; the card has a Simulate button, shows the server's refusals,
  and asks for confirmation in the page instead of a browser dialog that some browsers
  suppress. Copies record which version of the library they came from: the status reports
  `outdated`, and applying again updates them in their current mode. Disconnecting a
  project snapshots its library copies and "Restore guardrails" brings them back, under
  the same gate. Draft agents from `agentfox init --key` can take libraries and are listed
  (marked `draft`) in `GET /api/policies/applied`; library routes accept `project` and
  refuse agents outside it, other workspaces' agents, and anything but a shipped library.
- Watching rules read "Would block · watching" (and Would ask / Would hide), and rule
  titles made from ids keep acronyms (PII, API, URL, …).

- **A workspace's judgment settings now reach its checks.** Checks run on worker
  threads, and those threads did not inherit the request's context, so every check
  saw the deployment's settings instead of the workspace's. A workspace that set
  "personal data to a judge: block" had it redacted and sent anyway, and judge tiers
  switched on only for a workspace looked "not configured". Each check, and each call
  to a workspace's own models, now runs in a copy of the request's context (judgment
  posture and tenant).

- **"On a judge outage: deny the request" is now applied.** The judgment posture's
  `fail_closed` was stored and shown but nothing read it. A judge that was asked and did
  not answer (unreachable, an error, a timeout) is now a degraded detector, so
  `fail_mode` treats "unreachable" and "timed out" the same way. With the posture's
  `fail_closed` on, an enforcing decision is also blocked as `pipeline.judge_outage` when
  an enforcing pack has a rule on that surface that the judge's findings could fire. It
  adds a block and never removes one. A payload the egress gate refused to send
  (`pii_egress=block` on text with personal data) is reported as `cause="refused"` and is
  never an outage. Validator judges, standalone or in a workspace rule, report outages the
  same way, and one rule's judge being down no longer drops the other rules' findings.
- **`auto()` applies output redaction instead of only recording it.** A `redact` / `mask` /
  `tokenize` rule on the output surface was evaluated and logged under `auto()`, but the
  caller still got the original text, so a policy to hide personal data in replies hid
  nothing for apps on patched OpenAI, Anthropic, LiteLLM or LangChain calls. The redacted
  text now replaces the reply in the client's own response object (sync and async), as the
  gateway and the LangGraph guard already did. It follows the same mode rule as a block:
  the enforced verdict by default, the effective one under `mode="enforce"`, never under
  `mode="observe"`. A streamed reply, whose chunks are already with the caller, raises
  `Blocked` at the end of the stream instead; a response that cannot be rewritten is
  refused rather than returned unredacted.

- **Dashboard actions no longer land on `localhost`.** Add project, Add all and every
  other form action, and the sign-in and `/app/agents` redirects, came back on the
  server's own hostname. Opened at `127.0.0.1` or behind a proxy, that is another origin
  without the session cookie, so the action looked like a sign-out. They now return to
  the host the browser used.
- **`agentfox up`, found by running it end to end** on a sample project, locally, against
  a production-mode team server, through the Cloud path and as a Docker Compose stack:
  - A set-up agent works on its first call. The tools `up` declares are granted to the
    agent (locally and over the API), and a coding agent is offered a grant for the MCP
    servers it loads (the repository's and its user-level config's), so neither is
    refused by default-deny. Containment still applies: a refund whose recipient came
    from a tool result is still held.
  - A self-hosted stack started by `up` gets the control catalog and the shipped policy
    packs; the gateway image only serves, so before this it ran with no tool containment.
  - Before starting Docker, `up` names a port already in use and says the gateway image
    is a large download (its size read from the registry), asking first; a failed start says how to clean up.
  - `up` only reports a local API it started; another AgentFox on :8080 (a self-hosted
    stack, another project) is named, not claimed.
  - Running `up` again no longer records the same scan, and its draft agents and proposed
    policies, a second time.
  - A connected self-hosted server is asked for its dashboard address; the API URL is no
    longer shown as the dashboard.
  - "Watch first" says what still stops a call (destructive commands, protected paths,
    tampering); logs and pid files are git-ignored; plurals and long paths read properly.

- Opening Compliance on a new workspace could fail: its parallel requests each loaded the
  control catalog and collided on the same control.
- An extension's CLI commands could be dropped depending on import order.
- **The gateway proxy now governs the tool calls a model asks for.** `/v1/chat/completions`
  and `/v1/messages` authorise every tool call in the response through
  `guard_tool_call` before returning it, as `agentfox.auto()` does in-process: a
  refused call is a 403, a held one a 428, and a stream holds tool-call fragments until
  they are authorised. Before, only the reply's text was checked.
- **Anthropic `tool_result` blocks are tool output, not user input.** They arrive inside a
  `role: "user"` message, and the gateway tainted them `user`, so a payee copied out of a
  tool result passed a grant that allows user content. They are now `tool_result`, named
  after the tool that produced them (`tool:<tool>#<i>`) on both shapes, so composition
  checks and `output_trust` declarations apply on the gateway as on the SDK.
- **`/v1/messages` returns tool calls.** A non-streamed reply now carries `tool_use`
  blocks and `stop_reason: "tool_use"`; it used to drop them.
- Value checks could not be saved from the dashboard ("a condition rule needs
  `condition`"), and trying one on a tool call ignored the tool: the dashboard's proxy
  dropped both fields. Suggested argument names for a value check now load too.

## [0.4.0] - 2026-10-12

### Added

- **New tool-call paths.** Every agent's tool-call sequences in production, the ones
  never seen before, and one click to add a path to the regression tests; a daily scan
  raises a `new_tool_path` issue whose fix adds the path (Test → Tool paths).
- **Agent circuit breaker.** An agent whose calls start getting blocked in a burst is
  flagged (default) or paused for a cool-down, then probed and closed after clean
  calls; Resume now from the agent's settings or the issue.
- **Your own access control.** A workspace registers its RBAC service (or an OPA or
  Cedar server); matching tool calls are posted to it with the end user before they
  run (`principal` on `/v1/guard/tool_call`, `fox.session(principal=...)`).
- **`govern(fox, *agents)`** for the OpenAI Agents SDK: one call guards every agent,
  hand-off and tool.
- Playground sandboxes come from a spare pool (about 2.5 s to start), and due jobs run
  off ordinary traffic as well as the daily cron.
- Policy import from agent-governance YAML, Codex CLI hooks, industry and regional
  packs, Rego and Cedar libraries, a coding-agent blocklist.

- **Key rotation** for the two keys that protect stored data.
  `AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS` and `AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS`
  (comma-separated) hold retired keys: secrets still decrypt and checkpoints still
  verify under them, while everything new uses the current key. `agentfox admin keys
  rotate` re-encrypts every encrypted column (atomic per column; a value no key
  decrypts is reported and left alone), verifies each tenant's audit chain, re-signs
  its previous-key checkpoints, records an `audit.key_rotated` entry with the key
  fingerprints (first 8 hex of SHA-256, never the key) and checkpoints the new head.
  `agentfox admin keys status` shows the fingerprints and what still needs a previous
  key. The job runner (`/api/internal/jobs/run`, `agentfox admin jobs run-due`) enqueues
  a `keys.rotate` job by itself while a previous key still protects something;
  `/api/version` reports `key_rotation` states and `agentfox doctor` has a `key
  rotation` line. See docs/deployment/key-rotation.md.
- Checkpoints record the signing key's fingerprint in `key_id` (was the constant
  `local`), and are written into the chain of the entry they anchor even inside
  `system_scope`. `chain.verify` accepts one key or several.
- The `verify_chain.py` in evidence packages accepts several comma-separated keys in
  `AGENTFOX_AUDIT_KEY`, for a chain that spans a rotation.
- One-time migration bridge: when both `AGENTFOX_<KEY>` and `NOMETRIA_<KEY>` were set
  and differed for `TOKEN_ENCRYPTION_KEY` or `AUDIT_SIGNING_KEY`, the `NOMETRIA_` value
  was used as the previous key. Removed again by rename stage B (below).

- **Capability packs.** A business use case or framework is one directory with a
  `pack.yaml` (id, version, maturity, owners, compliance mappings, vocabulary) and its
  policies, controls, ladder templates, red-team probes, optional checks, golden cases
  and fixtures. Built in: `baseline`, `tool-containment`, `coding-agent`, `eu-ai-act`,
  `compliance/catalog`, `payments/refunds`, `customer-support`. Your own load from
  `.agentfox/packs/` or an `agentfox.packs` entry point; only `stable` packs load unless
  `pack_maturity` (`AGENTFOX_PACK_MATURITY`) says otherwise.
- `agentfox policy packs list|show|test|validate|new`. Bare `agentfox policy packs` still
  prints the policy files on disk (now also `policy packs files`).
- A finding-type registry: `GET /api/findings/types` and `agentfox findings --types` list
  every type with its title, usual severity, meaning and owner; packs declare their own.
- A check registry: request-path checks register with `@check` from the capability
  that owns them, an `agentfox.checks` entry point or a pack.
- `mcp_tool_added_under_wildcard` finding (high): a registered MCP server added a tool
  that an existing wildcard grant already allows.
- `agentfox doctor` has a `legacy names` line listing every pre-rename `NOMETRIA_*`
  variable still set (in use, or set but not read) and any `nometria.toml` / `[nometria]`
  config in use.

### Changed

- **Get started's last step enforces everything that protects the agent** (baseline,
  its own protections, blocked words and topics), with a preview of what it would have
  stopped. Previews now count calls that went through and would be stopped.
- **Fewer, plainer issues.** One medium issue per tool an agent has not been given
  (granting it closes the issue); calls held for the approval their grant asks for
  are not issues; titles and refusal reasons are plain words.
- Loop detection counts within a turn, so a conversation that repeats itself across
  turns is not refused; a stopped loop is a recorded, blocked run.
- Runs are grouped by conversation; the SDK reads `AGENTFOX_API_TOKEN`.
- Reports show controls working out of every control that applies, not out of those
  measured; rates over nothing show a dash.

- **A cascade that only sends a message escalates instead of blocking.** A tool can be
  declared `effect: communication` (`agentfox declare tool --effect communication`, or
  `effect:` in a pack's `world.yaml`): its irreversible effect is a message leaving, not
  data destroyed, money moved or state changed. When every destructive tool a call's
  declared triggers reach is such a tool, `cascade_risk` reports
  `cascade-reaches-notification` (high) and the new `cascade.reaches_notification` rule
  in `tool-containment` holds the call for approval; one reached tool outside that class
  and it is `cascade.reaches_destructive` (block), as before. Never guessed from a tool's
  name: an undeclared tool counts as destructive. The demo world declares `email.send`
  this way, so an ordinary `tickets.update` is held for approval rather than refused.

- **Nometria to AgentFox, environment and headers (stage A).** Everything the product
  writes and documents is now `AGENTFOX_*`, `agentfox.toml` / `[agentfox]` and
  `X-AgentFox-*`: the gateway's response headers (`X-AgentFox-Trace`, `-Verdict`,
  `-Effective-Verdict`, `-Applied-Verdict`, `-Would-Be-Verdict`, `-Decision`, `-Mode`,
  `-Latency-Ms`, `-Explain`, `-Streaming`, `-Degraded`), the finding webhook's
  (`X-AgentFox-Event`, `-Delivery`, `-Timestamp`, `-Signature`: **update a webhook
  receiver that verifies `X-Nometria-Signature`**), the FastAPI middleware's, and what the
  SDK, the CLI and the dashboard send. The pre-rename names still work as input:
  `NOMETRIA_*` variables, `NOMETRIA_CONFIG`, `nometria.toml` and a `[nometria]` table are
  read below the new names, and `x-nometria-*` request headers are accepted, with
  `x-agentfox-*` winning when a request carries both. The process logs one startup
  warning naming each legacy setting in use; the dashboard warns once per legacy
  variable. `render.yaml`, `deploy/`, the docs and the plugins use only the new names.
  The self-host blueprint now prompts for `AGENTFOX_AUDIT_SIGNING_KEY` instead of
  generating it, so a blueprint sync can never rotate an existing deployment's key.
  Renaming the hosted deployment: `docs/deployment/vercel-env-rename.md` (since removed).
- The shipped policies and the control catalog moved from `policies_data/` and
  `compliance_data/` into the capability packs (`packs/<id>/policies/`,
  `packs/compliance/catalog/controls/`). `compliance_dir` and `policies_dir` still
  override them, and are now unset by default. `agentfox policy packs` and
  `agentfox admin catalog validate` print the new paths.
- The dashboard's finding labels come from the registry. `budget_breach` now reads
  "Detector over budget" (it is a detector's latency budget); it read "Budget
  exceeded", which describes `budget_exhausted`.

- The Claude Code operator plugin moved from `harness/` to `plugins/claude-code/`, and its
  runtime-neutral parts (`AGENTS.md`, `skills/`, `reference/`) to `plugins/shared/`. The
  marketplace entry now points at `./plugins/claude-code`; the install command
  (`claude plugin install agentfox@agentfox`) is unchanged. A local clone uses
  `claude --plugin-dir ./plugins/claude-code`. The maintainer command
  `/agentfox:harness-check` is now `/agentfox:plugin-check`, the drift checker is
  `scripts/check_plugins.py`, and the docs page is `/docs/plugin` (`/docs/harness`
  redirects).
- Coding-agent harnesses are adapters behind one interface, `agentfox.harnesses`
  (registered through the `agentfox.harnesses` entry-point group). Claude Code is the only
  one; installed hooks (`agentfox hooks run --harness claude`) behave exactly as before.
- Accepting a changed MCP tool listing is now a two-person change. A changed definition is
  held and filed as an `mcp.tool.accept` change proposal; `McpGovernor.register_tools(...,
  accept_changes=True)` now requires `actor=` (the reviewer) and raises `ValueError`
  without one, and the change applies only when a second, different person approves.
  `POST /api/mcp-servers/{name}/tools` with `accept_changes` counts as the signed-in
  person's approval and needs the role that approves policy proposals. The result carries
  `held`, `accepted`, `awaiting_second_approver` and `proposals`.
- `McpCallBlocked`, raised by the MCP governor, is now an `agentfox.AgentFoxError` like
  every other refusal. It is still a `RuntimeError`.

### Removed

- The `nometria` Python package shim and the `nometria` console script. Import from `agentfox` (e.g. `agentfox.frameworks.langgraph`) and run `agentfox`.
- **The last of the Nometria names (rename stage B). Breaking.** The `NOMETRIA_*`
  environment fallback (settings, `NOMETRIA_CONFIG`, the CLI's `NOMETRIA_API_URL` /
  `NOMETRIA_API_TOKEN` / `NOMETRIA_USER`, `NOMETRIA_AGENT`, `NOMETRIA_MCP_LOG_LEVEL`, the
  evidence package's `NOMETRIA_AUDIT_KEY`, the dashboard's `NOMETRIA_*`, the demos'
  `NOMETRIA_DEMO_MODEL` and `NOMETRIA_DATABASE_*`), the `nometria.toml` / `[nometria]`
  config file, acceptance of `x-nometria-*` request headers, the `legacy names` doctor
  line and the one-time `NOMETRIA_` key bridge are gone. Only `AGENTFOX_*`,
  `agentfox.toml` / `[agentfox]` and `X-AgentFox-*` are read; an old name is ignored
  without a warning. Key rotation (`*_PREVIOUS`) stays.
- **Breaking:** the dashboard session cookie is `agentfox_session` (was
  `nometria_session`). Everyone is signed out once and signs in again.
- **Breaking:** the LangGraph governance state key is `__agentfox__` (was
  `__nometria__`). Declare `__agentfox__` in your state schema. Graph state checkpointed
  before the upgrade keeps its governance state under the old key, where it is no
  longer read: an in-flight thread resumed across the upgrade starts a new trace.
- **Breaking:** OPA policy documents are pushed as `agentfox_<policy>` (were
  `nometria_<policy>`). An OPA sidecar that kept documents pushed by an older version
  holds both under the same package; restart it (pushed policies are in memory) or
  `DELETE /v1/policies/nometria_<policy>` for each.
- The secrets detector's entity for AgentFox API and agent keys (`nom_api_…`,
  `nom_agt_…`) is `SECRET.AGENTFOX_KEY` (was `SECRET.NOMETRIA_KEY`). The `SECRET.*`
  policy rules match it unchanged; a rule naming the old entity must be updated. The
  key prefixes themselves are unchanged, so issued keys keep working and keep being
  detected.

- The hidden pre-consolidation CLI names. `agentfox --help` shows thirteen verbs, and
  the old top-level names had kept running, hidden, with a "now called" hint. They no
  longer resolve. `agentfox hooks run` and `agentfox mcp serve` stay,
  because installed hook configs and MCP client configs call them. Where each old name
  lives now:

  | Old | New |
  |---|---|
  | `check` · `quickscan` | `scan` · `scan --sessions` |
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
  | `guardrails …` · `guardrails test` | `policy rules …` · `test rule` |
  | `proposals …` · `approvals …` | `policy proposals …` · `permit approvals …` |
  | `auth …` · `db …` · `users …` · `hooks …` | `admin auth …` · `admin db …` · `admin users …` · `admin hooks …` |
  | `mcp tools` | `admin mcp tools` |

### Fixed

- **Benchmark honesty.** Detector patterns and similarity-corpus entries that had been
  written from the misses of the datasets they are scored on, and the AgentDojo
  grader's tool list in the repository scanner, are removed; every published number
  was re-measured. Default held-out injection recall is 16.7% (had been reported as
  26.7%). The adaptive benchmark's "unmapped" operators now test characters the
  product does not map, and show the open gap that had been hidden.
- A due-jobs pass now runs on a freshly booted instance.

## [0.3.1] - 2026-09-26

The first release published to PyPI, which is the whole point of it: 0.3.0 was
tagged before `release.yml` had a `pypi` job, so `pip install agentfox` has never
worked and the README's first command has been a `git+https` URL. From this tag
the package is on PyPI and the name is held.

Published through Trusted Publishing — PyPI mints a short-lived token from the
release workflow's OIDC identity, so there is no API token in the repository's
secrets, nothing to rotate, and nothing that keeps working if it leaks.

Also in this release, all of it since 0.3.0:

- A blocked tool call no longer leaves its trace reading `allow`. `Trace.verdict`
  was only ever written by the completion path, so every trace the tool-call path
  refused reported that nothing had happened.
- Twenty Guardrails AI Hub validators wrapped one-per-detector, each with its own
  key, telemetry and suppressions, reporting into this project's entity taxonomy —
  and with that project's own telemetry switched off, because enabling a check
  must not start exporting spans to a third party.
- The vendored gateway wheel carries two fixes it had been missing since 0.3.0.
- The latency probe measures the mechanism rather than the CI runner.

## [0.3.0] - 2026-09-25

The MVP described in the README. The package was declared `0.1.0` while every document
said `MVP v0.3`; they now agree on `0.3.0`, which is what `pyproject.toml`,
`src/agentfox/__init__.py`, `agentfox version` and the API's `/health` all report.

> Note for the maintainer: replace this heading with a release date when you tag
> `v0.3.0`. `.github/workflows/release.yml` refuses to publish unless the tag, the
> `pyproject.toml` version and `__version__` all match.

### Added

- **Containment that does not depend on detection.** Tools are declared with an impact
  tier (`read`, `write`, `high_impact`, `irreversible`), agents hold explicit capability
  grants with argument constraints, and every argument carries the provenance of where it
  came from. An irreversible tool called with an argument that originated in untrusted
  content is refused because of where the value came from, not because anything
  recognised the payload. Measured with every detector switched off; the result is in the
  README.
- **Policy engine** with three shipped packs, `baseline`, `tool-containment` and
  `eu-ai-act-high-risk`, each bindable in `observe` (records what it would have done) or
  `enforce`. `agentfox policy simulate` replays recorded traffic against a candidate
  policy and exits non-zero when the change would newly block production traffic.
- **Detector and scorer pipeline** across six surfaces (`input`, `output`, `tool_args`,
  `tool_result`, `memory_write`, `agent_message`), wrapping permissive OSS primitives as
  optional extras: Presidio for PII, NeMo Guardrails, Guardrails AI, Granite Guardian,
  garak and PyRIT for red-team probes, sqlglot for SQL action assurance. Every verdict
  carries the rule that produced it.
- **Tamper-evident audit chain** with a verifier (`agentfox audit verify`, exits 1 when
  broken) and signed checkpoints (`agentfox audit checkpoint`).
- **Compliance layer**: a control catalog, framework mappings, and evidence packages.
  Mappings ship labelled `DRAFT, UNVERIFIED, NOT LEGAL ADVICE`, because they were
  produced by engineers rather than reviewed by compliance counsel.
- **Ways to run it**: the `auto()` library patch, `agentfox serve` for the gateway and
  control-plane API, an MCP server, a LangGraph integration, and Docker Compose,
  Render and Fly deployment configs under `deploy/`.
- **CLI** covering setup and operation: `init`, `demo`, `serve`, `version`, `doctor`,
  `check`, `scan`, `tools`, `policy`, `agents`, `audit`, `evidence`, `compliance`,
  `eval`, `redteam`, `access`, `proposals`, `db`.
- **Dashboard** (Next.js, `dashboard/`) and a hosted playground that hands every visitor a
  throwaway sandbox running the same enforcement code.
- **Benchmarks** with committed result files: containment under total detector bypass,
  AgentDojo end to end, Crescendo trajectory, and PII. A nightly workflow re-measures the
  offline deterministic ones and fails when a published claim no longer matches.
- **Drift checks that fail CI rather than rot**: `scripts/api_routes.py --check` holds the
  API reference to the running app, `scripts/claims.py --check` holds every published
  number to its result file, and `harness/scripts/check_harness.py` holds the agent
  harness to the live command line.
- **Agent harness** (`harness/`) packaged as a Claude Code plugin.
- **Phase 0 improvement loop**: proposals, findings hygiene, label integrity and a
  scheduler, with scheduled red-teaming shipped disabled so a deployment opts in.
- **Deferred job queue** behind evidence export and red-team campaigns, and Alembic
  migrations, because a deployment that cannot be upgraded is not a deployment.

### Known limits

The README lists these in full and the product measures them rather than hiding them:
detection is a speed bump and not a defence, compliance mappings are draft, containment is
exactly as good as the tool declarations behind it, multi-tenancy is single-org and
enforced at the session, there is no live IdP or SSO, and text is the only modality.
`docs/status.md` reports live coverage computed by probe rather than asserted.
