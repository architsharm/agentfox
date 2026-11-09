# Getting started

The short path first: your repository connected and its agents tested in a few minutes. The
same steps, with screenshots, are at <https://useagentfox.com/docs/quickstart>. After it comes a
longer first hour, offline, that shows what each piece does and how to check it. This page teaches;
the [product tour](product-tour.md) is the reference for every integration surface and command.

You need Python 3.11 or newer.

## The short path: with the dashboard

1. Sign up at <https://useagentfox.com/login>. The Agents page opens on **Connect your first
   agent**. Press **Create a key**: a workspace API key (`nom_api_…`), shown once.
2. In your repository, run the command the card shows, with your key and server filled in:

   ```bash
   pip install -U agentfox
   agentfox init --key nom_api_… --server https://…
   ```

   `init` reads your code without running it and reports the agents and tools it found. It
   asks *Add one line to main.py so your app's calls show up in AgentFox? [Y/n]*. Yes adds
   `agentfox.auto("<agent>")` to the file that runs the agent and saves the key in
   `.agentfox/agentfox.env` (owner-only, git-ignored). Leave `init` running: it runs the attack
   tests on your machine.
3. Press **Add N agents to AgentFox**. Each agent is allowed the tools its own code hands it:
   a read tool whatever its arguments came from, a tool that changes something or sends data
   out only with values from what the user asked.
4. The first attack test runs by itself, with no guardrails. **Add and test again** adds the
   basic guardrails (four rules: prompt attacks in what users send, instructions hidden in tool
   results and documents, personal data in replies, secrets in replies) and shows what got
   through before and after. For a new agent with no real traffic they go live blocking;
   otherwise they watch until you switch them on under Policies → Libraries.
5. Run your app. Its calls show up on the agent's **Activity** tab.

## The short path: command line only

```bash
pip install agentfox
agentfox scan        # names every agent it found, and ends with: agentfox up
agentfox up          # registers them, declares their tools, adds agentfox.auto()
python main.py       # run your app as usual
agentfox findings    # what it saw, and what it would have stopped
```

`up` registers your agents under the names the code gives them (the names `scan` printed),
declares the tools it found, and adds `agentfox.auto("<agent>")` to the file that starts one, for
Python apps on LangGraph, LangChain, CrewAI, AutoGen and the OpenAI Agents SDK included: a script
in `pyproject.toml`, the graph `langgraph.json` loads, or the file that runs the agent, under
`src/` too. Every question has a recommended answer: `agentfox up --yes` takes them all,
`agentfox up --dry-run` changes nothing. It starts in watch mode, and ends with what to run next:
your app, `agentfox findings`, then `agentfox test redteam <agent>` to attack-test it.

In a Python agent's repository `up` changes nothing else by default. Coding-agent hooks (with the
MCP grants and the background hook daemon they need), the GitHub workflow and the local API are
each one flag away: `--with coding-agents`, `--with ci`, `--with view`. In a repository set up for
a coding agent with no agent of its own, the hooks are the default. The workflow is only ever
written at the repository root, where GitHub reads it.

## One key everywhere

With an account key, `agentfox.auto()` sends every check to that account's gateway and the calls
appear on its dashboard; without one, checks run in your process against a local database. Set
`AGENTFOX_URL` and `AGENTFOX_API_KEY` wherever your app is deployed and its calls show up the same
way. The lookup order is in the
[product tour](product-tour.md#python--one-line).

---

# The long way: a first hour, offline

Every command here was run before it was written down, and each step says what it proves. No
API key, no model weights, no network egress: the built-in `echo` model provider makes the
whole enforcement path work with nothing else installed. To see the product before installing
anything, the hosted playground needs no account: <https://useagentfox.com/playground>.

**Vocabulary used throughout:**

- **Agent**: a program that calls a model and can take actions. AgentFox identifies each one by a
  slug such as `support-triage`.
- **Tool**: something an agent can call that is not the model: a function, an API, an MCP server
  method. Each tool is declared with an **impact** of `read`, `write`, `high_impact` or `irreversible`.
- **Capability grant**: permission for one agent to call one tool, with argument limits. Default
  is deny: an agent with no grant cannot call the tool at all.
- **Provenance** (also called taint): where an argument's value came from. `user` means a person
  typed it. `retrieved` means it came out of a document. `tool_result` means it came out of another
  tool. Untrusted provenance on an irreversible tool is the case containment exists for.
- **Policy**: a named pack of rules. A policy is in **observe** mode (record what it would have
  done) or **enforce** mode (actually do it).
- **Finding**: something the platform noticed that a person should look at.

---

## Step 1. Install (2 minutes)

```bash
uv tool install agentfox      # or: pipx install agentfox
agentfox --help
```

A tool install puts `agentfox` on your PATH in every directory, which the Claude Code and Codex
hooks need: they run `agentfox` from wherever your coding agent starts. A virtualenv works too
(`python3 -m venv .venv && source .venv/bin/activate && pip install agentfox`) as long as that
`agentfox` is on the PATH your coding agent starts with.

To see what it finds before setting anything up, `agentfox scan machine` checks the MCP servers
and skills your AI tools load, in about two seconds, and ends with the command to run next.

AgentFox is on PyPI. The core install is deliberately light: it pulls
no model weights and no detector frameworks. Optional extras (`[pii]`, `[classifiers]`, `[redteam]`,
`[langgraph]`, `[sql]`, `[otel]`, `[postgres]`, or `[all]` for everything permissive) add wrapped
third-party engines later, as configuration rather than as a prerequisite.

**What this proves:** nothing yet. It is the only step that touches the network.

---

## Step 2. Initialise (1 minute)

```bash
agentfox init
```

```
Setting up AgentFox
  ✓ database ready  sqlite:///…/agentfox.db
  ✓ 44 controls across 7 frameworks  v0.1.0-draft (draft)
  ✓ 4 policy packs loaded
      agent-integrity          observe  recorded, nothing blocked
      baseline                 observe  recorded, nothing blocked
      eu-ai-act-high-risk      observe  recorded, nothing blocked
      tool-containment         observe  recorded, nothing blocked
      coding-agent not enabled — no coding-agent hooks in this repo. `agentfox admin hooks install --agent <slug> --write` turns it on for that agent.
      Missing grants, destructive commands and tampering are still refused. When the would-block decisions look right: `agentfox policy enforce tool-containment`.
  ✓ wrote agentfox.toml
```

This creates a SQLite database, loads the control catalogue and the policy packs, and writes an
`agentfox.toml` in the current directory if there isn't one. The database lives in
`~/.agentfox/` (or `$XDG_DATA_HOME/agentfox/`), not in your project, so `agentfox findings` shows the
same thing from whichever directory you type it in; set `AGENTFOX_STATE_DIR` to put it somewhere
else. The coding-agent pack is bound only to agents whose Claude Code or Codex hooks are installed, so a plain
repository gets four. It is idempotent and offline, so it is safe to run again.

If the agent you want to govern is Claude Code or Codex itself, `agentfox admin hooks install --agent
<slug> --write` (add `--harness codex` for Codex) is the shortcut: besides writing the hooks, it
registers the agent, declares the harness's built-in tools with their real impact and grants them to it, and binds the coding-agent pack in
observe, so ordinary work is not refused by default deny. Destructive commands are still refused.

Read the mode column carefully, because it is the whole shape of the product. Every pack
starts in **observe**: it records what it would have done and blocks nothing your users do.
A few things are refused from the first call whatever the packs' modes, because they are
structural facts rather than classifier scores: a tool the agent was not granted (once it
holds any grant), a destructive statement such as `rm -rf ~/` or `DROP TABLE`, and an agent
switching AgentFox off. `tool-containment` is the pack built to block: it holds an
irreversible call with no stated task, or with arguments copied from untrusted content, for a
person. Switch it on with `agentfox policy enforce tool-containment` (or Start blocking in the
dashboard, after its simulation) once its would-block decisions look right. A second
`agentfox init` keeps whatever mode each pack is in.

**What this proves:** the control plane exists locally, with no service to sign up for, and
nothing your users do is blocked until you say so.

---

## Step 3. Scan a repository (5 minutes)

Point it at a codebase you actually work on.

```bash
cd /path/to/your/project
agentfox scan
```

```
╭─ CRITICAL · lethal trifecta ─────────────────────────────────────────────────╮
│ bot.py: can read customer records (read_customer_record), reads untrusted    │
│ web pages (fetch_url), and can send email (send_email). An instruction       │
│ hidden in a web page could send customer data out.                           │
│                                                                              │
│ Contain it: `agentfox permit grant <agent> send_email --max-taint user`      │
│ (...), or run with `agentfox.auto(mode="observe")` to watch it happen        │
│ without blocking anything.                                                   │
╰─ private data + untrusted content + a way out ───────────────────────────────╯
Scanned 2 files in /path/to/your/project
  built on: OpenAI SDK

  Found 1 agent
    project  OpenAI SDK · gpt-4o · 3 tools  bot.py:22

  1 of 1 model call sites are ungoverned  (0% covered)
  can reach: 3 tools · 0 MCP servers
     read_customer_record  bot.py  private data
     fetch_url             bot.py  untrusted input
     send_email            bot.py  sends out / irreversible
     ...
```

It is a static read of the source. It names each agent the code defines (its framework, model,
tools and file; one per agent in a multi-agent system), every place the code calls a model, every tool
(decorated functions, OpenAI function schemas (`tools=[{"type": "function", ...}]`, inline or in a
list passed later) and Anthropic tool dicts (`name` + `input_schema`)), every MCP server your client
configs declare, hard-coded credentials, and shell and SQL construction near model output. It writes
nothing to your project and sends nothing anywhere.

Each tool and MCP server is classified by what it can do: read private data, read content someone
outside can write, or send data out / act irreversibly. Where one agent has all three (tools grouped
by directory, MCP servers by the config file that loads them together), that is the **lethal
trifecta** (Simon Willison's term), and it is printed first, as a sentence you can forward, with the
command that contains it. The classification comes from names and descriptions, so a tool named
`do_thing` is left unflagged rather than guessed at, and an MCP server AgentFox does not recognise is
reported as unknown, never as safe. `--json` carries the same data as flags (`private_data`,
`untrusted_input`, `exfiltration`).

To look closer at the MCP servers, `agentfox scan mcp` reads the same configs, registers every
server, and reports reach, version pinning and remote auth for each without starting any of them.
It exits 1 on a critical finding (a poisoned tool description, a critical config issue, or a lethal
trifecta across the servers), so it can fail a CI step.

For a first look at a machine you have not installed anything on, `agentfox scan --sessions` does the
same thing plus a scan of local AI-tool session transcripts, and runs a handful of known-adversarial
prompts through the real detector pipeline in your terminal, so "we catch prompt injection" is
something you watch happen rather than something we said.

**What this proves:** you get an inventory before you get an opinion. Most teams do not have a list
of where their code talks to a model.

---

## Step 4. Watch the whole thing work (5 minutes)

```bash
agentfox demo --in-workspace
```

Thirteen steps in about five seconds, against a seeded environment of three agents. The step to
read closely is step 3, where the injection has already succeeded and the transfer is refused
anyway. The product tour walks through the output:
[what the demo prints](product-tour.md#what-the-demo-prints).

Bare `agentfox demo` writes to a database of its own (`demo.db`, beside your workspace's
`agentfox.db`), so a real project's `agentfox findings` never opens with the demo's made-up agents;
its last lines say how to look around that database. This guide keeps using the demo's agents in
the steps below, so it asks for `--in-workspace`, which writes them into your workspace database
instead. Do that in a workspace you are only trying things in.

The demo promotes the baseline policy to enforce at step 8 and restores it to observe when it
finishes, so it leaves the database in the state it found it.

**What this proves:** every claim later in this guide, end to end, on your machine, in one command.

---

## Step 5. Put your own agent behind it, over HTTP (15 minutes)

This path needs no Python in your application. It works from curl, Go, TypeScript, Java or anything
else that can make an HTTP request.

Start the control plane:

```bash
agentfox serve      # gateway + control-plane API on http://127.0.0.1:8080
```

### 5a. Ask about a tool call

Before the agent runs a tool, ask whether it is allowed to:

```bash
curl -s -X POST http://localhost:8080/v1/guard/tool_call \
  -H "Content-Type: application/json" \
  -d '{"agent":"my-agent",
       "tool":"payments.transfer",
       "arguments":{"amount":250},
       "provenance":{"amount":"user"},
       "intent":"refund a duplicate charge"}'
```

```json
{ "verdict": "block",
  "rules_fired": [ …,
    { "rule_id": "capability.denied", "effect": "block",
      "reason": "'payments.transfer' has not been granted to this agent yet (default deny). Allow it in the dashboard (the agent's Access tab), or run `agentfox permit grant <agent> payments.transfer`." }] }
```

Blocked, on a database you have never configured, for an agent that does not exist yet. That is
default deny doing its job, and it is enforced from the first call: there is no grace period in
which an agent nobody has configured may call anything. The refusal says what to do about it. The endpoint returns HTTP 200 with a verdict rather than an error
status, so your code branches on `verdict` (`allow`, `redact`, `escalate` or `block`) rather than on
exceptions. The sibling endpoints are `/v1/guard/input`, `/v1/guard/output`,
`/v1/guard/memory_write`, `/v1/guard/agent_message` and `/v1/mcp/call`.

Now look at what the call did to the registry:

```bash
agentfox agents list
```

```
agent               env         risk     registered  owner               framework
hr-screening        production  limited  yes         unowned             crewai
marketing-copy-bot  production  limited  SHADOW      unowned             —
my-agent            production  limited  SHADOW      unowned             —
payments-ops        production  high     yes         marcus@example.com  claude-agent-sdk
support-triage      production  limited  yes         priya@example.com   langgraph
  5 agents · 2 shadow · 3 unowned · 4 lineage edges
```

The other four are the demo's seeded agents. `my-agent` registered itself as **shadow** traffic,
from the call, without anyone filling in a form. `agentfox findings` shows the matching
`shadow_agent` finding; `agentfox agents register my-agent --owner you@example.com` makes it a
registered agent with an owner.

### 5b. Let it propose the grants (learned permissions)

You can write every declaration and grant by hand (5c). You do not have to. Let the agent run for
a while as it is: every refused call is recorded with its tool, its arguments and where each
argument came from. Then:

```bash
agentfox policy proposals from-traffic --agent support-triage  # --since 7d to narrow the window
```

```
read 21 tool call(s): 10 benign, 11 held for provenance, 0 flagged
filed 8, refreshed 0, superseded 0, verified 0
  chp_…  tool.declare · proven
      Declare send_email as irreversible (called 6 times by support-triage, never declared; impact guessed from its name)
  chp_…  capability.grant · proven
      Let support-triage call tickets.close with priority one of low, normal (seen 14 times)
  chp_…  capability.grant · proven
      Let support-triage call send_email with to at example.com or example.org (seen 6 times)
  …
```

Read one with `agentfox policy proposals show <id>`, then approve and apply it:

```bash
agentfox policy proposals approve <id> --actor you@example.com --note "matches its job"
agentfox policy proposals apply <id> --actor you@example.com
```

What it will and will not learn from is the part to understand:

- **Learned from:** calls refused only because no grant existed, the tool was undeclared, or no
  intent was declared. Those say nothing about the call, only about your configuration.
- **Held:** calls stopped for where their arguments came from (`taint.*`, `composition.escalation`),
  or carrying untrusted content into a tool whose impact nobody had declared yet. An injected call
  looks exactly like this, so held calls shape neither the argument limits nor the provenance
  ceiling; both are read off benign calls only. Once the grant exists, calls like them are escalated to the approval queue. Approve the
  ones that are fine there, and the next `from-traffic` proposes raising that grant's ceiling.
- **Never learned from:** a call a detector matched (an injection, a credential; personal data in
  an email address is not an attack), a call over an existing grant's limit, or one a person denied.

Every proposal widens what an agent may do, so none is ever applied by automation. Grants are
scoped to one agent and need one approver. Tool declarations apply to the whole organisation, so
they need two different people. `agentfox policy proposals rollback <id>` undoes either. The scheduler
runs the same loop daily (`grants.propose`); it files, a person decides.

**When the report says composition.** A value an agent copies out of one tool's output into a
higher-impact tool is blocked as `composition.escalation`: a CRM lookup's email address passed to
`send_email` looks exactly like an attacker's address scraped from a web page. If the producing
tool is a system of record you control, say so, and values copied out of it stop counting as
untrusted input:

```bash
agentfox declare tool read_customer_record --impact read --output-trust trusted
```

Output is untrusted unless you declare otherwise.

**Session or argument provenance.** One setting decides what a tool call's provenance is:
`taint_scope` in `agentfox.toml` (or `AGENTFOX_TAINT_SCOPE`). `session`, the default, is the worst
untrusted content anywhere in the run so far: once the agent has read a web page, every later
irreversible call carries it, including one with no arguments at all. `argument` is only what
the call's own arguments were copied from. Session contains more attacks and escalates more
legitimate calls; argument lets more legitimate work through and misses an attack whose payload
never lands in an argument. Every published number was measured under `session`.

### 5c. Declare the tool and grant the capability by hand

```bash
agentfox declare tool payments.transfer --impact irreversible
agentfox permit grant my-agent payments.transfer --yes \
    --limit amount:lt=1000 --max-taint user
```

`permit grant` is the only command that widens least privilege, so it prints exactly what it is
about to allow and, without `--yes`, asks before it writes; then it records the grant in the audit
chain. Leave `--yes` off to be asked; with no terminal to answer at, it grants nothing and says to
pass `--yes`. `--max-taint user` means: arguments a person typed are fine, anything that came out of
a document or another tool needs a human. A higher ceiling is respected: within it, the taint rules
do not overrule the grant. `composition.escalation` still applies, and the command says so.

Run the same three calls again and you get three different answers:

| Call | Verdict | Why |
|---|---|---|
| `amount: 250`, provenance `user` | `allow` | inside the grant |
| `amount: 250`, provenance `tool_result` | `escalate` | `taint.irreversible_tool`, `capability.approval_required` |
| `amount: 5000`, provenance `user` | `block` | `capability.constraint_violated`, over the argument limit |

The middle row is the point of the product. Same tool, same amount, same agent. The only difference
is that the value came out of something untrusted, and no detector was involved in noticing.

An `escalate` verdict returns an `approval_id`. Decide it from the dashboard or the CLI
(`agentfox permit approvals list`, then `approve ID` or `deny ID`). The agent can poll
`GET /api/approvals/{id}` with its own key (or `fox.wait_for_approval(id)` in Python); once it
reads `approved`, send the same call again with `"approval_id": "<id>"` and it runs, once.

### 5d. Proxy the model call too (optional)

If you want the model traffic traced and evaluated as well, point your existing OpenAI or Anthropic
client's `base_url` at `http://localhost:8080/v1` and change nothing else. The response carries the
decision in headers:

```
x-agentfox-trace: trc_01m48c2p7k1fan1r6r
x-agentfox-verdict: allow
x-agentfox-effective-verdict: allow
x-agentfox-applied-verdict: allow
x-agentfox-would-be-verdict: allow
x-agentfox-decision: dec_01m48c2p81b1tgqnvx
x-agentfox-mode: enforce
x-agentfox-latency-ms: 4.97
```

`x-agentfox-verdict` is what happened. `x-agentfox-effective-verdict` is what the policy would have
done regardless of mode (`applied` and `would-be` repeat the two under clearer names). In observe
mode they differ, and that gap is the thing you watch before turning enforcement on.

A proxied call held for a person returns HTTP **428**, which the OpenAI and Anthropic SDKs raise as
an error rather than parse as a completion. The body carries the `approval_id`; once it is approved,
send the same request again with the header `X-AgentFox-Approval: <id>`.

Useful request headers: `X-AgentFox-Agent` (the agent slug), `X-AgentFox-Session` (correlates calls
into one execution path), `X-AgentFox-Intent` (the declared task, used by intent-based containment),
and `X-AgentFox-Trust` (a JSON map marking message indices as untrusted, e.g.
`{"2":"retrieved"}`). Full surface: [Appendix C](architecture/api-spec.md).

**If you are in Python instead**, the whole of 5d is one line at your entry point:

```python
import agentfox
agentfox.auto()
```

Besides the request and the response text, it checks every tool call in the response before the
response is handed back, with argument provenance read from the conversation. What it covers, what
it raises and what it does not patch:
[the product tour](product-tour.md#python--one-line).

**What this proves:** enforcement is a property of the deployment, not of your codebase, and an
undeclared agent is refused before anybody writes a rule about it.

### 5e. A token for the control-plane API

The `/v1/guard/*` endpoints above need no credential (a key, when sent, must verify, and it decides
which workspace the call is recorded in). The control-plane API under `/api` does:

```bash
agentfox admin users create you@example.com --role owner   # once, on a fresh database
agentfox admin auth issue you@example.com --name "ci"
curl -H "Authorization: Bearer nom_api_..." http://localhost:8080/api/findings
```

`auth issue` mints a token for an operator that already exists, and a database created by
`agentfox init` alone has none: `admin users create` makes the first one without loading any demo
data (`agentfox admin seed` also creates operators, but writes demo agents and traffic too). Token
values are shown once, hashed at rest with argon2id, and carry an
expiry. `agentfox admin auth status` tells you whether this deployment is actually requiring them: in a
development environment it accepts an `X-AgentFox-User` header instead, which is fine locally and
unacceptable anywhere else.

Outside development, `/api` requires a token, and the gateway refuses to start until two secrets
have real values. Which two, and how to make them:
[the product tour's self-hosting section](product-tour.md#self-hosting).

---

## Step 6. Read what it found (10 minutes)

```bash
agentfox findings
agentfox findings --severity high
agentfox doctor
```

`findings` is the list of things a person should look at: shadow agents, agents with no accountable
owner, stale identities, every detection that led to a block or a redaction, and every tool call a
permission, provenance or blast-radius rule stopped, titled by what actually stopped it, e.g.
`support-triage tried to email.send with data that came from a web page (contained)`.

For the one-page version to forward to whoever signs off, run `agentfox report` (add
`--format html --out summary.html` for a file). With AgentFox Enterprise, the same page is
`SUMMARY.md` at the top of every `agentfox report evidence` zip.

`doctor` is the more interesting one, because it grades the configuration rather than the traffic:

```
  ✓    database            reachable — 5 agents, 11 traces
  ✓    enforcement         17 of 22 decisions enforced
  i    authentication      DEVELOPMENT auth is active (environment=development, auth_mode=auto):
                           an /api request with no token acts as the user named in
                           X-AgentFox-User, or as admin@example.com (an owner, once seeded) —
                           anyone who can reach this port is any user they name. Fine locally,
                           unacceptable anywhere else.
  ✓    secrets             development: the published default secrets are allowed here, and
                           refused (the gateway will not start) in any other environment
  ✓    containment         11 of 16 tools can act, 16 capability grants — an action outside
                           these is refused whether or not a detector fires
  ✓    detectors           5 running: injection.heuristic, pii.native, safety.lexicon,
                           schema.json, secrets.native
  i    detector failure    fail-open: a detector that times out lets the request through and
                           records the gap
  !    findings            18 open — run `agentfox findings`
```

Trimmed. Note the two lines marked `i` that are not about your agents at all. AgentFox tells you that it
fails open, and that your auth mode is a development mode, rather than leaving you to discover it. On a
local development setup these are information (`i`): they are the defaults of a first run. In staging
or production the same lines are warnings (`!`), or a failed check (`✗`) for development auth.

Three commands worth knowing here:

```bash
agentfox agents lineage my-agent     # what this agent reaches: its blast radius
agentfox permit list my-agent        # what it may do; anything not listed is refused
agentfox report verify               # re-derive the tamper-evident chain; exits 1 if broken
```

**What this proves:** the platform reports its own gaps, including the ones that are inconvenient
for it.

---

## Step 7. Test before you trust (10 minutes)

Three things worth running before you turn enforcement on.

```bash
agentfox test redteam my-agent
```

Fires the built-in adversarial probe suite (mapped to OWASP LLM Top 10 and MITRE ATLAS) at this
deployment's actual capability grants and policy bindings, and reports what got through. It
includes benign controls, so a configuration that blocks everything scores badly rather than
perfectly. The probes are a dry run: their tool calls are evaluated without writing decisions, so
they never appear in your findings or in what `policy simulate` replays. An attack stopped only by a rule
that still watches is shown as `would block (watching)` and counted on its own line, because
live traffic would get through; an agent name that does not exist is refused with the list of
those that do. It exits 1 when any attack
got through (`--allow-escapes` to report without failing). Read the result as configuration
regression testing: it tells you whether *this deployment* got weaker, and it is not a robustness
certificate.

```bash
agentfox policy validate candidate.yaml
agentfox policy simulate --file candidate.yaml
```

`validate` parses, lints and compiles a policy file without saving it, and exits 1 on a parse error
or a critical or high lint finding, such as a rule that can never fire. `simulate` replays the
traffic already recorded in your database against the candidate, so you can see what a rule change
would have done before it does it; it exits non-zero when the change would newly block production
traffic.

If you have an eval suite, `agentfox test gate <suite>` exits 1 on a regression or on any case that
errored, and is meant to run in CI.

**What this proves:** you can measure the change before you make it, against your own recorded
traffic.

---

## Step 8. Turn enforcement on (5 minutes)

When the findings look right and `effective_verdict` is no longer surprising you:

```bash
agentfox policy list                    # current mode of each pack
agentfox policy effective --agent my-agent   # what is in force, and where each rule came from
agentfox policy enforce baseline        # the one step that starts blocking model traffic
```

This is the only command in this guide that changes what reaches production. `tool-containment`
was already enforcing from step 2. Promoting `baseline` adds the detector-driven rules on top.

Saving and promoting are separate steps. A policy version you save in the dashboard's editor (or
with `POST /api/policies`) is stored next to the live one and changes nothing in force until it is
promoted. Over HTTP, promoting a version to enforce needs a recorded simulation of exactly that
version first, and is refused with a 409 otherwise.

If it goes wrong, `agentfox policy observe baseline` demotes it again, and
`agentfox agents quarantine <agent> --reason "..."` stops one agent without touching the rest. Both
are reversible and both are audited.

**What this proves:** enforcement is one deliberate, reversible, audited step, taken after you have
seen what it will do.

---

## Where to go next

- **[docs/README.md](README.md)**: what every other document in this directory is for.
- **[The product tour](product-tour.md)**: every other place the policy binds (LangGraph, the
  OpenAI Agents SDK, a LiteLLM proxy, Vapi, Retell, Copilot Studio, AgentCore, MCP, coding agents).
- **[Appendix C](architecture/api-spec.md)**: the full API, including the routes the dashboard
  itself uses. There is no privileged back-channel.
- **[The benchmarking white paper](evaluation/benchmarking-whitepaper.md)**: how each capability was measured,
  including where it loses.
- **[How to read our numbers](evaluation/evidence-standards.md)**: read this before quoting any benchmark
  result anywhere.
- **[`plugins/claude-code/`](../plugins/claude-code/README.md)**: drive all of the above from Claude Code or another coding
  agent, if you would rather not learn the command list.
- **[Appendix E](architecture/threat-model.md)**: the threat model, including threats to AgentFox
  itself.

Two things to keep in mind as you go further. Containment is exactly as good as the declarations
behind it: a destructive tool declared `read` will not be treated as destructive by anything
downstream, which is why `agentfox doctor` grades your declarations and `agentfox scan` finds the
tools you have not declared. And compliance mappings ship as engineering drafts, labelled
`DRAFT — UNVERIFIED / NOT LEGAL ADVICE` inside evidence packages, until a qualified reviewer signs
them off.
